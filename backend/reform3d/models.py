"""Shared data models for the ReForm3D pipeline.

These are the artefacts handed between stages (see ``design.md`` section 1.1):

* Stage 1 produces :class:`ImageSlot` / :class:`CaptureSession`.
* Stage 1.5 produces :class:`SlotEnhancement` / :class:`EnhancementOutcome`.
* Stage 2 produces ``DiagnosisResult`` (defined in :mod:`reform3d.schema`).
* Stage 3 produces :class:`MeshResult`.
* Stage 4 will consume :class:`MeshResult` and produce :class:`PrintReadyFile`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from reform3d.schema import DiagnosisResult, MeasurementItem, SuggestedTemplate


def _utc_now() -> datetime:
    """Timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class ShotKind(str, Enum):
    """The three required capture slots."""

    straight_on = "straight_on"
    angled = "angled"
    mating_surface = "mating_surface"


#: User-facing instruction text for each slot. Kept next to the enum so the frontend
#: and the API can never drift apart.
SHOT_INSTRUCTIONS: Dict[str, Dict[str, str]] = {
    ShotKind.straight_on.value: {
        "title": "Straight-on shot",
        "body": (
            "Point the camera directly at the broken part, square to it - do not tilt. "
            "Use even lighting and a plain background if you can."
        ),
        "tip": "Fill the frame with the part, but leave room for the reference object.",
    },
    ShotKind.angled.value: {
        "title": "Second angle (45-90 degrees)",
        "body": (
            "Move around the object so you are looking at it from a noticeably "
            "different angle - about 45 to 90 degrees from the first shot."
        ),
        "tip": "This is what tells us whether the part is round, square or tapered.",
    },
    ShotKind.mating_surface.value: {
        "title": "Close-up of the mating surface",
        "body": (
            "Get close to the exact surface that has to fit - the shaft, the bore, the "
            "cap, the clip. Lay your reference object (coin, card or ruler) FLAT "
            "AGAINST the part, in the same plane - never floating in front of it."
        ),
        "tip": (
            "This photo sets the scale, so the reference must be crisp and fully "
            "visible in the frame."
        ),
    },
}

#: Which slot is expected to carry the marked reference bounding box.
REFERENCE_BOX_SHOT = ShotKind.mating_surface.value


class ReferenceType(str, Enum):
    """Which scale reference the user placed in the photo."""

    coin = "coin"
    credit_card = "credit_card"
    ruler = "ruler"
    other = "other"


#: Known real-world size (mm) for each preset. ``COIN_DIAMETER_MM`` in .env is the
#: documented override point for non-US coins.
REFERENCE_KNOWN_DIMENSIONS: Dict[str, float] = {
    ReferenceType.coin.value: 24.26,
    ReferenceType.credit_card.value: 85.60,
    ReferenceType.ruler.value: 100.0,
}

#: Human-readable label + description for the reference picker.
REFERENCE_DESCRIPTIONS: Dict[str, Dict[str, str]] = {
    ReferenceType.coin.value: {
        "label": "Coin",
        "detail": "US quarter, 24.26 mm across the widest point.",
    },
    ReferenceType.credit_card.value: {
        "label": "Credit / bank card",
        "detail": "Standard ISO card, 85.60 mm along the long edge.",
    },
    ReferenceType.ruler.value: {
        "label": "Ruler",
        "detail": "Measure across a full 100 mm of the printed scale.",
    },
    ReferenceType.other.value: {
        "label": "Something else",
        "detail": "Any object whose size you know - type the size in mm below.",
    },
}


class ReferenceBox(BaseModel):
    """Normalised bounding box the user drew over the reference object.

    Coordinates are 0-1 fractions of the image, origin top-left, so the box survives
    client-side resizing and Stage 1.5 re-scaling.
    """

    x_min: float = Field(ge=0.0, le=1.0)
    y_min: float = Field(ge=0.0, le=1.0)
    x_max: float = Field(ge=0.0, le=1.0)
    y_max: float = Field(ge=0.0, le=1.0)

    @property
    def width(self) -> float:
        """Normalised width of the box."""
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        """Normalised height of the box."""
        return self.y_max - self.y_min

    @property
    def area(self) -> float:
        """Normalised area of the box (0-1)."""
        return self.width * self.height

    def is_degenerate(self, min_side: float = 0.02) -> bool:
        """True when the box is inverted or too small to be a real marking."""
        return self.width < min_side or self.height < min_side

    def to_pixel_box(self, image_width: int, image_height: int) -> "PixelBox":
        """Convert to integer pixel bounds, clipped to the image."""
        return PixelBox(
            left=max(0, min(image_width, int(round(self.x_min * image_width)))),
            top=max(0, min(image_height, int(round(self.y_min * image_height)))),
            right=max(0, min(image_width, int(round(self.x_max * image_width)))),
            bottom=max(0, min(image_height, int(round(self.y_max * image_height)))),
        )


