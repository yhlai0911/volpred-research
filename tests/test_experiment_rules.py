from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _experiments_rule_section(header: str) -> str:
    text = (ROOT / ".claude" / "rules" / "experiments.md").read_text(encoding="utf-8")
    assert header in text

    section = text[text.index(header) :]
    next_header = section.find("\n### ", len(header))
    if next_header != -1:
        section = section[:next_header]
    return section


def test_arch_forecast_alignment_rule_is_documented() -> None:
    section = _experiments_rule_section("### `arch` forecast alignment 必須 target 對齊")

    required_phrases = [
        "origin-aligned `h.1` forecast",
        "same-index realized variance",
        "forecast(..., align='target')",
        "shift 到 target return date",
        "QLIKE / MSE / DM tests",
        "lookahead / off-by-one",
        "K445",
    ]
    missing = [phrase for phrase in required_phrases if phrase not in section]
    assert missing == []


def test_qlike_pointwise_orientation_rule_is_documented() -> None:
    section = _experiments_rule_section("### QLIKE / DM pointwise loss 必須用 actual over predicted")

    required_phrases = [
        "actual / predicted - log(actual / predicted) - 1",
        "predicted / actual",
        "DM pointwise loss",
        "volpred.stats.model_evaluation.qlike_pointwise()",
        "volpred.evaluation.metrics.qlike()",
        "K783c",
    ]
    missing = [phrase for phrase in required_phrases if phrase not in section]
    assert missing == []


def test_var_es_basel_and_student_t_rule_is_documented() -> None:
    section = _experiments_rule_section("### VaR / ES 的 Basel 與 Student-t 口徑必須明示")

    required_phrases = [
        "Basel",
        "traffic-light",
        "250-day count rule",
        "exact-binomial sample-size rule",
        "自訂 500-day / rate threshold",
        "canonical Basel",
        "unit-variance scaling",
        "sqrt((df - 2) / df)",
        "K802",
        "Trinity PASS",
    ]
    missing = [phrase for phrase in required_phrases if phrase not in section]
    assert missing == []


def test_retrofit_uniqueness_claim_rule_is_documented() -> None:
    section = _experiments_rule_section("### Retrofit 後 uniqueness claims 必須重驗 current result table")

    required_phrases = [
        "唯一 significant pair",
        "only Harvey-significant",
        "current results JSON / table",
        "舊 README",
        "strongest / most visible",
        "K1416",
        "TW0050-HSI",
    ]
    missing = [phrase for phrase in required_phrases if phrase not in section]
    assert missing == []


def test_cross_asset_pooled_inference_rule_is_documented() -> None:
    section = _experiments_rule_section("### 跨資產 pooled inference 不可把 asset-day 當 iid")

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
