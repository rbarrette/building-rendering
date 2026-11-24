# <Space name> - context

Last updated: (template). **This file still describes the bundled EXAMPLE garage.** Replace it during setup (`START-HERE.md`).

## Goal
A measured 3D model of <your space>, used to test furniture/equipment layouts.
`data/space.json` is the single source of truth. `scripts/build_scene.py` builds the Blender scene from it.
Each layout option is a separate JSON file of item placements: a new layout means editing data, not dragging things in Blender.

## Conventions
- **Units:** inches, decimals. (Convert feet-inches or metric at the input.)
- **Origin (0,0,0):** inside SW corner at finished floor level. **+X east, +Y north, +Z up.**
  (Compass names are a convention; record here what "north" means for this space, e.g. "the wall with the main door".)
- **Walls** are named by compass: `W-S`, `W-E`, `W-N`, `W-W`. Interior walls: `IW-1`, `IW-2`, ...
- **Wall items** are measured standing inside, facing the wall, from the wall's LEFT end: `{wall, offset, z, w, h}`.
  Openings (doors, windows): `offset` = left edge. Other wall items (outlets, panels, vents): `offset` = centre. `z` = bottom of item.
  Left ends: W-S -> east end, W-E -> north end, W-N -> west end, W-W -> south end.
  So on W-S, world x = length_x - offset; on W-E, y = width_y - offset; on W-N, x = offset; on W-W, y = offset.
- **Floor/ceiling items:** `x, y, z`, `rot` in degrees (counter-clockwise from above). x,y = footprint centre.
- **Zones:** `x, y` = SW corner, `w` along X, `d` along Y. Kind `keep_clear` zones must stay empty.
- **Inventory items:** `w` along X, `d` along Y at rot 0. The item's *front* faces south (-Y) at rot 0
  (rot 90 = front faces E, 180 = N, 270 = W). Clearances (front/sides/back/top) are extra space beyond the footprint.
  Optional `folded` dims, `access` (side you use it from, if not the front), `mount: wall`, `refs`, `appearance`,
  `specs`, `owned` (owned/ordered/planned/considering), `asset`, `scan`. See `data/schema/inventory.schema.json`.
- **Placement rules** (`data/placement-rules.json`): `must` broken = ERROR, `prefer` broken = WARN. See `prompts/placement-rules.md`.
- **Confidence:** any value can carry `"confidence": "measured" | "scanned" | "spec" | "estimated"` and a `"source"`.
  Scalars may be a plain number or `{"value": n, "confidence": ..., "source": ...}`. `"todo": true` marks placeholders.
  Tape wins over scans and specs.
- **Measurement surface:** <what the tape hits: drywall / stud / trim / foam; expected +/- tolerance>.

## Layout of the repo
`data/` (space.json, inventory.json, placement-rules.json, schema/) - `layouts/` - `measurements/raw/` (verbatim dated
field notes, never edited) - `measurements/processed/` - `scripts/` - `prompts/` - `reference/` (photos, scans, specs,
items/<id>/) - `assets/items/<id>/` - `blend/` and `renders/` (build outputs, never hand-edited) - `extras/` (optional studies).
Make targets: `setup validate build render photo scan-views asset-import asset-preview scan-import splat-mesh scan-todo all clean`
(knobs `LAYOUT=`, `SCAN=0`, `ASSETS=0`, `VERSION=`, `ENGINE=cycles`, `ITEM=`, `SRC=`, `ARGS=`).
Large binaries (.blend, .glb, .usdz, .ply, images, PDFs) are in Git LFS.

## Known facts
| Fact | Status |
|---|---|
| EXAMPLE: inside 288 x 288 in (24 x 24 ft), ceiling 108 in | estimated (example) |
| EXAMPLE: 16x7 overhead door on W-S, entry door on W-E, window on W-W, panel on W-N | estimated (example) |

## Status
- Template example validates (0 errors) and renders.

## Open questions / TODO
- Everything: this is the example.

## Working with AI tools
Edit `data/*.json` and `layouts/*.json` only; never hand-edit `blend/` or `renders/`. After any edit run `make validate`
and report flags. Raw notes go verbatim into `measurements/raw/YYYY-MM-DD.md` first. Keep this file current.
