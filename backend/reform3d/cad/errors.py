"""Structured errors for the Stage 3 CAD engine.

Stage 3 must never return a broken file. When something cannot be produced safely it
raises one of these instead, and the API turns it into a structured JSON error.
"""

from __future__ import annotations

from typing import Dict, List, Optional


class CADError(Exception):
    """Base class for every Stage 3 failure."""

    #: Machine-readable code for the API response.
    code = "cad_error"

    def __init__(
        self,
        message: str,
        *,
        template: Optional[str] = None,
        details: Optional[Dict[str, object]] = None,
        hints: Optional[List[str]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.template = template
        self.details: Dict[str, object] = details or {}
        self.hints: List[str] = hints or []

    def to_dict(self) -> Dict[str, object]:
        """Serialisable form for the API response body."""
        return {
            "code": self.code,
            "message": self.message,
            "template": self.template,
            "details": self.details,
            "hints": self.hints,
        }


class CADParameterError(CADError):
    """A dimension is missing, non-numeric, non-positive or physically impossible."""

    code = "invalid_parameters"

    @classmethod
    def from_fields(
        cls,
        template: str,
        problems: List[str],
        *,
        parameters: Optional[Dict[str, object]] = None,
    ) -> "CADParameterError":
        """Build a parameter error from a list of human-readable problems."""
        return cls(
            "These dimensions cannot produce a printable part: " + "; ".join(problems),
            template=template,
            details={"problems": problems, "parameters": parameters or {}},
            hints=[
                "Check the numbers are in millimetres and greater than zero.",
                "Walls and flexures must be at least the configured minimum "
                "(MIN_WALL_THICKNESS_MM).",
                "A bore must be larger than the clearance so material remains.",
            ],
        )


class CADGenerationError(CADError):
    """The geometry operation itself failed (boolean op, fillet, loft, ...)."""

    code = "generation_failed"


class CADValidationError(CADError):
    """The generated geometry was not watertight / manifold and was discarded."""

    code = "invalid_geometry"


class UnsupportedTemplateError(CADError):
    """The archetype has no generator (for example ``other``)."""

    code = "unsupported_template"


__all__ = [
    "CADError",
    "CADGenerationError",
    "CADParameterError",
    "CADValidationError",
    "UnsupportedTemplateError",
]
