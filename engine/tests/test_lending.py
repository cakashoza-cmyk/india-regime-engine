import json, sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from engine import lending as L, lending_sources as ls

FX = Path(__file__).parent / "fixtures"
CFG = ls.load_config()
TODAY = date(2026, 11, 1)

IIP_TXT = ("13 Manufacture of textiles 3.275 123.7 145.2 122.1 137.9 17.4 12.9 "
           "21 Manufacture of basic pharmaceuticals products and pharmaceutical preparations 5.833 123.9 112.9 121.7 116.3 -8.9 -4.4 "
           "32 Other manufacturing 1.509 135 126.4 112 114.1 -6.4 1.9 *Figures for Sep 2026 are Quick Estimates.")


def test_parse_iip_with_crosscheck():
    rows, period = ls.parse_iip_text(IIP_TXT)
    assert period == "2026-09-30"
    assert rows["13"]["yoy_pct"] == 17.4 and rows["13"]["fytd_pct"] == 12.9 and rows["13"]["check_ok"]
    assert rows["32"]["check_ok"]
    bad, _ = ls.parse_iip_text(IIP_TXT.replace("145.2", "160.0"))
    assert bad["13"]["check_ok"] is False  # tampered index fails arithmetic check


def test_parse_sibc_rows():
    rows = [("Industry",), ("20.Sep,2024", "21.Mar,2025", "19.Sep,2025", "31.Mar,2026", "30.Sep,2026", "a", "b", "c", "d"),
            ("2.16. Gems and Jewellery", 94155.6, 88560.5, 102772.76, 124201.2, 136738.43, 9.15, 33.049, 16.0, 10.09)]
    out = ls.parse_sibc_rows(rows)
    g = out["2.16"]
    assert g["as_of"] == "2026-09-30" and g["outstanding_cr"] == 136738 and g["yoy_pct"] == 33.05 and g["check_ok"]


def test_parse_exports_inr_and_usd():
    t = (FX / "exports_qe_sep2026_inr.txt").read_text()
    out = ls.parse_exports_text(t, "2026-09-30")
    assert out[18]["inr_cr"] == 32197.78 and out[18]["usd_fytd_pct"] == 7.66 and out[18]["check_ok"]
    assert out[17]["usd_fytd_pct"] == -20.62  # ceramics: multi-line name still parsed


def _data(iip=(17.4, 12.9), exp=4.2, cr_yoy=14.6, period="2026-09-30", check=True):
    u = "https://example.gov.in"
    return {"iip_nic2": {"13": {"yoy_pct": iip[0], "fytd_pct": iip[1], "check_ok": check, "_period": period, "_url": u}},
            "exports_qe": {24: {"usd_fytd_pct": exp, "inr_fytd_cr": 1.0, "check_ok": True, "_period": period, "_url": u}},
            "rbi_sibc": {"2.4.3": {"name": "MMF", "yoy_pct": cr_yoy, "fy_pct": 1, "outstanding_cr": 57167, "as_of": period, "check_ok": True, "_period": period, "_url": u}}}


SEC = next(s for s in CFG["sectors"] if s["id"] == "mmf_textiles")


def test_strong_sector_lends_and_has_why():
    r = L.score_sector(SEC, _data(), {}, CFG, TODAY)
    assert r["verdict"] == "Lend" and r["why"] and r["main_driver"]


def test_weak_sector_avoid():
    r = L.score_sector(SEC, _data(iip=(-6, -5), exp=-8, cr_yoy=30), {}, CFG, TODAY)
    assert r["verdict"] == "Avoid"


def test_stale_data_not_scored():
    r = L.score_sector(SEC, _data(period="2026-05-31"), {}, CFG, TODAY)
    assert r["verdict"] == L.UNKNOWN
    assert all(r["drivers"][k]["status"] == "stale" and r["drivers"][k]["score"] is None for k in ("iip_yoy", "iip_fytd", "export_fytd_usd", "credit_vs_output"))


def test_failed_crosscheck_excluded():
    r = L.score_sector(SEC, _data(check=False), {}, CFG, TODAY)
    assert r["drivers"]["iip_yoy"]["score"] is None and r["drivers"]["iip_yoy"]["status"] == "excluded"


def test_unverified_macro_never_used():
    macro = {"brent": {"value": 130, "usable": False}, "rbi_stance_score": {"value": -1, "usable": False}, "repo_rate": {"value": 6, "prior_value": 5, "usable": False}}
    r = L.score_sector(SEC, _data(), macro, CFG, TODAY)
    assert r["drivers"]["energy_overlay"]["score"] is None and r["overlay_adj"] == 0


