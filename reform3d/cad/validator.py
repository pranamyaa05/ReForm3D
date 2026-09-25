"""Stage 3 validation: two independent layers, because they catch different bugs.

1. :func:`validate_solid` - checks the CadQuery/OpenCascade solid *before* export. It
   catches boolean-operation failures, multi-body results and non-positive volume.
2. :func:`validate_exported_stl` - reloads the **actual STL file that was written to
   disk** and checks the tessellated triangle mesh. This is the authority on
   watertightness, because a mathematically valid solid can still tessellate with gaps
   or duplicate triangles. Anything the slicer will see must pass this.

A part is only returned to the user when both layers pass. Otherwise a structured
:class:`reform3d.cad.errors.CADValidationError` is raised and no file is offered.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import cadquery as cq
import numpy as np

from reform3d.cad.errors import CADValidationError

logger = logging.getLogger(__name__)


@dataclass
class SolidReport:
    """Outcome of the pre-export solid check."""

    is_valid: bool
    is_single_solid: bool
    shells_closed: bool
    volume_mm3: float
    solids: int
    shells: int
    problems: List[str] = field(default_factory=list)


@dataclass
class MeshReport:
    """Outcome of the post-export STL reload check."""

    is_watertight: bool
    winding_consistent: bool
    volume_mm3: float
    face_count: int
    body_count: int
    open_edge_count: int
    non_manifold_edge_count: int
    bounding_box_mm: dict
    problems: List[str] = field(default_factory=list)


def validate_solid(shape: cq.Workplane) -> SolidReport:
    """Validate the CadQuery solid before tessellation."""
    problems: List[str] = []

    solid = shape.val()
    try:
        is_valid = bool(solid.isValid())
    except Exception as exc:  # noqa: BLE001 - OpenCascade validity probe
        return SolidReport(
            is_valid=False,
            is_single_solid=False,
            shells_closed=False,
            volume_mm3=0.0,
            solids=0,
            shells=0,
            problems=[f"OpenCascade could not validate the shape: {exc}"],
        )

    if not is_valid:
        problems.append("OpenCascade reports the shape as invalid.")

    solids = len(solid.Solids())
    if solids != 1:
        problems.append(
            f"The result contains {solids} separate solids; a printable part must be "
            "exactly one connected body."
        )

    shells = solid.Shells()
    shells_closed = all(_shell_is_closed(shell) for shell in shells)
    if not shells_closed:
        problems.append("At least one shell is open, so the solid is not watertight.")

    try:
        volume = float(solid.Volume())
    except Exception:  # noqa: BLE001 - volume can fail on a broken shape
        volume = 0.0
        problems.append("The shape volume could not be computed.")

    if volume <= 0:
        problems.append("The shape has zero or negative volume.")

    return SolidReport(
        is_valid=is_valid and not problems,
        is_single_solid=solids == 1,
        shells_closed=shells_closed,
        volume_mm3=volume,
        solids=solids,
        shells=len(shells),
        problems=problems,
    )


def _shell_is_closed(shell) -> bool:
    """Best-effort closure probe for an OpenCascade shell."""
    try:
        return bool(shell.Closed())
    except Exception:  # noqa: BLE001 - not every shape exposes Closed()
        # Fall back to "assume closed"; the STL reload check is the real authority.
        return True


def validate_exported_stl(stl_path: Path) -> MeshReport:
    """Reload an exported STL from disk and verify the triangle mesh is printable.

    Checks, in order:

    * the file exists and loads as a triangle mesh;
    * the mesh is watertight (every edge shared by exactly two triangles, so there are
      no open boundary loops);
    * winding is consistent (all triangles oriented the same way round);
    * there is exactly one connected body;
    * the enclosed volume is positive.

    Raises :class:`CADValidationError` when the file is unusable or the mesh would not
    slice. Diagnostics (open-edge and non-manifold-edge counts) are included in the
    error details so the problem is actionable rather than just "it failed".
    """
    try:
        import trimesh
    except ImportError as exc:  # pragma: no cover - trimesh is a hard dependency
        raise CADValidationError(
            "The 'trimesh' package is required to verify exported meshes. "
            "Install it with: pip install trimesh",
            details={"stl_path": str(stl_path)},
        ) from exc

    path = Path(stl_path)
    if not path.is_file():
        raise CADValidationError(
            f"Expected the exported STL at {path}, but the file is missing.",
            details={"stl_path": str(path)},
        )

    try:
        loaded = trimesh.load(str(path))
    except Exception as exc:  # noqa: BLE001 - many loader failure modes
        raise CADValidationError(
            f"The exported STL could not be read back: {exc}",
            details={"stl_path": str(path)},
        ) from exc

    mesh = _as_single_mesh(loaded)
    if mesh is None:
        raise CADValidationError(
            "The exported STL does not contain a single triangle mesh.",
            details={"stl_path": str(path), "loaded_type": type(loaded).__name__},
        )

    if len(mesh.faces) == 0:
        raise CADValidationError(
            "The exported STL contains no triangles.",
            details={"stl_path": str(path)},
        )

    open_edges, non_manifold_edges = _edge_statistics(mesh)
    volume = float(mesh.volume)

    problems: List[str] = []
    if not mesh.is_watertight:
        problems.append(
            f"The mesh is not watertight ({open_edges} open edges), so a slicer cannot "
            "tell the inside of the part from the outside."
        )
    if not mesh.is_winding_consistent:
        problems.append(
            "The mesh face orientations are inconsistent, which also prevents slicing."
        )
    if mesh.body_count != 1:
        problems.append(
            f"The mesh contains {mesh.body_count} disconnected bodies instead of one."
        )
    if volume <= 0:
        problems.append("The mesh encloses zero or negative volume.")

    report = MeshReport(
        is_watertight=bool(mesh.is_watertight),
        winding_consistent=bool(mesh.is_winding_consistent),
        volume_mm3=volume,
        face_count=int(len(mesh.faces)),
        body_count=int(mesh.body_count),
        open_edge_count=open_edges,
        non_manifold_edge_count=non_manifold_edges,
        bounding_box_mm={
            "x_mm": round(float(mesh.extents[0]), 4),
            "y_mm": round(float(mesh.extents[1]), 4),
            "z_mm": round(float(mesh.extents[2]), 4),
        },
        problems=problems,
    )

    if problems:
        raise CADValidationError(
            "The generated part did not pass the printability check, so it was not "
            "handed over. " + " ".join(problems),
            details={
                "stl_path": str(path),
                "open_edge_count": open_edges,
                "non_manifold_edge_count": non_manifold_edges,
                "face_count": report.face_count,
                "body_count": report.body_count,
                "volume_mm3": volume,
            },
            hints=[
                "Try slightly different dimensions, especially wall/flex thickness.",
                "Very thin features tessellate poorly - keep walls at or above "
                "MIN_WALL_THICKNESS_MM.",
            ],
        )

    return report


def _as_single_mesh(loaded):
    """Return a single ``trimesh.Trimesh`` from whatever the loader produced."""
    import trimesh

    if isinstance(loaded, trimesh.Trimesh):
        return loaded
    if isinstance(loaded, trimesh.Scene):
        # Merge the scene so body/watertightness counting stays meaningful.
        return loaded.to_mesh()
    return None


def _edge_statistics(mesh) -> Tuple[int, int]:
    """Return ``(open_edge_count, non_manifold_edge_count)`` for a triangle mesh.

    ``is_watertight`` alone tells the user a check failed but not why, so the numbers
    are computed for the error details.
    """
    try:
        edges = mesh.edges_sorted
        if len(edges) == 0:
            return 0, 0
        _, counts = np.unique(edges, axis=0, return_counts=True)
        return int((counts == 1).sum()), int((counts > 2).sum())
    except Exception:  # noqa: BLE001 - statistics are diagnostics only
        return 0, 0


__all__ = [
    "MeshReport",
    "SolidReport",
    "validate_exported_stl",
    "validate_solid",
]
