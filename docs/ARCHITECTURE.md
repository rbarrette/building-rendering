# Architecture

## 1. Core idea
**The space and everything in it is data. Blender is only a renderer.**
Nobody drags objects around in Blender. A layout option is a small JSON file of `item id -> x, y, rot`. Scripts check it
and render it. So a new idea for a layout means a new JSON file, AI agents can do the work by editing text, and every
number can be traced back to a source.

```
 field notes ──► measurements/raw/  (verbatim, never edited)
                       │ interpret
                       ▼
               measurements/processed/  (derivations, open questions)
                       │ apply
                       ▼
 LiDAR scan ──► data/space.json  ◄── single source of truth for the SPACE
 (cross-check)        │
 web research ─► data/inventory.json  ◄── /ingest-item   (things that can be placed)
 owner's words ► data/placement-rules.json ◄── /placement-rule (how they want them placed)
 vendor/procedural ► assets/items/<id>/ ◄── /build-asset  (visual only)
                       │
                layouts/<option>.json  (placements only: id -> x, y, rot, state)
                       │
          make validate ─────────► errors / warnings (schema, geometry, rules, walkability)
                       │
          make build ──► blend/<layout>.blend ──► make render / make photo ──► renders/<layout>/*.png (+ versions/)
```

## 2. Conventions (decide these first; everything depends on them)
- **Units:** decimal inches everywhere. Convert at the input edge.
- **Frame:** origin = inside SW corner at floor level; +X east, +Y north, +Z up. `rot` = degrees CCW from above.
- **Items:** `w` along X, `d` along Y at rot 0; the item's **front faces south (-Y) at rot 0**. `access` names the side
  you use it from if that isn't the front. Clearances (front/sides/back/top) are extra space beyond the footprint.
- **Wall items** (doors, windows, outlets, panels, vents) are positioned like a person stands inside, facing the wall:
  `{wall, offset-from-left-end, z, w, h}`. That matches how people actually tape-measure.
- **Confidence on every number:** `measured` (tape) > `spec` (manufacturer) > `estimated` (scan, photo, guess), plus a
  `source`. `"todo": true` marks placeholders. Scalars can be a plain number or `{value, confidence, source}`.
  Rule: **tape wins**. The scan only cross-checks.

## 3. Data files (see `schemas/`)
| File | Holds |
|---|---|
| `data/space.json` | `shell` (inside dims, wall height), `interior_walls` (with openings, sliding-door paths), `wall_items`, `ceiling_items` (trusses, fans, lights, ducts), `floor_items` (fixed fixtures), `zones` (intent areas; `keep_clear` must stay empty), `reference_scans` (scan files + alignment). |
| `data/inventory.json` | Every movable/placeable thing: dims, clearances, `folded` dims, `access`, `mount`, `owned` status, `refs` (URLs, images, textures, notes), `appearance` (per-part colour hex/material), `specs` (weight, power, ceiling needed), `asset`. |
| `data/placement-rules.json` | Owner preferences as rules: `in_zone`, `against`, `facing`, `facing_toward`, `state` (folded), `near`, `away_from`, `placed`, `not_placed`, `manual`. Each has `strength` must/prefer, optional `priority`, optional `layouts` scope, and the owner's verbatim words in `said`. |
| `layouts/<name>.json` | `meta` (name, description) + `placements` (`x, y, rot`, optional `state`, `note`). Nothing else. |

## 4. Ingestion architecture
Four ingestion channels. Each one has a fixed landing zone and a fixed promotion path.

### 4a. Field measurements (the space)
1. Owner dictates notes in their own shorthand (`S wall @5ft: 59' 7 1/2"`).
2. Agent saves them **verbatim** to `measurements/raw/YYYY-MM-DD.md` and never edits them after that (corrections go in a new dated entry).
3. Interpretation, unit assumptions, derivations and open questions go in `measurements/processed/YYYY-MM-DD.md`.
4. Values are applied to `data/space.json` with `confidence: measured` and `source` pointing at the raw log.
5. `make validate` checks them: diagonals within 1", overlaps, blocked doors.

### 4b. LiDAR scan (cross-check, not truth)
- Phone LiDAR (e.g. Scaniverse, Polycam) exported as a decimated textured mesh (GLB) **and** a coloured point cloud (PLY).
  The point cloud keeps thin things the mesh loses (fan blades, truss chords, door tracks).
