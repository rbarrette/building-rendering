# Inventory ingestion prompt

Use: give the agent this file plus one item, e.g. "Ingest: the 6 ft steel workbench from Home Depot" or a product URL,
optionally with a 3D scan of the owner's unit. In Claude Code: `/ingest-item <item or URL> [scan file]`.
Works in any tool that can browse the web and edit files. To add a scan to an item that's already in, use
`prompts/item-scan.md` (`/scan-item`) instead.

---

You are adding ONE item to this project's inventory. Read `CONTEXT.md` (conventions) and `data/inventory.json` first.
Units are decimal inches. The goal is an entry that is accurate enough to place in a layout and render.

## 1. Identify the item
- Pin down the exact make, model, and variant/config (size, attachments, year, colour). If the input is vague
  ("a dumbbell rack"), list 2-4 likely products and ask before going further.
- Check `data/inventory.json` for an existing entry (same model, or a placeholder like `workbench`, `shelving`).
  If one exists, **update it in place and keep its `id`** (layouts reference it). Otherwise make a new kebab-case id.

## 2. Research dimensions
Search the manufacturer's product page and manual/spec sheet first, then retailers, then reviews/forums.
Collect, citing a URL for each number:
- **Footprint and height**: assembled, in use. Note what the number includes (bar holders, feet, handles, cables).
- **Folded/stowed dims** if it folds or collapses.
- **Required clearances**: from the manual (safety zones, e.g. treadmill run-off behind, fall zones, bar overhang on a rack,
  door swings, drawer/cabinet pull-out depth, ventilation gaps). If the manual has none, estimate from use and say so.
- **Extras worth keeping** in `specs`: weight, power (V / A / plug), max load, ceiling height needed in use
  (e.g. overhead press, pull-ups, swinging a golf club), anchoring needs, boxed size if not yet assembled.
- Convert mm/cm/ft to decimal inches (2 decimals). When sources disagree, prefer the manufacturer's current spec,
  record the others in the notes, and flag the gap if it is more than 1".

**Orientation mapping (important):** stand in front of the item, facing it.
`w` = left-right width, `d` = front-to-back depth, `h` = height. At rot 0 the front faces south (-Y).
"Front" = the side you normally face or use it from (console end of a treadmill, open side of a rack, doors of a cabinet).
Set `access` if you approach it from somewhere other than the front. Wall-mounted items get `"mount": "wall"`.

