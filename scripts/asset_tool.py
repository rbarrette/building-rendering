"""Make and check per-item 3D assets (runs inside Blender). Contract: scripts/assets.py, prompts/item-asset.md.

  import   a vendor/downloaded model or an item scan -> assets/items/<id>/<id>.glb (item-local frame, joined, decimated)
           Scans: add --scan [--crop=x0,x1,y0,y1] [--texture-max 2048] (levels + cuts the floor, drops scraps).
           Blender --background --python scripts/asset_tool.py -- import --item example-rack \
               --src reference/items/example-rack/model/vendor-model.glb --square --rot 90 \
               [--units m|cm|mm|in] [--drop REGEX ...] [--recolor 'MATREGEX=#RRGGBB' ...] [--max-tris 80000]
           Writes import.json (the exact arguments, so the asset can be rebuilt) and then runs `preview`.
  preview  front / right side / top / 3-4 view sheet of the asset with the inventory w x d x h box (orange
           wireframe), a 12in floor grid and a red FRONT arrow on the -Y side -> assets/items/<id>/preview.png,
           plus asset.json (measured bbox, tris, sha256) that `make validate` checks.
           Blender --background --python scripts/asset_tool.py -- preview --item example-rack [--path FILE]

Make: `make asset-import ITEM=.. SRC=.. ARGS="..."`, `make asset-preview ITEM=..`.
"""
import argparse
import datetime
import hashlib
import json
import math
import re
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import assets as A  # noqa: E402
import build_scene as B  # noqa: E402  (main() is guarded; we only borrow its helpers)

UNITS = {"m": 1 / 0.0254, "cm": 1 / 2.54, "mm": 1 / 25.4, "in": 1.0}


def item_dir(iid):
    return C.ROOT / "assets" / "items" / iid


def get_item(iid):
    inv = C.load(C.ROOT / "data" / "inventory.json")
    for it in inv["items"]:
        if it["id"] == iid:
            return it
    sys.exit(f"ERROR: no inventory item '{iid}'")


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    B._mats.clear()
    s = bpy.context.scene
    s.unit_settings.system = "IMPERIAL"
    s.unit_settings.scale_length = 0.0254
    s.unit_settings.length_unit = "INCHES"
    return s


def rel(p):
    try:
        return str(Path(p).resolve().relative_to(C.ROOT))
    except ValueError:
        return str(p)


# ---------------------------------------------------------------------- import
def ancestors(o):
    names = []
    while o:
        names.append(o.name)
        o = o.parent
    return names


