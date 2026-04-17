# Paper 1 (leverage-direction) — Non-K Forensic Sweep Report

**Date**: 2026-04-17
**Agent**: Non-K Forensic Sweep (worktree agent-a30d366f)
**Task**: Map non-K experiment folders to Paper 1 STILL_NO_SOURCE list (21 numbers)

---

## Non-K Folders Inspected (Paper 1 Assigned)

| Folder | Has Real Data? | Content Summary |
|--------|---------------|-----------------|
| `jbf_robustness_suite` | NO — planning stub | Status=planning, metrics={}, data_sources=[]. Created 2026-04-16 as placeholder |
| `structural_leverage_panel` | NO — planning stub | Status=planning, metrics={}, data_sources=[]. Created 2026-04-16 |
| `structural_leverage_index` | NO — planning stub | Status=planning, metrics={}, data_sources=[]. Created 2026-04-16 |
| `gjr_vs_ewma_crisis` | NO — planning stub | Status=planning, metrics={}, data_sources=[]. Created 2026-04-16 |
| `qlike_error_decomposition` | NO — planning stub | Status=planning, metrics={}, data_sources=[]. Created 2026-04-16 |
| `caviar_test` | YES — real data | CAViaR (Engle & Manganelli 2004): CAViaR-SAV, CAViaR-AS, CAViaR-IG backtests on SPY 2019–2026 (1507 OOS days). Violation rates, Kupiec, Christoffersen, DQ tests at α=0.01 and α=0.05. |

---

## Paper 1 STILL_NO_SOURCE Analysis

From `diff_report.md`, Paper 1 has **21 no-source-found** numbers across:
- Table 3 absolute QLIKE values (SPY/QQQ/GLD/TLT/EEM/BTC — sample period mismatch with K902)
- Table 6 VaR panel (7 assets × 5 methods — 5 cells)
- Table 7 VT cross-asset performance (SPY/GLD/TLT/EEM/BTC Sharpe + MaxDD)
- Table 8 window robustness
- Table 11 tail risk metrics
- Table 12 gamma-mechanism (KB-only)
- C3: Gold regime-split t-test (no experiment JSON)

### Cross-Match: Non-K Folders vs No-Source Numbers

| No-Source Item | Best Candidate Non-K Folder | Verdict |
|---------------|---------------------------|---------|
| Table 6 VaR panel (5 cells: Skewed-t 76.2%, FHS 76.2%, CF-VaR 66.7%, Student-t 57.1%, Normal 57.1%) | `caviar_test` | **AMBIGUOUS** — caviar_test runs CAViaR (not Skewed-t/FHS/CF-VaR). Tests different model class. Cannot confirm Table 6 values. |
| Table 7 VT cross-asset performance (5 assets, 2005–2026) | None | **UNRELATED** — no non-K folder covers 7-asset 2005–2026 VT performance panel |
| Table 8 window robustness | None | **UNRELATED** — jbf_robustness_suite is planning stub only, contains no data |
| Table 11 tail risk metrics | None | **UNRELATED** — no non-K folder covers full-period ES/kurtosis/VaR tail risk table |
| Table 12 gamma-mechanism (β_trend, Spearman ρ) | None | **UNRELATED** — structural_leverage_panel/index are planning stubs only |
| Table 3 QLIKE absolute values | None | **UNRELATED** — gjr_vs_ewma_crisis is planning stub only |
| C3: GLD regime t-test | None | **UNRELATED** |

---

## caviar_test Detailed Match Analysis

`caviar_test_results.json` contains:
- Period: OOS n_oos_days=1507 (approximately 2019–2026)
- Models: CAViaR-SAV, CAViaR-AS, CAViaR-IG at α=0.01 and α=0.05
- CAViaR-SAV α=0.05: violation_rate=5.77%, Kupiec p=0.179 (pass)
- CAViaR-AS α=0.05: violation_rate=6.37%, Kupiec p=0.019 (reject)

**Paper 1 no-source VaR items** are for Skewed-t/FHS/CF-VaR/Student-t/Normal models (Table 6). CAViaR is a completely different model class not mentioned in Paper 1's VaR framework. **No match.**

---

## Additional Non-K Folders Checked (Potential Cross-Paper)

The following non-K folders were also inspected for any Paper 1 relevance:

| Folder | Verdict |
|--------|---------|
| `drawdown_duration_analysis` | UNRELATED — SPY drawdown analysis, no cross-asset VT panel |
| `transaction_cost_analysis` | UNRELATED — SPY breakeven cost analysis, not Paper 1 VaR/gamma tables |
| `emd_garch_vol` | UNRELATED — EMD signal decomposition, different methodology |
| `es_backtest_acerbi_szekely` | AMBIGUOUS — Tests SPY ES at α=0.01 with Acerbi-Szekely. Could theoretically support Paper 1's ES claims but no Table 11 values visible in top-level keys |

---

## Summary

| Category | Count |
|----------|-------|
| Non-K folders inspected (Paper 1 assigned + potential) | 6 directly + 4 supplemental |
| Folders with real data | 1 (caviar_test) |
| Folders as planning stubs only | 5 |
| Matches found for no-source numbers | **0** |
| STILL_NO_SOURCE after sweep | **21** (unchanged) |

**Verdict**: All 5 Paper-1-labeled non-K folders (jbf_robustness_suite, structural_leverage_panel, structural_leverage_index, gjr_vs_ewma_crisis, qlike_error_decomposition) are **planning stubs** created 2026-04-16 with no actual results. `caviar_test` has real data but tests CAViaR models not referenced in Paper 1. **Zero no-source numbers resolved by non-K sweep.**

---

## Action Recommendations

1. **Immediate**: Run `gjr_vs_ewma_crisis` and `jbf_robustness_suite` to populate the Table 3 QLIKE and Table 7 VT cross-asset gaps (these are the intended experiments per folder names).
2. **structural_leverage_panel/index** are designed to fill Table 12 gamma-mechanism data — currently empty stubs.
3. `qlike_error_decomposition` designed to decompose Table 3 QLIKE sources — currently empty stub.
4. No quick wins from non-K sweep for Paper 1.
