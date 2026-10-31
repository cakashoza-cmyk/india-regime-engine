import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from engine import logic, sectors
from engine.score import score_indicator, direction


def I(**kw):
    return {k: {"value": 1.0, "direction": d, "is_stale": False} for k, d in kw.items()}


def test_score_types():
    assert score_indicator(6.0, 6.5, "rate") == 1
    assert score_indicator(6.5, 6.0, "rate") == -1
    assert score_indicator(6.0, 6.0, "rate") == 0
    assert score_indicator(5.0, 4.0, "inflation") == -1
    assert score_indicator(5.0, 4.0, "growth") == 1
    assert score_indicator(20, 15, "fragility") == -1
    assert score_indicator(1200, None, "flow") == 1 and score_indicator(-900, None, "flow") == -1
    assert score_indicator(None, 1, "growth") == 0


def test_majority_60():
    assert logic.majority(["rising", "rising", "falling"]) == "Rising"
    assert logic.majority(["rising", "falling"]) == "Unclear"
    assert logic.majority(["unknown", "flat"]) == "Unclear"


def test_transitory_and_single_series():
    assert logic.score_inflation(I(brent=1, cpi_core=-1)) == "Transitory"
    assert logic.score_inflation(I(brent=1)) == "Unclear"
    assert logic.score_inflation(I(cpi_core=1)) == "Rising"


def test_stale_does_not_vote():
    ind = I(gdp_yoy=1, iip_yoy=1)
    ind["gdp_yoy"]["is_stale"] = ind["iip_yoy"]["is_stale"] = True
    assert logic.score_growth(ind) == "Unclear"


def test_quadrants_and_tightening():
    assert logic.quadrant("Rising", "Falling") == "Goldilocks"
    assert logic.quadrant("Rising", "Rising") == "Reflation"
    assert logic.quadrant("Falling", "Transitory") == "Slowdown"
    assert logic.quadrant("Falling", "Rising") == "Stagflation"
    assert logic.quadrant("Unclear", "Rising") == "Unclear"
    assert logic.regime_label("Goldilocks", "Contracting", True) == "Tightening"
    assert logic.sleeve("Unclear", "Falling", "Expanding", "Unclear", False) == "Unclear"


def test_liquidity_hard():
    ind = I(us10y=1, dxy=1, usdinr_ref=1, india10y=1)
    assert logic.score_liquidity(ind) == ("Contracting", True)


def test_confirm():
    assert logic.confirm("Goldilocks", "Goldilocks") == "confirmed"
    assert logic.confirm("Slowdown", "Goldilocks") == "transitional"
    assert logic.confirm("Unclear", "Unclear") == "transitional"


def test_stage_stops_on_unknown():
    st, _ = logic.stage(I(repo_rate=-1, india10y=-1))
    assert st == 1  # credit unknown -> stops at 1
    st, _ = logic.stage(I(repo_rate=0, india10y=-1, credit_growth=1, nifty_bank=1, nifty_auto=-1))
    assert st == 3


def test_size_position():
    assert logic.size_position(1, 0.9, 0.1, "underpriced")["action"] == "wait"
    assert logic.size_position(3, 0.9, 0.1, "none")["size"] == 0
    assert logic.size_position(3, 0.9, 0.1, "underpriced")["size"] == 0.15
    assert logic.size_position(3, 0.9, 0.8, "underpriced")["size"] == 0.08  # round(0.075,2)
    assert logic.size_position(3, 0.5, 0.0, "overpriced")["paper"] is True


def test_marginal_driver_and_close_call():
    ch = {k: 0.0 for k in ("currency", "growth", "rates", "credit_growth", "asset_quality", "commodities",
                           "liquidity", "funding_cost", "risk_off", "inflation")}
    r = sectors.marginal_driver("IT", {**ch, "currency": 1.0})
    assert r["marginal_driver"] == "currency" and r["verdict"] == "own"
    r = sectors.marginal_driver("FMCG", {**ch, "risk_off": 1.0, "inflation": 1.0})
    assert r["verdict"] == "TOO CLOSE TO CALL"
    r = sectors.marginal_driver("AUTOS", {**ch, "rates": 1.0})
    assert r["verdict"] == "avoid"


def test_invalidations():
    ind = {"cpi_headline": {"value": 6.5, "is_stale": False}, "us10y": {"value": 4.0, "is_stale": True}}
    st = {x["indicator"]: x["status"] for x in logic.invalidations(ind)}
    assert st["cpi_headline"] == "triggered" and st["us10y"] == "unknown (stale)" and st["capacity_util"] == "unknown"
