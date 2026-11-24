"""Build the shop scene in Blender from data/space.json (+ inventory + optional layout).

Run:  Blender --background --python scripts/build_scene.py -- --layout option-a
      (--layout none builds the shell and fixed items only)
Output: blend/<layout>.blend.  Scene units: 1 Blender unit = 1 inch.
"""
import argparse
import colorsys
import itertools
import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import assets as A  # noqa: E402

X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))


# ------------------------------------------------------------------ primitives
def add_box(bm, o, ex, ey, ez, sx, sy, sz):
    """Box spanning o + [0..sx]*ex + [0..sy]*ey + [0..sz]*ez."""
    vs = [bm.verts.new(o + ex * (i * sx) + ey * (j * sy) + ez * (k * sz))
          for i in (0, 1) for j in (0, 1) for k in (0, 1)]
    for f in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
        bm.faces.new([vs[i] for i in f])


def centered_box(cx, cy, z0, w, d, h, rot=0.0):
    r = math.radians(rot)
    ex, ey = Vector((math.cos(r), math.sin(r), 0)), Vector((-math.sin(r), math.cos(r), 0))
    o = Vector((cx, cy, z0)) - ex * (w / 2) - ey * (d / 2)
    return (o, ex, ey, Z, w, d, h)


def add_cyl(bm, cx, cy, z0, radius, h):
    res = bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=radius, radius2=radius, depth=h)
    bmesh.ops.translate(bm, verts=res["verts"], vec=(cx, cy, z0 + h / 2))


def make_obj(name, coll, boxes=(), material=None, transparent=False, cyl=None):
    bm = bmesh.new()
    for b in boxes:
        add_box(bm, *b)
    if cyl:
        add_cyl(bm, *cyl)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    if material:
        me.materials.append(material)
    if transparent:
        ob.show_transparent = True
    return ob


def add_label(text, x, y, z, size, rot, coll, material, name=None):
    cu = bpy.data.curves.new(name or f"LBL_{text}", "FONT")
    cu.body = text
    cu.size = size
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    ob = bpy.data.objects.new(name or f"LBL_{text}", cu)
    ob.location = (x, y, z)
    ob.rotation_euler = (0, 0, math.radians(rot))
    cu.materials.append(material)
    coll.objects.link(ob)
    return ob


_mats = {}

# Look used by photo renders (EEVEE/Cycles). Workbench diagram renders use diffuse_color only.
KIND_BY_NAME = {
    "slab": "floor", "wall": "flat_white", "interior_wall": "off_white", "glass": "glass",
    "door_insulated": "white", "door_solid": "plain", "barn_door": "white", "track": "black",
    "truss": "flat_black", "light": "emit", "tv": "black_gloss", "panel": "metal", "roof": "flat_black",
    "ahu": "metal", "fan": "plain", "platform": "plain", "vent": "black",
}


def mat(name, rgba, kind=None):
    if name in _mats:
        return _mats[name]
    m = bpy.data.materials.new(name)
    m.diffuse_color = rgba
    if rgba[3] < 1:
        for attr, val in (("blend_method", "BLEND"), ("surface_render_method", "BLENDED")):
            try:
                setattr(m, attr, val)
            except Exception:
                pass
    try:
        style(m, kind or KIND_BY_NAME.get(name, "plain"), rgba)
    except Exception as e:  # never let a material recipe break the build
        print(f"WARNING: material {name}: {e}")
    _mats[name] = m
    return m


def _set(node, names, value):
    for n in names if isinstance(names, (list, tuple)) else [names]:
        if n in node.inputs:
            node.inputs[n].default_value = value
            return


