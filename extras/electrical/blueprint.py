#!/usr/bin/env python3
"""To-scale electrical blueprint of the accent wall (IW-1), drawn from data.

Reads data/space.json (walls, openings, trim, fixed items), a layout (movable items against the wall, for context)
and data/electrical.json (circuits + boxes). Writes, under drawings/electrical/:
  accent-wall.pdf          2 pages, ARCH D (36x24 in): E1 elevations at 1/2" = 1'-0", E2 schedules
  accent-wall-E1.svg / -E2.svg
  accent-wall.dxf          both sheets; geometry at true size in inches (opens in AutoCAD, FreeCAD, LibreCAD, ...)

Also prints warnings: a box in a barn-door slide zone, on a trim batten/rail, or too close to an opening.
Needs reportlab + ezdxf (requirements.txt). Usage: make blueprint [LAYOUT=option-b]
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, load, layout_path  # noqa: E402

SHEET_W, SHEET_H = 36.0, 24.0          # ARCH D, inches
SCALE = 1 / 24                         # 1/2" = 1'-0"
PLATE = {1: (2.75, 4.5), 2: (4.5, 4.5), 3: (6.4, 4.5)}
BODY = {1: 2.3, 2: 4.0, 3: 5.8}        # new-work box body width (behind the plate); nail-on box centre = stud +/- (0.75 + BODY/2)
BODY_H = 3.75
SLAB_OVERLAP = 2.0                     # assumed barn-door slab overlap past the opening, each side
BLACK, GRAY, LIGHT, RED, BLUE = "#000000", "#8a8a8a", "#c8c8c8", "#c0392b", "#1f5fa8"
STUD = "#b08850"
OUT = ROOT / "drawings" / "electrical"


# ------------------------------------------------------------------ formatting
def fmt(v):
    """Inches -> 5'-3½" (nearest ½")."""
    v = round(v * 2) / 2
    neg, v = v < 0, abs(v)
    ft, rem = int(v // 12), v - int(v // 12) * 12
    whole, half = int(rem), (rem - int(rem)) >= 0.25
    s_in = f"{whole}{'½' if half else ''}\""
    s = f"{ft}'-{s_in}" if ft else s_in
    return "-" + s if neg else s


def text_w(s, size):
    """Rough Helvetica width in inches."""
    return len(s) * size * 0.52 / 72


# ---------------------------------------------------------------------- sheet
class Sheet:
    """Primitives in paper inches, origin bottom-left."""

    def __init__(self, name):
        self.name, self.items = name, []

    def line(self, x1, y1, x2, y2, lw=0.5, color=BLACK, dash=False, layer="0"):
        self.items.append(("line", dict(x1=x1, y1=y1, x2=x2, y2=y2, lw=lw, color=color, dash=dash, layer=layer)))

    def rect(self, x, y, w, h, lw=0.5, color=BLACK, fill=None, dash=False, layer="0"):
        self.items.append(("rect", dict(x=x, y=y, w=w, h=h, lw=lw, color=color, fill=fill, dash=dash, layer=layer)))

    def text(self, x, y, s, size=7, anchor="start", rot=0, color=BLACK, bold=False, layer="0"):
        self.items.append(("text", dict(x=x, y=y, s=str(s), size=size, anchor=anchor, rot=rot, color=color,
                                        bold=bold, layer=layer)))


class View:
    """Elevation: world x (along the wall) and z (height) -> paper. mirror=True draws x decreasing to the right."""

    def __init__(self, sheet, ox, oy, length, mirror):
        self.s, self.ox, self.oy, self.L, self.mirror = sheet, ox, oy, length, mirror

    def px(self, x):
        return self.ox + ((self.L - x) if self.mirror else x) * SCALE

    def py(self, z):
        return self.oy + z * SCALE

    def line(self, x1, z1, x2, z2, **k):
        self.s.line(self.px(x1), self.py(z1), self.px(x2), self.py(z2), **k)

    def rect(self, x0, z0, x1, z1, **k):
        a, b = sorted((self.px(x0), self.px(x1)))
        self.s.rect(a, self.py(z0), b - a, self.py(z1) - self.py(z0), **k)

    def text(self, x, z, s, **k):
        self.s.text(self.px(x), self.py(z), s, **k)

    def hatch(self, x0, x1, z0, z1, step=6.0, **k):
        c = x0 - (z1 - z0)
        while c < x1:
            za, zb = max(z0, z0 + (x0 - c)), min(z1, z0 + (x1 - c))
            if zb > za:
                self.line(c + (za - z0), za, c + (zb - z0), zb, **k)
            c += step


# ---------------------------------------------------------------------- data
def load_inputs(layout):
    shop = load(ROOT / "data" / "space.json")
    elec = json.loads((ROOT / "data" / "electrical.json").read_text())
    inv_raw = load(ROOT / "data" / "inventory.json")
    inv = {i["id"]: i for i in (inv_raw if isinstance(inv_raw, list) else inv_raw["items"])}
    lp = layout_path(layout)
    placements = load(lp)["placements"] if lp else {}
    wall = next(w for w in shop["interior_walls"] if w["id"] == elec["wall"])
    return shop, elec, inv, placements, wall


def footprint(x, y, w, d, rot):
    r = round((rot or 0) / 90) % 2
    ex, ey = (d, w) if r else (w, d)
    return x - ex / 2, x + ex / 2, y - ey / 2, y + ey / 2


def short(name, fallback, width_in):
    n = name.split(" (")[0].split(" - ")[0]
    for cand in (n, fallback):
        if text_w(cand, 5.5) < width_in - 0.05:
            return cand
    return ""


def wall_context(shop, inv, placements, wall, face):
    """Items standing against the given face: (x0, x1, z0, z1, label, dashed)."""
    yc, t = wall["y1"], wall["thickness"]
    fy = yc + t / 2 if face == "N" else yc - t / 2
    out = []

    def near(y0, y1):
        return (y0 <= fy + 6 and y1 >= fy - 0.01) if face == "N" else (y1 >= fy - 6 and y0 <= fy + 0.01)

    for it in shop.get("floor_items", []):
        if it.get("type") in ("backsplash",):
            continue
        x0, x1, y0, y1 = footprint(it["x"], it["y"], it["w"], it["d"], it.get("rot", 0))
        if near(y0, y1):
            z0 = it.get("z", 0)
            out.append((x0, x1, z0, z0 + it["h"], it.get("name", it["id"]), it["id"],
                        it.get("type") == "appliance" and "FRIDGE" in it["id"]))
    for iid, p in placements.items():
        it = inv.get(iid)
        if not it or "x" not in p:
            continue
        dims = it.get("folded") if p.get("state") == "folded" and it.get("folded") else it
        if not all(k in dims for k in ("w", "d", "h")):
            continue
        x0, x1, y0, y1 = footprint(p["x"], p["y"], dims["w"], dims["d"], p.get("rot", 0))
        if near(y0, y1):
            z0 = p.get("z", it.get("z", 0))
            out.append((x0, x1, z0, z0 + dims["h"], it.get("name", iid), iid, True))
    return out


def stations(wall):
    """Reference x stations along the wall: ends and opening edges, with names."""
    st = [(wall["x1"], "W wall"), (wall["x2"], "E corner")]
    for o in wall.get("openings", []):
        a, b = o["offset"], o["offset"] + o["w"]
        nm = {"OP-W": "W opening", "D-W": "W door", "D-E": "E door"}.get(o["id"], o["id"])
        st += [(a, nm), (b, nm)]
    return sorted(st)


def solid_sections(wall):
    edges, cur = [], wall["x1"]
    for o in sorted(wall.get("openings", []), key=lambda o: o["offset"]):
        if o["offset"] > cur:
            edges.append((cur, o["offset"]))
        cur = max(cur, o["offset"] + o["w"])
    if cur < wall["x2"]:
        edges.append((cur, wall["x2"]))
    return edges


def keepouts(wall, face):
    zones = []
    for o in wall.get("openings", []):
        sl = o.get("slide")
        if sl and sl.get("side") == face:
            if sl.get("dir", "+x") == "+x":
                zones.append((o["offset"] + o["w"], o["offset"] + o["w"] + sl["travel"] + SLAB_OVERLAP, o["h"] + 4, o["id"]))
            else:
                zones.append((o["offset"] - sl["travel"] - SLAB_OVERLAP, o["offset"], o["h"] + 4, o["id"]))
    return zones


def trim_parts(wall, face):
    """Rects (x0, x1, z0, z1) of the board-and-batten trim on this face."""
    t = wall.get("trim") or {}
    if t.get("side") != face:
        return []
    bw = t.get("batten_width", 3.5)
    parts = []
    for r in t.get("horizontal_rails", []):
        for a, b in r["spans"]:
            parts.append((a, b, r["z"], r["z"] + r["h"]))
    for v in t.get("vertical_battens", []):
        parts.append((v["x"] - bw / 2, v["x"] + bw / 2, v["z0"], v["z1"]))
    for c in t.get("door_casings", []):
        for a, b in (c["left_x"], c["right_x"]):
            parts.append((a, b, c["z0"], c["z1"]))
        h = c.get("header")
        if h:
            parts.append((h["x0"], h["x1"], h["z0"], h["z1"]))
    return parts


def studs(wall):
    """(x, z0, z1, id, kind) per stud from the wall's framing (scan-derived), or []."""
    f = wall.get("framing") or {}
    return [(s["x"], s.get("z0", 0), s.get("z1", wall["height"]), s["id"], s.get("kind", "stud"))
            for s in f.get("studs", [])]


def stud_ref(b, wall):
    """Field reference to the stud a box mounts on: 'E side of ST17' (or 'mid-bay ST16-ST17')."""
    sw = (wall.get("framing") or {}).get("stud_width", 1.5)
    st = [s for s in studs(wall) if s[1] <= b["z"] <= s[2]]
    if not st:
        return ""
    x = b["x"]
    s = min(st, key=lambda s: abs(s[0] - x))
    gap = abs(x - s[0]) - sw / 2 - BODY[b["gangs"]] / 2
    if gap <= 0.75:
        return f"{'E' if x > s[0] else 'W'} side of {s[3]}"
    lo = max((t for t in st if t[0] < x), key=lambda t: t[0], default=None)
    hi = min((t for t in st if t[0] > x), key=lambda t: t[0], default=None)
    return f"mid-bay {lo[3] if lo else '-'}/{hi[3] if hi else '-'}"


def bay_of(x, z, wall):
    st = sorted(s[0] for s in studs(wall) if s[1] <= z <= s[2])
    return (max((s for s in st if s < x), default=None), min((s for s in st if s > x), default=None))


def check(elec, wall, ctx_by_face):
    warns = []
    sw = (wall.get("framing") or {}).get("stud_width", 1.5)
    for b in elec["boxes"]:
        w, h = PLATE[b["gangs"]]
        bx0, bx1, bz0, bz1 = b["x"] - w / 2, b["x"] + w / 2, b["z"] - h / 2, b["z"] + h / 2
        bw = BODY[b["gangs"]]
        for sx, sz0, sz1, sid, _ in studs(wall):
            if sz0 <= b["z"] <= sz1 and abs(b["x"] - sx) < sw / 2 + bw / 2:
                warns.append(f"{b['id']}: box body hits stud {sid} (x ~{fmt(sx)}); mount it on the stud's side")
        for x0, x1, top, oid in keepouts(wall, b["face"]):
            if bx1 > x0 and bx0 < x1 and bz0 < top:
                warns.append(f"{b['id']}: in the {oid} barn-door slide zone (x {x0:.1f}-{x1:.1f})")
        covered = [c for c in ctx_by_face[b["face"]] if c[0] <= b["x"] <= c[1] and c[2] <= b["z"] <= c[3]]
        if not covered:
            for x0, x1, z0, z1 in trim_parts(wall, b["face"]):
                if bx1 > x0 and bx0 < x1 and bz1 > z0 and bz0 < z1:
                    warns.append(f"{b['id']}: plate overlaps trim at x {x0:.1f}-{x1:.1f}, z {z0:.1f}-{z1:.1f}")
        for o in wall.get("openings", []):
            a, c = o["offset"], o["offset"] + o["w"]
            gap = min(abs(bx0 - c), abs(a - bx1)) if not (bx1 > a and bx0 < c) else -1
            if gap < 6 and bz0 < o["h"]:
                warns.append(f"{b['id']}: {'inside' if gap < 0 else f'{gap:.1f} in from'} opening {o['id']}")
    # back-to-back: an N-face and an S-face box in the same stud bay at overlapping heights won't both fit
    # in a 3.5in cavity (new-work boxes are ~2.5-3.5in deep)
    if studs(wall):
        allb = elec["boxes"] + elec.get("existing", [])
        for a in [b for b in allb if b["face"] == "N"]:
            for c in [b for b in allb if b["face"] == "S"]:
                if abs(a["z"] - c["z"]) < BODY_H + 0.5 and bay_of(a["x"], a["z"], wall) == bay_of(c["x"], c["z"], wall) \
                        and abs(a["x"] - c["x"]) < (BODY[a["gangs"]] + BODY[c["gangs"]]) / 2 + 2:
                    warns.append(f"{a['id']} (N) and {c['id']} (S): back-to-back in the same stud bay; move one to another bay")
    return warns


# --------------------------------------------------------------- drawing E1
def dim_chain(view, xs, y, layer="DIM", size=6):
    """Horizontal chained dimension at paper height y through world x stations."""
    s = view.s
    pts = sorted(set(round(x, 3) for x in xs), key=view.px)
    for x in pts:
        p = view.px(x)
        s.line(p, y - 0.06, p, y + 0.06, lw=0.35, layer=layer)
        s.line(p - 0.03, y - 0.03, p + 0.03, y + 0.03, lw=0.8, layer=layer)
    for i, (a, b) in enumerate(zip(pts, pts[1:])):
        pa, pb = view.px(a), view.px(b)
        s.line(pa, y, pb, y, lw=0.35, layer=layer)
        label = fmt(abs(b - a))
        lift = 0.035 if text_w(label, size) < (pb - pa) - 0.04 else (0.035 if i % 2 == 0 else -0.12)
        s.text((pa + pb) / 2, y + lift, label, size=size, anchor="middle", layer=layer)


def draw_elevation(sheet, view, face, title, wall, elec, ctx, compass):
    L, H = wall["x2"], wall["height"]
    v, s = view, sheet
    # floor + wall outline (solid sections only)
    v.line(wall["x1"] - 12, 0, L + 12, 0, lw=1.6, layer="WALL")
    for a, b in solid_sections(wall):
        v.rect(a, 0, b, H, lw=1.1, layer="WALL")
    for o in wall.get("openings", []):
        a, b = o["offset"], o["offset"] + o["w"]
        if o["h"] >= H:                       # full-height opening
            v.line(a, 0, a, H, lw=1.1, layer="WALL")
            v.text((a + b) / 2, H / 2, f"OPEN ({o['id']})", size=7, anchor="middle", color=GRAY, layer="NOTE")
            v.text((a + b) / 2, H / 2 - 7, fmt(o["w"]) + " wide", size=6, anchor="middle", color=GRAY, layer="NOTE")
        else:
            v.rect(a, 0, b, o["h"], lw=0.9, layer="WALL")
            v.line(a, 0, b, o["h"], lw=0.25, color=LIGHT, layer="WALL")
            v.line(a, o["h"], b, 0, lw=0.25, color=LIGHT, layer="WALL")
            v.text((a + b) / 2, o["h"] + 1.5 if face != "N" else o["h"] - 8, f"{o['id']} {fmt(o['w'])} x {fmt(o['h'])}",
                   size=5.5, anchor="middle", color=GRAY, layer="NOTE")
    # studs (scan-derived, +/-2in): thin dashed outlines, id at the top
    sw = (wall.get("framing") or {}).get("stud_width", 1.5)
    for sx, z0, z1, sid, kind in studs(wall):
        v.rect(sx - sw / 2, z0, sx + sw / 2, z1, lw=0.25, color=STUD, dash=True, layer="STUD")
        v.text(sx, z1 - 5, sid.replace("ST", ""), size=4, anchor="middle", color=STUD, layer="STUD")
    # trim
    for x0, x1, z0, z1 in trim_parts(wall, face):
        v.rect(x0, z0, x1, z1, lw=0.2, color=LIGHT, layer="TRIM")
    # keep-outs
    for x0, x1, top, oid in keepouts(wall, face):
        v.hatch(x0, x1, 0, top, step=5, lw=0.3, color=RED, layer="KEEPOUT")
        v.rect(x0, 0, x1, top, lw=0.6, color=RED, layer="KEEPOUT")
        v.text((x0 + x1) / 2, top + 2, "DOOR SLIDE - NO BOXES", size=5.5, anchor="middle", color=RED, layer="KEEPOUT")
    # context items
    for x0, x1, z0, z1, name, iid, dashed in ctx:
        v.rect(x0, z0, x1, z1, lw=0.4, color=GRAY, dash=dashed, layer="CONTEXT")
        lab = short(name, iid, abs(v.px(x1) - v.px(x0)))
        if lab:
            v.text((x0 + x1) / 2, z0 + 2, lab, size=5.5, anchor="middle", color=GRAY, layer="CONTEXT")
    # existing devices
    for b in elec.get("existing", []):
        if b["face"] != face:
            continue
        w, h = PLATE[b["gangs"]]
        v.rect(b["x"] - w / 2, b["z"] - h / 2, b["x"] + w / 2, b["z"] + h / 2, lw=0.5, color=GRAY, layer="EXISTING")
        v.text(b["x"], b["z"] - h / 2 - 4, b["id"], size=5.5, anchor="middle", color=GRAY, layer="EXISTING")
    # new boxes + tags
    boxes = [b for b in elec["boxes"] if b["face"] == face]
    for b in boxes:
        w, h = PLATE[b["gangs"]]
        fill = "#ffffff" if b["kind"] == "switch" else "#222222"
        if b.get("recessed"):
            v.rect(b["x"] - w / 2 - 1, b["z"] - h / 2 - 1, b["x"] + w / 2 + 1, b["z"] + h / 2 + 1, lw=0.4, dash=True,
                   layer="BOX")
        v.rect(b["x"] - w / 2, b["z"] - h / 2, b["x"] + w / 2, b["z"] + h / 2, lw=0.6, fill=fill, layer="BOX")
        if b["kind"] == "switch":
            v.text(b["x"], b["z"] - 1.3, "S", size=4.5, anchor="middle", layer="BOX")
        if b.get("lv"):
            tx = b["x"] + (w / 2 + 3.2) * (-1 if v.mirror else 1)
            v.line(tx - 1.6, b["z"] - 1.4, tx + 1.6, b["z"] - 1.4, lw=0.5, color=BLUE, layer="LV")
            v.line(tx - 1.6, b["z"] - 1.4, tx, b["z"] + 1.6, lw=0.5, color=BLUE, layer="LV")
            v.line(tx + 1.6, b["z"] - 1.4, tx, b["z"] + 1.6, lw=0.5, color=BLUE, layer="LV")
        top = v.py(b["z"] + h / 2 + (1 if b.get("recessed") else 0)) + 0.05
        px = v.px(b["x"])
        s.text(px, top, f"@{fmt(b['z'])}", size=5, anchor="middle", layer="TAG")
        s.text(px, top + 0.085, "·".join(str(c) for c in b["circuits"]), size=6.5, anchor="middle", bold=True,
               color=BLUE, layer="TAG")
        s.text(px, top + 0.185, b["id"], size=5.5, anchor="middle", layer="TAG")
    # dimensions: sections + per-section box chains (high row / low row)
    yb = v.py(0)
    dim_chain(v, [x for x, _ in stations(wall)], yb - 0.35)
    dim_chain(v, [wall["x1"], wall["x2"]], yb - 0.65)
    yt = v.py(H)
    for a, b in solid_sections(wall):
        hi = [x["x"] for x in boxes if a <= x["x"] <= b and x["z"] >= 40]
        lo = [x["x"] for x in boxes if a <= x["x"] <= b and x["z"] < 40]
        if hi:
            dim_chain(v, [a, b] + hi, yt + 0.3)
        if lo:
            dim_chain(v, [a, b] + lo, yt + 0.62)
    left_x = v.px(wall["x2"] if v.mirror else wall["x1"])
    s.text(left_x - 0.1, yt + 0.29, "BOXES 40\"+", size=5.5, anchor="end", color=GRAY, layer="NOTE")
    s.text(left_x - 0.1, yt + 0.61, "BOXES <40\"", size=5.5, anchor="end", color=GRAY, layer="NOTE")
    s.text(left_x - 0.1, yb - 0.37, "OPENINGS", size=5.5, anchor="end", color=GRAY, layer="NOTE")
    s.text(left_x - 0.1, yb - 0.67, "OVERALL", size=5.5, anchor="end", color=GRAY, layer="NOTE")
    # compass + title
    lo_x, hi_x = sorted((v.px(wall["x1"]), v.px(wall["x2"])))
    s.text(lo_x, yt + 0.95, compass[0], size=8, bold=True, layer="NOTE")
    s.text(hi_x, yt + 0.95, compass[1], size=8, bold=True, anchor="end", layer="NOTE")
    s.text(lo_x, yb - 1.15, title, size=12, bold=True, layer="NOTE")
    s.text(lo_x, yb - 1.4, "SCALE: 1/2\" = 1'-0\"   Dimensions to box centres; @ = height of box centre above slab",
           size=7, color=GRAY, layer="NOTE")


def title_block(sheet, number, title, layout, warn_count):
    s = sheet
    s.rect(0.5, 0.5, SHEET_W - 1, SHEET_H - 1, lw=1.5, layer="BORDER")
    x0 = SHEET_W - 4.5
    s.line(x0, 0.5, x0, SHEET_H - 0.5, lw=1.0, layer="BORDER")
    tx = x0 + 0.2
    s.text(tx, SHEET_H - 1.1, "SHOP", size=16, bold=True, layer="TITLE")
    s.text(tx, SHEET_H - 1.45, "Accent wall (IW-1) electrical", size=10, layer="TITLE")
    s.rect(tx, SHEET_H - 2.25, 3.9, 0.5, lw=0.8, color=RED, layer="TITLE")
    s.text(tx + 1.95, SHEET_H - 2.07, "DRAFT - NOT FOR CONSTRUCTION", size=9, bold=True, anchor="middle", color=RED,
           layer="TITLE")
    rows = [("Sheet", title), ("Date", date.today().isoformat()), ("Scale", "1/2\" = 1'-0\" on 36x24 (ARCH D)"),
            ("", "Half-size on 11x17 = 1/4\" = 1'-0\""), ("Context layout", layout or "none"),
            ("Source", "data/space.json, data/electrical.json"), ("Generator", "scripts/blueprint.py (make blueprint)"),
            ("Checks", f"{warn_count} warning(s)")]
    y = SHEET_H - 2.8
    for k, val in rows:
        s.text(tx, y, k, size=6.5, color=GRAY, layer="TITLE")
        s.text(tx + 1.0, y, val, size=6.5, layer="TITLE")
        y -= 0.22
    # legend
    y -= 0.25
    s.text(tx, y, "LEGEND", size=9, bold=True, layer="TITLE")
    y -= 0.32
    items = [("rec", "Receptacle box (plate size, to scale)"), ("sw", "Switch box"), ("rcs", "Recessed box (TV kit)"),
             ("ex", "Existing device"), ("lv", "Low voltage (Cat6 / conduit)"), ("ko", "Barn-door slide: no boxes"),
             ("ctx", "Cabinets / equipment (dashed = movable)"), ("trim", "Board-and-batten trim (N face)"),
             ("stud", "Stud, ID no. (LiDAR, +/-2in; tape-check)")]
    for kind, label in items:
        cy = y + 0.04
        if kind in ("rec", "rcs"):
            s.rect(tx + 0.1, cy - 0.06, 0.12, 0.12, lw=0.6, fill="#222222", layer="TITLE")
            if kind == "rcs":
                s.rect(tx + 0.06, cy - 0.1, 0.2, 0.2, lw=0.4, dash=True, layer="TITLE")
        elif kind == "sw":
            s.rect(tx + 0.1, cy - 0.06, 0.12, 0.12, lw=0.6, fill="#ffffff", layer="TITLE")
        elif kind == "ex":
            s.rect(tx + 0.1, cy - 0.06, 0.12, 0.12, lw=0.5, color=GRAY, layer="TITLE")
        elif kind == "lv":
            s.line(tx + 0.08, cy - 0.05, tx + 0.24, cy - 0.05, lw=0.6, color=BLUE, layer="TITLE")
            s.line(tx + 0.08, cy - 0.05, tx + 0.16, cy + 0.08, lw=0.6, color=BLUE, layer="TITLE")
            s.line(tx + 0.24, cy - 0.05, tx + 0.16, cy + 0.08, lw=0.6, color=BLUE, layer="TITLE")
        elif kind == "ko":
            s.rect(tx + 0.05, cy - 0.08, 0.25, 0.16, lw=0.6, color=RED, layer="TITLE")
            s.line(tx + 0.05, cy - 0.08, tx + 0.21, cy + 0.08, lw=0.3, color=RED, layer="TITLE")
            s.line(tx + 0.14, cy - 0.08, tx + 0.30, cy + 0.08, lw=0.3, color=RED, layer="TITLE")
        elif kind == "ctx":
            s.rect(tx + 0.05, cy - 0.08, 0.25, 0.16, lw=0.4, color=GRAY, dash=True, layer="TITLE")
        elif kind == "trim":
            s.rect(tx + 0.05, cy - 0.08, 0.25, 0.16, lw=0.3, color=LIGHT, layer="TITLE")
        elif kind == "stud":
            s.rect(tx + 0.15, cy - 0.1, 0.05, 0.2, lw=0.4, color=STUD, dash=True, layer="TITLE")
        s.text(tx + 0.45, y, label, size=6.5, layer="TITLE")
        y -= 0.27
    y -= 0.05
    s.text(tx, y, "Tag (above each box):", size=6.5, color=GRAY, layer="TITLE")
    s.text(tx + 1.6, y + 0.17, "K2", size=5.5, anchor="middle", layer="TITLE")
    s.text(tx + 1.6, y + 0.07, "7", size=6.5, anchor="middle", bold=True, color=BLUE, layer="TITLE")
    s.text(tx + 1.6, y - 0.03, "@3'-6\"", size=5, anchor="middle", layer="TITLE")
    s.text(tx + 1.9, y + 0.17, "box ID", size=5.5, color=GRAY, layer="TITLE")
    s.text(tx + 1.9, y + 0.07, "circuit number(s)", size=5.5, color=GRAY, layer="TITLE")
    s.text(tx + 1.9, y - 0.03, "height to centre", size=5.5, color=GRAY, layer="TITLE")
    # notes
    y -= 0.5
    s.text(tx, y, "GENERAL NOTES", size=9, bold=True, layer="TITLE")
    notes = [
        "1. All 120V receptacles GFCI protected (detached building).",
        "   Use GFCI/dual-function breakers for boxes behind",
        "   appliances and TVs.",
        "2. One home run per circuit, no shared neutrals. 20A /",
        "   12 AWG unless noted; 10 AWG for 1, 2, 13 (long runs);",
        "   15A / 14 AWG for 9. See schedule (E2).",
        "3. Countertop circuits 7 and 8 alternate and feed nothing",
        "   else (no lighting). No counter point > 24\" from a box.",
        "4. Hatched zones: barn-door slab path. Before rough-in,",
        "   slide each door fully open and mark its edge.",
        "5. Keep plates clear of trim battens/rails (N face).",
        "6. Cabinets from the cabinet order; TV, console, existing",
        "   devices and studs from the LiDAR scan (+/-2\"). Boxes",
        "   nail to the named stud side (E2 'Mount'); move the box",
        "   with the real stud. Studs are open on the S face.",
        "7. Low voltage: Cat6 home-run to the network location;",
        "   2\" conduit from T1 down to T3 behind the console.",
        "8. Confirm all requirements with the local inspector.",
    ]
    y -= 0.3
    for n in notes:
        s.text(tx, y, n, size=6.5, layer="TITLE")
        y -= 0.19
    s.rect(x0, 0.5, 4.0, 1.0, lw=1.0, layer="BORDER")
    s.text(x0 + 2.0, 0.8, number, size=28, bold=True, anchor="middle", layer="TITLE")


def sheet_e1(shop, elec, inv, placements, wall, layout, warns):
    s = Sheet("E1")
    ctx = {f: wall_context(shop, inv, placements, wall, f) for f in ("N", "S")}
    for c in elec.get("context", []):
        ctx[c["face"]].append((c["x0"], c["x1"], c["z0"], c["z1"], c["name"], c["name"], False))
    ox = 1.55
    draw_elevation(s, View(s, ox, 14.2, wall["x2"], mirror=True), "N",
                   "1   NORTH FACE - as seen standing in the kitchen / TV side", wall, elec, ctx["N"], ("EAST", "WEST"))
    draw_elevation(s, View(s, ox, 3.4, wall["x2"], mirror=False), "S",
                   "2   SOUTH FACE - as seen standing in the gym / storage side", wall, elec, ctx["S"], ("WEST", "EAST"))
    title_block(s, "E1", "E1 - Accent wall elevations", layout, len(warns))
    return s, ctx


# --------------------------------------------------------------- drawing E2
def table(s, x, y, cols, rows, size=7.5, rh=0.23, title=None):
    if title:
        s.text(x, y + 0.2, title, size=11, bold=True, layer="TABLE")
    total = sum(w for _, w in cols)
    s.rect(x, y - rh * (len(rows) + 1) + 0.06, total, rh * (len(rows) + 1), lw=0.8, layer="TABLE")
    cx = x
    for name, w in cols:
        s.text(cx + 0.06, y - rh + 0.11, name, size=size, bold=True, layer="TABLE")
        cx += w
    s.line(x, y - rh + 0.06, x + total, y - rh + 0.06, lw=0.6, layer="TABLE")
    for i, r in enumerate(rows):
        ry = y - rh * (i + 2) + 0.11
        if i % 2:
            s.rect(x, ry - 0.05, total, rh, lw=0, fill="#f2f2f2", color="#f2f2f2", layer="TABLE")
        cx = x
        for (name, w), val in zip(cols, r):
            txt = str(val)
            while txt and text_w(txt, size) > w - 0.1:
                txt = txt[:-2] + "…"
            s.text(cx + 0.06, ry, txt, size=size, layer="TABLE")
            cx += w
    return y - rh * (len(rows) + 1)


def nearest_ref(x, refs):
    best = min(refs, key=lambda r: abs(r[0] - x))
    d = x - best[0]
    return f"{fmt(abs(d))} {'E' if d > 0 else 'W'} of {best[1]}"


def sheet_e2(elec, wall, layout, warns):
    s = Sheet("E2")
    boxes = elec["boxes"]
    by_c = {}
    for b in boxes:
        for c in b["circuits"]:
            by_c.setdefault(c, []).append(b["id"])
    rows = [(c["n"], c["name"], f"{c['amps']}A", f"{c['awg']} AWG", c["gfci"], ", ".join(by_c.get(c["n"], [])),
             c.get("note", "")) for c in elec["circuits"]]
    y = table(s, 1.0, 22.6, [("#", 0.4), ("Circuit", 3.0), ("Breaker", 0.8), ("Wire", 0.9), ("GFCI", 0.8),
                             ("Boxes", 2.6), ("Note", 3.2)], rows, title="CIRCUIT SCHEDULE")
    s.text(1.0, y - 0.2, f"{len(elec['circuits'])} home runs from the subpanel. Breaker sizes per the electrician / load calc.",
           size=7, color=GRAY, layer="TABLE")
    refs = stations(wall)
    rows = []
    for b in sorted(boxes, key=lambda b: (b["face"], b["x"])):
        kind = f"{b['gangs']}-gang {b['kind']}" + (", recessed" if b.get("recessed") else "")
        rows.append((b["id"], b["face"], fmt(b["x"]), nearest_ref(b["x"], refs), stud_ref(b, wall), fmt(b["z"]), kind,
                     " · ".join(str(c) for c in b["circuits"]), b.get("lv", ""), b.get("note", "")))
    y = table(s, 1.0, y - 0.9, [("Box", 0.5), ("Face", 0.5), ("x from W wall", 1.0), ("Field reference", 2.1),
                                ("Mount", 1.5), ("Height (ctr)", 0.95), ("Box", 1.8), ("Circuits", 0.8),
                                ("Low voltage", 1.9), ("Note", 8.5)], rows, title="BOX SCHEDULE")
    rows = [(b["id"], b["face"], fmt(b["x"]), nearest_ref(b["x"], refs), fmt(b["z"]), b.get("note", ""))
            for b in elec.get("existing", [])]
    y = table(s, 1.0, y - 0.9, [("Box", 0.5), ("Face", 0.5), ("x from W wall", 1.0), ("Field reference", 2.1),
                                ("Height (ctr)", 0.95), ("Note", 6.0)], rows, title="EXISTING DEVICES")
    s.text(1.0, y - 0.6, "CHECKS", size=11, bold=True, layer="TABLE")
    for i, w in enumerate(warns or ["No boxes in door slide zones, on trim, or within 6\" of an opening."]):
        s.text(1.0, y - 0.9 - i * 0.2, ("! " if warns else "") + w, size=7.5, color=RED if warns else BLACK, layer="TABLE")
    title_block(s, "E2", "E2 - Circuit + box schedules", layout, len(warns))
    return s


# ------------------------------------------------------------------ backends
def write_svg(sheet, path):
    def esc(t):
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    k = 100
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{SHEET_W}in" height="{SHEET_H}in" '
           f'viewBox="0 0 {SHEET_W * k:.0f} {SHEET_H * k:.0f}" font-family="Helvetica, Arial, sans-serif">',
           '<rect width="100%" height="100%" fill="#ffffff"/>']
    for kind, a in sheet.items:
        if kind == "line":
            d = ' stroke-dasharray="6 4"' if a["dash"] else ""
            out.append(f'<line x1="{a["x1"] * k:.2f}" y1="{(SHEET_H - a["y1"]) * k:.2f}" x2="{a["x2"] * k:.2f}" '
                       f'y2="{(SHEET_H - a["y2"]) * k:.2f}" stroke="{a["color"]}" stroke-width="{a["lw"] / 72 * k:.3f}"{d}/>')
        elif kind == "rect":
            d = ' stroke-dasharray="6 4"' if a["dash"] else ""
            sw = a["lw"] / 72 * k
            out.append(f'<rect x="{a["x"] * k:.2f}" y="{(SHEET_H - a["y"] - a["h"]) * k:.2f}" width="{a["w"] * k:.2f}" '
                       f'height="{a["h"] * k:.2f}" fill="{a["fill"] or "none"}" '
                       f'stroke="{a["color"] if sw else "none"}" stroke-width="{sw:.3f}"{d}/>')
        else:
            x, y = a["x"] * k, (SHEET_H - a["y"]) * k
            anc = {"start": "start", "middle": "middle", "end": "end"}[a["anchor"]]
            rot = f' transform="rotate({-a["rot"]} {x:.2f} {y:.2f})"' if a["rot"] else ""
            fw = ' font-weight="bold"' if a["bold"] else ""
            out.append(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{a["size"] / 72 * k:.2f}" text-anchor="{anc}" '
                       f'fill="{a["color"]}"{fw}{rot}>{esc(a["s"])}</text>')
    out.append("</svg>")
    path.write_text("\n".join(out))


