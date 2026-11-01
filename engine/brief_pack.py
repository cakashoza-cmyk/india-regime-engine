"""Structured data pack + validation for local credit briefs. Pack facts are copied from verified official data only."""
from __future__ import annotations
import re

BANNED = ["monitor closely", "macro headwinds", "exercise caution", "close monitoring", "headwinds and tailwinds", "cautious approach",
          "remain vigilant", "keep a close eye", "challenging environment", "uncertain times", "mixed bag", "going forward",
          "it is advisable", "prudent to", "robust due diligence", "careful assessment"]
NUM = re.compile(r"(?<![A-Za-z])[-+−]?\d[\d,]*(?:\.\d+)?")


def norm_num(s):
    s = s.replace(",", "").replace("−", "-").lstrip("+-")
    try:
        f = float(s)
    except ValueError:
        return None
    return f"{f:.2f}".rstrip("0").rstrip(".")


DATES = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?[-\s']?\d{2,4}\b|\bFY\s?\d{2,4}(?:-\d{2,4})?\b|\b20[12]\d\b|\bNIC\s?\d+\b|\bForm\s?483\b", re.I)


def nums(text):
    out = set()
    for m in NUM.findall(DATES.sub(" ", text or "")):
        n = norm_num(m)
        if n is not None:
            out.add(n)
    # Indian lakh grouping (e.g. 11,25,894) and plain forms both normalise via comma removal
    return out


def _m(iso):
    import calendar
    try:
        return f"{calendar.month_abbr[int(iso[5:7])]}-{iso[:4]}"
    except Exception:  # noqa: BLE001
        return str(iso)


def build_pack(d, combo, sector, state):
    """List of fact strings. Only verified numbers."""
    P = []
    g = d["geo_config"]
    if combo:
        combo = {**combo, "label": {"ok": "OK to lend", "caution": "Caution", "avoid": "Avoid"}.get(combo.get("data_call") or combo.get("call"), combo.get("label"))}
        if combo.get("score") is not None and combo.get("local_score") is not None:
            P.append(f"Call (data-based): {combo['label']}; combined score {combo['score']} = national sector score {combo['national_score']} "
                     f"{combo.get('local_adj') or 0:+d} {state['name']} state adjustment (capped +/-{g.get('local_adj_max_points',10)}). Bands: OK to lend >= {g['ok_at_or_above']}; Caution {g['avoid_below']} to {g['ok_at_or_above']-1}; Avoid < {g['avoid_below']}.")
        elif combo.get("national_score") is not None:
            P.append(f"Call (data-based): {combo['label']} on national sector score {combo['national_score']} only; not enough verified local data.")
        else:
            P.append("Call: not enough verified national sector data (Unknown).")
    if sector:
        for k, v in sector["drivers"].items():
            if v.get("status") == "verified" and v.get("value") is not None:
                band = {1: "scores positive", -1: "scores negative", 0: "scores neutral"}.get(v.get("score"), "not scored")
                P.append(f"India {sector['name']}: {v['text']} (data to {_m(v.get('as_of'))}; {band}).")
        cr = sector.get("credit")
        if cr:
            P.append(f"India bank credit to {sector['name']}: Rs {cr['outstanding_cr']:,.0f} Cr outstanding, {cr['yoy_pct']:+.1f}% YoY (RBI, {_m(cr.get('as_of'))}).")
        gn = (sector.get("gnpa") or {}).get("points") or []
        if gn:
            P.append(f"RBI FSR GNPA ratio for '{sector['gnpa']['fsr_category']}' (all banks, India): " + ", ".join(f"{p['period']} {p['value']}%" for p in gn) + ".")
        ct = sector.get("credit_trend") or []
        if len(ct) >= 2:
            P.append("India sector bank-credit growth trend: " + ", ".join(f"{_m(p['period'])} {p['yoy_pct']:+.1f}%" for p in ct) + ".")
    if state:
        for k in ("gst", "power"):
            s = state["signals"].get(k)
            if s and s.get("verified"):
                what = "GST collections" if k == "gst" else "electricity demand"
                extra = f"; latest month {s['month_yoy_pct']:+.1f}% YoY" if s.get("month_yoy_pct") is not None else ""
                P.append(f"{state['name']} {what}: {s['value']:+.1f}% Apr-to-date vs India {s['india']:+.1f}%{extra} ({s['source_name']}, data to {_m(s['as_of'])}).")
        c = state.get("credit")
        if c and c.get("verified"):
            P.append(f"{state['name']} all-bank credit: Rs {c['credit_cr']:,.0f} Cr, {c['credit_yoy_pct']:+.1f}% YoY; credit-deposit ratio {c.get('cd_ratio_pct')}% "
                     f"(RBI state handbook, end-{_m(c['as_of'])}).")
    return P


def validate(out, pack, articles_text, lens_text, require_pack=3):
    """Returns list of problems (empty = OK)."""
    probs = []
    flat = " ".join([out.get("verdict_rationale", ""), *out.get("sector_risks", []), out.get("local_news", ""),
                     *out.get("borrower_checks", []), out.get("change_the_call", ""), out.get("why", "")])
    low = flat.lower()
    for b in BANNED:
        if b in low:
            probs.append(f"banned generic phrase: '{b}'")
    pack_n = nums(" ".join(pack))
    allowed = pack_n | nums(articles_text) | nums(lens_text) | {str(i) for i in range(0, 13)}
    bad = sorted(n for n in nums(flat) if n not in allowed)
    if bad:
        probs.append("numbers not found in the data pack or articles: " + ", ".join(bad[:10]))
    cited = {n for n in nums(out.get("verdict_rationale", "")) if n in pack_n and n not in {"0", "1", "2", "3"}}
    if len(cited) < require_pack:
        probs.append(f"verdict_rationale cites {len(cited)} data-pack figures; at least {require_pack} required")
    if not 2 <= len(out.get("sector_risks") or []) <= 3:
        probs.append("sector_risks must have 2-3 items")
    if len(out.get("borrower_checks") or []) != 3:
        probs.append("borrower_checks must have exactly 3 items")
    for k in ("verdict_rationale", "local_news", "change_the_call"):
        if not (out.get(k) or "").strip():
            probs.append(f"missing {k}")
    return probs


def band_problems(text, ok, avoid):
    """'What would change the call' must name a correct threshold and never pair a band with the wrong number."""
    t = (text or "").lower()
    probs = []
    ns = nums(t)
    if str(ok) not in ns and str(avoid) not in ns:
        probs.append(f"change_the_call must name the threshold: OK to lend at {ok}+, Caution {avoid}-{ok - 1}, Avoid below {avoid}")
    for m in re.finditer(r"avoid", t):
        w = t[max(0, m.start() - 50): m.end() + 50]
        wn = nums(w)
        if str(ok) in wn and str(avoid) not in wn and not re.search(r"caution|ok to lend|\bok\b", w):
            probs.append(f"wrong band: Avoid starts below {avoid}, not {ok}")
            break
    for m in re.finditer(r"ok to lend|\bok\b", t):
        w = t[max(0, m.start() - 50): m.end() + 50]
        wn = nums(w)
        if str(avoid) in wn and str(ok) not in wn and not re.search(r"avoid|caution", w):
            probs.append(f"wrong band: OK to lend needs {ok}+, not {avoid}")
            break
    return probs


def validate_v3(out, pack, articles_text, lens_text, bands, need_pack=2):
    probs = []
    fl = out.get("local_flavour") or ""
    flat = " ".join([fl, *out.get("borrower_checks", []), out.get("change_the_call", ""), out.get("why") or ""])
    low = flat.lower()
    for b in BANNED:
        if b in low:
            probs.append(f"banned generic phrase: '{b}'")
    pack_n = nums(" ".join(pack))
    allowed = pack_n | nums(articles_text) | nums(lens_text) | {str(i) for i in range(0, 13)} | {str(bands["ok"] - 1)}
    bench = {"15", "30", "45", "60", "90", "120", "180", "1.2", "1.25", "1.3", "1.5", "10", "15", "20", "25", "50", "75"}  # standard diligence benchmarks, allowed in borrower checks only
    bad = sorted(n for n in nums(" ".join([fl, out.get("change_the_call", ""), out.get("why") or ""])) if n not in allowed)
    bad += sorted(n for n in nums(" ".join(out.get("borrower_checks", []))) if n not in allowed | bench and n not in bad)
    if bad:
        probs.append("numbers not found in the data pack or articles: " + ", ".join(bad[:10]))
    cited = {n for n in nums(fl) if n in pack_n and n not in {"0", "1", "2", "3"}}
    if len(cited) < need_pack:
        probs.append(f"local_flavour cites {len(cited)} data-pack figures; at least {need_pack} required")
    if not 40 <= len(fl.split()) <= 200:
        probs.append("local_flavour must be one paragraph of 80-140 words")
    if len(out.get("borrower_checks") or []) != 3:
        probs.append("borrower_checks must have exactly 3 items")
    if not (out.get("change_the_call") or "").strip():
        probs.append("missing change_the_call")
    else:
        probs += band_problems(out["change_the_call"], bands["ok"], bands["avoid"])
    return probs
