# K1302 Byte-Match Diagnostic — Paper 2 Table 2 γ

Generated: 2026-05-12T03:56:49.148413+00:00
Overall verdict: **FAIL** (4 of 4 Table-2 stocks failed)

Tolerance: |Δγ| ≤ 0.001, |Δt| ≤ 0.05

## Per-stock TWA (GJR-N w=2000) vs Table 2

| Ticker | Name | γ_paper | γ_est | Δγ | t_paper | t_est | Δt | Verdict |
|--------|------|--------:|------:|---:|--------:|------:|---:|---------|
| 2317.TW | Hon Hai Precision | +0.0520 | +0.0382 | 0.0138 | +1.140 | +3.110 | 1.970 | FAIL_LARGE_DRIFT |
| 2454.TW | MediaTek | +0.0440 | +0.0448 | 0.0008 | +0.960 | +5.066 | 4.106 | FAIL_LARGE_DRIFT |
| 0056.TW | Yuanta High Dividend ETF | +0.1120 | +0.0791 | 0.0329 | +1.870 | +4.628 | 2.758 | FAIL_LARGE_DRIFT |
| 2886.TW | Mega Financial | +0.1790 | +0.0445 | 0.1345 | +2.420 | +3.269 | 0.849 | FAIL_LARGE_DRIFT |

## Recommended next step (main thread)

Per K1256 3-spec footnote pattern + paper-workflow §資料/腳本/論文三方一致:

1. If Δγ small (≤0.005) but Δt large: SE-method footnote (Paper uses NW-HAC; this experiment uses inverse-Hessian).
2. If Δγ moderate (0.005–0.05): likely sample-window or data-revision drift (yfinance vs paper-pinned CSV adj-close differences).
3. If sign-flip / Δγ > 0.05: methodology mismatch — re-examine Paper 2 Table 2 source script provenance.

Option A: Update Paper 2 Table 2 to K1302 canonical values + add 3-spec footnote naming TWA/TWB/TWC.
Option B: Add SE-method clarification footnote (paper γ unchanged, footnote pins SE source).
Option C: Erratum + reproduce.py NOTE classification (K1256 precedent).

DO NOT fit the script to paper numbers — divergence reported as-is (CLAUDE.md §研究誠實原則 #1).