def style(m, kind, rgba):
    """Node-based (Principled BSDF) look with procedural textures. Object coords are world inches."""
    m.use_nodes = True
    N, Lk = m.node_tree.nodes, m.node_tree.links
    bsdf = next(n for n in N if n.type == "BSDF_PRINCIPLED")
    base = tuple(rgba[:3]) + (1.0,)
    _set(bsdf, "Base Color", base)
    _set(bsdf, "Roughness", 0.6)
    _set(bsdf, "Alpha", rgba[3])

    def coord(xz=False):
        tc = N.new("ShaderNodeTexCoord")
        if not xz:
            return tc.outputs["Object"]
        sep, comb = N.new("ShaderNodeSeparateXYZ"), N.new("ShaderNodeCombineXYZ")
        Lk.new(tc.outputs["Object"], sep.inputs[0])
        Lk.new(sep.outputs["X"], comb.inputs["X"])
        Lk.new(sep.outputs["Z"], comb.inputs["Y"])  # walls along X: pattern in the X-Z plane
        return comb.outputs[0]

    def ramp(fac, stops, constant=False):
        r = N.new("ShaderNodeValToRGB")
        if constant:
            r.color_ramp.interpolation = "CONSTANT"
        els = r.color_ramp.elements
        while len(els) < len(stops):
            els.new(0.5)
        for e, (pos, col) in zip(els, stops):
            e.position, e.color = pos, col
        Lk.new(fac, r.inputs["Fac"])
        return r.outputs["Color"]

    def scaled(c, f):
        return tuple(min(1.0, v * f) for v in c[:3]) + (1.0,)

    def brick(c1, mortar, bw, rh, ms, offset, xz):
        b = N.new("ShaderNodeTexBrick")
        b.offset = offset
        Lk.new(coord(xz), b.inputs["Vector"])
        for k, v in (("Color1", c1), ("Color2", c1), ("Mortar", mortar), ("Scale", 1.0),
                     ("Mortar Size", ms), ("Brick Width", bw), ("Row Height", rh)):
            _set(b, k, v)
        return b.outputs["Color"]

    if kind == "floor":  # Simiron decorative chip, "Domino" blend, 1/4in chips (reference/specs: colour guide + swatch)
        lin = lambda h: tuple((int(h[i:i + 2], 16) / 255.0) ** 2.2 for i in (0, 2, 4)) + (1.0,)
        v = N.new("ShaderNodeTexVoronoi")  # one random value per angular cell = one chip
        _set(v, "Scale", 4.0)  # object coords are inches -> ~1/4in chips
        _set(v, "Randomness", 1.0)
        Lk.new(coord(), v.inputs["Vector"])
        sep = N.new("ShaderNodeSeparateColor")
        Lk.new(v.outputs["Color"], sep.inputs[0])
        # chip shares measured from the Domino swatch: black 32%, mid grey 10%, light grey 31%, white 28%
        stops = [(0.0, lin("14110a")), (0.32, lin("625f59")), (0.42, lin("a9a8a3")), (0.73, lin("f4f1e9"))]
        Lk.new(ramp(sep.outputs[0], stops, constant=True), bsdf.inputs["Base Color"])
        _set(bsdf, "Roughness", 0.18)
        _set(bsdf, ["Coat Weight", "Clearcoat"], 0.8)
    elif kind == "wood":  # Timber Toffee (owner's door photo): light greyish-brown, oak-like cathedral grain
        photo = C.ROOT / "reference" / "textures" / "timber-toffee-door.png"
        if photo.exists():  # real texture: box-projected, one image tile per ~12in x 24in
            img = bpy.data.images.load(str(photo), check_existing=True)
            try:
                img.pack()
            except Exception:
                pass
            tex = N.new("ShaderNodeTexImage")
            tex.image, tex.projection, tex.projection_blend = img, "BOX", 0.25
            mp = N.new("ShaderNodeMapping")
            _set(mp, "Scale", (1 / 12.0, 1 / 12.0, 1 / 24.0))
            Lk.new(coord(), mp.inputs["Vector"])
            Lk.new(mp.outputs["Vector"], tex.inputs["Vector"])
            Lk.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        else:  # procedural stand-in matched by eye to the photo: long vertical streaks of grain
            lin = lambda h: tuple((int(h[i:i + 2], 16) / 255.0) ** 2.2 for i in (0, 2, 4)) + (1.0,)
            mp = N.new("ShaderNodeMapping")
            _set(mp, "Scale", (0.9, 0.9, 0.035))  # stretch along Z = vertical grain on doors and sides
            Lk.new(coord(), mp.inputs["Vector"])
            n = N.new("ShaderNodeTexNoise")
            for k, val in (("Scale", 2.2), ("Detail", 9.0), ("Roughness", 0.62), ("Distortion", 0.6)):
                _set(n, k, val)
            Lk.new(mp.outputs["Vector"], n.inputs["Vector"])
            Lk.new(ramp(n.outputs["Fac"], [(0.3, lin("76634d")), (0.5, lin("9a866e")), (0.7, lin("b6a48a"))]), bsdf.inputs["Base Color"])
        _set(bsdf, "Roughness", 0.5)
    elif kind == "tile":  # 3x6 subway tile, running bond, 1/8in light-grey grout (pattern in the wall's X-Z plane)
        Lk.new(brick(base, (0.66, 0.66, 0.64, 1), 6.0, 3.0, 0.125, 0.5, True), bsdf.inputs["Base Color"])
        _set(bsdf, "Roughness", 0.12)
    elif kind == "quartz":  # engineered quartz in the item's colour: fine speckle + faint soft veining
        n = N.new("ShaderNodeTexNoise")
        for k, val in (("Scale", 0.6), ("Detail", 6.0)):
            _set(n, k, val)
        Lk.new(coord(), n.inputs["Vector"])
        speck = N.new("ShaderNodeTexNoise")
        for k, val in (("Scale", 9.0), ("Detail", 2.0)):
            _set(speck, k, val)
        Lk.new(coord(), speck.inputs["Vector"])
        mix = N.new("ShaderNodeMath")
        mix.operation = "MULTIPLY_ADD"
        Lk.new(speck.outputs["Fac"], mix.inputs[0])
        mix.inputs[1].default_value, mix.inputs[2].default_value = 0.35, 0.0
        add = N.new("ShaderNodeMath")
        add.operation = "ADD"
        Lk.new(n.outputs["Fac"], add.inputs[0])
        Lk.new(mix.outputs[0], add.inputs[1])
        Lk.new(ramp(add.outputs[0], [(0.45, scaled(base, 0.88)), (0.75, scaled(base, 1.0)),
                                     (0.95, scaled(base, 1.18))]), bsdf.inputs["Base Color"])
        _set(bsdf, "Roughness", 0.14)
        _set(bsdf, ["Coat Weight", "Clearcoat"], 0.3)
    elif kind == "steel":
        _set(bsdf, "Base Color", (0.74, 0.75, 0.77, 1))
        _set(bsdf, "Metallic", 1.0)
        _set(bsdf, "Roughness", 0.32)
    elif kind == "metal":
        _set(bsdf, "Base Color", (0.5, 0.52, 0.55, 1))
        _set(bsdf, "Metallic", 0.8)
        _set(bsdf, "Roughness", 0.4)
    elif kind == "glass":
        _set(bsdf, "Base Color", (0.8, 0.9, 0.95, 1))
        _set(bsdf, "Roughness", 0.04)
        _set(bsdf, "Alpha", 0.22)
    elif kind in ("flat_white", "foam"):  # flat white exterior walls
        _set(bsdf, "Base Color", (0.95, 0.95, 0.95, 1))
        _set(bsdf, "Roughness", 0.95)
        _set(bsdf, ["Specular IOR Level", "Specular"], 0.08)
    elif kind == "spray_foam":  # closed-cell spray foam in the exterior wall bays: off-white, lumpy (noise bump)
        n = N.new("ShaderNodeTexNoise")
        for k, val in (("Scale", 0.22), ("Detail", 10.0), ("Roughness", 0.62)):
            _set(n, k, val)
        Lk.new(coord(), n.inputs["Vector"])
        Lk.new(ramp(n.outputs["Fac"], [(0.35, (0.76, 0.74, 0.68, 1)), (0.7, (0.93, 0.92, 0.88, 1))]), bsdf.inputs["Base Color"])
        bump = N.new("ShaderNodeBump")
        _set(bump, "Strength", 0.7)
        _set(bump, "Distance", 0.6)
        Lk.new(n.outputs["Fac"], bump.inputs["Height"])
        Lk.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
        _set(bsdf, "Roughness", 0.92)
        _set(bsdf, ["Specular IOR Level", "Specular"], 0.1)
    elif kind in ("lumber", "brown_wood", "plywood"):  # exposed framing: pale pine posts/girts, brown door bucks, plywood
        n = N.new("ShaderNodeTexNoise")
        mp = N.new("ShaderNodeMapping")
        _set(mp, "Scale", (0.6, 0.6, 0.6))
        Lk.new(coord(), mp.inputs["Vector"])
        for k, val in (("Scale", 1.5), ("Detail", 6.0), ("Distortion", 1.2)):
            _set(n, k, val)
        Lk.new(mp.outputs["Vector"], n.inputs["Vector"])
        Lk.new(ramp(n.outputs["Fac"], [(0.3, scaled(base, 0.8)), (0.7, scaled(base, 1.1))]), bsdf.inputs["Base Color"])
        _set(bsdf, "Roughness", 0.75)
    elif kind == "off_white":  # warm off-white bathroom / partition drywall
        _set(bsdf, "Base Color", A.hexrgba("#EDEAE2"))
        _set(bsdf, "Roughness", 0.82)
        _set(bsdf, ["Specular IOR Level", "Specular"], 0.12)
    elif kind == "panel_paint":  # Sherwin-Williams SW 6227 Meditative (#96AAB0) satin drywall & board-and-batten trim
        sw_lin = A.hexrgba("#96AAB0")
        _set(bsdf, "Base Color", sw_lin)
        _set(bsdf, "Roughness", 0.52)
    elif kind == "white":
        _set(bsdf, "Base Color", (0.94, 0.94, 0.93, 1))
        _set(bsdf, "Roughness", 0.45)
    elif kind == "flat_black":  # flat black ceiling and trusses
        _set(bsdf, "Base Color", (0.015, 0.015, 0.015, 1))
        _set(bsdf, "Roughness", 0.98)
        _set(bsdf, ["Specular IOR Level", "Specular"], 0.03)
    elif kind in ("black", "black_gloss"):
        _set(bsdf, "Base Color", (0.03, 0.03, 0.03, 1))
        _set(bsdf, "Roughness", 0.15 if kind == "black_gloss" else 0.7)
    elif kind == "emit":
        _set(bsdf, ["Emission Color", "Emission"], (1.0, 0.95, 0.85, 1))
        _set(bsdf, "Emission Strength", 25.0)


def item_color(key):
    h = (sum(ord(c) * (i + 3) for i, c in enumerate(key)) % 97) / 97.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.55, 0.85)
    return (r, g, b, 1.0)


# ----------------------------------------------------------------------- shell
def solid_intervals(z_max, holes):
    """Complement of merged hole z-intervals within [0, z_max]."""
    out, cur = [], 0.0
    for z0, z1 in sorted(holes):
        z0, z1 = max(z0, 0.0), min(z1, z_max)
        if z0 > cur:
            out.append((cur, z0))
        cur = max(cur, z1)
    if cur < z_max:
        out.append((cur, z_max))
    return out


def solid_strips(amin, amax, height, holes):
    """Yield (a0, a1, z0, z1) solid pieces of a wall face with rectangular holes (a0, a1, z0, z1)."""
    cuts = sorted({amin, amax, *[min(max(v, amin), amax) for h in holes for v in h[:2]]})
    for p, q in zip(cuts, cuts[1:]):
        if q - p < 1e-6:
            continue
        zs = [(h[2], h[3]) for h in holes if h[0] <= p + 1e-9 and h[1] >= q - 1e-9]
        for z0, z1 in solid_intervals(height, zs):
            yield p, q, z0, z1


def foam_recess(shop):
    """How far the exterior wall surface (spray foam) sits behind the post/girt face; 0 = flat walls (no framing data)."""
    fr = shop["shell"].get("wall_framing")
    return float(fr.get("foam_recess", 3)) if fr else 0.0


def wall_boxes(wall, shop, thick):
    """Wall slab with openings cut out, as boxes. Its inside face is the foam surface: on the footprint line,
    or foam_recess behind it when shell.wall_framing is present (the posts/girts then stand on the line)."""
    L, W, H = C.shell_dims(shop)
    (ox, oy), (dx, dy), (nx, ny), length = C.wall_frame(wall, L, W)
    rec = foam_recess(shop)
    o2, d2, n2 = Vector((ox, oy, 0)) - Vector((nx, ny, 0)) * rec, Vector((dx, dy, 0)), Vector((nx, ny, 0))
    ext = thick + rec if wall in ("W-S", "W-N") else rec  # S/N walls cover the corners
    holes = []
    for wi in shop["wall_items"]:
        if wi["wall"] == wall and wi["kind"] in C.OPENINGS:
            a0, a1 = C.wall_item_span(wi)
            holes.append((a0, a1, wi["z"], wi["z"] + wi["h"]))
    return [(o2 + d2 * p - n2 * thick + Z * z0, d2, n2, Z, q - p, thick, z1 - z0)
            for p, q, z0, z1 in solid_strips(-ext, length + ext, H, holes)]


