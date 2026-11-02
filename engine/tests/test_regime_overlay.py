import json
from datetime import date
from pathlib import Path
from engine import wpi, regime_overlay as ro

FX = Path(__file__).parent / "fixtures" / "wpi_press_release_202609.txt"


def _wpi():
    p = wpi.parse(FX.read_text())
    p.update(period="2026-09", errors=wpi.validate(p), source_url="x")
    return p


def test_wpi_parse_official_release():
    p = _wpi()
    assert p["errors"] == [] and p["headline_yoy"] == 11.39 and p["month"] == "September 2026"
    assert p["wpi_yoy"]["rubber and plastic products"][-1] == 13.47
    assert p["oppi"]["rubber and plastic products"] == [106.7, 107.0, 107.4, 107.3, 108.1, 109.5]
    assert p["ippi"]["rubber and plastic products"][0] == 109.8 and p["ippi"]["rubber and plastic products"][-1] == 115.5
    assert p["ippi"]["other non-metallic mineral products"][-1] == 95.8


def test_margin_driver_squeeze_and_unknown():
    s = json.loads(ro.SENS_P.read_text())["sectors"]
    m = ro.margin_driver(s["plastics"], _wpi())
    assert m["score"] == -1 and m["value"] == -2.6
    assert ro.margin_driver(s["nbfc"], _wpi()) is None          # unmapped stays unknown
    assert ro.margin_driver(s["edible_oil"], _wpi())["score"] is None  # group-level, display only


def _macro(repo=(5.5, 5.25), stance=-1, brent=113.0):
    v = lambda val, prior=None: {"value": val, "prior_value": prior, "usable": True, "as_of": "2026-10-30", "source_url": "u"}
    return {"repo_rate": v(*repo), "rbi_stance_score": v(stance), "brent": v(brent), "cpi_headline": v(5.54), "usdinr_ref": v(95.25)}


def test_regime_late_cycle_and_overlay():
    r = ro.regime(_macro(), _wpi(), date(2026, 11, 2))
    assert r["factors"]["tightening"] and r["factors"]["oil_shock"] and r["factors"]["cost_push"] and r["late_cycle"]
    s = json.loads(ro.SENS_P.read_text())["sectors"]
    pts, parts = ro.overlay_points(s["plastics"], {"factors": {"tightening": True, "oil_shock": True}})
    assert pts == -7.5 and dict(parts) == {"rates": -2.5, "crude": -5.0}
    pts, _ = ro.overlay_points(s["aviation"], {"factors": {"tightening": True, "oil_shock": True, "inr_weak": True}})
    assert pts == ro.OV_MIN


def test_regime_unknown_inputs_leave_factors_off():
    m = _macro(); m["brent"]["usable"] = False; m["repo_rate"]["prior_value"] = None
    r = ro.regime(m, None, date(2026, 11, 2))
    assert "oil_shock" not in r["factors"] and "tightening" not in r["factors"] and not r["late_cycle"]


def test_stress_deltas():
    s = json.loads(ro.SENS_P.read_text())["sectors"]["plastics"]
    d = ro.stress_deltas(s, -4)
    assert d == {"brent_up20": -5.0, "inr_down5": -2.5, "repo_up50": -5.0, "demand_down5": -4}
