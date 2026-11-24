#!/usr/bin/env python3
"""Validate space.json, inventory.json and layouts. Plain Python, no Blender.

Usage: validate.py [--layout NAME_OR_PATH]   (default: every file in layouts/)
Exit code 1 if any ERROR was found.
"""
import argparse
import hashlib
import itertools
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

issues = []


def add(level, code, msg):
    issues.append((level, code, msg))


# ---------------------------------------------------------------------- schema
def check_schema(raw, schema_name, label):
    try:
        import jsonschema
    except ImportError:
        if not any(i[1] == "schema-skipped" for i in issues):
            add("WARN", "schema-skipped", "jsonschema not installed - schema checks skipped (run `make setup`)")
        return
    schema = C.load_raw(C.ROOT / "data" / "schema" / schema_name)
    v = jsonschema.Draft202012Validator(schema)
    for e in sorted(v.iter_errors(raw), key=lambda e: [str(p) for p in e.absolute_path]):
        path = "/".join(str(p) for p in e.absolute_path)
        add("ERROR", "schema", f"{label}: /{path}: {e.message}")


# ------------------------------------------------------------------- diagonals
def check_diagonals(shop):
    sh = shop["shell"]
    L, W = sh["length_x"], sh["width_y"]
    wl = sh.get("wall_lengths", {})
    for name, nominal in (("W-S", L), ("W-N", L), ("W-E", W), ("W-W", W)):
        if name in wl and abs(wl[name] - nominal) > 1:
            add("WARN", "wall-length", f"{name} measured {wl[name]:.2f}\" but shell implies {nominal:.2f}\"")
    xs = [wl[k] for k in ("W-S", "W-N") if k in wl] or [L]
    ys = [wl[k] for k in ("W-E", "W-W") if k in wl] or [W]
    if len(xs) == 2 and abs(xs[0] - xs[1]) > 1:
        add("WARN", "not-rectangular", f"W-S ({xs[0]:.2f}) and W-N ({xs[1]:.2f}) differ by more than 1\"")
    if len(ys) == 2 and abs(ys[0] - ys[1]) > 1:
        add("WARN", "not-rectangular", f"W-E ({ys[0]:.2f}) and W-W ({ys[1]:.2f}) differ by more than 1\"")
    implied = math.hypot(sum(xs) / len(xs), sum(ys) / len(ys))
    diags = sh.get("diagonals", [])
    if not diags:
        add("INFO", "no-diagonals", f"no diagonals measured yet (implied diagonal = {implied:.2f}\")")
    for dg in diags:
        diff = dg["length"] - implied
        if abs(diff) > 1:
            add("ERROR", "diagonal",
                f"diagonal {dg['id']} {dg['from']}-{dg['to']} measured {dg['length']:.2f}\" vs implied "
                f"{implied:.2f}\" (off by {diff:+.2f}\") - building is out of square or a measurement is wrong")


# ----------------------------------------------------------------- shop checks
def door_zones(shop):
    L, W, H = C.shell_dims(shop)
    out = []
    for wi in shop["wall_items"]:
        if wi["kind"] in ("overhead_door", "door") and wi["z"] < 24:
            depth = wi.get("clear_depth", 48 if wi["kind"] == "overhead_door" else 36)
            out.append((wi["id"], C.wall_item_plan_rect(wi, L, W, depth)))
    for iw in shop["interior_walls"]:
        out.extend(C.interior_door_zones(iw))
    return out


def fixed_obstacles(shop):
    """(label, plan polygon, z0, z1) for floor items and solid interior-wall segments."""
    obs = []
    for fi in shop["floor_items"]:
        z0 = fi.get("z", 0)
        obs.append((f"floor item {fi['id']}", C.rect_poly(fi["x"], fi["y"], fi["w"], fi["d"], fi.get("rot", 0)),
                    z0, z0 + fi["h"]))
    for iw in shop["interior_walls"]:
        for poly in C.interior_wall_segments(iw):
            obs.append((f"interior wall {iw['id']}", poly, 0, iw["height"]))
    return obs


def panel_zones(shop):
    """NEC-style working space in front of electrical panels: max(30in, panel width) wide x 36in deep."""
    L, W, _ = C.shell_dims(shop)
    out = []
    for wi in shop["wall_items"]:
        if wi["kind"] == "panel":
            z = dict(wi, w=max(30, wi["w"]))
            if "working_space_offset" in wi:  # off-centre zone; must still cover the panel front
                z["offset"] = wi["working_space_offset"]
                a0, a1 = C.wall_item_span(wi)
                b0, b1 = C.wall_item_span(z)
                if a0 < b0 - C.EPS or a1 > b1 + C.EPS:
                    add("ERROR", "panel-zone", f"{wi['id']}: working_space_offset leaves part of the panel front uncovered")
            out.append((wi["id"], C.wall_item_plan_rect(z, L, W, 36)))
    return out


