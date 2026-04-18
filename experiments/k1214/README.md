# K1214: BTC GAS-t Negative-Result Methodology Paper — Markdown Draft

**Status**: completed (2026-04-17)
**Proposer**: Claude (main-thread request per CLAUDE.md narrative state machine — paper body cannot be written by agents, but markdown draft is permitted as a cherry-pick source)
**Executor**: Claude (worktree `agent-a3473585`)
**Related K**: K1129 (BTC GAS-t full-sample reversal motivator), K1133 (sub-period decomposition), K1133b (5-model Student-t attribution + MS-GAS-t OOS)

## Purpose

Produce a full-length, publication-ready paper draft in markdown format assembling the K1129, K1133, and K1133b findings into a single coherent narrative for **negative-result methodology paper** publication. The draft is intended for main-thread adoption as the initial seed for a new paper repository `paper/btc-gas-negative/`.

**Paper title**: *Why GAS-t Fails on Bitcoin: Student-t Innovation Is the Culprit, Regime-Switching Cannot Rescue*

**Core claim**: The documented underperformance of GAS-Student-t vs GJR-Normal on Bitcoin (K1129 DM $t = -4.58$) is (i) concentrated almost entirely in the 2015-2020 pre-institutional period, (ii) approximately 75% attributable to the Student-t innovation distribution and only 25% to score-driven GAS dynamics, and (iii) *cannot* be rescued by a Markov-switching extension (MS-GAS-t) beyond the GJR-Normal baseline, falsifying the Catania (2018) regime-switching remedy for Bitcoin.

## Why NOT .tex

Per `CLAUDE.md` rule: *"禁止用 background agent 直接寫論文 `.tex`；寫作與方法論決策要在主線程完成"*. This experiment delivers a markdown draft that main-thread can review, edit, and cherry-pick into LaTeX. Agent produces only content, main-thread owns the compilation pipeline.

## Materials source

All numerical results are quoted verbatim from the following JSON files (no recalculation, no divergence):

- `experiments/K1129/k1129_results.json` — full-sample BTC-USD (n_OOS=1,926) replication of the M3 GAS-t vs M1 GJR-N reversal.
  - BTC M3 vs M1: DM_HLN_t = $-4.578$, $p = 5.0\times 10^{-6}$, QLIKE_rel_improvement_pct = $-3.95$%.
  - BTC M2 vs M1: DM_HLN_t = $-5.175$, $p = 2.5\times 10^{-7}$, QLIKE_rel_improvement_pct = $-5.84$%.
- `experiments/k1133/k1133_results.json` — three sub-periods (P1/P2/P3) × three models (M1/M2/M3) on independent rolling windows.
  - P1 pre-institutional (n_OOS=1,441, 2017-01-21 to 2020-12-31): M3 vs M1 DM_HLN_t = $-4.669$, Harvey-significant.
  - P2 FTX/Luna (n_OOS=345 PRELIMINARY): M3 vs M1 DM_HLN_t = $-0.815$, not significant.
  - P3 spot-ETF (n_OOS=100 PRELIMINARY): M3 vs M1 DM_HLN_t = $-0.803$, not significant.
- `experiments/k1133b/k1133b_results.json` — 5-model decomposition + MS-GAS-t OOS (Klaassen 2002 state-prob recursion).
  - P1 Part A: M4 GAS-Normal vs M1 DM = $-1.898$ NS; M4 vs M3 DM = $+2.665$ significant; $\sim 75$% attribution to Student-t.
  - P1 Part B MS-GAS-t: vs M3 DM = $+5.971$ (rescues single-state); vs M1 DM = $+0.275$ NS (no edge over GJR-N).

## Files produced

| File | Purpose |
|---|---|
| `k1214_paper_draft.md` | Full paper draft ~4,100 words: Abstract, Introduction, Methodology, Data, Results, Discussion, Conclusion, References, Appendix. |
| `k1214_paper_outline.json` | Structured outline (sections, subsections, word targets, key citations, key numbers). |
| `README.md` | This file. |

## Paper structure and word budget

| Section | Target words | Actual |
|---|---|---|
| Abstract | 200 | ~280 |
| 1. Introduction | 800 | ~820 |
| 2. Methodology | 500 | ~650 |
| 3. Data | 300 | ~320 |
| 4. Results | 1,200 | ~1,200 |
| 5. Discussion | 600 | ~700 |
| 6. Conclusion | 300 | ~230 |
| References | ~20 entries | 16 entries |
| Appendix A | (supporting tables) | ~250 |

Total main text: ~4,100 words + tables + appendix.

## Main-thread adoption workflow

Suggested initialization of `paper/btc-gas-negative/`:

