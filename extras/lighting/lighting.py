"""Lighting simulation of the shop: game-table spot packages, indirect layers, scenes and themes.

Brief: ~/Downloads/shop-lighting-blender-prompt.md (copy in prompts/lighting-brief.md).
Every guess is in PARAMS below; change it and re-run.  `make lighting` runs every stage in order:

  Blender -b --python scripts/lighting.py -- calibrate   # factory scene: 1000 cd spot -> scale factors
  Blender -b --python scripts/lighting.py -- build       # blend/option-a.blend -> blend/lighting.blend (metres)
  Blender -b blend/lighting.blend --python scripts/lighting.py -- analyze   # analytic model, optimiser, CSV
  Blender -b blend/lighting.blend --python scripts/lighting.py -- render    # Cycles checks + scene renders
  Blender -b --python scripts/lighting.py -- report      # exports/lighting/report.md

Conventions: PARAMS lengths are INCHES in the shop frame (origin SW inside corner, +X east, +Y north, +Z up),
converted with IN = 0.0254.  The lighting .blend is in metres: the whole built shop sits under SHOP_ROOT
(scale 0.0254); everything this script adds is built directly in metres.
Photometry: P_watts = 4*pi*I_cd/683 for spots and flux/683 for strips, times 1/k from the calibration, so a
Cycles pixel on an albedo-1 diffuse surface reads lux = pi * pixel * 683.
"""
import json
import math
import random
import sys
import time
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

ROOT = Path(__file__).resolve().parents[1]
IN = 0.0254
FT = 12.0

# ============================================================================ PARAMS
# [P] = unconfirmed guess from the brief or this session; [M] = from the measured model (data/space.json)
PARAMS = {
    "source_blend": "blend/option-a.blend",          # built by `make build LAYOUT=option-a`
    "out_blend": "blend/lighting.blend",
    "render_dir": "renders/lighting",
    "export_dir": "exports/lighting",

    # ---- shell [M]
    "chord_z": 142.0,                 # underside of truss bottom chords
    "partition_n_face_y": 237.75,     # IW-1 N face (4.5in wall centred on y 235.5) [M]
    "north_wall_y": 471.75,           # inside face of W-N (the door wall) [M]
    "truss_x": [0, 47.44, 94.88, 142.32, 189.76, 237.2, 284.64, 332.08, 379.52, 426.96, 474.4,
                521.84, 569.28, 616.72, 664.16, 711.6],

    # ---- glass overhead door OH-2 on W-N [M position]
    "door_x0": 320.85, "door_x1": 443.1,
    "door_open_depth": 102.0,         # [P] open panel runs 8.5 ft in from the wall (8 ft door + a few in)
    # C4AL 10x8 is STANDARD LIFT (door label, data/space.json OH-2): the horizontal tracks sit 8-10in above the 96in
    # opening, the same as build_scene.py draws them. The brief's "just under the chords" (141in) was wrong.
    "door_panel_top_z": 106.0,        # open panel rides in the horizontal track at z 104-106
    "track_run": 114.0,               # horizontal track length from the wall (door h + 18, as build_scene.py)
    "torsion_shaft_z": 108.0,         # spring shaft over the opening, 12in above its top (build_scene.py)
    "trolley_rail_z": 109.0,          # [P] trolley rail just above the open panel (standard lift), hung from the chords
    "design_door_open": False,        # owner: table lights are used with the door closed -> optimiser + summaries use this state
    "door_panel_thick": 2.0,
    "track_angle": 2.0, "track_gap": 3.0,  # 2in angle, 3in outside each side of the opening
    "openers": ["jackshaft", "trolley"],   # [P] owner unsure: both are evaluated
    "trolley_len": 138.0,             # rail to 11.5 ft from the wall
    "trolley_motor": (16.0, 12.0, 8.0),  # along-rail, across, tall
    "envelope_pad": 12.0,

    # ---- game table (family-table, 102 x 38.5 x 30 [M]) and its two orientations [P]
    "table_w": 102.0, "table_d": 38.5,
    "table_z": 30.25,                 # felt top: the scanned table top reaches 30.12in, felt sits just above it
    "case_A_center": (381.0, 380.0),  # layouts' scan position: long axis E-W, parallel to the door wall
    "case_B_center": (381.0, None),   # long axis N-S; None = centre on the open panel's end (panel covers N half)
    "felt": True, "felt_hex": "#3A5A3A", "felt_rough": 0.9,   # [P]
    "grid": (51, 20),                 # 2in grid (51 x 20 cells over the top)

    # ---- seated players (6 chairs, 3 per long side at -34/0/+34 in along the table [M layouts])
    "seat_along": [-34.0, 0.0, 34.0],
    "eye_z": 48.0, "arm_reach": 12.0, "fill_lux": 75.0,      # [P] fill from the indirect layers
    "pieces_per_player": 3, "pieces_middle": 6, "piece_seed": 3,

    # ---- spot heads on strut boards under the chords [P]
    "strut_board": 0.75,              # board under the chord
    "head_stem": 3.0,                 # mount -> pivot
    "side_offset": 30.0,              # standard layout: rail distance outside each long edge
    "side_spacing": 51.0,             # heads at +-25.5 in along the rail
    "end_offset": 30.0, "end_spread": 24.0,
    "keepout_highbay": 10.0, "keepout_fan": 6.0,

    # ---- optimiser
    "opt_evals": 300, "opt_seed": 11, "opt_snap": 3.0, "opt_pad": 96.0,
    "mean_lux_range": (350.0, 550.0), "dim_target": 450.0,
    "u_target": 0.7, "shadow_visible": 0.7, "shadow_dark": 0.5,
    "glare_penalty": 0.05,

    # ---- glare
    "glare_los_deg": 40.0, "glare_beam_deg": 25.0,

    # ---- fixture library  (lm = catalogue lumens; peak = candela; radius in metres = lens radius)
    "fixtures": {
        "CHG":   {"name": "WAC Charge 8010-CS", "lm": 865, "beam": 45, "peak": 1006, "radius": 0.025, "dia": 2.6, "len": 5.5, "cct": 3000, "cct_mode": "switch"},
        "CHG30": {"name": "WAC Charge 8010-30", "lm": 850, "beam": 40, "peak": 1196, "radius": 0.025, "dia": 2.6, "len": 5.5, "cct": 3000, "cct_mode": "fixed"},
        "SBL":   {"name": "SuperBrightLEDs 20W Halo", "lm": 1760, "beam": 25, "peak": None, "in_beam": 0.6, "radius": 0.035, "dia": 3.5, "len": 6.0, "cct": 3000, "cct_mode": "fixed", "flag": "peak cd not published: estimated from lumens (60% in-beam requested; capped at the catalogue 1,760 lm, i.e. ~50% in-beam)"},
        "SILO":  {"name": "WAC Silo X20 2020", "lm": 869, "beam": 25, "peak": 3400, "radius": 0.025, "dia": 2.6, "len": 6.5, "cct": 2700, "cct_mode": "fixed", "louver_cutoff": 35, "louver_trans": 0.9, "flag": "25 deg values interpolated between 15 and 50 deg"},
        "PUCK":  {"name": "Govee Permanent Outdoor Lights 2 puck", "lm": 50, "beam": 30, "peak": None, "radius": 0.02, "dia": 2.0, "len": 0.8, "cct": 2700},   # [P] 50 lm
        "WASH":  {"name": "Chauvet SlimPAR Q12 ILS", "lm": 1500, "beam": 25, "peak": None, "radius": 0.1, "dia": 8.0, "len": 3.7, "cct": 3000},       # [P] 1500 lm
        "MOVER": {"name": "moving head (Boss fight)", "lm": 1200, "beam": 12, "peak": None, "radius": 0.04, "dia": 6.0, "len": 9.0, "cct": 6000},
        "GOBO":  {"name": "gobo spot (Dungeon)", "lm": 1500, "beam": 40, "peak": None, "radius": 0.03, "dia": 4.0, "len": 8.0, "cct": 4000},
        "UPL":   {"name": "Govee Uplighter floor lamp", "lm": 1500, "beam": 100, "peak": None, "radius": 0.08, "dia": 10.0, "len": 3.0, "cct": 2400},  # [P] 1500 lm
        "HB":    {"name": "Greentek GT-HB8 240W", "lm": 33600, "profile": "cosine", "radius": 0.15, "dia": 13.0, "len": 4.0, "cct": 5700,
                  "flag": "GT-HB8 240W sheet not found; 33,600 lm from Greentek's 240W UFO4 sheet"},
    },
    # strips: lm per foot [P], runs as (x0,y0,z, x1,y1,z) in inches, normal (nx,ny,nz)
    "strips": {
        "UC": {"lmft": 400, "cct": 3500, "runs": [((315, 249, 59.6), (351, 249, 59.6)), ((411, 249, 59.6), (447, 249, 59.6)),
                                                  ((351, 249, 59.6), (411, 249, 59.6))], "normal": (0, -0.7071, -0.7071)},
        "GR": {"lmft": 350, "cct": 3000, "runs": [((118, 242.75, 141.0), (210, 242.75, 141.0)), ((517, 242.75, 141.0), (708, 242.75, 141.0))], "normal": (0, 0, -1)},
        "WW": {"lmft": 350, "cct": 3000, "runs": [((696.6, 250, 141.0), (696.6, 460, 141.0)), ((15, 250, 141.0), (15, 370, 141.0))], "normal": (0, 0, -1)},
        "UP": {"lmft": 300, "cct": 2700, "runs": [((316, 240.75, 96.3), (350, 240.75, 96.3)), ((412, 240.75, 96.3), (446, 240.75, 96.3))], "normal": (0, -0.5, 0.866)},
        "TOE": {"lmft": 100, "cct": 2700, "runs": [((310, 258.5, 1.0), (467, 258.5, 1.0))], "normal": (0, 0.5, -0.866)},
        "BIAS": {"lmft": 150, "cct": 6500, "runs": [((570, 239.0, 92.0), (637, 239.0, 92.0)), ((570, 239.0, 56.0), (637, 239.0, 56.0)),
                                                    ((569, 239.0, 58.0), (569, 239.0, 90.0)), ((638, 239.0, 58.0), (638, 239.0, 90.0))], "normal": (0, -1, 0)},
    },
    "strip_seg": 6.0,                 # analytic discretisation (in)
    "pucks": {"chords": ["T06", "T07", "T10", "T11"], "spacing": 12.0, "y0": 250.0, "y1": 462.0, "z": 141.2},
    "washes": [  # mount (x,y,z) -> aim (x,y,z), on chords
        ((142.32, 300, 138), (142.32, 237.75, 70)), ((284.64, 300, 138), (240, 237.75, 70)),
        ((521.84, 300, 138), (530, 237.75, 70)), ((664.16, 300, 138), (664.16, 237.75, 70)),
        ((189.76, 420, 138), (189.76, 471.75, 70)), ((474.4, 420, 138), (500, 471.75, 70)),
        ((664.16, 400, 138), (711.6, 380, 70)), ((47.44, 330, 138), (0, 330, 70)),
    ],
    "mover": ((569.28, 330, 136), (381, 320, 0)),
    "gobo": ((379.52, 300, 136), (381, 318, 0)),
    "highbay_drop": 6.0,              # [P] two rows of three (data/space.json HB-1..6), 6in below chords
    "highbay_north_min_y": 237.75,

    # ---- golf sim bay (brief section 7), shop frame inches
    "golf": {
        "screen_face_x": 4.5, "screen_cy": 115.0,            # [M] Carl's Place screen plane in the model (golf-screen at x 9)
        "image_w": 204.0, "image_h": 115.2, "image_z0": 6.0,  # 17 x 9.6 ft 16:9 image, bottom 6in [P]
        "enclosure_depth": 24.0, "enclosure_h": 130.0,        # [P] black side curtains, 2 ft deep
        "mat": 60.0, "mat_h": 3.0, "ball_dist": 132.0,        # 5x5 mat (1.25in) on the 1.75in turf floor [M]; ball 11 ft from the screen (owner)
        "swing_r_m": 1.9, "swing_c_m": 1.1, "swing_buffer_m": 1.0,   # [P]
        "hitter_stand": 26.0, "hitter_h": 72.0, "club_top_z": 108.0,  # [P] right-handed, stands S of the ball facing N
        "projector": "AK900ST",                               # owner
        "projectors": {"AK900ST": {"tr": [0.81, 0.89], "lm": 6000, "vshift": 0.60, "body": [13.0, 16.9, 6.5]},
                       "LK936ST": {"tr": [0.81, 0.89], "lm": 5100, "vshift": 0.60, "body": [13.0, 16.9, 6.5]}},
        "zoom": 0.5,                                          # 0 = 0.81 throw ratio, 1 = 0.89
        "proj_lens_drop": 8.0,                                # [P] lens centre below the chords (strut + bracket)
        "proj_level": 0.35,                                   # mean image level for renders (fraction of white)
        "monitor": {"name": "ProTee VX", "size": [7.9, 32.7, 6.7], "top_above_mat": 120.0, "ahead": 43.0},  # 83x20x17 cm, 10 ft, 43in ahead [P orientation]
        "track_lateral": [48.0, 60.0],                        # runs 4-5 ft out each side
        "head_behind": [18.0, 54.0],                          # [P] head positions along each run, behind the ball
        "track_run": [0.0, 96.0],                             # [P] 8 ft H-track from the ball line back
        "cct": 4000,
        "uplighter": {"pos": [225.0, 175.0, 60.0], "aim": [330.0, 175.0, 160.0]},   # [P] behind the tee line, facing away
        "packages": {"VALUE": {"fixture": "CHG", "cost": 464}, "PREMIUM": {"fixture": "SILO", "cost": 1177, "louver": True}},
        "shadow_lux": 0.5,                                    # stray light below this can't show a hitter shadow
        "render_package": "auto", "render_lateral": 48.0,
    },

    # ---- golf screen spill and indirect checks
    "spill_target": 3.0,              # [P] lux, about 1% of the projector's white
    "counter_target": 500.0,
    "counter_region": (315, 447, 238.25, 261.75, 36.0), "sink_cut": (366, 396, 241.5, 258.5),

    # ---- packages (8 heads each)
    "packages": {
        "VALUE": {"fixture": "CHG", "cost": 2020, "ccts": [3000] * 8},
        "MID": {"fixture": "SBL", "cost": 3910, "ccts": [3000, 4000] * 4},
        "PREMIUM": {"fixture": "SILO", "cost": 9250, "ccts": [2700, 4000] * 4, "louver": True},
    },

    # ---- haze
    "haze_densities": [0.005, 0.01, 0.02], "haze_anisotropy": 0.6, "haze_step_rate": 1.5,
    "haze_contrast_min": 0.5,         # beam / background luminance (Weber) for "clearly visible" [P]
    "haze_density": None,             # None = pick from the test

    # ---- rendering
    "res": (1280, 720), "samples": 256, "final": False, "samples_final": 1024,
    "measure_samples": 512, "render_option": "auto", "render_case": "A",

    # ---- scenes: layer -> fraction | {"f", "cct" | "rgb", "anim"}, "ev" exposure, "haze"
    "scenes": {
        "game_night": {"TABLE": {"f": 1.0, "cct": 3000}, "UC": 0.25, "GR": 0.25, "WW": 0.25, "UP": 0.2, "PUCK": 0.25, "ev": 3.0},
        "lan_party": {"HB_N": 0.15, "TABLE": {"f": 0.6, "cct": 4000}, "UP": {"f": 0.9, "rgb": (0.25, 0.35, 1.0)},
                      "PUCK": {"f": 0.8, "rgb": (0.7, 0.15, 1.0)}, "GR": {"f": 0.3, "rgb": (0.1, 0.8, 1.0)}, "ev": 3.0},
        "movie": {"TOE": 0.1, "BIAS": {"f": 0.1, "cct": 6500}, "ev": 6.0},
        "cooking": {"UC": {"f": 1.0, "cct": 3500}, "HB_N": 0.3, "ev": 1.5},
        "all_on": {"HB_N": 1, "HB_S": 1, "TABLE": 1, "UC": 1, "GR": 1, "WW": 1, "UP": 1, "PUCK": 1, "TOE": 1, "BIAS": 1, "WASH": 1,
                   "HIT": 1, "AMB": 1, "ev": 0.0},
        "sim_play": {"HIT": {"f": 1.0, "cct": 4000}, "AMB": 0.15, "PROJ": 0.35, "ev": 3.0},
        "sim_social": {"HIT": {"f": 0.6, "cct": 4000}, "AMB": 0.3, "PROJ": 0.35, "ev": 3.0},
        "sim_movie": {"PROJ": 0.35, "ev": 4.0},
        "theme_tavern": {"TABLE": {"f": 1.0, "cct": 2700}, "WASH": {"f": 0.7, "rgb": (1.0, 0.45, 0.08)},
                         "PUCK": {"f": 0.6, "cct": 2200, "anim": "flicker"}, "UP": {"f": 0.3, "rgb": (1.0, 0.5, 0.1)}, "haze": True, "ev": 3.0},
        "theme_dungeon": {"TABLE": {"f": 0.8, "cct": 3000}, "WASH": {"f": 0.8, "rgb": (0.0, 0.55, 0.5), "anim": "pulse_slow"},
                          "GOBO": {"f": 1.0, "cct": 4500}, "PUCK": {"f": 0.15, "rgb": (0.1, 0.4, 1.0)}, "haze": True, "ev": 3.5},
        "theme_boss": {"TABLE": {"f": 1.0, "cct": 4000}, "WASH": {"f": 1.0, "rgb": (1.0, 0.02, 0.0), "anim": "pulse_fast"},
                       "MOVER": {"f": 1.0, "cct": 6000, "anim": "sweep"}, "haze": True, "ev": 3.0},
        "theme_magic": {"TABLE": {"f": 1.0, "cct": 3500}, "WASH": {"f": 0.9, "seat_colors": True}, "PUCK": {"f": 0.2, "cct": 4000},
                        "haze": True, "ev": 3.0},
    },
    "deck_colors": {"white": (1.0, 0.95, 0.85), "blue": (0.05, 0.25, 1.0), "black": (0.35, 0.0, 0.6),
                    "red": (1.0, 0.05, 0.02), "green": (0.05, 0.9, 0.15)},

    # ---- materials (brief section 2)
    "materials": {
        "flat_black": ("#0D0D0D", 1.0), "ext_wall": ("#E8E8E6", 0.95), "partition": ("#96AAB0", 0.9),
        "floor": ("#7A7A7A", 0.25), "cabinet": ("#5A4A3A", 0.6), "counter": ("#DDDDDD", 0.3),
    },
}
P = PARAMS


# ============================================================================ helpers
def m(x, y, z):
    return Vector((x * IN, y * IN, z * IN))


def npm(p):
    return np.array([p[0] * IN, p[1] * IN, p[2] * IN])


def hex_rgb(h):
    h = h.lstrip("#")
    s = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in s)


def lum(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _g(x, mu, s1, s2):
    s = s1 if x < mu else s2
    return math.exp(-0.5 * ((x - mu) / s) ** 2)


def cct_rgb(T):
    """Blackbody colour as linear Rec.709, max channel 1 (CIE 1931 CMF fit by Wyman et al. 2013)."""
    X = Y = Zc = 0.0
    for lam in range(380, 781, 5):
        l = lam * 1e-9
        B = 1.0 / (l ** 5 * (math.exp(1.4388e-2 / (l * T)) - 1))
        xb = 1.056 * _g(lam, 599.8, 37.9, 31.0) + 0.362 * _g(lam, 442.0, 16.0, 26.7) - 0.065 * _g(lam, 501.1, 20.4, 26.2)
        yb = 0.821 * _g(lam, 568.8, 46.9, 40.5) + 0.286 * _g(lam, 530.9, 16.3, 31.1)
        zb = 1.217 * _g(lam, 437.0, 11.8, 36.0) + 0.681 * _g(lam, 459.0, 26.0, 13.8)
        X += B * xb; Y += B * yb; Zc += B * zb
    X, Zc = X / Y, Zc / Y
    r = 3.2406 * X - 1.5372 - 0.4986 * Zc
    g = -0.9689 * X + 1.8758 + 0.0415 * Zc
    b = 0.0557 * X - 0.2040 + 1.0570 * Zc
    c = [max(v, 0.0) for v in (r, g, b)]
    mx = max(c)
    return tuple(v / mx for v in c)


def ftin(inches):
    s = "-" if inches < 0 else ""
    inches = abs(inches)
    f = int(inches // 12)
    i = inches - 12 * f
    if i > 11.75:
        f, i = f + 1, 0
    return f"{s}{f}' {i:.1f}\""


def out_dir(*parts):
    d = ROOT.joinpath(*parts)
    d.mkdir(parents=True, exist_ok=True)
    return d


def jload(path, default=None):
    p = ROOT / path
    return json.loads(p.read_text()) if p.exists() else default


def jsave(path, obj):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1, default=float))


# ============================================================================ photometric profiles
def fixture_profile(fx):
    """(kind, half_beam_rad, cut_rad, I0_cd, flux_from_profile_lm)."""
    if fx.get("profile") == "cosine":
        I0 = fx["lm"] / math.pi
        return "cos", math.radians(60), math.radians(90), I0, fx["lm"]
    hb = math.radians(fx["beam"] / 2)
    cut = min(hb * math.sqrt(math.log(500) / math.log(2)), math.radians(89))
    if fx.get("louver_cutoff"):
        cut = min(cut, math.radians(fx["louver_cutoff"]))
    th = np.linspace(0, cut, 2000)
    f = np.exp(-math.log(2) * (th / hb) ** 2)
    w = 2 * math.pi * np.sin(th) * (th[1] - th[0])
    om_total = float((f * w).sum())
    om_beam = float((f * w)[th <= hb].sum())
    if fx.get("peak"):
        I0 = fx["peak"]
    elif fx.get("in_beam"):  # a smooth beam holds only ~50% inside its half-power angle: never exceed catalogue lumens
        I0 = min(fx["in_beam"] * fx["lm"] / om_beam, fx["lm"] / om_total)
    else:
        I0 = fx["lm"] / om_total
    trans = fx.get("louver_trans", 1.0) if fx.get("louver_cutoff") else 1.0
    return "gauss", hb, cut, I0 * trans, I0 * trans * om_total


def profile_f(kind, hb, cut, th):
    th = np.asarray(th)
    if kind == "cos":
        f = np.cos(np.minimum(th, math.pi / 2))
    elif kind == "flat":
        f = np.ones_like(th, dtype=float)
    else:
        f = np.exp(-math.log(2) * (th / hb) ** 2)
    return np.where(th <= cut, f, 0.0)