class PixelBox(BaseModel):
    """Integer pixel bounds, already clipped to the image."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def area(self) -> int:
        return self.width * self.height


class ReferenceSpec(BaseModel):
    """The scale anchor for a capture session."""

    reference_type: ReferenceType
    known_dimension_mm: float = Field(gt=0.0)
    dimension_label: str = Field(
        default="longest edge",
        description="What the known dimension measures, for display to the user.",
    )
    bbox: Optional[ReferenceBox] = Field(
        default=None,
        description="User-marked bounding box around the reference object.",
    )
    bbox_shot: Optional[ShotKind] = Field(
        default=None, description="Which photo carries the marked reference box."
    )


class QualityVerdict(BaseModel):
    """Stage 1 pre-enhancement quality check result for one raw image."""

    passed: bool
    blur_score: float = Field(description="Variance of the Laplacian; higher is sharper.")
    mean_luminance: float = Field(description="Mean greyscale level, 0-255.")
    clipped_pixel_ratio: float = Field(description="Fraction of pixels at 0 or 255.")
    underexposed_pixel_ratio: float = Field(description="Fraction of pixels below 15.")
    reference_detected: bool = Field(
        description="Heuristic: does a reference-like shape appear in the frame?"
    )
    reference_box_coverage: float = Field(
        default=0.0,
        description="How much of the marked reference box a detected shape covers.",
    )
    needs_enhancement: bool = Field(
        default=False,
        description="True when exposure is outside the window (drives CLAHE in 1.5).",
    )
    warnings: List[str] = Field(default_factory=list)
    overridden: bool = Field(
        default=False,
        description="True when the user chose 'use anyway' despite warnings.",
    )

    @property
    def has_warnings(self) -> bool:
        """True when the check found anything worth telling the user about."""
        return bool(self.warnings)


class ImageSlot(BaseModel):
    """One captured photo plus its Stage 1 metadata."""

    kind: ShotKind
    raw_filename: str
    raw_path: Path
    original_filename: Optional[str] = None
    quality: Optional[QualityVerdict] = None
    captured_at: datetime = Field(default_factory=_utc_now)


class CaptureSession(BaseModel):
    """Everything Stage 1 collects, handed forward to Stage 1.5 and Stage 2."""

    session_id: str
    created_at: datetime = Field(default_factory=_utc_now)
    reference: Optional[ReferenceSpec] = None
    slots: Dict[str, ImageSlot] = Field(default_factory=dict)

    @property
    def missing_slots(self) -> List[str]:
        """Shot kinds that have not been captured yet."""
        return [kind.value for kind in ShotKind if kind.value not in self.slots]

    @property
    def ready_for_diagnosis(self) -> bool:
        """True when the minimum inputs for Stage 1.5 / Stage 2 are present."""
        if self.missing_slots or self.reference is None:
            return False
        bbox = self.reference.bbox
        return bbox is not None and not bbox.is_degenerate()

    def get_slot(self, kind: ShotKind) -> Optional[ImageSlot]:
        """Look up a captured slot by kind."""
        return self.slots.get(kind.value)
    def add_slot(self, slot: ImageSlot) -> None:
        """Add or replace a captured slot."""
        self.slots[slot.kind.value] = slot



# --- Stage 1.5 ------------------------------------------------------------------


class SlotEnhancement(BaseModel):
    """Result of enhancing a single slot."""

    kind: ShotKind
    raw_path: Path
    enhanced_path: Optional[Path] = None
    lighting_corrected: bool = False
    background_removed: bool = False
    fallback_applied: bool = False
    skip_reason: Optional[str] = None
    reference_retained_ratio: Optional[float] = None
    notes: List[str] = Field(default_factory=list)

    @property
    def effective_path(self) -> Path:
        """The image the VLM should see: enhanced when available, else raw."""
        return self.enhanced_path or self.raw_path


class EnhancementOutcome(BaseModel):
    """Result of the whole Stage 1.5 pass."""

    enhancement_skipped: bool = False
    skip_reason: Optional[str] = None
    items: List[SlotEnhancement] = Field(default_factory=list)
    user_messages: List[str] = Field(default_factory=list)

    def for_kind(self, kind: ShotKind) -> Optional[SlotEnhancement]:
        """Look up one slot's enhancement result."""
        for item in self.items:
            if item.kind == kind:
                return item
        return None


# --- Stage 3 / 4 ---------------------------------------------------------------


class MeshResult(BaseModel):
    """Stage 3 output: a real, verified, downloadable solid."""

    success: bool
    template: SuggestedTemplate
    stl_filename: str
    step_filename: Optional[str] = None
    stl_path: Optional[Path] = None
    step_path: Optional[Path] = None
    watertight: bool = False
    volume_mm3: float = 0.0
    bounding_box_mm: Dict[str, float] = Field(default_factory=dict)
    parameters: Dict[str, float] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


class PrintReadyFile(BaseModel):
    """Stage 4 stub output. Placeholder only - see :mod:`reform3d.stage4_stub`."""

    stl_filename: str
    step_filename: Optional[str] = None
    status: str = "stub_not_implemented"
    recommended_orientation: Optional[str] = None
    recommended_layer_height_mm: Optional[float] = None
    supports_required: Optional[bool] = None
    slicer_metadata: Dict[str, str] = Field(default_factory=dict)
    message: str = ""


__all__ = [
    "CaptureSession",
    "DiagnosisResult",
    "EnhancementOutcome",
    "ImageSlot",
    "MeasurementItem",
    "MeshResult",
    "PixelBox",
    "PrintReadyFile",
    "QualityVerdict",
    "REFERENCE_BOX_SHOT",
    "REFERENCE_DESCRIPTIONS",
    "REFERENCE_KNOWN_DIMENSIONS",
    "ReferenceBox",
    "ReferenceSpec",
    "ReferenceType",
    "SHOT_INSTRUCTIONS",
    "ShotKind",
    "SlotEnhancement",
]
