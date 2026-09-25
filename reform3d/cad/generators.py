"""Stage 3 - parametric CadQuery generators.

Pure deterministic CAD. No AI, no randomness: the same confirmed measurements always
produce the same solid. CadQuery runs OpenCascade headlessly, so there is no GUI
dependency anywhere in this path.

Every generator returns a :class:`cadquery.Workplane` whose ``.val()`` is a single
valid ``Solid``.

Safety rule enforced everywhere
-------------------------------
Any dimension that has to *slide or snap onto* the real object (a bore, a socket, a
clip's inner width/depth) gets ``clearance_mm`` added to it. A 1:1 mating dimension is
never generated, because a printed part that is exactly the same size as the object it
must fit over will bind.

Adding a new archetype
----------------------
1. Add the template value to :class:`reform3d.schema.SuggestedTemplate`.
2. Add its parameter names to :class:`reform3d.schema.FeatureName` and its
   required/optional sets to ``TEMPLATE_FEATURES``. The import-time guard in
   ``schema.py`` fails fast if you forget.
3. Write ``def my_archetype(..., clearance_mm: float) -> cq.Workplane`` in this module,
   call :func:`_require_positive` on every dimension and add ``clearance_mm`` to any
   mating dimension.
4. Register it in :data:`GENERATORS`.
5. Add it to ``TEMPLATE_OPTIONAL_DEFAULTS`` if it has optional parameters.

Nothing else needs to change: the mapping gate, the API and the pipeline all read the
contract from ``schema.py`` and the callable from :data:`GENERATORS`.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

import cadquery as cq

from reform3d.cad.errors import CADGenerationError, CADParameterError
from reform3d.config import Settings, get_settings
from reform3d.schema import FeatureName, SuggestedTemplate

#: Type of a generator callable: keyword parameters in, one Workplane out.
GeneratorFn = Callable[..., cq.Workplane]

# --- Shared helpers ---------------------------------------------------------------


def _fmt(value: float) -> str:
    """Format a number for error messages without trailing noise."""
    return f"{value:g}"


def _require_positive(
    template: str,
    values: Dict[str, Optional[float]],
    *,
    required: Tuple[str, ...] = (),
) -> Dict[str, float]:
    """Validate every supplied dimension and return them as floats.

    Raises :class:`CADParameterError` with a per-field breakdown when a value is
    missing, non-numeric, non-positive, absurdly large, or smaller than the configured
    minimum wall thickness for wall-like parameters.
    """
    problems: List[str] = []
    clean: Dict[str, float] = {}

    for name, raw in values.items():
        if raw is None:
            if name in required:
                problems.append(f"{name} is required")
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            problems.append(f"{name} must be a number (got {raw!r})")
            continue
        if value != value:  # NaN
            problems.append(f"{name} must be a number (got NaN)")
            continue
        if value <= 0:
            problems.append(f"{name} must be greater than 0 (got {_fmt(value)} mm)")
            continue
        clean[name] = value

    if problems:
        raise CADParameterError.from_fields(template, problems, parameters=dict(values))
    return clean


#: Parameters that describe a wall/flexure rather than an object dimension. Their lower
#: bound is enforced by :func:`_check_walls` so the user gets a printability message
#: instead of a generic "out of range" one.
_WALL_LIKE = ("wall_thickness_mm", "flex_thickness_mm")


def _check_plausible(
    template: str,
    params: Dict[str, float],
    settings: Settings,
) -> Dict[str, float]:
    """Reject dimensions outside the configured plausible range (mm).

    For wall-like parameters only the upper bound is checked here, so that a too-thin
    wall is reported by :func:`_check_walls` with a printability explanation.
    """
    problems: List[str] = []
    for name, value in params.items():
        if value > settings.max_dimension_mm:
            problems.append(
                f"{name} is {_fmt(value)} mm, which is larger than the accepted maximum "
                f"of {_fmt(settings.max_dimension_mm)} mm"
            )
            continue
        if name in _WALL_LIKE:
            continue
        if value < settings.min_dimension_mm:
            problems.append(
                f"{name} is {_fmt(value)} mm, smaller than the accepted minimum of "
                f"{_fmt(settings.min_dimension_mm)} mm"
            )
    if problems:
        raise CADParameterError.from_fields(template, problems, parameters=dict(params))
    return params


def _check_walls(
    template: str,
    params: Dict[str, float],
    settings: Settings,
    *,
    extra_problems: Optional[List[str]] = None,
) -> None:
    """Enforce a minimum printable wall/flexure thickness."""
    problems = list(extra_problems or [])
    for name in ("wall_thickness_mm", "flex_thickness_mm"):
        value = params.get(name)
        if value is not None and value < settings.min_wall_thickness_mm:
            problems.append(
                f"{name} is {_fmt(value)} mm; anything under "
                f"{_fmt(settings.min_wall_thickness_mm)} mm will not print reliably"
            )
    if problems:
        raise CADParameterError.from_fields(template, problems, parameters=dict(params))


def _fillet_edges(
    shape: cq.Workplane,
    selector: str,
    radius: float,
    *,
    enabled: bool = True,
) -> cq.Workplane:
    """Fillet edges matched by ``selector``, always returning the *solid*.

    If OpenCascade refuses the fillet we return the original solid unchanged, so a
    cosmetic rounding can never turn the result into an edges-only workplane or fail
    the whole generation. ``enabled=False`` skips the rounding entirely, which the
    pipeline uses as a second attempt when a tessellated mesh is not watertight.
    """
    if not enabled or radius <= 0:
        return shape
    try:
        return shape.edges(selector).fillet(radius)
    except Exception:  # noqa: BLE001 - cosmetic only
        return shape


def _chamfer_face_edges(
    shape: cq.Workplane,
    face_selector: str,
    edge_selector: str,
    distance: float,
    *,
    enabled: bool = True,
) -> cq.Workplane:
    """Chamfer selected edges of selected faces, always returning the *solid*.

    Falls back to the original solid when the chamfer cannot be applied.
    """
    if not enabled or distance <= 0:
        return shape
    try:
        return shape.faces(face_selector).edges(edge_selector).chamfer(distance)
    except Exception:  # noqa: BLE001 - cosmetic only
        return shape


# =====================================================================================
# Archetype 1: friction_fit_collar
# =====================================================================================


def friction_fit_collar(
    bore_diameter_mm: float,
    wall_thickness_mm: float,
    height_mm: float,
    clearance_mm: Optional[float] = None,
    *,
    settings: Optional[Settings] = None,
    decorative: bool = True,
) -> cq.Workplane:
    """A ring that slides over a shaft or knob stub.

    ``bore_diameter_mm`` is the measured shaft diameter. The generated bore is
    ``bore_diameter_mm + clearance_mm`` so the collar slips on instead of binding. The
    bore entry gets a lead-in chamfer, which makes starting the part onto the shaft
    much easier.

    Args:
        bore_diameter_mm: Measured diameter of the shaft/stub the collar fits over.
        wall_thickness_mm: Radial wall thickness of the collar.
        height_mm: Height (length) of the collar along the shaft axis.
        clearance_mm: Safety clearance added to the bore. Defaults to configuration.
        settings: Optional settings override (used by tests).
        decorative: Apply cosmetic edge treatment. Set ``False`` to get the simplest
            possible geometry, which the pipeline uses as a retry when tessellation
            does not come out watertight.

    Returns:
        A CadQuery workplane containing one valid solid.
    """
    config = settings or get_settings()
    template = SuggestedTemplate.friction_fit_collar.value

    params = _require_positive(
        template,
        {
            FeatureName.bore_diameter_mm.value: bore_diameter_mm,
            FeatureName.wall_thickness_mm.value: wall_thickness_mm,
            FeatureName.height_mm.value: height_mm,
        },
        required=(
            FeatureName.bore_diameter_mm.value,
            FeatureName.wall_thickness_mm.value,
            FeatureName.height_mm.value,
        ),
    )
    params = _check_plausible(template, params, config)
    clearance = config.clamp_clearance(clearance_mm)

    bore_diameter = params[FeatureName.bore_diameter_mm.value]
    wall = params[FeatureName.wall_thickness_mm.value]
    height = params[FeatureName.height_mm.value]

    short_height_problem = (
        f"height_mm is {_fmt(height)} mm, which is shorter than the wall thickness and "
        "cannot grip the shaft"
        if height < wall
        else None
    )
    _check_walls(
        template,
        {FeatureName.wall_thickness_mm.value: wall},
        config,
        extra_problems=[short_height_problem] if short_height_problem else None,
    )

    # Mating dimension: the bore always receives the clearance.
    bore_radius = (bore_diameter + clearance) / 2.0
    outer_radius = bore_radius + wall

    try:
        collar = (
            cq.Workplane("XY")
            .circle(outer_radius)
            .extrude(height)
            .faces(">Z")
            .workplane()
            .circle(bore_radius)
            .cutThruAll()
        )
        # Lead-in chamfer where the shaft enters the collar.
        lead_in = min(wall * 0.4, bore_radius * 0.25, height * 0.25)
        collar = _chamfer_face_edges(collar, ">Z", "%CIRCLE", lead_in, enabled=decorative)
    except Exception as exc:  # noqa: BLE001 - wrap OpenCascade failures
        raise CADGenerationError(
            f"Could not build the friction-fit collar: {exc}",
            template=template,
            details={"parameters": dict(params), "clearance_mm": clearance},
        ) from exc

    return collar


# =====================================================================================
# Archetype 2: snap_clip_bracket
# =====================================================================================

#: How much of the channel width each retaining lip may intrude into the opening.
#: Capped at a quarter of the channel so a genuine opening always remains.
_LIP_BITE_FRACTION = 0.25

#: How far back from the open front the retaining lips extend, as a fraction of the
#: channel depth.
_LIP_DEPTH_FRACTION = 0.5


def snap_clip_bracket(
    clip_width_mm: float,
    clip_depth_mm: float,
    flex_thickness_mm: float,
    clearance_mm: Optional[float] = None,
    *,
    settings: Optional[Settings] = None,
    decorative: bool = True,
) -> cq.Workplane:
    """A flexible C-shaped clip bracket that snaps onto a feature and grips it.

    Geometry: a C-section (channel plus back wall plus two retaining lips) extruded
    along Z. The channel's inner width and depth both receive ``clearance_mm``, and the
    lips narrow the entry opening below ``clip_width_mm`` so the clip has to flex over
    the feature and then snaps back to hold it.

    ``clip_width_mm`` is the measured width of the thing being gripped (across the
    opening) and ``clip_depth_mm`` is how deep the grip must reach. Both are mating
    dimensions, so both get the clearance added. The clip is extruded to the same
    length as its depth, which keeps the proportions sensible without extra parameters.

    ``flex_thickness_mm`` sets both the side-wall thickness (the flexing arms) and the
    back-wall thickness.

    Returns:
        A CadQuery workplane containing one valid solid.
    """
    config = settings or get_settings()
    template = SuggestedTemplate.snap_clip_bracket.value

    params = _require_positive(
        template,
        {
            FeatureName.clip_width_mm.value: clip_width_mm,
            FeatureName.clip_depth_mm.value: clip_depth_mm,
            FeatureName.flex_thickness_mm.value: flex_thickness_mm,
        },
        required=(
            FeatureName.clip_width_mm.value,
            FeatureName.clip_depth_mm.value,
            FeatureName.flex_thickness_mm.value,
        ),
    )
    params = _check_plausible(template, params, config)
    clearance = config.clamp_clearance(clearance_mm)

    width = params[FeatureName.clip_width_mm.value]
    depth = params[FeatureName.clip_depth_mm.value]
    flex = params[FeatureName.flex_thickness_mm.value]

    _check_walls(
        template,
        {FeatureName.flex_thickness_mm.value: flex},
        config,
        extra_problems=(
            [f"clip_depth_mm is {_fmt(depth)} mm, shallower than the flex thickness"]
            if depth < flex
            else None
        ),
    )

    # Mating dimensions: channel width and depth always receive the clearance.
    channel_width = width + clearance
    channel_depth = depth + clearance
    half_width = channel_width / 2.0
    extrusion_length = channel_depth

    bite = min(flex, channel_width * _LIP_BITE_FRACTION)
    lip_depth = min(flex * 2.0, channel_depth * _LIP_DEPTH_FRACTION)

    outer_half_width = half_width + flex
    back_outer = channel_depth + flex

    profile = [
        (-outer_half_width, back_outer),  # back-left outer corner
        (outer_half_width, back_outer),  # back-right outer corner
        (outer_half_width, 0.0),  # front-right outer corner
        (half_width - bite, 0.0),  # right lip tip
        (half_width - bite, lip_depth),  # right lip inner corner
        (half_width, lip_depth),  # channel right wall, at lip depth
        (half_width, channel_depth),  # channel right wall, at channel bottom
        (-half_width, channel_depth),  # channel bottom-left
        (-half_width, lip_depth),  # channel left wall, at lip depth
        (-half_width + bite, lip_depth),  # left lip inner corner
        (-half_width + bite, 0.0),  # left lip tip
        (-outer_half_width, 0.0),  # front-left outer corner
    ]

    try:
        clip = cq.Workplane("XY").polyline(profile).close().extrude(extrusion_length)
        # Take the sharp corners off the front edges so the clip is comfortable to push.
        clip = _fillet_edges(clip, "|Z", min(flex * 0.5, 0.8), enabled=decorative)
    except Exception as exc:  # noqa: BLE001 - wrap OpenCascade failures
        raise CADGenerationError(
            f"Could not build the snap-clip bracket: {exc}",
            template=template,
            details={"parameters": dict(params), "clearance_mm": clearance},
        ) from exc

    return clip


# =====================================================================================
# Archetype 3: lever_cap
# =====================================================================================

#: Design ratios (relative to the supplied dimensions) that keep the proportions
#: sensible without hiding absolute magic numbers in the geometry code.
_LEVER_WIDTH_FACTOR = 2.0  # lever width = 2 x wall thickness
_LEVER_HEIGHT_FRACTION = 0.35  # lever sits at 35% of the cap height
_LEVER_EMBED_FRACTION = 0.6  # lever starts 60% of the way out, so it fuses to the wall


def lever_cap(
    cap_diameter_mm: float,
    lever_length_mm: float,
    cap_height_mm: float = 15.0,
    wall_thickness_mm: float = 2.5,
    clearance_mm: Optional[float] = None,
    *,
    settings: Optional[Settings] = None,
    decorative: bool = True,
) -> cq.Workplane:
    """A slip-on cap with an extended grip lever.

    ``cap_diameter_mm`` is the measured diameter of the cap/knob being gripped. The
    socket bore is ``cap_diameter_mm + clearance_mm`` so the part slides on. The cap has
    a closed top (a floor of one wall thickness), so it can also be pushed or pulled.

    The lever is a bar with a rounded end extending radially outwards by
    ``lever_length_mm``, which turns a hard-to-turn cap into an easy one.

    Returns:
        A CadQuery workplane containing one valid solid.
    """
    config = settings or get_settings()
    template = SuggestedTemplate.lever_cap.value

    params = _require_positive(
        template,
        {
            FeatureName.cap_diameter_mm.value: cap_diameter_mm,
            FeatureName.lever_length_mm.value: lever_length_mm,
            FeatureName.cap_height_mm.value: cap_height_mm,
            FeatureName.wall_thickness_mm.value: wall_thickness_mm,
        },
        required=(
            FeatureName.cap_diameter_mm.value,
            FeatureName.lever_length_mm.value,
        ),
    )
    params = _check_plausible(template, params, config)
    clearance = config.clamp_clearance(clearance_mm)

    diameter = params[FeatureName.cap_diameter_mm.value]
    lever_length = params[FeatureName.lever_length_mm.value]
    height = params[FeatureName.cap_height_mm.value]
    wall = params[FeatureName.wall_thickness_mm.value]

    floor_thickness = wall
    _check_walls(
        template,
        {FeatureName.wall_thickness_mm.value: wall},
        config,
        extra_problems=(
            [f"cap_height_mm must be greater than one wall thickness ({_fmt(wall)} mm)"]
            if height <= floor_thickness
            else None
        ),
    )

    # Mating dimension: the socket bore always receives the clearance.
    bore_radius = (diameter + clearance) / 2.0
    outer_radius = bore_radius + wall
    socket_depth = height - floor_thickness

    lever_width = wall * _LEVER_WIDTH_FACTOR
    lever_thickness = wall
    lever_start = outer_radius * _LEVER_EMBED_FRACTION
    lever_end = outer_radius + lever_length
    lever_z = height * _LEVER_HEIGHT_FRACTION

    try:
        cap = cq.Workplane("XY").circle(outer_radius).extrude(height)
        cap = (
            cap.faces(">Z")
            .workplane()
            .circle(bore_radius)
            .cutBlind(-socket_depth)
        )

        # Lever: a rectangle with a semicircular end, drawn in the XY plane and lifted
        # to the grip height.
        half_lever = lever_width / 2.0
        lever = (
            cq.Workplane("XY")
            .moveTo(lever_start, -half_lever)
            .lineTo(lever_end, -half_lever)
            .threePointArc(
                (lever_end + half_lever, 0.0), (lever_end, half_lever)
            )
            .lineTo(lever_start, half_lever)
            .close()
            .extrude(lever_thickness)
            .translate((0.0, 0.0, lever_z))
        )

        part = cap.union(lever)
        part = _fillet_edges(part, "|Z", min(wall * 0.4, 1.0), enabled=decorative)
    except Exception as exc:  # noqa: BLE001 - wrap OpenCascade failures
        raise CADGenerationError(
            f"Could not build the lever cap: {exc}",
            template=template,
            details={"parameters": dict(params), "clearance_mm": clearance},
        ) from exc

    return part


# =====================================================================================
# Archetype 4: wing_adapter
# =====================================================================================

_WING_ROOT_WIDTH_FACTOR = 3.0  # wing root width = 3 x wall thickness
_WING_TIP_WIDTH_FACTOR = 1.6  # wing tip width = 1.6 x wall thickness
_WING_HEIGHT_FRACTION = 0.8  # wings are 80% of the hub height
_WING_EMBED_FRACTION = 0.5  # wings start at 50% of the hub radius, so they fuse


def wing_adapter(
    base_diameter_mm: float,
    wing_span_mm: float,
    base_height_mm: float = 15.0,
    wall_thickness_mm: float = 2.5,
    clearance_mm: Optional[float] = None,
    *,
    settings: Optional[Settings] = None,
    decorative: bool = True,
) -> cq.Workplane:
    """A slip-on hub with two large wings, for turning things with poor grip strength.

    ``base_diameter_mm`` is the measured diameter of the knob/cap the adapter slips
    over; the bore is ``base_diameter_mm + clearance_mm`` so it slides on. The hub is
    open at both ends, which prints without supports.

    ``wing_span_mm`` is the total tip-to-tip span across both wings, so each wing
    reaches out to ``wing_span_mm / 2``. The wings taper from root to tip: wide and
    strong where they meet the hub, narrower where the fingers go.

    Returns:
        A CadQuery workplane containing one valid solid.
    """
    config = settings or get_settings()
    template = SuggestedTemplate.wing_adapter.value

    params = _require_positive(
        template,
        {
            FeatureName.base_diameter_mm.value: base_diameter_mm,
            FeatureName.wing_span_mm.value: wing_span_mm,
            FeatureName.base_height_mm.value: base_height_mm,
            FeatureName.wall_thickness_mm.value: wall_thickness_mm,
        },
        required=(
            FeatureName.base_diameter_mm.value,
            FeatureName.wing_span_mm.value,
        ),
    )
    params = _check_plausible(template, params, config)
    clearance = config.clamp_clearance(clearance_mm)

    diameter = params[FeatureName.base_diameter_mm.value]
    wing_span = params[FeatureName.wing_span_mm.value]
    height = params[FeatureName.base_height_mm.value]
    wall = params[FeatureName.wall_thickness_mm.value]

    # Mating dimension: the bore always receives the clearance.
    bore_radius = (diameter + clearance) / 2.0
    outer_radius = bore_radius + wall
    hub_height = height

    wing_half_span = wing_span / 2.0
    root_width = wall * _WING_ROOT_WIDTH_FACTOR
    tip_width = wall * _WING_TIP_WIDTH_FACTOR
    wing_height = hub_height * _WING_HEIGHT_FRACTION
    embed_radius = outer_radius * _WING_EMBED_FRACTION

    _check_walls(
        template,
        {FeatureName.wall_thickness_mm.value: wall},
        config,
        extra_problems=(
            [
                f"wing_span_mm is {_fmt(wing_span)} mm, which does not reach beyond the "
                f"hub outer diameter ({_fmt(outer_radius * 2.0)} mm), so there would be "
                "no wing to grip"
            ]
            if wing_half_span <= outer_radius
            else None
        ),
    )

    try:
        hub = (
            cq.Workplane("XY")
            .circle(outer_radius)
            .circle(bore_radius)
            .extrude(hub_height)
        )

        # One tapered wing profile in the XY plane, then the same shape mirrored in X.
        wing_profile = [
            (embed_radius, -root_width / 2.0),
            (wing_half_span, -tip_width / 2.0),
            (wing_half_span, tip_width / 2.0),
            (embed_radius, root_width / 2.0),
        ]
        # Round each wing on its own, *before* the union. Filleting the combined part
        # across the hub/wing junction produces a tessellation that is not watertight,
        # whereas rounding the simple prisms first keeps the mesh closed. The rounded
        # root edges end up buried inside the hub material.
        wing = _fillet_edges(
            cq.Workplane("XY").polyline(wing_profile).close().extrude(wing_height),
            "|Z",
            min(wall * 0.5, 1.0),
            enabled=decorative,
        )
        other_wing = _fillet_edges(
            cq.Workplane("XY")
            .polyline([(-x, y) for x, y in wing_profile])
            .close()
            .extrude(wing_height),
            "|Z",
            min(wall * 0.5, 1.0),
            enabled=decorative,
        )

        part = hub.union(wing).union(other_wing)
    except Exception as exc:  # noqa: BLE001 - wrap OpenCascade failures
        raise CADGenerationError(
            f"Could not build the wing adapter: {exc}",
            template=template,
            details={"parameters": dict(params), "clearance_mm": clearance},
        ) from exc

    return part


# =====================================================================================
# Registry
# =====================================================================================

#: Maps a template value to its generator. This is the only place the pipeline needs to
#: know about, so adding an archetype is a one-line change here plus the contract entry
#: in ``reform3d/schema.py``.
GENERATORS: Dict[str, GeneratorFn] = {
    SuggestedTemplate.friction_fit_collar.value: friction_fit_collar,
    SuggestedTemplate.snap_clip_bracket.value: snap_clip_bracket,
    SuggestedTemplate.lever_cap.value: lever_cap,
    SuggestedTemplate.wing_adapter.value: wing_adapter,
}


def get_generator(template: str) -> Optional[GeneratorFn]:
    """Return the generator for ``template``, or ``None`` when there is none."""
    return GENERATORS.get(template)


__all__ = [
    "GENERATORS",
    "GeneratorFn",
    "friction_fit_collar",
    "get_generator",
    "lever_cap",
    "snap_clip_bracket",
    "wing_adapter",
]
