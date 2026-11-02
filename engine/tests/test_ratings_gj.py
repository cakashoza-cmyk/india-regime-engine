from datetime import date
from engine import ratings_gj as rg


def test_classify_actions_from_agency_headlines():
    c = rg.classify_action
    assert c("X Ltd:Rating upgraded to 'Crisil BBB+ / Stable'")[0] == "upgrade"
    assert c("X Ltd:Ratings downgraded to 'Crisil BB / Negative'")[:3] == ("downgrade", True, True)
    assert c("X Ltd:Issuer Not Cooperating, based on best-available information; rating revised to 'Crisil D Issuer Not Cooperating'")[0] == "default"
    assert c("X Ltd:Issuer Not Cooperating, based on best-available information; rating continues to be 'Crisil B'")[:2] == ("inc_continues", False)
    assert c("X Ltd:Issuer Not Cooperating, based on best-available information; rating migrated to 'Crisil B+'")[:3] == ("inc_new", False, False)
    assert c("X Ltd:Rating outlook revised to 'Negative'; ratings reaffirmed")[:3] == ("outlook_negative", True, True)
    assert c("X Ltd:Rating outlook revised to 'Positive'; ratings reaffirmed")[2] is False
    assert c("X Ltd:Ratings placed on 'Rating Watch with Negative Implications'")[0] == "watch_negative"
    assert c("X Ltd:Ratings Reaffirmed")[:3] == ("reaffirm", True, False)
    assert c("X Ltd:Rating Withdrawn")[1] is False


def test_city_and_industry_keywords():
    a = "About the Company Incorporated in 2005, the company manufactures vitrified tiles at Morbi, Gujarat."
    assert rg.city_of(a) == "Morbi" and rg.industry_kw(a) == "ceramics"
    assert rg.industry_kw("About the Company Surat (Gujarat)-based firm trades in polished diamonds") == "diamonds"
    assert rg.industry_kw("About the Company A ship breaking unit at Alang, Gujarat") == "shipbreaking"


def _a(act, ind="ceramics", d="2026-10-01"):
    cnt, neg = {"upgrade": (1, 0), "downgrade": (1, 1), "reaffirm": (1, 0), "inc_new": (0, 0), "inc_continues": (0, 0), "default": (1, 1)}[act]
    return {"agency": "CRISIL", "date": d, "entity": "E", "city": None, "industry": ind, "action": act, "counted": bool(cnt), "negative": bool(neg), "url": "u"}


def test_score_min_actions_and_ratio():
    t = date(2026, 11, 2)
    s = rg.score([_a("downgrade")] * 4 + [_a("inc_continues")] * 10, t)["ceramics"]
    assert s["signal"] == "insufficient" and s["actions"] == 4 and s["inc_continues"] == 10
    s = rg.score([_a("downgrade"), _a("default"), _a("downgrade"), _a("inc_new"), _a("upgrade"), _a("reaffirm"), _a("reaffirm")], t)["ceramics"]
    assert s["actions"] == 6 and s["inc_new"] == 1  # INC recorded, not scored
    assert s["net_ratio"] == round((3 - 1) / 6, 2) and s["signal"] == "negative" and len(s["samples"]) == 3
    s = rg.score([_a("upgrade")] * 3 + [_a("reaffirm")] * 3, t)["ceramics"]
    assert s["signal"] == "neutral" and s["net_ratio"] == -0.5
    old = rg.score([_a("downgrade", d="2025-06-01")] * 6, t)["ceramics"]
    assert old["actions"] == 0 and old["signal"] == "insufficient"  # outside the 12-month window


def test_signal_only_makes_calls_more_cautious():
    calls = {"GJ|ceramics": ["ok", 70], "GJ|pharma": ["avoid", 30], "GJ|cement": ["ok", 77], "MH|ceramics": ["ok", 70]}
    sig = {"ceramics": {"signal": "negative", "engine": ["ceramics"]}, "pharma": {"signal": "negative", "engine": ["pharma"]},
           "cement": {"signal": "neutral", "engine": ["cement"]}}
    ch = rg.apply_to_calls(calls, sig)
    assert ch == ["GJ|ceramics"] and calls["GJ|ceramics"][0] == "caution" and calls["GJ|pharma"][0] == "avoid"
    assert calls["GJ|cement"][0] == "ok" and calls["MH|ceramics"][0] == "ok"
    sig2 = {"pharma": {"signal": "neutral", "engine": ["pharma"]}}
    rg.apply_to_calls(calls, sig2)
    assert calls["GJ|pharma"][0] == "avoid"  # never upgrades
