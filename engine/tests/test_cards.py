"""Lending Radar simple card (engine/cards.py): every displayed number must carry a source URL and a date."""
import json, re, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from engine import cards as C

TODAY = date(2026, 11, 16)
COMMON, STATES = C.build(today=TODAY, write=False)
D = json.loads((ROOT / "data" / "radar.json").read_text())
DIGIT = re.compile(r"\d")


def _src_ok(s):
    return bool(s.get("url")) and (s["url"].startswith("http") or s["url"].endswith(".html")) and bool(s.get("as_of")) and bool(s.get("label"))


def _all_lines():
    for k, v in COMMON["industries"].items():
        for sec in ("what", "money"):
            for l in v[sec]:
                yield f"industry {k}/{sec}", l
    for k, v in COMMON["local"].items():
        for sec in ("what", "money"):
            for l in v[sec]:
                yield f"local {k}/{sec}", l
    for st, s in STATES.items():
        for par, v in s["views"].items():
            for sec in ("why", "move"):
                for l in v[sec]:
                    yield f"{st}|{par}/{sec}", l
            if v.get("conf", {}).get("text") and DIGIT.search(v["conf"]["text"]):
                yield f"{st}|{par}/conf", {"t": v["conf"]["text"], "src": v["conf"].get("src", [])}


def test_every_number_has_source_and_date():
    bad = [(w, l["t"]) for w, l in _all_lines() if DIGIT.search(l["t"]) and (not l.get("src") or not all(_src_ok(s) for s in l["src"]))]
    assert not bad, bad[:5]


def test_descriptive_text_has_no_unsourced_figures():
    for w, l in _all_lines():
        if l.get("kind") == "desc":
            assert not DIGIT.search(l["t"]), (w, l["t"])
    for k, v in list(COMMON["industries"].items()) + list(COMMON["local"].items()):
        for c in v["checks"]:
            assert not DIGIT.search(c), (k, c)
    plain = json.loads((ROOT / "engine" / "plain_industries.json").read_text())
    assert not any(DIGIT.search(t) for t in plain["what"].values())


def test_news_items_have_link_and_date_and_stale_flag():
    for st, s in STATES.items():
        for k, n in s["news"].items():
            for it in n["items"]:
                assert it["url"].startswith("http") and re.match(r"\d{4}-\d{2}-\d{2}$", it["date"]), (k, it)
                assert it["stale"] == ((TODAY - date.fromisoformat(it["date"])).days > C.NEWS_STALE_DAYS)
            assert n["fresh"] == any(not i["stale"] for i in n["items"])


def test_old_news_is_stale_and_cannot_count_as_fresh():
    city = {"id": "gj_surat", "name": "Surat", "state": "GJ"}
    notes = {"GJ_gj_surat_mmf_textiles": {"news_direction": "Worse", "articles": [
        {"title": "Surat weavers shut looms", "url": "https://example.org/a", "date": "2026-05-01", "kind": "local"}]}}
    n = C.news_for(city, "mmf_textiles", "Gujarat", notes, {}, TODAY)
    assert n["items"][0]["stale"] and not n["fresh"] and n["worse"]


def test_view_matches_live_engine_call_and_thresholds():
    th = COMMON["thresholds"]
    assert th == {"ok": D["geo"]["ok_at_or_above"], "avoid": D["geo"]["avoid_below"]}
    for key, e in D["calls"].items():
        st, par = key.split("|")
        if st not in STATES:
            continue
        v = STATES[st]["views"][par]
        assert v["score"] == e[1]
        if e[1] is not None:
            assert v["call"] == (e[0] or C.band(e[1], th))
            head = v["move"][0]["t"]
            assert head.startswith(f"Score {e[1]}:")
            if e[1] < th["ok"]:
                gap = th["ok"] - e[1]
                assert f"{gap} point" in head
            assert v["conf"]["level"] in ("low", "medium")
        else:
            assert v["call"] is None and v["why"] == []