def build_shell(shop, coll):
    L, W, H = C.shell_dims(shop)
    sh = shop["shell"]
    thick = sh.get("wall_thickness", 6)
    slab = sh.get("slab_thickness", 4)
    make_obj("Slab", coll, [(Vector((0, 0, -slab)), X, Y, Z, L, W, slab)], mat("slab", (0.62, 0.62, 0.6, 1)))
    if sh.get("wall_framing"):
        wmat = mat("wall_foam", (0.86, 0.85, 0.80, 1), "spray_foam")
    else:
        wmat = mat("wall", (0.95, 0.95, 0.95, 1), "flat_white")
    for wall in C.WALLS:
        make_split(f"Wall_{wall}", coll, wall_boxes(wall, shop, thick), wmat)
    build_wall_framing(shop, coll)
    build_roof(shop, coll)


FRAMING_MATS = {  # name -> (diagram rgba, photo kind)
    "lumber": ((0.80, 0.70, 0.52, 1), "lumber"), "brown_wood": ((0.42, 0.29, 0.18, 1), "brown_wood"),
    "plywood": ((0.72, 0.60, 0.43, 1), "plywood"), "white": ((0.94, 0.94, 0.93, 1), "white"),
    "black": ((0.02, 0.02, 0.02, 1), "flat_black"), "foam": ((0.86, 0.85, 0.80, 1), "spray_foam"),
}


def build_wall_framing(shop, coll):
    """Exposed exterior-wall framing in front of the recessed foam (shell.wall_framing + wall_items posts).

    Objects are named Wall_<wall>_framing_<material> so the iso views hide them with their wall; parts above
    door height go to ..._hdr (hidden in plan). Each part fills the foam recess and stands `depth` proud of the face."""
    fr = shop["shell"].get("wall_framing")
    if not fr:
        return
    L, W, H = C.shell_dims(shop)
    rec = foam_recess(shop)
    parts = {}  # (wall, material, is_hdr) -> boxes

    def add(wall, m, a0, a1, z0, z1, d0=None, d1=0.0, hdr=None):
        (ox, oy), (dx, dy), (nx, ny), _ = C.wall_frame(wall, L, W)
        o2, d2, n2 = Vector((ox, oy, 0)), Vector((dx, dy, 0)), Vector((nx, ny, 0))
        d0 = -rec if d0 is None else d0
        if a1 - a0 <= 0 or z1 - z0 <= 0 or d1 - d0 <= 0:
            return
        hdr = z0 >= 84.0 if hdr is None else hdr
        parts.setdefault((wall, m, hdr), []).append((o2 + d2 * a0 + n2 * d0 + Z * z0, d2, n2, Z, a1 - a0, d1 - d0, z1 - z0))

    post_w = 5.5
    for wi in shop["wall_items"]:  # posts (taped + scan); outlets and panels sit on their face
        if wi["kind"] == "post":
            a0, a1 = C.wall_item_span(wi)
            add(wi["wall"], "lumber", a0, a1, wi["z"], wi["z"] + wi["h"], hdr=False)
    if fr.get("corner_posts"):
        for wall in C.WALLS:
            length = C.wall_frame(wall, L, W)[3]
            for a0 in (0.0, length - post_w):
                add(wall, "lumber", a0, a0 + post_w, 0, H, hdr=False)
    eh = fr.get("eave_header")
    if eh:
        for wall in eh["walls"]:
            length = C.wall_frame(wall, L, W)[3]
            add(wall, eh.get("material", "black"), 0, length, eh["z0"], eh["z1"], hdr=True)
    dt = fr.get("door_trim")
    if dt:
        w, dd, hh, m = dt.get("w", 5.5), dt.get("depth", 0.75), dt.get("header_h", 7.25), dt.get("material", "brown_wood")
        for wi in shop["wall_items"]:
            if wi["kind"] not in dt.get("kinds", ["overhead_door", "door"]):
                continue
            a0, a1 = C.wall_item_span(wi)
            zt = wi["z"] + wi["h"]
            for b0 in (a0 - w, a1):  # jamb legs
                add(wi["wall"], m, b0, b0 + w, wi["z"], zt, d1=dd, hdr=False)
            add(wi["wall"], m, a0 - w, a1 + w, zt, zt + hh, d1=dd, hdr=True)  # header
    for e in fr.get("elements", []):
        wall, m, k = e["wall"], e.get("material", "lumber"), e["kind"]
        a0, a1, z0, z1, dep = e["a0"], e["a1"], e["z0"], e["z1"], e.get("depth", 0.0)
        if k == "shelf":  # ledger in the recess + shelf board out to `depth`
            add(wall, m, a0, a1, z0 - 3.5, z0, d1=0.75)
            add(wall, m, a0, a1, z0, z1, d0=0.0, d1=dep)
        elif k == "rack":  # free-standing-looking wood rack against the face: top, low shelf, 4 legs
            t = 1.5
            add(wall, m, a0, a1, z1 - t, z1, d0=0.0, d1=dep, hdr=False)
            add(wall, m, a0, a1, z0 + 6, z0 + 6 + t, d0=0.0, d1=dep, hdr=False)
            for la in (a0, a1 - 3.5):
                for ld in (0.0, dep - 3.5):
                    add(wall, m, la, la + 3.5, z0, z1 - t, d0=ld, d1=ld + 3.5, hdr=False)
        else:  # board / stud / backer / header: fills the recess, `depth` proud of the face
            add(wall, m, a0, a1, z0, z1, d1=dep)
    for (wall, m, hdr), boxes in sorted(parts.items()):
        rgba, kind = FRAMING_MATS.get(m, FRAMING_MATS["lumber"])
        make_obj(f"Wall_{wall}_framing_{m}{'_hdr' if hdr else ''}", coll, boxes, mat(f"framing_{m}", rgba, kind))


def build_roof(shop, coll):
    """Flat black roof deck + gable fills over the trusses (shown in photo eye-level views; casts no shadow)."""
    L, W, H = C.shell_dims(shop)
    sh = shop["shell"]
    ch = sh.get("truss_chord", {}).get("h", 5.5)
    rise = (W / 2) * sh.get("roof_pitch", 4) / 12.0
    e = H + ch + 0.5
    v = [(0, 0, e), (L, 0, e), (L, W / 2, e + rise), (0, W / 2, e + rise), (0, W, e), (L, W, e),
         (0, 0, H), (0, W, H), (L, 0, H), (L, W, H)]
    f = [(0, 1, 2, 3), (3, 2, 5, 4), (6, 0, 3, 4, 7), (8, 9, 5, 2, 1)]
    me = bpy.data.meshes.new("ROOF")
    me.from_pydata(v, [], f)
    me.materials.append(mat("roof", (0.02, 0.02, 0.02, 1), "flat_black"))
    ob = bpy.data.objects.new("ROOF", me)
    try:
        ob.visible_shadow = False  # let the (sun) light in
    except Exception:
        pass
    coll.objects.link(ob)


def make_split(name, coll, boxes, m):
    """Wall pieces resting on the floor -> name; pieces above openings (headers) -> name_hdr (hidden in plan)."""
    base = [b for b in boxes if b[0].z < 1e-6]
    hdr = [b for b in boxes if b[0].z >= 1e-6]
    make_obj(name, coll, base, m)
    if hdr:
        make_obj(f"{name}_hdr", coll, hdr, m)


