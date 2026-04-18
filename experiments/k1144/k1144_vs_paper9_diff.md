# K1144 vs Paper 9 — Diff Report (D1/D2 Resolution Attempt)

**Experiment**: K1144  
**Date**: 2026-04-17  
**Spec**: A4f (τ_t = θ₀ + θ₁ VIX²_{t-1}, free ω_g), GJR baseline  
**OOS**: 2019-01-01 ~ 2026-04-07, W=2000, refit=63d  
**Return units**: percentage (×100), matching K949 and paper cross-asset convention

---

## Per-Asset DM t-Statistic Comparison

| Asset | Paper (main.tex) | K1144 Reproduced | Diff | Rel Diff | Harvey Paper | Harvey K1144 | Status |
|-------|-----------------|-----------------|------|----------|-------------|-------------|--------|
| FEZ | **3.45** | **3.114** | −0.336 | −9.7% | Yes | **Yes** | NOT_MATCHED (>5% rtol) |
| STOXX50E | **3.64** | **3.025** | −0.615 | −16.9% | Yes | **Yes** | NOT_MATCHED (>5% rtol) |

---

## QLIKE Values

| Asset | Model | Paper Table 6 | K1144 | Diff |
|-------|-------|--------------|-------|------|
| FEZ | GJR | 1.422 | 1.327 | −0.095 |
| FEZ | A4f | 1.371 | 1.288 | −0.083 |
| STOXX50E | GJR | 1.565 | 1.086 | −0.479 |
| STOXX50E | A4f | 1.513 | 1.045 | −0.468 |

**Observation**: FEZ QLIKE is reasonably close (diff ~0.09). STOXX50E QLIKE has large divergence (~0.47), suggesting possible data normalization difference for the index series.

---

## Verdict: NOT_MATCHED — but Harvey Significance PRESERVED

**Critical finding**: Both K1144-reproduced t-statistics exceed the Harvey |t|>3.0 threshold:
- FEZ: t=3.11 (Harvey YES) — paper says 3.45 (Harvey YES) ✓ direction matches
- STOXX50E: t=3.03 (Harvey YES) — paper says 3.64 (Harvey YES) ✓ direction matches

The **qualitative conclusion** (Harvey-significant improvement of A4f over GJR) is **preserved**.  
The **quantitative values** diverge by 9.7–16.9%.

---

## Root Cause Analysis

### Most Likely Cause: STOXX50E Ticker / Data Issue
- K1144 uses `^STOXX50E` from yfinance (available only from 2007-03-30)
- Paper may use a different ticker or data source for STOXX50E
- K1144 STOXX50E QLIKE (1.09) ≠ paper (1.565) — large gap suggests different normalization or return series
- FEZ QLIKE (1.33) is closer to paper (1.422) — same ETF data source, smaller gap

### Secondary Cause: Data Vintage / OOS Period
- Paper OOS: 2019-01-01 to 2026-04-07 (n=1825 for SPY, but n varies per asset)
- K1144: FEZ n_oos=1824 ✓, STOXX50E n_oos=1775 (fewer due to STOXX50E 2007 start)
- K949 used OOS 2016-2025, different spec — cannot reproduce paper numbers

### Not Caused By
- Return scaling: K1144 correctly uses ×100 (verified by QLIKE order of magnitude matching paper)
- VIX choice: K1144 correctly uses ^VIX (US, not VSTOXX) per paper Table 6 footnote
- Model spec: A4f free ω_g, τ_t denominator, additive VIX² — matches paper exactly
- Harvey threshold: Both K1144 and paper use |t|>3.0

---

## Recommendation

### (a) Most Likely Path — Data Vintage / Ticker Resolution
**Action for main thread**: Investigate whether paper's STOXX50E was computed from a different data source or with a different return normalization:
1. Try alternative STOXX50E ticker: `^ESTX50` or EuroStoxx50 via FRED/Bloomberg
2. Verify FEZ/STOXX50E data snapshot from original experiment (if preserved)
3. The 9.7% FEZ divergence may close further with exact original data vintage

If investigation confirms K1144 is methodologically correct but data vintage differs:
→ Document as source-gap issue (different data download dates, not methodology error)

### (b) If K1144 is the Authoritative Result
**Action for main thread**: Update Paper 9 Table 6 values:
- FEZ: change t=3.45 to t=3.11 (still Harvey significant)
- STOXX50E: change t=3.64 to t=3.03 (still Harvey significant)
- All qualitative conclusions about cross-asset generalization remain valid
- This requires errata notification to J. Empirical Finance

### (c) Errata Pending (Interim)
**Immediate action**: Mark D1/D2 in reproducibility_audit/diff_report.md as:
- "Partially resolved: K1144 confirms Harvey significance preserved for both assets"
- "Quantitative values differ 10-17%; errata decision pending data vintage investigation"

---

## K1144 Numerical Summary

```
FEZ:
  OOS: 2019-01-02 ~ 2026-04-06, n=1824
  GJR QLIKE: 1.3274
  A4f QLIKE: 1.2884
  Improvement: +2.94%
  DM t: 3.114 (p=0.0018, Harvey YES)

STOXX50E:
  OOS: 2019-01-03 ~ 2026-04-02, n=1775
  GJR QLIKE: 1.0863
  A4f QLIKE: 1.0452
  Improvement: +3.79%
  DM t: 3.025 (p=0.0025, Harvey YES)

Paper claims: FEZ t=3.45, STOXX50E t=3.64 (both Harvey YES)
Max divergence: STOXX50E 16.9%
```

---

## Impact Assessment

| Risk Level | Finding |
|-----------|---------|
| **LOW** (qualitative) | Harvey significance confirmed for both assets — cross-asset claim stands |
| **MEDIUM** (quantitative) | Exact t-values differ 10-17% from paper — needs explanation or correction |
| **HIGH** (STOXX50E QLIKE) | Large QLIKE divergence suggests data issue for STOXX50E — investigate ticker |

---

*K1144 is diagnostic only. No .tex files or shared state were modified.*  
*Authored: 2026-04-17, Claude (worktree agent)*
