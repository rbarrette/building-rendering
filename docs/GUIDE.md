# Guide: model your space with an AI agent

This is the human-readable walkthrough. Your AI agent reads it too, but it's written for you: what you'll do, what the
agent does, and what was learned the first time round. The step-by-step checklist is [WORKPLAN.md](WORKPLAN.md);
the technical design is [ARCHITECTURE.md](ARCHITECTURE.md).

## What you end up with
- A model of your space accurate to an inch or two, where every number says where it came from.
- An inventory of what you own or are considering: real dimensions, clearances (how much room a treadmill needs
  behind it, how far drawers pull out), colours, links to the product pages.
- Your preferences as **rules** ("bench against a wall", "treadmill stored folded", "TV visible from the couch").
- Several **layout options**, each checked automatically for overlaps, blocked doors, panel working space, items too
  tall for the ceiling, and whether you can actually walk to everything (36" paths).
- Renders: a top-down plan, corner isometrics, eye-level views, optional photo-style renders, and a version history.
- Optional: 3D models of your own furniture from phone scans, a lighting study, an electrical drawing.

The first project went from an empty folder to a measured, scanned, rendered shop with ~40 items and three layout
options in about two days of evenings. You can get a useful first render in a few hours.

## How it works
```
 your tape notes ──► measurements/raw/  (verbatim)  ──► measurements/processed/ (interpretation)
                                                              │
 phone LiDAR scan ──(cross-check)──────────────────► data/space.json      the room: walls, doors, windows, outlets, zones
 product research ──► /ingest-item ────────────────► data/inventory.json  the things
 what you say ──────► /placement-rule ─────────────► data/placement-rules.json
 what you ask for ──► /layout ─────────────────────► layouts/option-*.json   item -> x, y, rot
                                                              │
                              make validate  ──► errors / warnings
                              make render    ──► Blender ──► renders/<layout>/*.png  (+ versions/)
```
You talk; the agent writes JSON, runs the checks and renders, and shows you pictures. You never need to open
Blender (though you can).

## What you need
| | Required? | Notes |
|---|---|---|
| Computer (Mac, Windows or Linux) | yes | Developed on a Mac; the scripts are plain Python + Blender. |
| [Blender](https://www.blender.org/download/) 4.2 or newer | yes | Free. Run headless by the scripts. Tested on 5.x. |
| Python 3.10+ | yes | Only `jsonschema` is installed (`make setup`). |
| Git + [Git LFS](https://git-lfs.com) | yes | LFS keeps photos, scans and .blend files out of normal git history. |
| `make` | yes | Built in on Mac/Linux. Windows: use WSL, or ask the agent to run the commands in the Makefile directly. |
| An AI coding agent | yes | [Claude Code](https://claude.com/claude-code) works well and has the `/` commands. Others work from `AGENTS.md` + `prompts/`. It needs web access for item research. |
| Tape measure | yes | A laser measure makes long walls much easier. |
| Phone with LiDAR + scan app | optional, very useful | iPhone/iPad Pro with Scaniverse, Polycam or similar. Catches things you forgot to measure, and lets you scan furniture. |

## Step by step

### 0. Make your copy and check it works
Create your own **private** repo from this template, open it in your agent, and say *"Read START-HERE.md and set this up
for my space."* The agent checks your tools, sets the Blender path, and renders the bundled example garage. If you see
`renders/option-a/plan.png`, everything works.

### 1. Decide the conventions (10 minutes, and don't skip it)
Everything depends on a few choices, recorded in `CONTEXT.md`:
- **Units:** decimal inches in all data. You can speak feet-and-inches or metric; the agent converts.
- **Origin and axes:** a corner of the room at floor level (default: inside south-west corner), +X east, +Y north, +Z up.
  Compass names don't have to be true north. They just have to be consistent.
- **Wall names:** `W-S`, `W-E`, `W-N`, `W-W`. Things on walls (doors, windows, outlets, panels) are measured the way you
  actually measure them: stand inside facing the wall, measure from the wall's **left** end.
- **Item orientation:** an item's front faces south at rotation 0. `w` is left-right, `d` is front-to-back.
- **Confidence:** every number is `measured` (tape) > `scanned` (phone scan of your own item) > `spec` (manufacturer) >
  `estimated`. **Tape wins.**

### 2. Measure the space
Do it in passes and **dictate notes in your own shorthand**, e.g. `N wall: 23' 11 1/2"`, `garage door: 16' wide,
4' from E wall`, `outlet W wall 8'4" from S corner, 18" up`. The agent:
1. saves your words **verbatim** in `measurements/raw/YYYY-MM-DD.md` (photos of a notebook page are fine too),
2. writes its interpretation and open questions in `measurements/processed/YYYY-MM-DD.md`,
3. updates `data/space.json` with `confidence: measured` and a source pointing back at your note,
4. runs `make validate` and tells you what looks off.

What to measure, in order of value:
1. Inside length and width at two heights, plus **both diagonals** (that's how the validator knows the room is square).
2. Ceiling height (to the lowest thing: joists, trusses, beams, ductwork).
3. Every door, window and opening: offset from the wall's left end, width, height, sill height. Note door swing.
4. Interior walls: where they are, how thick, their openings.
5. Fixed things that limit placement: electrical panels (they need 36" clear in front), outlets, switches, vents, water
   heaters, posts, stairs, floor drains, plumbing stubs.
6. Your intent as **zones**: "gym goes here", "keep this strip clear for the car" (`keep_clear` zones must stay empty).

Say what surface you measured to (drywall, stud, trim). Write down anything you're unsure of; the agent tracks it as an open question.

### 3. Scan the room (optional, recommended)
A phone LiDAR scan of the whole room, exported as both a **textured mesh (GLB)** and a **point cloud (PLY)**, is a
superb cross-check. The point cloud keeps thin things the mesh loses (fan blades, door tracks, pipes). The agent
registers it in `space.json` `reference_scans`, aligns it, and `make scan-views` renders gridded plan and wall views
it can read positions off. The scan never overrides the tape (it's typically ±2-3"), but it catches what you missed
and gives real colours. It's also a fast way to inventory what's in the room today.

### 4. Inventory: one item at a time
`/ingest-item <name or product URL>` (or give the agent `prompts/inventory-ingest.md` and the item). The agent finds the
exact model, researches dimensions **and clearances** from the manual, looks for pictures and an embedded 3D model,
asks you **once** to approve downloads, writes the entry, then **interviews you** for what the web can't answer (your
variant, colour, how you use it, whether it folds, where you'd like it). For things with no product page (family
furniture, home-built), measure them or scan them (step 8).

### 5. Placement rules: say what you want
`/placement-rule <what you want, in your own words>`. One sentence can become several rules:
*"treadmill folded against the S wall, facing the TV"* → `state: folded`, `against W-S`, `facing_toward TV`.
Rules are `prefer` (a warning when broken) unless you say they're non-negotiable (`must`, an error). Your exact words
are kept with each rule, so later you can see why it exists.

### 6. Layouts: try options
`/layout <request>`: *"make option-a with the gym along the north wall"*, *"option-b like A but swap the bench and the
shelving"*. The agent edits `layouts/option-*.json`, runs `make validate` until there are no new problems, renders a
**tagged version** (`renders/option-b/versions/v03-swap-bench/`), and reports what moved. Old versions stay, so you can
compare. Branch freely: a new idea is a new file.

### 7. Renders
- `make render LAYOUT=option-a`: fast diagram look (plan, four corner isos, eye-level views both ways).
- `make photo LAYOUT=option-a`: lit, textured look (EEVEE; `ENGINE=cycles` for slower path tracing).
  Materials are defined in `scripts/build_scene.py` `style()`; the agent can match your floor, paint and cabinet
  colours from photos or paint codes.
- Want a view from a particular spot ("standing at the door looking at the TV")? Ask; the agent adds a named camera in
  `scripts/render.py`.

### 8. Make items look real (optional)
By default items are coloured boxes, which is enough for layout decisions. For things you care about seeing:
- `/build-asset <id>`: import the vendor's 3D model, or build a simple procedural one from photos. A preview sheet shows
  the model inside the inventory box with a FRONT arrow; it has to match within 1.5".
- `/scan-item <id> <file>`: scan your own piece with your phone (tips in `reference/scans/_capture-guide.md`). The scan
  becomes both the item's dimensions and its 3D model. Great for heirloom or home-built furniture.
Assets are visual only: placement and checks always use the inventory box.

### 9. Extras
`extras/` holds two studies from the original project, as starting points rather than drop-in tools:
a **lighting simulation** (fixture options compared on lux, glare, shadows) and an **electrical blueprint** (to-scale
wall elevations and box schedules as PDF/DXF). Ask the agent to adapt one when you get there.

## Working with the agent
- **Memory lives in the repo, not the chat.** Every session starts by reading `.agents/HANDOFF.md`, recent
  `.agents/history/` entries, and `CONTEXT.md`, and ends with `/handoff` (writes a history entry, rewrites HANDOFF).
  That's what lets you stop for a week, or switch tools, without losing anything.
- **One job per run.** One item per ingest, one request per layout change. Small steps validate cleanly.
- **Look at the pictures.** Ask for the plan and one eye-level view after each change. Most mistakes are obvious in a render.
- **Answer the interview questions.** That's where the agent learns what the web can't tell it.
- **Commit often.** Data, prompts and notes are small. Renders and .blend files are rebuildable (and ignored by git here).

## Houses and odd shapes
The scripts model one **rectangular shell** per project, with interior walls that split it into rooms. That covers a
garage, a shop, a basement, or a simple floor plan. For a house:
- **Start with one room or one level.** Get it measured and rendered before expanding.
- A rectangular floor plate with interior walls works today. Each interior wall can have doors and openings.
- L-shaped or non-rectangular footprints need the shell extended (for example a footprint polygon in `space.json`
  and in the validator's walkability grid). Ask the agent to make that change before you measure; it's a contained job.
- Several levels: one project per level is the easy way; a `level` field on everything is the thorough way.
- Ceiling heights that vary (vaulted, soffits, beams) can be modelled as ceiling items so the height checks see them.

## Lessons learned
- **Raw notes are sacred.** "59.3'" could be decimal feet or 59'3". Keeping the verbatim note made that fixable later.
- **Say what you measured to.** Stud vs drywall vs foam vs trim made 2-3" differences that mattered against tight fits.
- **Measure diagonals.** It's the only way to know the room is square.
- **Clearances are half the value.** Item footprints rarely collide; door swings, drawer pull-outs, bar overhangs,
  run-off zones and panel working space do. Make the agent find them in manuals.
- **Walk paths matter.** A layout with no overlaps can still leave the back corner unreachable. The walkability check catches it.
- **Scans are a cross-check, not truth.** Phone LiDAR is great for "what's there" and colours, and it's off by a few inches.
- **Ask for numbers with each change** (before → after positions, validate counts). It keeps the agent honest.
- **Keep your project private.** It holds your floor plan, photos of your home and what's in it.

## Troubleshooting
- *Blender not found*: set `BLENDER ?=` in the `Makefile`, or `make render BLENDER=/path/to/blender`.
- *Render is empty or the camera is inside a wall*: run `make validate` first; a shell with `todo` placeholders can be
  zero-sized. Then ask the agent to look at the render with you.
- *Validator floods warnings after a big change*: fix errors first, then warnings for the items you touched. Some
  warnings are fine to keep (the agent should say which and why).
- *Git complains about large files*: run `git lfs install` and check `.gitattributes`.
