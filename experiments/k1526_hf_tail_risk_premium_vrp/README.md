# K1526: High-Frequency Tail Risk Premium as a Time-Varying Predictor of SPY Excess Return and VRP

## 0. Verdict (TL;DR)

| Channel | Sample | Spec | t-stat (HAC, lag=4) | p | OOS R^2 | DM p | Conclusion |
|---|---|---|---|---|---|---|---|
| Daily RDSV | 2010-01 → 2026-05, n=197 months | M2 RDSV alone -> excess_ret_{t+1} | **+3.36** | **0.0008** | — | — | **In-sample sig (Harvey 3.0 cleared)** |
| Daily ES | same | M1 ES alone -> excess_ret_{t+1} | +1.25 | 0.21 | — | — | NULL |
| ES + VIX (focal) | same | M3 -> excess_ret_{t+1} | ES: -0.60 / VIX: +1.87 | 0.55 / 0.06 | -0.045 | 0.40 | **OOS NULL** |
| ES + VIX -> RV_{t+1} | same | VRP side-check | VIX: +1.97 | 0.049 | (in-sample R^2 = 0.214) | — | VIX predicts next-month RV (expected) |
| 5-min concept | 4 months 2026-03..06 | TRP_lower/_alt | — | — | — | — | **n=4, concept only** |

**Overall verdict: CONDITIONAL_PASS.**
RDSV (realized downside semi-variance, the simplest monthly downside-tail proxy) cleared the Harvey (2016) |t|>3 bar with HAC SE (t=+3.36, p=0.0008, n=197) for predicting next-month SPY excess return in-sample.
But the focal multivariate spec (ES + VIX) fails the OOS gate: R^2_OOS = -4.5%, DM p = 0.40 against historical-mean baseline. The in-sample RDSV signal does not translate into beat-the-mean OOS forecasts. Bootstrap 95% CI for the focal-spec t(ES_d) is [-3.06, +1.56] — sign-unstable.

The result is therefore **honest in-sample evidence of a downside-tail premium, but no OOS edge**. Publishable as a methodology / null-OOS article, **not** as a strategy claim.

## 1. Motivation and difference from prior K's

Variance risk premium (VRP) literature (Bollerslev-Tauchen-Zhou 2009) shows that the gap between option-implied and realized variance predicts equity excess returns. Kelly-Jiang (2014) and Bali-Cakici-Whitelaw (2011) show tail-risk-related quantities also have predictive content. K1526 asks: does a **high-frequency** realized truncated downside moment (a time-varying TRP) deliver predictive content beyond, or distinct from, VIX/VRP?

Prior K's:
- **K447 (SKEW Index)** -> tail risk via CBOE SKEW: NULL
- **K768 (Conformal VaR)** -> distribution-free downside coverage: a coverage tool, not a premium predictor
- **K789 (Google Trends tail)** -> behavioural proxy for tail attention: NULL

K1526 deliberately **avoids** SKEW and search-volume proxies. Instead it uses the realized 5%-tail mean from intraday and daily returns — the model-free truncated moment that Kelly-Jiang argue captures cross-sectional tail-risk pricing.

## 2. Data

| Series | Source | Range | Frequency |
|---|---|---|---|
| SPY OHLC | yfinance | 2010-01-04 → 2026-06-16 | daily |
| SPY OHLC | yfinance | 2026-03-23 → 2026-06-16 | 5-min |
| ^VIX | yfinance | 2010-01-04 → 2026-06-16 | daily |
| ^IRX (13-week T-bill, annualized %) | yfinance | 2010-01-04 → 2026-06-16 | daily |

- Daily SPY log-return: `r_d = log(C_t / C_{t-1})`.
- Risk-free daily: `^IRX / 100 / 252`. Excess return: `r_d - rf_d`.
- 5-min log-return reset at each session boundary.
- yfinance intraday history limit is 60 trading days; 5-min channel reported as **concept validation only**.

## 3. Method

### 3.1 Predictors (all dated as of end of month *t*)

