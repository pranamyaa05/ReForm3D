"""Stage 4 stub: slicer orientation and print preparation interface.

Out of scope for Phase 1. This stub preserves the typed pipeline contract so that
Stage 4 can be implemented in a subsequent phase without modifying Stages 1 to 3.
"""

from __future__ import annotations

import logging
from typing import Optional

from reform3d.models import MeshResult, PrintReadyFile

logger = logging.getLogger(__name__)


def finalize_for_printing(
    mesh: MeshResult,
    *,
    printer_profile: Optional[str] = None,
) -> PrintReadyFile:
    """Stage 4 entry point placeholder.

    Args:
        mesh: Stage 3 output pointing at verified watertight STL/STEP files.
        printer_profile: Optional printer profile identifier (e.g. 'prusa_mk4').

    Returns:
        A :class:`~reform3d.models.PrintReadyFile` with status ``stub_not_implemented``.
    """
    logger.info(
        "Stage 4 stub invoked for %s (printer_profile=%s). No slicer processing applied.",
        mesh.stl_filename,
        printer_profile,
    )
    return PrintReadyFile(
        stl_filename=mesh.stl_filename,
        step_filename=mesh.step_filename,
        status="stub_not_implemented",
        recommended_orientation="flat_on_largest_face",
        recommended_layer_height_mm=0.2,
        supports_required=False,
        slicer_metadata={
            "template": mesh.template.value,
            "volume_mm3": str(mesh.volume_mm3),
            "stage4_status": "stub",
        },
        message=(
            "Stage 4 (automated slicer orientation and G-code export) is not implemented in "
            "Phase 1. The watertight STL and editable STEP files are ready for manual import "
            "into your slicer (e.g. PrusaSlicer, Bambu Studio, Cura)."
        ),
    )


__all__ = [
    "finalize_for_printing",
]