# ----------------------------------------------------------------------- fixed
def build_wall_items(shop, coll):
    L, W, H = C.shell_dims(shop)
    thick = shop["shell"].get("wall_thickness", 6)
    glass = mat("glass", (0.55, 0.8, 0.95, 0.35))
    leaves = {"glass": glass, "insulated": mat("door_insulated", (0.8, 0.8, 0.76, 1)),
              "solid": mat("door_solid", (0.55, 0.4, 0.28, 1))}
    for wi in shop["wall_items"]:
        (ox, oy), (dx, dy), (nx, ny), _ = C.wall_frame(wi["wall"], L, W)
        o2, d2, n2 = Vector((ox, oy, 0)), Vector((dx, dy, 0)), Vector((nx, ny, 0))
        a0, a1 = C.wall_item_span(wi)
        if wi["kind"] == "post" and shop["shell"].get("wall_framing"):
            continue  # drawn as exposed framing (build_wall_framing)
        if wi["kind"] == "overhead_door":
            build_overhead_door(wi, o2, d2, n2, a0, a1, thick, shop, coll, leaves)
        elif wi["kind"] in C.OPENINGS:
            leaf = wi.get("leaf", "glass" if wi["kind"] == "window" else "solid")
            t0 = -thick / 2 - 0.5  # thin leaf in the middle of the wall thickness
            origin = o2 + d2 * a0 + n2 * t0 + Z * wi["z"]
            make_obj(f"WI_{wi['id']}", coll, [(origin, d2, n2, Z, a1 - a0, 1.0, wi["h"])],
                     leaves[leaf], transparent=(leaf == "glass"))
        else:  # fixture / panel / outlet standing proud of the wall
            depth = wi.get("depth", 6)
            origin = o2 + d2 * a0 + Z * wi["z"]
            m = mat("panel", (0.45, 0.47, 0.5, 1)) if wi["kind"] in ("panel", "outlet", "mount") \
                else mat("vent", (0.08, 0.08, 0.08, 1)) if wi["kind"] == "vent" \
                else mat("fixture", (0.75, 0.55, 0.3, 1))
            make_obj(f"WI_{wi['id']}", coll, [(origin, d2, n2, Z, a1 - a0, depth, wi["h"])], m)
        if wi["kind"] in ("outlet", "post"):
            continue  # too small/many to label legibly
        c = o2 + d2 * ((a0 + a1) / 2) + n2 * 2
        add_label(wi["id"], c.x, c.y, wi["z"] + wi["h"] + 4, 6, 0, coll, mat("label", (0.1, 0.1, 0.1, 1)),
                  name=f"LBL_{wi['id']}")


def build_overhead_door(wi, o2, d2, n2, a0, a1, thick, shop, coll, leaves):
    """Sectional overhead door (closed) + standard-lift track: vertical tracks, horizontal tracks, torsion shaft, hangers."""
    H = C.shell_dims(shop)[2]
    w, h, z0 = a1 - a0, wi["h"], wi["z"]
    n = wi.get("sections", 4)
    t_in = -0.5  # door panel sits just outside the inside face
    glass = wi.get("leaf") == "glass"
    secs, frame = [], []
    sh = h / n
    for i in range(n):
        zb = z0 + i * sh
        if glass:  # aluminium full-view: glass lites in a black frame grid
            secs.append((o2 + d2 * a0 + n2 * (t_in - 1.5) + Z * zb, d2, n2, Z, w, 0.5, sh))
            cols = wi.get("columns", 4)
            for k in range(cols + 1):  # stiles / mullions
                s = 3.0 if k in (0, cols) else 1.5
                a = a0 + k * (w - s) / cols
                frame.append((o2 + d2 * a + n2 * (t_in - 2) + Z * zb, d2, n2, Z, s, 2.0, sh))
            for zz, s in ((zb, 2.5), (zb + sh - 2.5, 2.5)):  # rails
                frame.append((o2 + d2 * a0 + n2 * (t_in - 2) + Z * zz, d2, n2, Z, w, 2.0, s))
        else:  # steel sections with a small reveal between them
            secs.append((o2 + d2 * a0 + n2 * (t_in - 2) + Z * (zb + 0.2), d2, n2, Z, w, 2.0, sh - 0.4))
    leaf = leaves["glass"] if glass else leaves.get(wi.get("leaf", "insulated"), leaves["insulated"])
    make_obj(f"WI_{wi['id']}", coll, secs, leaf, transparent=glass)
    if frame:
        fmat = mat("door_frame_alu", (0.76, 0.78, 0.80, 1), "steel") if glass else mat("door_frame", (0.05, 0.05, 0.05, 1), "black")
        make_obj(f"WI_{wi['id']}_frame", coll, frame, fmat)
    # standard-lift track hardware (galvanised)
    run = wi.get("open_depth", h + 18)
    zt = z0 + h
    parts = []
    for a in (a0 - 3.0, a1 + 1.0):
        parts.append((o2 + d2 * a + Z * z0, d2, n2, Z, 2.0, 3.0, h + 6))            # vertical track
        parts.append((o2 + d2 * a + n2 * 3 + Z * (zt + 8), d2, n2, Z, 2.0, run - 3, 2.0))  # horizontal track
        parts.append((o2 + d2 * a + n2 * (run - 1.5) + Z * (zt + 10), d2, n2, Z, 1.5, 1.5, max(H - zt - 10, 1)))  # rear hanger
    parts.append((o2 + d2 * (a0 - 6) + n2 * 2 + Z * (zt + 12), d2, n2, Z, w + 12, 2.0, 2.0))  # torsion spring shaft
    make_obj(f"TRACK_{wi['id']}", coll, parts, mat("galvanized", (0.62, 0.64, 0.66, 1), "metal"))


def build_fan(it, coll, H):
    """Ceiling fan: downrod to the truss underside, motor housing, 5 blades at it['z']."""
    m = mat(f"fan_{it.get('color', 'white')}", (0.9, 0.9, 0.9, 1) if it.get("color") != "black" else (0.04, 0.04, 0.04, 1),
            "white" if it.get("color") != "black" else "black_gloss")
    x, y, zb, span = it["x"], it["y"], it["z"], it["w"]
    boxes = [(Vector((x - 0.6, y - 0.6, zb + 5)), X, Y, Z, 1.2, 1.2, max(H - zb - 5, 1))]  # downrod
    for k in range(5):
        a = math.radians(k * 72 + 18)
        d, p = Vector((math.cos(a), math.sin(a), 0)), Vector((-math.sin(a), math.cos(a), 0))
        boxes.append((Vector((x, y, zb)) + d * 4.5 - p * 2.75, d, p, Z, span / 2 - 4.5, 5.5, 0.5))
    make_obj(f"CI_{it['id']}", coll, boxes, m, cyl=(x, y, zb - 2, 4.5, 7))


