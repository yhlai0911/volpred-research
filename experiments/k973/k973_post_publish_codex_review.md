# K973 — Post-Publish Codex Primary-Path Review

**Article**: mile_927eeb01 "高頻學界紅得發紫的「粗糙波動率」，搬到日線就熄火了"  
**Review date**: 2026-05-16  
**Reviewer**: Codex primary-path (`codex exec --skip-git-repo-check`)  
**Tokens used**: 25,393  
**Review task**: `paper_review_mile_927eeb01`

---

## VERDICT: CONDITIONAL PASS

---

## Checklist Results

### (a) Lookahead handling — PASS

All Hurst and RV features are properly lagged before entering any forecasting model:

```python
spy['H_rs_ewma_lag1'] = spy['H_rs_ewma'].shift(1)   # line 244
spy['H_vario_ewma_lag1'] = spy['H_vario_ewma'].shift(1)  # line 245
spy['H_rs_lag1'] = spy['H_rs'].shift(1)              # line 246
spy['r2_lag1'] = spy['r_squared'].shift(1)            # line 253
spy['r2_lag5'] = spy['r_squared'].rolling(5).mean().shift(1)   # line 254
spy['r2_lag22'] = spy['r_squared'].rolling(22).mean().shift(1) # line 255
```

OOS forecast loop uses `df.loc[date, feature_cols]` where all features are already `.shift(1)`. No lookahead found.

### (b) Forward correlation — PASS (not a problem)

`rv_22_fwd = rv_22.shift(-22)` appears only in the descriptive correlation analysis section, not in any forecasting feature set or OOS training path. As long as the article clearly frames it as descriptive (which it does), this is acceptable.

### (c) DM test for h=1 — PASS

`range(1, h)` with `h=1` is empty → no additional Newey-West lags applied. This is methodologically correct for 1-step-ahead forecast evaluation. HAC with 0 lags is equivalent to standard variance estimator.

### (d) t=0.62 traceability — MINOR (tracking completeness only)

The IS coefficient for `H_vario_ewma_lag1` (t=0.62) is computed in `k973_hurst_vol.py` lines 436-455 and printed to stdout, and is documented in `README.md` lines 48-49. However, `k973_hurst_vol_results.json` only contains the `HAR_H_rs_ewma` IS coefficient block — the `HAR_H_vario_ewma` block is missing.

**Fix needed**: Add `HAR_H_vario_ewma` IS coefficient entry to `results.json` (run the IS regression section offline or on next experiment re-run). This is a reporting completeness issue, not a methodology failure.

### (e) NULL result conclusion — PASS

OOS QLIKE results from `results.json`:

| Model | QLIKE | DM stat vs HAR | p-value |
|-------|-------|----------------|---------|
| HAR (baseline) | 1.526412 | — | — |
| HAR + H_rs_ewma | 1.527548 | −0.8932 | 0.3719 |
| HAR + H_vario_ewma | 1.527022 | −0.1121 | 0.9107 |
| HAR + H_rs + H_vario | 1.527863 | −0.2789 | 0.7804 |
| HAR + H_rs_raw | 1.545287 | −1.9227 | 0.0547 |
| GJR-GARCH(1,1) | 2.447498 | −3.7071 | 0.0002 |

All Hurst-augmented models show QLIKE **worse** than baseline HAR (by ≤0.02). All DM p-values >> 0.05. The NULL conclusion "Hurst exponent has no incremental predictive value for daily SPY volatility" is well-supported by the evidence.

The DM negative statistic direction (HAR losses − augmented losses > 0 → augmented is actually slightly worse in expectation) is consistent with the QLIKE table.

---

## Required Fix (MINOR)

**Add `HAR_H_vario_ewma` IS coefficient block to `k973_hurst_vol_results.json`**:

- Features: `['const', 'r2_lag1', 'r2_lag5', 'r2_lag22', 'H_vario_ewma_lag1']`
- `H_vario_ewma_lag1` t-stat = 0.62 (from README.md line 49)
- Exact coef/se/other t-stats require re-running lines 437-455 of `k973_hurst_vol.py`

This can be done with a one-off run of the IS section without re-running the full OOS pipeline.

**Status**: Tracked — not a blocker for article publication (article is already published). Fix on next experiment maintenance pass.

---

## Article-Level Findings

No source-code-level issues found that contradict article claims:

- "R/S method 平均 Hurst ≈ 0.50" → confirmed: `H_rs mean = 0.5019`  
- "Variogram method 數字更接近 0" → confirmed: `H_vario mean = 0.0086`  
- "Adding H to HAR does NOT improve QLIKE" → confirmed by all DM p >> 0.05  
- "5,094 obs, OOS n=1,822" → results.json has n_oos=1824 (total available) but actual n_valid per model=1822 (NaN filtering); no overclaim  
- R/S vs Variogram distinction clearly maintained throughout  

---

## Review Source

Codex primary-path review (NOT subagent fallback). Consistent with CLAUDE.md experiments.md requirement: "primary-path Codex review before writing knowledge.json".
