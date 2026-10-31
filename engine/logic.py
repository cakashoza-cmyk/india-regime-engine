"""Pure decision logic (ported from AUDIT_LOGIC.md so web wizard and engine agree). Unit-tested."""
from __future__ import annotations
from engine.config import SECTOR_MAP

DIR = {1: "rising", -1: "falling", 0: "flat"}


def majority(dirs: list[str]) -> str:
    known = [d for d in dirs if d in ("rising", "falling")]
    if not known:
        return "Unclear"
    if known.count("rising") / len(known) >= 0.6:
        return "Rising"
    if known.count("falling") / len(known) >= 0.6:
        return "Falling"
    return "Unclear"


def _d(ind, key):
    r = ind.get(key)
    # stale (failed refresh or past max age) values are shown but do not vote
    return DIR.get(r["direction"], "unknown") if r and r.get("value") is not None and not r.get("is_stale") else "unknown"


def score_growth(ind):
    dirs = [_d(ind, k) for k in ("gdp_yoy", "iip_yoy", "gst_yoy")]
    if all(d == "unknown" for d in dirs):
        return "Unclear"  # Nifty is display-only for growth
    return majority(dirs)


def score_inflation(ind):
    core, food, crude, head = (_d(ind, k) for k in ("cpi_core", "food_inflation", "brent", "cpi_headline"))
    if (crude == "rising" or food == "rising") and core in ("flat", "falling"):
        return "Transitory"
    if core == "rising":
        return "Rising"
    if sum(d in ("rising", "falling", "flat") for d in (core, food, crude, head)) < 2:
        return "Unclear"  # engine safeguard: never label inflation off a single live series
    m = majority([core, food, crude, head])
    if m == "Rising":
        return "Rising"
    if m == "Falling":
        return "Falling"
    if core == "falling" and food != "rising" and crude != "rising":
        return "Falling"
    return m


def liq_signals(ind, stance=None):
    sig = {}
    if stance:
        sig["rbi_stance"] = {"tightening": "con", "accommodative": "exp"}.get(stance, "neutral")
    for k in ("us10y", "dxy", "usdinr_ref", "india10y", "repo_rate"):
        d = _d(ind, k)
        sig[k] = "con" if d == "rising" else ("exp" if d == "falling" else "unknown")
    f = ind.get("fii_net")
    if f and f.get("value") is not None:
        v = f["value"]
        sig["fii_net"] = "con" if v < -500 else ("exp" if v > 500 else "neutral")
    return sig


def score_liquidity(ind, stance=None):
    sig = [s for s in liq_signals(ind, stance).values() if s in ("con", "exp")]
    if not sig:
        return "Unclear", False
    con, n = sig.count("con"), len(sig)
    hard = con >= 4 or (n >= 3 and con / n >= 0.75)
    if con / n >= 0.6:
        return "Contracting", hard
    if (n - con) / n >= 0.6:
        return "Expanding", hard
    return "Unclear", hard


def quadrant(g, i):
    gUp, gDown = g == "Rising", g == "Falling"
    iUp, iDown = i == "Rising", i in ("Falling", "Transitory")
    if gUp and iDown: return "Goldilocks"
    if gUp and iUp: return "Reflation"
    if gDown and iDown: return "Slowdown"
    if gDown and iUp: return "Stagflation"
    return "Unclear"


def regime_label(quad, l, hard):
    """Spec labels. Tightening = hard liquidity contraction overriding a non-stagflation quadrant (assumption)."""
    if hard and l == "Contracting" and quad != "Stagflation":
        return "Tightening"
    return quad


def sleeve(g, i, l, quad, hard):
    if g == "Unclear" or quad == "Unclear": return "Unclear"
    if quad == "Stagflation" or (hard and l == "Contracting"): return "Risk-Off"
    if quad == "Reflation" and l == "Contracting": return "Selective cyclicals / dry powder"
    if g == "Rising" and i == "Falling" and l == "Expanding": return "Risk-On"
    if quad == "Goldilocks": return "Risk-On" if l == "Expanding" else "Staples-Defensives"
    if quad == "Reflation": return "Cyclicals-Reflation"
    if quad == "Slowdown" or g == "Falling": return "Staples-Defensives"
    if l == "Contracting": return "Staples-Defensives"
    return "Unclear"


def conviction(g, i, l, quad, slv):
    un = [g, i, l].count("Unclear")
    if un >= 2 or slv == "Unclear" or quad == "Unclear": return "Unclear"
    if i == "Transitory" or un == 1: return "Mixed"
    return "Strong"


def confirm(prev_label, label):
    """2-eval confirmation: same label as previous snapshot -> confirmed, else transitional."""
    return "confirmed" if prev_label == label and label not in (None, "Unclear") else "transitional"


def dial_score(rows):
    live = [r for r in rows if r.get("value") is not None and r["weight"] and not r.get("is_stale")]
    w = sum(r["weight"] for r in live)
    if not w:
        return None
    return round(sum(r["score"] * r["weight"] for r in live) / w, 3)


