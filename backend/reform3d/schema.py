"""Stage 2 structured-output schema and the *single source of truth* for the
template / parameter contract that Stage 3 must satisfy.

Three things live here and nowhere else:

1. :class:`SuggestedTemplate` - the archetype enum. Its values match the CadQuery
   generator names exactly, so a VLM response maps deterministically onto a call.
2. :class:`FeatureName` - the union of every legal ``feature_name``. Because it is an
   enum baked into the Gemini response schema, the model cannot invent a parameter.
3. :data:`TEMPLATE_FEATURES` - the *per-template* required/optional parameter sets.
   This is what makes the mapping conditional on ``suggested_template``: a name can be
   globally legal and still wrong for the chosen template. That is rejected here and
   again, authoritatively, in :mod:`reform3d.mapping`.

An import-time assertion guarantees every name referenced by :data:`TEMPLATE_FEATURES`
is a member of :class:`FeatureName`; renaming a generator parameter without updating
this module fails immediately rather than at request time.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet, List

from pydantic import BaseModel, Field, model_validator


class SuggestedTemplate(str, Enum):
    """Archetype enum. Values must equal the CAD generator names exactly."""

    friction_fit_collar = "friction_fit_collar"
    snap_clip_bracket = "snap_clip_bracket"
    lever_cap = "lever_cap"
    wing_adapter = "wing_adapter"
    other = "other"


class InteractionPrimitive(str, Enum):
    """How the user physically interacts with the object."""

    ROTATE = "ROTATE"
    GRIP = "GRIP"
    CLIP = "CLIP"
    BRACE = "BRACE"
    PUSH = "PUSH"
    OTHER = "OTHER"


class MeasurementConfidence(str, Enum):
    """Self-reported confidence for a single measurement."""

    low = "low"
    medium = "medium"
    high = "high"


class FeatureName(str, Enum):
    """Union of every legal measurement feature name.

    Members are exactly the CAD generator parameter names, minus ``clearance_mm``
    (which is a print setting and is never requested from the model).
    """

    # friction_fit_collar
    bore_diameter_mm = "bore_diameter_mm"
    wall_thickness_mm = "wall_thickness_mm"
    height_mm = "height_mm"

    # snap_clip_bracket
    clip_width_mm = "clip_width_mm"
    clip_depth_mm = "clip_depth_mm"
    flex_thickness_mm = "flex_thickness_mm"

    # lever_cap
    cap_diameter_mm = "cap_diameter_mm"
    lever_length_mm = "lever_length_mm"
    cap_height_mm = "cap_height_mm"

    # wing_adapter
    base_diameter_mm = "base_diameter_mm"
    wing_span_mm = "wing_span_mm"
    base_height_mm = "base_height_mm"


#: Templates that Stage 3 can actually build.
GENERATABLE_TEMPLATES: FrozenSet[SuggestedTemplate] = frozenset(
    {
        SuggestedTemplate.friction_fit_collar,
        SuggestedTemplate.snap_clip_bracket,
        SuggestedTemplate.lever_cap,
        SuggestedTemplate.wing_adapter,
    }
)

#: Upper bound on measurements accepted from a single response.
MAX_MEASUREMENTS = 12


class TemplateFeatureSpec(BaseModel):
    """The measurement contract for one archetype.

    ``required`` names must all be supplied before the CAD generator may be called.
    ``optional`` names may be supplied to override a generator default. Anything else
    is a contract violation.
    """

    model_config = {"frozen": True}

    required: FrozenSet[str]
    optional: FrozenSet[str] = frozenset()

    @property
    def allowed(self) -> FrozenSet[str]:
        """Every name this template accepts."""
        return self.required | self.optional


#: The per-template parameter contract. Keys are :class:`SuggestedTemplate` values.
TEMPLATE_FEATURES: Dict[str, TemplateFeatureSpec] = {
    SuggestedTemplate.friction_fit_collar.value: TemplateFeatureSpec(
        required=frozenset(
            {
                FeatureName.bore_diameter_mm.value,
                FeatureName.wall_thickness_mm.value,
                FeatureName.height_mm.value,
            }
        ),
    ),
    SuggestedTemplate.snap_clip_bracket.value: TemplateFeatureSpec(
        required=frozenset(
            {
                FeatureName.clip_width_mm.value,
                FeatureName.clip_depth_mm.value,
                FeatureName.flex_thickness_mm.value,
            }
        ),
    ),
    SuggestedTemplate.lever_cap.value: TemplateFeatureSpec(
        required=frozenset(
            {
                FeatureName.cap_diameter_mm.value,
                FeatureName.lever_length_mm.value,
            }
        ),
        optional=frozenset(
            {
                FeatureName.cap_height_mm.value,
                FeatureName.wall_thickness_mm.value,
            }
        ),
    ),
    SuggestedTemplate.wing_adapter.value: TemplateFeatureSpec(
        required=frozenset(
            {
                FeatureName.base_diameter_mm.value,
                FeatureName.wing_span_mm.value,
            }
        ),
        optional=frozenset(
            {
                FeatureName.base_height_mm.value,
                FeatureName.wall_thickness_mm.value,
            }
        ),
    ),
}

#: Generator defaults for optional parameters. Kept beside the contract so the UI can
#: show the value that will be used when the user leaves a field blank.
TEMPLATE_OPTIONAL_DEFAULTS: Dict[str, Dict[str, float]] = {
    SuggestedTemplate.lever_cap.value: {
        FeatureName.cap_height_mm.value: 15.0,
        FeatureName.wall_thickness_mm.value: 2.5,
    },
    SuggestedTemplate.wing_adapter.value: {
        FeatureName.base_height_mm.value: 15.0,
        FeatureName.wall_thickness_mm.value: 2.5,
    },
}

# --- Guard rails ------------------------------------------------------------------
_ALL_CONTRACT_NAMES: FrozenSet[str] = frozenset(
    name for spec in TEMPLATE_FEATURES.values() for name in spec.allowed
)

_UNKNOWN_CONTRACT_NAMES = _ALL_CONTRACT_NAMES - {member.value for member in FeatureName}
if _UNKNOWN_CONTRACT_NAMES:  # pragma: no cover - configuration-error guard
    raise RuntimeError(
        "TEMPLATE_FEATURES references feature names that are not members of "
        f"FeatureName: {sorted(_UNKNOWN_CONTRACT_NAMES)}. Rename them in "
        "reform3d/schema.py and in the matching CAD generator together."
    )

for _template_value in GENERATABLE_TEMPLATES:  # pragma: no cover - guard
    if _template_value.value not in TEMPLATE_FEATURES:
        raise RuntimeError(
            f"Template '{_template_value.value}' is generatable but has no "
            "TEMPLATE_FEATURES entry."
        )


def required_feature_names(template: str) -> FrozenSet[str]:
    """Required feature names for ``template`` (empty set when unknown)."""
    spec = TEMPLATE_FEATURES.get(template)
    return spec.required if spec else frozenset()


def allowed_feature_names(template: str) -> FrozenSet[str]:
    """Every feature name ``template`` accepts (empty set when unknown)."""
    spec = TEMPLATE_FEATURES.get(template)
    return spec.allowed if spec else frozenset()


# --- Stage 2 response schema ------------------------------------------------------


class MeasurementItem(BaseModel):
    """One estimated dimension, anchored to the reference object's known size."""

    feature_name: FeatureName = Field(
        description=(
            "Which dimension this is. Must be one of the legal parameter names for "
            "the chosen suggested_template; never invent a name."
        )
    )
    estimated_value_mm: float = Field(
        description=(
            "Estimated real-world size in millimetres, computed using the reference "
            "object's known dimension as the scale anchor."
        )
    )
    confidence: MeasurementConfidence = Field(
        description="How confident you are in this specific number."
    )


