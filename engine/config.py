"""Indicator catalog: dial, scoring type, weight, tier, flip levels (editable assumptions)."""

# type: rate|inflation -> +1 if falling; growth|liquidity_up|vote -> +1 if rising;
#       fragility -> -1 if rising; flow -> sign of net vs ±500 cr (AUDIT_LOGIC FII rule)
INDICATORS = {
    # growth (macro — manual or official scrape; Nifty never votes growth)
    "gdp_yoy":      dict(dial="growth", type="growth", weight=2),
    "iip_yoy":      dict(dial="growth", type="growth", weight=1),
    "gst_yoy":      dict(dial="growth", type="growth", weight=1),
    # inflation
    "cpi_headline": dict(dial="inflation", type="inflation", weight=2),
    "cpi_core":     dict(dial="inflation", type="inflation", weight=2),
    "food_inflation": dict(dial="inflation", type="inflation", weight=1),
    "brent":        dict(dial="inflation", type="inflation", weight=1),
    # liquidity
    "repo_rate":    dict(dial="liquidity", type="rate", weight=2),
    "india10y":     dict(dial="liquidity", type="rate", weight=1),
    "fii_net":      dict(dial="liquidity", type="flow", weight=1),
    "credit_growth": dict(dial="liquidity", type="growth", weight=1),
    "rbi_stance_score": dict(dial="liquidity", type="stance", weight=2),  # MPC stance: -1 tightening .. +1 accommodative
    "usdinr_ref":   dict(dial="liquidity", type="fragility", weight=1),
    "us10y":        dict(dial="liquidity", type="fragility", weight=1),
    "dxy":          dict(dial="liquidity", type="fragility", weight=1),
    # vote (market)
    "nifty":        dict(dial="vote", type="vote", weight=1),
    "nifty_bank":   dict(dial="vote", type="vote", weight=1),
    "breadth_200dma": dict(dial="vote", type="vote", weight=1),
    # fragility
    "india_vix":    dict(dial="fragility", type="fragility", weight=1),
    "dii_net":      dict(dial="fragility", type="display", weight=0),  # display only (AUDIT_LOGIC)
    "capacity_util": dict(dial="display", type="display", weight=0),
    "ois_1y":       dict(dial="display", type="display", weight=0),
    # stage helpers (not dial votes)
    "nifty_auto":   dict(dial="stage", type="vote", weight=0),
    "nifty_metal":  dict(dial="stage", type="vote", weight=0),
}

YAHOO = {
    "nifty": "^NSEI", "nifty_bank": "^NSEBANK", "nifty_auto": "^CNXAUTO",
    "nifty_metal": "^CNXMETAL", "brent": "BZ=F", "us10y": "^TNX",
    "dxy": "DX-Y.NYB", "india_vix": "^INDIAVIX",
}

# Flip watchlist (assumed levels — edit to taste). tier 1 = regime-changing, tier 2 = confirmers.
FLIP_LEVELS_CALIBRATED = "2026-11-01"
FLIP_LEVELS = {
    "repo_rate":   dict(level=5.50, direction="above", tier=1, last_calibrated="2026-11-01", calibration_note="current repo after 7 Oct 2026 hike"),
    "india10y":    dict(level=7.25, direction="below", tier=1, last_calibrated="2026-11-01", calibration_note="assumed level"),
    "cpi_headline": dict(level=6.0, direction="above", tier=1, last_calibrated="2026-11-01", calibration_note="Spec 3.1: RBI upper tolerance band 6.0% (was 4.0)"),
    "fii_net":     dict(level=-3000, direction="below", tier=1, last_calibrated="2026-11-01", calibration_note="assumed level"),
    "brent":       dict(level=100.0, direction="below", tier=2, last_calibrated="2026-11-01", calibration_note="assumed level"),
    "india_vix":   dict(level=20.0, direction="above", tier=2, last_calibrated="2026-11-01", calibration_note="assumed level"),
    "usdinr_ref":  dict(level=95.0, direction="above", tier=2, last_calibrated="2026-11-01", calibration_note="assumed level"),
    "us10y":       dict(level=5.5, direction="above", tier=2, last_calibrated="2026-11-01", calibration_note="Spec 3.2: 5.5% (was 4.5)"),
}
FLIP_STALE_DAYS = 180

