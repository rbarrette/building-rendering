"""Render measurement views of the reference scan (plan halves + wall elevations) with labelled grids.

Run:  Blender --background --python scripts/scan_views.py -- [--blend blend/none.blend] [--ppi 2.5]
Needs a .blend built WITH the scan (make build LAYOUT=none). Output: renders/scan/*.png
Each view renders from the textured mesh (<name>.png, Workbench) and from the point cloud (<name>-pts.png, EEVEE
unlit, needs a kind=points scan); --source mesh|points|both.
Grid labels are WORLD coordinates (x for N/S walls and plan, y for E/W walls), red every 24", thin every 12".
Each elevation is a section: only geometry within ~48" in front of the wall (and 24" behind it) is drawn.
"""
import argparse
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

Z = Vector((0, 0, 1))
_mats = {}


def mat(name, rgba):
    if name not in _mats:
        m = bpy.data.materials.new(name)
        m.diffuse_color = rgba  # Workbench
        m.use_nodes = True  # EEVEE (points pass): unlit
        nt = m.node_tree
        nt.nodes.clear()
        em, out = nt.nodes.new("ShaderNodeEmission"), nt.nodes.new("ShaderNodeOutputMaterial")
        em.inputs["Color"].default_value = rgba
        nt.links.new(em.outputs[0], out.inputs["Surface"])
        _mats[name] = m
    return _mats[name]


def box(coll, name, lo, hi, m):
    lo, hi = Vector(lo), Vector(hi)
    me = bpy.data.meshes.new(name)
    v = [(x, y, z) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
    f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    me.from_pydata(v, [], f)
    me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)


def text(coll, body, loc, right, up, size, m):
    cu = bpy.data.curves.new("T", "FONT")
    cu.body, cu.size, cu.align_x, cu.align_y = body, size, "CENTER", "CENTER"
    cu.materials.append(m)
    ob = bpy.data.objects.new("T_" + body, cu)
    r, u = Vector(right).normalized(), Vector(up).normalized()
    n = r.cross(u)
    ob.matrix_world = Matrix(((r.x, u.x, n.x, loc[0]), (r.y, u.y, n.y, loc[1]), (r.z, u.z, n.z, loc[2]), (0, 0, 0, 1)))
    coll.objects.link(ob)