def square_angle(objs):
    """Yaw (deg, 0..90) that minimises the XY bounding-box area, from a vertex sample."""
    pts = [o.matrix_world @ v.co for o in objs for v in o.data.vertices]
    step = max(1, len(pts) // 40000)
    pts = [(p.x, p.y) for p in pts[::step]]
    best = (1e30, 0.0)
    for i in range(0, 360):
        a = math.radians(i * 0.25)
        c, s = math.cos(a), math.sin(a)
        xs = [x * c - y * s for x, y in pts]
        ys = [x * s + y * c for x, y in pts]
        best = min(best, ((max(xs) - min(xs)) * (max(ys) - min(ys)), i * 0.25))
    return best[1]


# ------------------------------------------------------------ scan cleanup
# Phone/LiDAR/photogrammetry scans of one item (prompts/item-scan.md). All of these work on ONE joined mesh,
# in inches, before squaring. They are deterministic, so re-running with the same args gives the same frame.
def _verts(ob):
    import numpy as np
    co = np.empty(len(ob.data.vertices) * 3, dtype=np.float64)
    ob.data.vertices.foreach_get("co", co)
    return co.reshape(-1, 3)


def merge_close(ob, dist):
    """Weld duplicate vertices (glTF splits them at UV seams), so loose-part detection sees real islands."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    n0 = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=dist)
    n1 = len(bm.verts)
    bm.to_mesh(ob.data)
    bm.free()
    print(f"SCAN: welded {n0 - n1} duplicate verts (within {dist} in)")


def level_floor(ob, max_tilt=20.0, tol=0.6, low_frac=0.35, min_frac=0.03, iters=600):
    """Find the floor plane under the item (RANSAC on the lowest vertices), rotate it flat and put it at z=0.
    Returns a dict describing the fit, or None if there is no clear floor (e.g. the app already removed it)."""
    import numpy as np
    P = _verts(ob)
    if len(P) < 50:
        return None
    rng = np.random.default_rng(0)
    low = P[P[:, 2] <= np.quantile(P[:, 2], low_frac)]
    S = low if len(low) <= 30000 else low[rng.choice(len(low), 30000, replace=False)]
    cos_max = math.cos(math.radians(max_tilt))
    best = (0, None, None)
    for _ in range(iters):
        p = S[rng.choice(len(S), 3, replace=False)]
        n = np.cross(p[1] - p[0], p[2] - p[0])
        ln = np.linalg.norm(n)
        if ln < 1e-9:
            continue
        n = n / ln
        if n[2] < 0:
            n = -n
        if n[2] < cos_max:
            continue
        cnt = int((np.abs((S - p[0]) @ n) < tol).sum())
        if cnt > best[0]:
            best = (cnt, n, p[0])
    if best[1] is None:
        return None
    n, p0 = best[1], best[2]
    inl = P[np.abs((P - p0) @ n) < tol]
    c = inl.mean(axis=0)  # refine: least-squares plane through the inliers
    n = np.linalg.svd(inl - c)[2][2]
    if n[2] < 0:
        n = -n
    frac = len(inl) / len(P)
    below = float(((P - c) @ n < -3 * tol).mean())
    if frac < min_frac or below > 0.02:
        print(f"SCAN: no clear floor plane (best {frac:.1%} of verts, {below:.1%} below it) - not levelling")
        return None
    R = Vector(n.tolist()).rotation_difference(Vector((0, 0, 1))).to_matrix().to_4x4()
    zc = (R @ Vector(c.tolist())).z
    ob.data.transform(Matrix.Translation((0, 0, -zc)) @ R)
    tilt = math.degrees(math.acos(min(1.0, float(n[2]))))
    print(f"SCAN: floor plane found ({frac:.1%} of verts), tilt {tilt:.2f} deg -> levelled to z=0")
    return {"tilt_deg": round(tilt, 2), "inlier_frac": round(frac, 4)}


def cut_planes(ob, planes, what):
    """Cut the mesh along each plane (point, normal) and delete what lies on the normal's side.
    Bisecting (rather than deleting vertices) keeps faces that cross the plane, so legs keep their length."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    n0 = len(bm.verts)
    for co, no in planes:
        geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-4, plane_co=co, plane_no=no, clear_outer=True)
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    n1 = len(bm.verts)
    bm.to_mesh(ob.data)
    bm.free()
    print(f"SCAN: cut {what} ({n0} -> {n1} verts)")
    if not ob.data.vertices:
        sys.exit(f"ERROR: nothing left after {what}")


def drop_islands(ob, min_frac):
    """Delete loose parts with fewer faces than min_frac x the biggest part (floor scraps, clutter, floaters)."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    seen, islands = set(), []
    for f in bm.faces:
        if f.index in seen:
            continue
        stack, isl = [f], []
        seen.add(f.index)
        while stack:
            g = stack.pop()
            isl.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h.index not in seen:
                        seen.add(h.index)
                        stack.append(h)
        islands.append(isl)
    if len(islands) <= 1:
        bm.free()
        print("SCAN: 1 connected part - nothing to drop")
        return
    biggest = max(len(i) for i in islands)
    small = [i for i in islands if len(i) < min_frac * biggest]
    faces = [f for i in small for f in i]
    bmesh.ops.delete(bm, geom=faces, context="FACES")
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(ob.data)
    bm.free()
    print(f"SCAN: {len(islands)} parts; dropped {len(small)} under {min_frac:.0%} of the biggest ({len(faces)} faces)")


def scan_materials(ob):
    """Scans bake the light into the texture: make each material a matte Principled BSDF fed by its image
    (glTF 'unlit' scans import without a BSDF), so photo renders don't add a second sheen on top."""
    for m in {s.material for s in ob.material_slots if s.material}:
        if not m.node_tree:
            continue
        nt = m.node_tree
        tex = next((n for n in nt.nodes if n.type == "TEX_IMAGE"), None)
        bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
        if bsdf is None and out is not None:
            bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
            for l in list(out.inputs["Surface"].links):
                nt.links.remove(l)
            nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
            if tex is not None:
                nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
            print(f"SCAN: material '{m.name}' was unlit -> matte BSDF")
        if bsdf is not None:
            bsdf.inputs["Roughness"].default_value = 0.85
            if "Specular IOR Level" in bsdf.inputs:
                bsdf.inputs["Specular IOR Level"].default_value = 0.2
            bsdf.inputs["Metallic"].default_value = 0.0


