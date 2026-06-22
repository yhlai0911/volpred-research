# K1533: RECH-X replication and extension to Taiwan (TAIFEX)

- Experiment ID: `k1533`
- Status: complete (final v3 run n=479 US / n=320 TW). Verdict: PARTIAL
  REPLICATION vs RealGARCH (SPY only, H≥5); RECH-X never beats pre-specified
  GJR(1,1) → 9th ML-ceiling confirmation. Codex-reviewed (2 passes, all blocking
  issues fixed).
- Model under test: **RECH-X** (Recurrent Conditional Heteroskedasticity with eXogenous covariates)
- Paper: Nguyen, H.T., Nguyen, H., & Tran, M.-N. (2024), "Deep learning enhanced
  volatility modeling with covariates", *Finance Research Letters* 69:106145.
  SSRN abstract_id=4657189; LiU DiVA full text diva2:1901445.

## Motivation and differentiation

This project has confirmed an "ML ceiling" eight times: deep-learning / ML
volatility models do **not** beat simple GARCH/HAR on our data.

- **K1312** GARCH-to-Neural (LSTM): SPY QLIKE 99.4% worse than GJR — NULL.
- **K1263** KAN-GARCH-MIDAS (NN + macro covariates): 24-33% worse — NULL.
- **K816v2** GINN, **K784** GARCH-GRU: both NULL.

The owner explicitly lifted the novel-method moratorium for this replication.
The task is an **honest test** of whether RECH-X can reproduce its claimed win
over RealGARCH on our data. A NULL result is a complete result — it would be
the 9th ML-ceiling confirmation. We do not tune parameters or report selectively
to manufacture a "successful replication".

**Difference from K1312 / K1263**: K1312 chained a generic LSTM onto GARCH
output; K1263 used a KAN with macro covariates inside a GARCH-MIDAS. RECH-X is
architecturally distinct: it keeps the *additive* GARCH(1,1) recursion intact
and lets a single-state Simple-RNN drive only the **constant term** `omega_t`,
fed an exogenous covariate. The additive design is the paper's central claim for
why it should help where prior NN-GARCH hybrids did not.

## Model (paper Eqs. 2a-2d)

RECH-X = SRN-GARCH(1,1) with Student-t innovations and an exogenous covariate:

```
y_t       = sigma_t * eps_t,            eps_t ~ standardized t_nu
sigma_t^2 = omega_t + alpha y_{t-1}^2 + beta sigma_{t-1}^2
omega_t   = beta0 + beta1 h_t
h_t       = ReLU( v . x_t + w_h h_{t-1} + b ),   h_1 = 0
x_t       = (omega_{t-1}, y_{t-1}, sigma_{t-1}^2, z_{t-1})
```

`z` = exogenous covariate (realized measure RV). The model reduces to GARCH(1,1)
when `beta1 = 0`. `v_RV` quantifies the importance of the realized measure.

## Baselines (paper Section 2.1), all with Student-t innovations

- **GARCH(1,1)**: `sigma_t^2 = omega + alpha y_{t-1}^2 + beta sigma_{t-1}^2`
- **GJR(1,1)** (project-standard extra leverage baseline):
  `+ gamma 1[y_{t-1}<0] y_{t-1}^2`
- **GARCH-X**: `+ pi z_{t-1}` (z non-negative RV)
- **RealGARCH** (Hansen et al. 2012, non-exponential):
  `sigma_t^2 = omega + beta sigma_{t-1}^2 + gamma RV_{t-1}` with a Gaussian
  measurement equation `RV_t = xi + phi sigma_t^2 + tau1 eps_t + tau2(k eps_t^2-1) + u_t`
  estimated jointly.

The paper's primary claim (Table 3, S&P500): RECH-X beats RealGARCH on MSE
(0.095 vs 0.120, ~21%) and on all five predictive scores.

## Data — sources, periods, sample sizes, fidelity

