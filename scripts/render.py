"""Render plan / iso / eye views of blend/<layout>.blend to renders/<layout>/ (plus versioned snapshots).

Run:  Blender --background --python scripts/render.py -- --layout option-a [--views plan,iso,eye] [--version tag]
Uses the Workbench engine (fast, no GPU/lighting setup needed) or EEVEE/Cycles for --look photo.
"""
import argparse
import datetime
import hashlib
import json
import math
import os
import shutil
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import lighting_plan as LP  # noqa: E402

PLAN_CUT = 110  # inches above the slab for plan-view section cuts
SUN_ANGLED = (math.radians(38), 0, math.radians(35))  # high sun from the SSE
SUN_OVERHEAD = (math.radians(8), 0, math.radians(30))
PHOTO_EXPOSURE = float(os.environ.get("PHOTO_EXPOSURE", -0.8))
# world-space studio light rotation (deg) per view, chosen so faces turned toward the camera are lit
LIGHT_ROT = {
    "plan": 45, "scan": 45,
    "iso": 45, "iso-ne": 225, "iso-nw": 135, "iso-se": 315,
    "eye-north": 180, "eye-north-w": 0,
    "eye-south": 180, "eye-south-w": 0,
    "kitchen": 270, "gym": 90,
}
ISO_VIEWS = ("iso", "iso-ne", "iso-nw", "iso-se")
EYE_VIEWS = ("eye-north", "eye-north-w", "eye-south", "eye-south-w", "kitchen", "gym")


def look_at(cam, target):
    d = Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def new_camera(name, kind):
    data = bpy.data.cameras.new(name)
    data.type = kind
    data.clip_start, data.clip_end = 1, 20000
    ob = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.scene.camera = ob
    return ob, data


def setup_photo(scene, engine, L, W):
    """EEVEE (or Cycles) with node materials, a sun, a sky-tinted world and AgX tone mapping."""
    if engine == "cycles":
        scene.render.engine = "CYCLES"
        scene.cycles.samples = 96
        try:
            scene.cycles.use_denoising = True
        except Exception:
            pass
    else:
        for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
            try:
                scene.render.engine = eng
                break
            except TypeError:
                continue
        ee = scene.eevee
        for attr, val in (("taa_render_samples", 48), ("use_raytracing", True), ("use_gtao", True),
                          ("use_shadows", True), ("shadow_ray_count", 2)):
            try:
                setattr(ee, attr, val)
            except Exception:
                pass
    for vt in ("AgX", "Filmic"):
        try:
            scene.view_settings.view_transform = vt
            break
        except TypeError:
            continue
    scene.view_settings.exposure = PHOTO_EXPOSURE
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.75, 0.79, 0.85, 1)
    bg.inputs[1].default_value = 0.9
    sun = bpy.data.lights.new("SUN", "SUN")
    sun.energy = 3.5
    try:
        sun.angle = math.radians(8)
    except Exception:
        pass
    ob = bpy.data.objects.new("SUN", sun)
    ob.rotation_euler = SUN_ANGLED
    scene.collection.objects.link(ob)


# Night renders of a lighting plan. The scene is in inches but Blender lights fall off per Blender unit, so every
# light is scaled by 1/0.0254^2 to give metric-correct levels. Not photometrically calibrated (EEVEE, plain spot
# cones): numbers come from `make lighting`; these renders are for looks.
LIGHT_SCALE = 1 / 0.0254 ** 2
NIGHT_EXPOSURE = float(os.environ.get("NIGHT_EXPOSURE", -0.5))


