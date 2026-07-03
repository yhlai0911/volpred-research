# k1616 | Cointegration error-correction term (ECT) as a HAR-RV covariate

**Verdict: NULL** — the cointegration error-correction term provides **no robust
incremental out-of-sample HAR-RV forecasting power**, including for the one pair
that is genuinely cointegrated (VIX term structure).

---

## Motivation & differentiation

Two cointegrated assets share a long-run equilibrium. Their short-run deviation —
the **error-correction term (ECT)** — measures cross-asset disequilibrium.
Economic intuition: when the equilibrium is stretched (|ECT| large), correction
pressure builds and realized volatility may rise. If true, ECT could seed a vol
strategy / pairs signal (a monetization angle).

**Research question:** Does `ECT_{t-1}` (and `|ECT_{t-1}|`) add *incremental* OOS
forecasting power for an asset's realized variance, **over and above** a standard
Corsi (2009) HAR-RV baseline?

**Differentiation vs prior K:** knowledge.json has no cointegration/ECT × HAR-RV
entry (grep `cointegrat` returns only category-field noise). Prior HAR-covariate
experiments used illiquidity (k1472), jump/macro regime (k1462), foreign flow
(k1518) — none used a cross-asset cointegration disequilibrium term.

## Data (single source: `data/cache/price_cache.db`, table `price_data`)

| Pair | y | x | Sample | N (coint) | Cointegrated (EG 5%)? |
|------|---|---|--------|-----------|-----------------------|
| SPY-QQQ | SPY | QQQ | 2016-01-04 → 2026-07-02 | 2639 | **No** (ADF p=0.296) |
| GLD-TLT | GLD | TLT | 2016-01-04 → 2026-07-02 | 2639 | **No** (ADF p=0.825) |
| SPY-EEM | SPY | EEM | 2016-01-04 → 2026-07-02 | 2639 | **No** (ADF p=0.512) |
| VIX-VIX3M | ^VIX | ^VIX3M | 2020-01-02 → 2026-07-02 | 1633 | **Yes** (coint p=0.0046, ADF p=0.00085) |

- **RV proxy:** Garman-Klass daily variance from OHLC (canonical
  `volpred.data.preprocessing.compute_garman_klass_vol`). Baseline HAR and
  HAR+ECT use the **same** RV definition → we test the ECT increment, not
  HAR-vs-anything-else.
- **Cointegration price series:** `adj_close`, `log` for ETFs, `level` for the
  VIX term-structure pair.
- **Forecast targets:** SPY, QQQ (SPY-QQQ); GLD, TLT (GLD-TLT); EEM (SPY-EEM,
  SPY already covered); SPY (VIX-VIX3M term-structure ECT → equity RV, the
  strongest economic prior).

## Method

1. **Cointegration gate (Engle-Granger, full sample, descriptive only):**
   statsmodels `coint` both directions + ADF on the OLS residual. Full-sample use
   here is a *gate*, never a forecasting input. A pair is eligible for ECT only if
   cointegration is not rejected at 5%.
2. **HAR-RV baseline (Corsi 2009), log-RV:** daily = `RV_{t-1}`, weekly =
   `mean(RV_{t-5..t-1})`, monthly = `mean(RV_{t-22..t-1})`. Target = `RV_t`.
3. **HAR+ECT:** baseline + `ECT_{t-1}` + `|ECT_{t-1}|`.
4. **OOS:** expanding window, monthly refit (`refit_freq=21`), burn-in 750.
   Both the cointegration β (for the ECT feature) and the HAR coefficients are
   re-estimated on data **through `i-1` only**; the forecast for day `i` uses
   **zero** information from day `i`.
5. **Retransformation:** log-normal `exp(pred + 0.5·resid_var)`, each model using
   its own in-sample residual variance (fair, common bias direction).
6. **Evaluation:** QLIKE via `qlike_pointwise` (actual/predicted direction), MSE
   auxiliary. **DM test (Newey-West HAC) + Harvey-Leybourne-Newbold (1997)
   small-sample correction.** Single 1-step horizon.

## Anti-error rule compliance (`.claude/rules/experiments.md`)

| Rule | Compliance |
|------|-----------|
| **Lookahead (highest risk)** | HAR features all `.shift(1)` (known at end of `t-1`); `ECT_{t-1}` uses β fitted on `[0,i-1]` and price at `i-1`; forecast for day `i` uses no day-`i` info. Explicit in `run_oos`. |
| **Forward-label / refit** | 1-step target = `RV_t`; training rows `j` have targets fully realized before day `i` (expanding, `target_end < forecast_origin`). |
| **In-sample β leakage** | Cointegration β re-estimated expanding (monthly). `*_static_beta` variant is a **hybrid sensitivity only** (forecast ECT feature uses full-sample β while the model coefficient stays expanding-β-trained; **not** a pure static-β model), disclosed as mildly leaky — not treated as formal robustness. |
| **Seed fixed** | `SEED=20260704`, `np.random.seed`. |
| **QLIKE direction** | `qlike_pointwise` (actual/predicted), not reversed. |
| **DM + HLN + HAC** | `dm_test` (Newey-West) + `hln_correct`; single horizon = target H. |
| **Fair comparison** | baseline & HAR+ECT: same lag, same RV proxy, same OOS window, same retransform. |
| **RV proxy target match** | GK RV used for both models; no GARCH-vs-HAR target mismatch (preamble §1). |