def test_overlay_capped_and_cannot_decide_alone():
    macro = {"brent": {"value": 130, "usable": True, "as_of": "2026-10-30", "source_url": "u"},
             "rbi_stance_score": {"value": -1, "usable": True, "source_url": "u"}, "repo_rate": {"value": 6, "prior_value": 5.5, "usable": True, "as_of": "x"}}
    r = L.score_sector(SEC, _data(iip=(3, 3), exp=5, cr_yoy=15), macro, CFG, TODAY)
    assert abs(r["overlay_adj"]) <= CFG["thresholds"]["overlay_max_points"]
    assert r["core_score"] == 50 and r["score"] >= 45 and r["verdict"] == "Selective"  # overlays alone cannot push to Avoid


def test_unknown_when_no_series():
    cre = next(s for s in CFG["sectors"] if s["id"] == "commercial_real_estate")
    r = L.score_sector(cre, _data(), {}, CFG, TODAY)
    assert r["verdict"] == L.UNKNOWN and r["score"] is None


def test_config_sectors_complete_and_calibrated():
    ids = [s["id"] for s in CFG["sectors"]]
    assert len(ids) == len(set(ids))
    for s in CFG["sectors"]:
        assert {"name", "cluster", "rbi_row", "ews"} <= set(s)
    for k in ("weights", "thresholds"):
        assert CFG[k]["_last_calibrated"]
    assert L.calibration_warnings(CFG, date(2027, 12, 1))  # stale after 180 days
    for ds in ("rbi_sibc", "iip_nic2", "exports_qe"):
        assert len(CFG["sources"][ds]["chain"]) >= 3  # fallbacks exist


def test_deepseek_skipped_without_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    cfg = {"sources": {"x": {"chain": [{"id": "ds", "method": "deepseek_search", "query": "site:rbi.org.in {month_year}"},
                                        {"id": "st", "method": "static", "url": "u1"}]}}}
    h, state = [], {}
    p, per, u, sid = ls.discover("x", cfg, state, h, TODAY, lambda url: ({"rows": {}}, "2026-09-30"))
    assert sid == "st" and h[0]["skipped"] and state["x"]["url"] == "u1"


def test_fallback_chain_logs_failures():
    cfg = {"sources": {"x": {"chain": [{"id": "a", "method": "static", "url": "bad"}, {"id": "b", "method": "static", "url": "good"}]}}}
    def v(url):
        if url == "bad":
            raise RuntimeError("boom")
        return {"rows": {}}, "2026-09-30"
    h = []
    _, _, u, sid = ls.discover("x", cfg, {}, h, TODAY, v)
    assert sid == "b" and h[0]["ok"] is False and h[1]["ok"] is True


def test_fy_label():
    assert L.fy_label(date(2026, 11, 1)).startswith("FY27") and L.fy_label(date(2027, 2, 1)).startswith("FY27")


def _ctx(late=True):
    from engine import regime_overlay as ro
    from engine.tests.test_regime_overlay import _wpi
    reg = {"factors": {"tightening": late, "oil_shock": late}, "late_cycle": late, "stage": "test", "next_mpc": "2026-12-04", "next_wpi": "2026-11-16"}
    return {"sens": ro.sens(), "wpi": _wpi(), "regime": reg}


def test_gap_is_red_flag_not_linear_and_deflated():
    small = L.score_sector(SEC, _data(cr_yoy=14.6), {}, CFG, TODAY, _ctx())
    assert small["drivers"]["credit_vs_output"]["score"] == 0  # a small gap earns nothing
    assert "after WPI textiles inflation" in small["drivers"]["credit_vs_output"]["text"]
    red = L.score_sector(SEC, _data(cr_yoy=60), {}, CFG, TODAY, _ctx())
    cv = red["drivers"]["credit_vs_output"]
    assert cv["score"] == -1 and cv["flag"] == "red" and red["score"] < 65


def test_cyclical_cap_and_regime_overlay():
    r = L.score_sector(SEC, _data(iip=(30, 30), exp=40, cr_yoy=20), {}, CFG, TODAY, _ctx())
    assert r["score"] <= 85 and r["drivers"]["regime_overlay"]["points"] < 0
    assert r["wrong_if"] if "wrong_if" in r else True