def apply_lighting(scene, plan, scene_id):
    """Show only LIGHT_<plan>; with a scene: night world, no sun, each light set from data/lighting.json levels."""
    data = LP.load()
    if plan not in data["plans"]:
        raise SystemExit(f"unknown lighting plan '{plan}' (have: {', '.join(data['plans'])})")
    for c in bpy.data.collections:
        if c.name.startswith("LIGHT_"):
            c.hide_render = c.name != f"LIGHT_{plan}"
    if not scene_id:
        return
    if scene_id not in data["scenes"]:
        raise SystemExit(f"unknown scene '{scene_id}' (have: {', '.join(data['scenes'])})")
    pkgs, fxs = data["table_packages"], data["fixture_types"]
    n = 0
    for ob in bpy.data.objects:
        ld = ob.data if ob.type == "LIGHT" else None
        if ld is None or "plan" not in ld:
            continue
        if ld["plan"] != plan:
            ld.energy = 0.0
            continue
        f, rgb, cct = LP.scene_level(data, scene_id, ld["layer"])
        if rgb:
            col, lf = rgb, 1.0
        else:
            own = ld["cct"]
            t = cct or own
            if data["layers"][ld["layer"]]["kind"] == "table":
                pk = pkgs[ld["package"]]
                if fxs[pk["fixture"]].get("cct_mode") == "fixed":  # two fixed-CCT circuits: dim instead of recolouring
                    f *= LP.circuit_mix(pk["ccts"], t)[pk["ccts"].index(own)]
                    t = own
                f *= ld.get("dim", 1.0)
            col = LP.cct_rgb(t)
            lf = 1.0 / LP.lum(col)
        watts = 4 * math.pi * ld["peak_cd"] / 683 if ld.type == "SPOT" else ld["lm"] / 683
        ld.color = col
        ld.energy = watts * lf * f * LIGHT_SCALE
        n += f > 0
    sun = bpy.data.objects.get("SUN")
    if sun:
        sun.hide_render = True
    bg = scene.world.node_tree.nodes.get("Background") if scene.world and scene.world.use_nodes else None
    if bg:
        bg.inputs[1].default_value = 0.0
    scene.view_settings.exposure = NIGHT_EXPOSURE + data["scenes"][scene_id].get("ev", 0.0)
    print(f"LIGHTING: plan {plan}, scene {scene_id}: {n} lights on")


def render(path, res, scale=100):
    s = bpy.context.scene
    s.render.resolution_x, s.render.resolution_y = res
    s.render.resolution_percentage = scale
    s.render.filepath = str(path)
    s.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
    print(f"RENDERED {path}")


