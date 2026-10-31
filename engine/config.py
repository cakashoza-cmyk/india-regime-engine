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
FLIP_LEVELS = {
    "repo_rate":   dict(level=5.50, direction="above", tier=1),
    "india10y":    dict(level=7.25, direction="below", tier=1),
    "cpi_headline": dict(level=4.0, direction="above", tier=1),
    "fii_net":     dict(level=-3000, direction="below", tier=1),
    "brent":       dict(level=100.0, direction="below", tier=2),
    "india_vix":   dict(level=20.0, direction="above", tier=2),
    "usdinr_ref":  dict(level=95.0, direction="above", tier=2),
    "us10y":       dict(level=4.5, direction="above", tier=2),
}

SECTOR_MAP = {
    "Risk-On": dict(own=["Banks/NBFCs", "Capital goods", "Autos", "Real estate", "Consumer discretionary"], avoid=["Gold heavy", "Long-duration cash"]),
    "Cyclicals-Reflation": dict(own=["Metals", "Energy", "PSU banks", "Industrials"], avoid=["Long-duration bonds", "Expensive staples"]),
    "Selective cyclicals / dry powder": dict(own=["Banks (select)", "Capital goods", "Metals/energy (select)"], avoid=["High-beta smallcaps", "Leveraged NBFCs"]),
    "Staples-Defensives": dict(own=["FMCG", "Pharma", "IT", "Utilities"], avoid=["Metals", "Real estate", "High-beta cyclicals"]),
    "Risk-Off": dict(own=["Cash/short-duration", "Gold", "Pharma"], avoid=["Cyclicals", "Smallcaps", "Leveraged balance sheets"]),
    "Unclear": dict(own=[], avoid=[]),
}