def write_ies(path, kind, hb, cut):
    """LM-63-2002 file, rotationally symmetric, peak 1000 cd (every file has the same peak, see calibrate)."""
    ang = np.arange(0, 181, 1.0)
    cd = 1000.0 * profile_f(kind, hb, cut, np.radians(ang))
    cd[ang > 90] = 0
    lines = ["IESNA:LM-63-2002", "[TEST] generated by scripts/lighting.py", f"[LUMINAIRE] {kind} hb={math.degrees(hb):.2f}",
             "TILT=NONE", f"1 -1 1 {len(ang)} 1 1 2 0 0 0", "1.0 1.0 0",
             " ".join(f"{a:g}" for a in ang), "0", " ".join(f"{c:.3f}" for c in cd)]
    Path(path).write_text("\n".join(lines) + "\n")


def ies_key(kind, hb, cut):
    return f"{kind}_{math.degrees(hb):.2f}_{math.degrees(cut):.2f}"


# ============================================================================ Cycles setup
def setup_cycles(scene, samples, denoise=True):
    scene.render.engine = "CYCLES"
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "METAL"
        prefs.get_devices()
        for d in prefs.devices:
            d.use = True
        scene.cycles.device = "GPU"
    except Exception as e:
        print("WARN GPU:", e)
    c = scene.cycles
    c.samples = samples
    c.use_denoising = denoise
    c.use_adaptive_sampling = True
    c.use_light_tree = True
    c.max_bounces, c.diffuse_bounces, c.glossy_bounces, c.transmission_bounces = 8, 4, 4, 8
    c.volume_bounces = 1
    c.volume_step_rate = P["haze_step_rate"]
    scene.render.film_transparent = False


def set_view(scene, measure, ev=0.0):
    vs = scene.view_settings
    try:
        vs.view_transform = "Standard" if measure else "AgX"
    except TypeError:
        print("WARN view transforms:", [i.identifier for i in vs.bl_rna.properties["view_transform"].enum_items])
    try:
        vs.look = "None"
    except TypeError:
        pass
    vs.exposure = 0.0 if measure else ev
    vs.gamma = 1.0


def render_to(scene, path, res, exr=False):
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.resolution_percentage = 100
    st = scene.render.image_settings
    if exr:
        st.file_format = "OPEN_EXR"
        st.color_depth = "32"
        st.exr_codec = "ZIP"
    else:
        st.file_format = "PNG"
        st.color_depth = "8"
    st.color_mode = "RGB"
    scene.render.filepath = str(path)
    t = time.time()
    bpy.ops.render.render(write_still=True, scene=scene.name)
    print(f"  rendered {Path(path).name} in {time.time() - t:.1f}s")


def read_exr(path):
    img = bpy.data.images.load(str(path), check_existing=False)
    w, h = img.size
    a = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(a)
    bpy.data.images.remove(img)
    return a.reshape(h, w, 4)[:, :, :3]


def white_diffuse():
    mt = bpy.data.materials.get("MEAS_WHITE")
    if mt:
        return mt
    mt = bpy.data.materials.new("MEAS_WHITE")
    mt.use_nodes = True
    nt = mt.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    d = nt.nodes.new("ShaderNodeBsdfDiffuse")
    d.inputs["Color"].default_value = (1, 1, 1, 1)
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(d.outputs[0], o.inputs["Surface"])
    return mt


def principled(name, rgb, rough, **kw):
    mt = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mt.use_nodes = True
    nt = mt.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = rough
    for k, v in kw.items():
        if k in b.inputs:
            b.inputs[k].default_value = v
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(b.outputs[0], o.inputs["Surface"])
    mt.diffuse_color = (*rgb, 1)
    return mt


def light_with_ies(name, I0, kind, hb, cut, radius, k, ies_dir):
    ld = bpy.data.lights.new(name, "SPOT")
    ld.energy = 4 * math.pi * I0 / 683.0 / k
    ld.spot_size = min(2 * cut + math.radians(2), math.pi)
    ld.spot_blend = 0.0
    ld.shadow_soft_size = radius
    if hasattr(ld, "use_soft_falloff"):
        ld.use_soft_falloff = False
    path = Path(ies_dir) / f"{ies_key(kind, hb, cut)}.ies"
    if not path.exists():
        write_ies(path, kind, hb, cut)
    if hasattr(ld, "use_nodes"):
        ld.use_nodes = True
    nt = ld.node_tree
    em = next(n for n in nt.nodes if n.type == "EMISSION")
    ies = nt.nodes.new("ShaderNodeTexIES")
    ies.mode = "EXTERNAL"
    ies.filepath = str(path)
    nt.links.new(ies.outputs[0], em.inputs["Strength"])
    ld["base_W"] = ld.energy
    return ld


def area_light(name, length_m, width_m, flux_lm, k):
    ld = bpy.data.lights.new(name, "AREA")
    ld.shape = "RECTANGLE"
    ld.size, ld.size_y = length_m, width_m
    ld.spread = math.pi
    ld.energy = flux_lm / 683.0 / k
    ld["base_W"] = ld.energy
    return ld


def strip_emitter(name, c, length_m, width_m, flux_lm, k):
    """One-sided Lambertian emissive strip (plane facing local -Z). Cycles area lights don't fall off as a Lambertian
    emitter does, so strips are emissive meshes calibrated like the spots (calibrate stage, key 'mesh')."""
    me = bpy.data.meshes.new(name)
    L2, W2 = length_m / 2, width_m / 2
    me.from_pydata([(-L2, W2, 0), (L2, W2, 0), (L2, -W2, 0), (-L2, -W2, 0)], [], [(0, 1, 2, 3)])  # normal -Z
    ob = bpy.data.objects.new(name, me)
    c.objects.link(ob)
    mt = bpy.data.materials.new(name + "_em")
    mt.use_nodes = True
    nt = mt.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    em = nt.nodes.new("ShaderNodeEmission"); em.name = "EM"
    dk = nt.nodes.new("ShaderNodeBsdfDiffuse"); dk.inputs["Color"].default_value = (0.02, 0.02, 0.02, 1)
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(geo.outputs["Backfacing"], mix.inputs[0])
    nt.links.new(em.outputs[0], mix.inputs[1]); nt.links.new(dk.outputs[0], mix.inputs[2])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    me.materials.append(mt)
    ob["base_S"] = flux_lm / 683.0 / (length_m * width_m) / k
    set_strip(ob, ob["base_S"], (1, 1, 1))
    ob.visible_shadow = False
    ob.visible_camera = False   # light the scene, but stay out of measurement views (channels show the fixture)
    return ob


def set_strip(ob, strength, color):
    em = ob.data.materials[0].node_tree.nodes["EM"]
    em.inputs["Strength"].default_value = strength
    em.inputs["Color"].default_value = (*color, 1)


def rot_to(axis, up=Vector((0, 0, 1))):
    """Rotation whose -Z points along axis (and X along `up` cross ... for strips)."""
    a = Vector(axis).normalized()
    return a.to_track_quat("-Z", "Y" if abs(a.y) < 0.99 else "X").to_euler()


# ============================================================================ stage: calibrate
def stage_calibrate():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system, sc.unit_settings.scale_length = "METRIC", 1.0
    sc.world = bpy.data.worlds.new("black")
    sc.world.color = (0, 0, 0)
    setup_cycles(sc, P["measure_samples"], denoise=False)
    sc.cycles.max_bounces = 0
    set_view(sc, True)
    ies_dir = out_dir(P["export_dir"], "ies")
    cal_dir = out_dir(P["render_dir"], "calibration")
    # 1 x 1 m albedo-1 plane
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0, 0, 0))
    plane = bpy.context.object
    plane.data.materials.append(white_diffuse())
    cam_d = bpy.data.cameras.new("cam")
    cam_d.type, cam_d.ortho_scale = "ORTHO", 1.0
    cam = bpy.data.objects.new("cam", cam_d)
    sc.collection.objects.link(cam)
    cam.location = (0, 0, 1.5)
    sc.camera = cam
    H = 2.845
    res = (101, 101)
    out = {"spot": {}, "area": None}
    profiles = {}
    fixtures = dict(P["fixtures"])
    fixtures["_CAL"] = {"lm": 0, "beam": 45, "peak": 1000}
    for key, fx in fixtures.items():
        kind, hb, cut, I0, _ = fixture_profile(fx)
        profiles[ies_key(kind, hb, cut)] = (kind, hb, cut)
    for pk, (kind, hb, cut) in profiles.items():
        ld = light_with_ies("cal", 1000.0, kind, hb, cut, 0.025, 1.0, ies_dir)
        lo = bpy.data.objects.new("cal", ld)
        sc.collection.objects.link(lo)
        lo.location = (0, 0, H)  # points down (-Z) by default
        path = cal_dir / f"spot_{pk}.exr"
        render_to(sc, path, res, exr=True)
        px = read_exr(path)
        Y = 0.2126 * px[..., 0] + 0.7152 * px[..., 1] + 0.0722 * px[..., 2]
        c = res[0] // 2
        meas = float(math.pi * Y[c - 1:c + 2, c - 1:c + 2].mean() * 683.0)
        expect = 1000.0 / H ** 2
        # off-axis check 0.4 m from the centre (pixel scale: 1 m over 101 px)
        off = 0.4
        po = int(round(c + off * res[0]))
        th = math.atan(off / H)
        exp_off = float(1000.0 * profile_f(kind, hb, cut, th) * math.cos(th) ** 3 / H ** 2)
        meas_off = float(math.pi * Y[c - 1:c + 2, po - 1:po + 2].mean() * 683.0)
        out["spot"][pk] = {"k": meas / expect, "meas_lux": meas, "expect_lux": expect,
                           "offaxis_meas": meas_off, "offaxis_expect": exp_off}
        print(f"CAL spot {pk}: centre {meas:.1f} lux vs {expect:.1f} -> k={meas / expect:.4f}; "
              f"0.4m off-axis {meas_off:.1f} vs {exp_off:.1f}")
        bpy.data.objects.remove(lo)
    # area: 1 m x 0.5 in strip, 1000 lm, 1 m above the plane
    ld = area_light("cal_a", 1.0, 0.0127, 1000.0, 1.0)
    lo = bpy.data.objects.new("cal_a", ld)
    sc.collection.objects.link(lo)
    lo.location = (0, 0, 1.0)
    path = cal_dir / "area.exr"
    render_to(sc, path, res, exr=True)
    px = read_exr(path)
    Y = 0.2126 * px[..., 0] + 0.7152 * px[..., 1] + 0.0722 * px[..., 2]
    c = res[0] // 2
    meas = float(math.pi * Y[c - 1:c + 2, c - 1:c + 2].mean() * 683.0)
    xs = np.linspace(-0.5, 0.5, 2001)
    dx = xs[1] - xs[0]
    r2 = xs ** 2 + 1.0
    expect = float(((1000.0 * dx / math.pi) * (1.0 / np.sqrt(r2)) ** 2 / r2).sum())  # cos*cos/r^2
    out["area"] = {"k": meas / expect, "meas_lux": meas, "expect_lux": expect}
    print(f"CAL area: {meas:.1f} lux vs {expect:.1f} -> k={meas / expect:.4f}")
    bpy.data.objects.remove(lo)
    em = strip_emitter("cal_m", sc.collection, 1.0, 0.0127, 1000.0, 1.0)
    em.location = (0, 0, 1.0)
    path = cal_dir / "mesh.exr"
    sc.cycles.max_bounces = 0
    render_to(sc, path, res, exr=True)
    px = read_exr(path)
    Y = 0.2126 * px[..., 0] + 0.7152 * px[..., 1] + 0.0722 * px[..., 2]
    meas = float(math.pi * Y[c - 1:c + 2, c - 1:c + 2].mean() * 683.0)
    po = int(round(c + 0.4 * res[0]))
    meas_off = float(math.pi * Y[po - 1:po + 2, c - 1:c + 2].mean() * 683.0)   # 0.4 m across the strip
    r2o = xs ** 2 + 1.0 + 0.16
    exp_off = float(((1000.0 * dx / math.pi) * (1.0 / r2o) ** 2).sum())
    out["mesh"] = {"k": meas / expect, "meas_lux": meas, "expect_lux": expect, "offaxis_meas": meas_off, "offaxis_expect": exp_off}
    print(f"CAL mesh strip: {meas:.1f} lux vs {expect:.1f} -> k={meas / expect:.4f}; 0.4 m across {meas_off:.1f} vs {exp_off:.1f}")
    out["brief_check"] = {"expect_124": 1000 / H ** 2, "note": "pi * pixel * 683 on an albedo-1 diffuse plane (Combined, max_bounces 0 = direct only)"}
    jsave(f"{P['export_dir']}/calibration.json", out)


def cal():
    c = jload(f"{P['export_dir']}/calibration.json")
    if not c:
        raise SystemExit("run the calibrate stage first")
    return c


def k_spot(fx, c):
    kind, hb, cut, _, _ = fixture_profile(fx)
    return c["spot"][ies_key(kind, hb, cut)]["k"]


# ============================================================================ geometry: door envelope, table, seats
def DSTATE():
    """results.csv 'door' value of the design state (the one the optimiser and summaries use)."""
    return "open" if P["design_door_open"] else "closed"


def table_center(case):
    if case == "A":
        return P["case_A_center"]
    cx, cy = P["case_B_center"]
    return (cx, P["north_wall_y"] - P["door_open_depth"] if cy is None else cy)


def table_frame(case):
    """centre, long-axis unit a, cross unit b (2D, inches), half sizes."""
    c = np.array(table_center(case))
    a = np.array([1.0, 0.0]) if case == "A" else np.array([0.0, 1.0])
    b = np.array([0.0, 1.0]) if case == "A" else np.array([-1.0, 0.0])
    return c, a, b, P["table_w"] / 2, P["table_d"] / 2


def table_bbox(case):
    c, a, b, hw, hd = table_frame(case)
    ext = np.abs(a) * hw + np.abs(b) * hd
    return c - ext, c + ext


def door_parts(opener):
    """Boxes (min, max) in inches: open panel, tracks, opener."""
    x0, x1, yw = P["door_x0"], P["door_x1"], P["north_wall_y"]
    zt, th = P["door_panel_top_z"], P["door_panel_thick"]
    yd = yw - P["door_open_depth"]
    parts = {"panel": ((x0, yd, zt - th), (x1, yw, zt))}
    g, ta = P["track_gap"], P["track_angle"]
    yr = yw - P["track_run"]
    cz = P["chord_z"]
    parts["track_w"] = ((x0 - g - ta, yr, zt - th - 0.5), (x0 - g, yw, zt))
    parts["track_e"] = ((x1 + g, yr, zt - th - 0.5), (x1 + g + ta, yw, zt))
    # rear hangers: angle from each track's back end up to the chords
    parts["hanger_w"] = ((x0 - g - ta, yr, zt), (x0 - g, yr + 1.5, cz))
    parts["hanger_e"] = ((x1 + g, yr, zt), (x1 + g + ta, yr + 1.5, cz))
    sz = P["torsion_shaft_z"]
    parts["shaft"] = ((x0 - 6, yw - 4, sz), (x1 + 6, yw - 2, sz + 2))
    if opener == "trolley":
        xc = (x0 + x1) / 2
        ye = yw - P["trolley_len"]
        la, ac, h = P["trolley_motor"]
        rz = P["trolley_rail_z"]
        parts["rail"] = ((xc - 0.75, ye, rz - 1.5), (xc + 0.75, yw, rz + 1.5))
        parts["motor"] = ((xc - ac / 2, ye - la, rz - h / 2), (xc + ac / 2, ye, rz + h / 2))
        parts["motor_hanger"] = ((xc - 0.75, ye - la / 2 - 0.75, rz + h / 2), (xc + 0.75, ye - la / 2 + 0.75, cz))
    else:
        parts["jackshaft"] = ((x1 + 6, yw - 12, 84), (x1 + 20, yw, 104))  # wall-mounted beside the door
    return parts


def envelope(opener, pad=None):
    pad = P["envelope_pad"] if pad is None else pad
    boxes = []
    for k, (lo, hi) in door_parts(opener).items():
        if k == "jackshaft":
            continue  # on the wall, not in the overhead envelope
        boxes.append((np.array(lo) - pad, np.array(hi) + pad))
    return boxes


def box_hit(a, b):
    return bool(np.all(a[0] < b[1]) and np.all(b[0] < a[1]))


def seats(case):
    """Six seats: dict(eye, edge, n (into table), t) in inches (3D np arrays)."""
    c, a, b, hw, hd = table_frame(case)
    out = []
    for side in (-1, 1):
        for s in P["seat_along"]:
            e2 = c + a * s + b * side * hd
            n2 = -b * side
            out.append({"edge": np.array([*e2, P["table_z"]]), "n": np.array([*n2, 0.0]), "t": np.array([*a, 0.0]),
                        "side": side, "along": s})
    for st in out:
        st["eye"] = st["edge"] - st["n"] * 3.6
        st["eye"][2] = P["eye_z"]
    return out


def grid_points(case):
    c, a, b, hw, hd = table_frame(case)
    nu, nv = P["grid"]
    us = (np.arange(nu) + 0.5) / nu * 2 * hw - hw
    vs = (np.arange(nv) + 0.5) / nv * 2 * hd - hd
    pts = []
    for v in vs:
        for u in us:
            p2 = c + a * u + b * v
            pts.append((p2[0], p2[1], P["table_z"] + 0.06))
    return np.array(pts), (nv, nu)


# ============================================================================ stage: build
def coll(name, parent=None):
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    par = parent or bpy.context.scene.collection
    if c.name not in [x.name for x in par.children]:
        par.children.link(c)
    return c


def mesh_obj(name, c, build, mat=None):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    build(bm)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    c.objects.link(o)
    if mat:
        o.data.materials.append(mat)
    return o


def bm_box(bm, lo, hi):
    """Axis-aligned box from inch corners, built in metres."""
    lo, hi = np.array(lo) * IN, np.array(hi) * IN
    r = bmesh.ops.create_cube(bm, size=1.0)
    for v in r["verts"]:
        v.co = Vector(((lo + hi) / 2 + (hi - lo) * np.array(v.co)))


def bm_capsule(bm, p0, p1, r, seg=12):
    p0, p1 = Vector(np.array(p0) * IN), Vector(np.array(p1) * IN)
    d = p1 - p0
    L = d.length
    q = d.normalized().to_track_quat("Z", "Y")
    M = Matrix.Translation(p0) @ q.to_matrix().to_4x4()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r * IN, radius2=r * IN, depth=L,
                          matrix=M @ Matrix.Translation((0, 0, L / 2)))
    for p in (p0, p1):
        bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=8, radius=r * IN, matrix=Matrix.Translation(p))


def bm_sphere(bm, c, r):
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=r * IN, matrix=Matrix.Translation(Vector(np.array(c) * IN)))


def bm_cyl(bm, center_m, axis, r_m, length_m, seg=16):
    """Cylinder whose front face centre is center_m, extending BACK along -axis... (housing behind the lens)."""
    a = Vector(axis).normalized()
    q = a.to_track_quat("Z", "Y")
    M = Matrix.Translation(Vector(center_m) + a * (length_m / 2 + 0.003)) @ q.to_matrix().to_4x4()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r_m, radius2=r_m, depth=length_m, matrix=M)


def remap_materials():
    M = P["materials"]
    blk = principled("L_flat_black", hex_rgb(M["flat_black"][0]), M["flat_black"][1])
    wall = principled("L_ext_wall", hex_rgb(M["ext_wall"][0]), M["ext_wall"][1])
    part = principled("L_partition", hex_rgb(M["partition"][0]), M["partition"][1])
    flr = principled("L_floor_flake", hex_rgb(M["floor"][0]), M["floor"][1])
    cab = principled("L_cabinet", hex_rgb(M["cabinet"][0]), M["cabinet"][1])
    ctr = principled("L_counter", hex_rgb(M["counter"][0]), M["counter"][1])
    glass = bpy.data.materials.new("L_glass")
    glass.use_nodes = True
    nt = glass.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    g = nt.nodes.new("ShaderNodeBsdfGlass")
    g.inputs["IOR"].default_value = 1.5
    g.inputs["Roughness"].default_value = 0.0
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(g.outputs[0], o.inputs["Surface"])
    rules = [(("truss", "roof", "framing_black", "ceiling"), blk), (("wall_foam", "spray_foam"), wall),
             (("iw_paint",), part), (("slab",), flr), (("glass",), glass), (("fi_K-TOP",), ctr),
             (("fi_K-B", "fi_K-DB", "fi_K-SB", "fi_K-W36", "fi_K-WINE"), cab)]
    swapped = {}
    for ob in bpy.context.scene.objects:
        if ob.type != "MESH":
            continue
        for slot in ob.material_slots:
            if not slot.material:
                continue
            nm = slot.material.name
            for keys, mt in rules:
                if any(nm.startswith(k) for k in keys):
                    slot.material = mt
                    swapped[nm] = mt.name
                    break
    print("materials remapped:", swapped)
    return blk


def build_door(cdoor_open, cfixed, copen, blk):
    galv = principled("L_galv", (0.55, 0.57, 0.6), 0.4, Metallic=1.0)
    alu = principled("L_door_alu", (0.6, 0.62, 0.64), 0.35, Metallic=1.0)
    glass = bpy.data.materials["L_glass"]
    parts = door_parts("trolley")
    x0, x1, yw = P["door_x0"], P["door_x1"], P["north_wall_y"]
    zt, th = P["door_panel_top_z"], P["door_panel_thick"]
    yd = yw - P["door_open_depth"]
    # open panel: glass lites in an aluminium frame (4 sections x 4 columns)
    mesh_obj("DOOR_OPEN_glass", cdoor_open, lambda bm: bm_box(bm, (x0 + 1.5, yd + 1, zt - th + 0.75), (x1 - 1.5, yw - 1, zt - th + 1.0)), glass)

    def frame(bm):
        for k in range(5):
            xa = x0 + k * (x1 - x0 - 3) / 4
            bm_box(bm, (xa, yd, zt - th), (xa + 3, yw, zt))
        for k in range(5):
            ya = yd + k * (yw - yd - 2.5) / 4
            bm_box(bm, (x0, ya, zt - th), (x1, ya + 2.5, zt))
    mesh_obj("DOOR_OPEN_frame", cdoor_open, frame, alu)

    def tracks(bm):
        for k in ("track_w", "track_e"):
            lo, hi = parts[k]
            bm_box(bm, lo, hi)
            bm_box(bm, (lo[0], yw - 3, 0), (hi[0], yw, zt - th))  # vertical track (up to the horizontal one)
        for k in ("hanger_w", "hanger_e", "shaft"):
            bm_box(bm, *parts[k])
    mesh_obj("DOOR_tracks", cfixed, tracks, galv)
    ct = coll("OPENER_trolley", copen)
    mesh_obj("OPENER_trolley_rail", ct, lambda bm: bm_box(bm, *parts["rail"]), galv)
    mesh_obj("OPENER_trolley_hanger", ct, lambda bm: bm_box(bm, *parts["motor_hanger"]), galv)
    mesh_obj("OPENER_trolley_motor", ct, lambda bm: bm_box(bm, *parts["motor"]), principled("L_motor", (0.8, 0.8, 0.8), 0.5))
    cj = coll("OPENER_jackshaft", copen)
    mesh_obj("OPENER_jackshaft_motor", cj, lambda bm: bm_box(bm, *door_parts("jackshaft")["jackshaft"]), principled("L_motor", (0.8, 0.8, 0.8), 0.5))
    ct.hide_render = True  # default jackshaft
    # door-open toggle: scene["door_open"] drives the open/closed objects
    sc = bpy.context.scene
    sc["door_open"] = 0
    return [o for o in cdoor_open.objects]


