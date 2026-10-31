"""RBI DBIE public data API (https://data-api.dbie.rbihub.in, no key). Verified Oct 2026.
NOTE: it serves the last scrape of DBIE (vintage lag of months), so it is a secondary/history source;
recent official prints come from manual_inputs.json and override it when newer."""
from __future__ import annotations
import json, urllib.parse, urllib.request

BASE = "https://data-api.dbie.rbihub.in/api/tables"

SERIES = {  # key: (schema/table, filters, transform)
    "cpi_headline":   ("real_sector/cpi_ruc_rn", {"comd_item": "C_GIAG", "coverage_geo_rn": "ALL_INDIA"}, "yoy"),
    "food_inflation": ("real_sector/cpi_ruc_rn", {"comd_item": "C_CFPI", "coverage_geo_rn": "ALL_INDIA"}, "yoy"),
    "iip_yoy":        ("real_sector/inx_inds_prod_rn", {"inds_prod_class_rn": "SEC_GEN_INDX"}, "yoy"),
}


def rows(table, filters, frm="2010-01-01", limit=1000):
    out, off = [], 0
    while True:
        qs = urllib.parse.urlencode({**filters, "from": frm, "limit": limit, "offset": off})
        req = urllib.request.Request(f"{BASE}/{table}/rows?{qs}", headers={"User-Agent": "regime-engine"})
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read())
        cols = d["columns"]
        batch = [dict(zip(cols, x)) for x in d["rows"]]
        out += batch
        if len(batch) < limit:
            return out
        off += limit


def series(key, frm="2010-01-01"):
    """Returns sorted [(period, value)] where value is YoY % for 'yoy' transforms."""
    table, flt, tr = SERIES[key]
    rs = rows(table, flt, frm)
    lvl = {}
    for r in rs:
        if r.get("obs_value") is not None:
            lvl[r["time_period"]] = float(r["obs_value"])  # last base wins per period
    ps = sorted(lvl)
    if tr != "yoy":
        return [(p, lvl[p]) for p in ps]
    out = []
    for p in ps:
        y = f"{int(p[:4]) - 1}{p[4:]}"
        if y[5:7] == "02" and y not in lvl:
            y = y[:8] + ("29" if y[8:] == "28" else "28")
        if y in lvl and lvl[y]:
            out.append((p, round((lvl[p] / lvl[y] - 1) * 100, 2)))
    return out


def latest(key):
    s = series(key, frm="2023-01-01")
    if len(s) < 2:
        return None
    (pp, pv), (p, v) = s[-2], s[-1]
    table, flt, _ = SERIES[key]
    return {"value": v, "prior": pv, "as_of": p, "reference_period": p,
            "source_url": f"{BASE}/{table}/rows?{urllib.parse.urlencode(flt)}",
            "note": "DBIE public API (scrape vintage; may lag official release)"}
