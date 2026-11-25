# Extras: worked examples of studies built on the model

These came from the original shop project and are **hard-wired to it** (fixture lists, door names, a specific game
table, the accent wall). They're here so an agent can see how a study plugs into the same data. Don't expect them to run
on your project; ask the agent to adapt one.

## `lighting/lighting.py`: lighting simulation
Stages: calibrate (Blender light units vs real candela) → build (copies `blend/<layout>.blend` into a metric scene with
fixture options, an overhead-door open/closed toggle, people for shadow tests) → analyze (analytic lux grids, shadows,
glare, spill, a small optimiser, ray casts against the scene) → render (Cycles cross-checks, haze, scene views) →
report (`exports/lighting/report.md`). The plans themselves (fixtures, layers, table spots, scenes) come from
`data/lighting.json` through `scripts/lighting_plan.py`, the same file the core build/render/validate use; the
guesses about the room live in one `PARAMS` dict at the top so the owner can change and re-run. Manual table-head
plans (`heads_from: "manual"`) are analysed as given; optimiser plans get their heads written back.
Typical ask: *"compare three lighting packages for the game table and the work bench: lux, glare, shadows."*
Run with `Blender --background --python extras/lighting/lighting.py -- <stage>`.

## `electrical/blueprint.py`: electrical drawing
Reads `data/space.json` (a wall, its openings, trim, studs), a layout (furniture against the wall, for context) and
`data/electrical.json` (circuits and boxes), and draws to-scale wall elevations and box/circuit schedules as PDF, SVG and
DXF for an electrician. Warns when a box lands in a door's slide path, on trim, on a stud, or back-to-back with one on
the other face, and checks each box sits beside a stud. `routing` in `electrical.json` describes home runs (panel → header
→ truss → top plate → down beside the stud); the script draws two routing plans as a top view and wiring diagrams with
cable schedules, lengths and voltage drop. Needs `reportlab` and `ezdxf` (see `requirements.txt`).
Typical ask: *"plan outlets for the north wall: TV, desk, two counters; draw it for the electrician."*