def write_pdf(sheets, path):
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=(SHEET_W * 72, SHEET_H * 72))
    c.setTitle("Shop - accent wall electrical")
    for sh in sheets:
        for kind, a in sh.items:
            if kind == "line":
                c.setStrokeColor(HexColor(a["color"]))
                c.setLineWidth(a["lw"])
                c.setDash(4, 3) if a["dash"] else c.setDash()
                c.line(a["x1"] * 72, a["y1"] * 72, a["x2"] * 72, a["y2"] * 72)
            elif kind == "rect":
                c.setStrokeColor(HexColor(a["color"]))
                c.setLineWidth(a["lw"] or 0.01)
                c.setDash(4, 3) if a["dash"] else c.setDash()
                if a["fill"]:
                    c.setFillColor(HexColor(a["fill"]))
                c.rect(a["x"] * 72, a["y"] * 72, a["w"] * 72, a["h"] * 72, stroke=1 if a["lw"] else 0,
                       fill=1 if a["fill"] else 0)
            else:
                c.setFillColor(HexColor(a["color"]))
                c.setFont("Helvetica-Bold" if a["bold"] else "Helvetica", a["size"])
                c.saveState()
                c.translate(a["x"] * 72, a["y"] * 72)
                if a["rot"]:
                    c.rotate(a["rot"])
                {"start": c.drawString, "middle": c.drawCentredString, "end": c.drawRightString}[a["anchor"]](0, 0, a["s"])
                c.restoreState()
        c.showPage()
    c.save()


