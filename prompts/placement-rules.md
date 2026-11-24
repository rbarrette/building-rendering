# Placement rules: capture how the owner wants things laid out

Turn the owner's preferences ("bench against the wall", "treadmill stored folded", "treadmill faces the TV") into
rules in `data/placement-rules.json`. Every layout must honour them, and `make validate` checks them.
This prompt records rules only. It does not move items unless the owner asks.

Units are decimal inches. Read `CONTEXT.md` for the frame first: +X east, +Y north, `rot` is CCW degrees, and an item's
**front faces south (-Y) at rot 0**. So rot 90 = front faces E, 180 = N, 270 = W. `right` is the +X side at rot 0.

## 1. Load context
- `data/placement-rules.json` (existing rules; next free id `R-NNN`), `data/inventory.json` (item ids, `access`,
  `folded`), `data/space.json` (walls `W-S/W-E/W-N/W-W`, interior walls `IW-*`, `zones`, `wall_items` such as
  outlets, doors and panels), and `layouts/*.json` (what's placed where today).
- Each item's `reference/items/<id>/notes.md` may already hold placement wishes from an ingest interview.

## 2. Turn each statement into rules
One statement can make several rules ("treadmill folded against the S wall, facing east" = 3 rules).
Keep the owner's words verbatim in `said` on every rule it produces.

| kind | means | fields |
|---|---|---|
| `in_zone` | footprint entirely inside one of the zones | `target`: zone id or list |
| `against` | that side of the item within `max_gap` of a wall (or another target) and facing it | `target`: wall / `IW-*` / `IW-*:S` (one face) / `any-wall` / item, or a list (any one); `side` (default `back`); `max_gap` (default 6) |
| `facing` | that side points a compass direction | `direction` N/S/E/W; `side` (default `front`); `tolerance` deg (default 20) |
| `facing_toward` | that side points at a target (TV, window, door, item, zone) | `target`; `side`; `tolerance` (default 45) |
| `state` | placed `open` or `folded` ("stored up" = `folded`) | `value` |
| `near` | footprint within `max_dist` of the target | `target`, `max_dist` |
| `away_from` | footprint at least `min_dist` from the target | `target`, `min_dist` |
| `placed` / `not_placed` | must (or must not) appear in the layout | none |
| `manual` | anything the fields can't express (sight lines, "feels open", heights) | `said` only; `item` optional |

Common fields: `id`, `item`, `kind`, `strength` (`must` makes a broken rule a validate ERROR, `prefer` makes it
a WARN), optional `layouts` (list of names; omit = every layout), `said`, `date` (today), `note`.

Translation tips:
- "Facing" is ambiguous. Decide which side is meant: for a treadmill or bike it's usually the way you look while
  using it (`front`, or the side named in `access`). For a rack against a wall it's the open side. If unsure, ask.
- "Against the wall" with no wall named means `target: "any-wall"`. A specific wall means `W-*`. An interior wall
  is `IW-<n>` (either face); `IW-1:S` / `IW-1:N` pins one face.
- "Either X or Y, but ideally X" means two rules: a `must` (or `prefer`) `against` with `target: [X, Y]`, plus a `prefer`
  `against` X. Layout options can then use either spot, and the second spot only shows as a WARN.
- "Next to X" means `near` with about 12-24in. "Not by the door" means `away_from` the door's wall item (e.g. `DR-MAIN`, `OH-1`).
- Use `must` only when the owner says it's non-negotiable (safety, power, a fixed fixture). Default to `prefer`.
- If the preference only applies to one option ("in option B the sim rigs go north"), set `layouts`.
- Never invent rules the owner didn't state. Things you infer go in the report as suggestions.

## 3. Check before writing
- Every `item` and `target` id exists. If the item isn't in inventory yet, suggest `/ingest-item` first.
- Look for conflicts with existing rules (same item, different zone/wall/direction, or `near` vs `away_from`).
  If the new statement replaces an old one, **edit that rule in place, keep its id**, and put the old wording in
  `note` ("was: ..."). Otherwise ask which wins.
- Look for physical impossibility: the item is taller than the ceiling (`shell.wall_height`), too deep for the wall run, or
  `against` a wall that's all doors or panel working space. Flag it rather than writing a rule that can never pass.

## 4. Interview (only if needed)
Ask only what you can't resolve. Batch the questions (at most 6), with options where possible. Use your tool's question
UI if it has one (Claude Code: AskUserQuestion), otherwise a numbered list. Typical gaps:
- Which wall or zone? Which way is "facing" for this item?
- Must or prefer?
- All layouts, or just one option?
- How tight: flush to the wall (2in), or room behind it for cables (6-12in)?
- Stored state vs in-use state: should the layout show it folded or open?

## 5. Write, validate, report
- Write the rules to `data/placement-rules.json` and set `meta.updated`. Don't touch layouts.
- Run `make validate`. Report each new or changed rule in one line (`R-012 prefer: freak-bench back against W-S <= 6in`),
  then every `[rule]` ERROR/WARN, which tells you which layouts now break which rules, and any `rule-skip` (item unplaced).
- Offer to fix the broken layouts. A fix means editing `layouts/*.json` until validate shows no `[rule]` errors and no new
  overlap/door/keep-clear errors, then `make all LAYOUT=<name>` (and `make photo LAYOUT=<name>`) to re-render.