def snapshot_version(out_dir, layout_name, rendered_files, version_tag=""):
    """Archive rendered images + layout.json into renders/<layout>/versions/vNN-<tag_or_hash>/."""
    lp = C.layout_path(layout_name)
    if not lp or not lp.exists():
        return
    raw_bytes = lp.read_bytes()
    lsha = hashlib.sha256(raw_bytes).hexdigest()[:8]
    vroot = out_dir / "versions"
    vroot.mkdir(parents=True, exist_ok=True)
    existing = sorted([d for d in vroot.iterdir() if d.is_dir() and d.name.startswith("v")])
    tag = (version_tag or os.environ.get("RENDER_VERSION", "")).strip()
    target_dir = None

    if tag:
        for d in existing:
            if d.name == tag or d.name.endswith(f"-{tag}"):
                target_dir = d
                break
        if target_dir is None:
            idx = len(existing) + 1
            target_dir = vroot / f"v{idx:02d}-{tag}"
    else:
        if existing:
            last = existing[-1]
            meta_file = last / "version.json"
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text())
                    if meta.get("layout_sha") == lsha:
                        target_dir = last
                except Exception:
                    pass
        if target_dir is None:
            idx = len(existing) + 1
            today = datetime.date.today().isoformat()
            target_dir = vroot / f"v{idx:02d}-{today}-{lsha}"

    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(lp, target_dir / "layout.json")
    for f in rendered_files:
        if f.exists():
            shutil.copy2(f, target_dir / f.name)
    meta = {
        "version": target_dir.name,
        "layout": layout_name,
        "layout_sha": lsha,
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "files": sorted(p.name for p in target_dir.glob("*.png")),
    }
    (target_dir / "version.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"VERSIONED -> {target_dir}")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--layout", default="none")
    ap.add_argument("--views", default="plan,iso,iso-ne,iso-nw,iso-se,eye-north,eye-north-w,eye-south,eye-south-w")
    ap.add_argument("--look", choices=("diagram", "photo"), default="diagram",
                    help="diagram = flat Workbench with labels/zones; photo = EEVEE with materials and lighting")
    ap.add_argument("--engine", choices=("eevee", "cycles"), default="eevee", help="photo look only")
    ap.add_argument("--scale", type=int, default=100, help="resolution percentage")
    ap.add_argument("--version", default="", help="optional version label for renders/<layout>/versions/")
    ap.add_argument("--lighting", default="", help="lighting plan from data/lighting.json (default: the layout's)")
    ap.add_argument("--scene", default="", help="lighting scene: photo look renders at night with that plan + scene")
    args = ap.parse_args(argv)
    photo = args.look == "photo" or bool(args.scene)

    name = C.layout_name(args.layout)
    shop = C.load(C.ROOT / "data" / "space.json")
    L, W, H = C.shell_dims(shop)
    bpy.ops.wm.open_mainfile(filepath=str(C.ROOT / "blend" / f"{name}.blend"))
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    if photo:
        setup_photo(scene, args.engine, L, W)
    lp = C.layout_path(args.layout)
    night = bool(args.scene)
    if (args.lighting or night) and not LP.PATH.exists():
        raise SystemExit("--lighting/--scene need data/lighting.json")
    if args.lighting or night:
        plan, scene_id = LP.layout_choice(LP.load(), C.load(lp) if lp else None, args.lighting or None, args.scene or None)
        apply_lighting(scene, plan, scene_id if night else None)
    sh = scene.display.shading
    sh.light, sh.color_type = "STUDIO", "MATERIAL"
    sh.show_object_outline = True
    sh.show_xray = False
    try:  # light from a fixed world direction (set per view) so walls facing the camera aren't left black
        sh.use_world_space_lighting = True
    except Exception:
        pass
    out = C.ROOT / "renders" / name / ("lighting" if night else "")
    out.mkdir(parents=True, exist_ok=True)
    centre = Vector((L / 2, W / 2, 0))

    scan_objs = [o for o in bpy.data.objects if o.name.startswith("SCAN_")]
    views = [v.strip() for v in args.views.split(",") if v.strip()]
    if args.views == ap.get_default("views") and scan_objs and not photo:
        views.append("scan")
    roof = [o for o in bpy.data.objects if o.name == "ROOF"]
    # photo look: drop the diagram overlays (zones, labels, clearances, door envelopes, axes)
    overlays = [o for o in bpy.data.objects if o.type == "FONT"
                or o.name.startswith(("ZONE_", "CLR_", "ENV_", "AXIS_"))] if photo else []
    rendered_files = []
    for view in views:
        cam, cd = new_camera(f"CAM_{view}", "ORTHO" if view in ("plan", "scan", *ISO_VIEWS) else "PERSP")
        hidden = list(scan_objs) + overlays
        # the roof only shows from inside, in photo eye-level views
        if not (photo and view in EYE_VIEWS):
            hidden += roof
        sh.color_type = "MATERIAL"
        if view in ("plan", "scan"):
            res = (2400, 1600)
            cam.location = (L / 2, W / 2, 1000)
            cam.rotation_euler = (0, 0, 0)
            cd.ortho_scale = max(L + 140, (W + 140) * res[0] / res[1])
            if view == "scan":
                cd.clip_start = 1000 - PLAN_CUT  # section cut so the scanned roof doesn't cover the plan
            # overhead items (trusses, air handler, lights, door tracks) and wall headers above openings
            # would hide the floor plan; hiding headers shows doors as gaps like a drawn plan
            hidden += [o for o in bpy.data.objects
                       if o.name.startswith(("TRUSS_", "CI_", "LT_", "LBL_AH", "LBL_HB", "TRACK_")) or o.name.endswith("_hdr")]
            if view == "scan":  # scan overlay: model walls/fixed items over the textured scan, no slab/zones
                # textured mesh only; point clouds need EEVEE (see scan_views.py)
                hidden = [o for o in hidden if not o.name.startswith("SCAN_") or o.get("scan_kind") == "points"]
                hidden += [o for o in bpy.data.objects
                           if o.name == "Slab" or o.name.startswith(("ZONE_", "LBL_ZONE", "INV_", "CLR_", "LBL_"))]
                sh.color_type = "TEXTURE"
        elif view in ISO_VIEWS:
            # 4-corner isometric cutaways so every wall face can be reviewed from both sides
            res = (2400, 1600)
            iso_cfg = {
                "iso":    ((1, 1, -1.2),   ("Wall_W-S", "Wall_W-W")),  # from SW looking NE
                "iso-ne": ((-1, -1, -1.2), ("Wall_W-N", "Wall_W-E")),  # from NE looking SW
                "iso-nw": ((1, -1, -1.2),  ("Wall_W-N", "Wall_W-W")),  # from NW looking SE
                "iso-se": ((-1, 1, -1.2),  ("Wall_W-S", "Wall_W-E")),  # from SE looking NW
            }
            dvec, near = iso_cfg[view]
            d = Vector(dvec).normalized()
            cam.location = centre - d * 3000
            look_at(cam, centre)
            cd.ortho_scale = (L + W) * 0.78
            hidden += [o for o in bpy.data.objects if o.name.startswith(near)]
            hidden += [o for o in bpy.data.objects if o.name.startswith(("TRUSS_", "CI_AH-", "LBL_AH-"))]  # trusses and overhead air handler clutter the iso
        elif view in EYE_VIEWS:
            # eye level (64in) from both ends (east->west and west->east) plus kitchen (N->S) and gym (S->N)
            res = (2400, 1350)
            cd.lens = 14
            if view == "kitchen":  # standing in the north section facing the cabinet run (design-render viewpoint)
                cd.lens = 20
                cam.location = (386, 430, 62)
                look_at(cam, (386, 237.75, 54))
            elif view == "gym":  # standing at the south wall facing the centre wall S face (opposite side of kitchen)
                cd.lens = 16
                cam.location = (365, 70, 62)  # in front of the stowed treadmill on W-S (was y=30)
                look_at(cam, (365, 233.25, 54))
            # eye views scale with the room: y as a fraction of its N-S width W (tuned on a 59 x 39 ft shop)
            elif view == "eye-north":
                cam.location = (L - 30, W * 0.64, 64)
                look_at(cam, (0, W * 0.80, 54))
            elif view == "eye-north-w":
                cam.location = (30, W * 0.72, 64)
                look_at(cam, (L, W * 0.72, 54))
            elif view == "eye-south":
                cam.location = (L - 30, W * 0.24, 64)
                look_at(cam, (0, W * 0.21, 54))
            else:  # eye-south-w
                cam.location = (30, W * 0.24, 64)
                look_at(cam, (L, W * 0.24, 54))
        else:
            print(f"unknown view '{view}' - skipped")
            continue
        try:  # top-down views look best with camera lighting; angled views with fixed world lighting
            sh.use_world_space_lighting = view not in ("plan", "scan")
            sh.studiolight_rotate_z = math.radians(LIGHT_ROT.get(view, 45))
        except Exception:
            pass
        for o in hidden:
            o.hide_render = True
        sun = bpy.data.objects.get("SUN")
        if sun:  # near-overhead for plan/iso so walls don't throw long shadows across the floor
            sun.rotation_euler = SUN_OVERHEAD if view in ("plan", *ISO_VIEWS) else SUN_ANGLED
        scene.render.resolution_percentage = args.scale
        out_file = out / (f"{plan}__{scene_id}__{view}.png" if night else f"photo-{view}.png" if photo else f"{view}.png")
        render(out_file, res, args.scale)
        rendered_files.append(out_file)
        for o in hidden:
            o.hide_render = False

    if name != "none" and rendered_files and (not night or args.version):
        snapshot_version(out, name, rendered_files, args.version)


main()
