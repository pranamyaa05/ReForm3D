"""Stage 1.5 - deterministic lighting / background enhancement.

Hard constraint: this stage may fix exposure and remove background clutter, and it may
do **nothing else**. It never crops, never resizes, never warps perspective and never
runs a generative model, so nothing can be hallucinated into or out of the image.

Two deterministic operations are available:

* :func:`correct_lighting` - CLAHE on the L channel in Lab space. A tone curve only;
  pixel positions are untouched.
* :func:`remove_background` - rembg / U^2-Net segmentation, producing an RGBA image
  whose background is genuinely transparent (removed pixels, not invented ones).

After segmentation the user-marked reference bounding box is inspected in the alpha
mask. If the reference object was clipped or erased, the enhanced image is discarded
for that slot and the pipeline falls back to the raw (or CLAHE-only) image, with a
message explaining why. Nothing is ever silently dropped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

import cv2
import numpy as np

from reform3d.config import Settings, get_settings
from reform3d.models import (
    CaptureSession,
    EnhancementOutcome,
    ImageSlot,
    REFERENCE_BOX_SHOT,
    ReferenceBox,
    ShotKind,
    SlotEnhancement,
)

logger = logging.getLogger(__name__)

#: Cached rembg sessions, keyed by model name (model load is the expensive part).
_REMBG_SESSIONS: dict = {}

#: Suffix used for enhanced images, so raw files are never overwritten.
ENHANCED_SUFFIX = "_enhanced.png"


class EnhancementError(RuntimeError):
    """Raised when an enhancement operation cannot be performed at all."""


@dataclass
class ImageEnhancementResult:
    """In-memory result of enhancing a single image."""

    image: np.ndarray
    lighting_corrected: bool = False
    background_removed: bool = False
    fallback_applied: bool = False
    reference_retained_ratio: Optional[float] = None
    notes: List[str] = field(default_factory=list)


# --- Toggle -----------------------------------------------------------------------


def enhancement_enabled(settings: Optional[Settings] = None) -> bool:
    """True when Stage 1.5 should run at all."""
    return (settings or get_settings()).enable_image_enhancement


# --- Deterministic operations -----------------------------------------------------


def correct_lighting(bgr: np.ndarray, settings: Optional[Settings] = None) -> np.ndarray:
    """Apply CLAHE to the L channel in Lab space.

    This is a tone curve only. Every pixel stays in place, so geometry, scale and
    perspective are untouched. Alpha, when present, is preserved verbatim.
    """
    config = settings or get_settings()
    if bgr.size == 0:
        return bgr

    has_alpha = bgr.ndim == 3 and bgr.shape[2] == 4
    color = bgr[:, :, :3] if has_alpha else bgr

    lab = cv2.cvtColor(color, cv2.COLOR_BGR2LAB)
    lightness, a_channel, b_channel = cv2.split(lab)

    clahe = cv2.createCLAHE(
        clipLimit=config.clahe_clip_limit,
        tileGridSize=(config.clahe_tile_grid_size, config.clahe_tile_grid_size),
    )
    merged = cv2.merge((clahe.apply(lightness), a_channel, b_channel))
    corrected = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)

    if has_alpha:
        return np.dstack([corrected, bgr[:, :, 3]])
    return corrected


def _get_rembg_session(model_name: str) -> Any:
    """Return a cached rembg session, importing rembg lazily.

    Importing rembg pulls in onnxruntime, which is slow; doing it lazily keeps this
    module importable (and unit-testable) when enhancement is switched off.
    """
    if model_name in _REMBG_SESSIONS:
        return _REMBG_SESSIONS[model_name]

    try:
        from rembg import new_session
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise EnhancementError(
            "Background removal needs the 'rembg' package, which is not installed. "
            'Install it with: pip install "rembg[cpu]" (see SETUP.md), or set '
            "ENABLE_IMAGE_ENHANCEMENT=false."
        ) from exc

    logger.info("Loading rembg model '%s' (first use downloads it)", model_name)
    session = new_session(model_name)
    _REMBG_SESSIONS[model_name] = session
    return session


def remove_background(
    bgr: np.ndarray,
    settings: Optional[Settings] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Segment the subject out and return ``(rgba_image, alpha_mask)``.

    The returned image has the same width and height as the input, with background
    pixels made fully transparent. No pixels are moved or generated.
    """
    config = settings or get_settings()
    if bgr.size == 0:
        raise EnhancementError("Cannot segment an empty image.")

    session = _get_rembg_session(config.rembg_model)

    try:
        from rembg import remove
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise EnhancementError(
            "Background removal needs the 'rembg' package. "
            'Install with: pip install "rembg[cpu]" or disable enhancement.'
        ) from exc

    color = bgr[:, :, :3] if bgr.ndim == 3 and bgr.shape[2] == 4 else bgr
    ok, encoded = cv2.imencode(".png", color)
    if not ok:  # pragma: no cover - cv2 encode failure is exceptional
        raise EnhancementError("Failed to encode the image for background removal.")

    try:
        cutout_bytes = remove(encoded.tobytes(), session=session, post_process_mask=True)
    except Exception as exc:  # pragma: no cover - defensive around model runtime
        raise EnhancementError(f"Background removal failed: {exc}") from exc

    rgba = cv2.imdecode(np.frombuffer(cutout_bytes, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if rgba is None or rgba.ndim != 3 or rgba.shape[2] != 4:  # pragma: no cover
        raise EnhancementError("Background removal returned an unexpected image format.")

    if rgba.shape[:2] != color.shape[:2]:  # pragma: no cover - scale guard
        raise EnhancementError(
            "Background removal changed the image dimensions; refusing to use it "
            "because that would alter scale."
        )

    return rgba, rgba[:, :, 3]


# --- Reference-retention gate -----------------------------------------------------


def reference_retention_ratio(
    alpha_mask: np.ndarray,
    reference_box: Optional[ReferenceBox],
) -> float:
    """Mean alpha inside the user-marked reference box, as a 0-1 ratio.

    ``1.0`` means every pixel the user marked as "this is my reference object" is
    still present after segmentation; a low value means the reference was clipped or
    erased. When no box was marked we return ``1.0`` and let the caller decide, because
    there is nothing to check against.
    """
    if reference_box is None or reference_box.is_degenerate():
        return 1.0
    if alpha_mask.size == 0:
        return 0.0

    height, width = alpha_mask.shape[:2]
    pixel_box = reference_box.to_pixel_box(width, height)
    if pixel_box.width < 2 or pixel_box.height < 2:
        return 1.0

    region = alpha_mask[pixel_box.top : pixel_box.bottom, pixel_box.left : pixel_box.right]
    if region.size == 0:
        return 1.0
    return float(region.mean()) / 255.0


def clip_is_reference_safe(
    alpha_mask: np.ndarray,
    reference_box: Optional[ReferenceBox],
    settings: Optional[Settings] = None,
) -> Tuple[bool, float]:
    """Return ``(safe, ratio)`` for the reference box against a segmentation mask."""
    config = settings or get_settings()
    ratio = reference_retention_ratio(alpha_mask, reference_box)
    return ratio >= config.reference_retention_min_ratio, ratio


# --- Orchestration ----------------------------------------------------------------


def enhance_image(
    bgr: np.ndarray,
    *,
    reference_box: Optional[ReferenceBox] = None,
    apply_lighting: bool = True,
    apply_background: bool = True,
    settings: Optional[Settings] = None,
) -> ImageEnhancementResult:
    """Enhance one image, honouring the retention gate.

    Order of operations: lighting first (so segmentation sees a normalised image),
    then background removal, then the reference-retention check. If the check fails the
    background-removed result is thrown away and the CLAHE-only (or raw) image is
    returned with ``fallback_applied=True``.
    """
    config = settings or get_settings()
    notes: List[str] = []

    base = bgr
    lighting_corrected = False
    if apply_lighting:
        base = correct_lighting(base, config)
        lighting_corrected = True

    if not apply_background:
        return ImageEnhancementResult(
            image=base,
            lighting_corrected=lighting_corrected,
            background_removed=False,
            notes=notes,
        )

    rgba, alpha = remove_background(base, config)
    safe, ratio = clip_is_reference_safe(alpha, reference_box, config)

    if not safe:
        notes.append(
            "Background removal would have cut off or hidden your reference object, so "
            "the cleaned-up version was discarded for this photo. The original image is "
            "being used instead - scale calibration stays valid."
        )
        logger.warning(
            "Reference retention %.2f below threshold %.2f - falling back to "
            "unenhanced image",
            ratio,
            config.reference_retention_min_ratio,
        )
        return ImageEnhancementResult(
            image=base,
            lighting_corrected=lighting_corrected,
            background_removed=False,
            fallback_applied=True,
            reference_retained_ratio=ratio,
            notes=notes,
        )

    return ImageEnhancementResult(
        image=rgba,
        lighting_corrected=lighting_corrected,
        background_removed=True,
        reference_retained_ratio=ratio,
        notes=notes,
    )


def enhanced_path_for(raw_path: Path) -> Path:
    """Where the enhanced version of ``raw_path`` is written."""
    return raw_path.with_name(f"{raw_path.stem}{ENHANCED_SUFFIX}")


def enhance_session(
    session: CaptureSession,
    *,
    settings: Optional[Settings] = None,
) -> EnhancementOutcome:
    """Run Stage 1.5 over every captured slot.

    Never raises for per-image problems: an individual slot that cannot be enhanced is
    recorded with ``skip_reason`` and its raw path is used instead. The whole stage is
    skipped when ``ENABLE_IMAGE_ENHANCEMENT=false``.
    """
    config = settings or get_settings()

    if not config.enable_image_enhancement:
        return EnhancementOutcome(
            enhancement_skipped=True,
            skip_reason="Image enhancement is switched off (ENABLE_IMAGE_ENHANCEMENT=false).",
            items=[
                _passthrough_item(slot, "Enhancement disabled by configuration.")
                for slot in _ordered_slots(session)
            ],
            user_messages=[
                "Image cleanup is switched off, so the raw photos are being used. "
                "Measurements may be a little less accurate in poor lighting."
            ],
        )

    reference_box = session.reference.bbox if session.reference else None
    outcome = EnhancementOutcome()

    for slot in _ordered_slots(session):
        outcome.items.append(
            _enhance_slot(slot, session, reference_box, config, outcome.user_messages)
        )

    return outcome


def _ordered_slots(session: CaptureSession):
    """Captured slots in the canonical shot order."""
    for kind in ShotKind:
        slot = session.get_slot(kind)
        if slot is not None:
            yield slot


def _passthrough_item(slot: ImageSlot, reason: str) -> SlotEnhancement:
    """A SlotEnhancement that simply points at the raw image."""
    return SlotEnhancement(
        kind=slot.kind,
        raw_path=slot.raw_path,
        enhanced_path=None,
        skip_reason=reason,
        notes=[reason],
    )


def _should_correct_lighting(slot: ImageSlot) -> bool:
    """CLAHE only for images the Stage 1 gate flagged as poorly lit."""
    if slot.quality is None:
        return False
    return bool(slot.quality.needs_enhancement)


def _enhance_slot(
    slot: ImageSlot,
    session: CaptureSession,
    reference_box: Optional[ReferenceBox],
    config: Settings,
    messages: List[str],
) -> SlotEnhancement:
    """Enhance one slot, writing the result beside the raw file."""
    target_box_shot = (
        session.reference.bbox_shot.value
        if (session.reference is not None and session.reference.bbox_shot is not None)
        else REFERENCE_BOX_SHOT
    )
    holds_reference = slot.kind.value == target_box_shot
    box_for_gate = reference_box if holds_reference else None

    raw = cv2.imread(str(slot.raw_path), cv2.IMREAD_COLOR)
    if raw is None:
        reason = f"Could not read {slot.raw_path.name}; the original will be used."
        messages.append(reason)
        return _passthrough_item(slot, reason)

    try:
        result = enhance_image(
            raw,
            reference_box=box_for_gate,
            apply_lighting=_should_correct_lighting(slot),
            apply_background=True,
            settings=config,
        )
    except EnhancementError as exc:
        reason = f"{exc} The original photo will be used for this shot."
        logger.warning("Enhancement skipped for %s: %s", slot.raw_path.name, exc)
        messages.append(reason)
        return _passthrough_item(slot, reason)

    output_path = enhanced_path_for(slot.raw_path)
    if not cv2.imwrite(str(output_path), result.image):
        reason = (
            f"Could not write the enhanced image for {slot.raw_path.name}; "
            "the original will be used."
        )
        logger.warning(reason)
        messages.append(reason)
        return _passthrough_item(slot, reason)

    for note in result.notes:
        messages.append(note)
    if result.lighting_corrected and not result.background_removed:
        messages.append(
            f"Brightness was evened out on {slot.kind.value.replace('_', ' ')}."
        )

    return SlotEnhancement(
        kind=slot.kind,
        raw_path=slot.raw_path,
        enhanced_path=output_path,
        lighting_corrected=result.lighting_corrected,
        background_removed=result.background_removed,
        fallback_applied=result.fallback_applied,
        reference_retained_ratio=result.reference_retained_ratio,
        notes=result.notes,
    )


__all__ = [
    "ENHANCED_SUFFIX",
    "EnhancementError",
    "ImageEnhancementResult",
    "clip_is_reference_safe",
    "correct_lighting",
    "enhance_image",
    "enhance_session",
    "enhanced_path_for",
    "enhancement_enabled",
    "reference_retention_ratio",
    "remove_background",
]