def camera(name, loc, direction, up, ortho, clip):
    cd = bpy.data.cameras.new(name)
    cd.type, cd.ortho_scale = "ORTHO", ortho
    cd.clip_start, cd.clip_end = clip
    ob = bpy.data.objects.new(name, cd)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = Vector(direction).to_track_quat("-Z", up).to_euler()
    return ob


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", default=str(C.ROOT / "blend" / "none.blend"))
    ap.add_argument("--ppi", type=float, default=2.5, help="pixels per inch")
    ap.add_argument("--source", choices=("mesh", "points", "both"), default="both")
    ap.add_argument("--out", default=str(C.ROOT / "renders" / "scan"), help="output directory")
    ap.add_argument("--only", default="", help="comma-separated view names to render (default: all)")
    args = ap.parse_args(argv)

    shop = C.load(C.ROOT / "data" / "space.json")
    L, W, H = C.shell_dims(shop)
    bpy.ops.wm.open_mainfile(filepath=args.blend)
    scene = bpy.context.scene
    if not any(o.name.startswith("SCAN_") for o in bpy.data.objects):
        sys.exit("no SCAN_ objects in blend - build with the scan first")
    scans = [o for o in bpy.data.objects if o.name.startswith("SCAN_")]
    by_kind = {k: [o for o in scans if o.get("scan_kind", "mesh") == k] for k in ("mesh", "points")}
    sources = [k for k in ("mesh", "points") if args.source in (k, "both") and by_kind[k]]
    for o in bpy.data.objects:
        o.hide_render = True
    sh = scene.display.shading
    sh.light, sh.color_type, sh.show_object_outline = "FLAT", "TEXTURE", False
    scene.render.image_settings.file_format = "PNG"
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    red, thin = mat("grid_red", (0.95, 0.1, 0.1, 1)), mat("grid_thin", (1.0, 0.85, 0.0, 1))

    jobs = []

    only = {v.strip() for v in args.only.split(",") if v.strip()}

    def render(name, cam, wpx, hpx, coll):  # queued; rendered once per source below
        if not only or name in only:
            jobs.append((name, cam, wpx, hpx, coll))

    def new_coll(name):
        c = bpy.data.collections.new(name)
        scene.collection.children.link(c)
        c.hide_render = True
        return c

    # ---------------- plan halves (section cut at 100")
    # (name, y range, z band): floor plans cut at 100in, and ceiling-band plans showing only z 80-150
    # (door tracks, fans, lights, ducts hanging below the roof)
    for name, y0, y1, zlo, zhi in (("plan-south", -24, 252, -50, 100), ("plan-north", 220, W + 24, -50, 100),
                                   ("ceiling-south", -24, 252, 80, 150), ("ceiling-north", 220, W + 24, 80, 150)):
        g = new_coll(name)
        zg = zhi - 2
        for x in range(0, int(L) + 1, 12):
            m, w = (red, 0.8) if x % 24 == 0 else (thin, 0.4)
            box(g, "gx", (x - w / 2, y0, zg), (x + w / 2, y1, zg + 0.2), m)
            if x % 24 == 0:
                for yl in (y0 + 8, y1 - 8):
                    text(g, str(x), (x, yl, zg), (1, 0, 0), (0, 1, 0), 5, red)
        for y in range(0, int(W) + 1, 12):
            if y0 <= y <= y1:
                m, w = (red, 0.8) if y % 24 == 0 else (thin, 0.4)
                box(g, "gy", (-10, y - w / 2, zg), (L + 10, y + w / 2, zg + 0.2), m)
                if y % 24 == 0:
                    text(g, str(y), (-18, y, zg), (1, 0, 0), (0, 1, 0), 5, red)
                    text(g, str(y), (L + 18, y, zg), (1, 0, 0), (0, 1, 0), 5, red)
        wid, hei = L + 60, y1 - y0
        cam = camera("CAM_" + name, ((L) / 2, (y0 + y1) / 2, 1000), (0, 0, -1), "Y", wid, (1000 - zhi, 1000 - zlo))
        render(name, cam, wid * args.ppi, hei * args.ppi, g)

    # ---------------- elevations: (name, face centre, normal toward camera, image-right, lo, hi, along-axis)
    # lo/hi = world extent of the face along its axis; grid labels are world coordinates on that axis
    elevs = [
        ("elev-S", (L / 2, 0), (0, 1), (-1, 0), 0, L, "x"),
        ("elev-N", (L / 2, W), (0, -1), (1, 0), 0, L, "x"),
        ("elev-E", (L, W / 2), (-1, 0), (0, -1), 0, W, "y"),
        ("elev-W", (0, W / 2), (1, 0), (0, 1), 0, W, "y"),
    ]
    for iw in shop["interior_walls"]:  # both faces of every interior wall
        (x1, y1), (ux, uy), (nx, ny), length = C.seg_frame(iw)
        mx, my, t = (iw["x1"] + iw["x2"]) / 2, (iw["y1"] + iw["y2"]) / 2, iw["thickness"] / 2
        axis = "x" if abs(ux) > abs(uy) else "y"
        lo, hi = sorted((iw["x1"], iw["x2"]) if axis == "x" else (iw["y1"], iw["y2"]))
        for s in (1, -1):
            m = Vector((nx * s, ny * s, 0))
            r = (-m).cross(Z)
            side = {(0, 1): "Nface", (0, -1): "Sface", (1, 0): "Eface", (-1, 0): "Wface"}[(round(m.x), round(m.y))]
            elevs.append((f"elev-{iw['id']}-{side}", (mx + m.x * t, my + m.y * t), (m.x, m.y), (r.x, r.y), lo, hi, axis))
    D, near, behind = 400, 48, 24
    for name, (px, py), (nx, ny), (rx, ry), lo, hi, axis in elevs:
        length = hi - lo
        g = new_coll(name)
        n, r = Vector((nx, ny, 0)), Vector((rx, ry, 0))
        p = Vector((px, py, 0))
        gp = p + n * (near - 2)  # grid plane, just inside the near clip
        for k in range(int(math.ceil(lo / 12.0)) * 12, int(hi) + 1, 12):
            pt = Vector((k, py, 0)) if axis == "x" else Vector((px, k, 0))
            along = (pt - p).dot(r)
            c = gp + r * along
            m, w = (red, 0.8) if k % 24 == 0 else (thin, 0.4)
            a, b = c - r * (w / 2) - n * 0.1, c + r * (w / 2) + n * 0.1
            box(g, "gv", (min(a.x, b.x), min(a.y, b.y), -12), (max(a.x, b.x), max(a.y, b.y), H + 12), m)
            if k % 24 == 0:
                for zl in (-6, H + 6):
                    text(g, str(k), (c.x, c.y, zl), r, Z, 5, red)
        for zz in range(0, int(H) + 1, 12):
            m, w = (red, 0.8) if zz % 24 == 0 else (thin, 0.4)
            a = gp - r * (length / 2 + 10) - n * 0.1
            b = gp + r * (length / 2 + 10) + n * 0.1
            box(g, "gh", (min(a.x, b.x), min(a.y, b.y), zz - w / 2), (max(a.x, b.x), max(a.y, b.y), zz + w / 2), m)
            if zz % 24 == 0:
                for s in (-1, 1):
                    q = gp + r * s * (length / 2 + 20)
                    text(g, f"z{zz}", (q.x, q.y, zz), r, Z, 5, red)
        cam_loc = p + n * D + Z * (H / 2)
        wid, hei = length + 70, H + 40
        cam = camera("CAM_" + name, cam_loc, tuple(-n), "Y", wid, (D - near, D + behind))
        render(name, cam, wid * args.ppi, hei * args.ppi, g)

    for src in sources:
        if src == "mesh":
            scene.render.engine = "BLENDER_WORKBENCH"
            scene.view_settings.view_transform = "Standard"
        else:  # unlit emission: colours come straight from the points
            scene.render.engine = "BLENDER_EEVEE"
            scene.view_settings.view_transform = "Standard"
            scene.eevee.taa_render_samples = 4
            scene.world = None
        for o in scans:
            o.hide_render = o not in by_kind[src]
        for name, cam, wpx, hpx, coll in jobs:
            coll.hide_render = False
            scene.camera = cam
            scene.render.resolution_x, scene.render.resolution_y = int(wpx), int(hpx)
            scene.render.resolution_percentage = 100
            scene.render.filepath = str(out / (f"{name}.png" if src == "mesh" else f"{name}-pts.png"))
            bpy.ops.render.render(write_still=True)
            coll.hide_render = True
            print(f"RENDERED {scene.render.filepath}")


main()