## Results

### OOS QLIKE (lower is better); DM/HLN positive t ⇒ HAR+ECT better

| Pair → target | Cointegrated? | N_oos | QLIKE HAR | QLIKE HAR+ECT | Δ% | HLN t | HLN p |
|---------------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| SPY-QQQ → SPY | No | 1889 | 0.38090 | 0.37910 | +0.47% | +0.60 | 0.552 |
| SPY-QQQ → QQQ | No | 1889 | 0.31954 | 0.31899 | +0.17% | +0.17 | 0.866 |
| GLD-TLT → GLD | No | 1889 | 0.38653 | 0.37989 | +1.72% | +1.30 | 0.195 |
| GLD-TLT → TLT | No | 1889 | 0.29694 | 0.29746 | −0.17% | −0.29 | 0.772 |
| SPY-EEM → EEM | No | 1889 | 0.33061 | 0.33328 | −0.81% | −1.56 | 0.120 |
| **VIX-VIX3M → SPY** | **Yes** | 883 | 0.35144 | 0.35033 | +0.32% | **+0.11** | **0.909** |

**No configuration reaches even 5% significance**, let alone Harvey-strict |t|>3.

### The key finding: in-sample significance ≠ OOS value

- **VIX-VIX3M → SPY** (the only genuinely cointegrated pair): the ECT is **highly
  in-sample significant** (HAC t = **4.26** on ECT, **3.54** on |ECT|), i.e. the
  term-structure disequilibrium *is* contemporaneously correlated with SPY RV.
  Yet OOS it adds **nothing** (DM t = +0.11, p = 0.91). **HAR's own lagged RV
  already spans that information** — VIX term structure and realized vol are
  collinear, so ECT is redundant *conditional on* the HAR features. This is the
  classic in-sample-vs-OOS gap.
- **GLD-TLT → GLD** has in-sample ECT HAC t = 4.45, but the pair is **not
  cointegrated** → this is a **spurious** regression on a non-stationary
  regressor. Under a hybrid static-ECT-feature sensitivity (forecast ECT uses the
  full-sample β while the model coefficient stays expanding-β-trained — **not** a
  pure static-β model) the OOS effect even flips negative
  (`hln_t_static_beta = −2.18`), and the honest expanding-β OOS is insignificant
  (t = 1.30, p = 0.195). This is exactly why the cointegration gate matters: raw
  in-sample ECT t-stats on non-cointegrated pairs are misleading. (Caveat: the
  `any_pair_ect_helps_*` verdict flags scan all pairs and do not gate out
  non-cointegrated ones; harmless here since every pair is insignificant, but the
  "cointegrated-eligible-only" principle should be enforced in the flag logic
  before any future positive is claimed.)

### Figures
- `k1616_ect_vs_rv.png` — VIX-VIX3M ECT (term-structure slope) vs SPY annualized
  realized vol. Visible co-spiking at 2024-08 and 2025-03 stress, but HAR already
  captures it.
- `k1616_qlike_bar.png` — HAR vs HAR+ECT OOS QLIKE across all pair→target configs
  (all differences economically and statistically negligible).

## Verdict — NULL (honestly reported)

Cointegration ECT provides **no robust incremental HAR-RV forecasting power**.
The one genuinely cointegrated pair (VIX term structure) is in-sample significant
but OOS-redundant given HAR; the non-cointegrated pairs are spurious. **Do not
build a vol signal on cointegration ECT as a HAR add-on.** Honest null: HAR-RV's
long-memory structure already absorbs the disequilibrium information that a
cross-asset ECT could plausibly carry.

### Caveats / scope
- Daily OHLC → GK RV proxy (no intraday RV available). Conclusions are about a
  range-based RV target; an intraday 5-min RV target is untested.
- ECT specification = Engle-Granger residual + |ECT|. Alternative ECT forms
  (VECM-implied speed-of-adjustment, regime-switching ECT) untested.
- VIX pair sample is short (2020-, N=1633; N_oos=883) — the shortest and the
  most economically motivated, yet still flat OOS.

## Related K / literature
- **Corsi (2009)** HAR-RV — the baseline this augments.
- **Engle & Granger (1987)** cointegration & error-correction — the ECT source.
- HAR-covariate augmentation experiments: k1472 (illiquidity), k1462 (jump/macro),
  k1518 (foreign flow) — all similar "does feature X beat plain HAR" null-prone
  designs; k1616 adds cross-asset disequilibrium to that family (also null).

## Reproduce
```bash
uv run python experiments/k1616_cointegration_ect_har_rv/k1616_cointegration_ect_har_rv.py
```
Deterministic (`SEED=20260704`). Writes `k1616_cointegration_ect_har_rv_results.json`
+ 2 PNGs.
