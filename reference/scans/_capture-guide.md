# Scanning one item: capture guide

For item scans that go through `prompts/item-scan.md` (`/scan-item`). The whole-room scan is a
different job (see `docs/GUIDE.md`, step 3); this is one piece of furniture or equipment at a time. `make scan-todo` lists what's worth scanning.

## Before
- Pull the item out from walls and clutter so you can walk all the way round (~3 ft clear). Leave it on open floor:
  the import finds the floor and cuts it away, so a little floor in the scan is good.
- Even light; avoid direct sun stripes. Matte things scan best. Glass, chrome and glossy black come out holey or lumpy.
- Chairs: tuck them in or pull them away; don't let them touch the table if you want them as separate pieces.
  Scanning one chair on its own is better than six around the table.
- Have a tape measure handy: you'll be asked for 1-2 lengths (e.g. table top end to end, floor to top).

## Capture
- App: Scaniverse, Polycam, or Apple's Object Capture. Any of them is fine.
  - LiDAR mode is fast and gets the size right; textures are so-so.
  - Photo / photogrammetry / object mode gives better detail and texture, especially for wood; slower.
- Walk a full loop at about chest height, then a second loop lower (seat/leg height) and a pass over the top.
  Keep the phone 2-4 ft away and move slowly. Get under the table edge and between the legs.
- Prefer the highest quality / detail setting. One item per capture if you can.

## Export
- **GLB** (binary glTF), real-world scale / metres. USDZ, OBJ or FBX work too. No point cloud (PLY) for this.
- If the app offers it, export the raw mesh rather than a heavily simplified one; the import decimates to ~80k triangles.
- AirDrop/copy the file to the Mac and hand it over with the item: `/scan-item family-table ~/Downloads/table.glb`
  or `/ingest-item <new item> ~/Downloads/thing.glb`. The agent files it under `reference/items/<id>/scan/`.
