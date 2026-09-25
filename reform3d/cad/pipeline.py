"""Stage 3 entry point: :func:`generate_repair_geometry`.

Takes a Stage 2 :class:`~reform3d.schema.DiagnosisResult`, validates the measurements
against the template's parameter contract, dispatches to the matching CadQuery
generator, exports STL (and STEP), and refuses to hand back anything that fails the
watertightness check.

Two independent safety barriers live here:

* the **confirmation gate** - low-confidence or malformed measurements cannot reach a
  generator unless the caller explicitly states ``user_confirmed=True``;
* the **printability barrier** - the exported STL is reloaded from disk and verified,
  and a decorated attempt that fails is retried once without cosmetic edge treatment.

The CAD path contains no AI and no randomness, so identical confirmed measurements
always produce identical geometry.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import cadquery as cq

from reform3d.cad.errors import (
    CADError,
    CADGenerationError,
    CADValidationError,
    UnsupportedTemplateError,
)
from reform3d.cad.generators import get_generator
from reform3d.cad.validator import MeshReport, validate_exported_stl, validate_solid
from reform3d.config import Settings, get_settings
from reform3d.mapping import CadArgumentValidation, validate_and_map_cad_args
from reform3d.models import MeshResult
from reform3d.schema import (
    DiagnosisResult,
    TEMPLATE_OPTIONAL_DEFAULTS,
    SuggestedTemplate,
)

logger = logging.getLogger(__name__)


class ConfirmationRequiredError(CADError):
    """Raised when generation is attempted with unconfirmed measurements."""

    code = "confirmation_required"


def generate_repair_geometry(
    diagnosis: DiagnosisResult,
    *,
    user_confirmed: bool = False,
    clearance_mm: Optional[float] = None,
    settings: Optional[Settings] = None,
    output_dir: Optional[Path] = None,
    basename: Optional[str] = None,
) -> MeshResult:
    """Generate, verify and export the attachment described by ``diagnosis``.

    Args:
        diagnosis: Stage 2 output (the same object the user edits in the form).
        user_confirmed: Must be ``True`` when the measurements require review. The API
            only sets this after the user has actually confirmed the form.
        clearance_mm: Override the configured default clearance.
        settings: Optional settings override (used by tests).
        output_dir: Where to write STL/STEP. Defaults to the configured output dir.
        basename: Explicit file stem. Defaults to ``<template>_<utc timestamp>``.

    Returns:
        A :class:`~reform3d.models.MeshResult` pointing at verified files.

    Raises:
        CADError: (or a subclass) for every failure mode - bad parameters, unsupported
            template, unconfirmed measurements, or geometry that fails validation.
    """
    config = settings or get_settings()

    validation = validate_and_map_cad_args(
        diagnosis.suggested_template.value,
        list(diagnosis.measurements),
        clearance_mm,
        min_dimension_mm=config.min_dimension_mm,
        max_dimension_mm=config.max_dimension_mm,
    )

    if not validation.is_valid:
        # ``other``/unknown templates and schema mismatches land here. Nothing is
        # generated and no file is written.
        _raise_for_validation(validation)
    if validation.requires_confirmation and not user_confirmed:
        raise ConfirmationRequiredError(
            "These measurements need to be reviewed before anything is built. "
            + (validation.error_message or "Confirm the numbers and try again."),
            template=validation.template,
            details=validation.model_dump(),
            hints=[
                "Check the flagged measurements in the confirmation form.",
                "Re-submit with user_confirmed set to true once you are happy with them.",
            ],
        )

    generator = get_generator(validation.template)
    if generator is None:
        raise UnsupportedTemplateError(
            f"There is no CAD generator for '{validation.template}'.",
            template=validation.template,
        )

    params = _with_optional_defaults(validation.template, validation.mapped_args or {})
    target_dir = Path(output_dir or config.output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = basename or _default_basename(validation.template)

    shape, solid_problems = _build(generator, params, config, decorative=True)
    if solid_problems:
        raise _solid_error(validation.template, params, solid_problems)

    mesh, stl_path, step_path = _export_and_verify(
        shape, target_dir, stem, config, validation.template, params
    )

    warnings: List[str] = []
    if mesh is None:
        # Decorated geometry did not tessellate watertight. Retry with the plain
        # version: same dimensions, no cosmetic edge rounding.
        logger.warning(
            "STL failed validation for %s; retrying without decorative edge treatment",
            validation.template,
        )
        shape, solid_problems = _build(generator, params, config, decorative=False)
        if solid_problems:
            raise _solid_error(validation.template, params, solid_problems)

        mesh, stl_path, step_path = _export_and_verify(
            shape, target_dir, stem, config, validation.template, params
        )
        if mesh is not None:
            warnings.append(
                "The rounded-edge version of this part did not produce a printable "
                "mesh, so it was regenerated with simple sharp edges. The dimensions "
                "are unchanged."
            )

    if mesh is None or stl_path is None:
        raise CADValidationError(
            "The part could not be produced as a printable mesh, even after retrying "
            "with simple geometry.",
            template=validation.template,
            details={"parameters": params},
        )

    return MeshResult(
        success=True,
        template=diagnosis.suggested_template,
        stl_filename=stl_path.name,
        step_filename=step_path.name if step_path else None,
        stl_path=stl_path,
        step_path=step_path,
        watertight=mesh.is_watertight,
        volume_mm3=round(mesh.volume_mm3, 3),
        bounding_box_mm=mesh.bounding_box_mm,
        parameters={key: float(value) for key, value in params.items()},
        warnings=warnings,
    )

# --- Internal helpers -------------------------------------------------------------


def _raise_for_validation(validation: CadArgumentValidation) -> None:
    """Turn a failed validation into the right structured CAD error."""
    if validation.template == SuggestedTemplate.other.value or not validation.template:
        raise UnsupportedTemplateError(
            validation.error_message or "No supported attachment type was matched.",
            template=validation.template,
            details=validation.model_dump(),
            hints=[
                "Choose one of the supported archetypes manually.",
                "A human-designed part is the right answer when no archetype fits.",
            ],
        )
    raise CADError(
        validation.error_message or "The measurements are not usable.",
        template=validation.template,
        details=validation.model_dump(),
    )


def _build(
    generator: Callable,
    params: dict,
    config: Settings,
    *,
    decorative: bool,
) -> Tuple[object, List[str]]:
    """Run one generator attempt and return ``(shape, solid_problems)``."""
    try:
        shape = generator(**params, settings=config, decorative=decorative)
    except CADError:
        raise
    except Exception as exc:  # noqa: BLE001 - unexpected generator failure
        raise CADGenerationError(
            f"The generator failed: {exc}",
            details={"parameters": params},
        ) from exc

    report = validate_solid(shape)
    return shape, list(report.problems)


def _solid_error(
    template: str,
    params: dict,
    problems: List[str],
) -> CADValidationError:
    """Build the structured error for a solid that failed the pre-export check."""
    return CADValidationError(
        "The generated shape is not a valid single watertight solid: "
        + " ".join(problems),
        template=template,
        details={"problems": problems, "parameters": params},
    )


def _export_and_verify(
    shape,
    target_dir: Path,
    stem: str,
    config: Settings,
    template: str,
    params: dict,
) -> Tuple[Optional[MeshReport], Optional[Path], Optional[Path]]:
    """Export STL + STEP and run the post-export STL watertightness check.

    Returns ``(mesh_report, stl_path, step_path)``. ``mesh_report`` is ``None`` when the
    exported STL failed validation - the caller decides whether to retry. STEP is
    best-effort: if it cannot be written, the STL is still returned with a warning.
    """
    stl_path = target_dir / f"{stem}.stl"
    step_path = target_dir / f"{stem}.step"

    try:
        cq.exporters.export(
            shape,
            str(stl_path),
            cq.exporters.ExportTypes.STL,
            tolerance=config.stl_tessellation_tolerance_mm,
            angularTolerance=config.stl_angular_tolerance_rad,
        )
    except Exception as exc:  # noqa: BLE001 - exporter failure modes
        logger.warning("STL export failed for %s: %s", stem, exc)
        return None, None, None

    try:
        cq.exporters.export(shape, str(step_path), cq.exporters.ExportTypes.STEP)
    except Exception as exc:  # noqa: BLE001 - STEP is the editable bonus, not a must
        logger.warning("STEP export failed for %s (STL is still available): %s", stem, exc)
        step_path = None

    try:
        report = validate_exported_stl(stl_path)
    except CADValidationError as exc:
        logger.warning("Exported STL failed validation: %s", exc.message)
        return None, stl_path, step_path

    return report, stl_path, step_path


def _with_optional_defaults(template: str, mapped_args: dict) -> dict:
    """Fill in generator defaults for optional parameters the user did not supply."""
    params = dict(mapped_args)
    for name, value in TEMPLATE_OPTIONAL_DEFAULTS.get(template, {}).items():
        params.setdefault(name, value)
    return params


def _default_basename(template: str) -> str:
    """Deterministic-ish file stem: template plus a UTC timestamp."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    return f"{template}_{stamp}"


__all__ = [
    "ConfirmationRequiredError",
    "generate_repair_geometry",
]

