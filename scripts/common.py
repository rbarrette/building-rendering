"""Shared helpers for build_scene.py (runs inside Blender), validate.py and render.py.

Standard library only. All lengths are decimal inches.
World frame: origin = inside SW corner at slab level, +X east, +Y north, +Z up.
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WALLS = ("W-S", "W-E", "W-N", "W-W")
OPENINGS = {"overhead_door", "door", "window"}
EPS = 0.01


# --------------------------------------------------------------------- loading
def load_raw(path):
    return json.loads(Path(path).read_text())


def normalize(o):
    """Unwrap {"value": v, "confidence": ..., "source": ...} into v."""
    if isinstance(o, dict):
        if "value" in o and set(o) <= {"value", "confidence", "source", "note"}:
            return normalize(o["value"])
        return {k: normalize(v) for k, v in o.items()}
    if isinstance(o, list):
        return [normalize(v) for v in o]
    return o


def load(path):
    return normalize(load_raw(path))


def layout_path(name):
    """Resolve a layout name ('option-a') or path. None/'none' -> None."""
    if not name or str(name).lower() == "none":
        return None
    p = Path(name)
    if p.exists():
        return p
    p = ROOT / "layouts" / (str(name) if str(name).endswith(".json") else f"{name}.json")
    if not p.exists():
        raise FileNotFoundError(f"layout not found: {name}")
    return p


def layout_name(name):
    return "none" if layout_path(name) is None else layout_path(name).stem


def shell_dims(shop):
    s = shop["shell"]
    return s["length_x"], s["width_y"], s["wall_height"]


# -------------------------------------------------------------------- geometry
def rect_poly(cx, cy, w, d, rot=0.0):
    r = math.radians(rot)
    c, s = math.cos(r), math.sin(r)
    return [(cx + dx * c - dy * s, cy + dx * s + dy * c)
            for dx, dy in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2))]


def polys_overlap(a, b, eps=EPS):
    """Separating-axis test for convex polygons; touching (<= eps) is not overlap."""
    for poly in (a, b):
        n = len(poly)
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            ax, ay = -(y2 - y1), x2 - x1
            norm = math.hypot(ax, ay) or 1.0
            pa = [ax * x + ay * y for x, y in a]
            pb = [ax * x + ay * y for x, y in b]
            if (min(max(pa), max(pb)) - max(min(pa), min(pb))) / norm <= eps:
                return False
    return True


def point_seg_dist(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def point_poly_dist(p, poly):
    """0 if p is inside the convex polygon, else the distance to its boundary."""
    n = len(poly)
    signs = [(poly[(i + 1) % n][0] - poly[i][0]) * (p[1] - poly[i][1]) -
             (poly[(i + 1) % n][1] - poly[i][1]) * (p[0] - poly[i][0]) for i in range(n)]
    if all(s >= -EPS for s in signs) or all(s <= EPS for s in signs):
        return 0.0
    return min(point_seg_dist(p, poly[i], poly[(i + 1) % n]) for i in range(n))


def poly_dist(a, b):
    """Gap between two convex polygons (0 if they touch or overlap)."""
    if polys_overlap(a, b):
        return 0.0
    return min(min(point_poly_dist(p, b) for p in a), min(point_poly_dist(p, a) for p in b))


def centroid(poly):
    return sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly)


SIDE_EXTRA = {"front": 0, "back": 180, "left": 270, "right": 90}  # item front faces -Y at rot 0


def side_dir(rot, side="front"):
    """Unit vector the given side of an item points toward (front = -Y at rot 0)."""
    r = math.radians(rot + SIDE_EXTRA[side])
    return math.sin(r), -math.cos(r)


def side_edge(poly, side):
    """Endpoints of one side of a rect_poly footprint."""
    i, j = {"front": (0, 1), "right": (1, 2), "back": (2, 3), "left": (3, 0)}[side]
    return poly[i], poly[j]


def inside_rect(poly, L, W, eps=EPS):
    return all(-eps <= x <= L + eps and -eps <= y <= W + eps for x, y in poly)


def wall_frame(wall, L, W):
    """(origin, direction of increasing offset, inward normal, wall length).

    Offsets are measured standing inside, facing the wall, from its LEFT end.
    """
    return {
        "W-S": ((L, 0.0), (-1.0, 0.0), (0.0, 1.0), L),
        "W-E": ((L, W), (0.0, -1.0), (-1.0, 0.0), W),
        "W-N": ((0.0, W), (1.0, 0.0), (0.0, -1.0), L),
        "W-W": ((0.0, 0.0), (0.0, 1.0), (1.0, 0.0), W),
    }[wall]


def wall_item_span(item):
    """(a0, a1) offsets along the wall. Openings: offset is the left edge; others: centre."""
    if item["kind"] in OPENINGS:
        return item["offset"], item["offset"] + item["w"]
    return item["offset"] - item["w"] / 2, item["offset"] + item["w"] / 2


def wall_item_plan_rect(item, L, W, depth):
    """Plan-view polygon of a wall item, extruded `depth` into the room."""
    (ox, oy), (dx, dy), (nx, ny), _ = wall_frame(item["wall"], L, W)
    a0, a1 = wall_item_span(item)
    p0 = (ox + dx * a0, oy + dy * a0)
    p1 = (ox + dx * a1, oy + dy * a1)
    return [p0, p1, (p1[0] + nx * depth, p1[1] + ny * depth), (p0[0] + nx * depth, p0[1] + ny * depth)]


def interior_wall_poly(iw):
    dx, dy = iw["x2"] - iw["x1"], iw["y2"] - iw["y1"]
    length = math.hypot(dx, dy)
    return rect_poly((iw["x1"] + iw["x2"]) / 2, (iw["y1"] + iw["y2"]) / 2,
                     length, iw["thickness"], math.degrees(math.atan2(dy, dx)))


def seg_frame(iw):
    """(start point, unit direction, unit left normal, length) of an interior wall."""
    dx, dy = iw["x2"] - iw["x1"], iw["y2"] - iw["y1"]
    length = math.hypot(dx, dy)
    return (iw["x1"], iw["y1"]), (dx / length, dy / length), (-dy / length, dx / length), length


def interior_wall_segments(iw):
    """Plan polygons of the solid parts of an interior wall (openings that reach the floor removed)."""
    (x1, y1), (ux, uy), _, length = seg_frame(iw)
    cuts = sorted((o["offset"], o["offset"] + o["w"]) for o in iw.get("openings", []) if o.get("z", 0) < 24)
    spans, cur = [], 0.0
    for a0, a1 in cuts:
        if a0 > cur:
            spans.append((cur, a0))
        cur = max(cur, a1)
    if cur < length:
        spans.append((cur, length))
    rot = math.degrees(math.atan2(uy, ux))
    return [rect_poly(x1 + ux * (a0 + a1) / 2, y1 + uy * (a0 + a1) / 2, a1 - a0, iw["thickness"], rot)
            for a0, a1 in spans if a1 - a0 > EPS]


SIDES = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}
AXES = {"+x": (1, 0), "-x": (-1, 0), "+y": (0, 1), "-y": (0, -1)}
SLIDE_DEPTH = 3  # door panel + track standoff; things set further out (e.g. the fridge) let the door slide behind


def slide_span(iw, o):
    """For a sliding door: (b0, b1) along the wall it slides over, and side sign (+1 = left normal side)."""
    sl = o["slide"]
    (_, _), (ux, uy), (nx, ny), _ = seg_frame(iw)
    sx, sy = SIDES[sl["side"]]
    s = 1 if sx * nx + sy * ny > 0 else -1
    ax, ay = AXES[sl["dir"]]
    a0, a1 = o["offset"], o["offset"] + o["w"]
    if ax * ux + ay * uy > 0:
        return (a1, a1 + sl["travel"]), s
    return (a0 - sl["travel"], a0), s


def interior_door_zones(iw, depth=36):
    """Approach rectangles (both sides) for doors in an interior wall, plus barn-door slide paths."""
    (x1, y1), (ux, uy), (nx, ny), _ = seg_frame(iw)

    def band(b0, b1, t0, t1):
        q0, q1 = (x1 + ux * b0, y1 + uy * b0), (x1 + ux * b1, y1 + uy * b1)
        return [(q0[0] + nx * t0, q0[1] + ny * t0), (q1[0] + nx * t0, q1[1] + ny * t0),
                (q1[0] + nx * t1, q1[1] + ny * t1), (q0[0] + nx * t1, q0[1] + ny * t1)]

    out = []
    for o in iw.get("openings", []):
        if o["kind"] != "door" or o.get("z", 0) >= 24:
            continue
        a0, a1 = o["offset"], o["offset"] + o["w"]
        t = iw["thickness"] / 2 + o.get("clear_depth", depth)
        out.append((f"{iw['id']}/{o['id']}", band(a0, a1, -t, t)))
        if "slide" in o:
            (b0, b1), s = slide_span(iw, o)
            t0 = iw["thickness"] / 2
            out.append((f"{iw['id']}/{o['id']} slide path", band(b0, b1, s * t0, s * (t0 + SLIDE_DEPTH))))
    return out


def overhead_envelopes(shop):
    """(id, plan polygon, bottom z) of the space an open overhead door occupies under its ceiling tracks."""
    L, W, _ = shell_dims(shop)
    out = []
    for wi in shop["wall_items"]:
        if wi["kind"] == "overhead_door":
            depth = wi.get("open_depth", wi["h"] + 18)
            out.append((wi["id"], wall_item_plan_rect(wi, L, W, depth), wi["z"] + wi["h"]))
    return out


def effective_dims(inv, pl):
    """(w, d, h, clearance) for a placed item, honouring "state": "folded"."""
    if pl.get("state") == "folded" and "folded" in inv:
        f = inv["folded"]
        return f["w"], f["d"], f["h"], f.get("clearance", inv.get("clearance", {}))
    return inv["w"], inv["d"], inv["h"], inv.get("clearance", {})


def zone_poly(z):
    return rect_poly(z["x"] + z["w"] / 2, z["y"] + z["d"] / 2, z["w"], z["d"])


def item_rects(inv, pl):
    """Footprint polygon and clearance rect (cx, cy, w, d, rot) of a placed inventory item.

    Item front faces -Y at rot 0; rot is CCW degrees. Clearance covers the footprint plus
    front/back/sides (and `top` above, handled by callers via the z range).
    """
    w, d, _, cl = effective_dims(inv, pl)
    f, s, b = cl.get("front", 0), cl.get("sides", 0), cl.get("back", 0)
    x, y, rot = pl["x"], pl["y"], pl.get("rot", 0)
    foot = rect_poly(x, y, w, d, rot)
    off = (b - f) / 2.0
    r = math.radians(rot)
    clr = (x - off * math.sin(r), y + off * math.cos(r), w + 2 * s, d + f + b, rot)
    return foot, clr