### US (SPY, QQQ)
- **Source**: yfinance daily OHLC + Adj Close, 2007-2024 (4,528 trading days each).
- **Returns**: `100 * dlog(AdjClose)`.
- **Realized measure**: **Garman-Klass daily variance proxy** from OHLC
  `GK = 0.5 (ln H/L)^2 - (2 ln2 - 1)(ln C/O)^2`, scaled to percent^2.
- **FIDELITY GAP**: the paper uses **5-min intraday RV from the Oxford-Man
  Institute**. We have **no local US 5-min high-frequency data** (K1350 already
  recorded this). The Garman-Klass daily range estimator is the best available
  proxy; it is far less informative than 5-min RV. This weakens the covariate's
  signal-to-noise versus the original, biasing **against** finding a RECH-X win.
  We report the gap honestly rather than fabricate intraday RV.

### Taiwan (TAIFEX TX futures)
- **Source**: 5-min TAIFEX TX bars reconstructed in k1100h
  (`experiments/k1100h/data/_taifex_5min_2017-2021.parquet`), **day session only**.
- **Period**: 2017-05-17 .. 2021-12-30, 1,137 trading days (~60 5-min bars/day).
- **Returns**: daily close-to-close `100 * dlog(close)`.
- **Realized measure**: **TRUE 5-min intraday realized variance**
  `RV_t = sum (5-min log returns)^2` — a genuine high-frequency RV, matching the
  spirit of the paper's covariate (higher fidelity than the US proxy). Caveat:
  day-session only, so it excludes overnight variance.

## Method and anti-lookahead controls

- **Estimation**: own **MLE** (scipy.optimize L-BFGS-B on the analytic
  Student-t log-likelihood), with parameter transforms enforcing stationarity
  (`alpha,beta>0`, `alpha nu/(nu-2)+beta<1`, `nu>2`). The paper uses Bayesian
  likelihood-annealing SMC. For well-identified parameters the MLE point estimate
  approximates the SMC posterior mean — this is a legitimate reproduction of the
  same likelihood (K1213: a package/method limitation is not model invalidity).
  RECH-X is fit with **>=12 random multistart** (fixed seed) on the first window
  to handle the NN non-convexity; warm-started with 4 restarts on subsequent
  refits (the surface barely moves day-to-day). The variance recursions are
  numba-JIT compiled (`@njit`) — an execution-speed change only; nll values are
  numerically identical to the pure-Python version (verified GARCH 2364.68,
  GJR 2334.07 unchanged), giving ~70x speedup on RECH-X.
- **Lookahead is the highest risk**:
  - Every `sigma_t^2` forecast uses only information dated `<= t-1`. The
    covariate enters as `z_{t-1}` in **every** model (identical lag convention
    across RECH-X and all baselines).
  - The RECH-X recurrent input `x_t` is built entirely from `t-1` quantities
    (`omega_{t-1}, y_{t-1}, sigma_{t-1}^2, z_{t-1}`).
  - **Expanding-window OOS**: refit on `data[:origin]`, forecast the window
    `[origin, origin+H-1]`. The H-day target is the average realized variance
    over that window, whose end (`origin+H-1`) is strictly **after** the training
    window end (`origin-1`), so `target_end < forecast_origin` holds for every
    refit and horizon. Refit cadence = every 10 days (bounded cost; warm-started).
  - All RNG (multistart inits, generator) uses **fixed seed 1533**.
- **Horizons**: 1, 5, 22 days. Each horizon's H-day forecast uses forward
  iteration of its own recursion; the DM test uses the matching horizon `h` for
  the HAC/Harvey correction (no shared horizon across targets).
- **Evaluation**: Patton **QLIKE** (robust to noisy RV proxy) + **MSE** on the
  volatility scale (sqrt), both against the realized measure. **DM-HLN test with
  Harvey small-sample correction**; significance threshold **|t| > 3** (project
  Harvey standard). RECH-X and every model tested vs RealGARCH per horizon.

## Code review (Codex, gpt-5.5 xhigh) — issues found and fixed before the run

Codex reviewed `k1533.py` (two passes, gpt-5.5 xhigh) and flagged correctness
issues; **all fixed before the canonical run**:

