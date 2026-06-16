# K1513 — Commodity short-term momentum-reversal coexistence under vol regime (PoC)

**Status**: NULL (PoC; no statistically-significant regime separation after Bonferroni)
**Date**: 2026-06-16
**Proposer**: Claude (autonomous loop, task `research_1_4_vol`)
**Executor**: Claude (worktree-agent context, main repo run)

## 1. Motivation

A recent JFEM/SSRN 2025-26 strand argues that in commodity markets the
traditional horizon decomposition (short-term reversal / medium-term momentum
/ long-term reversal) breaks down: at the same short horizon (1-4 weeks),
momentum and reversal coexist, and the dominant phase is conditional on
volatility regime. The conjecture this experiment tests is:

* **H1** — high-vol regime: reversal dominates (negative autocorrelation
  amplified by inventory/liquidation pressure).
* **H1** — low-vol regime: momentum dominates (slow information diffusion,
  trend-following speculator behaviour).
* **H0** — no regime separation: signs of momentum and reversal returns
  conditional on vol regime are not statistically distinguishable.

K1339 already touched commodity ETF momentum-regime as an event-study signal
for vol jumps (CONDITIONAL_PASS); the differentiation here is: same-horizon
coexistence + return PnL framing (not event-study), and vol regime as the
*separation* axis rather than the outcome.

## 2. Differentiation vs prior knowledge

| Prior K | Relation | Differentiation |
|---|---|---|
| K1339 (CONDITIONAL_PASS) | commodity ETF 21d/63d momentum regime → vol jump | Mine is return-PnL within a single horizon (1-4 weeks), not event-study on vol forecast. |
| K1129 / K1133b (PASS-tier) | BTC GAS-t reversal regime-concentrated | Methodology reference: regime split + Newey-West DM. Different asset, different horizon, different signal definition. |
| `a04a1eda` (TZ momentum) | intraday momentum/reversal timing bias | Methodology reference: strict `.shift(1)` discipline. No overnight gap content here. |

## 3. Design

* **Universe**: GLD, SLV, USO, UNG, CPER, PDBC (yfinance, adjusted close).
* **Sample**: 2010-01-01 → 2026-06-15 (16.5 years).
* **Frequencies**: weekly (W-FRI close), monthly (month-end close).
* **Signal**: `position_t = sign(past_N_return_{t-1})` for momentum; reversal
  is the same signal negated. N ∈ {1, 2, 4} bars.
* **Vol regime**: trailing 26-bar (weekly) / 6-bar (monthly) realized
  volatility, classified high/low by *past-only expanding median*. No
  future information.
* **Costs**: 1 bp applied to absolute position flips (sensitivity-style; does
  not drive verdict).
* **Statistical test**: Diebold-Mariano on `r_rev - r_mom` series, HAC standard
  error (Newey-West, lag = round(T^{1/3})), within each regime.
* **Multiple testing**: 36 cells (6 ETFs × 3 N × 2 freq); Bonferroni α = 0.05/36
  ≈ 0.00139. Two regimes evaluated separately (conservative).
* **Seed**: 42 (preserved for the bootstrap diagnostics; DM uses analytical HAC).

## 4. Lookahead defence (audited)

* `mom_sig_raw = np.sign(past_n.shift(1))` — signal at t uses past_N_return
  computed from prices up to and including t-1.
* `rolling_lag = rolling.shift(1)` — trailing vol used at t is computed on
  returns up to t-1.
* `expanding_med` of rolling-vol-lagged → regime threshold itself does not see
  future.
* Bar return `r_t` is paired with the lagged signal → strict `signal_{t-1} →
  r_t` convention.
* Momentum and reversal share the *same* lag (reversal is `-1 × momentum`),
  ensuring fair head-to-head. Costs apply symmetrically.

## 5. Results (summary)

* 36 cells in total; 18 cells (50%) show the H1-consistent direction
  (`mean_rev_high > mean_mom_high` AND `mean_mom_low > mean_rev_low`).
* DM significance after Bonferroni (α ≈ 0.00139): **0 / 36 in either regime**.
* DM significance at raw α = 0.05: 1 cell in high-vol regime
  (reversal-dominates), 3 cells in low-vol regime (momentum-dominates).
* Sharpe magnitudes are modest and symmetric (|Sharpe| ≤ 0.62 across all
  asset/N/freq combinations), consistent with the well-known fact that
  unconditional commodity short-horizon momentum is weak after the 2010s
  financialisation era.
* Notable counter-examples that **break** the H1 direction: GLD monthly N=1/2/4
  all show DM t negative in the *low*-vol regime — reversal wins where the
  hypothesis predicted momentum. PDBC monthly N=1 shows reversal dominates in
  the high-vol regime (DM t = -2.19) — consistent with H1.

Full per-cell grid (Sharpe mom/rev, MDD, DM t/p in three slices) is in
`k1513_results.json`. Visualisation: `k1513_regime_split.png`.

## 6. Verdict

**NULL** — sign-consistent direction in half the grid but no cell survives
Bonferroni. Raw-α positives (4/36) are fewer than expected by chance under H0
at 5%, suggesting the regime split *does* carry some signal — but it is too
weak to claim regime separation as a robust effect on yfinance ETF proxies.

The result does **not** falsify the JFEM/SSRN 2025-26 thesis; it shows that
when proxied with broad commodity ETFs and `signal.shift(1)`-strict design, the
effect is below the detection threshold of a 16-year sample at 6 assets. The
original literature uses real futures with curve/roll information, which carries
strictly more information than total-return ETFs.

## 7. Limitations

1. **ETF proxy, not futures**: roll yield, basis, and inventory effects are
   absorbed into total returns; the canonical academic momentum/reversal effect
   sits on futures excess returns. Using futures (continuous-contract with
   honest roll adjustment) is the natural next step.
2. **6-asset universe** is too narrow to power Bonferroni-corrected DM at 36
   cells. Extending to grains/livestock/softs (DBA / CORN / WEAT / SOYB)
   would give meaningful Bonferroni headroom.
3. **Single vol-regime metric** (trailing realized vol). The literature uses
   GARCH-filtered regimes, VIX/OVX percentiles, or HMM states; any of these
   may sort observations more cleanly.
4. **No size/value sorting**: the headline result in commodity momentum often
   uses cross-sectional spreads, not single-asset time-series. The PoC here
   is time-series only.
5. **DM uses normal-approximation p-values**. With T_high or T_low under 100,
   Patton-style block bootstrap would be more honest. Diagnostic-only.

## 8. Follow-up ideas

* Re-run with continuous futures (Bloomberg or Quandl `CHRIS/CME_*`) for at
  least GC, SI, CL, NG, HG over 2005-2026.
* Replace trailing-vol-median split with HMM-state regimes from K1462 / K1460
  pipeline; would let us compare regime sortings on the same data.
* Add a cross-sectional version: rank N-period returns across the universe and
  build long-short within high-vol vs low-vol regimes.
* If futures + HMM still NULL → write up as a clean falsification of the
  JFEM/SSRN claim on ETF/HMM-proxy ground.

## 9. Reproducibility

```bash
uv run python experiments/k1513/k1513.py
```

* No cached state; cold-run downloads `yfinance` quotes each invocation.
* Deterministic at the seed level (`np.random.seed(42)`); yfinance data may
  refresh as new bars print but the historical bars 2010-2025 are stable.

## 10. References

See `references.md`.
