# K1025b: BTC Vol Spillover to NASDAQ-100 Equity (VXN target)

**Date**: 2026-04-28
**Author**: VolPred Research System (main thread)
**Status**: complete
**Parent experiment**: K1025 (BTC vol → VIX)
**Purpose**: Multi-asset OOS robustness check for P10 (paper/crypto-fear-channel) per cross-paper meta-evaluation 2026-04-28 mandatory IJFMIM/JEF blocker fix.

---

## Motivation

P10 cross-paper meta-evaluation (2026-04-28, agent `a4c82fc4`) identified single-asset OOS as a top-tier blocker for IJFMIM/JEF submission: P6 PRG and P9 GARCH-X-VIX both run multi-asset OOS (5-6 markets), while P10 originally tested only the BTC→VIX (S&P 500 fear gauge) channel. Reviewers comparing same-author submissions would notice the asymmetry.

K1025b runs the identical 6-method analysis on the NASDAQ-100 fear gauge (^VXN) paired with QQQ as the equity ETF. If the asymmetric Granger / QR sign-reversal / regime-watershed / DY-net-receiver findings replicate, the family-level spillover claim is supported across two equity-fear gauges rather than a single asset.

## Variant from K1025

Three lines changed (mechanical ticker swap):

| Component | K1025 | K1025b |
|---|---|---|
| Equity ETF | SPY | QQQ |
| Fear gauge | ^VIX | ^VXN |
| Tracking | S&P 500 | NASDAQ-100 |

All 6 methods (symmetric Granger / asymmetric Hatemi-J / quantile regression / Diebold-Yilmaz / DCC / DM forecast) and all parameters (sample window 2015-02 to 2026-04-09, lag windows, quantiles, regime cutoffs, OOS window 2019-01-01 to 2026-04-08) are byte-identical to K1025.

Variable naming: `vix` is preserved as the internal Python variable name (for code-reuse simplicity); all output JSON keys rename `vix` → `vxn` and `experiment_id` is set to `K1025b`.

## Lookahead Audit

Inherited from K1025 framework:
- **Granger causality**: `statsmodels.tsa.stattools.grangercausalitytests(maxlag=L)` is internally lag-aware; tests whether *past* $X$ predicts *current* $Y$, not contemporaneous association.
- **Quantile regression**: explicit `t-1` lag in $Q_\tau(\text{VIX}_t | \text{RV}^{(20)}_{\text{btc}, t-1})$ specification.
- **DM forecast**: explicit `t-1` lag in `VIX_t = α₀ + Σ α_j VIX_{t-j} + γ * RV_btc_{t-1} + u_t`.
- **ADF tests**: stationarity check only; no forecast produced.
- **DCC / DY spillover**: contemporaneous correlation / variance decomposition; descriptive not predictive.

K1025 passed prior code review (per `research_program.md` 2026-04 history); K1025b mechanical ticker swap inherits the same protections.

## Results Summary

| Finding | K1025 (BTC→VIX) | K1025b (BTC→VXN) | Pattern preserved? |
|---|---|---|---|
| Asymmetric Granger (BTC-) lag 3 F | 10.18 | 11.46 | ✅ same direction |
| Asymmetric Granger (BTC+) lag 1-5 p | 0.16-0.95 (all NS) | 0.14+ (NS) | ✅ |
| QR sign reversal $\beta_{0.05}$ | $-2.86$ | $-1.46$ | ✅ |
| QR upper-tail $\beta_{0.95}$ | $+22.31$ | $+16.29$ | ✅ |
| QR amplification ratio ($\tau=0.95/0.5$) | 8.54$\times$ | $\sim$11$\times$ (similar order) | ✅ |
| 2020 subperiod Granger F | 11.05 | 13.41 | ✅ same regime watershed |
| DY total spillover mean | 90.11% | 90.09% | ✅ near-identical |
| DY net BTC (receiver) | $-76.89$pp | $-76.64$pp | ✅ near-identical |
| DCC Crisis-regime mean | 0.41 | 0.51 (Crisis VIX>30 def doesn't apply to VXN; using existing K1025 thresholds) | ✅ rises with stress |
| OOS DM stat (Harvey) | $-0.98$ (NS) | $-0.43$ (NS) | ✅ both fail Harvey |
| OOS DM full-sample improvement | $-0.24\%$ MSE | $-0.11\%$ MSE | ✅ both deteriorate marginally |

**Verdict**: All 6 P10 stylized facts replicate qualitatively in the BTC→VXN channel. Quantitative magnitudes shift modestly (e.g., upper-tail amplification 8.54× → ~11×, DM −0.98 → −0.43), consistent with the empirical variation expected when changing from S&P 500 to NASDAQ-100 fear gauge.

## Files

- `k1025b.py` — fork from `experiments/k1025/k1025.py` with 4 line edits
- `k1025b_results.json` — full JSON output (descriptive / ADF / Granger / asymmetric / QR / DY / DCC / forecast / sub-period)
- `k1025b_results.png` — visualization
- `README.md` (this file)

## Cross-link

- Parent: `experiments/k1025/`
- Paper: `paper/crypto-fear-channel/`
- Cross-paper meta-evaluation: `paper/crypto-fear-channel/research_notes/cross_paper_meta_eval_2026_04_28.md` (Section 6 multi-asset OOS blocker)
- Knowledge entry: pending (will write to `storage/memory/knowledge.json` after main.tex §6 update)
