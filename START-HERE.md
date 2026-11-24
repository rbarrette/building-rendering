# START HERE (instructions for the AI agent)

You are helping the owner set up a **building-rendering** project for their own space from this template: a measured
3D model of a real space, an inventory of things, placement rules, layout options and Blender renders, all driven by
data files you edit. The owner may not be a programmer. Explain briefly, ask few questions at a time, and do the
typing yourself.

Read these first: `README.md`, `docs/GUIDE.md`, `docs/WORKPLAN.md`, `AGENTS.md`, `CONTEXT.md`.
`docs/ARCHITECTURE.md` and `scripts/README.md` are the technical reference; read the parts you need.

## Phase 0: check the setup (do this before anything else)
1. Confirm this is the owner's **own copy** of the template (not the public template repo). If `git remote -v` points at
   the public template, help them make their own repo (GitHub "Use this template", **private**) before committing data.
2. Check tools and report what's missing, with the install command for their OS: `git`, `git lfs` (run `git lfs install`),
   `python3` (3.10+), Blender (find the executable; macOS: `/Applications/Blender.app/Contents/MacOS/Blender`).
   Set `BLENDER ?=` in the `Makefile` to the path you found.
3. `make setup`, then `make validate`: the example garage should give 0 errors, 0 warnings.
4. `make render LAYOUT=option-a` and look at `renders/option-a/plan.png` and `iso.png` yourself. Show the owner one of them
   so they see what they're building toward.
If anything fails, fix the environment (not the example data) and say what you changed.

## Phase 1: interview, then replace the example
Ask in one batch (use your question UI if you have one), with options where you can:
- What is the space (garage, shop, basement, one room, a whole floor)? What do they want to figure out
  (fit furniture, plan a gym, plan storage, compare layouts, lighting, outlets)?
- Is it roughly one rectangle? If not: how many rooms/levels, and which one to model first? (See GUIDE "Houses and
  odd shapes": start with one rectangular shell; interior walls split it into rooms.)
- Which way is north (roughly), and which corner will be the origin? Default: the inside SW corner, +X east, +Y north.
  If they don't know compass directions, pick "the wall with the main door = N" and write that down.
- Tools they have: tape measure, laser measure, a phone with LiDAR (iPhone/iPad Pro) and a scan app?
- Units they think in. The data is always decimal inches; you convert. (Metric owners: convert at the input, keep inches.)
- Which AI tools they'll use (only Claude Code, or several).

Then:
1. Replace the example: empty `data/inventory.json` items, `data/placement-rules.json` rules, and `layouts/option-a.json`
   placements; reset `data/space.json` to the new shell with `"todo": true` placeholders from the owner's rough numbers
   (say they're placeholders). Delete `assets/items/example-treadmill/` unless they want a treadmill. Keep the schemas.
2. Fill `CONTEXT.md` from the interview (space name, goal, origin, axes, wall names and left ends, what the tape will
   measure to). Keep the conventions section exact; it's what every later step depends on.
3. Rewrite `.agents/HANDOFF.md` (state: set up, nothing measured yet; next steps = WORKPLAN phase 2).
4. `make validate`, commit ("Start project from building-rendering template").

## After that
Follow `docs/WORKPLAN.md` phase by phase. At each phase: tell the owner what you need from them (measurements, a scan,
a list of items, preferences), do the data work, validate, render, and show the result. Use the prompts in `prompts/`
(or the `/` commands) for the repeatable jobs. End every session with `prompts/session-handoff.md`.

## Guardrails
- Field notes are saved **verbatim** in `measurements/raw/YYYY-MM-DD.md` before you interpret them; never edit them later.
- Tape measurements beat spec sheets, which beat scans and estimates. Tag every number with `confidence` and `source`.
- Never hand-edit `blend/` or `renders/`. Edit `data/` and `layouts/`, then run the scripts.
- Ask once before downloading files; never run downloaded files; don't get around captchas or blocked sites.
- Don't publish the owner's measurements, photos, scans, or vendor 3D models anywhere.
