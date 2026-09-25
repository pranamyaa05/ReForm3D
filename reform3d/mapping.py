"""Stage 2 -> Stage 3 gate: :func:`validate_and_map_cad_args`.

This module answers two *separate* questions, and never conflates them:

* **``is_valid``** - is the measurement set well-formed against the selected
  template's parameter contract (no missing required names, no names that belong to a
  different template, no non-positive values)?
* **``requires_confirmation``** - may we proceed *without a human*? This is true when
  the data is malformed **or** when any measurement is low-confidence **or** when the
  template is unsupported (``other`` / unknown).

Because these are different signals, a low-confidence measurement set can be perfectly
well-formed (``is_valid=True``) and still be blocked from generating until the user
confirms. The CAD endpoint enforces exactly that.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Protocol

from pydantic import BaseModel, Field

from reform3d.schema import (
    SuggestedTemplate,
    TEMPLATE_FEATURES,
    allowed_feature_names,
    required_feature_names,
)

#: Message shown when the VLM could not map the object onto a supported archetype.
UNSUPPORTED_TEMPLATE_MESSAGE = (
    "No supported attachment type was matched for this object. "
    "ReForm3D can generate a friction-fit collar, a snap-clip bracket, a lever cap or "
    "a wing adapter - nothing was selected, so no CAD has been generated. "
    "Pick one of those four archetypes below and enter its dimensions to continue."
)

#: Message shown when the template is a name we do not know at all.
UNKNOWN_TEMPLATE_MESSAGE = (
    "Unrecognised attachment template '{template}'. No CAD has been generated. "
    "Choose one of: {choices}."
)


class CadArgumentValidation(BaseModel):
    """Outcome of validating a measurement set against a template contract."""

    is_valid: bool = Field(
        description="True when the measurement set matches the template contract."
    )
    requires_confirmation: bool = Field(
        description=(
            "True when a human must review/confirm before generation: schema mismatch, "
            "unsupported template, or at least one low-confidence measurement."
        )
    )
    template: str = Field(description="Template the measurements were checked against.")
    summary: str = Field(default="", description="One-line human-readable verdict.")
    error_message: Optional[str] = Field(
        default=None, description="Detailed explanation when something is wrong."
    )
    missing_fields: List[str] = Field(
        default_factory=list,
        description="Required names for this template that were not supplied at all.",
    )
    unexpected_fields: List[str] = Field(
        default_factory=list,
        description="Supplied names that are not legal for this template.",
    )
    invalid_value_fields: List[str] = Field(
        default_factory=list,
        description="Supplied legal names whose value is <= 0.",
    )
    low_confidence_fields: List[str] = Field(
        default_factory=list,
        description="Supplied legal names the model was unsure about.",
    )
    out_of_range_fields: List[str] = Field(
        default_factory=list,
        description="Supplied legal names outside the configured plausible range.",
    )
    mapped_args: Optional[Dict[str, float]] = Field(
        default=None,
        description=(
            "Generator keyword arguments, including clearance_mm. Populated whenever "
            "is_valid is True - including on the low-confidence-only path."
        ),
    )

    @property
    def blocked(self) -> bool:
        """True when generation must not proceed at all."""
        return not self.is_valid

    @property
    def problem_fields(self) -> List[str]:
        """Every field name the UI should highlight as needing attention."""
        return sorted(
            set(
                self.missing_fields
                + self.unexpected_fields
                + [entry.split(" ")[0] for entry in self.invalid_value_fields]
                + [entry.split(" ")[0] for entry in self.out_of_range_fields]
                + self.low_confidence_fields
            )
        )


# --- Small adapters so the gate works with model objects or plain dicts -----------


class MeasurementLike(Protocol):
    """Anything exposing ``feature_name``, ``estimated_value_mm`` and ``confidence``."""

    feature_name: object
    estimated_value_mm: float
    confidence: object


def _feature_name_of(item: object) -> str:
    """Extract a feature name from a Pydantic model, an enum or a plain mapping."""
    raw = _get(item, "feature_name")
    if raw is None:
        return ""
    value = getattr(raw, "value", raw)
    return str(value).strip()


def _value_of(item: object) -> Optional[float]:
    """Extract the numeric millimetre value, or ``None`` when unusable."""
    raw = _get(item, "estimated_value_mm")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _confidence_of(item: object) -> str:
    """Extract the confidence label as a lowercase string."""
    raw = _get(item, "confidence")
    if raw is None:
        return ""
    value = getattr(raw, "value", raw)
    return str(value).strip().lower()


def _get(item: object, key: str) -> object:
    """Read ``key`` from a mapping-like or attribute-like object."""
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def validate_and_map_cad_args(
    suggested_template: str,
    measurements: List[object],
    clearance_mm: Optional[float] = None,
    *,
    min_dimension_mm: float = 0.5,
    max_dimension_mm: float = 500.0,
) -> CadArgumentValidation:
    """Validate ``measurements`` against ``suggested_template``'s contract.

    Never calls a generator. Returns a :class:`CadArgumentValidation` describing
    whether generation may proceed, what is wrong if not, and (when valid) the exact
    keyword arguments to hand to the CadQuery generator.

    Order of checks:

    1. ``other`` / unknown template -> invalid, requires confirmation, stop here.
    2. Partition supplied names into legal-for-template vs unexpected.
    3. ``<= 0`` values -> ``invalid_value_fields`` (never also ``missing_fields``).
    4. Plausible-range violations -> ``out_of_range_fields``.
    5. Required names never supplied -> ``missing_fields``.
    6. ``low`` confidence -> ``low_confidence_fields`` and ``requires_confirmation``.
    7. On success inject ``clearance_mm`` into ``mapped_args`` on *both* the clean and
       the low-confidence-only paths, so callers see one consistent shape.
    """
    template = (suggested_template or "").strip()
    choices = ", ".join(sorted(TEMPLATE_FEATURES))

    # --- 1. Unsupported / unknown template -----------------------------------
    if template == SuggestedTemplate.other.value:
        return CadArgumentValidation(
            is_valid=False,
            requires_confirmation=True,
            template=template,
            summary="No supported attachment type matched - generation skipped.",
            error_message=UNSUPPORTED_TEMPLATE_MESSAGE,
        )

    spec = TEMPLATE_FEATURES.get(template)
    if spec is None:
        return CadArgumentValidation(
            is_valid=False,
            requires_confirmation=True,
            template=template,
            summary="Unrecognised template - generation skipped.",
            error_message=UNKNOWN_TEMPLATE_MESSAGE.format(
                template=template, choices=choices
            ),
        )

    required = required_feature_names(template)
    allowed = allowed_feature_names(template)

    # --- 2. Partition the supplied measurements ------------------------------
    provided: Dict[str, float] = {}
    seen: Dict[str, int] = {}
    duplicates: List[str] = []
    unexpected: List[str] = []
    invalid_values: List[str] = []
    out_of_range: List[str] = []
    low_confidence: List[str] = []

    for item in measurements:
        name = _feature_name_of(item)
        if not name:
            continue

        seen[name] = seen.get(name, 0) + 1
        if seen[name] == 2:
            duplicates.append(name)

        if name not in allowed:
            # A legal-as-such name that belongs to a different template, or a name
            # the model invented. Either way it must not reach a generator.
            unexpected.append(name)
            if _confidence_of(item) == "low":
                low_confidence.append(name)
            continue

        value = _value_of(item)
        if value is None or value <= 0:
            invalid_values.append(f"{name} ({value}mm <= 0)")
        elif value < min_dimension_mm or value > max_dimension_mm:
            out_of_range.append(
                f"{name} ({value}mm outside {min_dimension_mm}-{max_dimension_mm}mm)"
            )
            # Unusable as-is, so it does not count as a supplied value.
        else:
            provided[name] = float(value)

        if _confidence_of(item) == "low":
            low_confidence.append(name)

    # --- 3/4/5. Contract violations ------------------------------------------
    # A name that WAS supplied with a non-positive value appears only in
    # invalid_values; it is deliberately never also listed as missing.
    missing = sorted(name for name in required if name not in seen)

    has_schema_mismatch = bool(
        missing or unexpected or invalid_values or out_of_range or duplicates
    )
    is_valid = not has_schema_mismatch
    requires_confirmation = has_schema_mismatch or bool(low_confidence)

    reasons: List[str] = []
    if missing:
        reasons.append(f"Missing required parameters: {', '.join(missing)}")
    if unexpected:
        reasons.append(
            f"Parameters that are not valid for '{template}': "
            f"{', '.join(sorted(set(unexpected)))}"
        )
    if invalid_values:
        reasons.append(
            f"Dimensions must be greater than zero: {', '.join(invalid_values)}"
        )
    if out_of_range:
        reasons.append(
            f"Dimensions outside the plausible range: {', '.join(out_of_range)}"
        )
    if duplicates:
        reasons.append(f"Duplicate parameters: {', '.join(sorted(set(duplicates)))}")
    if low_confidence:
        reasons.append(
            f"Low confidence - please check these numbers: "
            f"{', '.join(sorted(set(low_confidence)))}"
        )

    # --- 6/7. Map arguments; clearance always injected on the valid path ------
    mapped_args: Optional[Dict[str, float]] = None
    if is_valid:
        mapped_args = dict(provided)
        mapped_args["clearance_mm"] = resolve_clearance(clearance_mm)

    if not reasons:
        summary = f"Measurements match the '{template}' contract."
    elif is_valid:
        summary = f"'{template}' contract matched, but user confirmation is required."
    else:
        summary = f"'{template}' contract not satisfied - generation blocked."

    return CadArgumentValidation(
        is_valid=is_valid,
        requires_confirmation=requires_confirmation,
        template=template,
        summary=summary,
        error_message="; ".join(reasons) if reasons else None,
        missing_fields=missing,
        unexpected_fields=sorted(set(unexpected)),
        invalid_value_fields=invalid_values,
        low_confidence_fields=sorted(set(low_confidence)),
        out_of_range_fields=out_of_range,
        mapped_args=mapped_args,
    )


def resolve_clearance(clearance_mm: Optional[float]) -> float:
    """Return the configured default clearance, clamped into its safe range.

    Imported lazily so ``reform3d.cad`` can use this module without pulling the
    settings object in eagerly at import time.
    """
    from reform3d.config import get_settings

    return get_settings().clamp_clearance(clearance_mm)


__all__ = [
    "CadArgumentValidation",
    "MeasurementLike",
    "UNKNOWN_TEMPLATE_MESSAGE",
    "UNSUPPORTED_TEMPLATE_MESSAGE",
    "resolve_clearance",
    "validate_and_map_cad_args",
]