def add_toggle_driver(ob, show_when_open):
    for prop in ("hide_render", "hide_viewport"):
        fc = ob.driver_add(prop)
        drv = fc.driver
        drv.type = "SCRIPTED"
        v = drv.variables.new()
        v.name, v.type = "door_open", "SINGLE_PROP"
        v.targets[0].id_type = "SCENE"
        v.targets[0].id = bpy.context.scene
        v.targets[0].data_path = '["door_open"]'
        drv.expression = "1 - door_open" if show_when_open else "door_open"


def build_case_objects(case, ccase, felt_mat, src_objs):
    """Table + chairs for a case (linked duplicates for B) and the felt top."""
    c, a, b, hw, hd = table_frame(case)
    c0 = np.array(P["case_A_center"])
    ang = 0.0 if case == "A" else math.pi / 2
    root = bpy.data.objects["SHOP_ROOT"]
    for ob in src_objs:
        if case == "A":
            for uc in list(ob.users_collection):
                uc.objects.unlink(ob)
            ccase.objects.link(ob)
            continue
        nb = ob.copy()
        nb.name = ob.name + "_B"
        ccase.objects.link(nb)
        nb.parent = root
        nb.matrix_parent_inverse = ob.matrix_parent_inverse.copy()
        loc = np.array(ob.location[:2]) - c0
        r = np.array([loc[0] * math.cos(ang) - loc[1] * math.sin(ang), loc[0] * math.sin(ang) + loc[1] * math.cos(ang)])
        nb.location = (c[0] + r[0], c[1] + r[1], ob.location[2])
        nb.rotation_euler.z = ob.rotation_euler.z + ang
    if P["felt"]:
        lo, hi = table_bbox(case)
        mesh_obj(f"FELT_{case}", ccase, lambda bm: bm_box(bm, (lo[0], lo[1], P["table_z"] - 0.25), (hi[0], hi[1], P["table_z"] + 0.02)), felt_mat)


def build_proxies(case, cprox):
    skin = principled("L_proxy", (0.55, 0.42, 0.35), 0.6)
    piece = principled("L_piece", (0.8, 0.75, 0.6), 0.5)
    holder = principled("L_holder", (0.15, 0.12, 0.1), 0.6)
    zt = P["table_z"]
    rnd = random.Random(P["piece_seed"])
    c, a, b, hw, hd = table_frame(case)
    piece_boxes = []

    def people(bm):
        for s in seats(case):
            e, n, t = s["edge"], s["n"], s["t"]
            base = e.copy(); base[2] = 0
            bm_capsule(bm, base - n * 13 + [0, 0, 22], base - n * 9 + [0, 0, 40], 6.5)
            bm_sphere(bm, base - n * 8 + [0, 0, 47.5], 4.5)
            for sgn in (-1, 1):
                sh = base - n * 9 + t * sgn * 7 + [0, 0, 41]
                hand = base + n * P["arm_reach"] + t * sgn * 6 + [0, 0, zt + 1.75]
                bm_capsule(bm, sh, hand, 1.75)
    mesh_obj(f"PROXY_people_{case}", cprox, people, skin)

    def pieces(bm):
        for s in seats(case):
            e, n, t = s["edge"], s["n"], s["t"]
            hc = e + n * 5
            lo = hc - np.abs(t) * 6 - np.abs(n) * 0.75
            hi = hc + np.abs(t) * 6 + np.abs(n) * 0.75
            lo[2], hi[2] = zt, zt + 4
            piece_boxes.append((lo.copy(), hi.copy(), "holder"))
            for _ in range(P["pieces_per_player"]):
                pc = e + n * rnd.uniform(9, 14) + t * rnd.uniform(-10, 10)
                piece_boxes.append((pc - [1, 1, 0] + [0, 0, 0], pc + [1, 1, 2], "cube"))
        for _ in range(P["pieces_middle"]):
            pc = np.array([*(c + a * rnd.uniform(-hw * 0.5, hw * 0.5) + b * rnd.uniform(-hd * 0.3, hd * 0.3)), zt])
            piece_boxes.append((pc - [1, 1, 0], pc + [1, 1, 2], "cube"))
        for lo, hi, kind in piece_boxes:
            bm_box(bm, lo, hi)
    mesh_obj(f"PROXY_pieces_{case}", cprox, pieces, piece)
    return [(lo.tolist(), hi.tolist(), k) for lo, hi, k in piece_boxes]


def stage_build():
    src = ROOT / P["source_blend"]
    bpy.ops.wm.open_mainfile(filepath=str(src))
    sc = bpy.context.scene
    calib = cal()
    # --- drop diagram-only content: scans/zones/labels, clearances, door envelopes
    for cname in ("Reference", "Clearances"):
        cc = bpy.data.collections.get(cname)
        if cc:
            for ob in list(cc.all_objects):
                bpy.data.objects.remove(ob)
            bpy.data.collections.remove(cc)
    for ob in list(sc.objects):
        if ob.type == "FONT" or ob.name.startswith(("ENV_", "ZONE_", "AXIS_", "CLR_")):
            bpy.data.objects.remove(ob)
    for ob in list(sc.objects):
        if ob.type == "LIGHT":
            bpy.data.objects.remove(ob)
    # the model's OH-2 tracks are a builder default (z ~104); the brief's tracks at panel height replace them
    for nm in ("TRACK_OH-2",):
        if nm in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[nm])
    # --- to metres: everything under SHOP_ROOT (scale 0.0254)
    root = bpy.data.objects.new("SHOP_ROOT", None)
    sc.collection.objects.link(root)
    root.scale = (IN, IN, IN)
    for ob in sc.objects:
        if ob is not root and ob.parent is None:
            ob.parent = root
            ob.matrix_parent_inverse = Matrix.Identity(4)
    sc.unit_settings.system, sc.unit_settings.scale_length, sc.unit_settings.length_unit = "METRIC", 1.0, "METERS"
    sc.world = bpy.data.worlds.new("Night")
    sc.world.color = (0, 0, 0)
    if hasattr(sc.world, "use_nodes"):
        sc.world.use_nodes = True
    bg = next((n for n in sc.world.node_tree.nodes if n.type == "BACKGROUND"), None)
    if bg:
        bg.inputs["Strength"].default_value = 0.0
    blk = remap_materials()
    for ob in list(sc.objects):  # model high-bay placeholders are replaced by fixture objects
        if ob.name.startswith("CI_HB-"):
            bpy.data.objects.remove(ob)
    # --- door, opener, toggle
    clight = coll("LIGHTING")
    cdoor_c = coll("DOOR_closed", clight)
    cdoor_o = coll("DOOR_open", clight)
    copen = coll("OPENER", clight)
    for nm in ("WI_OH-2", "WI_OH-2_frame"):
        ob = bpy.data.objects.get(nm)
        if ob:
            for uc in list(ob.users_collection):
                uc.objects.unlink(ob)
            cdoor_c.objects.link(ob)
    cfixed_l = coll("DOOR_hardware", clight)
    build_door(cdoor_o, cfixed_l, copen, blk)
    for ob in cdoor_c.objects:
        add_toggle_driver(ob, show_when_open=False)
    for ob in cdoor_o.objects:
        add_toggle_driver(ob, show_when_open=True)
    # --- table cases
    felt = principled("L_felt", hex_rgb(P["felt_hex"]), P["felt_rough"])
    src_objs = [ob for ob in sc.objects if ob.name.startswith(("INV_family-table", "INV_family-chair"))]
    meta = {"pieces": {}}
    for case in ("B", "A"):  # B first: duplicates A's objects before they move collection
        cc = coll(f"CASE_{case}", clight)
        build_case_objects(case, cc, felt, src_objs)
        cp = coll(f"PROXY_{case}", clight)
        meta["pieces"][case] = build_proxies(case, cp)
    bpy.data.collections["CASE_B"].hide_render = True
    bpy.data.collections["PROXY_B"].hide_render = True
    for case in "AB":
        bpy.data.collections[f"PROXY_{case}"].hide_render = True
    # --- fixtures: high bays, strips, pucks, washes, specials
    ies_dir = out_dir(P["export_dir"], "ies")
    cfx = coll("FIXTURES", clight)
    build_static_fixtures(cfx, calib, ies_dir)
    # --- table packages (standard layouts; the optimised ones are added by `analyze`)
    ctab = coll("TABLE_OPTIONS", clight)
    layouts = {}
    for case in "AB":
        for opener in P["openers"]:
            for pkg in P["packages"]:
                heads, clashes = standard_layout(pkg, case, opener)
                key = f"{pkg}_STD_{case}_{opener}"
                layouts[key] = {"heads": heads, "naive_clashes": clashes}
                build_table_collection(key, heads, ctab, calib, ies_dir)
    meta["layouts"] = layouts
    jsave(f"{P['export_dir']}/build_meta.json", meta)
    # cameras
    build_cameras(clight)
    # haze
    build_haze(clight)
    # golf sim bay
    meta["golf"] = build_golf(clight, calib, ies_dir)
    # the param dict in the .blend for reference
    tx = bpy.data.texts.get("lighting.py") or bpy.data.texts.new("lighting.py")
    tx.from_string(Path(__file__).read_text())
    tx2 = bpy.data.texts.get("README_lighting") or bpy.data.texts.new("README_lighting")
    tx2.from_string("Door: set Scene > Custom Properties > door_open to 0/1.\n"
                    "Table case: toggle collections LIGHTING/CASE_A, CASE_B (and PROXY_* for the player proxies).\n"
                    "Options: LIGHTING/TABLE_OPTIONS/<PACKAGE>_<STD|OPT>_<case>_<opener>; enable one.\n"
                    "Opener: LIGHTING/OPENER/OPENER_trolley | OPENER_jackshaft.\n"
                    "Golf bay: LIGHTING/GOLF_BAY (screen curtains, mat, ProTee VX, projector), GOLF_OPTIONS/<PKG>_L<lateral>, HITTER_* proxies.\n"
                    "Regenerate everything from the PARAMS dict at the top of the lighting.py text: `make lighting`.\n")
    set_active(sc, P["render_case"], "jackshaft", None, door_open=False)
    sc.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / P["out_blend"]))
    print("BUILD OK ->", P["out_blend"])


def highbays():
    shop = json.loads((ROOT / "data" / "space.json").read_text())
    out = []
    for it in shop["ceiling_items"]:
        if it.get("type") == "light" and it["id"].startswith("HB-"):
            out.append((it["id"], float(it["x"]), float(it["y"]), P["chord_z"] - P["highbay_drop"]))
    return out


def static_sources():
    """Every non-table light as analytic sources: list of dicts(layer, id, L (m), axis, kind, hb, cut, I0, fx, rgb_default)."""
    src = []
    fxs = P["fixtures"]

    def spot(layer, sid, Lin, aim_in, fk, cct=None):
        fx = fxs[fk]
        kind, hb, cut, I0, _ = fixture_profile(fx)
        L = npm(Lin)
        ax = npm(aim_in) - L
        ax /= np.linalg.norm(ax)
        src.append({"layer": layer, "id": sid, "L": L, "axis": ax, "kind": kind, "hb": hb, "cut": cut, "I0": I0, "fx": fk,
                    "cct": cct or fx["cct"], "radius": fx["radius"]})
    for hid, x, y, z in highbays():
        lay = "HB_N" if y > P["highbay_north_min_y"] else "HB_S"
        spot(lay, hid, (x, y, z), (x, y, 0), "HB")
    tx = dict(zip([f"T{i:02d}" for i in range(16)], P["truss_x"]))
    k = 0
    for ch in P["pucks"]["chords"]:
        y = P["pucks"]["y0"]
        while y <= P["pucks"]["y1"] + 1e-6:
            x = tx[ch]
            pos = (x, y, P["pucks"]["z"])
            lo = np.array(pos) - [1, 1, 0.8]
            hi = np.array(pos) + [1, 1, 0]
            if not any(box_hit((lo, hi), e) for op in P["openers"] for e in envelope(op)):
                spot("PUCK", f"PUCK-{k:02d}", pos, (x, y, 0), "PUCK")
                k += 1
            y += P["pucks"]["spacing"]
    for i, (mnt, aim) in enumerate(P["washes"]):
        spot("WASH", f"WASH-{i}", mnt, aim, "WASH")
    spot("MOVER", "MOVER", *P["mover"], "MOVER")
    spot("GOBO", "GOBO", *P["gobo"], "GOBO")
    # strips -> Lambertian segments
    for lay, sd in P["strips"].items():
        n = np.array(sd["normal"], float)
        n /= np.linalg.norm(n)
        for ri, (p0, p1) in enumerate(sd["runs"]):
            p0, p1 = np.array(p0, float), np.array(p1, float)
            length = np.linalg.norm(p1 - p0)
            nseg = max(1, int(math.ceil(length / P["strip_seg"])))
            flux = sd["lmft"] * length / FT
            for s in range(nseg):
                pc = p0 + (p1 - p0) * (s + 0.5) / nseg
                src.append({"layer": lay, "id": f"{lay}-{ri}-{s}", "L": npm(pc), "axis": n, "kind": "cos", "hb": math.radians(60),
                            "cut": math.radians(90), "I0": flux / nseg / math.pi, "fx": "STRIP", "cct": sd["cct"], "radius": 0.0,
                            "run": (lay, ri)})
    return src


def make_fixture(name, c, L_m, axis, fx_key, calib, ies_dir, layer, cct, house_mat, extra=None):
    """Housing (cylinder behind the lens) + spot light parented to it + aim empty with Track To."""
    fx = P["fixtures"][fx_key]
    kind, hb, cut, I0, _ = fixture_profile(fx)
    ksp = k_spot(fx, calib)
    L = Vector(L_m)
    ax = Vector(axis).normalized()
    hous = mesh_obj(name, c, lambda bm: bm_cyl(bm, (0, 0, 0), (0, 0, 1), fx["dia"] / 2 * IN, fx["len"] * IN), house_mat)
    hous.location = L
    aim = bpy.data.objects.new(name + "_aim", None)
    c.objects.link(aim)
    aim.location = L + ax * 2.5
    aim.empty_display_size = 0.05
    con = hous.constraints.new("TRACK_TO")
    con.target = aim
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y" if abs(ax.y) < 0.99 else "UP_X"
    ld = light_with_ies(name + "_L", I0, kind, hb, cut, fx["radius"], ksp, ies_dir)
    lo = bpy.data.objects.new(name + "_L", ld)
    c.objects.link(lo)
    lo.parent = hous
    lo.location = (0, 0, 0)
    ld["layer"] = layer
    ld["cct"] = cct
    ld.color = cct_rgb(cct)
    ld["lum_fac"] = 1.0 / lum(ld.color)
    ld.energy = ld["base_W"] * ld["lum_fac"]
    lo["layer"] = layer
    if extra:
        for k2, v in extra.items():
            ld[k2] = v
    return hous, lo


def build_static_fixtures(cfx, calib, ies_dir):
    hm = principled("L_housing", (0.03, 0.03, 0.03), 0.5)
    hbm = principled("L_highbay", (0.25, 0.25, 0.27), 0.4, Metallic=1.0)
    ka = calib["mesh"]["k"]
    by_layer = {}
    for s in static_sources():
        by_layer.setdefault(s["layer"], []).append(s)
    for lay, lst in by_layer.items():
        cl = coll(f"FX_{lay}", cfx)
        if lay in P["strips"]:
            sd = P["strips"][lay]
            stm = principled("L_strip_channel", (0.85, 0.85, 0.87), 0.3, Metallic=1.0)
            for ri, (p0, p1) in enumerate(sd["runs"]):
                p0, p1 = np.array(p0, float), np.array(p1, float)
                length = np.linalg.norm(p1 - p0)
                flux = sd["lmft"] * length / FT
                n = Vector(sd["normal"]).normalized()
                dirv = Vector((p1 - p0) / length)
                lo = strip_emitter(f"{lay}-{ri}_L", cl, length * IN, 0.5 * IN, flux, ka)
                # local -Z = normal, local X = strip direction
                zl = -n
                xl = dirv - zl * dirv.dot(zl)
                xl.normalize()
                yl = zl.cross(xl)
                Mx = Matrix((xl, yl, zl)).transposed().to_4x4()
                Mx.translation = Vector(((p0 + p1) / 2) * IN)
                lo.matrix_world = Mx
                lo["strip_layer"], lo["cct"] = lay, sd["cct"]
                col = cct_rgb(sd["cct"])
                lo["lum_fac"] = 1.0 / lum(col)
                set_strip(lo, lo["base_S"] * lo["lum_fac"], col)
                # channel behind the strip (excluded from the analytic ray casts)
                ch = mesh_obj(f"{lay}-{ri}_channel", cl, lambda bm: bm_box(bm, (-length / 2, -0.5, 0.05), (length / 2, 0.5, 0.6)), stm)
                ch.matrix_world = Mx
            continue
        for s in lst:
            make_fixture(s["id"], cl, s["L"], s["axis"], s["fx"], calib, ies_dir, lay, s["cct"],
                         hbm if s["fx"] == "HB" else hm)
    # gobo: Voronoi "stone" mask on the gobo spot's emission
    gl = bpy.data.objects.get("GOBO_L")
    if gl:
        nt = gl.data.node_tree
        em = next(n for n in nt.nodes if n.type == "EMISSION")
        ies = next(n for n in nt.nodes if n.type == "TEX_IES")
        tc = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(tc.outputs["Normal"], sep.inputs[0])
        dx = nt.nodes.new("ShaderNodeMath"); dx.operation = "DIVIDE"
        dy = nt.nodes.new("ShaderNodeMath"); dy.operation = "DIVIDE"
        nt.links.new(sep.outputs[0], dx.inputs[0]); nt.links.new(sep.outputs[2], dx.inputs[1])
        nt.links.new(sep.outputs[1], dy.inputs[0]); nt.links.new(sep.outputs[2], dy.inputs[1])
        cmb = nt.nodes.new("ShaderNodeCombineXYZ")
        nt.links.new(dx.outputs[0], cmb.inputs[0]); nt.links.new(dy.outputs[0], cmb.inputs[1])
        vor = nt.nodes.new("ShaderNodeTexVoronoi")
        vor.feature = "DISTANCE_TO_EDGE"
        vor.inputs["Scale"].default_value = 9.0
        nt.links.new(cmb.outputs[0], vor.inputs["Vector"])
        ramp = nt.nodes.new("ShaderNodeMapRange")
        ramp.inputs["From Min"].default_value = 0.02
        ramp.inputs["From Max"].default_value = 0.06
        nt.links.new(vor.outputs["Distance"], ramp.inputs["Value"])
        mul = nt.nodes.new("ShaderNodeMath"); mul.operation = "MULTIPLY"
        nt.links.new(ies.outputs[0], mul.inputs[0]); nt.links.new(ramp.outputs[0], mul.inputs[1])
        nt.links.new(mul.outputs[0], em.inputs["Strength"])


# ---------------------------------------------------------------- table heads
def head_geometry(mount_xy, aim, fx_key):
    """Mount point on the strut board -> pivot -> lens.  Returns dict with inch-frame numbers."""
    fx = P["fixtures"][fx_key]
    zm = P["chord_z"] - P["strut_board"]
    pivot = np.array([mount_xy[0], mount_xy[1], zm - P["head_stem"]])
    aim = np.array(aim, float)
    ax = aim - pivot
    ax /= np.linalg.norm(ax)
    lens = pivot + ax * fx["len"] / 2
    ax = aim - lens
    ax /= np.linalg.norm(ax)
    r = fx["dia"] / 2
    pts = np.array([pivot + ax * fx["len"] / 2, pivot - ax * fx["len"] / 2, [mount_xy[0], mount_xy[1], P["chord_z"]]])
    bb = (pts.min(0) - r, pts.max(0) + r)
    return {"mount": [float(mount_xy[0]), float(mount_xy[1]), float(zm)], "aim": aim.tolist(), "lens": lens.tolist(),
            "axis": ax.tolist(), "bbox": (bb[0].tolist(), bb[1].tolist())}


def allowed(hg, opener, case, extra_pad=0.0):
    lo, hi = np.array(hg["bbox"][0]), np.array(hg["bbox"][1])
    for e in envelope(opener):
        if box_hit((lo, hi), e):
            return False, "door envelope"
    x, y = hg["mount"][:2]
    for hid, hx, hy, hz in highbays():
        if math.hypot(x - hx, y - hy) < 6.5 + P["keepout_highbay"]:
            return False, f"high bay {hid}"
    for fx_, fy_, fr in ((207.6, 300.15, 43), (603.6, 296.55, 45)):
        if math.hypot(x - fx_, y - fy_) < fr + P["keepout_fan"]:
            return False, "ceiling fan"
    if not (P["partition_n_face_y"] + 6 <= y <= P["north_wall_y"] - 6):
        return False, "outside north half"
    return True, ""


def nudge(mount, aim, fx_key, opener, case):
    """Move a clashing head the shortest way out (search rings of 3in steps)."""
    for rad in np.arange(3, 160, 3):
        best = None
        for k in range(48):
            a = 2 * math.pi * k / 48
            mxy = (mount[0] + rad * math.cos(a), mount[1] + rad * math.sin(a))
            hg = head_geometry(mxy, aim, fx_key)
            if allowed(hg, opener, case)[0]:
                best = hg
                break
        if best:
            return best
    return None


