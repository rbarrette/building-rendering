# building-rendering

Build a **measured 3D model of a real space** (garage, shop, basement, a room or a whole floor of a house), fill it with
the things you own or want to buy, and try out layouts **by talking to an AI coding agent**. The agent researches each
item, records how you want things placed, checks every layout for collisions, blocked doors and walkways, and renders
it in Blender.

This repo is the workflow and tooling from a real project (a 40x60 ft pole-barn shop), with that project's data
removed. It comes with a tiny **example garage** so you can check everything works before you measure anything.

## The idea in one paragraph
The space and everything in it is **data** (JSON). Blender is only a renderer. Nobody drags objects around in a 3D
app: a layout is a small file of `item -> x, y, rotation`, a validator checks it, and a script renders it. That means an AI
agent can do nearly all the work by editing text, every number can be traced back to where it came from (tape measure,
spec sheet, scan, estimate), and trying a new idea is just a new layout file.

## Start here
1. Click **Use this template** on GitHub (or clone it) to make **your own repo**. Keep that repo **private**: it will
   end up holding measurements, photos and scans of your home.
2. Install the prerequisites (see [docs/GUIDE.md](docs/GUIDE.md#what-you-need)): Git + Git LFS, Python 3.10+, Blender,
   and an AI coding agent (Claude Code works well; any agent that reads `AGENTS.md` will do).
3. Open the repo in your agent and say:

   > Read START-HERE.md and set this project up for my space.

The agent will check your setup, render the example, interview you about your space, and walk you through the
[work plan](docs/WORKPLAN.md) one phase at a time.

## What's in here
| Path | What it is |
|---|---|
| [START-HERE.md](START-HERE.md) | The bootstrap instructions for the AI agent. |
| [docs/GUIDE.md](docs/GUIDE.md) | **The walkthrough for humans**: what you need, each step, how to work with the agent, lessons learned. |
| [docs/WORKPLAN.md](docs/WORKPLAN.md) | Phased checklist with "done when" for each phase. |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it's built: data model, ingestion paths, validator, render pipeline, agent memory. |
| `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `CONTEXT.md`, `.agents/` | Shared memory for AI agents (works across tools and sessions). |
| [docs/AGENT-TOOLS.md](docs/AGENT-TOOLS.md) | Using Codex, Cursor, Gemini, Antigravity and others alongside (or instead of) Claude Code; handoffs between tools. |
| `prompts/` | Reusable, tool-neutral prompts: ingest an item, placement rules, layout changes, 3D assets, item scans, handoff. |
| `.claude/commands/` | Claude Code slash commands that wrap the prompts (`/ingest-item`, `/layout`, ...). |
| `data/` | `space.json` (the room), `inventory.json` (things), `placement-rules.json` (your preferences), optional `lighting.json` (fixtures, plans, scenes), JSON schemas. **Example data: replace it.** |
| `layouts/` | One JSON file per layout option. |
| `scripts/` | Validator (plain Python) and Blender scripts (scene build, renders, scan views, asset tools). |
| `measurements/`, `reference/`, `assets/` | Field notes (raw and processed), photos/scans/spec sheets, per-item 3D assets. |
| `extras/` | Optional studies from the original project (lighting simulation, electrical blueprint). Adapt them if you want them. |

## Quick commands
```bash
make setup                      # one-time: .venv with jsonschema
make validate                   # schema + geometry + rule + walkability checks
make render LAYOUT=option-a     # build blend/option-a.blend and render plan/iso/eye views to renders/option-a/
make photo LAYOUT=option-a      # textured + lit renders (EEVEE; ENGINE=cycles for path tracing)
make photo LAYOUT=option-a LIGHTING=workshop SCENE=evening   # night render of a lighting plan -> renders/option-a/lighting/
make lighting-options           # every layout x lighting plan x scene at night (PLANS=.. SCENES=.. LIGHT_VIEWS=..)
```
Set the Blender path at the top of the `Makefile` (or pass `BLENDER=/path/to/blender`).

## License
MIT. See [LICENSE](LICENSE).
