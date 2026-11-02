"""Official WPI / Output PPI / trial Input PPI by NIC-2 group from the Office of the Economic Adviser (DPIIT)
monthly press release PDF (https://eaindustry.nic.in). Free, monthly, official. No AI involved.
Run: python3 engine/wpi.py  -> data/wpi_latest.json"""
from __future__ import annotations
import json, re, subprocess, sys, tempfile, urllib.request, ssl
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "wpi_latest.json"
IST = timezone(timedelta(hours=5, minutes=30))
BASE = "https://eaindustry.nic.in/press_release/press_release_{ym}.pdf"
# eaindustry.nic.in serves its leaf cert without the Let's Encrypt YR1 intermediate; we ship the public
# intermediate (letsencrypt.org/certs/gen-y/int-yr1.pem + root-yr-by-x1.pem) and still verify the chain.
CA_EXTRA = ROOT / "engine" / "certs" / "letsencrypt_yr1_chain.pem"

NIC = {  # NIC-2 code -> normalised group name key used in the release
    "10": "food products", "11": "beverages", "12": "tobacco products", "13": "textiles", "14": "wearing apparel",
    "15": "leather and related products", "16": "wood and products of wood", "17": "paper and paper products",
    "18": "printing and reproduction", "19": "coke and refined petroleum", "20": "chemicals and chemical products",
    "21": "pharma", "22": "rubber and plastic products", "23": "other non-metallic mineral products",
    "24": "basic metals", "25": "fabricated metal products", "26": "computer, electronic and optical",
    "27": "electrical equipment", "28": "machinery and equipment", "29": "motor vehicles", "30": "other transport equipment",
    "31": "furniture", "32": "other manufacturing"}


def _key(name):
    n = re.sub(r"\s+", " ", name.lower()).replace("non- ", "non-").replace("manufacture of ", "").replace("manufacture ", "").strip(" .")
    if "pharma" in n:
        return "pharma"
    if "motor vehicles" in n:
        return "motor vehicles"  # IPPI combines 29+30 in one row
    for k in NIC.values():
        if n.startswith(k[:14]):
            return k
    return n


def _records(block, ncols=6):
    """Rows start with '(X).' ; label text may wrap above/below the numbers. Returns {key: [values...]} (weight dropped)."""
    recs, cur = {}, None
    for line in block.splitlines():
        s = line.strip()
        if not s or "EMBARGO" in s or "embargoed" in s or s.startswith("Page ") or "of 14th" in s:
            continue
        m = re.match(r"^\(([A-Z])\)\.\s*(.*)$", s)
        if m or s.startswith(("Manufacturing Sector", "ALL COMMODITIES", "MANUFACTURED")):
            cur = {"name": "", "nums": []}
            recs[len(recs)] = cur
            s = m.group(2) if m else s
        if cur is None:
            continue
        toks = s.split()
        words = [t for t in toks if not re.fullmatch(r"-?\d+(\.\d+)?", t)]
        nums = [float(t) for t in toks if re.fullmatch(r"-?\d+(\.\d+)?", t)]
        if words and len(cur["nums"]) == 0 or (words and not nums):
            cur["name"] += " " + " ".join(words)
        elif words:
            cur["name"] += " " + " ".join(words)
        cur["nums"] += nums
    out = {}
    for r in recs.values():
        if len(r["nums"]) >= ncols + 1:
            out[_key(r["name"])] = r["nums"][1:ncols + 1]
    return out


def _between(t, a, b):
    """Text between two stand-alone annex header lines (e.g. a line that is only 'Annexure-II')."""
    ma = re.search(r"^\s*" + re.escape(a) + r"\s*$", t, re.M)
    if not ma:
        return ""
    mb = re.search(r"^\s*" + re.escape(b) + r"\s*$", t[ma.end():], re.M)
    return t[ma.start():ma.end() + (mb.start() if mb else len(t))]


def parse(text):
    head = re.search(r"WPI\) inflation for (\w+ \d{4}) is ([\d.]+) per cent", text)
    a2 = _between(text, "Annexure-II", "Annexure-III")
    months = re.search(r"Commodity\s+(\w{3}-\d\d)\s+(\w{3}-\d\d)\s+(\w{3}-\d\d)\s+(\w{3}-\d\d)\s+(\w{3}-\d\d)\s+(\w{3}-\d\d)", text, re.S)
    yoy = _records(_between(text, "Annexure-II", "Annexure-III"))
    fuel = {}
    for nm in ("Mineral Oils", "Crude Petroleum & Natural Gas", "Food Articles", "Non-Food Articles", "Electricity", "Coal and Lignite"):
        m = re.search(re.escape(nm) + r"\s+[\d.]+\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)", _between(text, "Annexure-II", "Annexure-III"))
        if m:
            fuel[nm] = [float(x) for x in m.groups()]
    allc = re.search(r"ALL COMMODITIES\s+[\d.]+\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)", a2, re.S)
    oppi = _records(_between(text, "Annexure-V", "Annexure-VI"))
    ippi = _records(text[text.find("Trial Input PPI for all Manufacturing Industries"):])
    return {"month": head.group(1) if head else None, "headline_yoy": float(head.group(2)) if head else None,
            "months": list(months.groups()) if months else None, "all_yoy": [float(x) for x in allc.groups()] if allc else None,
            "wpi_yoy": yoy, "fuel_primary_yoy": fuel, "oppi": oppi, "ippi": ippi}


def validate(p):
    errs = []
    if not p["month"] or p["headline_yoy"] is None:
        errs.append("headline not found")
    if p["all_yoy"] and p["headline_yoy"] is not None and abs(p["all_yoy"][-1] - p["headline_yoy"]) > 0.011:
        errs.append(f"annex all-commodities {p['all_yoy'][-1]} != headline {p['headline_yoy']}")
    for k, n in (("wpi_yoy", 20), ("oppi", 20), ("ippi", 18)):
        if len([x for x in p[k] if x in NIC.values()]) < n:
            errs.append(f"{k}: only {len(p[k])} groups parsed")
    for k, v in p["ippi"].items():
        if any(not (40 < x < 250) for x in v):
            errs.append(f"ippi {k} out of range")
    return errs


def _get(url):
    ctx = ssl.create_default_context()
    if CA_EXTRA.exists():
        ctx.load_verify_locations(str(CA_EXTRA))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
        return r.read()


def fetch(today=None):
    today = today or datetime.now(IST).date()
    y, m = today.year, today.month
    for _ in range(4):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        url = BASE.format(ym=f"{y}{m:02d}")
        try:
            b = _get(url)
        except Exception:  # noqa: BLE001
            continue
        if not b.startswith(b"%PDF"):
            continue
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(b); f.flush()
            text = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True, check=True).stdout
        p = parse(text)
        errs = validate(p)
        p.update(source_url=url, period=f"{y}-{m:02d}", fetched_ist=datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
                 errors=errs, source="Office of the Economic Adviser, DPIIT: WPI/Output PPI/trial Input PPI press release (base 2022-23)")
        return p
    return None


def load():
    return json.loads(OUT.read_text()) if OUT.exists() else None


if __name__ == "__main__":
    p = fetch()
    if not p or p["errors"]:
        print("WPI fetch/validate failed:", p and p["errors"]); sys.exit(2)
    OUT.write_text(json.dumps(p, indent=1))
    print(p["month"], p["headline_yoy"], len(p["wpi_yoy"]), len(p["oppi"]), len(p["ippi"]))
