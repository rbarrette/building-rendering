# Change a layout (or make a new option)

Tool-neutral prompt (Claude Code, Antigravity, others). Claude Code: `/layout <request>`.
Input: what the owner wants, in their words, e.g. "move the grill next to the garage door in option-b" or
"make option-d like C but with the treadmill on the W wall". Output: an edited or new `layouts/<name>.json`,
validated, rendered as a new version, with a short before/after report.

## 0. Read first
- `CONTEXT.md` (inches, origin SW inside corner, +X east, +Y north, `rot` CCW from above, item FRONT faces -Y at rot 0,
  `x, y` = footprint centre; wall item conventions).
- The target layout(s) in `layouts/` (`meta.name`, `meta.description`, `placements` keyed by inventory id with
  `x, y, [z], rot, [state], note`), schema `data/schema/layout.schema.json`.
- `data/placement-rules.json`: the owner's standing preferences. Items involved, plus anything near where they go.
- `data/inventory.json` for the items' `w, d, h`, clearances, `access`, `folded`, `mount`.
- Zones and fixed features in `data/space.json` (doors, barn-door slide paths, panels, outlets, `keep_clear` zones).

## 1. Pin down the request
- Which layout? If the owner didn't say, ask. "Like option-c but ..." means copy option-c to a NEW file; don't edit C.
  New layouts are `layouts/option-<next letter>.json` unless the owner names it.
- Is this a one-off move for this option, or a standing preference ("grill always by the big door")? A standing
  preference becomes a rule via `prompts/placement-rules.md` (`/placement-rule`) as well as the move.
- If the request conflicts with a `must` rule, say which rule and ask: break it in this option only (note it), or change the rule.
- Ambiguous position ("by the door") -> propose 1-2 concrete spots with coordinates and pick the one that validates.

## 2. Baseline
Run `make validate LAYOUT=<name>` before editing (skip for a brand new copy) and keep the counts and the flags that mention
the items you'll touch. The goal is no NEW errors or warnings, not necessarily zero: some warnings are pre-existing.

## 3. Edit the data (never Blender)
- Work out coordinates from the conventions: for an item against a wall at rot 180 (front facing north, back on W-S),
  `y = d/2 + back clearance`; on W-N at rot 0, `y = width_y - d/2 - back`; turned 90/270, swap w and d.
  Wall-mounted items need `z`. Stacked items (printer on a bench, kart under a rack) need `z` and a rule/note saying so.
- Update each moved item's `note` (where and why, rule ids). Update `meta.name` / `meta.description` so they describe
  the option as it is now. Remove items the owner wants out; don't leave stale notes.
- Only touch the items the request is about, plus anything that must move to make room (say so in the report).

## 4. Validate and iterate
`make validate LAYOUT=<name>`. Fix new overlaps, blocked doors/slide paths, panel working space, walkability (36 in path)
and broken rules by nudging positions. If a flag can't be fixed without breaking the request, keep it and report it.

## 5. Render a version
- `make render LAYOUT=<name> VERSION=<short-tag>` (diagram views) and, when the look matters or the owner asked,
  `make photo LAYOUT=<name> VERSION=<short-tag>`. The tag is kebab-case and says what changed (`grill-by-garage-door`).
  Each run snapshots into `renders/<name>/versions/vNN-<tag>/` with the layout JSON, so old versions stay comparable.
- Look at the plan and the eye-level views that show the changed area (`iso*`, `eye-*`, and any named room views you added in `scripts/render.py`) before reporting.

## 6. Report
In a few lines: layout + version, each move (`item: (x,y,rot) -> (x,y,rot)`, why), validate counts before -> after and
any new or remaining flags, rules added or broken, and the render paths to look at (plan + the best view of the change).
Don't commit unless asked. If several layouts should get the same change, ask before applying it to the others.
