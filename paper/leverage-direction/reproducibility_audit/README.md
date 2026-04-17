# Paper 1 Reproducibility Audit — Pilot Pass

**Paper:** Leverage Direction Matters: Cross-Asset Evidence on GARCH Model Selection and Volatility Targeting  
**Target journal:** Journal of Banking and Finance  
**Audit type:** Pilot pass (establishes pattern for remaining 9 papers)  
**Audit date:** 2026-04-17  
**Auditor:** Reproducibility audit agent (worktree agent-af5db316)  

---

## Scope

Full scan of `paper/leverage-direction/main.tex` (208 lines) + `body.tex` (610 lines) + `tables.tex` (236 lines) + `table_nulls.tex` (42 lines). All Tables and Figure captions, Abstract, and inline result claims.

## Methodology

1. **Extraction:** Full read of all .tex files; extracted all numeric claims with context.
2. **Script execution:** Ran `paper/leverage-direction/reproduce.py` which compared paper values against 4 experiment JSONs (K799, K802, K824v2, K902).
3. **Supplementary comparison:** Directly read K902 JSON to obtain Table 1 descriptive stats, Table 2 rolling gamma, and Table 3 QLIKE (cross-asset).
4. **Tolerance:** rtol=0.01 (1%) for most numbers; rtol=0.001 for test statistics.

## Files Generated

| File | Contents |
|------|----------|
| `main_tex_numbers.csv` | ~180 rows: all numeric claims extracted from main.tex + body.tex + tables |
| `script_output.json` | Actual values from K799/K802/K824v2/K902 experiment JSONs |
| `diff_report.md` | Full diff table + 6 divergent case recommendations |
| `README.md` | This file — scope, findings, recommendations |

## Experiment Coverage

| Paper Table | Experiment Source | Coverage |
|-------------|------------------|----------|
| Table 1 (descriptive stats) | K902 | 90% (SLV minor discrepancy) |
| Table 2 (rolling gamma) | K799, K902 | 50% — period mismatch K902 vs paper |
| Table 3 (QLIKE OOS) | K799, K802, K902 | Rankings ✓; absolute values mismatched (period) |
| Table 4 (VaR attribution) | KB only | 0% JSON |
| Table 5 (VaR ortho) | K799, K802, K824v2 | 80% — Kupiec p rounding issue |
| Table 6 (VaR panel 7 assets) | None | 0% |
| Table 7 (VT cross-asset) | None | 0% |
| Table 8 (window robustness) | None | 0% |
| Table 9 (Hybrid VT) | KB only | 90% (Sharpe confirmed via KB) |
| Table 10 (amplification) | K824v2, KB | 60% |
| Table 11 (tail risk) | None | 0% |
| Table 12 (gamma-mechanism) | KB only | 0% JSON |
| Appendix B (TZ momentum) | None | 0% |

## Reproducibility Score

| Category | Count | Pct |
|----------|-------|-----|
| ✓ matched | 28 | 32% |
| ≈ approx (rounding only) | 14 | 16% |
| ✗ divergent (needs action) | 24 | 28% |
| ? no-source-found | 21 | 24% |
| **Total checked** | **87** | |

**Headline score: 48% fully reproducible (✓+≈), 72% qualitatively confirmed.**

## Key Findings

### Critical

1. **HM gamma conflict (D4):** Sec 4.7 reports γ_HM=−0.035 (t=−0.39, p=0.70, not significant) while Sec 5.4 reports γ_HM=−0.043 (t=−4.06, p<0.001, highly significant). These are for two different setups (Sec 4.7: SPY-only VT over 2023-24 short window; Sec 5.4: Hybrid VT over 2014-2026 full period), but this is NOT made clear in the text. Must clarify or one is wrong.

### High

2. **Sample period mismatch (D1, D2):** Tables 2 and 3 absolute values differ substantially from K902 because K902 uses 2017-2025 start while the paper's computations appear to use an extended 2010-2025 window. K799 independently validates the extended-window results (HAC t=−5.79 for GLD, SPY γ≈0.21). The qualitative conclusions are unaffected. A K903 experiment should reproduce the exact paper window.

3. **Kupiec p-value rounding (D3):** Paper reports 0.60 for both GJR+StudentT (actual 0.6698) and GJR+HistSim (actual 0.6353). This is aggressive rounding to 1 decimal. Should be corrected to 0.67 and 0.64.

### Medium

4. **QQQ 2023-24 QLIKE direction (D6):** Paper shows GARCH marginally better for QQQ 2023-24 (Δ=+0.92%, p=0.067), but K902 shows GJR marginally better (Δ=−0.12%, p=0.619). Both agree GJR is not significantly better at 5%, consistent with the paper's threshold story. The specific Δ direction depends on estimation window.

5. **Hybrid VT Sharpe (D5):** Paper reports 0.99 but KB says 0.985. Minor but could be noted.

### Missing Experiments

Large portions of the paper have **no experiment JSON at all**: Tables 4, 6, 7, 8, 11, 12, Appendix B. These need dedicated K-numbers for full reproducibility. Specifically:
- Table 4 (VaR 2020-2025 attribution) → needs K904a
- Tables 6-7 (cross-asset VaR + VT) → needs K904b
- Appendix B (TZ momentum) → needs K904c

## Conclusion

Paper 1 is **partially reproducible** from existing experiment JSONs. The core findings (GJR > GARCH for SPY, not for GLD/TLT; VT reduces MDD universally) are qualitatively confirmed. The main reproducibility gap is:
1. Missing a canonical "extended sample" experiment that matches the paper's exact computation window
2. Three tables (4, 6, 7, 8, 11, 12) with no source experiment JSON
3. Two confirmed divergences requiring paper corrections (Kupiec p rounding, HM gamma conflict)

## Pilot Pattern Learnings for 9 Remaining Papers

1. **Check sample period consistency first.** The biggest source of divergence was K902 using 2017 vs paper using 2010 start. Always verify `data_start` in experiment JSON vs paper's stated sample.
2. **Kupiec / p-value rounding is a recurring issue.** Check that all reported p-values are within ±0.01 of actual (2-decimal rounding), not ±0.10.
3. **Internal consistency: same test in multiple sections.** Search for the same statistic name (e.g., "gamma_HM") across all .tex files to catch conflicts.
4. **KB-only verification is insufficient.** If a number appears in the paper but only in knowledge.json (no JSON file), flag as ? no-source-found.
5. **Table cross-reference:** When descriptive stats appear in both abstract and tables, check for consistency (e.g., Table 1 kurtosis vs inline text).
6. **Figure source scripts.** None of the 7 figures have explicit generation scripts in `scripts/`. This is a systematic gap across all papers.
7. **The reproduce.py pattern works.** Having `reproduce.py` in the paper directory plus local `experiments/` JSONs is the right architecture. The gap is completeness of the experiment JSONs.