def build_interior_walls(shop, coll):
    default_m = mat("interior_wall", (0.93, 0.92, 0.89, 1), "off_white")  # warm off-white bathroom / partition drywall
    casing_m = mat("trim_white", (0.94, 0.94, 0.93, 1), "white")
    door_m = mat("barn_door", (0.94, 0.94, 0.93, 1), "white")
    track_m = mat("track", (0.12, 0.12, 0.12, 1), "black")
    for iw in shop["interior_walls"]:
        m = default_m
        if iw.get("paint") and iw["paint"].get("hex"):
            hx = iw["paint"]["hex"].lstrip("#")
            srgb = tuple(int(hx[i:i + 2], 16) / 255.0 for i in (0, 2, 4)) + (1.0,)
            m = mat(f"iw_paint_{iw['id']}", srgb, "panel_paint")
        (x1, y1), (ux, uy), (nx, ny), length = C.seg_frame(iw)
        p, u, n, t = Vector((x1, y1, 0)), Vector((ux, uy, 0)), Vector((nx, ny, 0)), iw["thickness"]
        holes = [(o["offset"], o["offset"] + o["w"], o.get("z", 0), o.get("z", 0) + o["h"])
                 for o in iw.get("openings", [])]
        # an end on the shell footprint runs on into the foam recess (no gap behind the post face)
        L, W, _ = C.shell_dims(shop)
        rec = foam_recess(shop)
        on_shell = lambda x, y: min(abs(x), abs(y), abs(L - x), abs(W - y)) < 0.5
        s0 = -rec if on_shell(iw["x1"], iw["y1"]) else 0.0
        s1 = length + (rec if on_shell(iw["x2"], iw["y2"]) else 0.0)
        boxes = [(p + u * a0 - n * (t / 2) + Z * z0, u, n, Z, a1 - a0, t, z1 - z0)
                 for a0, a1, z0, z1 in solid_strips(s0, s1, iw["height"], holes)]
        make_split(f"IW_{iw['id']}", coll, boxes, m)

        # Build programmatic 3D board-and-batten overlay trim and door casings from space.json
        tr = iw.get("trim")
        if tr:
            side_vec = Vector(C.SIDES[tr.get("side", "N")] + (0,))
            s = 1 if side_vec.dot(n) >= 0 else -1
            n_out = n * s
            face_o = p + n_out * (t / 2)
            bw = tr.get("batten_width", 3.5)
            bd = tr.get("batten_depth", 0.625)
            cd_depth = tr.get("casing_depth", 0.75)

            tiles = [r[:4] for r in tile_rects(shop, iw, s)]  # no battens behind a tile backsplash

            def trim(a0, a1, z0, z1, depth):
                for b0, b1, c0, c1 in subtract_rects((a0, a1, z0, z1), tiles):
                    trim_boxes.append((face_o + u * b0 + Z * c0, u, n_out, Z, b1 - b0, depth, c1 - c0))

            trim_boxes = []
            for hr in tr.get("horizontal_rails", []):
                z0, h, d_hr = hr["z"], hr["h"], hr.get("w_depth", bd)
                for a0, a1 in hr.get("spans", []):
                    trim(a0, a1, z0, z0 + h, d_hr)
            for vb in tr.get("vertical_battens", []):
                vw = vb.get("w", bw)
                trim(vb["x"] - vw / 2.0, vb["x"] + vw / 2.0, vb["z0"], vb["z1"], bd)
            if trim_boxes:
                base_tb = [b for b in trim_boxes if b[0].z < 83.0]
                hdr_tb = [b for b in trim_boxes if b[0].z >= 83.0]
                if base_tb:
                    make_obj(f"TRIM_{iw['id']}", coll, base_tb, m)
                if hdr_tb:
                    make_obj(f"TRIM_{iw['id']}_hdr", coll, hdr_tb, m)

            casing_boxes, casing_hdr = [], []
            for dc in tr.get("door_casings", []):
                cz0, cz1 = dc["z0"], dc["z1"]
                for lx0, lx1 in (dc["left_x"], dc["right_x"]):
                    casing_boxes.append((face_o + u * lx0 + Z * cz0, u, n_out, Z, lx1 - lx0, cd_depth, cz1 - cz0))
                hdr = dc.get("header")
                if hdr:
                    hx0, hx1, hz0, hz1 = hdr["x0"], hdr["x1"], hdr["z0"], hdr["z1"]
                    casing_hdr.append((face_o + u * hx0 + Z * hz0, u, n_out, Z, hx1 - hx0, cd_depth, hz1 - hz0))
            if casing_boxes:
                make_obj(f"CASING_{iw['id']}", coll, casing_boxes, casing_m)
            if casing_hdr:
                make_obj(f"CASING_{iw['id']}_hdr", coll, casing_hdr, casing_m)

        build_wall_plates(shop, iw, coll, p, u, n, t)

        for o in iw.get("openings", []):
            if "slide" not in o:
                continue
            # barn door: leaf (closed) and track mounted on the slide side's face / track header board
            (b0, b1), s = C.slide_span(iw, o)
            a0, a1 = o["offset"], o["offset"] + o["w"]
            n_out = n * s
            face = n_out * (t / 2)
            lo, hi = min(a0, b0) - 2, max(a1, b1) + 2
            leaf_o = p + u * (a0 - 2) + face + n_out * 1.1 + Z * 0
            make_obj(f"DOOR_{iw['id']}_{o['id']}", coll, [(leaf_o, u, n_out, Z, o["w"] + 4, 1.5, o["h"] + 2)], door_m)
            trk_o = p + u * lo + face + n_out * 0.75 + Z * (o["h"] + 2.75)
            make_obj(f"TRACK_{iw['id']}_{o['id']}", coll, [(trk_o, u, n_out, Z, hi - lo, 1.5, 1.75)], track_m)


def tile_rects(shop, iw, side):
    """(a0, a1, z0, z1, depth) of backsplash floor items against one face (side +1/-1 along the wall's left normal)."""
    (x1, y1), (ux, uy), (nx, ny), _ = C.seg_frame(iw)
    out = []
    for fi in shop["floor_items"]:
        if fi["type"] != "backsplash":
            continue
        dx, dy = fi["x"] - x1, fi["y"] - y1
        a, dist = dx * ux + dy * uy, dx * nx + dy * ny
        if abs(dist - side * iw["thickness"] / 2) > fi["d"] + 1:
            continue
        r = math.radians(fi.get("rot", 0))
        half = abs(fi["w"] / 2 * (math.cos(r) * ux + math.sin(r) * uy)) + abs(fi["d"] / 2 * (-math.sin(r) * ux + math.cos(r) * uy))
        z0 = fi.get("z", 0)
        out.append((a - half, a + half, z0, z0 + fi["h"], fi["d"]))
    return out


def subtract_rects(r, holes):
    """Parts of rectangle r = (a0, a1, z0, z1) not covered by any of the holes."""
    parts = [r]
    for h0, h1, k0, k1 in holes:
        nxt = []
        for a0, a1, z0, z1 in parts:
            if h0 >= a1 or h1 <= a0 or k0 >= z1 or k1 <= z0:
                nxt.append((a0, a1, z0, z1))
                continue
            if a0 < h0:
                nxt.append((a0, h0, z0, z1))
            if h1 < a1:
                nxt.append((h1, a1, z0, z1))
            m0, m1 = max(a0, h0), min(a1, h1)
            if z0 < k0:
                nxt.append((m0, m1, z0, k0))
            if k1 < z1:
                nxt.append((m0, m1, k1, z1))
        parts = nxt
    return [q for q in parts if q[1] - q[0] > 0.05 and q[3] - q[2] > 0.05]


PLATE = {1: (2.75, 4.5), 2: (4.5, 4.5), 3: (6.4, 4.5)}  # wall plate w x h by gang count (matches blueprint.py)


def build_wall_plates(shop, iw, coll, p, u, n, t):
    """Planned receptacle/switch boxes from data/electrical.json as decora plates (box z = plate centre)."""
    path = C.ROOT / "data" / "electrical.json"
    if not path.exists():
        return
    elec = __import__("json").loads(path.read_text())
    if elec.get("wall") != iw["id"]:
        return
    plates, rockers, slots = [], [], []
    for b in elec.get("boxes", []):
        side = 1 if Vector(C.SIDES[b["face"]] + (0,)).dot(n) >= 0 else -1
        n_out = n * side
        w, h = PLATE.get(b.get("gangs", 1), PLATE[1])
        a0, z0 = b["x"] - w / 2, b["z"] - h / 2
        proud = 0.0  # sits on the tile where there is a backsplash
        for t0, t1, k0, k1, dep in tile_rects(shop, iw, side):
            if t0 <= b["x"] <= t1 and k0 <= b["z"] <= k1:
                proud = max(proud, dep)
        o = p + n_out * (t / 2 + proud)
        plates.append((o + u * a0 + Z * z0, u, n_out, Z, w, 0.3, h))
        for g in range(b.get("gangs", 1)):  # one decora opening per gang (receptacle face or rocker)
            gx = a0 + (w / b.get("gangs", 1)) * (g + 0.5)
            rockers.append((o + n_out * 0.3 + u * (gx - 0.655) + Z * (b["z"] - 1.31), u, n_out, Z, 1.31, 0.12, 2.62))
            if b.get("kind") == "receptacle":  # duplex decora: two faces, each with two blade slots + ground
                for fz in (b["z"] + 0.62, b["z"] - 0.62):
                    for sx in (-0.25, 0.25):
                        slots.append((o + n_out * 0.42 + u * (gx + sx - 0.04) + Z * (fz - 0.13), u, n_out, Z, 0.08, 0.03, 0.3))
                    slots.append((o + n_out * 0.42 + u * (gx - 0.06) + Z * (fz - 0.36), u, n_out, Z, 0.12, 0.03, 0.12))
            else:  # switch: rocker split line
                slots.append((o + n_out * 0.42 + u * (gx - 0.55) + Z * (b["z"] - 0.02), u, n_out, Z, 1.1, 0.03, 0.04))
    if plates:  # plate a shade off the tile white so its true 2.75x4.5in-per-gang outline reads
        make_obj(f"PLATES_{iw['id']}", coll, plates, mat("wall_plate", (0.80, 0.80, 0.78, 1), "plain"))
        make_obj(f"PLATES_{iw['id']}_devices", coll, rockers, mat("wall_device", (0.92, 0.92, 0.90, 1), "plain"))
        make_obj(f"PLATES_{iw['id']}_slots", coll, slots, mat("wall_device_slot", (0.05, 0.05, 0.05, 1), "black"))