# ---- Stage 0-6 (7-gate sequence). Gate passes only on known data; unknown stops the climb.
def stage(ind, credit_dir=None):
    def dirn(k):
        r = ind.get(k)
        return r["direction"] if r and r.get("value") is not None and not r.get("is_stale") else None
    gates = [
        ("Rate peak", lambda: None if dirn("repo_rate") is None or dirn("india10y") is None
            else (dirn("repo_rate") <= 0 and dirn("india10y") <= 0)),
        ("Credit stabilises", lambda: None if dirn("credit_growth") is None else dirn("credit_growth") >= 0),
        ("Rate-sensitives bottom", lambda: None if dirn("nifty_bank") is None else dirn("nifty_bank") > 0),
        ("Cyclicals turn", lambda: None if dirn("nifty_auto") is None else dirn("nifty_auto") > 0),
        ("Commodities run", lambda: None if dirn("nifty_metal") is None or dirn("brent") is None
            else (dirn("nifty_metal") > 0 and dirn("brent") > 0)),
        ("Next tightening", lambda: None if dirn("repo_rate") is None else dirn("repo_rate") > 0),
    ]
    st, trail = 0, []
    for n, (name, fn) in enumerate(gates, 1):
        res = fn()
        trail.append({"gate": n, "name": name, "passed": res})
        if res is not True:
            break
        st = n
    return st, trail


def flips(ind, levels):
    out = []
    for k, lv in levels.items():
        r = ind.get(k)
        v = r.get("value") if r else None
        f = None if v is None or (r and r.get("is_stale")) else (v > lv["level"] if lv["direction"] == "above" else v < lv["level"])
        out.append({"indicator": k, "current_value": v, "flip_level": lv["level"], "flip_direction": lv["direction"],
                    "is_flipped": f, "tier": lv["tier"], "stale": bool(r and r.get("is_stale"))})
    return out


def gap(regime, vote):
    """Returns (gap_type, text). gap_type: underpriced | overpriced | none | unknown."""
    if regime in ("Unclear", None):
        return "unknown", "No macro regime call — cannot price a gap. STOP."
    if vote is None:
        return "unknown", f"Macro says {regime}; market vote unavailable."
    favourable = regime in ("Goldilocks", "Reflation")
    if favourable and vote < 0:
        return "underpriced", f"Macro {regime} but market voting down (vote {vote:+.2f}) — not yet priced."
    if not favourable and vote > 0:
        return "overpriced", f"Macro {regime} but market voting up (vote {vote:+.2f}) — market ignoring macro risk."
    return "none", f"Macro {regime} and market vote ({vote:+.2f}) agree — no gap left to harvest."


GAP_CONVICTION = {"Strong": 1.0, "Mixed": 0.6, "Unclear": 0.0}


def size_position(stage, gap_conviction, fragility_score, gap_type="unknown"):
    """Module 7. fragility_score here is 0..1 'how fragile' (= max(0, -fragility dial)). PAPER only."""
    if stage < 2:
        return {"action": "wait", "size": 0.0, "reason": f"stage {stage} < 2", "paper": True}
    if gap_type in ("none", "unknown", None):
        return {"action": "wait", "size": 0.0, "reason": f"gap {gap_type}", "paper": True}
    base = 0.10
    if gap_conviction > 0.7:
        base *= 1.5
    if fragility_score is not None and fragility_score > 0.7:
        base *= 0.5
    return {"action": "enter", "size": round(base, 2), "reason": "all gates clear", "paper": True}


INVALIDATIONS = [
    ("capacity_util", "above", 75.0, "Capacity utilisation > 75%"),
    ("cpi_headline", "above", 6.0, "CPI > 6.0%"),
    ("us10y", "above", 5.5, "US10Y > 5.5%"),
    ("usdinr_ref", "above", 98.0, "USDINR > 98"),
]


def invalidations(ind):
    out = []
    for k, dirn, lvl, label in INVALIDATIONS:
        r = ind.get(k)
        v = r.get("value") if r else None
        st = "unknown" if v is None else "unknown (stale)" if r.get("is_stale") else ("triggered" if (v > lvl if dirn == "above" else v < lvl) else "not triggered")
        out.append({"indicator": k, "rule": label, "value": v, "status": st})
    return out


def decide(slv, conv, status, fragility, coverage):
    """Sleeve-level view (own/avoid). STOP preferred when ambiguous; never force a label."""
    sec = SECTOR_MAP.get(slv, SECTOR_MAP["Unclear"])
    why = []
    if coverage < 0.6: why.append(f"live-data coverage {coverage:.0%} < 60%")
    if slv in (None, "Unclear"): why.append("sleeve Unclear")
    if conv in (None, "Unclear"): why.append("conviction Unclear")
    if why:
        return {"action": "STOP", "text": "STOP — no regime-driven call (" + "; ".join(why) + ").", **sec}
    return {"action": "PROCEED", "text": f"{slv} ({conv}, {status}{', fragility rising' if fragility is not None and fragility < 0 else ''}).", **sec}
