from volpred.publisher.prepublish_audit import extract_numeric_claims


def test_iso_date_fragments_not_treated_as_statistics():
    claims = extract_numeric_claims(
        "公平比較期間是 2013-07-19 到 2026-06-09，共 3,242 個日報酬觀測值。"
    )
    raws = {c["raw"] for c in claims}
    assert "07" not in raws
    assert "19" not in raws
    assert "06" not in raws
    assert "09" not in raws
    assert "3,242" in raws