def shrink_textures(max_px):
    for im in bpy.data.images:
        w, h = im.size
        if max(w, h) > max_px:
            k = max_px / max(w, h)
            im.scale(max(1, round(w * k)), max(1, round(h * k)))
            print(f"SCAN: texture '{im.name}' {w}x{h} -> {im.size[0]}x{im.size[1]}")


def parse_crop(s):
    v = [float(t) for t in s.split(",")]
    if len(v) not in (4, 6):
        sys.exit("ERROR: --crop wants x0,x1,y0,y1 or x0,x1,y0,y1,z0,z1 (inches, item frame)")
    return v + ([-1e9, 1e9] if len(v) == 4 else [])


def cmd_import(a):
    src = (C.ROOT / a.src) if not Path(a.src).is_absolute() else Path(a.src)
    if not src.exists():
        sys.exit(f"ERROR: source not found: {src}")
    reset_scene()
    units = bpy.context.scene.unit_settings
    saved_scale = units.scale_length
    units.scale_length = 1.0  # keep importers in raw source units; we scale by UNITS[a.units] below
    ext = src.suffix.lower()
    try:
        if ext in (".glb", ".gltf"):
            bpy.ops.import_scene.gltf(filepath=str(src))
        elif ext == ".obj":
            bpy.ops.wm.obj_import(filepath=str(src))
        elif ext == ".fbx":
            bpy.ops.import_scene.fbx(filepath=str(src))
        elif ext in (".usdz", ".usd", ".usdc", ".usda"):
            bpy.ops.wm.usd_import(filepath=str(src))
        else:
            sys.exit(f"ERROR: unsupported source type {ext}")
    finally:
        units.scale_length = saved_scale
    drops = [re.compile(r) for r in a.drop]
    meshes, dropped = [], 0
    for o in list(bpy.data.objects):
        if o.type == "MESH" and not any(r.search(n) for r in drops for n in ancestors(o)):
            meshes.append(o)
        elif o.type == "MESH":
            dropped += 1
    k = UNITS[a.units] * a.scale
    for o in meshes:  # bake hierarchy + units into each mesh
        o.data = o.data.copy()  # instanced meshes: make single-user before transforming
        mw = o.matrix_world.copy()
        o.data.transform(Matrix.Scale(k, 4) @ mw)
        if mw.determinant() < 0:
            o.data.flip_normals()
    for o in [o for o in bpy.data.objects if o not in meshes]:
        bpy.data.objects.remove(o)
    for o in meshes:
        o.parent = None
        o.matrix_world = Matrix.Identity(4)
    print(f"IMPORT: {len(meshes)} meshes kept, {dropped} dropped by --drop")
    if not meshes:
        sys.exit("ERROR: nothing left to import")

    for spec in a.recolor:
        pat, hx = spec.rsplit("=", 1)
        r = re.compile(pat)
        for m in bpy.data.materials:
            if r.search(m.name) and m.node_tree:
                bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
                if bsdf:
                    for l in list(bsdf.inputs["Base Color"].links):
                        m.node_tree.links.remove(l)
                    bsdf.inputs["Base Color"].default_value = A.hexrgba(hx)
                    print(f"RECOLOR: material '{m.name}' -> {hx}")

    for o in bpy.context.selected_objects:
        o.select_set(False)
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = ob.data.name = a.item

    floor = None
    if a.scan:  # one-item scan: weld, level on the floor plane, cut the floor, drop scraps, matte materials
        merge_close(ob, 0.02)
        if a.floor == "auto":
            floor = level_floor(ob)
            if floor:
                cut = a.floor_cut
                cut_planes(ob, [((0, 0, cut), (0, 0, -1))], f"floor: below z {cut} in")
                floor["cut_in"] = cut
        if a.min_island > 0:
            drop_islands(ob, a.min_island)
        scan_materials(ob)
    if a.texture_max:
        shrink_textures(a.texture_max)

    sq = square_angle([ob]) if a.square else 0.0
    yaw = sq + a.rot
    ob.data.transform(Matrix.Rotation(math.radians(yaw), 4, "Z"))

    def recentre():
        mn, mx = A.bbox([ob])
        z = 0.0 if floor else -mn.z  # a levelled scan keeps its floor at z=0 (legs lost ~floor_cut in, not height)
        ob.data.transform(Matrix.Translation((-(mn.x + mx.x) / 2, -(mn.y + mx.y) / 2, z)))
    recentre()
    if a.crop:
        x0, x1, y0, y1, z0, z1 = parse_crop(a.crop)
        planes = [((x0, 0, 0), (-1, 0, 0)), ((x1, 0, 0), (1, 0, 0)), ((0, y0, 0), (0, -1, 0)), ((0, y1, 0), (0, 1, 0))]
        if z0 > -1e8:
            planes += [((0, 0, z0), (0, 0, -1)), ((0, 0, z1), (0, 0, 1))]
        cut_planes(ob, planes, f"crop {a.crop}")
        recentre()

    tris = A.tri_count([ob])
    if a.max_tris and tris > a.max_tris:
        mod = ob.modifiers.new("decimate", "DECIMATE")
        mod.ratio = a.max_tris / tris
        bpy.ops.object.modifier_apply(modifier=mod.name)
        print(f"DECIMATE: {tris} -> {A.tri_count([ob])} tris")
    mn, mx = A.bbox([ob])
    size = mx - mn
    size.z = mx.z - min(mn.z, 0.0)
    print(f"IMPORT: yaw {yaw:.2f} deg (square {sq:.2f} + rot {a.rot}); bbox w {size.x:.1f} x d {size.y:.1f} x h {size.z:.1f} in")

    out_dir = item_dir(a.item)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{a.item}.glb"
    ob.data.transform(Matrix.Scale(0.0254, 4))  # glTF is metres
    bpy.ops.export_scene.gltf(filepath=str(out), export_format="GLB", use_selection=True, export_yup=True,
                              export_apply=True, export_cameras=False, export_lights=False)
    (out_dir / "import.json").write_text(json.dumps({
        "item": a.item, "src": rel(src), "units": a.units, "scale": a.scale, "square": a.square, "square_deg": round(sq, 2),
        "rot": a.rot, "yaw_deg": round(yaw, 2), "drop": a.drop, "recolor": a.recolor, "max_tris": a.max_tris,
        "scan": a.scan, "floor": floor if a.scan else None, "min_island": a.min_island if a.scan else None,
        "crop": a.crop, "texture_max": a.texture_max,
        "out": rel(out), "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "argv": sys.argv[sys.argv.index("--") + 1:],
    }, indent=1) + "\n")
    print(f"EXPORTED {out}")
    cmd_preview(argparse.Namespace(item=a.item, path=rel(out), size=a.size))


