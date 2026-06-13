# K1476 — VRP Decline and Short-Vol Strategy Edge Erosion

**Status**: MIXED (NULL on H1 VRP decline + H3 predictive correlation; directional-only on H2 SVXY Sharpe)
**Created**: 2026-06-14 (Asia/Taipei)
**Reviewer**: Codex GPT-5.4 (round-1 CONDITIONAL_PASS → applied fixes → round-2 FAIL → applied fixes → round-3 verification below)

## Hypothesis

The Chicago Fed (2025) raised the concern that the **Variance Risk Premium (VRP)** has structurally declined in the post-2018 era, eroding the economic edge of naive short-volatility strategies. K1476 tests three falsifiable claims:

- **H1**: VRP (VIX² − RV², monthly) has a statistically lower mean in post-2018 (B) vs 2006-2017 (A).
- **H2**: A naive long-SVXY monthly rebalance strategy delivers lower Sharpe / worse MDD in regime B.
- **H3**: The 1-month-ahead predictive correlation `corr(VRP_t, ret_{t+1})` is structurally weaker in B.

## Method

- **Data**: yfinance ^VIX, ^GSPC (2006-01 to 2026-05); SVXY (2011-10-04 onward); VXX (post-Jan-2018 reissue only — see disclosure).
- **VRP measure**: `VRP_t = VIX²_{t-1, EoM} − RV²_t (annualized)`. The VIX leg uses `.shift(1)` to enforce ex-ante observability.
- **Regime boundary (primary)**: 2018-03-01 — ex-ante motivated by the Feb 5, 2018 XIV blowup episode that structurally changed the inverse-VIX-ETF ecosystem.
- **Robustness boundaries**: 2018-01-01, 2019-01-01, 2020-04-01 (post-COVID).
- **Tests**:
  - H1: Welch t-test + HAC Newey-West (1994) auto-lag.
  - H2: HAC test of mean SVXY return diff + per-regime Sharpe with 1000-bootstrap 95% CI.
  - H3: Per-regime corr(VRP_t, ret_{t+1}) with bootstrap CI. Pairs classified by **return-month** to prevent boundary leakage.
- **Lookahead controls**: VRP uses `vix.shift(1)`; H3 strategy returns use `shift(-1)` for next-month alignment. Bootstrap seed=42.
- **Final partial month dropped**: a month is included only if it has ≥15 observed trading days.
- **Short-VXX feasibility fix**: collateralized return floored at -100% (`max(0, 1 + (-r_vxx)) − 1`).

## Results

| Quantity | A (2006-02 to 2018-02) | B (2018-03 to 2026-05) |
|---|---|---|
| Months (VRP) | 145 | 99 |
| VRP mean (vol-pts²) | 72.9 | 71.4 |
| VRP median | 105.1 | 120.1 |
| VRP share positive | 80.0% | 82.8% |
| SVXY months | 76 | 100 |
| SVXY Sharpe (ann.) | 0.71 \[-0.07, 1.77\] | 0.47 \[-0.20, 1.30\] |
| SVXY MDD | -90.5% | -52.5% |
| Short-VXX MDD | n/a (no yfinance data) | -100% (wipeout) |

**H1 (VRP mean diff A−B)**: NW diff = +1.5 vol-pts², t = 0.02, p = 0.987 — **null**. VRP magnitude has not statistically declined.

**H2 (SVXY return diff A−B)**: NW diff = +2.78 pp / month, t = 1.27, p = 0.20 — directional but not statistically significant. Sharpe drops from 0.71 to 0.47 but bootstrap CIs overlap substantially.

**H3 (predictive corr)**: SVXY A = +0.020 \[-0.19, 0.23\] vs B = -0.052 \[-0.15, 0.16\] — both indistinguishable from zero; cannot conclude weakening.

**Boundary robustness** (key takeaway):
| Boundary | VRP A−B | NW p | SVXY Sharpe A | SVXY Sharpe B |
|---|---|---|---|---|
| 2018-01-01 | +12.6 | 0.89 | 1.14 | 0.08 |
| 2018-03-01 (primary) | +1.5 | 0.99 | 0.71 | 0.47 |
| 2019-01-01 | -10.6 | 0.91 | 0.64 | 0.57 |
| 2020-04-01 | **-144.4** | **0.07** | 0.53 | 0.85 |

The 2020-04-01 split flips sign and reaches marginal significance — VRP *expanded* post-COVID, not contracted. The 2018-01-01 boundary shows the most dramatic Sharpe erosion (1.14 → 0.08) but is heavily driven by the Feb 2018 XIV blowup being booked into regime B — a single-event artifact, not a structural decline.

## Verdict

**MIXED (1/3 directional only)**

- H1 NULL — no statistically significant VRP decline at any tested boundary except a marginal (p=0.07) *increase* at the 2020 boundary.
- H2 directional only (Sharpe 0.71 → 0.47 not significant; HAC p = 0.20).
- H3 NULL — predictive correlation indistinguishable from zero in both regimes.

**Interpretation**: The "VRP decline → short-vol edge erosion" narrative is **not supported** by simple VIX² − RV² measurement at monthly frequency. The apparent edge erosion in 2018-01-01 splits is a Feb 2018 XIV-event artifact, not a structural premium compression. Short-VXX in regime B did suffer a complete wipeout (-100% MDD), but this is consistent with the known one-shot 2018-02-05 event, not a persistent premium decline. **The takeaway is that the Chicago Fed (2025) framing should be tested against a more refined VRP measure (e.g., model-free implied vs realized at multi-horizon) before claiming a structural break.**

This is broadly consistent with VolPred-internal prior K430 (IS sig, OOS null), K734 (VRP not tradable beyond 12/VIX), and K913 (VRP return prediction NULL at all horizons).

## Mission contribution

- **Mission #2 (research rigor)**: NULL result honestly reported; refines prior K430/K734 by adding regime decomposition + boundary robustness. Adds a small but concrete piece to the VolPred VRP literature trail.
- **Mission #4 (platform operations)**: Informs reader-facing strategy cards — the "short-vol VT" strategy family does NOT need an explicit "post-2018 VRP regime warning" flag at this evidence level. Avoids over-claiming.
- **Mission #3 (academic paper)**: This result feeds a potential rebuttal note ("The VRP-decline thesis is not robust to boundary choice") usable in JBF/FRL-style commentary letters.
- **Monetization**: Indirect — supports platform credibility by NOT overclaiming a fashionable "decline" narrative.

## Files

- `k_vrp_short_vol_edge_erosion_2026_06_14.py` — fully reproducible script.
- `k_vrp_short_vol_edge_erosion_2026_06_14_results.json` — all numerics + boundary robustness.
- `fig_vrp_regime.png` — VRP time series with regime mean lines.
- `fig_short_vol_sharpe.png` — rolling 36-month Sharpe of long-SVXY and short-VXX (B only).
- `references.md` — literature + data sources.

## Reproduce

```bash
uv run python experiments/k_vrp_short_vol_edge_erosion_2026_06_14/k_vrp_short_vol_edge_erosion_2026_06_14.py
```

Deterministic given seed=42 + same yfinance snapshot. Re-downloads will pick up the latest end-of-history.
