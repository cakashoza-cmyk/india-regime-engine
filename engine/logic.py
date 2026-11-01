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
    live = [r for r in rows if r.get("value") is not None and r["weight"] and not r.get("is_stale") and r.get("score") is not None]
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


def active_flips(fl):
    return [f["indicator"] for f in fl if f["is_flipped"]]


def invalidation_status(inv):
    sts = [i["status"] for i in inv]
    if "triggered" in sts:
        return "triggered"
    return "pending_data" if any(s.startswith("unknown") or s == "stale" for s in sts) else "none"


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
        st = "unknown" if v is None else "stale" if r.get("is_stale") else ("triggered" if (v > lvl if dirn == "above" else v < lvl) else "not triggered")
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


# ---- classify_regime (Akash's correction, Nov 2026). Numeric dial scores in [-1, 1]:
# growth +ve = rising; inflation score +ve = inflation FALLING (favourable), -ve = rising; liquidity +ve = easing.
POINT = 0.3
STRONG = 0.6
LIQ_PHRASE = {"accommodative": "accommodative liquidity",
              "neutral_behind_curve": "neutral liquidity (central bank behind curve)",
              "contracting": "contracting liquidity (central bank fighting)"}
ACTION = {"confirmed": "full playbook",
          "transitional": "preserve capital, watch for confirmation",
          "emerging": "no change; watch for dials to point",
          "contracting_but_unconfirmed": "no change; liquidity contracting but RBI-inflation/rates-biting not confirmed"}


def liquidity_modifier(liq):
    if liq is not None and liq >= POINT:
        return "accommodative"
    if liq is not None and liq <= -POINT:
        return "contracting"
    return "neutral_behind_curve"


def rates_biting(ind) -> int:
    """2-of-4 'rates are biting' check (assumption until Akash's code): repo rising, India 10Y rising,
    credit growth decelerating, Bank Nifty falling. Stale/missing signals count as not biting."""
    def dirn(k):
        r = ind.get(k)
        return r["direction"] if r and r.get("value") is not None and not r.get("is_stale") else 0
    return sum([dirn("repo_rate") > 0, dirn("india10y") > 0, dirn("credit_growth") < 0, dirn("nifty_bank") < 0])


def rbi_driver_is_inflation(stance) -> bool:
    """From stored RBI stance language. Default True (spec default) when no stance is stored."""
    if not stance:
        return True
    s = str(stance).lower()
    return not any(w in s for w in ("accommodat", "easing", "growth support"))


def classify_regime(g, inf, liq, rbi_driver_inflation=True, rates_biting_signals=0) -> dict:
    vals = {"growth": g, "inflation": inf, "liquidity": liq}
    pointing = {k: v for k, v in vals.items() if v is not None and abs(v) >= POINT}
    n = len(pointing)
    max_strength = max((abs(v) for v in pointing.values()), default=0.0)
    gup, gdn = g is not None and g >= POINT, g is not None and g <= -POINT
    iup, idn = inf is not None and inf <= -POINT, inf is not None and inf >= POINT  # inflation rising / falling
    mod = liquidity_modifier(liq)
    confirm_ok = bool(rbi_driver_inflation) and rates_biting_signals >= 2
    sub = None
    if gdn and iup:
        regime = "Stagflation"
    elif gup and iup and mod == "contracting":
        regime, sub = ("Tightening", None) if confirm_ok else ("Unclear", "contracting_but_unconfirmed")
    elif gup and iup:
        regime = "Reflation"
    elif gup and idn:
        regime = "Goldilocks"
    elif gdn and idn:
        regime = "Slowdown"
    else:
        regime = "Unclear"
    if n == 3 and max_strength >= STRONG:
        confidence = "high"
    elif n == 2 and max_strength >= STRONG:
        confidence = "medium_high"
    elif n >= 2:
        confidence = "medium"
    else:
        confidence = "low"
    if sub is None:
        if regime == "Unclear":
            sub = "emerging"
        else:
            sub = "transitional" if (n < 3 or max_strength < STRONG) else "confirmed"
    checks = {"growth_pointing": "growth" in pointing, "inflation_pointing": "inflation" in pointing,
              "liquidity_pointing": "liquidity" in pointing}
    liq_state = {"accommodative": "accommodative",
                 "contracting": "contracting (fighting)",
                 "neutral_behind_curve": "neutral, central bank behind the curve" if regime == "Stagflation" else "neutral"}[mod]
    full = f"{regime} ({sub}) with {LIQ_PHRASE[mod]}"
    return {"regime": regime, "sub_label": sub, "confidence": confidence, "liquidity_modifier": mod,
            "liquidity_state": liq_state, "full_label": full, "action": ACTION.get(sub, ""),
            "diagnostics": {"dials_pointing": n, "max_strength": round(max_strength, 3),
                            "margins": {k: (None if v is None else round(abs(v) - POINT, 3)) for k, v in vals.items()},
                            "checks": checks, "all_checks_passed": all(checks.values()),
                            "rbi_driver_inflation": bool(rbi_driver_inflation), "rates_biting_signals": rates_biting_signals}}