def build_truss(t, shop, coll, m):
    L, W, H = C.shell_dims(shop)
    sh = shop["shell"]
    cw = sh.get("truss_chord", {}).get("w", 1.5)
    ch = sh.get("truss_chord", {}).get("h", 5.5)
    pitch = sh.get("roof_pitch", 4)
    if t.get("span", "Y") == "Y":
        u, v, S, pos = Y, X, W, t["x"]
    else:
        u, v, S, pos = X, Y, L, t["y"]
    half = S / 2
    rise = half * pitch / 12.0
    rl = math.hypot(half, rise)
    c, s = half / rl, rise / rl
    base = v * (pos - cw / 2) + Z * H
    boxes = [
        (base, u, v, Z, S, cw, ch),                                              # bottom chord
        (base, u * c + Z * s, v, u * -s + Z * c, rl, cw, ch),                    # left top chord
        (base + u * S, u * -c + Z * s, v, u * s + Z * c, rl, cw, ch),            # right top chord
        (base + u * (half - cw / 2) + Z * ch, u, v, Z, cw, cw, max(rise - ch, 1)),  # king post
    ]
    make_obj(f"TRUSS_{t['id']}", coll, boxes, m)


def build_ceiling_items(shop, coll):
    truss_m = mat("truss", (0.06, 0.06, 0.06, 1), "flat_black")
    plat_m = mat("platform", (0.6, 0.45, 0.3, 1))
    ahu_m = mat("ahu", (0.7, 0.75, 0.8, 1))
    light_m = mat("light", (1.0, 0.95, 0.5, 1))
    fan_m = mat("fan", (0.5, 0.5, 0.52, 1))
    for it in shop["ceiling_items"]:
        t = it["type"]
        if t == "truss":
            build_truss(it, shop, coll, truss_m)
        elif t in ("platform", "box"):
            m = plat_m if t == "platform" else ahu_m
            make_obj(f"CI_{it['id']}", coll,
                     [centered_box(it["x"], it["y"], it["z"], it["w"], it["d"], it["h"], it.get("rot", 0))], m)
            if t == "box":
                add_label(it.get("name", it["id"]), it["x"], it["y"], it["z"] + it["h"] + 0.2,
                          5, it.get("rot", 0), coll, mat("label", (0.1, 0.1, 0.1, 1)), name=f"LBL_{it['id']}")
        elif t == "light":
            make_obj(f"CI_{it['id']}", coll, cyl=(it["x"], it["y"], it["z"], it["w"] / 2, it["h"]), material=light_m)
        elif t == "fan":
            build_fan(it, coll, C.shell_dims(shop)[2])
        elif t == "duct":  # vertical round duct drop (open end at the bottom)
            make_obj(f"CI_{it['id']}", coll, cyl=(it["x"], it["y"], it["z"], it["w"] / 2, it["h"]),
                     material=mat("duct", (0.78, 0.78, 0.8, 1), "metal"))
            add_label(it["id"], it["x"], it["y"], it["z"] + it["h"] + 0.2, 5, 0, coll,
                      mat("label", (0.1, 0.1, 0.1, 1)), name=f"LBL_{it['id']}")


def front_boxes(fi, stile=2.25, proud=0.6, kick=4.0):
    """Frame-and-panel door/drawer fronts on a cabinet's front face, plus bar pulls.

    fi["fronts"] = rows from the top, each [height, count]; height 0 shares what's left.
    """
    r = math.radians(fi.get("rot", 0))
    ex, ey = Vector((math.cos(r), math.sin(r), 0)), Vector((-math.sin(r), math.cos(r), 0))
    c = Vector((fi["x"], fi["y"], 0))
    z0 = fi.get("z", 0)
    zb, zt = (z0 + kick if z0 < 1 else z0), z0 + fi["h"]
    w, d = fi["w"], fi["d"]
    out = -ey  # front = local -Y
    fixed = sum(h for h, _ in fi["fronts"] if h)
    flex = [h for h, _ in fi["fronts"] if not h]
    share = (zt - zb - fixed) / max(len(flex), 1)

    def member(a, b, p, q, t, inset=0.0):
        o = c + ex * a + ey * (-d / 2) + out * inset + Z * p
        return (o, ex, out, Z, b - a, t, q - p)

    frames, pulls = [], []
    top = zt
    for h, n in fi["fronts"]:
        h = h or share
        bot = top - h
        pw = w / n
        for i in range(n):
            a, b = -w / 2 + i * pw, -w / 2 + (i + 1) * pw
            s = min(stile, pw / 4, h / 4)
            frames += [member(a, a + s, bot, top, proud), member(b - s, b, bot, top, proud),
                       member(a + s, b - s, top - s, top, proud), member(a + s, b - s, bot, bot + s, proud)]
            if h <= 12:  # drawer: horizontal bar centred
                pulls.append(member((a + b) / 2 - 3, (a + b) / 2 + 3, (bot + top) / 2 - 0.25, (bot + top) / 2 + 0.25, 0.6, proud))
            else:  # door: vertical bar near the meeting edge (or the right edge for a single door)
                xe = (b - 2.5) if (n == 1 or i == 0) else (a + 2.5)
                zc = top - 6 if z0 < 1 else bot + 6
                pulls.append(member(xe - 0.25, xe + 0.25, zc - 3, zc + 3, 0.6, proud))
        top = bot
    return frames, pulls


def _aabb(fi):
    """World (x0, x1, y0, y1) of an axis-aligned (rot multiple of 90) floor item."""
    sw = abs(round(math.cos(math.radians(fi.get("rot", 0)))))
    hw, hd = (fi["w"], fi["d"]) if sw else (fi["d"], fi["w"])
    return fi["x"] - hw / 2, fi["x"] + hw / 2, fi["y"] - hd / 2, fi["y"] + hd / 2


SINK_REVEAL = 0.25  # counter overhangs the bowl rim by this much (undermount "positive reveal")


def countertop_boxes(top, items):
    """Slab boxes for a countertop with rectangular holes over undermount sinks (world axis-aligned)."""
    x0, x1, y0, y1 = _aabb(top)
    z0, h = top.get("z", 0), top["h"]
    holes = []
    for s in items:
        if s["type"] != "sink":
            continue
        a0, a1, b0, b1 = _aabb(s)
        if a0 < x1 and a1 > x0 and b0 < y1 and b1 > y0:
            holes.append((a0 + SINK_REVEAL, a1 - SINK_REVEAL, b0 + SINK_REVEAL, b1 - SINK_REVEAL))
    return [(Vector((a0, b0, z0)), X, Y, Z, a1 - a0, b1 - b0, h)
            for a0, a1, b0, b1 in subtract_rects((x0, x1, y0, y1), holes)]


def build_sink(fi, coll, m):
    """Undermount single-bowl stainless sink (fi = bowl outside: w x d x h, z = bottom) and a gooseneck faucet
    centred behind it on the counter (the item's back, local +Y, faces the wall)."""
    x0, x1, y0, y1 = _aabb(fi)
    z0, h, wt = fi.get("z", 0), fi["h"], 0.12
    top = z0 + h
    boxes = [
        (Vector((x0, y0, z0)), X, Y, Z, x1 - x0, y1 - y0, wt),               # bottom
        (Vector((x0, y0, z0)), X, Y, Z, x1 - x0, wt, h),                     # walls
        (Vector((x0, y1 - wt, z0)), X, Y, Z, x1 - x0, wt, h),
        (Vector((x0, y0, z0)), X, Y, Z, wt, y1 - y0, h),
        (Vector((x1 - wt, y0, z0)), X, Y, Z, wt, y1 - y0, h),
        (Vector((x0 - 0.75, y0 - 0.75, top - wt)), X, Y, Z, x1 - x0 + 1.5, 0.75, wt),  # rim flange under the counter
        (Vector((x0 - 0.75, y1, top - wt)), X, Y, Z, x1 - x0 + 1.5, 0.75, wt),
        (Vector((x0 - 0.75, y0, top - wt)), X, Y, Z, 0.75, y1 - y0, wt),
        (Vector((x1, y0, top - wt)), X, Y, Z, 0.75, y1 - y0, wt),
    ]
    make_obj(f"FI_{fi['id']}", coll, boxes, mat(f"fi_{fi['id']}_ss", (0.74, 0.75, 0.77, 1), "steel"))
    make_obj(f"FI_{fi['id']}_drain", coll, cyl=((x0 + x1) / 2, (y0 + y1) / 2, z0 + wt, 1.75, 0.05),
             material=mat("sink_drain", (0.55, 0.56, 0.58, 1), "metal"))
    # faucet on whichever long side is nearer the wall behind (the item's back = local +Y)
    r = math.radians(fi.get("rot", 0))
    back = Vector((-math.sin(r), math.cos(r), 0))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half_d = (y1 - y0) / 2 if abs(back.y) > 0.5 else (x1 - x0) / 2
    base = Vector((cx, cy, 0)) + back * (half_d + 1.6)
    zc = top + 1.5  # counter surface (sink top + counter thickness)
    fm = mat("faucet_black", (0.03, 0.03, 0.03, 1), "black")
    reach = half_d + 1.6 - 2.0  # spout tip lands ~2in behind the bowl centre
    make_obj(f"FI_{fi['id']}_faucet", coll, cyl=(base.x, base.y, zc, 1.1, 13.5), material=fm)
    arm_o = Vector((base.x, base.y, 0)) - back * (reach / 2)
    make_obj(f"FI_{fi['id']}_spout", coll,
             [centered_box(arm_o.x, arm_o.y, zc + 12.4, *((0.9, reach + 1.1) if abs(back.y) > 0.5 else (reach + 1.1, 0.9)), 1.1)], fm)
    tip = Vector((base.x, base.y, 0)) - back * reach
    make_obj(f"FI_{fi['id']}_head", coll, cyl=(tip.x, tip.y, zc + 9.5, 0.6, 3.0), material=fm)
    lever = Vector((base.x, base.y, 0)) + Vector((back.y, -back.x, 0)) * 1.6
    make_obj(f"FI_{fi['id']}_lever", coll, cyl=(lever.x, lever.y, zc + 6.5, 0.3, 3.5), material=fm)


