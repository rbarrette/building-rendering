# Handoff

Last updated: (template). Fresh from the building-rendering template.

## Current state
- Template as published: `data/space.json`, `inventory.json`, `placement-rules.json` and `layouts/option-a.json` hold a small
  **example garage** (24x24 ft, 4 items, 3 rules). `make validate`: 0 errors, 0 warnings. `make render LAYOUT=option-a` works.
- Nothing about the owner's space is recorded yet. `CONTEXT.md` still describes the example.

## Next 3 steps
1. Follow `START-HERE.md` Phase 0: check tools, set `BLENDER` in the Makefile, validate + render the example.
2. Phase 1: interview the owner, fill `CONTEXT.md`, replace the example data with the new shell (placeholders).
3. `docs/WORKPLAN.md` Phase 2: measure the shell.

## Blockers
- None. Blender: <path> (<version>) - set when known.