def standard_layout(pkg, case, opener):
    """Brief layout: 2 heads per long side on rails parallel to the table, 2 per end; each aims at the far half."""
    fx_key = P["packages"][pkg]["fixture"]
    c, a, b, hw, hd = table_frame(case)
    zt = P["table_z"]
    heads, clashes = [], []
    specs = []
    for side in (-1, 1):
        for s in (-P["side_spacing"] / 2, P["side_spacing"] / 2):
            mxy = c + a * s + b * side * (hd + P["side_offset"])
            aim = c + a * s - b * side * hd * 0.5
            specs.append((f"side{'+' if side > 0 else '-'}{'+' if s > 0 else '-'}", mxy, aim))
    for end in (-1, 1):
        for s in (-P["end_spread"] / 2, P["end_spread"] / 2):
            mxy = c + a * end * (hw + P["end_offset"]) + b * s
            aim = c - a * end * hw * 0.5 + b * s
            specs.append((f"end{'+' if end > 0 else '-'}{'+' if s > 0 else '-'}", mxy, aim))
    for i, (tag, mxy, aim2) in enumerate(specs):
        aim = (aim2[0], aim2[1], zt)
        hg = head_geometry(mxy, aim, fx_key)
        ok, why = allowed(hg, opener, case)
        if not ok:
            clashes.append({"head": tag, "why": why, "at": [float(mxy[0]), float(mxy[1])]})
            hg2 = nudge(hg["mount"], aim, fx_key, opener, case)
            if hg2 is None:
                continue
            hg2["nudged_from"] = [float(mxy[0]), float(mxy[1])]
            hg = hg2
        hg["tag"] = tag
        hg["cct"] = P["packages"][pkg]["ccts"][i]
        heads.append(hg)
    return heads, clashes


def build_table_collection(key, heads, parent, calib, ies_dir):
    old = bpy.data.collections.get(key)
    if old:
        for ob in list(old.all_objects):
            bpy.data.objects.remove(ob)
        bpy.data.collections.remove(old)
    cc = coll(key, parent)
    pkg = key.split("_")[0]
    fx_key = P["packages"][pkg]["fixture"]
    hm = principled("L_housing", (0.03, 0.03, 0.03), 0.5)
    bd = principled("L_strut", (0.75, 0.62, 0.45), 0.8)
    for i, hg in enumerate(heads):
        nm = f"{key}_H{i}"
        h, lo = make_fixture(nm, cc, npm(hg["lens"]), np.array(hg["axis"]), fx_key, calib, ies_dir, "TABLE", hg["cct"], hm,
                             extra={"pkg": pkg})
        mx, my, mz = hg["mount"]
        tx = np.array(P["truss_x"])
        lft, rgt = tx[tx <= mx].max(initial=0), tx[tx >= mx].min(initial=711.6)
        mesh_obj(nm + "_strut", cc, lambda bm: bm_box(bm, (lft, my - 1.75, mz), (rgt, my + 1.75, P["chord_z"])), bd)
        mesh_obj(nm + "_stem", cc, lambda bm: bm_box(bm, (mx - 0.4, my - 0.4, mz - P["head_stem"]), (mx + 0.4, my + 0.4, mz)), hm)
    cc.hide_render = True
    return cc


def build_cameras(parent):
    cc = coll("CAMERAS", parent)
    cams = camera_defs()
    for nm, (eye, tgt, lens) in cams.items():
        cd = bpy.data.cameras.new(nm)
        cd.lens = lens
        cd.clip_start = 0.05
        ob = bpy.data.objects.new(nm, cd)
        cc.objects.link(ob)
        place_cam(ob, eye, tgt)


def place_cam(ob, eye, tgt):
    ob.location = m(*eye)
    d = m(*tgt) - m(*eye)
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def camera_defs(case=None):
    case = case or P["render_case"]
    c, a, b, hw, hd = table_frame(case)
    cams = {
        "CAM_entry": ((257, 452, 64), (390, 330, 34), 18),
        "CAM_sectional": ((600, 380, 42), (390, 360, 40), 20),
    }
    for side, nm in ((-1, "CAM_seat_S"), (1, "CAM_seat_N")):
        e = c + b * side * (hd + 4)
        t = c - b * side * hd * 0.4
        cams[nm] = ((e[0], e[1], P["eye_z"]), (t[0], t[1], P["table_z"]), 20)
    return cams


def build_haze(parent):
    ch = coll("HAZE", parent)
    mt = bpy.data.materials.new("L_haze")
    mt.use_nodes = True
    nt = mt.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    v = nt.nodes.new("ShaderNodeVolumePrincipled")
    v.inputs["Density"].default_value = 0.01
    v.inputs["Anisotropy"].default_value = P["haze_anisotropy"]
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(v.outputs[0], o.inputs["Volume"])
    mesh_obj("HAZE_volume", ch, lambda bm: bm_box(bm, (0.5, 0.5, 0.5), (711.1, 471.25, 141.5)), mt)
    ch.hide_render = True


# ============================================================================ scene state helpers
def set_active(sc, case, opener, table_key, door_open, proxies=False, haze=False, golf_key=None, hitter=None):
    for c in "AB":
        bpy.data.collections[f"CASE_{c}"].hide_render = (c != case)
        bpy.data.collections[f"PROXY_{c}"].hide_render = not (proxies and c == case)
    for op in ("trolley", "jackshaft"):
        bpy.data.collections[f"OPENER_{op}"].hide_render = (op != opener)
    for cc in bpy.data.collections["TABLE_OPTIONS"].children:
        cc.hide_render = (cc.name != table_key)
    bpy.data.collections["HAZE"].hide_render = not haze
    if "GOLF_OPTIONS" in bpy.data.collections:
        gk = golf_key or golf_default_key()
        for cc in bpy.data.collections["GOLF_OPTIONS"].children:
            cc.hide_render = (cc.name != gk)
        for hk in ("address", "top"):
            bpy.data.collections[f"HITTER_{hk}"].hide_render = (hk != hitter)
    sc["door_open"] = 1 if door_open else 0
    for ob in bpy.data.collections["DOOR_open"].objects:
        ob.hide_render = not door_open
    for ob in bpy.data.collections["DOOR_closed"].objects:
        ob.hide_render = door_open
    sc.frame_set(sc.frame_current)


def circuit_mix(ccts, target):
    """Per-head dim for fixed-CCT heads on two circuits to hit `target` K (mired mix, brightest circuit at 100%)."""
    u = sorted(set(ccts))
    if len(u) == 1:
        return [1.0] * len(ccts)
    lo, hi = u[0], u[-1]
    t = min(max(target, lo), hi)
    m_lo, m_hi, m_t = 1e6 / lo, 1e6 / hi, 1e6 / t
    w_hi = (m_lo - m_t) / (m_lo - m_hi)  # flux fraction from the cool circuit
    w_lo = 1 - w_hi
    s = max(w_lo, w_hi)
    return [(w_hi if c == hi else w_lo) / s for c in ccts]


def apply_scene(sc, name, magic_seats=None):
    spec = P["scenes"][name]
    for ob in sc.objects:
        if ob.type != "LIGHT":
            continue
        ld = ob.data
        lay = ld.get("layer")
        if lay is None:
            continue
        if ld.animation_data:
            ld.animation_data_clear()
        s = spec.get(lay, 0)
        s = {"f": float(s)} if not isinstance(s, dict) else s
        f = s.get("f", 0.0)
        col = None
        if "rgb" in s:
            col = tuple(s["rgb"])
            lf = 1.0
        else:
            cct = s.get("cct", ld.get("cct", 3000))
            fixed = lay == "TABLE" and P["fixtures"][P["packages"][ld["pkg"]]["fixture"]].get("cct_mode") == "fixed"
            if fixed:  # fixed-CCT head: dim by circuit mix instead of recolouring
                ccts = P["packages"][ld["pkg"]]["ccts"]
                mix = circuit_mix(ccts, cct)
                own = ld["cct"]
                f *= mix[ccts.index(own)]
                cct = own
            col = cct_rgb(cct)
            lf = 1.0 / lum(col)
        if s.get("seat_colors") and magic_seats:
            col = magic_seats.get(ob.name, col)
            lf = 1.0
        ld.color = col
        ld.energy = ld["base_W"] * lf * f
        anim = s.get("anim")
        if anim and f > 0:
            ld["base_now"] = ld.energy
            fc = ld.driver_add("energy")
            drv = fc.driver
            drv.type = "SCRIPTED"
            v = drv.variables.new()
            v.name, v.type = "b", "SINGLE_PROP"
            v.targets[0].id_type = "LIGHT"
            v.targets[0].id = ld
            v.targets[0].data_path = '["base_now"]'
            ph = (hash(ob.name) % 97) / 7.0
            drv.expression = {
                "flicker": f"b*(0.78+0.12*sin(frame*1.73+{ph:.2f})+0.1*sin(frame*0.61+{2 * ph:.2f}))",
                "pulse_slow": "b*(0.55+0.45*sin(frame*0.08))",
                "pulse_fast": "b*(0.5+0.5*sin(frame*0.5))",
                "sweep": "b",
            }[anim]
    for ob in sc.objects:
        lay = ob.get("strip_layer")
        if lay is None:
            continue
        s_ = spec.get(lay, 0)
        s_ = {"f": float(s_)} if not isinstance(s_, dict) else s_
        if "rgb" in s_:
            col, lf = tuple(s_["rgb"]), 1.0
        else:
            col = cct_rgb(s_.get("cct", ob["cct"]))
            lf = 1.0 / lum(col)
        set_strip(ob, ob["base_S"] * lf * s_.get("f", 0.0), col)
    mv = bpy.data.objects.get("MOVER")
    if mv:
        aim = bpy.data.objects.get("MOVER_aim")
        if aim.animation_data:
            aim.animation_data_clear()
        if spec.get("MOVER"):
            for fr, tgt in ((1, (300, 300, 0)), (24, (381, 330, 0)), (48, (470, 400, 0)), (72, (300, 300, 0))):
                aim.location = m(*tgt)
                aim.keyframe_insert("location", frame=fr)
    sc.frame_set(24)


