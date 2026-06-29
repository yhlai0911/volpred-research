# Codex 24h Review — mile_96ec845f (K478)

- **Article**: 市場看起來越複雜，不代表波動率就更好預測
- **Draft source**: `storage/reports/feed.json` (`mile_96ec845f`)
- **Task**: `paper_review_mile_96ec845f`
- **Reviewed**: 2026-06-30 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **FAIL**

## Summary

文章的高層結論「entropy / complexity 指標沒有證明能打贏簡單波動率基準」可能方向上仍成立，但目前 K478 source 不能支撐 production claim。主要 blocker 是 `rv21_fwd` 是 21-day forward realized variance，script 的 expanding OLS 沒有做 horizon embargo；訓練列尾端會包含預測日之後的 realized returns。DM test 也用預設 `h=1`，沒有處理 21-day overlapping target 的 HAC horizon。

另外，production 文章嵌入的 DM p-value 圖把 VIX 那根標成「Baseline 勝」，但 results JSON 與文章文字都顯示 VIX QLIKE 較低、約改善 17.8%。這是 reader-facing 圖表矛盾。

## Numeric Verification

下列文章數字對得上 `experiments/k478/k478_entropy_vol_results.json`：

| Article claim | Source | Match |
|---|---|---|
| Baseline QLIKE = 0.3357 | `oos_results.M1_baseline.qlike` | yes |
| Permutation entropy QLIKE = 0.3439 | `oos_results.M3_pe.qlike` | yes |
| Shannon entropy QLIKE = 0.3370 | `oos_results.M4_shannon.qlike` | yes |
| VIX QLIKE = 0.2761 | `oos_results.M6_vix.qlike` | yes |
| VIX QLIKE improvement ≈ 17.8% | `dm_tests_vs_baseline.M6_vix.qlike_gain_pct = -17.755%` | yes |
| PE Granger p ≈ 0.026; SampEn/Shannon NS | `granger_tests` | yes |

The numeric transcription is mostly correct. The failure is methodology/provenance: the source computations are not clean enough for the article's causality-safe OOS framing.

## Findings

1. **Forward-label training leak in expanding OOS** — `experiments/k478/k478_entropy_vol.py:359`, `experiments/k478/k478_entropy_vol.py:278`

   `rv21_fwd = spy["rv21"].shift(-21)` means row `t` is labeled with realized variance over approximately `t+1 ... t+21`. But `expanding_ols_forecast()` trains on `X_all[:train_end]` / `y_all[:train_end]` for forecast origin `train_end`. For a 21-day forward label, training rows near the cutoff have `target_end >= forecast_origin`, so they include returns from the forecast date or after it. This violates the project rule that forward-label OOS training rows must satisfy `target_end < forecast_origin`.

   The fixed IS/OOS split has the same tail issue: `spy_is` includes late-2022 rows whose `rv21_fwd` reaches into January 2023, while the article describes 2023-2025 as true OOS.

2. **DM/HAC horizon is wrong for the target** — `experiments/k478/k478_entropy_vol.py:255`, `experiments/k478/k478_entropy_vol.py:534`

   The primary forecast target is 21-day overlapping forward RV, but `dm_test()` is called with default `h=1`. With `h=1`, the Newey-West loop `range(1, h)` adds no autocovariance terms. The p-values in `dm_tests_vs_baseline` are therefore not the correct HAC/HLN-style inference for a 21-day overlapping target.

3. **DM sign handling is internally confusing and one article figure is wrong** — `experiments/k478/k478_entropy_vol.py:260`, `experiments/k478/make_figs.py:74`

   The code computes `d = loss1 - loss2` with `loss1 = baseline`, so positive DM means challenger lower loss, negative DM means baseline lower loss. The helper comment says the opposite, and `make_figs.py` labels `t < 0` as "challenger wins". The saved figure partly reflects this confusion: VIX is labeled "Baseline 勝" even though `M6_vix` has lower QLIKE (`0.2761` vs `0.3357`) and the article text calls VIX the winner.

4. **Experiment artifact standard is incomplete** — `experiments/k478/README.md`

   README remains a placeholder (`Status: planning`) and does not document data source, sample, methodology, lookahead defense, limitations, or verdict. The article relies on the script/results directly, but K478 does not meet the current experiment three-piece documentation standard.

5. **Reproducibility path bug** — `experiments/k478/k478_entropy_vol.py:810`

   The script writes to `experiments/k478_entropy_vol_results.json` relative to the current working directory, while canonical results live at `experiments/k478/k478_entropy_vol_results.json`. Running the advertised script from repo root would create/update the wrong file.

## Article Impact

The article should not remain published in its current form. The exact OOS and DM claims are not lag-clean, and the embedded DM figure contradicts the text on VIX. A corrected K478-v2 should:

1. Recompute forward-label expanding OOS with `target_end < forecast_origin` embargo.
2. Use horizon-aware HAC/DM (`h=21`, ideally with HLN small-sample adjustment or an explicit block-bootstrap sensitivity).
3. Regenerate all figures after fixing DM direction labels.
4. Replace the placeholder README with a real methodology/verdict record.
5. Write results to the canonical `experiments/k478/` path.

## Action Taken

1. Added this 24h review record.
2. Soft-unpublished `mile_96ec845f` pending K478-v2 rerun and article correction.
3. Added `details.errata_24h_review` metadata to the feed entry.
4. Materialized follow-up task `K478_v2_fix_forward_label_dm` in `storage/next_tasks.json`.
5. Initial unpublish mirror sync returned HTTP 401, then `uv run volpred ops sync-all` completed with `articles: 1`.

## Verification Commands

```bash
jq '.oos_results, .dm_tests_vs_baseline, .granger_tests' experiments/k478/k478_entropy_vol_results.json
sed -n '278,540p' experiments/k478/k478_entropy_vol.py
```

The full experiment was not rerun because rerunning the current script would overwrite the wrong path and refresh yfinance-dependent data without fixing the methodological blockers.
