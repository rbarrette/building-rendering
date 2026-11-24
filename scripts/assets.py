"""Per-item 3D assets (runs inside Blender). Used by build_scene.py and asset_tool.py.

Asset contract (see prompts/item-asset.md):
  - Lives in assets/items/<id>/. inventory.json item -> "asset": {"path": ..., "source": ..., "status": ...}.
  - Item-local frame, same as the inventory: origin = footprint centre at the floor, +Z up,
    FRONT faces -Y (south) at rot 0, w along X, d along Y.
  - .glb: standard glTF (metres, Y-up). Written by `asset_tool.py import`; loaded here and scaled to inches.
  - .py:  procedural builder with `def build(ctx) -> list[bpy.types.Object]`, modelled in inches in the
          item-local frame. ctx: coll, item, prefix, mat(name, rgba, kind=None), hexrgba("#RRGGBB"),
          box(cx, cy, z0, w, d, h, rot=0), make_obj(name, coll, boxes, material, cyl=None), part(name, boxes, material).
  - assets/items/<id>/asset.json (written by `asset_tool.py preview`): measured bbox, tris, sha256 of the asset file.
"""
import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Matrix, Vector

M_TO_IN = 1 / 0.0254


def asset_file(root, item):
    a = item.get("asset")
    if not a or not a.get("path"):
        return None
    return Path(root) / a["path"]