def z_overlap(a0, a1, b0, b1):
    return min(a1, b1) - max(a0, b0) > C.EPS


def check_ids(items, label):
    seen = set()
    for it in items:
        if it["id"] in seen:
            add("ERROR", "dup-id", f"duplicate id '{it['id']}' in {label}")
        seen.add(it["id"])


def check_shop(shop):
    L, W, H = C.shell_dims(shop)
    check_diagonals(shop)
    for key in ("interior_walls", "wall_items", "ceiling_items", "floor_items", "zones"):
        check_ids(shop[key], key)

    # wall items
    by_wall = {}
    for wi in shop["wall_items"]:
        _, _, _, wlen = C.wall_frame(wi["wall"], L, W)
        a0, a1 = C.wall_item_span(wi)
        if a0 < -C.EPS or a1 > wlen + C.EPS:
            add("ERROR", "wall-bounds", f"{wi['id']} spans {a0:.1f}..{a1:.1f}\" on {wi['wall']} (wall is {wlen:.1f}\" long)")
        if wi["z"] + wi["h"] > H + C.EPS:
            add("ERROR", "wall-bounds", f"{wi['id']} top at {wi['z'] + wi['h']:.1f}\" exceeds wall height {H:.1f}\"")
        by_wall.setdefault(wi["wall"], []).append(wi)
    for wall, items in by_wall.items():
        for a, b in itertools.combinations(items, 2):
            if a["kind"] not in C.OPENINGS and b["kind"] not in C.OPENINGS:
                continue  # e.g. an outlet mounted on a post
            sa, sb = C.wall_item_span(a), C.wall_item_span(b)
            if (min(sa[1], sb[1]) - max(sa[0], sb[0]) > C.EPS and
                    min(a["z"] + a["h"], b["z"] + b["h"]) - max(a["z"], b["z"]) > C.EPS):
                add("ERROR", "wall-overlap", f"{a['id']} and {b['id']} overlap on {wall}")

    # interior walls inside shell
    for iw in shop["interior_walls"]:
        if not C.inside_rect(C.interior_wall_poly(iw), L, W, eps=iw["thickness"]):
            add("ERROR", "wall-bounds", f"interior wall {iw['id']} extends outside the shell")
        _, _, _, length = C.seg_frame(iw)
        ops = sorted(iw.get("openings", []), key=lambda o: o["offset"])
        for o in ops:
            if o["offset"] + o["w"] > length + C.EPS:
                add("ERROR", "wall-bounds", f"opening {iw['id']}/{o['id']} runs past the end of the wall")
            if o.get("z", 0) + o["h"] > iw["height"] + C.EPS:
                add("ERROR", "wall-bounds", f"opening {iw['id']}/{o['id']} is taller than the wall")
        for a, b in zip(ops, ops[1:]):
            if a["offset"] + a["w"] > b["offset"] + C.EPS:
                add("ERROR", "wall-overlap", f"openings {iw['id']}/{a['id']} and {b['id']} overlap")

    # zones
    zones = shop["zones"]
    for z in zones:
        if not C.inside_rect(C.zone_poly(z), L, W):
            add("ERROR", "zone-bounds", f"zone {z['id']} extends outside the shell")
    for a, b in itertools.combinations(zones, 2):
        if C.polys_overlap(C.zone_poly(a), C.zone_poly(b)):
            add("WARN", "zone-overlap", f"zones {a['id']} and {b['id']} overlap")

    # fixed floor items
    doors = door_zones(shop)
    keep = [z for z in zones if z["kind"] == "keep_clear"]
    obs = fixed_obstacles(shop)
    panels = panel_zones(shop)
    for lbl, poly, z0, z1 in obs:
        if not lbl.startswith("floor item"):
            continue
        if not C.inside_rect(poly, L, W):
            add("ERROR", "bounds", f"{lbl} extends outside the shell")
        if z0 >= 60:
            continue  # wall-hung above head height: doesn't block floor space
        for did, dpoly in doors:
            if C.polys_overlap(poly, dpoly):
                add("ERROR", "blocks-door", f"{lbl} blocks door {did}")
        for pid, ppoly in panels:
            if C.polys_overlap(poly, ppoly):
                add("ERROR", "blocks-panel", f"{lbl} is in the working space in front of panel {pid}")
        for z in keep:
            if C.polys_overlap(poly, C.zone_poly(z)):
                add("ERROR", "keep-clear", f"{lbl} is inside keep-clear zone {z['id']}")
    ftype = {f"floor item {fi['id']}": fi["type"] for fi in shop["floor_items"]}
    for (la, pa, a0, a1), (lb, pb, b0, b1) in itertools.combinations(obs, 2):
        if la.startswith("interior") and lb.startswith("interior"):
            continue  # interior walls are allowed to meet / overlap at joints
        ta, tb = ftype.get(la), ftype.get(lb)
        if "backsplash" in (ta, tb) and not (la.startswith("interior") or lb.startswith("interior")):
            continue  # tile is a wall finish: shelves/cabinets/plates mount on it
        if {ta, tb} == {"sink", "cabinet"}:
            continue  # undermount bowl hangs inside its sink base
        if z_overlap(a0, a1, b0, b1) and C.polys_overlap(pa, pb):
            add("ERROR", "overlap", f"{la} overlaps {lb}")

    # summary of unknowns
    todo = est = 0
    stack = [shop]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            todo += bool(o.get("todo") is True)
            est += o.get("confidence") == "estimated"
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    add("INFO", "todo", f"{todo} items flagged todo, {est} entries still 'estimated'")