## 3. Check the LiDAR scan (if the item is already in the space)
Skip this if the item isn't in the space yet, or was still boxed on the scan date (see `reference_scans` in `data/space.json`).
Otherwise it's worth doing: it gives the item's current position, a size cross-check, and its real colour.
- Check `measurements/processed/*-scan-extraction.md` first: the item may already be noted there.
- Look at the gridded views in `renders/scan/` (run `make scan-views` if they're missing): plan halves for the footprint,
  wall elevations for height, `*-pts.png` for thin parts (frames, bars, cables) that the mesh lost.
- If you find it, read its extents off the grid. If you need more precision, crop the PLY points in that box with a short
  script (world frame per `reference_scans` alignment) and take the min/max.
- Record what you found in the notes file: position (x, y, rot), scan extents, and colour (sample the scan texture for `hex`).
  Scan values are `estimated` (+/- 2-3"): they cross-check the spec and never override it or a tape value. If the scan
  disagrees with the spec by more than ~3", ask about it in the interview (a different variant? attachments?).
- Don't change layouts. Mention the scanned position as a candidate placement in the report.

## 4. Find pictures and textures
Look for: a clean front view, side view, top view, a dimensioned drawing, a close-up of each main material
(frame paint, upholstery, wood, metal, mesh, rubber), and the colour/finish options.
- **Look for a 3D model first.** Many stores embed one in the product viewer (Shopify: `<product-url>.js` -> `media` with
  `media_type: "model"` gives GLB/USDZ URLs). It settles the orientation (measure an oriented bounding box; ignore
  lights/props), gives material colours, and often carries normal-map textures. Note the variant it shows.
- Make a short list of candidates: **filename, source URL, approximate size**. Prefer the manufacturer's images.
- **Ask the owner once to approve the downloads as a batch** before saving anything. Download only image/PDF files
  from the manufacturer or a major retailer; never run anything you downloaded.
- Save to `reference/items/<id>/images/` (views) and `reference/items/<id>/textures/` (material close-ups, swatches).
  Name them by view or part: `front.jpg`, `side.jpg`, `dims.png`, `tex-upholstery.jpg`. A spec sheet PDF goes in
  `reference/items/<id>/spec.pdf`. These are local reference only (they stay in Git LFS); do not republish them.
- If the manufacturer's site rate-limits a scripted fetch (HTTP 429), open the page once in a real browser tool if you have one.
  Never get around a captcha or a hard block (403): use major retailers' listings
  (Amazon, Walmart, Home Depot, Rogue, etc.) for images, or ask the owner for photos.
- If you can't get a usable texture, record the colour instead: sample or estimate an sRGB hex per part.

## 5. Write the entry
Add or update the item in `data/inventory.json` (schema: `data/schema/inventory.schema.json`). Shape:

```json
{
  "id": "power-rack",
  "name": "Power rack",
  "model": "<brand> <model> (with lat/low row)",
  "category": "gym",
  "owned": "owned",
  "w": 54.5, "d": 74, "h": 90,
  "clearance": {"front": 36, "sides": 24, "back": 6, "top": 6},
  "movable": false,
  "confidence": "spec",
  "source": "manufacturer spec <url>; clearances from manual p.4 + 86in bar overhang",
  "refs": {
    "product_url": "https://...",
    "manual_url": "https://...",
    "notes": "reference/items/power-rack/notes.md",
    "images": [{"path": "reference/items/power-rack/images/front.jpg", "url": "https://...", "view": "front"}],
    "textures": [{"path": "reference/items/power-rack/textures/tex-frame.jpg", "url": "https://...", "view": "frame", "kind": "photo-crop"}]
  },
  "appearance": {
    "finish": "matte black powder coat",
    "parts": [{"part": "frame", "color": "black", "hex": "#1C1C1C", "material": "powder-coated steel"}]
  },
  "specs": {"weight_lb": 600, "ceiling_needed_in": 96}
}
```

Rules:
- `confidence`: `spec` when dims come from the manufacturer, `measured` only if the owner taped them, `estimated` otherwise.
  `source` says where. Remove `"todo": true` only when w/d/h are spec or measured.
- Keep existing fields (e.g. `folded`, `access`, `note`) unless the research shows they're wrong.
- `owned`: owned | ordered | planned | considering.
- Don't place the item in a layout unless the owner asks.

## 5b. If the owner gave a scan
Run `prompts/item-scan.md` steps 2-7 now for this item. For the owner's unit, the scan's w/d/h replace the web spec
(tape still wins); keep the spec values in the notes, and ask about any gap over ~1 in. The scan becomes the asset, so
skip `/build-asset`. Without a scan, set `scan.status` from the interview (step 8): `wanted` or `not_needed`.

## 6. Write the notes file
`reference/items/<id>/notes.md`: the item identity, every source URL with what it gave you, conversions, conflicts
between sources, scan findings, assumptions, and the interview Q&A (the owner's answers verbatim). Keep it short.

## 7. Validate and report
Run `make validate`. Report: the final entry in one line (w x d x h, clearance, confidence), any flags
(e.g. taller than the ceiling height in `CONTEXT.md`, `ceiling_needed_in` over it, or wider than the narrowest door it must come in through),
what you downloaded, and what's still unknown.

## 8. Interview (only if needed)
After the research, ask only what the web can't answer. Batch the questions (at most 6) and give options where you can.
Use your tool's question UI if it has one (Claude Code: AskUserQuestion), otherwise a numbered list. Typical gaps:
- Which variant/config, and which attachments are actually installed?
- Is it owned, ordered, or being considered? How many?
- Your unit's colour/finish if it differs from the product photos.
- Have you measured it? (Tape values win: `w`, `d`, `h` at the widest points, in inches.)
- How is it used here: which side do you approach from, does it fold, does it get moved, is it bolted down or wall-mounted?
- Clearance in practice: bar length, door/drawer swing, how far you step back, anything stored on or around it.
- Worth a 3D scan? Suggest `wanted` when the owner's unit differs from any vendor model or none exists (family or
  home-built furniture, custom builds), `not_needed` for plain boxes (racks, cabinets) or a good vendor model.
  Record it as `"scan": {"status": ...}`; `make scan-todo` lists them.
- Where would you like it (zone or wall, which way it faces, stored folded)? Record the answers as rules with
  `prompts/placement-rules.md` (`/placement-rule`). Don't place it unless asked.

Apply the answers, update the notes file, re-run `make validate`, and report again. If the owner gives tape measurements,
also save them verbatim in `measurements/raw/YYYY-MM-DD.md` (append; never edit earlier text) per the measurement workflow.
