# K1302 Byte-Match Diagnostic — Paper 2 Table 2 γ

Generated: 2026-05-14T16:14:32.413727+00:00
Overall verdict: **FAIL** (4 stocks failed)

Tolerance: |Δγ| ≤ 0.001, |Δt| ≤ 0.05

## Per-stock TWA (GJR-Normal Full-Sample) vs Table 2

| Ticker | Name | γ_paper | γ_est | Δγ | t_paper | t_est | Δt | Verdict |
|--------|------|--------:|------:|---:|--------:|------:|---:|---------|
| 2317.TW | Hon Hai Precision | +0.0520 | +0.0320 | 0.0200 | +1.140 | +1.741 | 0.601 | FAIL_LARGE_DRIFT |
| 2454.TW | MediaTek | +0.0440 | +0.0406 | 0.0034 | +0.960 | +3.096 | 2.136 | FAIL_LARGE_DRIFT |
| 0056.TW | Yuanta High Dividend ETF | +0.1120 | +0.0668 | 0.0452 | +1.870 | +1.914 | 0.044 | FAIL_LARGE_DRIFT |
| 2886.TW | Mega Financial | +0.1790 | +0.0379 | 0.1411 | +2.420 | +1.552 | 0.868 | FAIL_LARGE_DRIFT |


## Recommendation

The individual stocks (Hon Hai/MediaTek/0056/Mega) in Table 2 are confirmed legacy numbers from N121 knowledge summary. They differ significantly in t-stats from the new canonical Full-Sample Robust SE specification. Mega Financial (2886.TW) additionally shows a large γ drift (0.179 → 0.0379).

Main thread should adopt Option A: Update Paper 2 Table 2 to K1302 canonical values for internal consistency with 0050.TW/TSMC.