# --------------------------------------------------------------- layout checks
def check_layout(shop, inv, layout, label):
    L, W, H = C.shell_dims(shop)
    items = {i["id"]: i for i in inv["items"]}
    check_ids(inv["items"], "inventory")
    doors = door_zones(shop)
    keep = [z for z in shop["zones"] if z["kind"] == "keep_clear"]
    obs = fixed_obstacles(shop)
    placed = []
    for iid, pl in layout["placements"].items():
        if iid not in items:
            add("ERROR", "unknown-item", f"{label}: placement '{iid}' is not in inventory.json")
            continue
        foot, clr = C.item_rects(items[iid], pl)
        placed.append((iid, foot, C.rect_poly(*clr)))
    for iid in items:
        if iid not in layout["placements"]:
            add("INFO", "unplaced", f"{label}: inventory item '{iid}' is not placed")

    envs = C.overhead_envelopes(shop)
    panels = panel_zones(shop)
    for iid, foot, clr in placed:
        pl = layout["placements"][iid]
        _, _, h, cl = C.effective_dims(items[iid], pl)
        z0 = pl.get("z", 0)
        if z0 + h > H + C.EPS:
            add("ERROR", "ceiling", f"{label}: {iid} is {z0 + h:.0f}in tall but the truss underside is {H:.0f}in")
        elif z0 + h + cl.get("top", 0) > H + C.EPS:
            add("WARN", "ceiling", f"{label}: {iid} plus its top clearance reaches past the {H:.0f}in truss underside")
        flat = items[iid].get("specs", {}).get("floor_covering")  # mats/turf: walked on, never in the way
        for pid, ppoly in ([] if flat else panels):
            if C.polys_overlap(foot, ppoly):
                add("ERROR", "blocks-panel", f"{label}: {iid} is in the working space in front of panel {pid}")
        for eid, epoly, zb in envs:
            if h > zb - 2 and C.polys_overlap(foot, epoly):
                add("WARN", "door-track", f"{label}: {iid} ({h:.0f}in tall) is under the open-door path of {eid} (bottom ~{zb:.0f}in)")
        if not C.inside_rect(foot, L, W):
            add("ERROR", "bounds", f"{label}: {iid} extends outside the shell")
        elif not C.inside_rect(clr, L, W):
            add("WARN", "clearance-bounds", f"{label}: clearance of {iid} extends outside the shell")
        for did, dpoly in ([] if flat else doors):
            if C.polys_overlap(foot, dpoly):
                add("ERROR", "blocks-door", f"{label}: {iid} blocks door {did}")
        for z in ([] if flat else keep):
            if C.polys_overlap(foot, C.zone_poly(z)):
                add("ERROR", "keep-clear", f"{label}: {iid} is inside keep-clear zone {z['id']}")
        for lbl, poly, b0, b1 in obs:
            if not z_overlap(z0, z0 + h + cl.get("top", 0), b0, b1):
                continue
            if z_overlap(z0, z0 + h, b0, b1) and C.polys_overlap(foot, poly):
                add("ERROR", "overlap", f"{label}: {iid} overlaps {lbl}")
            elif C.polys_overlap(clr, poly):
                add("WARN", "clearance-overlap", f"{label}: clearance of {iid} overlaps {lbl}")
    check_walkability(shop, items, layout, label)

    def _fits_under_bay(rack_id, rack_pl, item_id, item_foot, item_pl):
        ub = items[rack_id].get("specs", {}).get("under_bay")
        if not ub:
            return False
        if ub.get("state") and rack_pl.get("state", "open") != ub["state"]:
            return False
        _, _, ih, _ = C.effective_dims(items[item_id], item_pl)
        iz1 = item_pl.get("z", 0) + ih
        rz0 = rack_pl.get("z", 0)
        if iz1 > rz0 + ub["h"] + C.EPS:
            return False
        bay_poly = C.rect_poly(rack_pl["x"], rack_pl["y"], ub["w"], ub["d"], rack_pl.get("rot", 0))
        return all(C.point_poly_dist(p, bay_poly) <= 0.5 for p in item_foot)

    for (ia, fa, ca), (ib, fb, cb) in itertools.combinations(placed, 2):
        pla, plb = layout["placements"][ia], layout["placements"][ib]
        _, _, ha, _ = C.effective_dims(items[ia], pla)
        _, _, hb, _ = C.effective_dims(items[ib], plb)
        za0, zb0 = pla.get("z", 0), plb.get("z", 0)
        if not z_overlap(za0, za0 + ha, zb0, zb0 + hb):
            continue
        if _fits_under_bay(ia, pla, ib, fb, plb) or _fits_under_bay(ib, plb, ia, fa, pla):
            continue
        # floor coverings (specs.floor_covering: rubber mats, turf) lie under other items
        if items[ia].get("specs", {}).get("floor_covering") or items[ib].get("specs", {}).get("floor_covering"):
            continue
        if C.polys_overlap(fa, fb):
            add("ERROR", "overlap", f"{label}: {ia} overlaps {ib}")
            continue
        # an item that sits at another (specs.sits_at, e.g. chairs at a table) may use that item's clearance
        if items[ia].get("specs", {}).get("sits_at") == ib or items[ib].get("specs", {}).get("sits_at") == ia:
            continue
        if C.polys_overlap(fa, cb):
            add("WARN", "clearance-overlap", f"{label}: {ia} sits in the clearance of {ib}")
        if C.polys_overlap(fb, ca):
            add("WARN", "clearance-overlap", f"{label}: {ib} sits in the clearance of {ia}")