# --------------------------------------------------------------------- preview
def edge_boxes(w, d, h, t):
    """12 thin boxes along the edges of a w x d x h box centred on the origin, z 0..h."""
    out = []
    for y in (-d / 2, d / 2):
        for z in (0, h):
            out.append(B.centered_box(0, y, z - t / 2, w + t, t, t))
    for x in (-w / 2, w / 2):
        for z in (0, h):
            out.append(B.centered_box(x, 0, z - t / 2, t, d + t, t))
    for x in (-w / 2, w / 2):
        for y in (-d / 2, d / 2):
            out.append(B.centered_box(x, y, 0, t, t, h))
    return out


def arrow(coll, y0, size, material):
    me = bpy.data.meshes.new("FRONT_arrow")
    s = size
    verts = [(-s * 0.25, y0, 0.2), (s * 0.25, y0, 0.2), (s * 0.25, y0 - s, 0.2), (s * 0.6, y0 - s, 0.2),
             (0, y0 - s * 1.7, 0.2), (-s * 0.6, y0 - s, 0.2), (-s * 0.25, y0 - s, 0.2)]
    me.from_pydata(verts, [], [list(range(7))])
    me.materials.append(material)
    ob = bpy.data.objects.new("FRONT_arrow", me)
    coll.objects.link(ob)
    B.add_label("FRONT (-Y)", 0, y0 - s * 2.3, 0.3, max(3, s * 0.45), 0, coll, material, name="FRONT_lbl")


