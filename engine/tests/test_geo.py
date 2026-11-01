import json
from pathlib import Path
from engine import lending_sources as ls, lending_geo as geo
from engine.local_news import numbers_ok

FX = Path(__file__).parent / "fixtures"
G = {"weight_national": 0.6, "weight_local": 0.4, "local_gap_pp": 2.0, "ok_at_or_above": 65, "avoid_below": 45,
     "min_local_signals": 2, "ratings_min_n": 5, "ratings_disagree_above": 6}


def test_fsr_gnpa_chart_labels():
    r = ls.parse_fsr_subsector_bbox(FX.joinpath("fsr_jun2026_subsector_page.html").read_text())
    assert r["period"] == "Mar-26"
    assert r["gnpa"]["textiles"] == 3.1 and r["gnpa"]["chemicals"] == 0.7 and r["gnpa"]["construction"] == 2.4
    assert len(r["gnpa"]) == 14


def _st(gst, pw, india_g=6.0, india_p=7.0, ok=True):
    return {"name": "X", "signals": {"gst": {"value": gst, "india": india_g, "verified": ok, "source_name": "GSTN", "as_of": "2026-09-30"},
                                     "power": {"value": pw, "india": india_p, "verified": ok, "source_name": "CEA", "as_of": "2026-08-31"}}}


def _sec(score, verdict="Selective"):
    return {"id": "s", "name": "S", "score": score, "verdict": verdict,
            "drivers": {"iip_yoy": {"score": 1, "text": "output up", "as_of": "2026-09-30"}}}


def test_geo_blend_and_bands():
    v = geo.geo_verdict(_sec(70), _st(12, 12), G, "X")      # local 100 -> 0.6*70+0.4*100=82
    assert v["score"] == 82 and v["call"] == "ok" and len(v["reasons"]) <= 3
    v = geo.geo_verdict(_sec(50), _st(-1, 1), G, "X")       # local 0 -> 30
    assert v["call"] == "avoid"


def test_insufficient_local_falls_back_to_national():
    v = geo.geo_verdict(_sec(70), _st(12, 12, ok=False), G, "X")
    assert v["insufficient"] == "local" and v["call"] == "ok" and "Not enough local data" in v["message"]
    v = geo.geo_verdict(_sec(None, geo.UNKNOWN), _st(12, 12), G, "X")
    assert v["insufficient"] == "sector" and v["call"] is None


def test_local_news_only_adds_caution():
    cs = [{"geo_type": "state", "geo_id": "GJ", "state": "GJ", "sector": "s", "call": c} for c in ("ok", "avoid", "caution")]
    news = {"items": {"GJ|*": {"analysis": "x", "outlook_vs_macro": "Worse"}}}
    geo.attach_local(cs, news)
    assert [c["call"] for c in cs] == ["caution", "avoid", "caution"]
    cs = [{"geo_type": "state", "geo_id": "GJ", "state": "GJ", "sector": "s", "call": "avoid"}]
    geo.attach_local(cs, {"items": {"GJ|*": {"outlook_vs_macro": "Better"}}})
    assert cs[0]["call"] == "avoid"


def test_accuracy_gate_flags_mismatch():
    good = {"gst_state": {f"S{i}": {"fytd_check_ok": True} for i in range(10)}}
    assert geo.accuracy_checks(good)["gst_state"][0]
    bad = {"gst_state": {f"S{i}": {"fytd_check_ok": i < 5} for i in range(10)}}
    assert not geo.accuracy_checks(bad)["gst_state"][0]


def test_news_figure_guard():
    assert numbers_ok("orders fell 20%", "Exporters said orders fell 20% in September")
    assert not numbers_ok("orders fell 35%", "Exporters said orders fell 20%")


def test_live_output_shape():
    p = Path(__file__).resolve().parents[2] / "data" / "lending_latest.json"
    if not p.exists():
        return
    d = json.loads(p.read_text())
    for a in d["avoid_list"]:
        assert d["combos"][a["i"]]["call"] == "avoid"
    for c in d["combos"]:
        if c.get("call") and not c.get("insufficient"):
            assert c["reasons"], c