# ------------------------------------------------------------- placement rules
COMPASS = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}


def _angle(u, v):
    nu, nv = math.hypot(*u), math.hypot(*v)
    if not nu or not nv:
        return 0.0
    c = max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / (nu * nv)))
    return math.degrees(math.acos(c))


def rule_targets(shop, items, layout, name):
    """Plan polygons for a target name, or None if unknown / not placed. 'any-wall' = every wall."""
    L, W, _ = C.shell_dims(shop)
    walls = {"W-S": C.rect_poly(L / 2, -1, L, 2), "W-N": C.rect_poly(L / 2, W + 1, L, 2),
             "W-W": C.rect_poly(-1, W / 2, 2, W), "W-E": C.rect_poly(L + 1, W / 2, 2, W)}
    for iw in shop["interior_walls"]:
        walls[iw["id"]] = C.interior_wall_poly(iw)
        (x1, y1), (ux, uy), (nx, ny), length = C.seg_frame(iw)
        for face, (fx, fy) in COMPASS.items():  # 'IW-1:S' = a 1in sliver on that face of the wall
            dot = nx * fx + ny * fy
            if abs(dot) > 0.7:
                sgn = 1 if dot > 0 else -1
                off = sgn * (iw["thickness"] / 2 - 0.5)
                walls[f"{iw['id']}:{face}"] = C.rect_poly(x1 + ux * length / 2 + nx * off, y1 + uy * length / 2 + ny * off,
                                                         length, 1, math.degrees(math.atan2(uy, ux)))
    if name == "any-wall":
        return [p for k, p in walls.items() if ":" not in k]
    if name == "half:S":
        return [C.rect_poly(L / 2, 233.25 / 2, L, 233.25)]
    if name == "half:N":
        return [C.rect_poly(L / 2, 237.75 + (W - 237.75) / 2, L, W - 237.75)]
    if name in walls:
        return [walls[name]]
    for z in shop["zones"]:
        if z["id"] == name:
            return [C.zone_poly(z)]
    for wi in shop["wall_items"]:
        if wi["id"] == name:
            return [C.wall_item_plan_rect(wi, L, W, 1)]
    for fi in shop["floor_items"]:
        if fi["id"] == name:
            return [C.rect_poly(fi["x"], fi["y"], fi["w"], fi["d"], fi.get("rot", 0))]
    if name in items and name in layout["placements"]:
        return [C.item_rects(items[name], layout["placements"][name])[0]]
    return None


