# Scripts

Working code from the original project, pointed at `data/space.json`. It runs as-is on the example garage. Variable
names still say `shop` in places; that's just the name of the space dict.

| Script | Runs in | Does |
|---|---|---|
| `common.py` | both | Loading (unwraps `{value, confidence}`), wall/offset geometry, footprints, door and panel zones. |
| `validate.py` | Python | Schemas, ids, diagonals, overlaps (height-aware), clearances, doors, sliding-door paths, overhead-door tracks, panel working space, `keep_clear` zones, ceiling height, placement rules, walkability (3 in grid, 36 in paths), asset checks. Exit 1 on any ERROR. |
| `build_scene.py` | Blender | Builds `blend/<layout>.blend`: shell with openings cut, roof/trusses, wall/ceiling/floor items, interior walls, inventory (asset or box), clearance volumes, reference scans. 1 unit = 1 inch. |
| `render.py` | Blender | Plan, 4 corner isos, eye-level views; `--look photo` for EEVEE/Cycles; versioned snapshots in `renders/<layout>/versions/`. |
| `scan_views.py` | Blender | Gridded plan halves and wall elevations of a room scan (mesh and point cloud) for reading positions off. |
| `assets.py`, `asset_tool.py` | Blender | Asset contract + loader; vendor import, procedural build, scan import, preview sheets (`asset.json` with bbox + sha256). |
| `splat_mesh.py` | Blender | Gaussian-splat PLY → cleaned mesh GLB for `scan-import`. |
| `scan_todo.py` | Python | Lists items by scan status. |

## Things that are specific to the original project (data-driven, dormant until your data uses them)
- `build_scene.py` `style()`: the photo-look materials (flake epoxy floor, stained cabinets, painted accent wall,
  spray-foam walls, black trusses). Change them to your finishes.
- Interior-wall `trim` (board-and-batten), barn doors, kitchen `fronts`/countertop/sink, wall `framing`, and the
  planned outlet plates read from `data/electrical.json`. They only build when those fields exist.
- `render.py` named eye-level views: add your own cameras (the original had `kitchen` and `gym`; see the `EYE_VIEWS`
  branch for how they were placed).
- The shell is a single rectangle. Non-rectangular spaces need `common.shell_dims`, the shell build and the walkability
  grid extended (see `docs/GUIDE.md`, "Houses and odd shapes").