def hexrgba(h, alpha=1.0):
    """'#RRGGBB' (sRGB) -> linear RGBA for Blender colours."""
    h = h.lstrip("#")

    def lin(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return (lin(h[0:2]), lin(h[2:4]), lin(h[4:6]), alpha)


def sync_viewport_colors(materials, objs=()):
    """Workbench (diagram renders) uses Material.diffuse_color; copy it from the Principled base colour
    (a texture's average for textured scans, the mesh colour attribute's average for vertex-coloured scans)."""
    for m in materials:
        if not m or not m.node_tree:
            continue
        bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf and "Base Color" in bsdf.inputs:
            src = bsdf.inputs["Base Color"].links[0].from_node if bsdf.inputs["Base Color"].links else None
            avg = _image_mean(src.image) if src is not None and src.type == "TEX_IMAGE" and src.image else None
            if avg is None and src is not None and _upstream(src, ("VERTEX_COLOR", "ATTRIBUTE")):
                avg = _color_attr_mean([o for o in objs if o.type == "MESH" and m.name in o.data.materials])
            m.diffuse_color = avg or tuple(bsdf.inputs["Base Color"].default_value)


def _upstream(node, types, depth=4):
    """True if `node` or a node feeding it (a few links back) is one of `types`."""
    if node.type in types:
        return True
    return depth > 0 and any(_upstream(l.from_node, types, depth - 1) for i in node.inputs for l in i.links)


def _color_attr_mean(objs):
    """Average active colour attribute (linear RGBA) over the given meshes, or None."""
    try:
        import numpy as np
        acc = []
        for o in objs:
            ca = o.data.color_attributes.active_color or (o.data.color_attributes[0] if o.data.color_attributes else None)
            if ca is None or not len(ca.data):
                continue
            px = np.empty(len(ca.data) * 4, dtype=np.float32)
            ca.data.foreach_get("color", px)  # linear for both FLOAT_COLOR and BYTE_COLOR
            acc.append(px.reshape(-1, 4)[:, :3])
        if not acc:
            return None
        rgb = np.vstack(acc).mean(axis=0)
        return (float(rgb[0]), float(rgb[1]), float(rgb[2]), 1.0)
    except Exception as e:  # noqa: BLE001 - colour is cosmetic; never fail a build over it
        print(f"WARNING: could not average colour attribute: {e}")
        return None


def _image_mean(im):
    """Average colour of a texture (linear RGBA), so a textured scan gets its real overall colour in Workbench."""
    try:
        import numpy as np
        w, h = im.size
        if not w or not h:
            return None
        px = np.empty(w * h * 4, dtype=np.float32)
        im.pixels.foreach_get(px)
        rgb = px.reshape(-1, 4)[::7, :3].mean(axis=0)
        if not im.is_float and im.colorspace_settings.name == "sRGB":  # byte sRGB pixels -> linear
            rgb = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        return (float(rgb[0]), float(rgb[1]), float(rgb[2]), 1.0)
    except Exception as e:  # noqa: BLE001 - colour is cosmetic; never fail a build over it
        print(f"WARNING: could not average texture {im.name}: {e}")
        return None


def _import_glb(path, coll):
    before = set(bpy.data.objects)
    units = bpy.context.scene.unit_settings
    saved_scale = units.scale_length
    units.scale_length = 1.0  # keep glTF importer in raw metres; we convert to inches below
    try:
        bpy.ops.import_scene.gltf(filepath=str(path))
    finally:
        units.scale_length = saved_scale
    new = [o for o in bpy.data.objects if o not in before]
    out = []
    for o in new:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        if o.type != "MESH":
            bpy.data.objects.remove(o)
            continue
        coll.objects.link(o)
        out.append(o)
    for o in out:  # bake parents/scale into the mesh, then metres -> inches
        mw = o.matrix_world.copy()
        o.parent = None
        o.data.transform(Matrix.Scale(M_TO_IN, 4) @ mw)
        o.matrix_world = Matrix.Identity(4)
    return out


def _run_builder(path, coll, item, prefix, helpers, state="open"):
    spec = importlib.util.spec_from_file_location(f"asset_{item['id'].replace('-', '_')}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mat = helpers["mat"]

    def part(name, boxes, material, cyl=None):
        return helpers["make_obj"](f"{prefix}_{name}", coll, boxes, material, cyl=cyl)
    ctx = SimpleNamespace(coll=coll, item=item, prefix=prefix, state=state, mat=mat, hexrgba=hexrgba,
                          box=helpers["centered_box"], make_obj=helpers["make_obj"], part=part)
    objs = mod.build(ctx) or []
    return list(objs)


def load_asset(root, item, coll, prefix, helpers, state="open"):
    """Load an item's asset into `coll` in the item-local frame (inches). Returns its objects, or None."""
    path = asset_file(root, item)
    if path is None:
        return None
    if not path.exists():
        print(f"WARNING: asset for {item['id']} missing: {path} - using a box")
        return None
    if path.suffix.lower() in (".glb", ".gltf"):
        if state == "folded":
            return None
        objs = _import_glb(path, coll)
    elif path.suffix.lower() == ".py":
        objs = _run_builder(path, coll, item, prefix, helpers, state=state)
    else:
        print(f"WARNING: unknown asset type {path.suffix} for {item['id']} - using a box")
        return None
    for i, o in enumerate(objs):
        if not o.name.startswith(prefix):
            o.name = f"{prefix}_{i:03d}"
    sync_viewport_colors({m for o in objs if o.type == "MESH" for m in o.data.materials}, objs)
    return objs


def place(objs, x, y, z, rot):
    """Move item-local objects to a layout placement (rot = CCW degrees from above)."""
    T = Matrix.Translation((x, y, z)) @ Matrix.Rotation(math.radians(rot), 4, "Z")
    for o in objs:
        o.matrix_world = T @ o.matrix_world


def bbox(objs):
    """World-space (min, max) Vectors over mesh vertices."""
    mn, mx = Vector((1e18,) * 3), Vector((-1e18,) * 3)
    for o in objs:
        if o.type != "MESH":
            continue
        mw = o.matrix_world
        for v in o.data.vertices:
            p = mw @ v.co
            mn = Vector(map(min, mn, p))
            mx = Vector(map(max, mx, p))
    return mn, mx


def tri_count(objs):
    return sum(len(p.vertices) - 2 for o in objs if o.type == "MESH" for p in o.data.polygons)