# ---- Source tiers (spec 1.1)
TIERS = ("official_primary", "official_secondary", "market_data", "news_llm")
SOURCE_TIER = {
    "rbi": "official_primary", "rbi_press": "official_primary", "rbi_mpc": "official_primary", "rbi_obicus": "official_primary",
    "mospi": "official_primary", "ccil": "official_primary", "treasury": "official_primary", "nse_archive": "official_primary",
    "nse_api": "official_primary", "nse": "official_primary", "dbie": "official_primary",
    "yahoo": "market_data", "ice_contract": "market_data", "nse+yahoo": "market_data",
    "tradingeconomics": "official_secondary", "investing": "official_secondary",
    "deepseek": "news_llm", "stub": "news_llm",
}
OFFICIAL_DOMAINS = ("mospi.gov.in", "pib.gov.in", "rbi.org.in", "gst.gov.in", "nseindia.com", "treasury.gov", "ccilindia.com", "fbil.org.in")
# Tier-1 signals: scored only from official_primary or market_data
TIER1 = {"rbi_stance_score", "ois_1y", "india10y", "yield_curve", "cpi_core", "brent"}
# priority order per indicator (first = preferred)
PREFERRED_SOURCES = {
    "cpi_headline": ["mospi", "manual", "tradingeconomics"], "food_inflation": ["mospi", "manual", "tradingeconomics"],
    "iip_yoy": ["mospi", "manual", "tradingeconomics"], "gdp_yoy": ["mospi", "manual", "tradingeconomics"],
    "gst_yoy": ["manual"], "capacity_util": ["rbi_obicus", "manual"], "credit_growth": ["rbi_press", "tradingeconomics"],
    "repo_rate": ["rbi", "manual"], "rbi_stance_score": ["rbi_mpc", "deepseek"], "india10y": ["ccil", "tradingeconomics", "investing"],
    "ois_1y": ["manual"], "fii_net": ["nse_api", "nse"], "dii_net": ["nse_api", "nse"], "usdinr_ref": ["rbi", "yahoo"],
    "us10y": ["treasury", "yahoo"], "brent": ["ice_contract", "yahoo"], "dxy": ["yahoo"],
    "nifty": ["nse_archive", "yahoo"], "nifty_bank": ["nse_archive", "yahoo"], "nifty_auto": ["nse_archive", "yahoo"],
    "nifty_metal": ["nse_archive", "yahoo"], "india_vix": ["nse_archive", "yahoo"], "breadth_200dma": ["nse+yahoo"],
}


def tier_for(source, payload=None):
    if source == "manual":
        url = (payload or {}).get("source_url") or ""
        if (payload or {}).get("source_tier") in TIERS:
            return payload["source_tier"]
        return "official_primary" if any(d in url for d in OFFICIAL_DOMAINS) else "news_llm"
    return SOURCE_TIER.get(source, "official_secondary")


def get_flip_level(key):
    return FLIP_LEVELS[key]["level"]


def evaluate_flip(key, value):
    lv = FLIP_LEVELS[key]
    if value is None:
        return {"indicator": key, "flipped": None, "level": lv["level"]}
    return {"indicator": key, "flipped": value > lv["level"] if lv["direction"] == "above" else value < lv["level"], "level": lv["level"]}

SECTOR_MAP = {
    "Risk-On": dict(own=["Banks/NBFCs", "Capital goods", "Autos", "Real estate", "Consumer discretionary"], avoid=["Gold heavy", "Long-duration cash"]),
    "Cyclicals-Reflation": dict(own=["Metals", "Energy", "PSU banks", "Industrials"], avoid=["Long-duration bonds", "Expensive staples"]),
    "Selective cyclicals / dry powder": dict(own=["Banks (select)", "Capital goods", "Metals/energy (select)"], avoid=["High-beta smallcaps", "Leveraged NBFCs"]),
    "Staples-Defensives": dict(own=["FMCG", "Pharma", "IT", "Utilities"], avoid=["Metals", "Real estate", "High-beta cyclicals"]),
    "Risk-Off": dict(own=["Cash/short-duration", "Gold", "Pharma"], avoid=["Cyclicals", "Smallcaps", "Leveraged balance sheets"]),
    "Unclear": dict(own=[], avoid=[]),
}
