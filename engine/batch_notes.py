"""One-off full refresh: build v8-lean notes for every city x hub pair, split into chunks by industry (so each
industry cache is built once). Usage: python3 engine/batch_notes.py <chunk> <nchunks>. Stops cleanly on DeepSeek 402."""
import json, sys, subprocess, time, zlib
from datetime import datetime, timedelta
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import note_v6 as nv, search_adapter as sa  # noqa: E402

def commit(msg):
    subprocess.run("git add data/notes data/cache && (git diff --cached --quiet || (git commit -qm \"%s\" && for i in 1 2 3 4 5 6; do git pull -q --rebase origin main && git push -q && break; sleep $((RANDOM%%7+3)); done))" % msg, shell=True, cwd=ROOT)

def main():
    k, n = int(sys.argv[1]), int(sys.argv[2])
    r = json.loads((ROOT / "data/radar.json").read_text())
    ind = {i["id"]: i for i in r["industries"]}
    pairs = sorted([(c["state"], c["id"], h) for c in r["cities"] for h in c["hubs"] if h in ind], key=lambda p: (p[2], p[0], p[1]))
    from collections import Counter
    cnt, load, owner = Counter(p[2] for p in pairs), [0] * n, {}
    for ii, c in sorted(cnt.items(), key=lambda x: (-x[1], x[0])):  # greedy balance, industry stays in one chunk
        j = load.index(min(load)); owner[ii] = j; load[j] += c
    mine = [p for p in pairs if owner[p[2]] == k]
    done = skipped = failed = 0
    tot = {"search": 0, "fetch": 0, "chat": 0}
    fails = []
    for st, ct, ii in mine:
        if sa.OUT_OF_BALANCE:
            break
        out = ROOT / "data/notes" / f"{st}_{ct}_{ii}.json"
        if out.exists():
            try:
                g = json.loads(out.read_text()).get("generated_at", "")[:16]
                nowist = datetime.utcnow() + timedelta(hours=5, minutes=30)
                if g and nowist - datetime.strptime(g, "%Y-%m-%d %H:%M") < timedelta(hours=6):
                    skipped += 1
                    continue
            except Exception:  # noqa: BLE001
                pass
        nv.NOW = datetime.now(nv.IST)
        for key in nv.CALLS:
            nv.CALLS[key] = 0
        try:
            note = nv.build(st, ct, ii)
            for key in tot:
                tot[key] += nv.CALLS[key]
            if sa.OUT_OF_BALANCE:
                fails.append(f"{st}|{ct}|{ii}: 402 balance")
                break
            if not note.get("narrative"):
                raise RuntimeError("empty narrative")
            out.write_text(json.dumps(note, ensure_ascii=False, indent=1))
            done += 1
        except Exception as e:  # noqa: BLE001
            for key in tot:
                tot[key] += nv.CALLS[key]
            failed += 1
            fails.append(f"{st}|{ct}|{ii}: {str(e)[:100]}")
            if sa.OUT_OF_BALANCE:
                break
        if done and done % 8 == 0:
            commit(f"batch notes chunk {k}: {done}")
    commit(f"batch notes chunk {k}: final {done}")
    summ = {"chunk": k, "assigned": len(mine), "done": done, "skipped_fresh": skipped, "failed": failed, "calls": tot,
            "out_of_balance": sa.OUT_OF_BALANCE, "fails": fails}
    print("SUMMARY " + json.dumps(summ))
    Path(f"/tmp/summary_{k}.json").write_text(json.dumps(summ))

if __name__ == "__main__":
    main()
