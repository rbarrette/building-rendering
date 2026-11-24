# Bring in a 3D scan of one item

Tool-neutral prompt (Claude Code, Antigravity, others). Claude Code: `/scan-item <id or item> <scan file>`.
Also run as a step of `prompts/inventory-ingest.md` when the owner hands over a scan with a new item.
Goal: the owner's own unit, scanned, becomes (1) the item's dimensions (`confidence: "scanned"`) and (2) its render asset.
How to capture a good scan: `reference/scans/_capture-guide.md`.

## 0. Read first
- `CONTEXT.md` (inches, +X east, +Y north, item FRONT faces -Y at rot 0, w along X, d along Y).
- The item in `data/inventory.json` and `reference/items/<id>/notes.md` if they exist.
- `prompts/item-asset.md` steps 3-4 (preview sheet, recording an asset): this prompt reuses them.

## 1. Which item?
- **Already in the inventory** (e.g. `family-table`): keep its `id`; layouts reference it. Go to step 2.
- **Not in the inventory**: run `prompts/inventory-ingest.md` steps 1-6 first (identify, research specs and clearances,
  write the entry, notes file), then come back. For a one-off with no product page (family furniture, shop-built),
  skip the web research: make a minimal entry (id, name, category, owned, clearances from use) and let the scan supply w/d/h.
- **One capture, several items** (a table with chairs around it): the same file can serve each item with a different `--crop`.
  Layout placements are one per item id, so identical pieces the owner wants placed one by one need one item each
  (`dining-chair-1`..`-6`, each pointing at the same capture). Ask the owner which they want before making N items.

## 2. Take in the file (never edit it)
- Copy the export as-is to `reference/items/<id>/scan/<YYYY-MM-DD>-<app>-<what>.<ext>`
  (e.g. `2026-11-24-scaniverse-table.glb`). Git LFS covers glb/usdz/obj/fbx/ply. Never modify or delete files here.
- GLB is best. USDZ, OBJ and FBX also import. A plain PLY point cloud can't be an asset: use it only to measure (as in ingest step 3).
- A Gaussian-splat export (PLY with `f_dc_*`/`opacity`/`scale_*`, or `.spz`; keep both) is not a mesh: first make one with
  `make splat-mesh SRC=<ply> OUT=reference/items/<id>/scan/<name>.mesh.glb ARGS="..."` (`scripts/splat_mesh.py`: frame on a
  height `--band`, `--keep` boxes to cut chairs/room, `--strip`/`--fill` for clutter on a surface, `--flatten` for one flat top,
  `--move`/`--mirror`/`--close` to fill parts the scan missed on a symmetric item, `--smooth`/`--smooth-below`/`--flat-top`/
  `--color-blur` to clean the mesh, `--views DIR --views-only` to choose boxes). Save the args next to it (`<name>.mesh.args`), then import that GLB with
  `--floor none`.
  Zipped OBJ/glTF exports: unzip into the same `scan/` folder and import the `.obj`/`.gltf`.
- Record the capture in the item: `"scan": {"status": "scanned", "captures": [{"path": ..., "date": "YYYY-MM-DD",
  "app": "Polycam", "mode": "LiDAR" | "photo" | "object capture", "units": "m", "covers": "table only"}]}`.
  Add to the list for a re-scan; keep older captures.

## 3. Import and clean it
`make scan-import ITEM=<id> SRC=reference/items/<id>/scan/<file> ARGS="..."` runs `asset_tool.py import` with
`--scan --square --texture-max 2048`. That welds the mesh, finds the floor plane and levels it (prints the tilt), cuts away
everything below 0.4 in, drops loose scraps under 2% of the biggest part, makes the materials matte (light is baked into
scan textures), squares the footprint to the axes and writes `assets/items/<id>/<id>.glb` + `preview.png`.
Look at the preview, then fix with `ARGS`:
- `--rot 90|180|270` until the FRONT (the side you use it from) is on the red arrow and w runs left-right.
- `--crop=x0,x1,y0,y1[,z0,z1]` (with the `=`, since values can be negative): inches in the preview's frame (12 in grid, origin at centre). Use it to cut off clutter,
  walls, or the other items in a shared capture. The frame doesn't change between runs with the same other args.
- `--min-island 0` if a real part went missing (a separate chair leg); raise it (0.1) if junk is left.
- "no clear floor plane" is fine when the app already removed the floor; then the item just sits on its lowest point.
  A tilt over ~5 deg or a lopsided preview means the fit grabbed the wrong plane: try `--floor none` plus a `--crop` z0.
- `--max-tris` defaults to 80k; keep under ~100k. `--units` only if the export isn't metres (glTF/USDZ are metres).
Iterate until the preview looks like the item, then commit to those args (they're saved in `import.json`).

## 4. Check the scale with a tape
Phone LiDAR is usually right within ~1%, but a bad capture can be off by several percent. Read the scan's size from
`assets/items/<id>/asset.json` `bbox_in`, then ask the owner for 1-2 tape values along the longest dimensions
(say exactly where: "top length end to end", "floor to top of the top"). Existing measured values count too.
- Within ~0.5 in (or 1%): the scale is good.
- Off by more: re-import with `--scale <tape / scan>` (same for all three axes), and note it.
Save the tape values verbatim in `measurements/raw/YYYY-MM-DD.md` (append only) and in the capture's `tape_check`.

## 5. Update the item from the scan
- `w`, `d`, `h` from `bbox_in` (round to 0.25 in), except taped values, which win.
- `confidence: "scanned"` (`"measured"` only if all three were taped); `source`: capture path + date + tape check.
- Remove `"todo": true` when w/d/h are scanned or measured.
- If the scan disagrees with a manufacturer spec by more than ~1 in, don't pick silently: the scan may include extras
  (cushions, handles, cables) or the variant may differ. Ask the owner, then record both values in the notes.
- `appearance`: take `hex` per part from the scan's colours if the item had placeholders (sample the texture).
- Folded/stowed: a scan shows one state. If the item has `folded` dims, the scan is the open state unless the owner
  scanned it folded (folded placements are drawn as boxes either way).
- Re-run `make asset-preview ITEM=<id>` so `asset.json` compares against the new dims (diff ~0).
- Record the asset: `"asset": {"path": "assets/items/<id>/<id>.glb", "source": "scan", "status": "draft", "note": ...}`
  (replaces a procedural or vendor asset; say what it replaced in the note).

## 6. Validate, render, approve
- `make validate`: 0 errors. It checks capture paths exist, the asset sha, and asset vs inventory size (1.5 in).
- If the item's size changed and it is placed, look for new overlap/clearance/walkability flags and report them;
  don't move it in a layout unless the owner asks.
- `make photo LAYOUT=<a layout that places it>` and look at it. Show the owner the preview sheet + render;
  set `asset.status: "approved"` only on their yes.

## 7. Notes
Add a "Scan" section to `reference/items/<id>/notes.md`: capture file(s), app/mode, import args, floor tilt,
what was cropped or dropped, tape check and scale, old vs new dims, open questions. Scans stay local; never publish them.