- Registered in `space.json` `reference_scans` with `rot_z`, `location` and `source_units`, and imported into a `Reference/Scan` collection.
- `make scan-views` renders gridded plan halves + wall elevations (mesh and point versions). Agents read positions and
  sizes off the grids (or crop the PLY numerically), and write findings to `measurements/processed/*-scan-extraction.md`
  and a `*-scan-inventory.md` (what's physically in the room now). Scan values are always `estimated`.
- `renders/<layout>/scan.png` overlays the model's walls on the scan to check alignment.

### 4c. Inventory items (`prompts/inventory-ingest.md`, `/ingest-item`)
One item per run. Steps: identify the exact variant (ask if vague) → reuse an existing id/placeholder if there is one →
research dims and clearances from the manufacturer, then retailers, then forums, citing a URL per number → map to the
w/d/h/front convention → cross-check against the scan if the item is already in the space → find images and textures, and
**look for an embedded 3D model first** (e.g. Shopify `<product>.js` media) → get **one batch approval** from the owner
before downloading → write the inventory entry + `reference/items/<id>/notes.md` → validate → **interview** for whatever
the web couldn't answer (max 6 batched questions, with options) → apply the answers and re-validate. Placement wishes that
come up are handed off to the rules prompt. It never moves items in layouts.

### 4d. Owner preferences (`prompts/placement-rules.md`, `/placement-rule`)
Natural language → one or more typed rules, with the verbatim quote kept. Default `prefer`; use `must` only for things the
owner calls non-negotiable (safety, power, fixed fixtures). It checks that ids exist, looks for conflicts with existing
rules (edit in place and keep the id, storing the old wording in `note`), and flags physically impossible rules. Validate
then reports which layouts break which rules, and the agent offers to fix the layouts.

### 4e. Item scans (`prompts/item-scan.md`, `/scan-item`)
The owner's own unit, scanned with a phone, becomes both the item's dimensions (`confidence: "scanned"`) and its asset.
The raw export is filed untouched in `reference/items/<id>/scan/`; `make scan-import` welds the mesh, finds and levels the
floor, cuts it away, drops scraps, squares the footprint and caps textures. One or two tape values check the scale.
Gaussian-splat exports are turned into a mesh first (`make splat-mesh`). `make scan-todo` lists items worth scanning.

### 4f. Layout changes (`prompts/layout-change.md`, `/layout`)
The owner's words → edits to one `layouts/*.json` (or a new option copied from an existing one), validated against a
baseline (no NEW errors/warnings), rendered as a tagged version, reported as before → after positions.

### 4g. 3D assets (`prompts/item-asset.md`, `/build-asset`)
Visual only. Placement and validation still use the inventory box. Source priority: vendor model (imported, squared,
rotated so the front is at -Y, unwanted parts dropped or recoloured, args saved in `import.json` so it can be rebuilt) →
procedural `build.py` (10-60 boxes in the item-local frame) → plain coloured box. `make asset-preview` renders a
front/side/top/iso sheet with the inventory box as an orange wireframe and a red FRONT arrow. The asset must match within
1.5". `asset.json` records a sha256 + `diff_in`, and validate checks both. Status stays `draft` until the owner approves it.

## 5. Validator (`scripts/validate.py`, plain Python + jsonschema)
- JSON Schema for all four data files; unique ids; reference integrity.
- Geometry: items inside the shell, height-aware overlaps (an upper cabinet over a counter is fine), clearances,
  heights vs ceiling, doors, sliding barn-door paths, overhead-door track envelopes, electrical panel working space, `keep_clear` zones.
- Rules: a broken `must` = ERROR, a broken `prefer` = WARN; priorities settle conflicts.
- **Walkability:** rasterises the floor into 3" cells and floods from the exterior doors. Every zone and every item's
  `access` side must be reachable with a 36" path (WARN if only 28").
- Exit code 1 on any ERROR, so `make all` stops before rendering.

## 6. Render pipeline (Blender, headless)
- `build_scene.py` builds walls (with openings cut out), roof/trusses, wall/ceiling/floor fixtures, inventory (asset or
  box; folded placements stay boxes), clearance volumes, and the optional scan → `blend/<layout>.blend`. 1 Blender unit = 1 inch.
- `render.py`: Workbench diagram look (fast, no lighting) or `--look photo` (EEVEE/Cycles with procedural materials sampled from
  the scan/vendor colours). Views: plan, 4 corner isos, eye-level views looking both ways, named room views, scan overlay.
  Each run also writes a versioned snapshot to `renders/<layout>/versions/vNN-<tag>/`.
- Make targets: `setup validate build render photo scan-views asset-import asset-preview scan-import splat-mesh scan-todo all clean`, with knobs
  `LAYOUT=`, `SCAN=0`, `ASSETS=0`, `VERSION=`, `ENGINE=cycles`, `ITEM=`, `SRC=`, `ARGS=`.

## 7. Multi-agent / multi-tool workflow
Worked on by several AI tools (Claude Code, Antigravity) in parallel, so **memory lives in the repo, not in any chat**:
- `AGENTS.md` (tool-neutral rules; `CLAUDE.md` just includes it). `CONTEXT.md` holds stable facts, conventions, and a table of known facts with their confidence.
- `.agents/HANDOFF.md`: current state, next 3 steps, blockers (rewritten at the end of every session, under 30 lines).
- `.agents/history/YYYY-MM-DD-<tool>-<topic>.md`: Goal / Done / Decisions / Open, under 40 lines, **append-only**.
- Rule: if HANDOFF disagrees with the code or data, trust the code and fix HANDOFF.
- Prompts are tool-neutral markdown in `prompts/` (including `session-handoff.md`). Claude Code slash commands are 10-line wrappers that say "follow `prompts/X.md` exactly".
- Guardrails written into the prompts: ask once before downloads, never run downloaded files, never get around captchas or 403s,
  never publish vendor assets, don't change layouts unless asked, owner approval before `status: approved`.
- Big binaries go in Git LFS (`gitattributes`); `blend/` and `renders/` are build outputs and are never hand-edited.

## 8. Extending it
New questions become new scripts that read the same data files, never a separate model. Examples in `extras/`:
- `extras/lighting/lighting.py`: copies a built layout into a metric scene, places fixture options, computes lux / shadow /
  glare analytically (BVH ray casts), cross-checks with Cycles renders, and writes a report.
- `extras/electrical/blueprint.py`: reads planned circuits and boxes from `data/electrical.json` and draws to-scale wall
  elevations and schedules (PDF/SVG/DXF), warning on boxes that land in door paths, on trim, or back-to-back.
Both are hard-wired to the original shop and are meant as worked examples for the agent to adapt.

## 9. Origin
Built for a 40x60 ft pole-barn shop over a few days with Claude Code and other agents. Order it was built in:
conventions + schema + first tape measurements → validator → Blender shell + diagram renders → LiDAR scan import and
overlay → layouts and zones → agent handoff files → inventory ingest (~25 items) → placement rules + walkability →
item assets and versioned renders → item scans → layout and handoff prompts → lighting and electrical studies.