def build_floor_items(shop, coll):
    mats = {"tv": mat("tv", (0.05, 0.05, 0.06, 1))}
    default = mat("floor_item", (0.4, 0.65, 0.85, 1))
    for fi in shop["floor_items"]:
        z0 = fi.get("z", 0)
        kind = {"cabinet": "wood", "appliance": "steel", "countertop": "quartz", "backsplash": "tile",
                "shelf": "black", "tv": "black_gloss"}.get(fi["type"], "plain")
        m = mat(f"fi_{fi['id']}", tuple(fi["color"][:3]) + (1.0,), kind) if "color" in fi \
            else mats.get(fi["type"], default)
        rot = fi.get("rot", 0)
        r = math.radians(rot)
        front = -Vector((-math.sin(r), math.cos(r), 0))  # local -Y = the cabinet front (into the room)
        if fi["type"] == "sink":
            build_sink(fi, coll, m)
            continue
        if fi["type"] == "countertop":  # cut around any undermount sink below it
            make_obj(f"FI_{fi['id']}", coll, countertop_boxes(fi, shop["floor_items"]), m)
            continue
        if fi["type"] == "cabinet" and z0 < 1 and fi.get("fronts"):  # base: carcass on a recessed 4in toe kick
            kc = Vector((fi["x"], fi["y"], 0)) - front * 1.5  # 3in-deep recess at the front
            boxes = [centered_box(fi["x"], fi["y"], 4, fi["w"], fi["d"], fi["h"] - 4, rot)]
            x0, x1, y0, y1 = _aabb(fi)
            sink = next((s for s in shop["floor_items"] if s["type"] == "sink"
                         and x0 <= s["x"] <= x1 and y0 <= s["y"] <= y1), None)
            if sink:  # open-topped carcass below the bowl: solid to the bowl bottom, 3/4in walls above it
                zs, wt, top = sink.get("z", 0) - 0.5, 0.75, fi["h"]
                boxes = [(Vector((x0, y0, 4)), X, Y, Z, x1 - x0, y1 - y0, zs - 4),
                         (Vector((x0, y0, zs)), X, Y, Z, x1 - x0, wt, top - zs),
                         (Vector((x0, y1 - wt, zs)), X, Y, Z, x1 - x0, wt, top - zs),
                         (Vector((x0, y0, zs)), X, Y, Z, wt, y1 - y0, top - zs),
                         (Vector((x1 - wt, y0, zs)), X, Y, Z, wt, y1 - y0, top - zs)]
            make_obj(f"KICK_{fi['id']}", coll, [centered_box(kc.x, kc.y, 0, fi["w"], fi["d"] - 3, 4, rot)],
                     mat("toe_kick", (0.05, 0.05, 0.05, 1), "black"))
        else:
            boxes = [centered_box(fi["x"], fi["y"], z0, fi["w"], fi["d"], fi["h"], rot)]
        if fi["type"] == "cabinet" and z0 >= 30 and fi.get("fronts"):  # wall cabinet: crown on top
            cc = Vector((fi["x"], fi["y"], 0)) + front * 0.75  # overhangs 1.5in at the front
            boxes.append(centered_box(cc.x, cc.y, z0 + fi["h"], fi["w"] + 3, fi["d"] + 1.5, 2.5, rot))
        pulls = []
        if fi.get("fronts"):
            fb, pulls = front_boxes(fi)
            boxes += fb
        make_obj(f"FI_{fi['id']}", coll, boxes, m)
        if pulls:
            make_obj(f"PULL_{fi['id']}", coll, pulls, mat("pull", (0.03, 0.03, 0.03, 1), "black"))
        if fi["type"] in ("countertop", "backsplash", "shelf") or fi.get("z", 0) >= 50:
            continue  # label only the floor-standing parts
        add_label(fi.get("name", fi["id"]), fi["x"], fi["y"], z0 + fi["h"] + 0.2, 3, fi.get("rot", 0), coll,
                  mat("label", (0.1, 0.1, 0.1, 1)), name=f"LBL_{fi['id']}")


# ------------------------------------------------------------------- inventory
def asset_helpers():
    return {"mat": mat, "make_obj": make_obj, "centered_box": centered_box}


def build_inventory(shop, inv, layout, inv_coll, clr_coll, use_assets=True):
    items = {i["id"]: i for i in inv["items"]}
    label_m = mat("label", (0.1, 0.1, 0.1, 1))
    clr_m = mat("clearance", (1.0, 0.55, 0.1, 0.18))
    for iid, pl in layout["placements"].items():
        if iid not in items:
            print(f"WARNING: placement '{iid}' not in inventory.json - skipped")
            continue
        it = items[iid]
        z0 = pl.get("z", 0)
        rot = pl.get("rot", 0)
        w, d, h, cl = C.effective_dims(it, pl)
        objs = None
        if use_assets:
            objs = A.load_asset(C.ROOT, it, inv_coll, f"INV_{iid}", asset_helpers(), state=pl.get("state", "open"))
        if objs:
            A.place(objs, pl["x"], pl["y"], z0, rot)
        else:
            make_obj(f"INV_{iid}", inv_coll, [centered_box(pl["x"], pl["y"], z0, w, d, h, rot)],
                     mat(f"inv_{iid}", item_color(iid)))
        name = it["name"] + (" (folded)" if pl.get("state") == "folded" else "")
        size = max(2.5, min(8, min(w, d) / 5))
        add_label(name, pl["x"], pl["y"], z0 + h + 0.3, size, rot + (90 if d > w * 1.5 else 0),
                  inv_coll, label_m, name=f"LBL_{iid}")
        _, (cx, cy, cw, cd, crot) = C.item_rects(it, pl)
        make_obj(f"CLR_{iid}", clr_coll, [centered_box(cx, cy, z0, cw, cd, h + cl.get("top", 0), crot)], clr_m,
                 transparent=True)
        if iid == "printer-3d":
            # 4.5-in galvanized exhaust duct from back of 3D printer up and over along W-S to VENT-S1 (x=367.1, z=99.25)
            vent = next((w_ for w_ in shop["wall_items"] if w_["id"] == "VENT-S1"), None)
            if vent:
                L_ = C.shell_dims(shop)[0]
                vx = L_ - vent["offset"]
                vz = vent["z"] + vent["h"] / 2.0
                px_d = pl["x"] + (7.5 if abs(rot - 180) < 10 else -7.5)
                py_back = max(2.5, pl["y"] - d / 2.0)
                z_start = z0 + 15.0
                duct_boxes = [
                    centered_box(px_d, (py_back + 2.5) / 2.0, z_start - 2.1, 4.2, abs(py_back - 2.5) + 4.2, 4.2),
                    centered_box(px_d, 2.5, z_start, 4.2, 4.2, max(4.0, vz + 2.1 - z_start)),
                    centered_box((px_d + vx) / 2.0, 2.5, vz - 2.1, abs(px_d - vx) + 4.2, 4.2, 4.2),
                ]
                make_obj("INV_printer-3d_exhaust_duct", inv_coll, duct_boxes,
                         mat("printer_duct", (0.72, 0.75, 0.78, 1), "metal"))