class DiagnosisResult(BaseModel):
    """Stage 2's structured output. This is also Stage 3's input type."""

    object_identified: str = Field(
        description="Short plain-language name of the object / broken part."
    )
    interaction_primitive: InteractionPrimitive = Field(
        description="How the user physically interacts with the object."
    )
    failure_diagnosis: str = Field(
        description="Plain-language reason the object is broken or hard to use."
    )
    suggested_template: SuggestedTemplate = Field(
        description=(
            "Which parametric attachment archetype best fixes this. Use 'other' when "
            "none of the four archetypes genuinely fit."
        )
    )
    measurements: List[MeasurementItem] = Field(
        default_factory=list,
        max_length=MAX_MEASUREMENTS,
        description=(
            "Estimated dimensions. Use ONLY the legal parameter names for "
            "suggested_template."
        ),
    )
    notes: str = Field(
        default="",
        description="Anything ambiguous, or caveats about the estimates.",
    )
    requires_manual_confirmation: bool = Field(
        default=False,
        description=(
            "Set true when unsure about any measurement, or about whether the "
            "reference object was clearly detected."
        ),
    )

    @model_validator(mode="after")
    def _features_match_template(self) -> "DiagnosisResult":
        """Conditional check: feature names must be legal *for this template*.

        A name can exist in :class:`FeatureName` and still be wrong for the selected
        archetype. Raising here surfaces the problem as a validation error so the app
        routes the user into the manual-confirmation form instead of passing a
        mismatched parameter set to CadQuery.
        """
        template = self.suggested_template.value
        if template == SuggestedTemplate.other.value:
            return self

        allowed = allowed_feature_names(template)
        unexpected = sorted(
            {item.feature_name.value for item in self.measurements} - allowed
        )
        if unexpected:
            raise ValueError(
                "measurements contain feature names that are not valid for "
                f"'{template}': {', '.join(unexpected)}. "
                f"Legal names for this template: {', '.join(sorted(allowed))}."
            )
        return self


def template_prompt_block() -> str:
    """Model-readable description of the template/parameter contract.

    Injected into the Stage 2 prompt so the model is told explicitly which parameter
    names are legal for each archetype. The deterministic checks in
    :mod:`reform3d.mapping` remain the authority.
    """
    lines: List[str] = []
    for template in sorted(GENERATABLE_TEMPLATES, key=lambda t: t.value):
        spec = TEMPLATE_FEATURES[template.value]
        required = ", ".join(sorted(spec.required))
        optional = ", ".join(sorted(spec.optional)) or "none"
        lines.append(f"- {template.value}: required [{required}]; optional [{optional}]")
    lines.append(
        f"- {SuggestedTemplate.other.value}: no generator exists. Use only when no "
        "archetype fits; return no measurements and explain why in notes."
    )
    return "\n".join(lines)


__all__ = [
    "DiagnosisResult",
    "FeatureName",
    "GENERATABLE_TEMPLATES",
    "InteractionPrimitive",
    "MAX_MEASUREMENTS",
    "MeasurementConfidence",
    "MeasurementItem",
    "SuggestedTemplate",
    "TEMPLATE_FEATURES",
    "TEMPLATE_OPTIONAL_DEFAULTS",
    "TemplateFeatureSpec",
    "allowed_feature_names",
    "required_feature_names",
    "template_prompt_block",
]

