# Extras: worked examples of studies built on the model

These came from the original shop project and are **hard-wired to it** (fixture lists, door names, a specific game
table, the accent wall). They're here so an agent can see how a study plugs into the same data. Don't expect them to run
on your project; ask the agent to adapt one.

## `lighting/lighting.py`: lighting simulation
Stages: calibrate (Blender light units vs real candela) → build (copies `blend/<layout>.blend` into a metric scene with
fixture options, an overhead-door open/closed toggle, people for shadow tests) → analyze (analytic lux grids, shadows,
glare, spill, a small optimiser, ray casts against the scene) → render (Cycles cross-checks, haze, scene views) →
report (`exports/lighting/report.md`). Every guess lives in one `PARAMS` dict at the top so the owner can change and re-run.
Typical ask: *"compare three lighting packages for the game table and the work bench: lux, glare, shadows."*
Run with `Blender --background --python extras/lighting/lighting.py -- <stage>`.

## `electrical/blueprint.py`: electrical drawing
Reads `data/space.json` (a wall, its openings, trim, studs), a layout (furniture against the wall, for context) and
`data/electrical.json` (circuits and boxes), and draws to-scale wall elevations and box/circuit schedules as PDF, SVG and
DXF for an electrician. Warns when a box lands in a door's slide path, on trim, on a stud, or back-to-back with one on
the other face. Needs `reportlab` and `ezdxf` (see `requirements.txt`).
Typical ask: *"plan outlets for the north wall: TV, desk, two counters; draw it for the electrician."*
