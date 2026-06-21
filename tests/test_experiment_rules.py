from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cross_asset_pooled_inference_rule_is_documented() -> None:
    text = (ROOT / ".claude" / "rules" / "experiments.md").read_text(encoding="utf-8")
    header = "### 跨資產 pooled inference 不可把 asset-day 當 iid"
    assert header in text

    section = text[text.index(header) :]
    next_header = section.find("\n### ", len(header))
    if next_header != -1:
        section = section[:next_header]

    required_phrases = [
        "asset-day",
        "primary publication claim",
        "cluster-robust",
        "panel HAC",
        "日期聚合 cross-asset loss differential",
        "HAC / DM",
        "stacked asset-day 結果只能放 diagnostic",
        "K1355",
    ]
    missing = [phrase for phrase in required_phrases if phrase not in section]
    assert missing == []