1. **RECH-X forecast reset the RNN hidden state to 0 at the forecast origin**
   (old `forecast_path` set `h_state = 0.0`). This discarded the recurrent
   memory exactly at the point of forecasting, **crippling RECH-X and biasing
   the comparison against it**. Fix: `filter_rechx` now also returns the last
   in-sample hidden state `h_last`, and the forward forecast **continues** the
   RNN memory from it.
2. **Full-sample demeaning** of returns (`y - mean(y)` over the whole series)
   leaked the OOS-period mean into the in-sample fit (mild lookahead). Fix:
   returns are now demeaned **per training window** using only `y[:origin]`.
3. **RealGARCH multi-step forecast blew up** — the first draft iterated
   `rv_l = sigma^2`, which with the fitted gamma>1 gave persistence
   `beta+gamma>1` and diverging H=22 variance, unfairly inflating RealGARCH's
   loss (caught by the "too good to be true" check at the smoke stage). Fix:
   multi-step now uses the measurement-equation expectation
   `E[RV_t|F]=xi+phi*sigma^2`, giving `E[sigma^2_{t+1}]=(omega+gamma*xi)+(beta+gamma*phi)*sigma^2_t`.
4. **RealGARCH measurement leverage term mis-centered** (2nd Codex pass): the
   draft used `tau2*((nu-2)/nu*eps^2 - 1)`, but `eps=y/sigma` is the
   *standardized* unit-variance innovation, so the Hansen leverage must be
   `tau2*(eps^2 - 1)` for `E[tau(eps)]=0`. The wrong centering left a non-zero
   constant making the measurement mean inconsistent with the forecast
   expectation. Fix: use `tau2*(eps^2 - 1)`, which makes
   `E[RV_t|F]=xi+phi*sigma^2` exact (consistent with issue 3's forecast).

Fixes 1-2 are anti-lookahead / pro-RECH-X; fixes 3-4 correct the RealGARCH
**baseline** (pro-fairness toward the benchmark). After all four, the partial US
win for RECH-X is robust and the comparison is symmetric.

## Success criteria

Success = a **rigorous, reproducible, honest** comparison with correct tests,
NOT "RECH-X wins". Verdict per market:
- **REPLICATED**: RECH-X beats RealGARCH on QLIKE with DM |t|>3 at >=1 horizon,
  no significant losses.
- **PARTIAL**: significant wins at some horizons, significant losses at others.
- **NULL**: no significant difference, or RECH-X significantly worse.

## Files

- `prepare_data.py` — builds US (GK proxy RV) and Taiwan (true 5-min RV) datasets.
- `k1533.py` — models, MLE, expanding-window OOS, QLIKE/MSE, DM-HLN. `--quick`
  flag runs a short OOS window for smoke testing.
- `k1533_results.json` — per-market, per-horizon QLIKE/MSE + DM-HLN + verdict.
- `figures/qlike_*.png` — QLIKE-by-horizon bar charts (per market).
- `figures/dm_heatmap_rechx_vs_realgarch.png` — DM-HLN t-stat heatmap.
- `data/` — `us_SPY.csv`, `us_QQQ.csv`, `us_VIX.csv`, `tw_TX.csv`.
- `references/sources.md` — primary paper + base RECH + baselines + methodology refs.

## Conclusion (final run v3: n=479 US, n=320 TW OOS one-step-origins; H=1/5/22)

**Headline verdict: PARTIAL replication of the RealGARCH comparison, but a clean
9th confirmation of the ML-ceiling.** After fixing the RealGARCH baseline
(measurement-eq centering + multi-step expectation) and using a sign-explicit DM
gate and a **pre-specified GJR(1,1)** ceiling, the result is unambiguous: RECH-X
never beats a fixed simple model, and the deep-learning recurrence adds nothing
over a linear GARCH-X at the horizons that matter.

All numbers below are QLIKE (lower=better) with DM-HLN Harvey t (negative =
RECH-X lower loss); a "win/loss" requires lower mean QLIKE AND |t|>3.

### (A) vs RealGARCH — the paper's headline claim
| Market | H=1 | H=5 | H=22 | verdict |
|---|---|---|---|---|
| US_SPY | tie (DM −1.4) | RECH-X better (−4.8*) | RECH-X better (−4.3*) | **REPLICATED** |
| US_QQQ | tie (+0.1) | tie (−2.6) | tie (−1.8) | **NULL** |
| TW_TX  | tie (−1.2) | tie (−0.7) | tie (+0.6) | **NULL** |

(* = \|t\|>3.) Only SPY significantly beats RealGARCH, and only at H≥5; at the
paper's actual 1-day setting it ties everywhere. QQQ and Taiwan never beat
RealGARCH significantly. (With the earlier RealGARCH multi-step bug, all 3 looked
REPLICATED — the bug was inflating RealGARCH's long-horizon loss. After the fix
the apparent "win" mostly evaporates.)

### (B) vs GARCH-X — does the RNN add value over the same covariate, linearly?
QLIKE(RECH-X) ≈ QLIKE(GARCH-X) at **H=1 and H=5 in all three markets** (DM
\|t\|<1.5 → tie). A significant edge appears **only at H=22** (SPY −3.3*, QQQ −4.3*,
TW −3.0*). **The predictive gain is the realized-measure covariate, captured
equally by the linear GARCH-X; the Simple-RNN contributes nothing at 1/5-day
horizons and only a marginal long-horizon edge.**

### (C) vs the pre-specified GJR(1,1) — the honest ML-ceiling test
(GJR is a fixed ex-ante model → DM here is NOT post-selection biased.)
| Market | QLIKE H=1 (RECH-X / GJR) | DM vs GJR (H=1 / H=5 / H=22) | result |
|---|---|---|---|
| US_SPY | 0.357 / 0.378 | −1.6 / −2.3 / −2.2 | indistinguishable |
| US_QQQ | 0.329 / 0.348 | −1.7 / −1.9 / −0.5 | indistinguishable |
| TW_TX  | 0.403 / 0.296 | **+8.4 / +3.1** / +1.4 | **RECH-X WORSE** |

**RECH-X never significantly beats GJR on any market or horizon.** On Taiwan —
the only market with **genuine 5-min intraday RV** (highest data fidelity) — the
plain GJR(1,1) decisively beats RECH-X (QLIKE 0.30 vs 0.40 at H=1, DM +8.4).

### Honest takeaway
RECH-X partially replicates the FRL paper's RealGARCH comparison (SPY only, H≥5),
but the layered design shows (i) the only edge is over the *weakest* baseline
(RealGARCH), (ii) the RNN adds nothing over a linear GARCH-X with the same RV
covariate except a fragile H=22 edge, and (iii) against a pre-specified GJR it
never wins and on true-RV Taiwan it loses badly. This is the **9th confirmation
of the project's ML-ceiling**: a deep-learning volatility model does not robustly
beat simple GARCH-family models on our data; any apparent advantage traces to the
exogenous covariate and/or a single long horizon, not to the neural recurrence.

### Fidelity limits (do not over-read)
- US realized measure is a Garman-Klass daily **proxy**, not 5-min RV — lower
  signal-to-noise than the paper's Oxford-Man data (biases against RECH-X, so the
  thin SPY edge is if anything conservative).
- Estimation is MLE, not the paper's Bayesian SMC (documented method gap).
- The H=22 target is a 22-day average RV with overlapping windows; the marginal
  H=22 edges rest on a 21-lag (h−1) Bartlett HAC with limited effective sample —
  treat as weak.
- Taiwan RV is day-session-only (excludes overnight) and the sample is 2017-2021.
- The per-horizon oracle "best baseline" (argmin QLIKE) is reported in the JSON
  as context only; it is post-selection biased, so the verdict uses the fixed
  pre-specified GJR instead.

See `k1533_results.json` for full per-horizon QLIKE/MSE and every DM-HLN test.