# ------------------------------------------------------------------- reference
def build_reference(shop, coll):
    L, W, H = C.shell_dims(shop)
    label_m = mat("label", (0.1, 0.1, 0.1, 1))
    zone_m = {"activity": mat("zone_activity", (0.3, 0.5, 0.95, 0.22)),
              "keep_clear": mat("zone_keep_clear", (0.9, 0.25, 0.25, 0.3))}
    for z in shop["zones"]:
        make_obj(f"ZONE_{z['id']}", coll,
                 [(Vector((z["x"], z["y"], 0.05)), X, Y, Z, z["w"], z["d"], 0.1)], zone_m[z["kind"]], transparent=True)
        add_label(z["name"].split(" (")[0], z["x"] + z["w"] / 2, z["y"] + z["d"] / 2, 0.3,
                  min(10, z["w"] / max(len(z["name"].split(" (")[0]), 1) * 1.6), 0, coll, label_m,
                  name=f"LBL_ZONE_{z['id']}")
    env_m = mat("door_envelope", (0.6, 0.3, 0.85, 0.2))
    for wi in shop["wall_items"]:  # space an open overhead door occupies under its ceiling tracks
        if wi["kind"] != "overhead_door":
            continue
        (ox, oy), (dx, dy), (nx, ny), _ = C.wall_frame(wi["wall"], L, W)
        a0, a1 = C.wall_item_span(wi)
        depth = wi.get("open_depth", wi["h"] + 18)
        o = Vector((ox + dx * a0, oy + dy * a0, wi["z"] + wi["h"]))
        make_obj(f"ENV_{wi['id']}", coll, [(o, Vector((dx, dy, 0)), Vector((nx, ny, 0)), Z, a1 - a0, depth, 14)],
                 env_m, transparent=True)
    for wall, (x, y) in (("W-S", (L / 2, -30)), ("W-N", (L / 2, W + 30)), ("W-E", (L + 40, W / 2)), ("W-W", (-40, W / 2))):
        add_label(wall, x, y, 0.3, 14, 0, coll, label_m, name=f"LBL_{wall}")
    for name, vec, col in (("AXIS_X", X, (0.9, 0.1, 0.1, 1)), ("AXIS_Y", Y, (0.1, 0.7, 0.1, 1)), ("AXIS_Z", Z, (0.1, 0.2, 0.9, 1))):
        ex, ey, ez = (X, Y, Z) if vec is X else (Y, X, Z) if vec is Y else (Z, X, Y)
        make_obj(name, coll, [(Vector((0, 0, 0)), ex, ey, ez, 24, 1.5, 1.5)], mat(name, col))


def point_cloud_display(o, size):
    """Make a vertex-only PLY renderable: a small cube per point (geometry nodes) with an unlit material
    reading the per-point 'Col' attribute. Workbench ignores colour attributes after geometry nodes, so
    scan_views renders points with EEVEE; size is in the object's local (source) units."""
    ng = bpy.data.node_groups.new(f"PTS_{o.name}", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = ng.nodes, ng.links
    gi, go = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")
    cube = nodes.new("GeometryNodeMeshCube")
    cube.inputs["Size"].default_value = (size, size, size)
    iop, real, setm = (nodes.new("GeometryNodeInstanceOnPoints"), nodes.new("GeometryNodeRealizeInstances"),
                       nodes.new("GeometryNodeSetMaterial"))
    m = bpy.data.materials.get("scan_points") or bpy.data.materials.new("scan_points")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    at, em, out = nt.nodes.new("ShaderNodeAttribute"), nt.nodes.new("ShaderNodeEmission"), nt.nodes.new("ShaderNodeOutputMaterial")
    at.attribute_name = "Col"
    nt.links.new(at.outputs["Color"], em.inputs["Color"])
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    m.diffuse_color = (0.6, 0.6, 0.6, 1)
    setm.inputs["Material"].default_value = m
    links.new(gi.outputs[0], iop.inputs["Points"])
    links.new(cube.outputs[0], iop.inputs["Instance"])
    links.new(iop.outputs[0], real.inputs[0])
    links.new(real.outputs[0], setm.inputs[0])
    links.new(setm.outputs[0], go.inputs[0])
    o.modifiers.new("points", "NODES").node_group = ng


def build_scans(shop, ref_coll):
    """Import reference scans (glb/gltf/obj/usd*) into Reference/Scan, aligned per space.json."""
    scans = [s for s in shop.get("reference_scans", []) if s.get("enabled", True)]
    if not scans:
        return
    sc = bpy.data.collections.new("Scan")
    ref_coll.children.link(sc)
    vl = bpy.context.view_layer
    vl.active_layer_collection = vl.layer_collection.children[ref_coll.name].children["Scan"]
    to_in = {"m": 1 / 0.0254, "cm": 1 / 2.54, "mm": 1 / 25.4, "in": 1.0}
    units = bpy.context.scene.unit_settings
    saved_scale = units.scale_length
    units.scale_length = 1.0  # importers would otherwise convert to scene units themselves (double scaling)
    for s in scans:
        path = C.ROOT / s["file"]
        if not path.exists():
            print(f"WARNING: scan file missing: {path}")
            continue
        before = set(bpy.data.objects)
        ext = path.suffix.lower()
        if ext in (".glb", ".gltf"):
            bpy.ops.import_scene.gltf(filepath=str(path))
        elif ext == ".obj":
            bpy.ops.wm.obj_import(filepath=str(path), forward_axis="NEGATIVE_Z", up_axis="Y")
        elif ext in (".usd", ".usda", ".usdc", ".usdz"):
            bpy.ops.wm.usd_import(filepath=str(path))
        elif ext == ".ply":
            bpy.ops.wm.ply_import(filepath=str(path))
        else:
            print(f"WARNING: unsupported scan format: {path}")
            continue
        unit = to_in[s.get("source_units", "m")]
        xf = (Matrix.Translation(Vector(s.get("location", (0, 0, 0))))
              @ Matrix.Rotation(math.radians(s.get("rot_z", 0)), 4, "Z")
              @ Matrix.Scale(unit, 4))
        kind = s.get("kind", "points" if ext == ".ply" else "mesh")
        for o in [o for o in bpy.data.objects if o not in before]:
            if o.parent is None:
                o.matrix_world = xf @ o.matrix_world
            o.name = f"SCAN_{s['id']}_{o.name}"
            o["scan_kind"] = kind
            if kind == "points" and o.type == "MESH":
                point_cloud_display(o, s.get("point_size", 1.25) / unit)
        print(f"SCAN imported: {path.name}")
    units.scale_length = saved_scale
    vl.active_layer_collection = vl.layer_collection


# ------------------------------------------------------------------------ main
def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--layout", default="none")
    ap.add_argument("--no-scan", action="store_true", help="skip importing reference scans (smaller .blend)")
    ap.add_argument("--no-assets", action="store_true", help="draw every inventory item as a box (ignore item assets)")
    args = ap.parse_args(argv)

    shop = C.load(C.ROOT / "data" / "space.json")
    inv = C.load(C.ROOT / "data" / "inventory.json")
    lp = C.layout_path(args.layout)
    layout = C.load(lp) if lp else None
    name = C.layout_name(args.layout)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "IMPERIAL"
    scene.unit_settings.scale_length = 0.0254  # 1 BU = 1 inch
    scene.unit_settings.length_unit = "INCHES"
    scene.world = bpy.data.worlds.new("World")
    scene.world.color = (0.93, 0.94, 0.96)

    colls = {}
    for cname in ("Shell", "Fixed", "Inventory", "Clearances", "Reference"):
        colls[cname] = bpy.data.collections.new(cname)
        scene.collection.children.link(colls[cname])

    build_shell(shop, colls["Shell"])
    build_interior_walls(shop, colls["Fixed"])
    build_wall_items(shop, colls["Fixed"])
    build_ceiling_items(shop, colls["Fixed"])
    build_floor_items(shop, colls["Fixed"])
    build_reference(shop, colls["Reference"])
    if not args.no_scan:
        build_scans(shop, colls["Reference"])
    if layout:
        build_inventory(shop, inv, layout, colls["Inventory"], colls["Clearances"], not args.no_assets)

    out = C.ROOT / "blend" / f"{name}.blend"
    out.parent.mkdir(exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    n = sum(len(c.objects) for c in colls.values())
    print(f"BUILD OK: layout={name} objects={n} -> {out}")


if __name__ == "__main__":
    main()