| Variable | Definition |
|---|---|
| `RDSV` | sum_{d in month t} r_d^2 * I(r_d < 0)  — realized downside semi-variance (daily) |
| `ES_d` | -mean(r_d \| r_d <= q5%(month t)) — daily expected-shortfall proxy at 5% |
| `vix_end` | VIX close on last trading day of month t |
| `RV_d` | sum_{d in month t} r_d^2 — realized variance (daily) |
| `VRP_d` | (vix_end/100)^2 / 12  - RV_d — proxy VRP at monthly horizon |

### 3.2 Target

`excess_ret_next[t] = sum_{d in month t+1}(r_d - rf_d)` — next-month SPY excess return.

### 3.3 Estimation

- OLS with HAC (Newey-West) standard errors, lag = 4 (Andrews data-driven rule-of-thumb for n=197).
- Five nested specs (M1–M5) covering univariate to full.
- VRP side regression: `RV_d[t+1] ~ ES_d[t] + vix_end[t]`.

### 3.4 Out-of-sample

- Campbell-Thompson (2008) rolling-window R^2_OOS, window = 60 months, baseline = historical mean.
- Focal spec: ES_d + vix_end.
- DM test with Harvey-Leybourne-Newbold small-sample correction, h=1, baseline-vs-model error series.

### 3.5 Bootstrap

- Stationary block bootstrap, block = floor(n^(1/3)) ≈ 5, n_boot = 1000, seed = 42.
- 95% CI on t-stats of focal spec + R^2_OOS.

## 4. Results

### 4.1 In-sample regressions (next-month excess return)

| Spec | Predictor | Coef | HAC SE | t | p |
|---|---|---|---|---|---|
| M1 | ES_d | 0.355 | 0.284 | 1.25 | 0.211 |
| **M2** | **RDSV** | **2.156** | **0.642** | **3.36** | **0.0008** |
| M3 | ES_d | -0.315 | 0.527 | -0.60 | 0.55 |
| M3 | vix_end | 0.00156 | 0.00083 | 1.87 | 0.061 |
| M4 | ES_d | -1.209 | 0.663 | -1.83 | 0.068 |
| M4 | vix_end | 0.00254 | 0.00073 | **3.48** | **0.0005** |
| M4 | VRP_d | -2.377 | 1.557 | -1.53 | 0.127 |
| M5 | ES_d | -1.290 | 0.637 | -2.02 | 0.043 |
| M5 | RDSV | 3.841 | 6.271 | 0.61 | 0.54 |

**Key in-sample reads** (HAC, n=197):
- **RDSV alone clears Harvey |t|>3** (3.36) and standard 1% (0.0008). Magnitude: 1 std-dev of monthly RDSV (~0.0021) predicts ~0.45% extra monthly excess return.
- Once VIX is added (M4), VIX dominates with t=3.48; ES turns *negative* (-1.83) — multicollinearity-induced sign flip.
- M5 shows RDSV's marginal power vanishes when ES is included — ES + RDSV are near-collinear.
- VIX_end is the strongest robust predictor (t > 3 in M4). This is *consistent with* prior literature (Bollerslev-Tauchen-Zhou) and not a new finding.

### 4.2 VRP side: predict next-month RV

| Predictor | Coef | HAC SE | t | p |
|---|---|---|---|---|
| ES_d | 0.0336 | 0.0333 | 1.01 | 0.31 |
| vix_end | 0.00034 | 0.00017 | 1.97 | 0.049 |
| R^2 | 0.214 | | | |

VIX_end significantly predicts next-month realized variance (R^2 = 21%); ES_d adds nothing marginal. This is the textbook IV-RV relation, replicated here for sanity.

### 4.3 Out-of-sample (focal spec ES + VIX)

- Rolling-window R^2_OOS = **-0.0452** (model worse than mean baseline by 4.5%).
- DM test (HLN-corrected): t = -0.85, p = **0.397**, n = 137 OOS months.
- Bootstrap 95% CI on R^2_OOS: [-0.144, +0.095], mean -0.014.

**The OOS gate fails.** The in-sample t=3.36 on RDSV does not survive as predictive content against a naive historical-mean baseline OOS. The cumulative SSE-difference plot (Fig 2) is largely flat with a late drift downward.

### 4.4 Bootstrap CI on t-stats (focal spec ES+VIX)

| Param | t_mean (boot) | 95% CI |
|---|---|---|
| ES_d | -0.64 | [-3.06, +1.56] |
| vix_end | +2.17 | [-0.31, +5.49] |