1. **Create folder**: `mkdir -p paper/btc-gas-negative/{figures,tables,scripts,data_docs,review_history}`.
2. **Seed main.tex**: cherry-pick sections from `k1214_paper_draft.md`, convert math to `amsmath`, convert tables to `booktabs`.
3. **README.md for paper**: title, target journal (JoEF primary; JFEC / J Risk backup), status=`draft`, K-list (K1129, K1133, K1133b), data source summary.
4. **experiments.md**: list K1129 (full-sample reversal), K1133 (sub-period), K1133b (decomposition + MS-GAS-t OOS).
5. **data_sources.md**: yfinance BTC-USD 2015-01-02 to 2026-04-14, $n = 4{,}121$ daily observations, pct_change * 100 percent units, seed 42.
6. **scripts/README.md**: entry point per table/figure. Table 1 produced by `experiments/K1129/k1129.py`; Tables 2-3 and Appendix A.1 by `experiments/k1133b/k1133b.py`; Appendix A.3 by `experiments/k1133/k1133.py`.
7. **figures/**: soft-link `k1129_qlike_comparison.png`, `k1129_dm_heatmap.png`, `k1133_qlike_by_period.png`, `k1133_dm_heatmap.png`, `k1133b_qlike_5model.png`, `k1133b_ms_state_prob.png`, `k1133b_dm_heatmap.png`.
8. **Pre-submission checklist**: run paper-workflow Self-contained paper folder checks from `CLAUDE.md` paper-workflow rules.
9. **reproduce.py**: one-shot script that re-runs the three K-level experiments and diffs output against `reproduce_report.json`.

## Target journal candidates

Ranked by fit (based on scope, methodology, and negative-result receptivity):

1. **Journal of Empirical Finance** (JoEF, Elsevier) — primary target. Strong track record on GARCH extensions, cryptocurrency volatility, and negative-result methodology papers. 2024 impact factor 2.1. Submission page limit flexible for methodology papers.
2. **Journal of Financial Econometrics** (JFEC, OUP) — direct home of Catania (2018). Very appropriate since the paper tests and falsifies a JFEC-published regime-switching claim for Bitcoin.
3. **Journal of Risk** (Incisive Media / Risk.net) — if revision emphasises VaR/ES angle of the heavy-tail innovation finding.
4. **Quantitative Finance** (Taylor & Francis) — as a fallback; accepts short empirical methodology notes.
5. **International Journal of Forecasting** (IJF, Elsevier) — considers methodology submissions but tends toward longer broad-application studies; fit is weaker but DM-HLN is their signature tool.

For a first submission, we recommend Journal of Empirical Finance.

## Strict constraints followed

- No `.tex` output. Only `.md` and `.json` files in `experiments/k1214/`.
- All numerical results verbatim from upstream K1129/K1133/K1133b JSON. Cross-verified: K1129 full-sample BTC $t = -4.58$ matches; K1133 P1 $t = -4.67$ matches; K1133b M4 vs M3 $t = +2.67$ matches; K1133b MS vs M3 $t = +5.97$ matches; K1133b MS vs M1 $t = +0.28$ matches.
- Cross-experiment numerical divergence: **NONE detected**. P1 QLIKE values for M1 / M2 / M3 match between K1133 and K1133b (1.9926 / 2.2339 / 2.1904).
- Academic finance writing style maintained: claim-evidence matching, no overclaims, limitations section included, Harvey (2016) threshold reported alongside raw $p$-values.
- Seed 42 referenced where applicable.
- Worktree scope limited to `experiments/k1214/`.

## Limitations of this draft

1. **References are a starter set (16 entries)**; the main-thread should expand the bibliography in the $\sim 20-30$ range typical for top-tier finance journals. Notable additions to consider: additional cryptocurrency volatility papers (Katsiampa, 2017 *Economics Letters*; Baur and Dimpfl, 2018 *Applied Economics*), additional MS-GARCH/MS-GAS literature (Haas et al. 2004 *Journal of Financial Econometrics*; Bauwens et al. 2014 *Econometric Reviews*), and proxy-robust loss literature beyond Patton (2011).
2. **Some numbers in-text use rounded presentation** (e.g., "$t = -4.58$" rather than "$t = -4.578$"). Main-thread can choose presentation precision per journal house style.
3. **Figure placeholders not yet embedded**. The draft text describes but does not reference specific figure numbers; main-thread will add `\ref{fig:...}` during LaTeX conversion.
4. **Appendix is minimal**. Consideration for full-results tables for all three sub-periods at submission-ready precision is deferred to main-thread.

## Success criteria (per K1214 brief)

- [x] `k1214_paper_draft.md` ~4,000 words with complete structure (abstract through references).
- [x] 6 sections + abstract + references + appendix.
- [x] All canonical numbers verbatim from K1129, K1133, K1133b JSONs.
- [x] `k1214_paper_outline.json` structured outline produced.
- [x] `README.md` produced.
- [x] No `.tex` output.

## References

- Catania, L. (2018). Dynamic Adaptive Mixture Models with an Application to Volatility and Risk. *Journal of Financial Econometrics*, 16(3), 493–544.
- Creal, D., Koopman, S. J., and Lucas, A. (2013). Generalized autoregressive score models with applications. *Journal of Applied Econometrics* 28(5):777–795 / *JASA* 108(501):1–18 (working paper).
- Glosten, L. R., Jagannathan, R., and Runkle, D. E. (1993). *Journal of Finance*, 48(5), 1779–1801.
- Harvey, D., Leybourne, S., and Newbold, P. (1997). *International Journal of Forecasting*, 13(2), 281–291.
- Klaassen, F. (2002). *Empirical Economics*, 27(2), 363–394.
- Patton, A. J. (2011). *Journal of Econometrics*, 160(1), 246–256.
- Hwang, S., and Valls Pereira, P. L. (2006). *European Journal of Finance*, 12(6–7), 473–494.