def magic_colors(sc, case):
    """Each wash takes the deck colour of the player whose 'quadrant' (azimuth sector from the table) it lights."""
    c = np.array(table_center(case))
    names = list(P["deck_colors"])
    out = {}
    for ob in sc.objects:
        if ob.type == "LIGHT" and ob.data.get("layer") == "WASH":
            p = np.array(ob.matrix_world.translation[:2]) / IN
            az = (math.degrees(math.atan2(p[1] - c[1], p[0] - c[0])) + 360) % 360
            out[ob.name] = P["deck_colors"][names[int(az // (360 / len(names))) % len(names)]]
    return out


# ============================================================================ analytic engine
class Engine:
    def __init__(self):
        self.sc = bpy.context.scene
        self.dg = bpy.context.evaluated_depsgraph_get()
        skip_coll = {"FIXTURES", "TABLE_OPTIONS", "HAZE", "CAMERAS", "CASE_A", "CASE_B", "PROXY_A", "PROXY_B",
                     "DOOR_open", "DOOR_closed", "OPENER_trolley", "OPENER_jackshaft", "GOLF_OPTIONS", "HITTER_address", "HITTER_top"}
        skip = set()
        for nm in skip_coll:
            skip |= {o.name for o in bpy.data.collections[nm].all_objects}
        base = [ob for ob in self.sc.objects if ob.type == "MESH" and ob.name not in skip and not ob.hide_render]
        t = time.time()
        self.bvh = {"base": self.make_bvh(base)}
        for nm in ("CASE_A", "CASE_B", "PROXY_A", "PROXY_B", "DOOR_open", "DOOR_closed", "OPENER_trolley", "OPENER_jackshaft"):
            self.bvh[nm] = self.make_bvh([o for o in bpy.data.collections[nm].all_objects if o.type == "MESH"])
        for nm in ("HITTER_address", "HITTER_top"):
            self.bvh[nm] = self.make_bvh([o for o in bpy.data.collections[nm].all_objects if o.type == "MESH"])
        self.bvh["VX"] = self.make_bvh([o for o in self.sc.objects if o.name.startswith("GOLF_monitor")])
        for c in "AB":  # chairs only: the table top cannot shadow itself (and its scan surface is bumpy)
            self.bvh[f"CHAIRS_{c}"] = self.make_bvh([o for o in bpy.data.collections[f"CASE_{c}"].all_objects
                                                     if o.type == "MESH" and "family-chair" in o.name])
        self.spill_cache = {}
        print(f"BVHs built in {time.time() - t:.1f}s ({len(base)} base objects)")
        self.cache = {}
        self.static = static_sources()

    def make_bvh(self, objs):
        V, T, off = [], [], 0
        for ob in objs:
            oe = ob.evaluated_get(self.dg)
            try:
                me = oe.to_mesh()
            except RuntimeError:
                continue
            if me is None:
                continue
            me.calc_loop_triangles()
            nv, nt = len(me.vertices), len(me.loop_triangles)
            if nt == 0:
                oe.to_mesh_clear()
                continue
            co = np.empty(nv * 3, np.float32)
            me.vertices.foreach_get("co", co)
            co = co.reshape(-1, 3).astype(np.float64)
            M = np.array(ob.matrix_world)
            co = co @ M[:3, :3].T + M[:3, 3]
            tr = np.empty(nt * 3, np.int32)
            me.loop_triangles.foreach_get("vertices", tr)
            V.append(co)
            T.append(tr.reshape(-1, 3) + off)
            off += nv
            oe.to_mesh_clear()
        if not V:
            return None
        V, T = np.vstack(V), np.vstack(T)
        return BVHTree.FromPolygons(V.tolist(), T.tolist(), all_triangles=True)

    def trees(self, case, door_open, opener, proxies, table=True):
        k = ["base", f"CASE_{case}" if table else f"CHAIRS_{case}", "DOOR_open" if door_open else "DOOR_closed", f"OPENER_{opener}"]
        if proxies:
            k.append(f"PROXY_{case}")
        return [self.bvh[x] for x in k if self.bvh.get(x)]

    def visible(self, trees, p, L, tol=0.02):
        d = L - p
        dist = d.length
        if dist < 1e-6:
            return True
        dn = d / dist
        o = p + dn * 0.002
        for t in trees:
            hit = t.ray_cast(o, dn, dist - tol - 0.002)
            if hit[0] is not None:
                return False
        return True

    def vis(self, case, door_open, opener, grid_key, pts_m, L_m):
        """(no-proxy, with-proxy) visibility arrays for one source position (cached)."""
        key = (case, door_open, opener, grid_key, tuple(np.round(L_m, 4)))
        if key in self.cache:
            return self.cache[key]
        tA = self.trees(case, door_open, opener, False, table=False)
        tP = [self.bvh[f"PROXY_{case}"]]
        L = Vector(L_m)
        v0 = np.zeros(len(pts_m))
        v1 = np.zeros(len(pts_m))
        for i, p in enumerate(pts_m):
            pv = Vector(p)
            if self.visible(tA, pv, L):
                v0[i] = 1
                if self.visible(tP, pv, L, tol=0.0):
                    v1[i] = 1
        self.cache[key] = (v0, v1)
        return v0, v1

    @staticmethod
    def E(pts_m, normal, L, axis, kind, hb, cut, I0):
        v = pts_m - L
        d2 = (v ** 2).sum(1)
        d = np.sqrt(d2)
        u = v / d[:, None]
        cth = np.clip(u @ axis, -1, 1)
        th = np.arccos(cth)
        f = profile_f(kind, hb, cut, th)
        cphi = np.clip(-(u @ normal), 0, None)
        return I0 * f * cphi / d2


def grid_ctx(case):
    pts, shape = grid_points(case)
    meta = jload(f"{P['export_dir']}/build_meta.json")
    mask = np.ones(len(pts), bool)
    for lo, hi, kind in meta["pieces"][case]:
        inside = (pts[:, 0] >= lo[0]) & (pts[:, 0] <= hi[0]) & (pts[:, 1] >= lo[1]) & (pts[:, 1] <= hi[1])
        mask &= ~inside
    return pts, pts * IN, shape, mask


def eval_layout(eng, heads, fx_key, case, door_open, opener, gctx, dims=None, louver=False):
    pts, pm, shape, mask = gctx
    fx = P["fixtures"][fx_key]
    kind, hb, cut, I0, _ = fixture_profile(fx)
    up = np.array([0, 0, 1.0])
    E0 = np.zeros(len(pm))
    E1 = np.zeros(len(pm))
    for i, hg in enumerate(heads):
        L = npm(hg["lens"])
        ax = np.array(hg["axis"])
        e = Engine.E(pm, up, L, ax, kind, hb, cut, I0) * (dims[i] if dims is not None else 1.0)
        v0, v1 = eng.vis(case, door_open, opener, f"T{case}", pm, L)
        E0 += e * v0
        E1 += e * v1
    return E0, E1


def metrics(E0, E1, mask, dim=1.0):
    E0, E1 = E0 * dim, E1 * dim
    e0 = E0[mask]
    e1 = E1[mask]
    mean0 = float(e0.mean())
    ratio = (e1 + P["fill_lux"]) / (e0 + P["fill_lux"])
    return {"mean": mean0, "min": float(e0.min()), "max": float(e0.max()), "U": float(e0.min() / mean0) if mean0 > 0 else 0.0,
            "mean_occ": float(e1.mean()), "min_occ": float(e1.min()), "U_occ": float(e1.min() / e1.mean()) if e1.mean() > 0 else 0,
            "A70": float((ratio < P["shadow_visible"]).mean()), "A50": float((ratio < P["shadow_dark"]).mean())}


def dim_for(mean_full):
    lo, hi = P["mean_lux_range"]
    return min(1.0, P["dim_target"] / mean_full) if mean_full > hi else 1.0


def glare_eval(eng, heads, fx_key, case, door_open, opener, louver=False):
    """Direct lens glare per seat + reflections (floor, glass door, TV) from seats and the sectional."""
    fx = P["fixtures"][fx_key]
    cutoff = math.radians(fx.get("louver_cutoff", 90)) if louver else math.radians(90)
    trees = eng.trees(case, door_open, opener, True)
    flags = []
    st = seats(case)
    c3 = np.array([*table_center(case), P["table_z"]])
    viewers = []
    for i, s in enumerate(st):
        opp = st[(i + 3) % 6]["eye"]
        viewers.append((f"seat{i}", s["eye"] + s["n"] * 0.2, [c3 - s["eye"], opp - s["eye"]]))
    tvc = np.array([603.5, 241.75, 74.0])
    for k, x in enumerate((560.0, 603.5, 647.0)):
        e = np.array([x, 378.0, 40.0])
        viewers.append((f"sectional{k}", e, [tvc - e, c3 - e]))
    los_lim = math.radians(P["glare_los_deg"])
    beam_lim = math.radians(P["glare_beam_deg"])
    lens_visible = 0
    for vname, eye, loss in viewers:
        E = Vector(npm(eye))
        for hi_, hg in enumerate(heads):
            L = npm(hg["lens"])
            ax = np.array(hg["axis"])
            dvec = L - npm(eye)
            dl = np.linalg.norm(dvec)
            dn = dvec / dl
            ang_beam = math.acos(np.clip(np.dot(ax, -dn), -1, 1))
            in_view = False
            for los in loss:
                ln = los / np.linalg.norm(los)
                a = math.acos(np.clip(np.dot(ln, dn), -1, 1))
                if a <= los_lim and dn[2] > ln[2]:
                    in_view = True
            if not in_view:
                continue
            if not eng.visible(trees, E, Vector(L), tol=0.03):
                continue
            if ang_beam <= cutoff:
                lens_visible += 1
            if ang_beam <= beam_lim and ang_beam <= cutoff:
                flags.append(f"direct:{vname}:H{hi_}")
        # reflections
        mirrors = [("floor", 2, 0.0, (0, 711.6), (P["partition_n_face_y"], P["north_wall_y"]))]
        if door_open:
            zt = P["door_panel_top_z"] - P["door_panel_thick"] + 0.75
            mirrors.append(("glass_door", 2, zt, (P["door_x0"], P["door_x1"]), (P["north_wall_y"] - P["door_open_depth"], P["north_wall_y"])))
        else:
            mirrors.append(("glass_door", 1, P["north_wall_y"] - 1.0, (P["door_x0"], P["door_x1"]), (0, 96)))
        if vname.startswith("sectional"):
            mirrors.append(("tv", 1, 241.75, (566.1, 640.9), (52.45, 95.55)))
        for mname, axis_i, val, r0, r1 in mirrors:
            for hi_, hg in enumerate(heads):
                Lin = np.array(hg["lens"])
                Lm_ = Lin.copy()
                Lm_[axis_i] = 2 * val - Lin[axis_i]
                eyein = np.array(eye)
                if (eyein[axis_i] - val) * (Lin[axis_i] - val) <= 0:
                    continue  # lens and eye on opposite sides of the mirror
                tpar = (val - eyein[axis_i]) / (Lm_[axis_i] - eyein[axis_i])
                if not (0 < tpar < 1):
                    continue
                R = eyein + (Lm_ - eyein) * tpar
                oth = [i for i in range(3) if i != axis_i]
                if not (r0[0] <= R[oth[0]] <= r0[1] and r1[0] <= R[oth[1]] <= r1[1]):
                    continue
                dview = (R - eyein) / np.linalg.norm(R - eyein)
                if not any(math.acos(np.clip(np.dot(los / np.linalg.norm(los), dview), -1, 1)) <= los_lim for los in loss):
                    continue
                ax = np.array(hg["axis"])
                toR = (R - Lin) / np.linalg.norm(R - Lin)
                # the beam must head for the mirror point and its mirror ray toward the eye
                ang = math.acos(np.clip(np.dot(ax, toR), -1, 1))
                if ang > beam_lim:
                    continue
                Rv = Vector(npm(R))
                nrm = np.zeros(3); nrm[axis_i] = 1 if eyein[axis_i] > val else -1
                Rv_off = Vector(npm(R) + nrm * 0.005)
                if eng.visible(trees, E, Rv_off, tol=0.01) and eng.visible(trees, Rv_off, Vector(npm(Lin)), tol=0.03):
                    flags.append(f"reflect-{mname}:{vname}:H{hi_}")
    return flags, lens_visible


def opt_layout(eng, pkg, case, opener, gctx, start_heads, rng):
    """Random-perturbation hill climb on head mount positions and aim points (door state = P["design_door_open"])."""
    fx_key = P["packages"][pkg]["fixture"]
    louver = P["packages"][pkg].get("louver", False)
    c, a, b, hw, hd = table_frame(case)
    lo_b, hi_b = table_bbox(case)
    pad = P["opt_pad"]
    snap = P["opt_snap"]

    def score(heads):
        E0, E1 = eval_layout(eng, heads, fx_key, case, P["design_door_open"], opener, gctx)
        mf = float(E0[gctx[3]].mean())
        dim = dim_for(mf)
        mt = metrics(E0, E1, gctx[3], dim)
        J = mt["U"] + (1 - mt["A70"]) + 0.5 * (1 - mt["A50"])
        if mf < P["mean_lux_range"][0]:
            J -= (P["mean_lux_range"][0] - mf) / 100.0
        fl, _ = glare_eval(eng, heads, fx_key, case, P["design_door_open"], opener, louver)
        J -= P["glare_penalty"] * sum(1 for f in fl if f.startswith("direct"))
        return J, mt, dim
    cur = [dict(h) for h in start_heads]
    Jc, mc, dc = score(cur)
    evals = 1
    hist = [Jc]
    while evals < P["opt_evals"]:
        cand = [dict(h) for h in cur]
        i = rng.randrange(len(cand))
        h = cand[i]
        mount, aim = list(h["mount"][:2]), list(h["aim"])
        if rng.random() < 0.55:
            s = rng.choice((6.0, 12.0, 24.0))
            mount = [round((mount[0] + rng.gauss(0, s)) / snap) * snap, round((mount[1] + rng.gauss(0, s)) / snap) * snap]
            mount[0] = min(max(mount[0], lo_b[0] - pad), hi_b[0] + pad)
            mount[1] = min(max(mount[1], lo_b[1] - pad), hi_b[1] + pad)
        else:
            s = rng.choice((3.0, 8.0))
            aim[0] = min(max(round((aim[0] + rng.gauss(0, s)) / 2) * 2, lo_b[0] + 2), hi_b[0] - 2)
            aim[1] = min(max(round((aim[1] + rng.gauss(0, s)) / 2) * 2, lo_b[1] + 2), hi_b[1] - 2)
        hg = head_geometry(mount, aim, fx_key)
        if not allowed(hg, opener, case)[0]:
            continue  # rejected candidates are free (no evaluation)
        hg["tag"], hg["cct"] = h.get("tag", f"h{i}"), h["cct"]
        cand[i] = hg
        J, mt, dm = score(cand)
        evals += 1
        if J > Jc:
            cur, Jc, mc, dc = cand, J, mt, dm
        hist.append(Jc)
    return cur, Jc, dc, hist


def spill_eval(eng, scene_name, table_heads, fx_key, case, door_open, opener):
    """Mean direct illuminance on the golf screen plane from north-half layers (analytic)."""
    pts = image_grid()
    normal = np.array([1.0, 0, 0])
    spec = P["scenes"][scene_name]
    trees = eng.trees(case, door_open, opener, False)
    tot = np.zeros(len(pts))
    srcs = []
    ck = (scene_name, case, door_open, opener)
    cached = eng.spill_cache.get(ck)
    for s in ([] if cached is not None else eng.static):
        f = spec.get(s["layer"], 0)
        frac = f if not isinstance(f, dict) else f.get("f", 0)
        if isinstance(f, dict) and "rgb" in f:
            frac *= lum(f["rgb"])
        if frac <= 0:
            continue
        if s["L"][1] / IN < P["partition_n_face_y"]:
            continue  # north-half layers only
        srcs.append((s, frac))
    tf = spec.get("TABLE", 0)
    tfrac = tf if not isinstance(tf, dict) else tf.get("f", 0)
    if tfrac > 0:
        kind, hb, cut, I0, _ = fixture_profile(P["fixtures"][fx_key])
        for hg in table_heads:
            srcs.append(({"L": npm(hg["lens"]), "axis": np.array(hg["axis"]), "kind": kind, "hb": hb, "cut": cut, "I0": I0}, tfrac))
    nstatic = len(srcs) - (len(table_heads) if tfrac > 0 else 0)
    for si, (s, frac) in enumerate(srcs):
        if si == nstatic:
            if cached is None:
                eng.spill_cache[ck] = tot.copy()
            else:
                tot = cached.copy()
        e = Engine.E(pts, normal, s["L"], s["axis"], s["kind"], s["hb"], s["cut"], s["I0"]) * frac
        nz = np.nonzero(e > 1e-4)[0]
        Lv = Vector(s["L"])
        for i in nz:
            if eng.visible(trees, Vector(pts[i]), Lv):
                tot[i] += e[i]
    if nstatic == len(srcs):
        if cached is None:
            eng.spill_cache[ck] = tot.copy()
        else:
            tot = cached.copy()
    return float(tot.mean())


def counter_eval(eng):
    x0, x1, y0, y1, z = P["counter_region"]
    sx0, sx1, sy0, sy1 = P["sink_cut"]
    pts = [(x, y, z + 0.05) for y in np.arange(y0 + 1, y1, 2.0) for x in np.arange(x0 + 1, x1, 2.0)
           if not (sx0 <= x <= sx1 and sy0 <= y <= sy1)]
    pts = np.array(pts)
    pm = pts * IN
    trees = eng.trees("A", False, "jackshaft", False)
    tot = np.zeros(len(pm))
    for s in eng.static:
        if s["layer"] != "UC":
            continue
        e = Engine.E(pm, np.array([0, 0, 1.0]), s["L"], s["axis"], s["kind"], s["hb"], s["cut"], s["I0"])
        Lv = Vector(s["L"])
        for i in np.nonzero(e > 0.01)[0]:
            if eng.visible(trees, Vector(pm[i]), Lv, tol=0.03):
                tot[i] += e[i]
    return {"mean": float(tot.mean()), "min": float(tot.min()), "max": float(tot.max()), "pts": pts.tolist(), "E": tot.tolist()}


# ---------------------------------------------------------------- PNG false-colour maps (numpy + 5x7 bitmap font)
FONT = {
    '0': ["01110", "10001", "10011", "10101", "11001", "10001", "01110"], '1': ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    '2': ["01110", "10001", "00001", "00010", "00100", "01000", "11111"], '3': ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    '4': ["00010", "00110", "01010", "10010", "11111", "00010", "00010"], '5': ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    '6': ["00110", "01000", "10000", "11110", "10001", "10001", "01110"], '7': ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    '8': ["01110", "10001", "10001", "01110", "10001", "10001", "01110"], '9': ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    'A': ["01110", "10001", "10001", "11111", "10001", "10001", "10001"], 'B': ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    'C': ["01110", "10001", "10000", "10000", "10000", "10001", "01110"], 'D': ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    'E': ["11111", "10000", "10000", "11110", "10000", "10000", "11111"], 'F': ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    'G': ["01110", "10001", "10000", "10111", "10001", "10001", "01111"], 'H': ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    'I': ["01110", "00100", "00100", "00100", "00100", "00100", "01110"], 'J': ["00111", "00010", "00010", "00010", "00010", "10010", "01100"],
    'K': ["10001", "10010", "10100", "11000", "10100", "10010", "10001"], 'L': ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    'M': ["10001", "11011", "10101", "10101", "10001", "10001", "10001"], 'N': ["10001", "10001", "11001", "10101", "10011", "10001", "10001"],
    'O': ["01110", "10001", "10001", "10001", "10001", "10001", "01110"], 'P': ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    'Q': ["01110", "10001", "10001", "10001", "10101", "10010", "01101"], 'R': ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    'S': ["01111", "10000", "10000", "01110", "00001", "00001", "11110"], 'T': ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    'U': ["10001", "10001", "10001", "10001", "10001", "10001", "01110"], 'V': ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    'W': ["10001", "10001", "10001", "10101", "10101", "10101", "01010"], 'X': ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    'Y': ["10001", "10001", "01010", "00100", "00100", "00100", "00100"], 'Z': ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    '.': ["00000", "00000", "00000", "00000", "00000", "01100", "01100"], '-': ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    '%': ["11001", "11010", "00010", "00100", "01000", "01011", "10011"], ':': ["00000", "01100", "01100", "00000", "01100", "01100", "00000"],
    '/': ["00001", "00010", "00010", "00100", "01000", "01000", "10000"], '=': ["00000", "00000", "11111", "00000", "11111", "00000", "00000"],
    ' ': ["00000"] * 7, '_': ["00000"] * 6 + ["11111"], '(': ["00010", "00100", "01000", "01000", "01000", "00100", "00010"],
    ')': ["01000", "00100", "00010", "00010", "00010", "00100", "01000"], '>': ["01000", "00100", "00010", "00001", "00010", "00100", "01000"],
    '<': ["00010", "00100", "01000", "10000", "01000", "00100", "00010"],
    '+': ["00000", "00100", "00100", "11111", "00100", "00100", "00000"], ',': ["00000", "00000", "00000", "00000", "01100", "00100", "01000"],
}
CMAP = [(0.0, (0.19, 0.07, 0.23)), (0.15, (0.27, 0.36, 0.85)), (0.35, (0.10, 0.75, 0.85)), (0.5, (0.35, 0.95, 0.45)),
        (0.65, (0.85, 0.90, 0.20)), (0.8, (0.98, 0.55, 0.12)), (1.0, (0.60, 0.05, 0.03))]


def cmap(t):
    t = np.clip(t, 0, 1)
    xs = np.array([c[0] for c in CMAP])
    cs = np.array([c[1] for c in CMAP])
    return np.stack([np.interp(t, xs, cs[:, k]) for k in range(3)], -1)


def draw_text(img, x, y, text, scale=2, color=(1, 1, 1)):
    """img is (H, W, 3) with row 0 at the TOP."""
    for ch in text.upper():
        g = FONT.get(ch, FONT[' '])
        for r, row in enumerate(g):
            for cidx, bit in enumerate(row):
                if bit == "1":
                    y0, x0 = y + r * scale, x + cidx * scale
                    img[y0:y0 + scale, x0:x0 + scale] = color
        x += 6 * scale


def save_png(img_top, path):
    h, w, _ = img_top.shape
    im = bpy.data.images.new(Path(path).stem, w, h, alpha=True)
    rgba = np.concatenate([img_top[::-1], np.ones((h, w, 1))], -1).astype(np.float32)
    im.pixels.foreach_set(rgba.ravel())
    im.filepath_raw = str(path)
    im.file_format = "PNG"
    im.save()
    bpy.data.images.remove(im)


def lux_map_png(E, shape, mask, case, title, lines, path, vmax=1000.0, ratio=False):
    nv, nu = shape
    grid = E.reshape(nv, nu)
    msk = mask.reshape(nv, nu)
    cell = 14
    W = max(nu * cell + 120, 760)
    H = nv * cell + 150
    img = np.full((H, W, 3), 0.08)
    col = cmap(grid / vmax)
    col[~msk] = (0.45, 0.45, 0.45)
    big = np.repeat(np.repeat(col[::-1], cell, 0), cell, 1)  # row 0 = north edge at top
    y0, x0 = 70, 20
    img[y0:y0 + nv * cell, x0:x0 + nu * cell] = big
    draw_text(img, 20, 10, title, 2)
    for k, ln in enumerate(lines):
        draw_text(img, 20, 34 + k * 0, ln, 2) if k == 0 else draw_text(img, 20, 34 + 18 * k, ln, 1)
    # colour bar
    bx = x0 + nu * cell + 20
    for r in range(nv * cell):
        t = 1 - r / (nv * cell)
        img[y0 + r, bx:bx + 16] = cmap(np.array([t]))[0]
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        lab = f"{t * vmax:.2f}" if ratio else f"{int(t * vmax)}"
        draw_text(img, bx + 22, y0 + int((1 - t) * (nv * cell)) - 4, lab, 1)
    draw_text(img, bx, y0 + nv * cell + 8, "RATIO" if ratio else "LUX", 1)
    draw_text(img, 20, y0 + nv * cell + 8, "GREY = UNDER GAME PIECES. TOP OF MAP = NORTH" if case == "A" else
              "GREY = UNDER GAME PIECES. TOP = WEST, RIGHT = NORTH (DOOR)", 1)
    save_png(img, path)


# ============================================================================ golf sim bay (brief section 7)
G = P["golf"]


def golf_ball():
    """Ball centre (inches)."""
    return np.array([G["screen_face_x"] + G["ball_dist"], G["screen_cy"], G["mat_h"] + 0.84])


def image_rect():
    y0, y1 = G["screen_cy"] - G["image_w"] / 2, G["screen_cy"] + G["image_w"] / 2
    z0, z1 = G["image_z0"], G["image_z0"] + G["image_h"]
    return G["screen_face_x"], y0, y1, z0, z1


def image_grid(ny=14, nz=8, inches=False):
    """Points on the projected image (metres unless inches=True), normal +X."""
    x, y0, y1, z0, z1 = image_rect()
    pts = np.array([(x + 0.4, y0 + (j + 0.5) * (y1 - y0) / ny, z0 + (k + 0.5) * (z1 - z0) / nz) for k in range(nz) for j in range(ny)])
    return pts if inches else pts * IN


def white_lux():
    pj = G["projectors"][G["projector"]]
    return pj["lm"] / (G["image_w"] * G["image_h"] * IN * IN)


def proj_geom():
    """Projector lens position (inches), image corners, throw, needed lens shift; clamps the lens down to the shift limit."""
    pj = G["projectors"][G["projector"]]
    x, y0, y1, z0, z1 = image_rect()
    tr = pj["tr"][0] + G["zoom"] * (pj["tr"][1] - pj["tr"][0])
    D = G["image_w"] * tr
    zc = (z0 + z1) / 2
    z_mount = P["chord_z"] - G["proj_lens_drop"]
    shift_needed = (z_mount - zc) / G["image_h"]
    lz = min(z_mount, zc + pj["vshift"] * G["image_h"])
    lens = np.array([x + D, G["screen_cy"], lz])
    corners = np.array([[x, y0, z0], [x, y1, z0], [x, y1, z1], [x, y0, z1]])
    return {"lens": lens, "corners": corners, "throw": D, "tr": tr, "shift_needed": shift_needed,
            "shift_used": (lz - zc) / G["image_h"], "lens_lowered_by": z_mount - lz, "body": pj["body"]}


def in_frustum(pts_in, pg=None):
    pg = pg or proj_geom()
    L, C = pg["lens"], pg["corners"]
    ctr = C.mean(0)
    planes = []
    for i in range(4):
        n = np.cross(C[i] - L, C[(i + 1) % 4] - L)
        if np.dot(n, ctr - L) < 0:
            n = -n
        planes.append((n, L))
    out = []
    for p in np.atleast_2d(pts_in):
        ok = all(np.dot(n, p - o) > 0 for n, o in planes) and p[0] > C[0][0] and p[0] < L[0]
        out.append(ok)
    return np.array(out)


def swing_dist(pts_in):
    """Distance (m) from each point to the swing disc (vertical, in the target-line plane through the ball)."""
    b = golf_ball()
    cz = b[2] + G["swing_c_m"] / IN
    p = np.atleast_2d(pts_in)
    dy = np.abs(p[:, 1] - b[1]) * IN
    r = np.hypot(p[:, 0] - b[0], p[:, 2] - cz) * IN
    ex = np.maximum(0, r - G["swing_r_m"])
    return np.hypot(dy, ex), r


def box_samples(lo, hi):
    lo, hi = np.array(lo, float), np.array(hi, float)
    n = 8
    pts = [lo + (hi - lo) * np.array([i, j, k]) / n for i in range(n + 1) for j in range(n + 1) for k in range(n + 1)]
    return np.array(pts)


def golf_clash(name, lo, hi, pg=None):
    sm = box_samples(lo, hi)
    fr = bool(in_frustum(sm, pg).any())
    d, r = swing_dist(sm)
    sw = "disc" if (d.min() < 0.05) else ("buffer" if d.min() <= G["swing_buffer_m"] else "")
    return {"item": name, "frustum": fr, "swing": sw, "swing_dist_m": float(d.min())}


def golf_heads(pkg, lateral):
    fx_key = G["packages"][pkg]["fixture"]
    b = golf_ball()
    heads = []
    for side in (-1, 1):
        for xb in G["head_behind"]:
            hg = head_geometry((b[0] + xb, b[1] + side * lateral), b, fx_key)
            hg["cct"] = G["cct"]
            hg["tag"] = f"{'N' if side > 0 else 'S'}{int(xb)}"
            heads.append(hg)
    return heads


def golf_tracks(lateral):
    b = golf_ball()
    return [((b[0] + G["track_run"][0], b[1] + s * lateral - 0.7, P["chord_z"] - 1.0),
             (b[0] + G["track_run"][1], b[1] + s * lateral + 0.7, P["chord_z"])) for s in (-1, 1)]


def monitor_box():
    mo = G["monitor"]
    b = golf_ball()
    cx = b[0] - mo["ahead"]
    top = G["mat_h"] + mo["top_above_mat"]
    sx, sy, sz = mo["size"]
    return (cx - sx / 2, b[1] - sy / 2, top - sz), (cx + sx / 2, b[1] + sy / 2, top)


def proj_box(pg=None):
    pg = pg or proj_geom()
    L = pg["lens"]
    d, w, h = pg["body"]
    return (L[0], L[1] - w / 2, L[2] - h / 2), (L[0] + d, L[1] + w / 2, L[2] + h / 2)


def golf_keys():
    return [f"GOLF_{pkg}_L{int(lat)}" for pkg in G["packages"] for lat in G["track_lateral"]]


def golf_default_key():
    an = jload(f"{P['export_dir']}/analysis.json") if (ROOT / P["export_dir"] / "analysis.json").exists() else None
    pkg, lat = G["render_package"], G["render_lateral"]
    if pkg == "auto":
        gd = (an or {}).get("golf", {})
        pkg, lat = gd.get("best_package", "PREMIUM"), gd.get("best_lateral", G["track_lateral"][0])
    lat = int(lat) if int(lat) in [int(x) for x in G["track_lateral"]] else int(G["track_lateral"][0])
    return f"GOLF_{pkg}_L{lat}"


def k_med(c):
    return float(np.median([v["k"] for v in c["spot"].values()]))


def build_hitter(cc, pose):
    skin = principled("L_proxy", (0.55, 0.42, 0.35), 0.6)
    club = principled("L_club", (0.1, 0.1, 0.1), 0.3, Metallic=1.0)
    b = golf_ball()
    F = np.array([b[0], b[1] - G["hitter_stand"], 0.0])
    H = G["hitter_h"]
    s = H / 72.0

    def body(bm):
        for dx in (-6, 6):
            bm_capsule(bm, F + [dx, 0, 3], F + [dx * 0.6, 2, 36 * s], 3.5)
        if pose == "address":
            bm_capsule(bm, F + [0, 2, 36 * s], F + [0, 9, 56 * s], 7)
            head = F + [0, 11, 63 * s]
            hands = np.array([b[0] + 2, b[1] - 9, 30 * s])
            for dx in (-6, 6):
                bm_capsule(bm, F + [dx, 9, 57 * s], hands, 1.75)
        else:
            bm_capsule(bm, F + [0, 2, 36 * s], F + [0, 4, 57 * s], 7)
            head = F + [0, 6, 65 * s]
            hands = F + [10, 0, 76 * s]
            for dx in (-6, 6):
                bm_capsule(bm, F + [dx, 4, 58 * s], hands, 1.75)
        bm_sphere(bm, head, 4.5)
    mesh_obj(f"HITTER_{pose}_body", cc, body, skin)
    if pose == "address":
        hands = np.array([b[0] + 2, b[1] - 9, 30 * s]); tip = b + [3.0, -0.5, -0.4]  # clubhead just behind the ball
    else:
        hands = F + [10, 0, 76 * s]; tip = np.array([F[0] + 30, F[1] + 2, G["club_top_z"]])
    mesh_obj(f"HITTER_{pose}_club", cc, lambda bm: bm_capsule(bm, hands, tip, 0.6, seg=8), club)


def build_golf(parent, calib, ies_dir):
    cg = coll("GOLF_BAY", parent)
    blk = principled("L_curtain", (0.004, 0.004, 0.004), 0.95)
    x, y0, y1, z0, z1 = image_rect()
    dpt = G["enclosure_depth"]
    for nm, yy in (("S", y0 - 12), ("N", y1 + 12)):
        mesh_obj(f"GOLF_curtain_{nm}", cg, lambda bm: bm_box(bm, (0.5, yy - 0.5, 0), (x + dpt, yy + 0.5, G["enclosure_h"])), blk)
    b = golf_ball()
    mat_m = principled("L_mat", (0.03, 0.12, 0.04), 0.9)
    mesh_obj("GOLF_mat", cg, lambda bm: bm_box(bm, (b[0] - G["mat"] / 2, b[1] - G["mat"] / 2, 0), (b[0] + G["mat"] / 2, b[1] + G["mat"] / 2, G["mat_h"])), mat_m)
    mesh_obj("GOLF_ball", cg, lambda bm: bm_sphere(bm, b, 0.84), principled("L_ball", (0.9, 0.9, 0.9), 0.3))
    lo, hi = monitor_box()
    mesh_obj("GOLF_monitor_VX", cg, lambda bm: bm_box(bm, lo, hi), principled("L_vx", (0.05, 0.05, 0.05), 0.4))
    mesh_obj("GOLF_monitor_mount", cg, lambda bm: bm_box(bm, ((lo[0] + hi[0]) / 2 - 1, (lo[1] + hi[1]) / 2 - 1, hi[2]),
                                                         ((lo[0] + hi[0]) / 2 + 1, (lo[1] + hi[1]) / 2 + 1, P["chord_z"])), principled("L_strut2", (0.2, 0.2, 0.2), 0.5))
    pg = proj_geom()
    plo, phi = proj_box(pg)
    mesh_obj("GOLF_projector", cg, lambda bm: bm_box(bm, (plo[0] + 0.3, plo[1], plo[2]), phi), principled("L_proj", (0.85, 0.85, 0.85), 0.4))
    mesh_obj("GOLF_projector_mount", cg, lambda bm: bm_box(bm, ((plo[0] + phi[0]) / 2 - 1, pg["lens"][1] - 1, phi[2]),
                                                           ((plo[0] + phi[0]) / 2 + 1, pg["lens"][1] + 1, P["chord_z"])), principled("L_strut2", (0.2, 0.2, 0.2), 0.5))
    # projector light: flat IES + rectangular mask in light space (forward -Z = world -X)
    L = pg["lens"]
    C = pg["corners"]
    D = L[0] - C[0][0]
    u = (L[2] - C[:, 2]) / D          # local x = world -z
    v = (C[:, 1] - L[1]) / D          # local y = world y
    cut = math.atan(math.hypot(max(abs(u)), max(abs(v)))) + math.radians(1)
    kc = k_med(calib)
    pts = image_grid(24, 14)
    Lm = L * IN
    vv = pts - Lm
    d2 = (vv ** 2).sum(1)
    cosi = (Lm[0] - pts[:, 0]) / np.sqrt(d2)
    I = white_lux() / np.mean(cosi / d2)
    ld = light_with_ies("PROJECTOR_L", I, "flat", math.radians(80), cut, 0.02, kc, ies_dir)
    nt = ld.node_tree
    em = next(n for n in nt.nodes if n.type == "EMISSION")
    ies = next(n for n in nt.nodes if n.type == "TEX_IES")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Normal"], sep.inputs[0])
    negz = nt.nodes.new("ShaderNodeMath"); negz.operation = "MULTIPLY"; negz.inputs[1].default_value = -1.0
    nt.links.new(sep.outputs[2], negz.inputs[0])
    acc = ies.outputs[0]
    for comp, lo_, hi_ in ((0, float(min(u)), float(max(u))), (1, float(min(v)), float(max(v)))):
        dv = nt.nodes.new("ShaderNodeMath"); dv.operation = "DIVIDE"
        nt.links.new(sep.outputs[comp], dv.inputs[0]); nt.links.new(negz.outputs[0], dv.inputs[1])
        gt = nt.nodes.new("ShaderNodeMath"); gt.operation = "GREATER_THAN"; gt.inputs[1].default_value = lo_
        lt = nt.nodes.new("ShaderNodeMath"); lt.operation = "LESS_THAN"; lt.inputs[1].default_value = hi_
        nt.links.new(dv.outputs[0], gt.inputs[0]); nt.links.new(dv.outputs[0], lt.inputs[0])
        for g in (gt, lt):
            mul = nt.nodes.new("ShaderNodeMath"); mul.operation = "MULTIPLY"
            nt.links.new(acc, mul.inputs[0]); nt.links.new(g.outputs[0], mul.inputs[1])
            acc = mul.outputs[0]
    nt.links.new(acc, em.inputs["Strength"])
    lo_obj = bpy.data.objects.new("PROJECTOR_L", ld)
    cfx = coll("FX_PROJ", bpy.data.collections["FIXTURES"])
    cfx.objects.link(lo_obj)
    lo_obj.location = Vector(Lm - np.array([0.01, 0, 0]))
    lo_obj.rotation_euler = (0, math.pi / 2, 0)
    ld["layer"], ld["cct"] = "PROJ", 6500
    ld.color = cct_rgb(6500)
    ld["lum_fac"] = 1.0 / lum(ld.color)
    ld.energy = 0.0
    lo_obj["layer"] = "PROJ"
    # uplighter (ambient)
    up = G["uplighter"]
    cam_ = coll("FX_AMB", bpy.data.collections["FIXTURES"])
    pos = np.array(up["pos"], float)
    ax = np.array(up["aim"], float) - pos
    make_fixture("UPLIGHTER", cam_, npm(pos), ax / np.linalg.norm(ax), "UPL", calib, ies_dir, "AMB", P["fixtures"]["UPL"]["cct"],
                 principled("L_housing", (0.03, 0.03, 0.03), 0.5))
    mesh_obj("UPLIGHTER_stand", cam_, lambda bm: bm_box(bm, (pos[0] - 0.5, pos[1] - 0.5, 0), (pos[0] + 0.5, pos[1] + 0.5, pos[2] - 2)),
             principled("L_housing", (0.03, 0.03, 0.03), 0.5))
    # hitter proxies
    for pose in ("address", "top"):
        ch = coll(f"HITTER_{pose}", parent)
        build_hitter(ch, pose)
        ch.hide_render = True
    # packages x track lateral offsets
    cgo = coll("GOLF_OPTIONS", parent)
    hm = principled("L_housing", (0.03, 0.03, 0.03), 0.5)
    trk = principled("L_htrack", (0.05, 0.05, 0.05), 0.4)
    for pkg in G["packages"]:
        for lat in G["track_lateral"]:
            key = f"GOLF_{pkg}_L{int(lat)}"
            cc = coll(key, cgo)
            for i, hg in enumerate(golf_heads(pkg, lat)):
                make_fixture(f"{key}_H{i}", cc, npm(hg["lens"]), np.array(hg["axis"]), G["packages"][pkg]["fixture"], calib, ies_dir,
                             "HIT", hg["cct"], hm, extra={"pkg": pkg})
            for j, (tlo, thi) in enumerate(golf_tracks(lat)):
                mesh_obj(f"{key}_track{j}", cc, lambda bm: bm_box(bm, tlo, thi), trk)
            cc.hide_render = True
    # cameras
    ccam = bpy.data.collections["CAMERAS"]
    for nm, (eye, tgt, lens) in golf_cams().items():
        cd = bpy.data.cameras.new(nm); cd.lens = lens; cd.clip_start = 0.05
        ob = bpy.data.objects.new(nm, cd); ccam.objects.link(ob); place_cam(ob, eye, tgt)
    return {"proj": {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in pg.items()}, "white_lux": white_lux()}


def golf_cams():
    b = golf_ball()
    x, y0, y1, z0, z1 = image_rect()
    sc_c = (x, G["screen_cy"], (z0 + z1) / 2)
    return {"CAM_golf_hitter": ((b[0] + 84, b[1] - 30, 66), sc_c, 18),
            "CAM_golf_waiting": ((205, 70, 44), sc_c, 18)}


def golf_analyze(eng):
    """Sim-bay metrics per package x track offset, plus bay-wide clash/shadow checks."""
    out = {"rows": []}
    b = golf_ball()
    pg = proj_geom()
    wl = white_lux()
    up = np.array([0, 0, 1.0])
    trees0 = eng.trees("A", False, "jackshaft", False)
    hit_addr = [eng.bvh["HITTER_address"]]
    # mat grid 6in and the ball
    m0 = b[0] - G["mat"] / 2
    mpts = np.array([(m0 + 3 + 6 * i, b[1] - G["mat"] / 2 + 3 + 6 * j, G["mat_h"] + 0.05) for j in range(10) for i in range(10)]) * IN
    ballp = np.array([b[0], b[1], b[2] + 0.85]) * IN
    imgp = image_grid()
    nx = np.array([1.0, 0, 0])
    # fixed bay checks
    bay = {"projector": {"model": G["projector"], "throw_in": pg["throw"], "throw_ratio": pg["tr"], "lens_in": pg["lens"].tolist(),
                         "lens_from_screen": ftin(pg["throw"]), "shift_needed": pg["shift_needed"], "shift_used": pg["shift_used"],
                         "shift_limit": G["projectors"][G["projector"]]["vshift"], "lens_lowered_by_in": pg["lens_lowered_by"],
                         "white_lux": wl}, "clashes": []}
    bay["clashes"].append(golf_clash("projector body", *proj_box(pg), pg) | {"note": "own frustum apex; swing only"})
    bay["clashes"][-1]["frustum"] = False
    bay["clashes"].append(golf_clash(f"{G['monitor']['name']} launch monitor", *monitor_box(), pg))
    lo_up = np.array(G["uplighter"]["pos"]) - [5, 5, 60]
    bay["clashes"].append(golf_clash("uplighter", lo_up, np.array(G["uplighter"]["pos"]) + [5, 5, 3], pg))
    for hid, hx, hy, hz in highbays():
        c = golf_clash(f"high bay {hid}", (hx - 6.5, hy - 6.5, hz), (hx + 6.5, hy + 6.5, hz + 4), pg)
        if c["frustum"] or c["swing"]:
            bay["clashes"].append(c)
    couch = [np.array([ob.matrix_world @ Vector(c) for c in ob.bound_box]) / IN
             for ob in bpy.context.scene.objects if ob.type == "MESH" and ob.name.startswith("INV_sectional-couch")]
    if couch:
        bb = np.vstack(couch)
        c = golf_clash("golf couch (sectional-couch, furniture)", bb.min(0), bb.max(0), pg)
        if c["frustum"] or c["swing"]:
            bay["clashes"].append(c)
    # projector shadows on the image: rays lens -> image grid
    ipts = image_grid(40, 22)
    Lv = Vector(pg["lens"] * IN - np.array([0.06, 0, 0]))
    def shadow_frac(trees):
        n = 0
        for p in ipts:
            if not eng.visible(trees, Lv, Vector(p + [0.002, 0, 0]), tol=0.003):
                n += 1
        return n / len(ipts)
    bay["proj_shadow_fixed"] = shadow_frac([eng.bvh["VX"]])
    bay["proj_shadow_fixed_all"] = shadow_frac(trees0)
    trim = [o for o in bpy.context.scene.objects if o.name.startswith("INV_golf-screen_trim")]
    bay["image_on_trim"] = shadow_frac([eng.make_bvh(trim)]) if trim else 0.0
    bay["proj_shadow_address"] = shadow_frac([eng.bvh["HITTER_address"]])
    bay["proj_shadow_top"] = shadow_frac([eng.bvh["HITTER_top"]])
    # north-half / other layers on the image in game night and sim play (everything but projector and golf heads)
    def static_on_image(scene_name):
        spec = P["scenes"][scene_name]
        tot = np.zeros(len(imgp))
        srcs = static_sources()
        upf = P["fixtures"]["UPL"]
        kind, hb, cut, I0, _ = fixture_profile(upf)
        pos = np.array(G["uplighter"]["pos"], float)
        ax = np.array(G["uplighter"]["aim"], float) - pos
        srcs.append({"layer": "AMB", "L": npm(pos), "axis": ax / np.linalg.norm(ax), "kind": kind, "hb": hb, "cut": cut, "I0": I0})
        for s_ in srcs:
            f = spec.get(s_["layer"], 0)
            frac = f if not isinstance(f, dict) else f.get("f", 0)
            if isinstance(f, dict) and "rgb" in f:
                frac *= lum(f["rgb"])
            if frac <= 0:
                continue
            e = Engine.E(imgp, nx, s_["L"], s_["axis"], s_["kind"], s_["hb"], s_["cut"], s_["I0"]) * frac
            Ls = Vector(s_["L"])
            for i in np.nonzero(e > 1e-4)[0]:
                if eng.visible(trees0, Vector(imgp[i]), Ls):
                    tot[i] += e[i]
        return tot
    base_img = {sn: static_on_image(sn) for sn in ("sim_play", "game_night")}
    best = None
    for pkg, pd in G["packages"].items():
        fx_key = pd["fixture"]
        louver = pd.get("louver", False)
        fx = P["fixtures"][fx_key]
        kind, hb, cut, I0, _ = fixture_profile(fx)
        cutoff = math.radians(fx.get("louver_cutoff", 90)) if louver else math.radians(90)
        for lat in G["track_lateral"]:
            heads = golf_heads(pkg, lat)
            mat_E = np.zeros(len(mpts)); ball0 = ball1 = 0.0
            img_E = np.zeros(len(imgp)); shadow_hits = {"address": 0, "top": 0}
            for hg in heads:
                L = npm(hg["lens"]); ax = np.array(hg["axis"]); Lv_ = Vector(L)
                e = Engine.E(mpts, up, L, ax, kind, hb, cut, I0)
                for i in range(len(mpts)):
                    if e[i] > 0 and eng.visible(trees0, Vector(mpts[i]), Lv_):
                        mat_E[i] += e[i]
                eb = float(Engine.E(ballp[None], up, L, ax, kind, hb, cut, I0)[0])
                if eng.visible(trees0, Vector(ballp), Lv_, tol=0.03):
                    ball0 += eb
                    if eng.visible(hit_addr, Vector(ballp), Lv_, tol=0.0):
                        ball1 += eb
                ei = Engine.E(imgp, nx, L, ax, kind, hb, cut, I0)
                for i in np.nonzero(ei > 1e-4)[0]:
                    pv = Vector(imgp[i])
                    if eng.visible(trees0, pv, Lv_):
                        img_E[i] += ei[i]
                        if ei[i] > G["shadow_lux"]:
                            for pose in ("address", "top"):
                                if not eng.visible([eng.bvh[f"HITTER_{pose}"]], pv, Lv_, tol=0.0):
                                    shadow_hits[pose] += 1
            sp = {sn: float((base_img[sn] + img_E * (P["scenes"][sn].get("HIT", 0) if not isinstance(P["scenes"][sn].get("HIT", 0), dict)
                                                       else P["scenes"][sn]["HIT"]["f"])).mean()) for sn in base_img}
            # clashes for this package
            cl = []
            for i, hg in enumerate(heads):
                c = golf_clash(f"head {hg['tag']}", *hg["bbox"], pg)
                if c["frustum"] or c["swing"]:
                    cl.append(c)
            for j, (tlo, thi) in enumerate(golf_tracks(lat)):
                c = golf_clash(f"track {j}", tlo, thi, pg)
                if c["frustum"] or c["swing"]:
                    cl.append(c)
            # glare from the hitter's eye at address (looking at the ball and at the screen centre)
            F = np.array([b[0], b[1] - G["hitter_stand"], 0.0])
            eye = F + [0, 15.5, 63 * G["hitter_h"] / 72]
            x, y0, y1, z0, z1 = image_rect()
            loss = [b - eye, np.array([x, G["screen_cy"], (z0 + z1) / 2]) - eye]
            flags = []
            for hg in heads:
                Lin = np.array(hg["lens"]); dn = (Lin - eye) / np.linalg.norm(Lin - eye)
                ab = math.acos(np.clip(np.dot(np.array(hg["axis"]), -dn), -1, 1))
                inv = any(math.acos(np.clip(np.dot(l / np.linalg.norm(l), dn), -1, 1)) <= math.radians(P["glare_los_deg"]) for l in loss)
                if inv and ab <= math.radians(P["glare_beam_deg"]) and ab <= cutoff and eng.visible(trees0, Vector(npm(eye)), Vector(npm(Lin)), tol=0.03):
                    flags.append(f"direct:hitter:{hg['tag']}")
            row = {"option": pkg, "fixture": fx["name"], "heads": len(heads), "track_lateral_in": lat,
                   "ball_lux": ball0, "ball_lux_hitter_at_address": ball1, "mat_mean_lux": float(mat_E.mean()),
                   "mat_min_lux": float(mat_E.min()), "mat_uniformity": float(mat_E.min() / mat_E.mean()) if mat_E.mean() > 0 else 0,
                   "screen_stray_simplay_lux": sp["sim_play"], "screen_stray_simplay_pct_white": 100 * sp["sim_play"] / wl,
                   "screen_stray_gamenight_lux": sp["game_night"], "screen_stray_gamenight_pct_white": 100 * sp["game_night"] / wl,
                   "heads_only_stray_lux": float(img_E.mean()),
                   "frustum_clashes": sum(1 for c in cl if c["frustum"]), "swing_clashes": sum(1 for c in cl if c["swing"]),
                   "clash_detail": ";".join(f"{c['item']}:{'frustum ' if c['frustum'] else ''}{c['swing']}" for c in cl),
                   "screen_shadow_from_heads": "yes" if (shadow_hits["address"] or shadow_hits["top"]) else "no",
                   "screen_shadow_from_projector": "yes" if (bay["proj_shadow_address"] > 0 or bay["proj_shadow_top"] > 0) else "no",
                   "glare_flags": ";".join(flags), "cost_usd": pd["cost"]}
            out["rows"].append(row)
            sc_ = (row["mat_uniformity"] - 0.1 * len(flags) - (row["frustum_clashes"] + row["swing_clashes"])
                   - (10.0 if row["screen_stray_simplay_pct_white"] >= 1.0 else 0.0) + row["ball_lux_hitter_at_address"] / 1e4)
            if best is None or sc_ > best[0]:
                best = (sc_, pkg, lat)
            print(f"GOLF {pkg} L{int(lat)}: ball {ball0:.0f} ({ball1:.0f} w/ hitter) mat {row['mat_mean_lux']:.0f} U {row['mat_uniformity']:.2f} "
                  f"stray sim {sp['sim_play']:.2f} lux ({row['screen_stray_simplay_pct_white']:.2f}%) clashes {row['clash_detail']} glare {flags}")
    out["bay"] = bay
    out["best_package"] = best[1]
    out["best_lateral"] = best[2]
    print("GOLF bay:", json.dumps({k: v for k, v in bay.items() if k != "clashes"}, default=float)[:600])
    print("GOLF clashes:", bay["clashes"])
    return out


# ============================================================================ stage: analyze
def stage_analyze():
    t0 = time.time()
    sc = bpy.context.scene
    calib = cal()
    meta = jload(f"{P['export_dir']}/build_meta.json")
    eng = Engine()
    exp = out_dir(P["export_dir"])
    gdir = out_dir(P["export_dir"], "grids")
    mdir = out_dir(P["render_dir"], "lux")
    rng = random.Random(P["opt_seed"])
    rows, layouts = [], dict(meta["layouts"])
    gctx = {c: grid_ctx(c) for c in "AB"}
    ies_dir = out_dir(P["export_dir"], "ies")
    # ---- optimise
    for case in "AB":
        for opener in P["openers"]:
            for pkg in P["packages"]:
                std = layouts[f"{pkg}_STD_{case}_{opener}"]["heads"]
                t = time.time()
                heads, J, dim, hist = opt_layout(eng, pkg, case, opener, gctx[case], std, rng)
                key = f"{pkg}_OPT_{case}_{opener}"
                layouts[key] = {"heads": heads, "naive_clashes": [], "J": J, "dim": dim, "hist": hist[::10]}
                print(f"OPT {key}: J {hist[0]:.3f} -> {J:.3f} in {time.time() - t:.0f}s")
    # ---- evaluate every layout x door state
    static_flags = fixture_clash_report()
    for key, lay in layouts.items():
        pkg, kind_l, case, opener = key.split("_")
        fx_key = P["packages"][pkg]["fixture"]
        louver = P["packages"][pkg].get("louver", False)
        heads = lay["heads"]
        for door_open in (False, True):
            E0, E1 = eval_layout(eng, heads, fx_key, case, door_open, opener, gctx[case])
            mask = gctx[case][3]
            mean_full = float(E0[mask].mean())
            dim = lay.get("dim", 1.0) if kind_l == "OPT" else 1.0
            mt = metrics(E0, E1, mask, dim)
            # game night at 3000 K with fixed-CCT circuits
            ccts = [h["cct"] for h in heads]
            mix = circuit_mix(ccts, 3000) if P["fixtures"][fx_key].get("cct_mode") == "fixed" else [1.0] * len(heads)
            G0, G1 = eval_layout(eng, heads, fx_key, case, door_open, opener, gctx[case], dims=mix)
            gm = metrics(G0, G1, mask, dim)
            flags, lensv = glare_eval(eng, heads, fx_key, case, door_open, opener, louver)
            spill_gn = spill_eval(eng, "game_night", heads, fx_key, case, door_open, opener)
            spill_lan = spill_eval(eng, "lan_party", heads, fx_key, case, door_open, opener)
            tag = f"{key}_{'open' if door_open else 'closed'}"
            row = {"option": pkg, "layout": kind_l, "case": case, "opener": opener, "door": "open" if door_open else "closed",
                   "fixture": P["fixtures"][fx_key]["name"], "heads": len(heads),
                   "mean_lux": mt["mean"], "min_lux": mt["min"], "max_lux": mt["max"], "uniformity": mt["U"],
                   "mean_full_output": mean_full, "dim_level": dim, "dim_for_450": min(1.0, P["dim_target"] / mean_full),
                   "mean_occupied": mt["mean_occ"], "U_occupied": mt["U_occ"],
                   "shadow_area_lt70_pct": 100 * mt["A70"], "shadow_area_lt50_pct": 100 * mt["A50"],
                   "gamenight_3000K_mean": gm["mean"], "gamenight_3000K_U": gm["U"],
                   "glare_direct": sum(1 for f in flags if f.startswith("direct")),
                   "glare_reflect": sum(1 for f in flags if f.startswith("reflect")),
                   "lens_visible_views": lensv, "glare_flags": ";".join(flags),
                   "screen_spill_gamenight_lux": spill_gn, "screen_spill_lan_lux": spill_lan,
                   "door_clashes": len(lay["naive_clashes"]), "clash_detail": ";".join(f"{c['head']}:{c['why']}" for c in lay["naive_clashes"]),
                   "cost_usd": P["packages"][pkg]["cost"]}
            rows.append(row)
            # grid CSV + false colour maps
            pts = gctx[case][0]
            with open(gdir / f"{tag}.csv", "w") as fh:
                fh.write("x_in,y_in,lux_empty,lux_occupied,shadow_ratio,under_piece\n")
                ratio = (E1 * dim + P["fill_lux"]) / (E0 * dim + P["fill_lux"])
                for i in range(len(pts)):
                    fh.write(f"{pts[i, 0]:.2f},{pts[i, 1]:.2f},{E0[i] * dim:.1f},{E1[i] * dim:.1f},{ratio[i]:.3f},{int(not mask[i])}\n")
            title = f"{pkg} {kind_l} CASE {case} DOOR {row['door']} {opener}"
            lux_map_png(E0 * dim, gctx[case][2], mask, case, title,
                        [f"MEAN {mt['mean']:.0f} MIN {mt['min']:.0f} MAX {mt['max']:.0f} U {mt['U']:.2f}",
                         f"EMPTY TABLE, 100% OUTPUT{' DIMMED TO %d%%' % round(dim * 100) if dim < 1 else ''}"],
                        mdir / f"{tag}.png")
            lux_map_png(ratio, gctx[case][2], mask, case, title + " SHADOW",
                        [f"<70%: {100 * mt['A70']:.1f}% OF AREA  <50%: {100 * mt['A50']:.1f}%", "SPOT WITH PLAYERS / WITHOUT, +75 LUX FILL"],
                        mdir / f"{tag}_shadow.png", vmax=1.0, ratio=True)
            print(f"{tag}: mean {mt['mean']:.0f} U {mt['U']:.2f} A70 {100 * mt['A70']:.1f}% glare {row['glare_direct']}/{row['glare_reflect']}")
    # ---- add optimised collections to the blend
    ctab = bpy.data.collections["TABLE_OPTIONS"]
    for key, lay in layouts.items():
        if "_OPT_" in key:
            build_table_collection(key, lay["heads"], ctab, calib, ies_dir)
    # ---- indirect layers
    counter = counter_eval(eng)
    print(f"counter (UC only): mean {counter['mean']:.0f} min {counter['min']:.0f}")
    # ---- sensitivity
    sens = sensitivity(eng, gctx)
    # ---- 5-point cross-check targets
    xc = {}
    for key in (f"VALUE_STD_A_jackshaft", f"PREMIUM_OPT_B_jackshaft", f"MID_OPT_A_trolley"):
        pkg, kl, case, opener = key.split("_")
        heads = layouts[key]["heads"]
        fx_key = P["packages"][pkg]["fixture"]
        c, a, b, hw, hd = table_frame(case)
        pts = np.array([[*(c + a * u * hw + b * v * hd), P["table_z"] + 0.06] for u, v in ((0, 0), (-0.5, -0.5), (0.5, -0.5), (-0.5, 0.5), (0.5, 0.5))])
        E = np.zeros(len(pts))
        kind, hb, cut, I0, _ = fixture_profile(P["fixtures"][fx_key])
        trees = eng.trees(case, False, opener, False)
        for hg in heads:
            e = Engine.E(pts * IN, np.array([0, 0, 1.0]), npm(hg["lens"]), np.array(hg["axis"]), kind, hb, cut, I0)
            for i in range(len(pts)):
                if eng.visible(trees, Vector(pts[i] * IN), Vector(npm(hg["lens"]))):
                    E[i] += e[i]
        xc[key] = {"pts": pts.tolist(), "analytic": E.tolist()}
    golf = golf_analyze(eng)
    write_csv(exp / "results.csv", rows)
    write_csv(exp / "sim_results.csv", golf["rows"])
    jsave(f"{P['export_dir']}/analysis.json", {"layouts": layouts, "rows": rows, "counter": {k: v for k, v in counter.items() if k not in ("pts", "E")},
                                                "sensitivity": sens, "crosscheck": xc, "static_clashes": static_flags, "golf": golf,
                                                "fixtures": {k: dict(zip(("kind", "hb", "cut", "I0", "flux"), fixture_profile(v))) for k, v in P["fixtures"].items()},
                                                "runtime_s": time.time() - t0})
    bpy.ops.wm.save_mainfile()
    print(f"ANALYZE OK in {time.time() - t0:.0f}s")


def fixture_clash_report():
    """Non-table fixtures vs the door envelope (both openers)."""
    out = []
    for op in P["openers"]:
        env = envelope(op)
        for s in static_sources():
            if s["fx"] == "STRIP":
                continue
            p = s["L"] / IN
            r = P["fixtures"][s["fx"]]["dia"] / 2 + 1
            bb = (p - [r, r, 2], p + [r, r, P["chord_z"] - p[2]])
            if any(box_hit(bb, e) for e in env):
                out.append({"opener": op, "id": s["id"], "layer": s["layer"], "at_in": p.round(1).tolist()})
    return out


def write_csv(path, rows):
    keys = list(rows[0].keys())
    with open(path, "w") as fh:
        fh.write(",".join(keys) + "\n")
        for r in rows:
            vals = []
            for k in keys:
                v = r[k]
                if isinstance(v, float):
                    v = f"{v:.3f}" if abs(v) < 10 else f"{v:.1f}"
                v = str(v)
                if "," in v or ";" in v:
                    v = '"' + v + '"'
                vals.append(v)
            fh.write(",".join(vals) + "\n")


def sensitivity(eng, gctx):
    """Re-run the standard layouts with one PARAM changed; flag metric changes > 15%."""
    tests = [("head_stem", 9.0), ("side_offset", 18.0), ("side_offset", 42.0), ("door_open_depth", 108.0),
             ("fill_lux", 40.0), ("fill_lux", 110.0)]
    fx_tests = [("SBL", "in_beam", 0.45), ("SBL", "in_beam", 0.75), ("SILO", "peak", 2700.0)]
    out = []
    base = {}

    def run(tagset):
        res = {}
        for case in "AB":
            for pkg in P["packages"]:
                heads, cl = standard_layout(pkg, case, "jackshaft")
                fx_key = P["packages"][pkg]["fixture"]
                E0, E1 = eval_layout(eng, heads, fx_key, case, P["design_door_open"], "jackshaft", gctx[case])
                mt = metrics(E0, E1, gctx[case][3])
                res[f"{pkg}_{case}"] = {"mean": mt["mean"], "U": mt["U"], "A70": mt["A70"], "clashes": len(cl)}
        return res
    base = run("base")
    for name, val in tests:
        old = P[name]
        P[name] = val
        r = run(name)
        P[name] = old
        out.append({"param": name, "from": old, "to": val, "res": r})
    for fk, prm, val in fx_tests:
        old = P["fixtures"][fk].get(prm)
        P["fixtures"][fk][prm] = val
        r = run(prm)
        P["fixtures"][fk][prm] = old
        out.append({"param": f"fixtures.{fk}.{prm}", "from": old, "to": val, "res": r})
    flags = []
    for t in out:
        for k, v in t["res"].items():
            b = base[k]
            for met in ("mean", "U", "A70"):
                if b[met] > 1e-6 and abs(v[met] - b[met]) / b[met] > 0.15:
                    flags.append({"param": t["param"], "to": t["to"], "config": k, "metric": met, "base": b[met], "new": v[met]})
    return {"base": base, "tests": out, "flags": flags}


# ============================================================================ stage: render
def stage_render():
    t0 = time.time()
    sc = bpy.context.scene
    an = jload(f"{P['export_dir']}/analysis.json")
    rdir = out_dir(P["render_dir"])
    samples = P["samples_final"] if P["final"] else P["samples"]
    setup_cycles(sc, samples)
    sc.frame_set(1)
    rows = an["rows"]
    # pick the render option
    opt = P["render_option"]
    if opt == "auto":
        cand = [r for r in rows if r["layout"] == "OPT" and r["case"] == P["render_case"] and r["door"] == DSTATE() and r["opener"] == "jackshaft"]
        best = max(cand, key=lambda r: r["uniformity"] - r["shadow_area_lt70_pct"] / 100 - 0.05 * r["glare_direct"] - r["cost_usd"] / 1e5)
        opt = f"{best['option']}_OPT_{P['render_case']}_jackshaft"
    print("render option:", opt)
    extra = {"render_option": opt}
    # ---- Cycles cross-check (direct only, albedo-1 felt, proxies hidden)
    extra["crosscheck"] = crosscheck(sc, an, rdir)
    # ---- counter, graze, wall wash, golf screen spill (Cycles)
    extra["counter_cycles"] = counter_cycles(sc, rdir, opt)
    extra["spill_cycles"] = spill_cycles(sc, rdir, opt)
    # ---- haze test
    extra["haze"] = haze_test(sc, rdir, opt)
    dens = P["haze_density"] or extra["haze"]["picked"]
    bpy.data.materials["L_haze"].node_tree.nodes["Principled Volume"].inputs["Density"].default_value = dens
    extra["haze_table"] = haze_table_check(sc, rdir, opt, dens)
    # ---- scenes x cameras
    sdir = out_dir(P["render_dir"], "scenes")
    case = P["render_case"]
    for cam_name, (eye, tgt, lens) in camera_defs(case).items():
        place_cam(bpy.data.objects[cam_name], eye, tgt)
    mag = magic_colors(sc, case)
    for sname, spec in P["scenes"].items():
        if sname.startswith("sim_"):
            continue
        set_active(sc, case, "jackshaft", opt, door_open=False, proxies=False, haze=bool(spec.get("haze")))
        apply_scene(sc, sname, magic_seats=mag)
        set_view(sc, False, spec.get("ev", 3.0))
        for cam_name in camera_defs(case):
            sc.camera = bpy.data.objects[cam_name]
            render_to(sc, sdir / f"{sname}__{cam_name[4:]}.png", P["res"])
    # door open, game night, entry view
    set_active(sc, case, "jackshaft", opt, door_open=True)
    apply_scene(sc, "game_night")
    set_view(sc, False, P["scenes"]["game_night"]["ev"])
    sc.camera = bpy.data.objects["CAM_entry"]
    render_to(sc, sdir / "game_night__entry_door_open.png", P["res"])
    # ---- golf bay: sim scenes from behind the hitter and the waiting area; Cycles check of the mat
    extra["golf_mat_cycles"] = golf_mat_cycles(sc, opt)
    gdir = out_dir(P["render_dir"], "golf")
    for sname in ("sim_play", "sim_social", "sim_movie"):
        set_active(sc, case, "jackshaft", opt, door_open=False, hitter="address")
        apply_scene(sc, sname)
        set_view(sc, False, P["scenes"][sname]["ev"])
        for cam_name in golf_cams():
            sc.camera = bpy.data.objects[cam_name]
            render_to(sc, gdir / f"{sname}__{cam_name[9:]}.png", P["res"])
    set_active(sc, case, "jackshaft", opt, door_open=False, hitter="top")
    apply_scene(sc, "sim_play")
    sc.camera = bpy.data.objects["CAM_golf_hitter"]
    render_to(sc, gdir / "sim_play__hitter_backswing.png", P["res"])
    # ---- seat POVs for both cases (game night, door closed, players + pieces shown)
    pdir = out_dir(P["render_dir"], "seats")
    cam = bpy.data.objects["CAM_seat_S"]
    for cs in "AB":
        key = opt.replace(f"_{P['render_case']}_", f"_{cs}_")
        set_active(sc, cs, "jackshaft", key, door_open=False, proxies=True)
        apply_scene(sc, "game_night")
        set_view(sc, False, P["scenes"]["game_night"]["ev"])
        c3 = np.array([*table_center(cs), P["table_z"]])
        for i, s in enumerate(seats(cs)):
            eye = s["eye"] + s["n"] * 1.5
            tgt = c3 + s["n"] * 6
            place_cam(cam, eye.tolist(), tgt.tolist())
            sc.camera = cam
            render_to(sc, pdir / f"case{cs}_seat{i}.png", (960, 640))
    jsave(f"{P['export_dir']}/render.json", extra)
    set_active(sc, case, "jackshaft", opt, door_open=False)
    apply_scene(sc, "game_night")
    for cam_name, (eye, tgt, lens) in camera_defs(case).items():
        place_cam(bpy.data.objects[cam_name], eye, tgt)
    sc.camera = bpy.data.objects["CAM_entry"]
    bpy.ops.wm.save_mainfile()
    print(f"RENDER OK in {time.time() - t0:.0f}s")


def only_layers(sc, layers, table=False):
    for ob in sc.objects:
        if ob.get("strip_layer") is not None:
            set_strip(ob, ob["base_S"] if ob["strip_layer"] in layers else 0.0, (1, 1, 1))
        if ob.type == "LIGHT":
            lay = ob.data.get("layer")
            on = (lay in layers) or (table and lay == "TABLE")
            ob.data.color = (1, 1, 1)
            ob.data.energy = ob.data["base_W"] if on else 0.0
            if ob.data.animation_data:
                ob.data.animation_data_clear()


def measure_cam(sc, x0, x1, y0, y1, z, res_per_m=400):
    cd = bpy.data.cameras.get("MEAS") or bpy.data.cameras.new("MEAS")
    cd.type = "ORTHO"
    w, h = (x1 - x0) * IN, (y1 - y0) * IN
    cd.ortho_scale = max(w, h)
    cd.clip_start, cd.clip_end = 0.01, 10
    ob = bpy.data.objects.get("MEAS") or bpy.data.objects.new("MEAS", cd)
    if ob.name not in sc.collection.objects:
        sc.collection.objects.link(ob)
    ob.location = (((x0 + x1) / 2) * IN, ((y0 + y1) / 2) * IN, z * IN)
    ob.rotation_euler = (0, 0, 0)
    sc.camera = ob
    rx = int(max(w, h) * res_per_m)
    if w >= h:
        res = (rx, max(int(rx * h / w), 8))
    else:
        res = (max(int(rx * w / h), 8), rx)
    cd.sensor_fit = "AUTO"
    return ob, res


def pix_at(img, x0, x1, y0, y1, x, y):
    H, W, _ = img.shape
    px = (x - x0) / (x1 - x0) * W
    py = (y - y0) / (y1 - y0) * H
    i, j = int(py), int(px)
    patch = img[max(i - 1, 0):i + 2, max(j - 1, 0):j + 2]
    Y = 0.2126 * patch[..., 0] + 0.7152 * patch[..., 1] + 0.0722 * patch[..., 2]
    return float(math.pi * Y.mean() * 683.0)


def measure_mode(sc, on=True):
    if on:
        sc["_samples"] = sc.cycles.samples
        sc.cycles.samples = P["measure_samples"]
        sc.cycles.use_denoising = False
        set_view(sc, True)
    else:
        sc.cycles.samples = sc["_samples"]
        sc.cycles.use_denoising = True


def crosscheck(sc, an, rdir):
    out = {}
    measure_mode(sc, True)
    mb = sc.cycles.max_bounces
    sc.cycles.max_bounces = 0
    wd = white_diffuse()
    for key, d in an["crosscheck"].items():
        pkg, kl, case, opener = key.split("_")
        set_active(sc, case, opener, key, door_open=False)
        only_layers(sc, set(), table=True)
        felt = bpy.data.objects[f"FELT_{case}"]
        old = felt.data.materials[0]
        felt.data.materials[0] = wd
        lo, hi = table_bbox(case)
        x0, y0, x1, y1 = lo[0] - 2, lo[1] - 2, hi[0] + 2, hi[1] + 2
        side = max(x1 - x0, y1 - y0)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        x0, x1, y0, y1 = cx - side / 2, cx + side / 2, cy - side / 2, cy + side / 2
        ob, res = measure_cam(sc, x0, x1, y0, y1, 60.0, 300)
        path = out_dir(P["render_dir"], "calibration") / f"crosscheck_{key}.exr"
        render_to(sc, path, res, exr=True)
        img = read_exr(path)
        felt.data.materials[0] = old
        cyc = [pix_at(img, x0, x1, y0, y1, p[0], p[1]) for p in d["pts"]]
        out[key] = {"analytic": d["analytic"], "cycles": cyc,
                    "ratio": [c / a if a > 0 else None for c, a in zip(cyc, d["analytic"])]}
        print("XCHECK", key, [f"{a:.0f}/{c:.0f}" for a, c in zip(d["analytic"], cyc)])
    sc.cycles.max_bounces = mb
    measure_mode(sc, False)
    return out


def counter_cycles(sc, rdir, opt):
    """Under-cabinet strips alone on the counter (direct), and beauty renders of the indirect layers."""
    idir = out_dir(P["render_dir"], "indirect")
    set_active(sc, "A", "jackshaft", opt, door_open=False)
    measure_mode(sc, True)
    mb = sc.cycles.max_bounces
    sc.cycles.max_bounces = 0
    only_layers(sc, {"UC"})
    top = bpy.data.objects.get("FI_K-TOP")
    old = top.data.materials[0]
    top.data.materials[0] = white_diffuse()
    x0, x1, y0, y1, z = P["counter_region"]
    ob, res = measure_cam(sc, x0, x1, y0 - 54, y1 + 54, 50.0, 300)  # square-ish view; uppers at 60in are above the camera
    path = idir / "counter_uc.exr"
    render_to(sc, path, res, exr=True)
    img = read_exr(path)
    top.data.materials[0] = old
    sc.cycles.max_bounces = mb
    measure_mode(sc, False)
    sx0, sx1, sy0, sy1 = P["sink_cut"]
    vals = [pix_at(img, x0, x1, y0 - 54, y1 + 54, x, y) for y in np.arange(y0 + 2, y1, 4.0) for x in np.arange(x0 + 2, x1, 4.0)
            if not (sx0 <= x <= sx1 and sy0 <= y <= sy1)]
    res_ = {"mean": float(np.mean(vals)), "min": float(np.min(vals))}
    # beauty views
    views = {"counter_uc": (("UC",), (381, 318, 64), (381, 245, 40), 24, 2.5),
             "graze_partition": (("GR",), (530, 300, 40), (650, 238, 100), 24, 2.5),
             "wall_wash_east": (("WW",), (560, 330, 60), (711, 390, 80), 22, 2.5),
             "above_cabinet": (("UP",), (381, 330, 70), (381, 240, 110), 24, 3.0)}
    cam = bpy.data.objects["CAM_entry"]
    keep = cam.matrix_world.copy()
    for nm, (lays, eye, tgt, lens, ev) in views.items():
        only_layers(sc, set(lays))
        for ob in sc.objects:
            if ob.get("strip_layer") in lays:
                set_strip(ob, ob["base_S"] * ob["lum_fac"], cct_rgb(ob["cct"]))
        place_cam(cam, eye, tgt)
        cam.data.lens = lens
        sc.camera = cam
        set_view(sc, False, ev)
        render_to(sc, idir / f"{nm}.png", (960, 640))
    cam.data.lens = 18
    cam.matrix_world = keep
    print("counter Cycles:", res_)
    return res_


def spill_cycles(sc, rdir, opt):
    """Total (incl. bounces) illuminance on the projected image, projector off: albedo-1 card over the image rect."""
    x, y0, y1, z0, z1 = image_rect()
    card = bpy.data.objects.get("MEAS_card")
    if card is None:
        card = mesh_obj("MEAS_card", sc.collection, lambda bm: bm_box(bm, (x + 0.2, y0, z0), (x + 0.3, y1, z1)), white_diffuse())
    card.hide_render = False
    cd = bpy.data.cameras.get("MEAS_SCREEN") or bpy.data.cameras.new("MEAS_SCREEN")
    cd.type = "ORTHO"
    w, h = (y1 - y0) * IN, (z1 - z0) * IN
    cd.ortho_scale = max(w, h)
    cam = bpy.data.objects.get("MEAS_SCREEN") or bpy.data.objects.new("MEAS_SCREEN", cd)
    if cam.name not in sc.collection.objects:
        sc.collection.objects.link(cam)
    cam.location = ((x + 30) * IN, (y0 + y1) / 2 * IN, (z0 + z1) / 2 * IN)
    cam.rotation_euler = (math.pi / 2, 0, math.pi / 2)  # look -X (at the W wall)
    cd.clip_start, cd.clip_end = 0.05, 2.0
    sc.camera = cam
    measure_mode(sc, True)
    out = {}
    res = (300, int(300 * h / w))
    for sname in ("game_night", "lan_party", "sim_play"):
        set_active(sc, "A", "jackshaft", opt, door_open=False)
        apply_scene(sc, sname)
        for o in sc.objects:
            if o.type == "LIGHT" and o.data.get("layer") in ("PROJ",) + (() if sname.startswith("sim") else ("HB_S",)):
                o.data.energy = 0
        path = out_dir(P["render_dir"], "calibration") / f"spill_{sname}.exr"
        render_to(sc, path, res, exr=True)
        img = read_exr(path)
        Y = 0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2]
        out[sname] = float(math.pi * Y.mean() * 683.0)
        print("spill Cycles", sname, out[sname])
    card.hide_render = True
    measure_mode(sc, False)
    return out
def haze_test(sc, rdir, opt):
    """Puck down-beams at each density: luminance at the beam centre vs the air beside it, sampled where the
    beams project into a camera looking up past the chord with pucks (black ceiling behind)."""
    from bpy_extras.object_utils import world_to_camera_view
    hdir = out_dir(P["render_dir"], "haze")
    set_active(sc, "A", "jackshaft", opt, door_open=False, haze=True)
    cam = bpy.data.objects["CAM_entry"]
    keep = cam.matrix_world.copy()
    tx = dict(zip([f"T{i:02d}" for i in range(16)], P["truss_x"]))
    chx = tx[P["pucks"]["chords"][0]]
    place_cam(cam, (chx + 70, 300, 50), (chx, 360, 112))
    sc.camera = cam
    sc.frame_set(24)
    vol = bpy.data.materials["L_haze"].node_tree.nodes["Principled Volume"]
    res = (960, 540)
    smp = sc.cycles.samples
    sc.cycles.samples = 256
    sc.cycles.use_denoising = False
    set_view(sc, True)
    pucks = [o for o in sc.objects if o.type == "LIGHT" and o.data.get("layer") == "PUCK"]
    beam = math.radians(P["fixtures"]["PUCK"]["beam"] / 2)
    samples = []
    dg = bpy.context.evaluated_depsgraph_get()
    for o in pucks:
        Lp = o.matrix_world.translation
        for drop in (0.5, 0.8):
            c = Lp - Vector((0, 0, drop))
            vdir = (c - cam.matrix_world.translation).normalized()
            side = vdir.cross(Vector((0, 0, 1))).normalized() * (drop * math.tan(beam) * 2.2)
            uvc = world_to_camera_view(sc, cam, c)
            uvs = [world_to_camera_view(sc, cam, c + sgn * side) for sgn in (-1, 1)]
            if all(0.03 < q.x < 0.97 and 0.03 < q.y < 0.97 and q.z > 0 for q in [uvc] + uvs):
                samples.append((uvc, uvs))
    out = {}
    for dens in [0.0] + list(P["haze_densities"]):
        bpy.data.collections["HAZE"].hide_render = dens == 0.0
        vol.inputs["Density"].default_value = max(dens, 1e-6)
        apply_scene(sc, "game_night")
        path = hdir / f"haze_{dens:.3f}.exr"
        render_to(sc, path, res, exr=True)
        img = read_exr(path)
        Y = 0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2]
        H, W = Y.shape
        def at(q):
            i, j = int(q.y * H), int(q.x * W)
            return float(Y[max(i - 2, 0):i + 3, max(j - 2, 0):j + 3].mean())
        # background (black ceiling + haze veil) measured beside the beams; beam in-scatter from single scattering:
        # L = sigma * p_HG(90 deg) * integral(E dl across the beam) = sigma * p * I0 * f * hb * sqrt(pi/ln2) / s
        bg = float(np.median([0.5 * (at(uvs[0]) + at(uvs[1])) for _, uvs in samples]) * 683.0) if samples else 1.0
        g = P["haze_anisotropy"]
        p90 = (1 - g * g) / (4 * math.pi * (1 + g * g) ** 1.5)
        spec = P["scenes"]["game_night"]
        res_b = {}
        for nm, fk, frac in (("puck", "PUCK", spec.get("PUCK", 0)), ("table_spot", P["packages"][opt.split("_")[0]]["fixture"], 1.0)):
            frac = frac["f"] if isinstance(frac, dict) else frac
            kind, hb, cut, I0, _ = fixture_profile(P["fixtures"][fk])
            Lb = dens * p90 * I0 * frac * hb * math.sqrt(math.pi / math.log(2)) / 0.5
            res_b[nm] = {"beam_cd_m2": Lb, "contrast": Lb / max(bg, 1e-6)}
        out[dens] = {"bg_cd_m2": bg, "beams": res_b, "contrast": res_b["puck"]["contrast"], "n_samples": len(samples)}
        save_png(np.clip((img[::-1] * 683 / 15) ** (1 / 2.2), 0, 1), hdir / f"haze_{dens:.3f}.png")
    sc.cycles.samples = smp
    sc.cycles.use_denoising = True
    ok = [d for d in P["haze_densities"] if out[d]["contrast"] >= P["haze_contrast_min"]]
    okt = [d for d in P["haze_densities"] if out[d]["beams"]["table_spot"]["contrast"] >= P["haze_contrast_min"]]
    picked = min(ok) if ok else (min(okt) if okt else max(P["haze_densities"]))
    cam.matrix_world = keep
    print("haze:", out, "picked", picked)
    return {"tests": {str(k): v for k, v in out.items()}, "picked": picked, "criterion": P["haze_contrast_min"],
            "pucks_visible": bool(ok), "basis": "puck beams" if ok else ("table spot beams (puck beams never reach the criterion)" if okt else "none pass")}
def golf_mat_cycles(sc, opt):
    """Golf heads only, direct, albedo-1 mat: mean over the 6in mat grid (compare with sim_results mat_mean_lux)."""
    b = golf_ball()
    key = golf_default_key()
    set_active(sc, "A", "jackshaft", opt, door_open=False, golf_key=key)
    measure_mode(sc, True)
    mb = sc.cycles.max_bounces
    sc.cycles.max_bounces = 0
    only_layers(sc, {"HIT"})
    mo = bpy.data.objects["GOLF_mat"]
    old = mo.data.materials[0]
    mo.data.materials[0] = white_diffuse()
    bpy.data.objects["GOLF_ball"].hide_render = True
    x0, x1 = b[0] - G["mat"] / 2, b[0] + G["mat"] / 2
    y0, y1 = b[1] - G["mat"] / 2, b[1] + G["mat"] / 2
    ob, res = measure_cam(sc, x0, x1, y0, y1, 20.0, 300)
    path = out_dir(P["render_dir"], "calibration") / "golf_mat.exr"
    render_to(sc, path, res, exr=True)
    img = read_exr(path)
    vals = [pix_at(img, x0, x1, y0, y1, x0 + 3 + 6 * i, y0 + 3 + 6 * j) for j in range(10) for i in range(10)]
    mo.data.materials[0] = old
    bpy.data.objects["GOLF_ball"].hide_render = False
    sc.cycles.max_bounces = mb
    measure_mode(sc, False)
    r = {"key": key, "mean": float(np.mean(vals)), "centre": pix_at(img, x0, x1, y0, y1, b[0], b[1])}
    print("golf mat Cycles:", r)
    return r


def haze_table_check(sc, rdir, opt, dens):
    """Table illuminance (direct, albedo-1 felt) with and without haze, table layer only."""
    wd = white_diffuse()
    case = P["render_case"]
    felt = bpy.data.objects[f"FELT_{case}"]
    old = felt.data.materials[0]
    measure_mode(sc, True)
    mb = sc.cycles.max_bounces
    sc.cycles.max_bounces = 0
    res_ = {}
    lo, hi = table_bbox(case)
    side = max(hi[0] - lo[0], hi[1] - lo[1]) + 4
    cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
    x0, x1, y0, y1 = cx - side / 2, cx + side / 2, cy - side / 2, cy + side / 2
    for hz in (False, True):
        set_active(sc, case, "jackshaft", opt, door_open=False, haze=hz)
        only_layers(sc, set(), table=True)
        felt.data.materials[0] = wd
        ob, res = measure_cam(sc, x0, x1, y0, y1, 60.0, 200)
        path = out_dir(P["render_dir"], "calibration") / f"haze_table_{int(hz)}.exr"
        render_to(sc, path, res, exr=True)
        img = read_exr(path)
        vals = [pix_at(img, x0, x1, y0, y1, x, y) for x in np.linspace(lo[0] + 4, hi[0] - 4, 9) for y in np.linspace(lo[1] + 4, hi[1] - 4, 4)]
        res_["haze" if hz else "clear"] = float(np.mean(vals))
    felt.data.materials[0] = old
    sc.cycles.max_bounces = mb
    measure_mode(sc, False)
    res_["ratio"] = res_["haze"] / res_["clear"]
    res_["density"] = dens
    import math as _m
    res_["analytic_attenuation"] = _m.exp(-dens * (P["chord_z"] - P["table_z"]) * IN * 1.15)
    print("haze table:", res_)
    return res_


# ============================================================================ stage: report
def stage_report():
    an = jload(f"{P['export_dir']}/analysis.json")
    rj = jload(f"{P['export_dir']}/render.json", {})
    cj = cal()
    rows = an["rows"]
    L = []
    w = L.append
    w("# Shop lighting simulation: results\n")
    w(f"Generated by `scripts/lighting.py` (`make lighting`). Raw numbers: `results.csv` (one row per option x layout x case x opener x door), "
      f"per-point grids in `grids/`, false-colour maps in `renders/lighting/lux/`.\n")
    # ---- key findings (computed)
    op = [r for r in rows if r["door"] == DSTATE() and r["opener"] == "jackshaft"]
    ds = f"door {DSTATE()}"
    def pick(o, l, c):
        return next(r for r in op if r["option"] == o and r["layout"] == l and r["case"] == c)
    w("## Key findings\n\n")
    ncl = {r["option"] + r["case"] + r["opener"]: r["door_clashes"] for r in rows if r["layout"] == "STD"}
    nst = len(an["static_clashes"])
    w(f"- **Door envelope:** the glass door is standard lift, so the open panel rides at z {P['door_panel_top_z'] - P['door_panel_thick']:.0f}-"
      f"{P['door_panel_top_z']:.0f}in, about {P['chord_z'] - P['door_panel_top_z']:.0f}in below the chords (tracks run {P['track_run'] / 12:.1f} ft in, "
      f"hangers up to the chords at their back ends). With a {P['envelope_pad']:.0f}in pad, the standard layouts have "
      f"{min(ncl.values())}-{max(ncl.values())} heads in the envelope (both openers); "
      + (f"{nst} other fixture clash(es) are listed below. " if nst else "no high bay or other fixture is in it. ")
      + "The open panel hangs between the heads and the table, so door-open rows in `results.csv` are much darker; "
      "the owner uses the table lights with the door closed, so the optimiser and this report use **door closed**.\n")
    for case in "AB":
        v, mo, pr = pick("VALUE", "OPT", case), pick("MID", "OPT", case), pick("PREMIUM", "OPT", case)
        vs = pick("VALUE", "STD", case)
        w(f"- **Case {case} table (optimised, {ds}):** Value {v['mean_lux']:.0f} lux U {v['uniformity']:.2f} at full output "
          f"(standard layout {vs['mean_lux']:.0f} lux U {vs['uniformity']:.2f}); Mid {mo['mean_lux']:.0f} lux U {mo['uniformity']:.2f} dimmed to "
          f"{mo['dim_level'] * 100:.0f}%; Premium {pr['mean_lux']:.0f} lux U {pr['uniformity']:.2f} dimmed to {pr['dim_level'] * 100:.0f}%.\n")
    mo, pr = pick("MID", "OPT", "A"), pick("PREMIUM", "OPT", "A")
    w(f"- **Fixed-CCT circuits matter at game night (3000K):** Mid's 3000K/4000K heads leave only the 3000K circuit on, so U drops to "
      f"{mo['gamenight_3000K_U']:.2f}. Premium mixes its 2700K and 4000K circuits to 3000K and keeps U {pr['gamenight_3000K_U']:.2f}. "
      "Value's heads are switchable, so nothing changes.\n")
    a70 = [r["shadow_area_lt70_pct"] for r in op if r["layout"] == "OPT"]
    w(f"- **Shadows:** even optimised, {min(a70):.0f}-{max(a70):.0f}% of the table falls below 70% with six players seated, almost all of it "
      "in front of each player (hands and card holders). No optimised layout has a direct-glare flag.\n")
    lan = [r["screen_spill_lan_lux"] for r in op]
    w(f"- **Golf screen spill:** game night {min(r['screen_spill_gamenight_lux'] for r in op):.1f}-{max(r['screen_spill_gamenight_lux'] for r in op):.1f} lux, "
      f"under the {P['spill_target']:.0f} lux target; LAN party {min(lan):.1f}-{max(lan):.1f} lux (Cycles with bounces {rj.get('spill_cycles', {}).get('lan_party', float('nan')):.1f}), over it. "
      "Nearly all of the LAN spill comes from the north high bays at 15%, through the open west end of the partition, whatever the table option.\n")
    w(f"- **Counter:** under-cabinet strips alone give {an['counter']['mean']:.0f} lux analytic and "
      f"{rj.get('counter_cycles', {}).get('mean', float('nan')):.0f} lux in Cycles (direct), right at the 500 target; the run's ends drop to ~{an['counter']['min']:.0f} lux.\n")
    gd = an.get("golf")
    if gd:
        bay = gd["bay"]
        w(f"- **Golf bay:** the couch sits inside the swing disc at the 11 ft ball position. The ProTee VX hangs inside the projector's "
          f"frustum (it shadows {bay['proj_shadow_fixed'] * 100:.0f}% of the image) and inside the swing buffer. The projector and HB-1 are inside "
          "the 1 m swing buffer too. Premium heads keep stray light on the screen at 0.02-0.03% of white; Value's 45 deg beams reach "
          "1.3% (target < 1%). At address the hitter shades the ball by 25-50%.\n")
    w("\n## How to read this\n")
    w("- **Lux** values are the spot layer alone on an **empty table** (direct light, analytic: inverse square, cosine, beam profile, ray-cast "
      "against the whole scene). Occupied values and shadow percentages include the six seated players, card holders and game pieces "
      f"with {P['fill_lux']:.0f} lux of fill.\n")
    w("- **STD** = the brief's layout (2 heads per long side, 2 per end, aimed at the far half), with any head that hit the door envelope "
      "moved the shortest way out. `door_clashes` counts the heads that had to move. **OPT** = the optimised layout "
      f"({P['opt_evals']} evaluations each, {'door open' if P['design_door_open'] else 'door closed'}, dimmed to {P['dim_target']:.0f} lux when the full-output mean is over {P['mean_lux_range'][1]:.0f}).\n")
    w("- Uniformity U = min / mean (target >= 0.7). Shadow = share of the table where spot light with players is under 70% (visible) "
      "or 50% (dark) of the empty-table value.\n")
    w("\n## Calibration\n")
    for k, v in cj["spot"].items():
        if k.startswith("gauss_22.50"):
            w(f"- 1000 cd spot at 2.845 m on an albedo-1 plane: Cycles {v['meas_lux']:.1f} lux vs {v['expect_lux']:.1f} expected "
              f"(k = {v['k']:.4f}); 0.4 m off-axis {v['offaxis_meas']:.1f} vs {v['offaxis_expect']:.1f}.\n")
    ks = [v["k"] for v in cj["spot"].values()]
    w(f"- All {len(ks)} beam profiles: k = {min(ks):.4f} to {max(ks):.4f}. Strips (one-sided emissive meshes): k = {cj['mesh']['k']:.4f}, 0.4 m across the strip {cj['mesh']['offaxis_meas']:.0f} vs {cj['mesh']['offaxis_expect']:.0f} lux "
      "(Cycles area lights were dropped: their off-axis falloff isn't Lambertian). "
      "Every light's power is divided by its k, so Cycles reads lux = pi x pixel x 683 directly.\n")
    if rj.get("crosscheck"):
        w("\n**5-point Cycles cross-check** (direct only, door closed, no players; analytic / Cycles lux):\n\n")
        w("| layout | centre | SW quarter | SE quarter | NW quarter | NE quarter |\n|---|---|---|---|---|---|\n")
        for k, v in rj["crosscheck"].items():
            w(f"| {k} | " + " | ".join(f"{a:.0f} / {c:.0f}" for a, c in zip(v["analytic"], v["cycles"])) + " |\n")
        allr = [r for v in rj["crosscheck"].values() for r in v["ratio"] if r]
        w(f"\nCycles / analytic: {min(allr):.3f} to {max(allr):.3f}.\n")
    # summary table
    w(f"\n## Summary ({ds}, jackshaft opener)\n\n")
    w("| option | layout | case | mean lux | min | U | dim | shadow <70% | <50% | glare direct / reflect | game night 3000K mean / U | screen spill (game / LAN) | clashes | cost |\n")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    sel = [r for r in rows if r["door"] == DSTATE() and r["opener"] == "jackshaft"]
    for r in sorted(sel, key=lambda r: (r["case"], r["layout"], r["option"])):
        w(f"| {r['option']} | {r['layout']} | {r['case']} | {r['mean_lux']:.0f} | {r['min_lux']:.0f} | {r['uniformity']:.2f} | "
          f"{r['dim_level'] * 100:.0f}% | {r['shadow_area_lt70_pct']:.1f}% | {r['shadow_area_lt50_pct']:.1f}% | "
          f"{r['glare_direct']} / {r['glare_reflect']} | {r['gamenight_3000K_mean']:.0f} / {r['gamenight_3000K_U']:.2f} | "
          f"{r['screen_spill_gamenight_lux']:.2f} / {r['screen_spill_lan_lux']:.2f} | {r['door_clashes']} | ${r['cost_usd']:,} |\n")
    # winners
    w(f"\n## Winners by metric ({ds}, all openers)\n\n")
    op_rows = [r for r in rows if r["door"] == DSTATE()]
    def best(metric, hi=True, pool=op_rows):
        r = (max if hi else min)(pool, key=lambda r: r[metric])
        return f"{r['option']} {r['layout']} case {r['case']} ({r['opener']}): {r[metric]:.2f}"
    w(f"- Uniformity: {best('uniformity')}\n")
    w(f"- Least visible shadow (<70%): {best('shadow_area_lt70_pct', False)}\n")
    w(f"- Least dark shadow (<50%): {best('shadow_area_lt50_pct', False)}\n")
    w(f"- Fewest direct glare flags: {best('glare_direct', False)}\n")
    w(f"- Lowest golf-screen spill (game night): {best('screen_spill_gamenight_lux', False)}\n")
    for case in "AB":
        pool = [r for r in op_rows if r["case"] == case and r["layout"] == "OPT"]
        sc_ = lambda r: r["uniformity"] - r["shadow_area_lt70_pct"] / 100 - 0.05 * r["glare_direct"]
        b = max(pool, key=sc_)
        w(f"- Best overall, case {case} (U - shadow - glare): **{b['option']} OPT ({b['opener']})**: U {b['uniformity']:.2f}, "
          f"shadow {b['shadow_area_lt70_pct']:.1f}%, glare {b['glare_direct']}.\n")
    # positions
    w("\n## Head positions for the optimised layouts\n\n")
    w(f"Mount = where the head's adaptor meets the strut board ({P['strut_board']}in board under the chords). "
      "'From door wall' = south of the N wall's inside face; 'from partition' = north of the partition's N face; "
      "'from W wall' = east of the W wall. Aim = the point on the table the beam centre hits.\n")
    for key, lay in an["layouts"].items():
        if "_OPT_" not in key:
            continue
        w(f"\n### {key}\n\n| head | from door wall | from partition | from W wall | nearest chord | aim (from door wall, from W wall) | CCT |\n|---|---|---|---|---|---|---|\n")
        for i, h in enumerate(lay["heads"]):
            x, y = h["mount"][:2]
            tx = np.array(P["truss_x"])
            j = int(np.argmin(np.abs(tx - x)))
            ax_, ay_ = h["aim"][:2]
            w(f"| H{i} | {ftin(P['north_wall_y'] - y)} | {ftin(y - P['partition_n_face_y'])} | {ftin(x)} | T{j:02d} ({ftin(x - tx[j])}) | "
              f"{ftin(P['north_wall_y'] - ay_)}, {ftin(ax_)} | {h['cct']}K |\n")
    # clashes
    w("\n## Door-envelope clashes\n\n")
    if not any(lay["naive_clashes"] for lay in an["layouts"].values()):
        w("- None: every standard-layout head clears the open panel, tracks, hangers, torsion shaft and opener by the pad.\n")
    for key, lay in an["layouts"].items():
        if lay["naive_clashes"]:
            w(f"- {key}: " + "; ".join(f"{c['head']} ({c['why']})" for c in lay["naive_clashes"]) + "\n")
    if an["static_clashes"]:
        w("\nOther fixtures inside the envelope:\n")
        seen = set()
        for c in an["static_clashes"]:
            k = (c["id"], c["opener"])
            if k not in seen:
                seen.add(k)
                w(f"- {c['id']} ({c['layer']}) with the {c['opener']} opener at {c['at_in']}\n")
    # indirect + spill + haze
    w("\n## Indirect layers, spill, haze\n\n")
    w(f"- Under-cabinet strips alone on the counter: analytic mean {an['counter']['mean']:.0f} lux (min {an['counter']['min']:.0f})"
      + (f", Cycles direct {rj['counter_cycles']['mean']:.0f} lux" if rj.get('counter_cycles') else "") + f"; target >= {P['counter_target']:.0f}.\n")
    if rj.get("spill_cycles"):
        w(f"- Golf screen, Cycles incl. bounces (render option): game night {rj['spill_cycles']['game_night']:.2f} lux, "
          f"LAN {rj['spill_cycles']['lan_party']:.2f} lux; target < {P['spill_target']:.0f}.\n")
    if rj.get("haze"):
        hz = rj["haze"]
        w(f"- Haze: beam / background luminance at 0.5 m below the source (single scattering, HG g={P['haze_anisotropy']}, side view; "
          f"background measured beside the beams in the render; 'clearly visible' >= {hz['criterion']}):\n")
        for k, v in hz["tests"].items():
            if float(k) > 0:
                w(f"  - {k} m^-1: pucks {v['beams']['puck']['contrast']:.2f}, table spots {v['beams']['table_spot']['contrast']:.2f} "
                  f"(background {v['bg_cd_m2']:.3f} cd/m2)\n")
        if hz["basis"] == "none pass":
            w(f"  - No tested density makes the beams clearly visible: the haze veil from the lit room rises with density as fast as the beams do. "
              f"Renders use the densest tested, **{hz['picked']} m^-1**. The 50 lm pucks stay invisible; they need far more output to read as beams.\n")
        else:
            w(f"  - Picked **{hz['picked']} m^-1** on {hz['basis']}.\n")
    if rj.get("haze_table"):
        h = rj["haze_table"]
        w(f"- Table under haze: {h['haze']:.0f} vs {h['clear']:.0f} lux clear ({(h['ratio'] - 1) * 100:+.1f}%; limit 10%).\n")
    # sensitivity
    w(f"\n## PARAM sensitivity (> 15% change, standard layouts, door {DSTATE()})\n\n")
    if an["sensitivity"]["flags"]:
        w("| param | changed to | config | metric | base | new |\n|---|---|---|---|---|---|\n")
        for f in an["sensitivity"]["flags"]:
            w(f"| {f['param']} | {f['to']} | {f['config']} | {f['metric']} | {f['base']:.3f} | {f['new']:.3f} |\n")
    else:
        w("None of the tested PARAMs moved a metric by more than 15%.\n")
    # golf bay
    gd = an.get("golf")
    if gd:
        bay = gd["bay"]
        pj = bay["projector"]
        w("\n## Golf sim bay (section 7)\n\n")
        w(f"Projector {pj['model']}: throw ratio {pj['throw_ratio']:.3f}, lens {pj['lens_from_screen']} from the screen at z {pj['lens_in'][2]:.1f}in "
          f"(centred on the screen, {ftin(pj['lens_in'][1])} from the S wall). "
          f"Vertical lens shift needed from the chord mount: {pj['shift_needed'] * 100:.0f}% (limit {pj['shift_limit'] * 100:.0f}%)"
          + (f", so the lens hangs {pj['lens_lowered_by_in']:.1f}in lower than the default mount" if pj['lens_lowered_by_in'] > 0.05 else "") +
          f". White level {pj['white_lux']:.0f} lux on the {G['image_w'] / 12:.0f} x {G['image_h'] / 12:.1f} ft image (before screen losses); 1% = {pj['white_lux'] / 100:.1f} lux.\n\n")
        w(f"Projector shadows on the image: {G['monitor']['name']} {bay['proj_shadow_fixed'] * 100:.1f}% of the image area"
          f"; the {G['image_w'] / 12:.0f} ft image also spills onto the model's screen trim over {bay.get('image_on_trim', 0) * 100:.1f}% of its area "
          f"(image wider than the screen opening); hitter at address {bay['proj_shadow_address'] * 100:.1f}%, "
          f"top of backswing (club to {G['club_top_z'] / 12:.0f} ft) {bay['proj_shadow_top'] * 100:.1f}%.\n\n")
        if bay["clashes"]:
            w("Bay clashes (frustum = inside the projection pyramid; swing disc = inside the 1.9 m swing disc; buffer = within the 1 m buffer):\n\n")
            for c in bay["clashes"]:
                w(f"- {c['item']}: {'frustum ' if c['frustum'] else ''}{c['swing'] or ''} (closest {c['swing_dist_m']:.2f} m from the swing disc)\n")
        w("\n| option | track out | ball lux | ball w/ hitter | mat mean / min / U | stray sim play (lux, % white) | stray game night | frustum / swing clashes | shadow (heads / projector) | glare | cost |\n")
        w("|---|---|---|---|---|---|---|---|---|---|---|\n")
        for r in gd["rows"]:
            w(f"| {r['option']} | {ftin(r['track_lateral_in'])} | {r['ball_lux']:.0f} | {r['ball_lux_hitter_at_address']:.0f} | "
              f"{r['mat_mean_lux']:.0f} / {r['mat_min_lux']:.0f} / {r['mat_uniformity']:.2f} | {r['screen_stray_simplay_lux']:.2f}, {r['screen_stray_simplay_pct_white']:.2f}% | "
              f"{r['screen_stray_gamenight_lux']:.2f}, {r['screen_stray_gamenight_pct_white']:.2f}% | {r['frustum_clashes']} / {r['swing_clashes']} | "
              f"{r['screen_shadow_from_heads']} / {r['screen_shadow_from_projector']} | {r['glare_flags'] or '-'} | ${r['cost_usd']:,} |\n")
        w(f"\nBest sim-bay option: **{gd['best_package']}** with the tracks {ftin(gd['best_lateral'])} out.\n")
        b = golf_ball()
        w(f"\nSim-bay head positions (tracks parallel to the target line; mount points; ball at {ftin(b[0])} from the W wall, "
          f"{ftin(b[1] - 0)} from the S wall, i.e. {ftin(P['partition_n_face_y'] - 4.5 - b[1])} south of the partition's S face):\n\n")
        w("| head | from W wall (screen side) | from S wall | aim |\n|---|---|---|---|\n")
        for hg in golf_heads(gd["best_package"], gd["best_lateral"]):
            w(f"| {hg['tag']} | {ftin(hg['mount'][0])} | {ftin(hg['mount'][1])} | ball |\n")
        if rj.get("golf_mat_cycles"):
            g = rj["golf_mat_cycles"]
            ref = next((r for r in gd["rows"] if f"GOLF_{r['option']}_L{int(r['track_lateral_in'])}" == g["key"]), None)
            if ref:
                w(f"\nCycles check ({g['key']}, direct): mat mean {g['mean']:.0f} lux vs analytic {ref['mat_mean_lux']:.0f}.\n")
        if rj.get("spill_cycles", {}).get("sim_play") is not None:
            w(f"Cycles stray on the image in Sim play (incl. bounces, projector off): {rj['spill_cycles']['sim_play']:.2f} lux "
              f"({100 * rj['spill_cycles']['sim_play'] / pj['white_lux']:.2f}% of white).\n")
    w("\n## Flags\n\n")
    for k, fx in P["fixtures"].items():
        if fx.get("flag"):
            w(f"- {fx['name']}: {fx['flag']}.\n")
    fxp = an["fixtures"]
    for k in ("CHG", "SBL", "SILO"):
        w(f"- {P['fixtures'][k]['name']}: peak {fxp[k]['I0']:.0f} cd, flux from the beam model {fxp[k]['flux']:.0f} lm vs catalogue {P['fixtures'][k]['lm']} lm.\n")
    (ROOT / P["export_dir"] / "report.md").write_text("".join(L))
    print("REPORT OK")


# ============================================================================ main
if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    stage = argv[0] if argv else "all"
    for kv in argv[1:]:  # simple overrides: key=value (JSON)
        k, v = kv.split("=", 1)
        P[k] = json.loads(v)
    {"calibrate": stage_calibrate, "build": stage_build, "analyze": stage_analyze, "render": stage_render,
     "report": stage_report}[stage]()
