"""List inventory items by 3D-scan status, to plan a scanning session (`make scan-todo`).

  wanted       worth scanning (owner's unit differs from any vendor model, or no model exists)
  scanned      has a capture in reference/items/<id>/scan/ (see prompts/item-scan.md)
  not_needed   a box or vendor model is enough
  (unset)      not decided yet - triage these
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402


def main():
    inv = C.load_raw(C.ROOT / "data" / "inventory.json")
    groups = {"wanted": [], "(unset)": [], "scanned": [], "not_needed": []}
    for it in inv["items"]:
        sc = it.get("scan") or {}
        st = sc.get("status", "(unset)")
        a = it.get("asset") or {}
        asset = f"{a.get('source', 'box')}/{a.get('status', '-')}" if a else "box"
        extra = sc.get("note", "")
        groups.setdefault(st, []).append(f"  {it['id']:<26} {it.get('owned', '?'):<11} asset {asset:<18} {extra}")
    for st, rows in groups.items():
        print(f"{st} ({len(rows)})")
        print("\n".join(rows) if rows else "  -")
    print("\nScan with reference/scans/_capture-guide.md, then `/scan-item <id> <file>` (prompts/item-scan.md).")


if __name__ == "__main__":
    main()
