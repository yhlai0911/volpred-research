# K1414 — SPY r² QLIKE Forecast Ceiling Meta-Analysis

**Proposer**: Claude (hourly-22 dispatch, 2026-06-03)
**Executor**: Claude (main thread, inline light analysis)
**Type**: Meta-analysis (light compute, no MLE refit)

## Motivation

過去 12+ K experiments 在 SPY 日頻 r² target 上對比過 25+ 個 volatility forecast
models（GARCH 系列、HAR 系列、MF-GARCH 變體、ML：MLP/Ridge/RF）。每個實驗
獨立 publish QLIKE 結論，但缺乏 cross-K aggregate view — 「哪個是 SPY r²
QLIKE ceiling？多少 model 已 confirm 此 ceiling？」是平台 narrative 重要
chunk，目前散落在 multiple knowledge entries。

K1414 不是新 fit / 新 estimation，是 **meta-analysis of already-published
QLIKE values from K889 / K940 / K1014 / K1016**，sample-aligned 內排序、
forest plot 視覺化、cross-K confirmation MF-GJR(VIX) ceiling at ~1.45.

## Hypothesis (descriptive, not testable)

- **H1**: MF-GJR(VIX) family（K889 MF-GJR 1.4094; K940 MF-GJR(VIX) 1.4582）
  在 SPY r² QLIKE 上達成 ceiling，其他 5+ family（GARCH, GJR, HAR, ML, EWMA）
  在各自 sample 內均無法 outperform。
- **H2**: ML models (MLP / Ridge) 在 QLIKE 上災難性失敗（K940 MLP QLIKE=651520, Ridge=40278），
  Random Forest 為唯一可行 ML 但仍劣於 MF-GJR(VIX)（K940 DM t=-4.11）。
- **H3**: 跨 sample 不能直接 compare absolute QLIKE（不同 OOS window / refit
  cadence / HAR estimation window），但 **within-sample best model** 在所有
  K 中均落在 MF-GJR(VIX) 或同等 multiplicative VIX-augmented 規格上。

## Scope

- 4 source experiments × ~5 models = ~20 model-sample observations
- No new fit / data fetch / MLE refit
- Pure Python aggregation + matplotlib forest plot
- Output: forest plot PNG + summary JSON + cross-K narrative

## Data sources

| Source K | OOS window | n_oos | refit cadence | Best model | QLIKE |
|----------|-----------|-------|---------------|-----------|-------|
| K889 | 2019-01 – 2026-03 | 1,821 | every 63d | MF-GJR | 1.4094 |
| K940 | 2016-01 – 2025-12 | 2,514 | every 63d | MF-GJR(VIX) | 1.4582 |
| K1014 | (HAR-PD setup) | varies | every 63d | HAR (vanilla) | 1.2826 |
| K1016 | 2012-01 – 2026-04 | 3,567 | every 63d (HAR), 2000d/63d (GARCH) | A4f-VIX9D / GJR-t | 1.5373 / 1.5370 |

**Important caveat**: K1014 HAR QLIKE=1.2826 顯著低於其他 sample 的 HAR QLIKE
(K1016 HAR=1.6164)，**不可直接 cross-K 比較**。原因可能是 K1014 用不同 OOS
window / HAR specification / target rescaling。Forest plot 視覺上會看到 K1014
exhibit a different baseline，但 **within-K** 仍可分析該 sample 內 ranking.

## Deliverables

- `k1414.py`: aggregation + plot script
- `k1414_results.json`: aggregated model table + within-K rankings
- `k1414_forest.png`: 4-panel forest plot (one per source K), models sorted by QLIKE
- Knowledge entry K1414 confirming MF-GJR(VIX) ceiling within sample-aligned regimes

## Limitations

1. Cross-K absolute QLIKE comparison invalid (different samples)
2. Only SPY; cross-asset robustness (EFA/EEM/GLD/IWM) not addressed
3. Only daily-frequency r² target; high-frequency RV target not in scope
4. ML universe limited to K940 MLP/Ridge/RF; LSTM/Transformer not tested

## References

- K889 results: experiments/k889/k889_multiplicative_vol_factor_results.json
- K940 results: experiments/k940/k940_results.json
- K1014 results: experiments/k1014/k1014_results.json
- K1016 results: experiments/k1016/k1016_results.json
- Patton (2011) JoE 160:246-256 — QLIKE proxy-robust criterion
- Harvey et al. (2016) JBES 34:92-104 — |t|>3 significance threshold
