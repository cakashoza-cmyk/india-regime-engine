"""Proposal Sense-Check: peer benchmarks trace to filings, grey when peers are missing,
flags only add caution, and the page never sends or stores what a banker types."""
import json, os, re, shutil, subprocess, unittest
from engine import sensecheck as sc

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
P = lambda *p: os.path.join(ROOT, *p)
NODE = shutil.which("node")


def _ev(company, period, metric, value, i):
    return {"id": f"E{i:05d}", "company": company, "period": period, "fq": "Q" + period, "metric": metric,
            "value": value, "source": "https://nsearchives.nseindia.com/x.xml", "filed": "2026-01-01"}


class Builder(unittest.TestCase):
    def test_half_year_figure_excluded_and_min_peers(self):
        qs = ["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"]
        raw = {"ARVIND": {"basis": "c", "quarters": {q: {"m": {"revenue": 2000 * (2 if q == "2026-09-30" else 1)}} for q in qs}}}
        ev, i = [], 0
        for s, g in (("ARVIND", [10, 12, 14, 130]), ("WELSPUNLIV", [5, 6, 7, 8])):
            for q, v in zip(qs[2:], g):
                i += 1; ev.append(_ev(s, q, "revenue_yoy_pct", v, i))
        br = {"as_of_quarter": "2026-09-30", "universe": [{"sym": "ARVIND", "name": "Arvind"}]}
        out = sc.build(ev, br, raw)
        arv = out["observations"]["ARVIND"]["revenue_yoy_pct"]
        self.assertIn("excluded", arv[-1])                      # 130% built on a doubled (YTD) quarter
        b = out["benchmarks"]["cotton_chain"]["revenue_yoy_pct"]
        self.assertEqual(b["per_company"]["ARVIND"], 12)       # median of 10, 12, 14 only
        self.assertEqual((b["lo"], b["hi"], b["n_companies"]), (6.5, 12, 2))
        self.assertIsNone(out["benchmarks"]["mmf_yarn"]["revenue_yoy_pct"]["median"])  # one peer -> grey
        self.assertIsNone(out["benchmarks"]["cotton_chain"]["ebitda_margin_pct"]["median"])  # no data -> grey

    def test_committed_benchmarks_trace_to_filings(self):
        peers = json.load(open(P("data", "sensecheck_peers.json")))
        ev = {(e["company"], e["metric"], e["period"], e["source"]): e["value"] for e in json.load(open(P("data", "detective", "evidence.json")))}
        n = 0
        for s, ms in peers["observations"].items():
            for m, rows in ms.items():
                for r in rows:
                    n += 1
                    self.assertRegex(r["source"], r"^https://nsearchives\.nseindia\.(com|in)/")
                    self.assertAlmostEqual(ev[(s, m, r["period"], r["source"])], r["value"], places=1)
        self.assertGreater(n, 20)
        for g, bm in peers["benchmarks"].items():
            for m, b in bm.items():
                if b["median"] is not None:
                    self.assertGreaterEqual(b["n_companies"], sc.MIN_COMPANIES)
                    self.assertTrue(b["lo"] <= b["median"] <= b["hi"])
        for ind, g in peers["industry_group"].items():
            self.assertIn(g, peers["groups"])


@unittest.skipUnless(NODE, "node not installed")
class Flags(unittest.TestCase):
    def js(self, code):
        src = "const S=require(%r),P=require(%r);" % (P("assets", "sensecheck.js"), P("data", "sensecheck_peers.json"))
        return json.loads(subprocess.check_output([NODE, "-e", src + "console.log(JSON.stringify(" + code + "))"], text=True))

    def test_example_is_labelled_and_flags_stretch(self):
        ex = self.js("S.EXAMPLE")
        self.assertIn("not a real borrower", ex["label"].lower())
        a = self.js("S.assess(S.EXAMPLE.values,P,'mmf_textiles')")
        lv = {f["id"]: f["level"] for f in a["flags"]}
        self.assertEqual({lv["creditor"], lv["capacity"], lv["dscr"]}, {"grey"})
        self.assertIn(a["verdict"], ("stretched", "unrealistic"))

    def test_grey_without_peers_and_never_upgrade(self):
        a = self.js("S.assess({growth:50,margin:40},P,'textile_trading')")
        self.assertEqual(a["verdict"], "unjudged")
        self.assertTrue(all(f["level"] == "grey" for f in a["flags"]))
        self.assertEqual(self.js("S.combine('avoid','reasonable')")["call"], "avoid")
        self.assertEqual(self.js("S.combine('caution','reasonable')")["call"], "caution")
        self.assertEqual(self.js("S.combine('ok','stretched')")["call"], "caution")
        self.assertEqual(self.js("S.assess({margin:-5},P,'mmf_textiles').flags[0].level"), "green")
        self.assertEqual(self.js("S.assess({margin:'abc'},P,'mmf_textiles').verdict"), "invalid")


class Page(unittest.TestCase):
    def test_inputs_stay_in_browser(self):
        code = open(P("sensecheck.html")).read() + open(P("assets", "sensecheck.js")).read()
        for bad in ("localStorage", "sessionStorage", "indexedDB", "document.cookie", "sendBeacon", "XMLHttpRequest",
                    "method:", "POST", "replaceState", "pushState", "workers.dev", "fetch_config"):
            self.assertNotIn(bad, code, bad)
        for url in re.findall(r"fetch\(\s*[`'\"]([^`'\"]+)", code):
            self.assertTrue(url.startswith("data/"), url)

    def test_linked_from_nav_and_fetch_stays_off(self):
        self.assertIn("sensecheck.html", open(P("assets", "nav.js")).read())
        self.assertIn("sensecheck.html", open(P("lending.html")).read())
        self.assertIs(json.load(open(P("data", "fetch_config.json"))).get("fetch_enabled"), False)


if __name__ == "__main__":
    unittest.main()