def known_target(shop, items, name):
    ids = {"any-wall", "half:S", "half:N", *C.WALLS, *(iw["id"] for iw in shop["interior_walls"]),
           *(f"{iw['id']}:{f}" for iw in shop["interior_walls"] for f in COMPASS)}
    for key in ("zones", "wall_items", "floor_items"):
        ids.update(x["id"] for x in shop[key])
    return name in ids or name in items


def check_rules(shop, inv, rules, layout, label):
    lname = Path(label).stem
    items = {i["id"]: i for i in inv["items"]}
    ordered = sorted(rules, key=lambda r: (r.get("priority", 2), 0 if r["strength"] == "must" else 1, r["id"]))
    for r in ordered:
        if r.get("layouts") and lname not in r["layouts"]:
            continue
        rid, kind, iid = r["id"], r["kind"], r.get("item")
        prio = r.get("priority", 2)
        lvl = "ERROR" if r["strength"] == "must" else "WARN"
        tag = f"{label}: {rid} ({r['strength']}, P{prio})"
        verb = "must" if r["strength"] == "must" else "should"
        if kind == "manual":
            add("INFO", "rule-manual", f"{tag}: check by eye - \"{r['said']}\"")
            continue
        if iid not in items:
            add("ERROR", "rule-unknown", f"{label}: {rid} is about '{iid}', which is not in inventory.json")
            continue
        targets = r.get("target", [])
        targets = [targets] if isinstance(targets, str) else targets
        bad = [t for t in targets if not known_target(shop, items, t)]
        if bad:
            add("ERROR", "rule-unknown", f"{label}: {rid} names unknown target(s) {', '.join(bad)}")
            continue
        pl = layout["placements"].get(iid)
        if kind == "placed":
            if not pl:
                add(lvl, "rule", f"{tag}: {iid} {verb} be placed but isn't")
            continue
        if kind == "not_placed":
            if pl:
                add(lvl, "rule", f"{tag}: {iid} is placed but {verb} not be")
            continue
        if not pl:
            add("INFO", "rule-skip", f"{tag}: {iid} isn't placed, rule not checked")
            continue
        foot, _ = C.item_rects(items[iid], pl)
        rot = pl.get("rot", 0)
        polys = {}
        for t in targets:
            p = rule_targets(shop, items, layout, t)
            if p is None:
                add("INFO", "rule-skip", f"{tag}: target {t} isn't placed in this layout, rule not checked")
            else:
                polys[t] = p
        if targets and not polys:
            continue

        ok, why = True, ""
        if kind == "in_zone":
            ok = any(all(C.point_poly_dist(p, zp) <= 0.5 for p in foot) for ps in polys.values() for zp in ps)
            why = f"{iid} is not inside {' or '.join(targets)}"
        elif kind == "against":
            side, gap = r.get("side", "back"), r.get("max_gap", 6)
            a, b = C.side_edge(foot, side)
            n = C.side_dir(rot, side)
            best = None
            for t, ps in polys.items():
                if ":" in t:  # one face of a wall: the side must point back into that face, not through the wall
                    fx, fy = COMPASS[t.split(":")[1]]
                    if n[0] * fx + n[1] * fy > -0.7:
                        continue
                for wp in ps:
                    da, db = C.point_poly_dist(a, wp), C.point_poly_dist(b, wp)
                    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                    probe = (mid[0] + n[0], mid[1] + n[1])
                    toward = C.point_poly_dist(probe, wp) < C.point_poly_dist(mid, wp) or max(da, db) < 0.5
                    d = max(da, db)
                    if toward and (best is None or d < best):
                        best = d
            ok = best is not None and best <= gap
            why = (f"{iid}'s {side} is {best:.1f}in from {' / '.join(targets)} (max {gap}in)" if best is not None
                   else f"{iid}'s {side} doesn't face {' / '.join(targets)}")
        elif kind == "facing":
            side, tol = r.get("side", "front"), r.get("tolerance", 20)
            ang = _angle(C.side_dir(rot, side), COMPASS[r["direction"]])
            ok = ang <= tol
            why = f"{iid}'s {side} points {ang:.0f} deg away from {r['direction']} (rot {rot})"
        elif kind == "facing_toward":
            side, tol = r.get("side", "front"), r.get("tolerance", 45)
            cx, cy = pl["x"], pl["y"]
            angs = [_angle(C.side_dir(rot, side), (C.centroid(p)[0] - cx, C.centroid(p)[1] - cy))
                    for ps in polys.values() for p in ps]
            ok = min(angs) <= tol
            why = f"{iid}'s {side} is {min(angs):.0f} deg off pointing at {' / '.join(polys)}"
        elif kind == "state":
            cur = pl.get("state", "open")
            ok = cur == r["value"]
            why = f"{iid} is {cur}, {verb} be {r['value']}"
        elif kind in ("near", "away_from"):
            d = min(C.poly_dist(foot, p) for ps in polys.values() for p in ps)
            if kind == "near":
                ok, why = d <= r["max_dist"], f"{iid} is {d:.0f}in from {' / '.join(polys)} (max {r['max_dist']}in)"
            else:
                ok, why = d >= r["min_dist"], f"{iid} is {d:.0f}in from {' / '.join(polys)} (min {r['min_dist']}in)"
        if not ok:
            add(lvl, "rule", f"{tag}: {why} - \"{r['said']}\"")


