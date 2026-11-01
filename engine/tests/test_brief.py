from engine import brief_pack as bp

PACK = ["Call: Avoid; combined score 10 = national 0 x 0.6 + local 25 x 0.4.", "exports -6.2% Apr-to-date (Rs 69,301 Cr FYTD)", "GNPA Mar-26 3.1%"]
GOOD = {"verdict_rationale": "Exports fell 6.2% and the combined score is 10 with local score 25.", "sector_risks": ["a", "b"],
        "local_news": "Limited local coverage.", "borrower_checks": ["debtor days vs 90", "x", "y"], "change_the_call": "Exports above 0%."}


def test_good_passes():
    assert bp.validate(GOOD, PACK, "", "debtor days vs 90") == []


def test_banned_phrase_rejected():
    o = {**GOOD, "change_the_call": "Monitor closely given macro headwinds."}
    assert any("banned" in p for p in bp.validate(o, PACK, "", "vs 90"))


def test_invented_number_rejected():
    o = {**GOOD, "local_news": "Orders fell 37%."}
    assert any("not found" in p for p in bp.validate(o, PACK, "", "vs 90"))
    assert bp.validate(o, PACK, "orders fell 37 percent", "vs 90") == []


def test_too_few_pack_figures():
    o = {**GOOD, "verdict_rationale": "Weak sector."}
    assert any("cites 0" in p for p in bp.validate(o, PACK, "", "vs 90"))


def test_indian_grouping():
    assert "69301" in bp.nums("Rs 69,301 Cr") and "1125894" in bp.nums("11,25,894")


def test_band_check():
    assert bp.band_problems("The call moves to Avoid if the combined score falls below 65.", 65, 45)
    assert not bp.band_problems("Below 65 the call drops to Caution; below 45 it becomes Avoid.", 65, 45)
    assert not bp.band_problems("A rise to 65 or more would make it OK to lend.", 65, 45)
    assert bp.band_problems("Exports must recover.", 65, 45)
