from __future__ import annotations

import json
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


def test_k445_source_uses_target_aligned_arch_forecasts() -> None:
    source = (ROOT / "experiments" / "k445" / "k445_btc_leverage.py").read_text(encoding="utf-8")
    readme = (ROOT / "experiments" / "k445" / "README.md").read_text(encoding="utf-8")

    assert "def target_aligned_variance_forecast" in source
    assert 'align="target"' in source
    assert "target_aligned_variance_forecast(res, oos_start)" in source
    assert "forecast(horizon=1, start=oos_start, reindex=False)" not in source
    assert "canonical_qlike(r_sq, f_var)" in source
    assert "canonical_qlike_pointwise(" in source
    assert "source-review FAIL pending target-aligned rerun" in readme


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


def test_k783c_source_uses_canonical_qlike_orientation() -> None:
    source = (
        ROOT / "experiments" / "k783c" / "k783c_cross_period_window.py"
    ).read_text(encoding="utf-8")
    readme = (ROOT / "experiments" / "k783c" / "README.md").read_text(encoding="utf-8")

    assert "from volpred.stats.model_evaluation import qlike, qlike_pointwise" in source
    assert "qlike(r2[valid], fc_aligned[valid].values)" in source
    assert "qlike_pointwise(r2_series[valid].values, fc_w[valid].values)" in source
    assert "ratio = sigma2_hat /" not in source
    assert ".claude/worktrees" not in source
    assert 'os.path.join(os.path.dirname(__file__), "k783c_cross_period_window_results.json")' in source
    assert "source-review FAIL pending K783c-v2 rerun" in readme


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


def test_k802_student_t_var_path_uses_unit_variance_scaling() -> None:
    source = (ROOT / "experiments" / "k802" / "k802_gjr_skewt.py").read_text(encoding="utf-8")

    assert "unit_variance_student_t_ppf(alpha_var, df_t_cur)" in source
    assert "t_dist.ppf(alpha_var" not in source
    assert "t_dist.logpdf(z / scale, df=df) - np.log(scale)" in source


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


def test_k1412_sources_scope_superseded_uniqueness_claim() -> None:
    source_paths = [
        ROOT / "experiments" / "k1412" / "README.md",
        ROOT / "experiments" / "k1412" / "k1412.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in source_paths)

    required_phrases = [
        "HLN retrofit superseded",
        "TW0050-HSI",
        "最強 / 最醒目",
    ]
    missing = [phrase for phrase in required_phrases if phrase not in combined]
    assert missing == []

    stale_phrases = [
        "TW0050-N225 唯一 Harvey sig",
        "TW0050-N225 唯一 Harvey-sig",
        "唯一 significant pair",
        "only Harvey-significant",
    ]
    offenders = [phrase for phrase in stale_phrases if phrase in combined]
    assert offenders == []


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


def test_k1355_pooled_dm_artifact_keeps_asset_day_dm_diagnostic_only() -> None:
    payload = json.loads((ROOT / "experiments" / "k1355" / "K1355_results.json").read_text(encoding="utf-8"))
    pooled_blocks = [
        payload["vol_channel_primary_gb"]["pooled"],
        payload["vol_channel_sensitivity"]["raw_proxy_signal_pooled"],
        payload["vol_channel_sensitivity"]["ridge_signal_pooled"],
        payload["vol_channel_sensitivity"]["mlp_signal_pooled"],
    ]

    for pooled in pooled_blocks:
        assert pooled["dm_method"] == "date-clustered cross-asset mean loss differential, HAC h=1"
        assert pooled["harvey_pass"] == (pooled["dm_t_augmented_vs_baseline"] < -3.0)

        diagnostic = pooled["stacked_asset_day_dm_diagnostic"]
        assert "diagnostic only" in diagnostic["note"]
        assert "same-day dependence" in diagnostic["note"]