# ----------------------------------------------------------------- walkability
CELL = 3.0  # raster resolution (in)


def _point_in_poly(x, y, poly):
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _cells_in(poly, nx, ny):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    i0, i1 = max(0, int(min(xs) / CELL)), min(nx - 1, int(max(xs) / CELL))
    j0, j1 = max(0, int(min(ys) / CELL)), min(ny - 1, int(max(ys) / CELL))
    for j in range(j0, j1 + 1):
        for i in range(i0, i1 + 1):
            if _point_in_poly((i + 0.5) * CELL, (j + 0.5) * CELL, poly):
                yield i, j


def walk_reach(shop, obstacles, path_width):
    """Cells reachable from any exterior door by a body `path_width` wide. Returns (reach set, nx, ny)."""
    L, W, _ = C.shell_dims(shop)
    nx, ny = int(math.ceil(L / CELL)), int(math.ceil(W / CELL))
    blocked = bytearray(nx * ny)
    solid = bytearray(nx * ny)
    for poly in obstacles:
        for i, j in _cells_in(poly, nx, ny):
            solid[j * nx + i] = 1
    r = path_width / 2.0 / CELL
    disk = [(di, dj) for di in range(-int(r) - 1, int(r) + 2) for dj in range(-int(r) - 1, int(r) + 2)
            if di * di + dj * dj <= r * r]
    rim = int(math.ceil(r))
    for j in range(ny):  # shell walls: anything within r of the boundary is blocked
        for i in range(nx):
            if i < rim or j < rim or i >= nx - rim or j >= ny - rim:
                d = min(i + 0.5, j + 0.5, nx - i - 0.5, ny - j - 0.5)
                if d <= r:
                    blocked[j * nx + i] = 1
    for j in range(ny):
        for i in range(nx):
            if not solid[j * nx + i]:
                continue
            edge = any(0 <= i + a < nx and 0 <= j + b < ny and not solid[(j + b) * nx + i + a]
                       for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1)))
            blocked[j * nx + i] = 1
            if edge:
                for di, dj in disk:
                    ii, jj = i + di, j + dj
                    if 0 <= ii < nx and 0 <= jj < ny:
                        blocked[jj * nx + ii] = 1
    # seeds: just inside every exterior door
    L_, W_ = L, W
    seeds = []
    for wi in shop["wall_items"]:
        if wi["kind"] in ("door", "overhead_door"):
            (ox, oy), (dx, dy), (nx_, ny_), _ = C.wall_frame(wi["wall"], L_, W_)
            a0, a1 = C.wall_item_span(wi)
            for depth in range(int(path_width / 2) + 2, int(path_width) + 30, 3):
                x, y = ox + dx * (a0 + a1) / 2 + nx_ * depth, oy + dy * (a0 + a1) / 2 + ny_ * depth
                i, j = int(x / CELL), int(y / CELL)
                if 0 <= i < nx and 0 <= j < ny and not blocked[j * nx + i]:
                    seeds.append(j * nx + i)
                    break
    reach = set(seeds)
    stack = list(seeds)
    while stack:
        c = stack.pop()
        i, j = c % nx, c // nx
        for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ii, jj = i + a, j + b
            if 0 <= ii < nx and 0 <= jj < ny:
                k = jj * nx + ii
                if k not in reach and not blocked[k]:
                    reach.add(k)
                    stack.append(k)
    return reach, nx, ny


