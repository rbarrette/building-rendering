# Agent instructions

This project is worked on with several AI coding tools (Claude Code, Antigravity, others).
Shared memory lives in `.agents/`. Never rely on your own tool's chat history.

## At the start of every session
1. Read `.agents/HANDOFF.md`. It describes the current state and the next steps.
2. Skim the 3 most recent files in `.agents/history/`.
3. Read `CONTEXT.md` for stable project background (conventions, units, known facts).

## At the end of every session (or before a long pause)
Step by step in `prompts/session-handoff.md` (Claude Code: `/handoff [topic]`).
1. Create `.agents/history/YYYY-MM-DD-<tool>-<short-topic>.md` with these sections:
   - **Goal:** what this session set out to do
   - **Done:** what changed, with the files touched
   - **Decisions:** choices made and why
   - **Open / next:** unfinished work, known issues, ideas
   Keep it under 40 lines.
2. Rewrite `.agents/HANDOFF.md` (under 30 lines): current state, next 3 steps, blockers.
3. If stable facts changed (layout, measurements, pipeline), update `CONTEXT.md`.

## Rules
- Do not delete or overwrite anything in `.agents/history/`. Only add to it.
- Large binaries (renders, .blend files, scans) stay out of `.agents/`. Reference them by path.
- If HANDOFF.md disagrees with the code or data, trust the code and fix HANDOFF.md.
- `data/space.json` is the single source of truth. `measurements/raw/` is verbatim field notes; never edit it.
- Lighting (fixtures, existing lights and dimmers, plans, scenes) lives in `data/lighting.json` (optional); positions of
  installed lights stay in `data/space.json` `ceiling_items`. Layouts pick a plan with `"lighting": {"plan", "scene"}`.

## Reusable prompts
- `prompts/inventory-ingest.md`: research one item (dims, clearances, pictures, textures), add it to `data/inventory.json`,
  then interview the owner for gaps. Claude Code shortcut: `/ingest-item <item>`.
- `prompts/placement-rules.md`: turn the owner's placement preferences (walls, facing, folded, zones) into rules in
  `data/placement-rules.json`, which `make validate` checks. Claude Code shortcut: `/placement-rule <preference>`.
- `prompts/item-asset.md`: build a 3D render asset (vendor model or procedural) for one inventory item, check it against
  the inventory box in a preview sheet, record it as `asset` in `data/inventory.json`. Claude Code shortcut: `/build-asset <id>`.
- `prompts/item-scan.md`: bring in a 3D scan of the owner's unit (new or existing item): file the raw capture, clean it
  (`make scan-import`), tape-check the scale, update the item's dims (`confidence: "scanned"`) and use it as the asset.
  Claude Code shortcut: `/scan-item <id> <file>`; `/ingest-item <item> <file>` runs it for a new item.
  Capture tips: `reference/scans/_capture-guide.md`. What's left to scan: `make scan-todo`.
- `prompts/layout-change.md`: move items or make a new layout option from the owner's words: edit `layouts/*.json`,
  validate (no new flags), render a tagged version, report before/after. Claude Code shortcut: `/layout <request>`.
- `prompts/session-handoff.md`: the end-of-session steps above. Claude Code shortcut: `/handoff [topic]`.

## Starting a new project from the template
If `.agents/HANDOFF.md` says the project is fresh from the template, follow `START-HERE.md` first.
Human walkthrough: `docs/GUIDE.md`; checklist: `docs/WORKPLAN.md`; design: `docs/ARCHITECTURE.md`.

## Other AI tools
Not Claude Code? `docs/AGENT-TOOLS.md` says how each tool loads these rules, how to run the `prompts/` without slash
commands, and how to hand off between tools (or run two at once).
