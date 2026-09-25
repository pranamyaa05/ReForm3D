"""Stage 3 CAD package: parametric generators, validation, and export."""

from reform3d.cad.errors import (
    CADError,
    CADGenerationError,
    CADParameterError,
    CADValidationError,
    UnsupportedTemplateError,
)
from reform3d.cad.generators import (
    friction_fit_collar,
    get_generator,
    lever_cap,
    snap_clip_bracket,
    wing_adapter,
)
from reform3d.cad.pipeline import ConfirmationRequiredError, generate_repair_geometry
from reform3d.cad.validator import (
    MeshReport,
    SolidReport,
    validate_exported_stl,
    validate_solid,
)

__all__ = [
    "CADError",
    "CADGenerationError",
    "CADParameterError",
    "CADValidationError",
    "ConfirmationRequiredError",
    "MeshReport",
    "SolidReport",
    "UnsupportedTemplateError",
    "friction_fit_collar",
    "generate_repair_geometry",
    "get_generator",
    "lever_cap",
    "snap_clip_bracket",
    "validate_exported_stl",
    "validate_solid",
    "wing_adapter",
]
