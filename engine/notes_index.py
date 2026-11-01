"""Build data/notes/index.json: one small file with every saved note's final (news-adjusted) stance, for the map."""
import json, glob, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = {}
for p in sorted(glob.glob(os.path.join(ROOT, "data/notes/*.json"))):
    if p.endswith("index.json"):
        continue
    try:
        n = json.load(open(p))
    except Exception:  # noqa: BLE001
        continue
    if not n.get("call") or not n.get("state"):
        continue
    out[f"{n['state']}|{n['city']}|{n['ind']}"] = {"call": n["call"], "base": n.get("base_call"), "score": n.get("score"), "at": n.get("generated_at", "")[:16] + " IST"}
json.dump({"notes": out}, open(os.path.join(ROOT, "data/notes/index.json"), "w"), indent=0)
print(len(out), "notes indexed")
