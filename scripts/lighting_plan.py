"""Shared reader for data/lighting.json (plain Python, no Blender).

Used by lighting.py (simulation), build_scene.py (draws fixtures per layout), render.py (lights a plan + scene)
and validate.py. Units: inches in the shop frame (x east from the W wall, y north from the S wall, z up from the slab).

A layout picks a plan with an optional block:  "lighting": {"plan": "value", "scene": "game_night"}
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "lighting.json"
CASE_TOL = 6.0  # in: table centre must sit this close to a plan case's centre for its heads to apply


def load(path=PATH):
    return json.loads(Path(path).read_text())


def dumps(obj, indent=2):
    """JSON with short lists of numbers kept on one line (coordinates stay readable)."""
    def enc(o, lvl):
        pad, pad1 = " " * (indent * lvl), " " * (indent * (lvl + 1))
        if isinstance(o, dict):
            if not o:
                return "{}"
            return "{\n" + ",\n".join(f"{pad1}{json.dumps(k)}: {enc(v, lvl + 1)}" for k, v in o.items()) + f"\n{pad}}}"
        if isinstance(o, (list, tuple)):
            if all(isinstance(v, (int, float, str, bool)) or v is None for v in o) and len(json.dumps(o)) <= 100:
                return json.dumps(list(o))
            if all(isinstance(v, (list, tuple)) and all(isinstance(w, (int, float)) for w in v) for v in o) and len(json.dumps(o)) <= 100:
                return json.dumps([list(v) for v in o])
            if not o:
                return "[]"
            return "[\n" + ",\n".join(pad1 + enc(v, lvl + 1) for v in o) + f"\n{pad}]"
        return json.dumps(o)
    return enc(obj, 0) + "\n"


def save(obj, path=PATH):
    Path(path).write_text(dumps(obj))


# ---------------------------------------------------------------- colour
def _g(x, mu, s1, s2):
    s = s1 if x < mu else s2
    return math.exp(-0.5 * ((x - mu) / s) ** 2)


def cct_rgb(T):
    """Blackbody colour as linear Rec.709, max channel 1 (CIE 1931 CMF fit by Wyman et al. 2013)."""
    X = Y = Zc = 0.0
    for lam in range(380, 781, 5):
        lm = lam * 1e-9
        B = 1.0 / (lm ** 5 * (math.exp(1.4388e-2 / (lm * T)) - 1))
        xb = 1.056 * _g(lam, 599.8, 37.9, 31.0) + 0.362 * _g(lam, 442.0, 16.0, 26.7) - 0.065 * _g(lam, 501.1, 20.4, 26.2)
        yb = 0.821 * _g(lam, 568.8, 46.9, 40.5) + 0.286 * _g(lam, 530.9, 16.3, 31.1)
        zb = 1.217 * _g(lam, 437.0, 11.8, 36.0) + 0.681 * _g(lam, 459.0, 26.0, 13.8)
        X += B * xb
        Y += B * yb
        Zc += B * zb
    X, Zc = X / Y, Zc / Y
    r = 3.2406 * X - 1.5372 - 0.4986 * Zc
    g = -0.9689 * X + 1.8758 + 0.0415 * Zc
    b = 0.0557 * X - 0.2040 + 1.0570 * Zc
    c = [max(v, 0.0) for v in (r, g, b)]
    mx = max(c)
    return tuple(v / mx for v in c)


def lum(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


# ---------------------------------------------------------------- plan pieces
def highbays(data, shop):
    """Existing high bays: positions from space.json (the source of truth), the rest from lighting.json."""
    pos = {it["id"]: it for it in shop["ceiling_items"]}
    out = []
    for e in data["existing"]:
        it = pos.get(e["shop_ref"])
        if it is None:
            continue
        out.append(dict(e, x=float(it["x"]), y=float(it["y"]), z=float(it["z"])))
    return out


def puck_points(layer):
    pts = []
    for col in layer["columns"]:
        y = layer["y0"]
        while y <= layer["y1"] + 1e-6:
            pts.append((col["x"], y, layer["z"]))
            y += layer["spacing"]
    return pts


def layout_choice(data, layout, plan=None, scene=None):
    """(plan id, scene id) from explicit args, then the layout's "lighting" block, then the file defaults."""
    lc = (layout or {}).get("lighting", {})
    return (plan or lc.get("plan") or data["meta"]["default_plan"],
            scene or lc.get("scene") or data["meta"]["default_scene"])


