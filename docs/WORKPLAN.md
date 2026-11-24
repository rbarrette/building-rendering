# Work plan

Phases in order. Each has who does what and a "done when". The agent keeps track of where you are in
`.agents/HANDOFF.md`. Times are rough, for a garage-sized space.

## Phase 0: Setup (30-60 min)
- [ ] Own **private** repo created from the template; `git lfs install`.
- [ ] Python, Blender, Git LFS, agent installed; `BLENDER` path set in the `Makefile`.
- [ ] `make setup && make validate` gives 0 errors on the example; `make render LAYOUT=option-a` makes images.

**Done when:** you've seen the example garage's `plan.png` render on your machine.

## Phase 1: Conventions and interview (15-30 min)
- [ ] Agent interviews you (space type, goal, rooms/levels, north, origin corner, tools).
- [ ] `CONTEXT.md` filled: goal, origin, axes, wall names + left ends, measuring surface.
- [ ] Example data cleared; `space.json` holds the rough shell as `todo` placeholders.
- [ ] Non-rectangular space? Decide now: model one rectangle first, or have the agent extend the shell (GUIDE, "Houses and odd shapes").

**Done when:** `make validate` passes on the empty project and the first commit is made.

## Phase 2: Measure the shell (1-3 h on site)
- [ ] Inside length/width (two heights), both diagonals, ceiling height to the lowest member.
- [ ] Doors, windows, openings (offset from left end, w, h, sill, swing).
- [ ] Interior walls and their openings.
- [ ] Fixed constraints: panels, outlets, switches, vents, posts, stairs, drains, plumbing, water heater, HVAC.
- [ ] Notes saved verbatim → processed → `space.json`; open questions listed.

**Done when:** `make validate` has no errors, diagonals agree within ~1", and the plan render matches what you see standing in the room.

## Phase 3: Room scan (optional, 30 min + agent time)
- [ ] LiDAR scan exported as GLB (mesh) and PLY (points) into `reference/scans/`.
- [ ] Registered in `space.json` `reference_scans`, aligned; `renders/<layout>/scan.png` overlay lines up.
- [ ] `make scan-views`; agent writes `measurements/processed/*-scan-extraction.md` (things you didn't measure, colours)
      and a scan inventory (what's in the room now).

**Done when:** the walls in the overlay sit on the scan within a few inches and disagreements are listed as questions.

## Phase 4: Zones and intent (15 min)
- [ ] What goes roughly where ("gym along the south wall", "keep a car bay clear", "office in the NW corner").
- [ ] Recorded as `zones` in `space.json` (`keep_clear` for must-stay-empty areas).

**Done when:** the zones show in the plan render and you agree with them.

## Phase 5: Inventory (10-20 min per item, mostly agent time)
- [ ] List everything that matters for layout (big, heavy, needs clearance, needs power/water/vent).
- [ ] `/ingest-item` each one; approve downloads; answer the interview.
- [ ] Unknown or home-built items: tape `w/d/h`, or mark `scan.status: wanted`.

**Done when:** every item you want to place is in `inventory.json` with no `todo` on its dimensions, and `make validate` is clean.

## Phase 6: Placement rules (as they come up)
- [ ] `/placement-rule` for each preference, in your own words. Must vs prefer.

**Done when:** the things you'd tell a mover are written down as rules.

## Phase 7: Layouts (iterate)
- [ ] `/layout make option-a ...`: first full layout, 0 errors, rule warnings explained.
- [ ] Render, look at plan + eye-level views, adjust.
- [ ] Branch option-b/c for real alternatives; tag each version.

**Done when:** you have 1-3 options you'd actually choose between, each validated and rendered.

## Phase 8: Looks (optional)
- [ ] `make photo`: floor, wall paint, cabinet colours matched (paint codes, photos, swatches).
- [ ] `/build-asset` or `/scan-item` for the items you care about seeing.
- [ ] Named camera views from the spots you'll actually stand.

**Done when:** the photo renders are good enough to decide by (or to show the family).

## Phase 9: Studies (optional)
- [ ] Lighting (`extras/lighting/`), electrical (`extras/electrical/`), or anything else (sight lines, acoustics,
      shelf capacity). Each one is a new script that reads the same data.

## Every session
- Start: agent reads `.agents/HANDOFF.md`, the 3 latest `.agents/history/` files, `CONTEXT.md`.
- End: `/handoff` (history entry + HANDOFF rewrite); commit.
