"""Credit Expert View: every sourced fact traces to a checked quote, practice guidance carries no numbers,
the verdict is the Radar call (signals only lower it), unknowns stay grey, and the page is static."""
import datetime as dt, json, os, re, sys, unittest
from engine import expert_kb as kb

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
P = lambda *p: os.path.join(ROOT, *p)
J = lambda *p: json.load(open(P(*p)))
RANK = {"ok": 0, "caution": 1, "avoid": 2}
SECTIONS = ["verdict", "lend", "economics", "local", "redflags", "triggers", "evidence", "links"]
NUM = re.compile(r"\d+(?:[.,]\d+)*")


def _norm(t):
    t = t.replace("\u2013", "-").replace("\u2014", "-").replace(",", "")
    return re.sub(r"\s+", " ", t)


def _views():
    ix = J("data", "expert", "index.json")
    out = {}
    for st in sorted({p["st"] for p in ix["pairs"]}):
        d = J("data", "expert", f"{st}.json")
        for k, v in d["pairs"].items():
            out[f"{st}|{k}"] = (v, d)
    return ix, out


class Knowledge(unittest.TestCase):
    def test_every_fact_has_a_linked_source(self):
        for f in kb.FACTS:
            s = kb.SOURCES.get(f["src"])
            self.assertIsNotNone(s, f["id"])
            self.assertTrue(s["url"].startswith(("http://", "https://")), f["id"])
            self.assertTrue(f["quotes"], f["id"])
            self.assertIn(f["section"], ("economics", "local"))

    def test_numbers_in_facts_appear_in_their_quotes(self):
        for f in kb.FACTS:
            s = kb.SOURCES[f["src"]]
            hay = _norm(" ".join(f["quotes"]) + " " + s["title"] + " " + s["date"])
            for n in NUM.findall(_norm(f["text"])):
                self.assertIn(n, hay, f"{f['id']}: number {n} is not in its quote or source title/date")

    def test_quotes_verified_against_source(self):
        chk = J("data", "expert", "source_check.json")
        used = {f["src"] for f in kb.FACTS}
        for sid in used:
            c = chk["sources"].get(sid) if "sources" in chk else chk.get(sid)
            self.assertIsNotNone(c, sid)
            self.assertEqual(c["status"], "ok", f"{sid}: {c}")

    def test_practice_guidance_has_no_numbers(self):
        def walk(x, path):
            if isinstance(x, dict):
                for k, v in x.items(): walk(v, path + "." + k)
            elif isinstance(x, list):
                for i, v in enumerate(x): walk(v, f"{path}[{i}]")
            elif isinstance(x, str):
                t = x
                for w in kb.PRACTICE_DIGIT_WHITELIST: t = t.replace(w, "")
                self.assertIsNone(re.search(r"\d", t), f"{path}: {x}")
        walk(kb.FAMILIES, "FAMILIES"); walk(kb.GENERIC_RED, "GENERIC_RED"); walk(kb.GENERIC_Q, "GENERIC_Q")
        keys = {"label", "model", "facilities", "tenor", "security", "covenants", "monitoring", "red_flags", "questions", "upgrade", "downgrade"}
        for k, f in kb.FAMILIES.items():
            self.assertTrue(keys <= set(f), k)
            self.assertTrue(set(f["red_flags"]) <= {"financials", "gst", "bank", "site"}, k)