def stitch(paths, out, cols=2):
    import numpy as np
    imgs = []
    for p in paths:
        im = bpy.data.images.load(str(p))
        w, h = im.size
        imgs.append(np.array(im.pixels[:], dtype=np.float32).reshape(h, w, 4))
        bpy.data.images.remove(im)
    rows = [np.concatenate(imgs[i:i + cols], axis=1) for i in range(0, len(imgs), cols)]
    sheet = np.concatenate(rows[::-1], axis=0)  # Blender pixels are bottom-up: first row goes on top
    h, w = sheet.shape[:2]
    im = bpy.data.images.new("sheet", w, h, alpha=True)
    im.pixels = sheet.ravel()
    im.filepath_raw = str(out)
    im.file_format = "PNG"
    im.save()
    for p in paths:
        Path(p).unlink(missing_ok=True)


def cmd_preview(a):
    it = get_item(a.item)
    if a.path:
        it = dict(it, asset=dict(it.get("asset") or {}, path=a.path))
    path = A.asset_file(C.ROOT, it)
    if path is None or not path.exists():
        sys.exit(f"ERROR: {a.item} has no asset file (inventory asset.path or --path): {path}")
    scene = reset_scene()
    coll = bpy.data.collections.new("Asset")
    scene.collection.children.link(coll)
    objs = A.load_asset(C.ROOT, it, coll, f"INV_{a.item}", B.asset_helpers())
    if not objs:
        sys.exit("ERROR: asset loaded no objects")
    mn, mx = A.bbox(objs)
    size = mx - mn
    size.z = mx.z - min(mn.z, 0.0)  # height above the floor (a levelled scan's floor cut leaves the legs at ~0.4 in)
    w, d, h = it["w"], it["d"], it["h"]
    span = max(w, d, h, size.x, size.y, size.z)

    guide = bpy.data.collections.new("Guides")
    scene.collection.children.link(guide)
    orange = B.mat("guide_box", (1.0, 0.45, 0.05, 1))
    red = B.mat("guide_front", (0.85, 0.05, 0.05, 1))
    grid_m = B.mat("guide_grid", (0.55, 0.55, 0.58, 1))
    floor_m = B.mat("guide_floor", (0.86, 0.86, 0.88, 1))
    B.make_obj("GUIDE_box", guide, edge_boxes(w, d, h, max(0.35, span / 250)), orange)
    ext = math.ceil((max(w, d, size.x, size.y) / 2 + span * 0.35) / 12) * 12
    B.make_obj("GUIDE_floor", guide, [B.centered_box(0, 0, -0.6, 2 * ext, 2 * ext, 0.5)], floor_m)
    lines = [B.centered_box(0, v, -0.1, 2 * ext, 0.25, 0.1) for v in range(-ext, ext + 1, 12)]
    lines += [B.centered_box(v, 0, -0.1, 0.25, 2 * ext, 0.1) for v in range(-ext, ext + 1, 12)]
    B.make_obj("GUIDE_grid", guide, lines, grid_m)
    arrow(guide, -max(d, size.y) / 2 - 3, max(6, span / 10), red)

    scene.render.engine = "BLENDER_WORKBENCH"
    sh = scene.display.shading
    sh.light, sh.color_type = "STUDIO", "MATERIAL"
    sh.show_object_outline = True
    sh.show_cavity = True
    scene.world = bpy.data.worlds.new("W")
    scene.world.color = (1, 1, 1)
    scene.render.resolution_x = scene.render.resolution_y = a.size
    scene.render.image_settings.file_format = "PNG"

    c = Vector((0, 0, max(h, size.z) / 2))
    dist = span * 6
    views = [("front", Vector((0, -1, 0)), "ORTHO"), ("right", Vector((1, 0, 0)), "ORTHO"),
             ("top", Vector((0, 0, 1)), "ORTHO"), ("iso", Vector((-0.8, -1.2, 0.85)).normalized(), "ORTHO")]
    out_dir = item_dir(a.item)
    out_dir.mkdir(parents=True, exist_ok=True)
    shots = []
    for name, dvec, kind in views:
        cd = bpy.data.cameras.new(f"CAM_{name}")
        cd.type = kind
        cd.ortho_scale = span * (1.35 if name != "top" else 1.25) + (24 if name == "top" else 0)
        cd.clip_start, cd.clip_end = 1, dist * 3
        cam = bpy.data.objects.new(f"CAM_{name}", cd)
        scene.collection.objects.link(cam)
        target = Vector((0, -6, 0)) if name == "top" else c  # top view: leave room for the arrow
        cam.location = target + dvec * dist
        up = "Y" if name != "top" else "Y"
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", up).to_euler()
        scene.camera = cam
        p = out_dir / f"_view-{name}.png"
        scene.render.filepath = str(p)
        bpy.ops.render.render(write_still=True)
        shots.append(p)
    sheet = out_dir / "preview.png"
    stitch(shots, sheet)

    diff = {"w": round(size.x - w, 2), "d": round(size.y - d, 2), "h": round(size.z - h, 2)}
    info = {
        "item": a.item, "path": rel(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bbox_in": {"w": round(size.x, 2), "d": round(size.y, 2), "h": round(size.z, 2)},
        "min_in": [round(v, 2) for v in mn], "max_in": [round(v, 2) for v in mx],
        "inventory_in": {"w": w, "d": d, "h": h}, "diff_in": diff,
        "tris": A.tri_count(objs), "objects": len(objs),
        "materials": sorted({m.name for o in objs if o.type == "MESH" for m in o.data.materials if m}),
        "preview": rel(sheet), "sheet_layout": "top-left front (from -Y), top-right right side (from +X), "
                                               "bottom-left top (north up), bottom-right 3/4 from front-left",
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    (out_dir / "asset.json").write_text(json.dumps(info, indent=1) + "\n")
    print(f"PREVIEW {sheet}")
    print(f"BBOX w {size.x:.1f} d {size.y:.1f} h {size.z:.1f} in vs inventory {w} x {d} x {h}  (diff {diff})")
    off = abs((mn.x + mx.x) / 2) + abs((mn.y + mx.y) / 2) + abs(mn.z)
    if off > 0.5:
        print(f"WARNING: asset is not centred on the footprint / floor (min {tuple(round(v, 1) for v in mn)})")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="asset_tool.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("import")
    pi.add_argument("--item", required=True)
    pi.add_argument("--src", required=True)
    pi.add_argument("--units", choices=sorted(UNITS), default="m", help="source units (glTF = m)")
    pi.add_argument("--scale", type=float, default=1.0,
                    help="extra uniform scale after --units (scans: tape / scan, when a tape check says the scale is off)")
    pi.add_argument("--square", action="store_true", help="auto-rotate so the footprint is axis-aligned")
    pi.add_argument("--rot", type=float, default=0.0, help="extra yaw (deg CCW) after --square, to put the front at -Y")
    pi.add_argument("--drop", action="append", default=[], help="regex on object (or parent) names to delete")
    pi.add_argument("--recolor", action="append", default=[], help="'MATERIAL_REGEX=#RRGGBB'")
    pi.add_argument("--max-tris", type=int, default=80000)
    pi.add_argument("--scan", action="store_true",
                    help="source is a scan of the owner's unit: weld, level + cut the floor, drop loose scraps, matte materials")
    pi.add_argument("--floor", choices=["auto", "none"], default="auto", help="with --scan: find and level the floor plane")
    pi.add_argument("--floor-cut", type=float, default=0.4, help="with --scan: delete everything below this z (in) after levelling")
    pi.add_argument("--min-island", type=float, default=0.02,
                    help="with --scan: drop loose parts smaller than this fraction of the biggest (0 = keep all)")
    pi.add_argument("--crop", help="--crop=x0,x1,y0,y1[,z0,z1] (use =, values can be negative) inches in the item frame (after square/rot/centre): keep only this box")
    pi.add_argument("--texture-max", type=int, default=0, help="downscale textures to at most this many px (scans: 2048)")
    pi.add_argument("--size", type=int, default=800, help="pixels per preview view")
    pp = sub.add_parser("preview")
    pp.add_argument("--item", required=True)
    pp.add_argument("--path", help="asset file (default: inventory asset.path)")
    pp.add_argument("--size", type=int, default=800)
    a = ap.parse_args(argv)
    cmd_import(a) if a.cmd == "import" else cmd_preview(a)


if __name__ == "__main__":
    main()
