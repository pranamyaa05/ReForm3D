"""Stage 1 - pre-enhancement quality checks on raw captures.

Three deterministic checks run on every raw image *before* any enhancement:

* **Blur** - variance of the Laplacian. Sharp images have lots of high-frequency
  energy, so a low variance means the photo is soft.
* **Exposure** - mean luminance plus the fraction of pixels that are fully clipped or
  near-black. This also decides whether Stage 1.5 needs to apply CLAHE.
* **Reference visibility** - a contour-shape heuristic that looks for something
  matching the chosen reference object (round for a coin, a card-shaped quad for a
  credit card, an elongated quad for a ruler) inside the user-marked bounding box.

Every check is advisory: a failure produces a warning and the user may choose
"use anyway". Nothing here ever hard-blocks the flow.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple, Union

import cv2
import numpy as np

from reform3d.config import Settings, get_settings
from reform3d.models import (
    PixelBox,
    QualityVerdict,
    ReferenceBox,
    ReferenceSpec,
    ReferenceType,
)

logger = logging.getLogger(__name__)

#: Greyscale level below which a pixel counts as "near black".
DARK_PIXEL_LEVEL = 15

#: Kernel size for the Laplacian operator used in the blur metric.
_LAPLACIAN_KERNEL = 3

#: Long-edge / short-edge ratio of an ISO/IEC 7810 ID-1 card (85.60 / 53.98).
_CARD_ASPECT_RATIO = 85.60 / 53.98

#: Aspect ratio at or above which a quad is treated as "ruler-like".
_RULER_ASPECT_RATIO = 3.0

#: Tolerances for the shape heuristics.
_ASPECT_TOLERANCE = 0.45
_MIN_CIRCULARITY = 0.62

#: Fraction of the region-of-interest area below which a contour is treated as a speck.
_MIN_CONTOUR_AREA_FRACTION = 0.02


class ImageReadError(RuntimeError):
    """Raised when an image cannot be decoded."""


# --- Loading ----------------------------------------------------------------------


def load_image_grey(image: Union[bytes, Path, str, np.ndarray]) -> np.ndarray:
    """Load an image as a single-channel ``uint8`` array.

    Accepts raw bytes, a filesystem path or an already-decoded array.
    """
    if isinstance(image, np.ndarray):
        if image.ndim == 2:
            return image
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    buffer = _read_bytes(image)
    decoded = cv2.imdecode(np.frombuffer(buffer, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded is None:
        raise ImageReadError(
            "Could not decode the image. Check that the file is a valid JPEG or PNG."
        )
    return cv2.cvtColor(decoded, cv2.COLOR_BGR2GRAY)


def _read_bytes(image: Union[bytes, Path, str]) -> bytes:
    """Read image bytes from memory or from disk."""
    if isinstance(image, bytes):
        return image
    path = Path(image)
    if not path.is_file():
        raise ImageReadError(f"Image file not found: {path}")
    return path.read_bytes()


# --- Reference-visibility heuristic -----------------------------------------------


def _reference_shape_score(contour: np.ndarray, reference_type: str) -> float:
    """Score how much a contour looks like the chosen reference object (0-1).

    Round objects are scored by circularity; rectangular ones by how close their
    bounding quad's aspect ratio is to the expected ratio.
    """
    area = cv2.contourArea(contour)
    if area <= 0:
        return 0.0

    perimeter = cv2.arcLength(contour, True)
    if perimeter <= 0:
        return 0.0

    if reference_type == ReferenceType.coin.value:
        circularity = float(4.0 * np.pi * area / (perimeter * perimeter))
        if circularity < _MIN_CIRCULARITY:
            return 0.0
        return float(
            np.clip((circularity - _MIN_CIRCULARITY) / (1.0 - _MIN_CIRCULARITY), 0.0, 1.0)
        )

    # Rectangular references: approximate the contour with a quad.
    approx = cv2.approxPolyDP(contour, 0.03 * perimeter, True)
    if len(approx) != 4:
        return 0.0

    rect = cv2.minAreaRect(contour)
    (_, _), (w, h), _ = rect
    if w <= 0 or h <= 0:
        return 0.0
    long_edge, short_edge = max(w, h), min(w, h)
    aspect = long_edge / short_edge

    if reference_type == ReferenceType.credit_card.value:
        expected = _CARD_ASPECT_RATIO
    else:
        # Ruler or "other": accept anything clearly elongated, otherwise a near-square
        # strong quad also counts as a plausible known-size object.
        expected = aspect if aspect >= _RULER_ASPECT_RATIO else 1.0

    deviation = abs(aspect - expected) / expected
    likeness = float(np.clip(1.0 - deviation / _ASPECT_TOLERANCE, 0.0, 1.0))
    return likeness


def _select_roi(
    grey: np.ndarray,
    reference_box: Optional[ReferenceBox],
) -> Tuple[np.ndarray, Optional[PixelBox]]:
    """Crop to the marked reference box when there is one, else use the whole frame."""
    if reference_box is None or reference_box.is_degenerate():
        return grey, None

    height, width = grey.shape[:2]
    pixel_box = reference_box.to_pixel_box(width, height)
    if pixel_box.width < 8 or pixel_box.height < 8:
        return grey, None
    return grey[pixel_box.top : pixel_box.bottom, pixel_box.left : pixel_box.right], pixel_box


def reference_visibility(
    grey: np.ndarray,
    reference: Optional[ReferenceSpec],
    min_coverage: float,
) -> Tuple[bool, float]:
    """Return ``(detected, coverage)`` for the chosen reference object.

    ``coverage`` is the fraction of the marked box (or of the frame, when no box was
    marked) explained by the best-matching contour. When the user has marked a box we
    additionally require the detected shape to *overlap* that box, so a coin sitting
    somewhere else in the frame does not count.
    """
    reference_type = (
        reference.reference_type.value if reference is not None else ReferenceType.coin.value
    )
    reference_box = reference.bbox if reference is not None else None

    roi, pixel_box = _select_roi(grey, reference_box)
    if roi.size == 0:
        return False, 0.0

    edges = cv2.Canny(roi, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return False, 0.0

    roi_area = float(roi.shape[0] * roi.shape[1])
    best_coverage = 0.0
    best_likeness = 0.0

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < _MIN_CONTOUR_AREA_FRACTION * roi_area:
            # Ignore specks: a reference object should be a meaningful chunk of the frame.
            continue
        coverage = float(min(1.0, area / roi_area))
        likeness = _reference_shape_score(contour, reference_type)
        if likeness <= 0.0:
            continue
        if likeness * coverage > best_likeness * best_coverage:
            best_likeness = likeness
            best_coverage = coverage

    if pixel_box is not None and best_coverage > 0.0:
        # Detected inside the marked box: the box is the region of interest, so the
        # coverage already describes overlap.
        return best_coverage >= min_coverage, best_coverage

    return best_coverage >= min_coverage, best_coverage


# --- Individual metrics -----------------------------------------------------------


def blur_score(grey: np.ndarray) -> float:
    """Return the variance of the Laplacian - higher means sharper."""
    if grey.size == 0:
        return 0.0
    laplacian = cv2.Laplacian(grey, cv2.CV_64F, ksize=_LAPLACIAN_KERNEL)
    return float(laplacian.var())


def exposure_metrics(grey: np.ndarray) -> Tuple[float, float, float]:
    """Return ``(mean_luminance, clipped_ratio, underexposed_ratio)``."""
    if grey.size == 0:
        return 0.0, 1.0, 1.0
    total = float(grey.size)
    mean_luminance = float(grey.mean())
    clipped = float(np.count_nonzero((grey <= 1) | (grey >= 254))) / total
    underexposed = float(np.count_nonzero(grey < DARK_PIXEL_LEVEL)) / total
    return mean_luminance, clipped, underexposed


# --- Composite check --------------------------------------------------------------


def analyse_capture(
    image: Union[bytes, Path, str, np.ndarray],
    reference: Optional[ReferenceSpec] = None,
    *,
    settings: Optional[Settings] = None,
    overridden: bool = False,
) -> QualityVerdict:
    """Run the full Stage 1 quality gate on one raw image.

    ``overridden`` records that the user already chose "use anyway"; the verdict is
    still computed and reported so the decision stays auditable, but the caller can
    treat ``passed`` or ``overridden`` as "may proceed".

    Raises :class:`ImageReadError` when the image cannot be decoded.
    """
    config = settings or get_settings()
    grey = load_image_grey(image)

    blur = blur_score(grey)
    mean_luminance, clipped_ratio, underexposed_ratio = exposure_metrics(grey)
    detected, coverage = reference_visibility(
        grey, reference, config.min_reference_box_coverage
    )

    warnings: List[str] = []

    if blur < config.blur_threshold:
        warnings.append(
            f"The photo looks blurry (sharpness {blur:.0f}, needs {config.blur_threshold:.0f}). "
            "Hold the phone steadier and tap to focus, then shoot again."
        )

    too_dark = mean_luminance < config.min_mean_luminance
    too_bright = mean_luminance > config.max_mean_luminance
    if too_dark:
        warnings.append(
            f"The photo is dark (brightness {mean_luminance:.0f} of 255). "
            "Move somewhere with more even light."
        )
    elif too_bright:
        warnings.append(
            f"The photo is very bright (brightness {mean_luminance:.0f} of 255). "
            "Avoid pointing a lamp or window directly at the part."
        )

    if clipped_ratio > config.max_clipped_pixel_ratio:
        warnings.append(
            f"{clipped_ratio * 100:.1f}% of the photo is pure black or pure white, which "
            "hides detail. Soften the lighting and try again."
        )

    if underexposed_ratio > config.max_underexposed_pixel_ratio:
        warnings.append(
            f"{underexposed_ratio * 100:.0f}% of the photo is very dark. "
            "More even lighting will make the measurements much more reliable."
        )

    if not detected:
        warnings.append(
            "We could not clearly see your reference object "
            f"(coin / card / ruler) - it needs to cover at least "
            f"{config.min_reference_box_coverage * 100:.0f}% of the area you marked. "
            "Keep it flat against the part and inside the frame."
        )

    needs_enhancement = (
        mean_luminance < config.min_mean_luminance - config.exposure_enhancement_margin
        or mean_luminance
        > config.max_mean_luminance + config.exposure_enhancement_margin
        or clipped_ratio > config.max_clipped_pixel_ratio
        or underexposed_ratio > config.max_underexposed_pixel_ratio
    )

    return QualityVerdict(
        passed=not warnings,
        blur_score=blur,
        mean_luminance=mean_luminance,
        clipped_pixel_ratio=clipped_ratio,
        underexposed_pixel_ratio=underexposed_ratio,
        reference_detected=detected,
        reference_box_coverage=coverage,
        needs_enhancement=boolean_needs_enhancement(needs_enhancement, too_dark, too_bright),
        warnings=warnings,
        overridden=overridden,
    )


def boolean_needs_enhancement(raw_flag: bool, too_dark: bool, too_bright: bool) -> bool:
    """Small helper kept separate so tests can assert the decision independently."""
    return bool(raw_flag or too_dark or too_bright)


__all__ = [
    "ImageReadError",
    "analyse_capture",
    "blur_score",
    "exposure_metrics",
    "load_image_grey",
    "reference_visibility",
]
