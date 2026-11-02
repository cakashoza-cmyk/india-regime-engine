import os, sys, json, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "detective"))
import build, fetch
from universe import UNIVERSE

def q(rev, ebitda, mat=None, **kw):
    m = dict(revenue=rev, ebitda=ebitda, material_cost=mat, finance_cost=kw.get("fin"), revenue_ytd=kw.get("ry"),
             receivables=kw.get("rec"), inventory=kw.get("inv"), ocf_ytd=kw.get("ocf"), impairment=None, loans=None)
    return {"m": m, "src": "https://nsearchives.nseindia.com/x.xml", "filed": "15-Feb-2020 10:00", "feed": "test"}

class T(unittest.TestCase):
    def test_universe(self):
        self.assertEqual(len(UNIVERSE), 30)
        self.assertEqual(len({u[0] for u in UNIVERSE}), 30)
        self.assertTrue({u[3] for u in UNIVERSE} >= {"demand", "input_cost", "credit", "policy", "export"})

    def test_percentile_needs_history(self):
        self.assertIsNone(build.pct([1, 2, 3], 2))
        self.assertEqual(build.pct([1, 2, 3, 4], 4), 100)

    def test_no_invented_values(self):
        raw = {"KAJARIACER": {"symbol": "KAJARIACER", "basis": "consolidated", "quarters": {"2019-06-30": q(100, None)}}}
        ev, models, gaps = build.build(raw)
        self.assertFalse(any(e["metric"] == "ebitda_margin_pct" for e in ev))
        for e in ev: self.assertTrue(e["source"].startswith("https://"))

    def test_models_cite_evidence_only(self):
        qs = {}
        for i, d in enumerate(["2017-06-30","2017-09-30","2017-12-31","2018-03-31","2018-06-30","2018-09-30","2018-12-31","2019-03-31","2019-06-30","2019-09-30","2019-12-31","2020-03-31"]):
            qs[d] = q(100 + 10 * i if i < 9 else 140, 20, 40 if i < 8 else 60)
        raw = {"KAJARIACER": {"symbol": "KAJARIACER", "basis": "c", "quarters": qs}}
        ev, models, _ = build.build(raw)
        ids = {e["id"] for e in ev}
        self.assertTrue(models)
        for m in models:
            self.assertTrue(set(m["evidence"]) <= ids)
            self.assertFalse(any(x.startswith("M-") for x in m["evidence"]))

    def test_common_factor_discount(self):
        ms = [dict(factor="building_materials", channel="demand", company=c) for c in ["KAJARIACER", "SOMANYCERA", "ULTRACEMCO"]]
        s, groups, chans = build.stage_for(ms, {"building_materials": 7})
        self.assertEqual(groups, [])  # 3 of 7 is not half: no clue
        self.assertLessEqual(s, 1)

    def test_three_channels_needed_for_hypothesis(self):
        ms = [dict(factor="a", channel="demand", company="X"), dict(factor="b", channel="export", company="Y")]
        s, _, _ = build.stage_for(ms, {"a": 1, "b": 1})
        self.assertLess(s, 4)
        ms.append(dict(factor="c", channel="credit", company="Z"))
        s, _, _ = build.stage_for(ms, {"a": 1, "b": 1, "c": 1})
        self.assertEqual(s, 4)

    def test_xbrl_parse_context_ids(self):
        x = b'''<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:f="http://x"><f:RevenueFromOperations contextRef="OneD">1e9</f:RevenueFromOperations>
        <f:RevenueFromOperations contextRef="FourD">3e9</f:RevenueFromOperations><f:Inventories contextRef="OneI">2e8</f:Inventories></xbrli:xbrl>'''
        import datetime as dt
        qd, ytd, inst = fetch.parse(x, dt.date(2019, 12, 31))
        m = fetch.extract(qd, ytd, inst)
        self.assertEqual(m["revenue"], 100.0); self.assertEqual(m["revenue_ytd"], 300.0); self.assertEqual(m["inventory"], 20.0)
        self.assertIsNone(m["ebitda"]); self.assertIsNone(m["volume"])

    def test_published_briefing_shape(self):
        fn = os.path.join(build.D, "briefing.json")
        if not os.path.exists(fn): self.skipTest("not built")
        B = json.load(open(fn))
        self.assertTrue(B["research_only"]); self.assertEqual(B["ai_calls"], 0)
        for h in B["hypotheses"]:
            self.assertTrue(h["wrong_if"] and h["alternatives"] and h["check_after"])
            if h["is_hypothesis"]: self.assertGreaterEqual(len(h["channels"]), 3)
            for e in h["evidence"]: self.assertIn(e, B["evidence_cited"])

if __name__ == "__main__": unittest.main()