class Views(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ix, cls.v = _views()
        cls.R = J("data", "radar.json")
        cls.K = J("data", "expert", "kb.json")

    def test_every_pair_has_the_seven_sections(self):
        self.assertEqual(len(self.v), len(self.ix["pairs"]))
        self.assertGreater(len(self.v), 400)
        for k, (v, _) in self.v.items():
            for s in SECTIONS: self.assertIn(s, v, f"{k} missing {s}")
            self.assertEqual(v["links"]["sensecheck"], f"sensecheck.html?state={v['st']}&city={v['ct']}&ind={v['ind']}")

    def test_verdict_is_radar_call_and_signals_only_downgrade(self):
        geo = self.R["geo"]
        for k, (v, _) in self.v.items():
            d = v["verdict"]
            if d["basis"] in ("proxy", "dealer"):
                self.assertIsNone(d["score"], k); continue
            e = self.R["calls"].get(f"{v['st']}|{v['parent']}")
            if not e or e[1] is None:
                self.assertIsNone(d["call"], k); continue
            self.assertEqual(d["score"], e[1], k)
            base = e[0] or ("ok" if e[1] >= geo["ok_at_or_above"] else "avoid" if e[1] < geo["avoid_below"] else "caution")
            self.assertGreaterEqual(RANK[d["call"]], RANK[base], f"{k}: a signal upgraded the call")
            if d["call"] != base: self.assertTrue(d["nudged"] or d["ratings_cut"], k)

    def test_surat_mmf_matches_sensecheck(self):
        v, _ = self.v["GJ|gj_surat|mmf_textiles"]
        e = self.R["calls"]["GJ|mmf_textiles"]
        self.assertEqual(v["verdict"]["score"], e[1])
        self.assertEqual(v["depth"], "full")

    def test_full_depth_clusters_have_sourced_local_facts(self):
        want = {"GJ|gj_surat|mmf_textiles", "GJ|gj_surat|textile_processing", "GJ|gj_surat|diamonds", "GJ|gj_morbi|ceramics",
                "GJ|gj_vapi|chemicals_dyes", "GJ|gj_ankleshwar|chemicals_dyes", "GJ|gj_rajkot|engineering",
                "GJ|gj_ahmedabad|pharma", "GJ|gj_alang|shipbuilding"}
        full = {k for k, (v, _) in self.v.items() if v["depth"] == "full"}
        self.assertTrue(want <= full, want - full)
        for k in full:
            v = self.v[k][0]
            self.assertTrue(v["local"]["facts"], k)
        for k, (v, _) in self.v.items():
            for fid in v["economics"]["facts"] + v["local"]["facts"]:
                self.assertIn(fid, self.K["facts"], k)
            if not v["st"] == "GJ": self.assertEqual(v["depth"], "standard", k)

    def test_grey_when_no_peers(self):
        for k, (v, d) in self.v.items():
            pk = v["economics"]["peers"]
            if pk is None: self.assertEqual(v["lend"]["anchors"], [], k)
            else: self.assertIn(pk, d["peers"], k)
            for a in v["lend"]["anchors"]: self.assertIsNotNone(a["median"], k)
        self.assertIsNone(self.v["GJ|gj_ahmedabad|pharma"][0]["economics"]["peers"])

    def test_peer_anchors_trace_to_filings(self):
        for k, (v, d) in self.v.items():
            pk = v["economics"]["peers"]
            if not pk: continue
            for m in d["peers"][pk]["metrics"].values():
                for obs in m.get("obs", {}).values():
                    for o in obs: self.assertTrue(o["source"].startswith("https://nsearchives.nseindia."), o)


class Page(unittest.TestCase):
    def test_static_page_reads_only_data(self):
        code = open(P("expert.html")).read() + open(P("assets", "expert.js")).read()
        for url in re.findall(r"fetch\(\s*[`'\"]([^`'\"]+)", code):
            self.assertTrue(url.startswith("data/") or url.startswith("FCFG"), url)
        for bad in ("doFetch", "Fetch latest", "localStorage", "deepseek", "api_key", "workers.dev"):
            self.assertNotIn(bad.lower(), code.lower(), bad)

    def test_sections_labels_feedback_and_print(self):
        js = open(P("assets", "expert.js")).read(); html = open(P("expert.html")).read()
        for t in ("How to lend", "Industry economics", "Local knowledge", "Red flags and promoter questions",
                  "What would change the view", "Evidence and sources", "Practice guidance", "Not yet known",
                  "id=\"fbf\"", "/feedback", "Employee ID", "compare", "window.print"):
            self.assertIn(t, js, t)
        self.assertIn("@media print", html)
        self.assertIn('name="viewport"', html)

    def test_navigation_links(self):
        self.assertIn("expert.html", open(P("assets", "nav.js")).read())
        lend = open(P("lending.html")).read()
        self.assertIn("expert.html?", lend); self.assertIn("data/expert/index.json", lend)
        self.assertIn("id=\"imap\"", lend)
        sc = open(P("sensecheck.html")).read()
        self.assertIn("URLSearchParams(location.search)", sc); self.assertIn("(no peer benchmark)", sc)
        self.assertIs(J("data", "fetch_config.json").get("fetch_enabled"), False)


class HalfYear(unittest.TestCase):
    X = """<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:in="x"><context id="OneD"><entity/><period><startDate>{s}</startDate><endDate>2026-09-30</endDate></period></context>
<context id="FourD"><entity/><period><startDate>2026-04-01</startDate><endDate>2026-09-30</endDate></period></context>
<in:RevenueFromOperations contextRef="OneD">{v}</in:RevenueFromOperations><in:RevenueFromOperations contextRef="FourD">5419</in:RevenueFromOperations></xbrl>"""

    def test_half_year_filing_is_not_a_quarter(self):
        sys.path.insert(0, P("engine", "detective")); import fetch
        b = self.X.format(s="2026-04-01", v=5419).encode()
        q, ytd, _ = fetch.parse(b, dt.date(2026, 9, 30))
        self.assertNotIn("RevenueFromOperations", q)
        self.assertEqual(ytd["RevenueFromOperations"], 5419)
        self.assertFalse(fetch.is_quarterly(b))
        b2 = self.X.format(s="2026-07-01", v=2918).encode()
        q2, _, _ = fetch.parse(b2, dt.date(2026, 9, 30))
        self.assertEqual(q2["RevenueFromOperations"], 2918)
        self.assertTrue(fetch.is_quarterly(b2))

    def test_rebuilt_raw_has_quarter_not_half_year(self):
        a = J("data", "detective", "raw", "ARVIND.json")["quarters"]["2026-09-30"]
        self.assertLess(a["m"]["revenue"], a["m"]["revenue_ytd"])
        f = J("data", "detective", "raw", "FILATEX.json")["quarters"]["2025-09-30"]
        self.assertLess(f["m"]["revenue"], 1500)


if __name__ == "__main__":
    unittest.main()
