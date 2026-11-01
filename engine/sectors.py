"""Module 6 — Sector transmission. regime_changes x driver matrix -> marginal driver, own/avoid rank."""
from __future__ import annotations
import json
from pathlib import Path

MATRIX = json.loads((Path(__file__).resolve().parent / "sector_matrix.json").read_text())
CLOSE_CALL = 0.20  # assumption: top-2 |impact| within 20% and opposite signs -> Gate 5 STOP


def _avg(*xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def credit_level(ind):
    r = ind.get("credit_growth")
    v = r.get("value") if r else None
    if v is None:
        return None
    return 1 if v > 10 else (0 if v >= 5 else -1)


DRIVER_TEXT = {"currency": "INR weakening", "growth": "growth", "rates": "rates (repo + 10Y)", "funding_cost": "funding cost",
               "credit_level": "credit growth level", "credit_direction": "credit growth direction", "credit_growth": "credit growth",
               "asset_quality": "asset quality", "liquidity": "liquidity", "commodities": "commodities (Brent)",
               "inflation": "inflation", "risk_off": "risk-off"}


def regime_changes(ind: dict, dials: dict) -> tuple[dict, list[str]]:
    """Driver change in [-1,+1]; positive = driver rising. Null -> 0 and logged."""
    def d(k):
        r = ind.get(k)
        return r["direction"] if r and r.get("value") is not None else None
    neg = lambda x: None if x is None else -x  # noqa: E731
    rates = _avg(d("repo_rate"), d("india10y"))
    ch = {
        "currency": d("usdinr_ref"),                    # USDINR up = INR weaker
        "growth": dials.get("growth"),                  # growth dial score
        "rates": rates,                                 # repo + India 10Y direction
        "funding_cost": rates,                          # same inputs as rates in v1
        "credit_growth": d("credit_growth"),            # direction only (kept for back-compat)
        "credit_level": credit_level(ind),              # +1 >10%, 0 5-10%, -1 <5%
        "credit_direction": d("credit_growth"),         # +1 accelerating / -1 decelerating
        "asset_quality": None,                          # no feed in v1
        "liquidity": dials.get("liquidity"),            # liquidity dial score (+ = expanding)
        "commodities": d("brent"),
        "inflation": neg(dials.get("inflation")),       # dial +1 = disinflation, so flip
        "risk_off": neg(dials.get("fragility")),        # fragility dial +1 = calmer, so flip
    }
    log = [f"{k}: null -> 0" for k, v in ch.items() if v is None]
    return {k: (0.0 if v is None else float(v)) for k, v in ch.items()}, log


def marginal_driver(sector: str, changes: dict) -> dict:
    impacts = {drv: round(changes.get(drv, 0.0) * w, 3) for drv, w in MATRIX[sector].items()}
    ranked = sorted(impacts.items(), key=lambda kv: -abs(kv[1]))
    top_drv, top = ranked[0]
    close = False
    if len(ranked) > 1:
        a, b = ranked[0][1], ranked[1][1]
        close = a * b < 0 and abs(a) > 0 and (abs(a) - abs(b)) / abs(a) <= CLOSE_CALL
    verdict = "TOO CLOSE TO CALL" if close else ("own" if top > 0 else "avoid" if top < 0 else "neutral")
    nm = DRIVER_TEXT.get(top_drv, top_drv)
    if close:
        b_drv, b = ranked[1]
        why = f"{nm} ({top:+.2f}) and {DRIVER_TEXT.get(b_drv, b_drv)} ({b:+.2f}) pull in opposite directions within 20%."
    elif top == 0:
        why = "No driver is moving; no call."
    else:
        why = f"{nm[0].upper() + nm[1:]} is the biggest mover and it {'helps' if top > 0 else 'hurts'} this sector ({top:+.2f})."
    out = {"sector": sector, "marginal_driver": top_drv, "impact": top, "impacts": impacts, "verdict": verdict, "why": why}
    if sector == "PSU_BANKS":
        out["credit"] = {"level_score": changes.get("credit_level"), "direction_score": changes.get("credit_direction")}
    return out


def rank(changes: dict) -> list[dict]:
    out = [marginal_driver(s, changes) for s in MATRIX if not s.startswith("_")]
    return sorted(out, key=lambda r: -r["impact"])