def test_every_map_pair_resolves_to_a_card():
    for c in D["cities"]:
        s = STATES[c["state"]]
        for ind in D["industries"]:
            assert ind["id"] in COMMON["industries"]
            assert ind["parent"] in s["views"], (c["id"], ind["id"])


def test_surat_mmf_sample_has_five_sections_with_sources():
    ind, loc = COMMON["industries"]["mmf_textiles"], COMMON["local"]["gj_surat|mmf_textiles"]
    v = STATES["GJ"]["views"]["mmf_textiles"]
    assert loc["what"] and loc["money"] and loc["checks"]
    assert any(l["kind"] == "filing" for l in ind["money"])
    if v["score"] is None:   # data-dependent: an unscored refresh must degrade to grey, not break the pipeline
        assert v["call"] is None and v["move"]
        return
    assert v["call"] in ("ok", "caution", "avoid") and 1 <= len(v["why"]) <= 5 and len(v["move"]) >= 1
    assert all(l["src"] for l in v["why"])
    assert "{city}" in v["conf"]["text"]


def test_half_year_filing_is_split_into_quarter():
    prev = {"m": {"revenue": 1049.4, "ebitda": 77.76, "revenue_ytd": 1049.4}}
    half = {"m": {"revenue": 2125.33, "ebitda": 166.69, "revenue_ytd": None}}
    vals, derived = C._quarter_vals(half, ["revenue", "ebitda"], prev)
    assert derived and round(vals["revenue"], 2) == 1075.93 and round(vals["ebitda"], 2) == 88.93
    vals, derived = C._quarter_vals({"m": {"revenue": 1100, "ebitda": 80, "revenue_ytd": 2149}}, ["revenue", "ebitda"], prev)
    assert not derived and vals["revenue"] == 1100


def test_workflows_are_valid_yaml_and_rebuild_cards():
    try:
        import yaml
    except ImportError:
        return
    for wf in ("engine.yml", "detective.yml"):
        y = yaml.safe_load((ROOT / ".github" / "workflows" / wf).read_text())
        runs = " ".join(str(s.get("run", "")) for j in y["jobs"].values() for s in j["steps"])
        assert "engine/cards.py" in runs and "data/cards" in runs, wf


PLAIN = json.loads((ROOT / "engine" / "plain_industries.json").read_text())
_YEAR = re.compile(r"\b(?:19|20)\d\d(?:-\d\d)?\b")


def _nums(s):
    s = _YEAR.sub(" ", s)
    return {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,.]*", s)}


def test_local_writeups_quote_their_sources():
    """Every number in a local write-up must appear in a quoted snippet from a dated, linked source."""
    city_ids = {c["id"] for c in D["cities"]}
    ind_ids = {i["id"] for i in D["industries"]}
    bad = []
    for key, e in PLAIN.get("local", {}).items():
        city, ind = key.split("|")
        if city not in city_ids or ind not in ind_ids:
            bad.append((key, "unknown city or industry"))
        for c in e.get("checks", []):
            if DIGIT.search(c):
                bad.append((key, "digit in check", c))
        for sec in ("what", "money"):
            for l in e.get(sec, []):
                if not DIGIT.search(l["t"]):
                    continue
                srcs = l.get("src") or []
                if not srcs or not all(_src_ok(s) and s.get("quote") and re.fullmatch(r"\d{4}-\d\d-\d\d", s["as_of"]) for s in srcs):
                    bad.append((key, "missing source/date/quote", l["t"]))
                    continue
                quoted = set().union(*(_nums(s["quote"]) for s in srcs))
                missing = _nums(l["t"]) - quoted
                if missing:
                    bad.append((key, "number not in quote", sorted(missing), l["t"]))
                if any((TODAY - date.fromisoformat(s["as_of"])).days > 2 * 366 for s in srcs):
                    bad.append((key, "source older than two years", l["t"]))
    assert not bad, bad[:5]
    for k in ("gj_surat|diamonds", "gj_morbi|ceramics", "gj_surat|mmf_textiles"):
        assert k in COMMON["local"], k
