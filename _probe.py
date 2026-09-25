"""Throwaway probe script - deleted after use."""
import os
import tempfile

import cadquery as cq
import trimesh

from reform3d.cad import generators as G


def report(label, workplane):
    tmp = tempfile.mkdtemp()
    stl = os.path.join(tmp, "x.stl")
    cq.exporters.export(workplane, stl, cq.exporters.ExportTypes.STL)
    m = trimesh.load(stl)
    print(
        f"{label:24s} watertight={m.is_watertight} winding={m.is_winding_consistent} "
        f"bodies={m.body_count} faces={len(m.faces)} vol={m.volume:.2f}"
    )
    if not m.is_watertight:
        import numpy as np

        edges = m.edges_sorted
        uniq, counts = np.unique(edges, axis=0, return_counts=True)
        open_edges = int((counts == 1).sum())
        over_edges = int((counts > 2).sum())
        print(f"{'':24s} open_edges={open_edges} over_shared_edges={over_edges}")
    return m


# Reproduce the wing_adapter body without the fillet, to isolate the cause.
diameter, wing_span, height, wall = 30.0, 70.0, 15.0, 2.5
clearance = G.get_settings().clamp_clearance(None) if hasattr(G, "get_settings") else 0.2
from reform3d.config import get_settings

clearance = get_settings().clamp_clearance(None)
bore_radius = (diameter + clearance) / 2.0
outer_radius = bore_radius + wall
wing_half_span = wing_span / 2.0
root_width = wall * G._WING_ROOT_WIDTH_FACTOR
tip_width = wall * G._WING_TIP_WIDTH_FACTOR
wing_height = height * G._WING_HEIGHT_FRACTION
embed_radius = outer_radius * G._WING_EMBED_FRACTION
fillet_r = min(wall * 0.5, 1.0)

hub = cq.Workplane("XY").circle(outer_radius).circle(bore_radius).extrude(height)
profile = [
    (embed_radius, -root_width / 2.0),
    (wing_half_span, -tip_width / 2.0),
    (wing_half_span, tip_width / 2.0),
    (embed_radius, root_width / 2.0),
]
wing = cq.Workplane("XY").polyline(profile).close().extrude(wing_height)
other = cq.Workplane("XY").polyline([(-x, y) for x, y in profile]).close().extrude(wing_height)

union = hub.union(wing).union(other)
report("union (no fillet)", union)
report("union + fillet", G._fillet_edges(union, "|Z", fillet_r))
report("generator output", G.wing_adapter(diameter, wing_span))
print("fillet radius", fillet_r)

# Approach A: fillet each wing prism before unioning, so the rounded edges at the
# wing roots are absorbed into the hub.
wing_r = G._fillet_edges(wing, "|Z", fillet_r)
other_r = G._fillet_edges(other, "|Z", fillet_r)
report("fillet wings then union", hub.union(wing_r).union(other_r))

# Approach B: no fillet at all on the wing adapter.
report("no fillet (hub + wings)", hub.union(wing).union(other))

# Approach C: fillet only the outer tip edges of the combined part.
combined = hub.union(wing).union(other)
try:
    tip = combined.edges("|Z").edges(cq.selectors.BoxSelector(
        (outer_radius, -100, -100), (1000, 100, 1000)
    ))
    report("fillet tips only (+X)", tip.fillet(fillet_r) if tip.size() else combined)
except Exception as exc:  # noqa: BLE001
    print("approach C failed:", exc)