def check_walkability(shop, items, layout, label, good=36, tight=28):
    """Can every zone and every placed item's front be reached from a door with a `good` (else `tight`) path?"""
    obstacles = [p for _, p, z0, _ in fixed_obstacles(shop) if z0 < 60]  # things you'd walk into
    fronts = {}
    seated = {}  # item id -> obstacles of the items that sit at it (chairs at a table: pulled out to reach it)
    lows = []  # (foot, top z, depth) of floor-standing items, for raised items mounted above them
    for iid, pl in layout["placements"].items():
        if iid in items and pl.get("z", 0) < 30 and not items[iid].get("specs", {}).get("floor_covering"):
            w, d, h, _ = C.effective_dims(items[iid], pl)
            lows.append((C.item_rects(items[iid], pl)[0], pl.get("z", 0) + h, d))
    for iid, pl in layout["placements"].items():
        if iid not in items:
            continue
        w, d, h, _ = C.effective_dims(items[iid], pl)
        foot, _ = C.item_rects(items[iid], pl)
        ub = items[iid].get("specs", {}).get("under_bay")
        if items[iid].get("specs", {}).get("floor_covering"):
            continue  # mats/turf are walked on: neither an obstacle nor a place to reach
        if pl.get("z", 0) >= 30:
            pass  # benchtop/elevated item does not block floor walkability
        elif ub and (not ub.get("state") or pl.get("state", "open") == ub["state"]):
            fw = max(2.0, (w - ub["w"]) / 2.0)
            rr = math.radians(pl.get("rot", 0))
            dx, dy = math.cos(rr) * (w / 2.0 - fw / 2.0), math.sin(rr) * (w / 2.0 - fw / 2.0)
            obstacles.append(C.rect_poly(pl["x"] - dx, pl["y"] - dy, fw, d, pl.get("rot", 0)))
            obstacles.append(C.rect_poly(pl["x"] + dx, pl["y"] + dy, fw, d, pl.get("rot", 0)))
        else:
            obstacles.append(foot)
            at = items[iid].get("specs", {}).get("sits_at")
            if at in layout["placements"]:
                seated.setdefault(at, []).append(foot)
        z0 = pl.get("z", 0)
        # the side you use the item from ("access", default front = -Y at rot 0)
        side = items[iid].get("access", "front")
        extra = {"front": 0, "back": 180, "left": 270, "right": 90}[side]
        r = math.radians(pl.get("rot", 0) + extra)
        span, reach_d = (w, d) if side in ("front", "back") else (d, w)
        depth = good / 2 + 8  # a standing spot just beyond the body-width band around the item
        if z0 >= 30:  # raised (wall TV, shelf): stand in front of any lower item mounted beneath it
            probe = C.rect_poly(pl["x"] + math.sin(r) * (reach_d / 2 + 2), pl["y"] - math.cos(r) * (reach_d / 2 + 2),
                                span, 4, pl.get("rot", 0) + extra)
            reach_d += max([ld for lf, top, ld in lows if top <= z0 and C.polys_overlap(probe, lf)], default=0)
        cx, cy = pl["x"] + math.sin(r) * (reach_d / 2 + depth / 2), pl["y"] - math.cos(r) * (reach_d / 2 + depth / 2)
        fronts[iid] = C.rect_poly(cx, cy, span + 12, depth, pl.get("rot", 0) + extra)
    targets = {f"zone {z['id']}": C.zone_poly(z) for z in shop["zones"]}
    targets.update({f"front of {k}": v for k, v in fronts.items()})
    results = {}
    for width in (good, tight):
        reach, nx, ny = walk_reach(shop, obstacles, width)
        results[width] = {name: any(j * nx + i in reach for i, j in _cells_in(poly, nx, ny))
                          for name, poly in targets.items()}
        for at, feet in seated.items():  # reach a table with its own chairs pulled out
            name = f"front of {at}"
            if name in targets and not results[width][name]:
                reach2, nx2, ny2 = walk_reach(shop, [o for o in obstacles if not any(o is f for f in feet)], width)
                results[width][name] = any(j * nx2 + i in reach2 for i, j in _cells_in(targets[name], nx2, ny2))
    for name in targets:
        if not results[tight][name]:
            add("WARN", "walkability", f"{label}: {name} can't be reached from any door, even with a {tight}in path")
        elif not results[good][name]:
            add("INFO", "walkability", f"{label}: {name} is only reachable through a gap narrower than {good}in")