def write_dxf(sheets, path):
    import ezdxf
    from ezdxf.enums import TextEntityAlignment

    f = 1 / SCALE                          # paper inch -> model inch (true size for the elevations)
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 1
    doc.header["$LTSCALE"] = 6
    msp = doc.modelspace()

    def rgb(h):
        return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))

    def attrs(a):
        if a["layer"] not in doc.layers:
            doc.layers.add(a["layer"])
        d = {"layer": a["layer"]}
        if a.get("dash"):
            d["linetype"] = "DASHED"
        return d

    for i, sh in enumerate(sheets):
        dx = i * (SHEET_W + 2) * f
        for kind, a in sh.items:
            if kind == "line":
                e = msp.add_line((a["x1"] * f + dx, a["y1"] * f), (a["x2"] * f + dx, a["y2"] * f), dxfattribs=attrs(a))
            elif kind == "rect":
                x, y, w, h = a["x"] * f + dx, a["y"] * f, a["w"] * f, a["h"] * f
                pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
                if a["fill"] and a["fill"].lower() not in ("#ffffff", "#f2f2f2"):
                    hh = msp.add_hatch(dxfattribs={"layer": attrs(a)["layer"]})
                    hh.paths.add_polyline_path(pts, is_closed=True)
                    hh.rgb = rgb(a["fill"])
                if not a["lw"]:
                    continue
                e = msp.add_lwpolyline(pts, close=True, dxfattribs=attrs(a))
            else:
                e = msp.add_text(a["s"], height=a["size"] / 72 * f * 0.72, rotation=a["rot"], dxfattribs=attrs(a))
                al = {"start": TextEntityAlignment.LEFT, "middle": TextEntityAlignment.CENTER,
                      "end": TextEntityAlignment.RIGHT}[a["anchor"]]
                e.set_placement((a["x"] * f + dx, a["y"] * f), align=al)
            e.rgb = rgb(a["color"])
    doc.saveas(path)


# ----------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--layout", default="option-b", help="layout for movable items against the wall (context only)")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    shop, elec, inv, placements, wall = load_inputs(args.layout)
    ctx = {f: wall_context(shop, inv, placements, wall, f) for f in ("N", "S")}
    warns = check(elec, wall, ctx)
    e1, _ = sheet_e1(shop, elec, inv, placements, wall, args.layout, warns)
    e2 = sheet_e2(elec, wall, args.layout, warns)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    write_pdf([e1, e2], out / "accent-wall.pdf")
    write_svg(e1, out / "accent-wall-E1.svg")
    write_svg(e2, out / "accent-wall-E2.svg")
    write_dxf([e1, e2], out / "accent-wall.dxf")
    for w in warns:
        print("WARN", w)
    print(f"wrote {out}/accent-wall.pdf, -E1.svg, -E2.svg, .dxf ({len(warns)} warning(s))")


if __name__ == "__main__":
    main()