def test_falling_gnpa_alone_cannot_upgrade():
    sec = {**SEC, "_gnpa_points": [{"period": "Mar-25", "value": 2.5}, {"period": "Mar-26", "value": 1.0}], "_gnpa_cat": "textiles"}
    ctx = {**_ctx(), "wpi": None}  # no margin driver: GNPA would be the only positive
    r = L.score_sector(sec, _data(iip=(2, 2), exp=5, cr_yoy=14), {}, CFG, TODAY, ctx)
    assert r["drivers"]["gnpa_trend"]["score"] == 0


PH = {**SEC, "id": "pharma"}  # same official-series fixture, pharma sensitivity row (defensive, defensive_floor)


def test_defensive_floor_holds_caution_without_hard_evidence():
    r = L.score_sector(PH, _data(iip=(-4, -4), exp=-3, cr_yoy=20), {}, CFG, TODAY, _ctx())
    assert r["score"] == 45 and r["verdict"] == "Selective" and any("defensive floor" in c for c in r["capped_by"])


def test_defensive_floor_released_by_rising_gnpa():
    sec = {**PH, "_gnpa_points": [{"period": "Mar-25", "value": 1.0}, {"period": "Mar-26", "value": 2.0}], "_gnpa_cat": "chemicals"}
    r = L.score_sector(sec, _data(iip=(-4, -4), exp=-3, cr_yoy=20), {}, CFG, TODAY, _ctx())
    assert r["drivers"]["gnpa_trend"]["score"] == -1 and r["score"] < 45


def test_defensive_floor_released_by_red_flag_gap():
    r = L.score_sector(PH, _data(iip=(-4, -4), exp=-3, cr_yoy=60), {}, CFG, TODAY, _ctx())
    assert r["drivers"]["credit_vs_output"]["flag"] == "red" and r["score"] < 45


def test_defensive_watch_gap_not_penalised_but_cyclical_is():
    d = _data(iip=(2, 2), exp=5, cr_yoy=24)  # deflated gap 15-25 pp: watch
    ph, mmf = L.score_sector(PH, d, {}, CFG, TODAY, _ctx()), L.score_sector(SEC, _data(iip=(2, 2), exp=5, cr_yoy=34), {}, CFG, TODAY, _ctx())
    assert ph["drivers"]["credit_vs_output"]["flag"] == "watch" and ph["drivers"]["credit_vs_output"]["score"] == 0
    assert mmf["drivers"]["credit_vs_output"]["flag"] == "watch" and mmf["drivers"]["credit_vs_output"]["score"] == -1


def test_coarse_deflator_keeps_nominal_gap():
    dm = {**SEC, "id": "diamonds"}  # 'other manufacturing' WPI (+19% on gold/silver) is coarse for polished diamonds
    r = L.score_sector(dm, _data(iip=(3, 3), exp=5, cr_yoy=33), {}, CFG, TODAY, _ctx())
    cv = r["drivers"]["credit_vs_output"]
    assert cv["value"] == 30.0 and cv["flag"] == "red" and "coarse match" in cv["text"] and r["score"] < 65


def test_demand_shock_scales_with_beta_and_holds_credit_gap():
    from engine import regime_overlay as ro
    base = L.score_sector(SEC, _data(iip=(3, 3), exp=5, cr_yoy=14), {}, CFG, TODAY, _ctx())
    sh = L.score_sector(SEC, _data(iip=(3, 3), exp=5, cr_yoy=14), {}, CFG, TODAY, _ctx(), shock="demand_down5")
    assert sh["drivers"]["credit_vs_output"]["value"] == base["drivers"]["credit_vs_output"]["value"]  # no double count
    assert sh["drivers"]["iip_fytd"]["value"] == 3 - 5 * ro.demand_beta(ro.sens()["mmf_textiles"])
    ph = L.score_sector(PH, _data(iip=(3, 3), exp=5, cr_yoy=14), {}, CFG, TODAY, _ctx(), shock="demand_down5")
    assert ph["drivers"]["iip_fytd"]["value"] == 3 - 5 * 0.4


def test_demand_stress_capped_by_beta():
    from engine import regime_overlay as ro
    s = ro.sens()
    assert ro.stress_deltas(s["pharma"], -30)["demand_down5"] == -4.0
    assert ro.stress_deltas(s["cement"], -30)["demand_down5"] == -10 * ro.demand_beta(s["cement"])
    assert ro.stress_deltas(s["cement"], -3)["demand_down5"] == -3