# ------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--layout", help="layout name or path (default: all in layouts/)")
    ap.add_argument("--rules", default=str(C.ROOT / "data" / "placement-rules.json"),
                    help="placement rules file (default: data/placement-rules.json)")
    args = ap.parse_args()

    shop_raw = C.load_raw(C.ROOT / "data" / "space.json")
    inv_raw = C.load_raw(C.ROOT / "data" / "inventory.json")
    check_schema(shop_raw, "space.schema.json", "space.json")
    check_schema(inv_raw, "inventory.schema.json", "inventory.json")
    rules = []
    if Path(args.rules).exists():
        rules_raw = C.load_raw(args.rules)
        check_schema(rules_raw, "placement-rules.schema.json", Path(args.rules).name)
        rules = rules_raw.get("rules", [])
        seen = set()
        for r in rules:
            if r.get("id") in seen:
                add("ERROR", "dup-id", f"duplicate rule id '{r['id']}' in {Path(args.rules).name}")
            seen.add(r.get("id"))
    if any(i[0] == "ERROR" for i in issues):
        return report()  # geometry checks assume a schema-valid file
    shop, inv = C.normalize(shop_raw), C.normalize(inv_raw)
    check_shop(shop)
    H = C.shell_dims(shop)[2]
    for it in inv["items"]:  # flag items that can't stand anywhere under the trusses, placed or not
        tallest = max(it["h"], it.get("folded", {}).get("h", 0))
        if min(it["h"], it.get("folded", {}).get("h", it["h"])) > H:
            add("WARN", "ceiling", f"inventory: {it['id']} is {tallest:.0f}in tall - won't fit under the {H:.0f}in truss underside")
        sc = it.get("scan") or {}
        for cap in sc.get("captures", []):
            if not (C.ROOT / cap["path"]).exists():
                add("ERROR", "scan-missing", f"inventory: {it['id']} scan capture missing: {cap['path']}")
        if sc.get("status") == "scanned" and not sc.get("captures"):
            add("WARN", "scan-meta", f"inventory: {it['id']} scan.status is 'scanned' but no captures are listed")
        a = it.get("asset")
        if a and a.get("source") == "scan" and sc.get("status") != "scanned":
            add("WARN", "scan-meta", f"inventory: {it['id']} asset.source is 'scan' but scan.status isn't 'scanned'")
        if a and a.get("path"):
            ap = C.ROOT / a["path"]
            if not ap.exists():
                add("ERROR", "asset-missing", f"inventory: {it['id']} asset file missing: {a['path']}")
                continue
            aj = C.ROOT / "assets" / "items" / it["id"] / "asset.json"
            if not aj.exists():
                add("WARN", "asset-meta", f"inventory: {it['id']} missing assets/items/{it['id']}/asset.json (run `make asset-preview ITEM={it['id']}`)")
                continue
            meta = C.load_raw(aj)
            sha = hashlib.sha256(ap.read_bytes()).hexdigest()
            if meta.get("sha256") != sha:
                add("WARN", "asset-stale", f"inventory: {it['id']} asset.json sha256 mismatch for {a['path']} (re-run `make asset-preview ITEM={it['id']}`)")
            diff = meta.get("diff_in", {})
            bad_dims = [f"{k} {v:+.2f}\"" for k, v in diff.items() if abs(v) > 1.5]
            if bad_dims:
                add("WARN", "asset-size", f"inventory: {it['id']} asset bbox differs from inventory by >1.5in ({', '.join(bad_dims)})")

    if args.layout and args.layout.lower() != "none":
        paths = [C.layout_path(args.layout)]
    elif args.layout:
        paths = []
    else:
        paths = sorted((C.ROOT / "layouts").glob("*.json"))
    for p in paths:
        raw = C.load_raw(p)
        check_schema(raw, "layout.schema.json", f"layouts/{p.name}")
        if not any(i[0] == "ERROR" and p.name in i[2] for i in issues):
            check_layout(shop, inv, raw, f"layouts/{p.name}")
            check_rules(shop, inv, rules, raw, f"layouts/{p.name}")
    return report()


def report():
    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    for level, code, msg in sorted(issues, key=lambda i: order[i[0]]):
        print(f"{level:5} [{code}] {msg}")
    errs = sum(i[0] == "ERROR" for i in issues)
    warns = sum(i[0] == "WARN" for i in issues)
    print(f"\n{errs} error(s), {warns} warning(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