def table_case(data, plan_id, layout):
    """Which optimised head set fits this layout's table: (case id, case dict, message)."""
    tb = data["plans"][plan_id].get("table")
    if not tb:
        return None, None, "plan has no table spots"
    pl = (layout or {}).get("placements", {}).get(tb["item"])
    if pl is None:
        return None, None, f"layout doesn't place {tb['item']}"
    rot = pl.get("rot", 0) % 180
    for cid, c in tb["cases"].items():
        cx, cy = c["table_center"]
        if math.hypot(pl["x"] - cx, pl["y"] - cy) <= CASE_TOL and abs(rot - c["rot"] % 180) < 1:
            return cid, c, ""
    return None, None, (f"{tb['item']} at ({pl['x']}, {pl['y']}) rot {pl.get('rot', 0)} matches no optimised case "
                        f"({', '.join(f'{k}: {v['table_center']} rot {v['rot']}' for k, v in tb['cases'].items())}); re-run `make lighting`")


def sources(data, shop, plan_id, layout):
    """Every light in a plan for a layout: list of dicts and a list of warnings.

    spot:  {id, layer, kind:'spot', fixture, pos, aim, cct}
    strip: {id, layer, kind:'strip', p0, p1, normal, lm, cct}
    """
    plan = data["plans"][plan_id]
    fx = data["fixture_types"]
    out, warn = [], []
    for lid in plan["layers"]:
        lay = data["layers"][lid]
        k = lay["kind"]
        if k == "existing":
            for h in highbays(data, shop):
                if h["layer"] == lid:
                    out.append({"id": h["id"], "layer": lid, "kind": "spot", "fixture": h["fixture"], "pos": (h["x"], h["y"], h["z"]),
                                "aim": (h["x"], h["y"], 0.0), "cct": fx[h["fixture"]]["cct"]})
        elif k == "table":
            cid, case, msg = table_case(data, plan_id, layout)
            if case is None:
                warn.append(f"{plan_id}: table spots skipped: {msg}")
                continue
            fk = data["table_packages"][plan["table"]["package"]]["fixture"]
            for i, h in enumerate(case["heads"]):
                out.append({"id": f"TBL-{i}", "layer": lid, "kind": "spot", "fixture": fk, "pos": tuple(h["mount"]),
                            "aim": tuple(h["aim"]), "cct": h["cct"], "case": cid, "dim": case.get("dim", 1.0)})
        elif k == "strip":
            for ri, r in enumerate(lay["runs"]):
                p0, p1 = r["p0"], r["p1"]
                length = math.dist(p0, p1)
                out.append({"id": f"{lid}-{ri}", "layer": lid, "kind": "strip", "p0": tuple(p0), "p1": tuple(p1),
                            "normal": tuple(lay["normal"]), "lm": lay["lm_per_ft"] * length / 12.0, "cct": lay["cct"]})
        elif k == "puck_grid":
            for i, p in enumerate(puck_points(lay)):
                out.append({"id": f"PUCK-{i:02d}", "layer": lid, "kind": "spot", "fixture": lay["fixture"], "pos": p,
                            "aim": (p[0], p[1], 0.0), "cct": fx[lay["fixture"]]["cct"]})
        elif k == "spots":
            for i, s in enumerate(lay["spots"]):
                out.append({"id": f"{lid}-{i}", "layer": lid, "kind": "spot", "fixture": lay["fixture"], "pos": tuple(s["mount"]),
                            "aim": tuple(s["aim"]), "cct": fx[lay["fixture"]]["cct"]})
        # kind "golf": simulated in lighting.py only (not drawn yet)
    return out, warn


def scene_level(data, scene_id, layer):
    """(fraction 0-1, rgb or None, cct or None) for a layer in a scene."""
    s = data["scenes"][scene_id]["levels"].get(layer, 0)
    s = {"f": float(s)} if not isinstance(s, dict) else s
    return float(s.get("f", 0.0)), (tuple(s["rgb"]) if "rgb" in s else None), s.get("cct")


def circuit_mix(ccts, target):
    """Per-head dim for fixed-CCT heads on two circuits to hit `target` K (mired mix, brightest circuit at 100%)."""
    u = sorted(set(ccts))
    if len(u) == 1:
        return [1.0] * len(ccts)
    lo, hi = u[0], u[-1]
    t = min(max(target, lo), hi)
    m_lo, m_hi, m_t = 1e6 / lo, 1e6 / hi, 1e6 / t
    w_hi = (m_lo - m_t) / (m_lo - m_hi)
    w_lo = 1 - w_hi
    s = max(w_lo, w_hi)
    return [(w_hi if c == hi else w_lo) / s for c in ccts]


def peak_cd(fx):
    """Peak intensity (cd) for drawing a fixture: catalogue peak, Lambertian for cosine profiles, else lumens over the beam cone."""
    if fx.get("peak"):
        return float(fx["peak"])
    if fx.get("profile") == "cosine":
        return fx["lm"] / math.pi
    half = math.radians(fx.get("beam", 60) / 2)
    return fx["lm"] * fx.get("in_beam", 0.6) / (2 * math.pi * (1 - math.cos(half)))