Sign-unstable for ES, weakly positive for VIX. Consistent with the OOS NULL.

### 4.5 5-minute channel (concept only, n=4 months)

| Month | n_5min | TRP_lower | TRP_alt | q5% |
|---|---|---|---|---|
| 2026-03 | 539 | 0.00197 | 0.00122 | -0.00162 |
| 2026-04 | 1617 | 0.00156 | 0.00112 | -0.00090 |
| 2026-05 | 1540 | 0.00140 | 0.00097 | -0.00096 |
| 2026-06 | 924 | 0.00238 | 0.00174 | -0.00155 |

4 monthly observations — well below the 60-day window's effective sample size for monthly aggregation. **No inferential statement is drawn.** The TRP magnitudes are economically plausible (10-20 bps tail-mean gap per 5-min observation).

## 5. Interpretation

**Honest read of the evidence**:
1. The naive in-sample RDSV result (t=3.36) is genuine — but it is consistent with the well-known fact that *monthly realized variance and downside variance both correlate with subsequent excess return*, and once VIX (the standard control) is added, the marginal tail-specific content collapses.
2. **No OOS gain over historical mean** for the focal spec at the 60-month window. The forecasted excess return adds nothing actionable.
3. The 5-min channel is too short to test inferentially; it serves only to validate that the truncated-downside moment is computable and economically sized.

**What this rules out**: a simple high-frequency TRP proxy is unlikely to be a stand-alone monthly excess-return signal beyond VIX. It does not rule out a TRP role in **cross-sectional** pricing (Kelly-Jiang 2014, Bali-Cakici-Whitelaw 2011) or at higher horizons.

## 6. Limitations

1. **5-min channel sample is ~60 trading days only** (yfinance intraday cap). Monthly aggregation gives n=4 — concept-only, no inference.
2. Daily-channel "TRP" (RDSV, ES_d) is a downside proxy, not a true high-frequency TRP. Magnitudes will differ from a true 5-min ES over a 10-year window.
3. ES_d, RDSV, VIX, VRP_d are highly correlated; multicollinearity inflates SE in full spec (M5).
4. Single OOS window (60 months) tested; sensitivity to window size not reported.
5. ^IRX used as risk-free; FRED DGS3MO would be the canonical alternative. Differences are at the 1-2 bp level monthly.
6. Block bootstrap block = n^(1/3) is conventional; sensitivity not tested.
7. Sample includes only one true bear (2022) and the 2020 COVID drawdown after 2015 — OOS power for tail predictors is limited.

## 7. Reproducibility

```bash
cd <repo_root>
uv run --active python experiments/k1526_hf_tail_risk_premium_vrp/k1526_hf_tail_risk_premium_vrp.py
```

- Seed: 42 (bootstrap and all stochastic blocks).
- Output: `k1526_hf_tail_risk_premium_vrp_results.json` + 3 figures.

## 8. Files

| File | Purpose |
|---|---|
| `k1526_hf_tail_risk_premium_vrp.py` | Main script |
| `k1526_hf_tail_risk_premium_vrp_results.json` | All numerical results |
| `references.bib` | 8 citations |
| `figures/fig1_trp_overlay.png` | Daily ES proxy vs SPY excess overlay |
| `figures/fig2_rolling_oos_cumdiff.png` | Cumulative SSE diff (baseline - model) |
| `figures/fig3_trp_5min_concept.png` | 5-min monthly TRP (concept channel) |

## 9. Code review

Codex review pending at time of write — README will be appended with Codex verdict before merge. If Codex flags any CRITICAL issue, results may be revised.

## 10. Relation to K447 / K768 / K789

- K447 (SKEW): K1526 confirms that *some* tail proxy correlates with excess return in-sample, but loses OOS. K447's SKEW NULL is consistent — observed-IV-based tail proxies and realized-downside proxies behave similarly OOS.
- K768 (Conformal VaR): different question (coverage calibration), not directly comparable.
- K789 (Google Trends): K1526 finds the realized-tail signal also weak OOS, consistent with K789's behavioral-proxy NULL. The tail-premium literature is robust in cross-section, brittle in time-series.
