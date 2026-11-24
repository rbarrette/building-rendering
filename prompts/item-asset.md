# Build a 3D asset for one inventory item

Tool-neutral prompt (Claude Code, Antigravity, others). Input: one inventory id (e.g. `power-rack`).
Goal: replace the item's coloured box in the renders with a model that is the right size, faces the right way,
and looks like the owner's unit. Placement and validation keep using the inventory `w/d/h`, so the asset is visual only.

## 0. Read first
- `CONTEXT.md` (units = inches, +X east, +Y north, item FRONT faces -Y at rot 0, w along X, d along Y).
- The item in `data/inventory.json` (dims, `appearance` parts + hex colours, `note`) and `reference/items/<id>/notes.md`
  (orientation hints, which variant the vendor model shows, what differs on the owner's unit).
- Code: `scripts/assets.py` (asset contract + loader), `scripts/asset_tool.py` (import + preview), `build_inventory` in
  `scripts/build_scene.py` (uses the asset when the item has one; folded placements stay boxes; `ASSETS=0` forces boxes).

## 1. Pick the source (best first)
0. **The owner's own scan** in `reference/items/<id>/scan/`: use `prompts/item-scan.md` instead of this prompt
   (it also updates the dims). If the item has none and the owner could scan it, mention `scan.status: "wanted"`.
1. **Vendor model** in `reference/items/<id>/model/` (GLB/USDZ/FBX/OBJ). Never run downloaded files; only import them.
2. **Procedural builder**: `assets/items/<id>/build.py` with `def build(ctx)` returning objects, modelled in inches in the
   item-local frame (origin = footprint centre on the floor). Use `ctx.part(name, [ctx.box(cx, cy, z0, w, d, h)], ctx.mat(name, ctx.hexrgba("#404040")))`.
   Build the recognisable masses (frame tubes, cushions, tops, legs, seats) from the photos; 10-60 parts is plenty.
3. **Box only**: if the item is a plain box (racks, cabinets), skip the asset; the `appearance` colour is enough.

## 2. Make it
- Vendor: `make asset-import ITEM=<id> SRC=reference/items/<id>/model/<file> ARGS="--square --rot <deg> [--drop REGEX] [--recolor 'MAT=#hex'] [--max-tris 80000]"`
  - `--square` aligns the footprint to the axes; then pick `--rot` (0/90/180/270) so the FRONT is at -Y and w runs along X.
  - `--drop` removes parts the owner's unit lacks (weight stacks, props, plates); `--recolor` fixes variant colours.
    Check the preview before guessing `--drop` names: vendor CAD exports often have opaque or non-ASCII node names, or may already omit optional add-ons.
  - Note: Blender's glTF/USD/FBX/OBJ importers auto-scale to `scene.unit_settings.scale_length`, while the glTF exporter does not; `asset_tool.py` and `assets._import_glb` temporarily set `scale_length = 1.0` during import so `UNITS` conversion is applied once. Also check for mirrored hierarchy transforms (`matrix_world.determinant() < 0`), which flip normals when baked.
  - Writes `assets/items/<id>/<id>.glb` + `import.json` (exact args, so it can be rebuilt), then the preview.
- Procedural: write `build.py`, then `make asset-preview ITEM=<id> ARGS="--path assets/items/<id>/build.py"`.
  - Use `ctx.mat(name, ctx.hexrgba("#RRGGBB"))` (default `"plain"` style) when you want exact hex colours in both diagram and photo renders; passing `kind="black"` overrides the base colour to near-black `(0.03, 0.03, 0.03)`.
  - Group boxes by material into a few `ctx.part(...)` calls (e.g. `frame`, `panels`, `cushions`) and leave a small (0.25-0.5 in) seam between modular cushions/parts so Workbench outline/cavity shading reads clearly.

## 3. Check it (look at the picture every time)
- Open `assets/items/<id>/preview.png`: front (from -Y) | right side (from +X) / top (north up) | 3/4 view.
  Orange wireframe = inventory w x d x h; red arrow = FRONT; floor grid = 12 in.
- The model should fill the orange box: each of w/d/h within ~1.5 in (`asset.json` `diff_in`), the front on the arrow side,
  sitting on the floor, centred. Compare against `reference/items/<id>/images/`.
- If the model is right and the inventory is wrong, do NOT change the inventory silently: note it and ask the owner.
- Iterate until it matches. Keep under ~100k tris.

## 4. Record it
- In `data/inventory.json` add to the item:
  `"asset": {"path": "assets/items/<id>/<id>.glb" (or build.py), "source": "vendor" | "procedural" | "scan", "status": "draft" | "approved", "note": "..."}`
  (add the `asset` object to `data/schema/inventory.schema.json` if it isn't there yet).
- Add a short "Asset" section to `reference/items/<id>/notes.md` (source, rotation, what was dropped/recoloured, deviations).
- `make validate` (checks that `asset.path` exists, `assets/items/<id>/asset.json` `sha256` matches, and `|diff_in| <= 1.5` in), then `make photo LAYOUT=<a layout that places it>` if the item is placed, and look at the result.
- Show the owner the preview and ask for approval; set `status: approved` only on their yes.
- Assets and vendor models are for local renders only; never publish them.
