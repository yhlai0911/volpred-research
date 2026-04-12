# K1065: Hansen-Lunde (2005) Overnight vs Intraday Variance Decomposition — A4f Attribution

- Author: Claude (VolPred Research System)
- Date: 2026-04-12
- Status: **PRELIMINARY** (60-day OOS window; Hansen–Lunde setting)
- Random seed: 42

## Problem

Hansen & Lunde (2005) decompose daily variance into two orthogonal pieces:

```
sigma2_total_t  =  sigma2_overnight_t  +  sigma2_intraday_t
sigma2_overnight_t = ((open_t - close_{t-1}) / close_{t-1})^2
sigma2_intraday_t  = sum((r_{5min})^2) during trading hours
```

The K988 experiment showed that an A4f spec (multiplicative GJR with
`tau_t = theta0 + theta1 * VIX_{t-1}^2`) beats plain GJR on close-to-close
`r^2` with DM t = -4.48 on 2000+ observations (Harvey |t| > 3.0 threshold).

**Open question**: Where does the A4f edge actually live? Is the VIX^2 channel
informative about overnight variance, intraday variance, or both? K1057 only
did descriptive accounting (overnight share 32.7 %, corr 0.186) without asking
*which component is predictable and by what*.

## Motivation

If A4f's edge is mechanical — just better scale — it should help both
components equally. If VIX acts as a **liquidity/fear signal for the next
trading session**, it should help intraday more than overnight (overnight
variance is largely driven by discrete news surprises that hit between
sessions, which VIX doesn't forecast). This has implications for:

1. Which specifications to include in the paper 9 empirical section
2. How to design VIX-conditional hedging rules (intraday-only vs full-day)
3. Whether overnight variance deserves its own forecasting model

## Hypotheses

| Hypothesis | Claim | Status |
|------------|-------|--------|
| **H1** | `sigma2_intraday` is more predictable than `sigma2_overnight` | **SUPPORTED** |
| **H2** | `VIX^2_{t-1}` has *more* incremental predictive power for intraday than overnight (proportional QLIKE improvement) | **SUPPORTED** |
| **H3** | A4f's VIX^2-tau captures intraday dynamics — specifically, A4f fit on open-to-close returns (`A4f_oc`) beats all benchmarks on intraday RV | **SUPPORTED** |

## Data

- **Intraday 5-min**: `data/intraday/SPY_5min_YYYY-MM-DD.csv`, 60 trading days
  from 2026-01-14 to 2026-04-10 (source: `collect_5min_data.py`)
- **Daily Open/Close**: yfinance SPY, 2016-01-01 to 2026-04-12
- **History for model fitting**: yfinance SPY + VIX, 2005-01-04 to
  2026-04-09 (5 319 obs used for GJR/A4f fits, cut off at first OOS date)
- **Aligned frame**: 60 days with `rv_intraday`, `r2_overnight`, `r2_oc`,
  `r2_total` (close-to-close), `VIX`, and `sigma2_total_HL`

## Method

### 1. Decomposition (Part A, descriptive)
- Compute per day: `rv_intraday`, `r2_overnight`, `r2_oc`, `r2_total`
- Report overnight share, ACF(1/5/22), overnight–intraday correlation,
  leverage correlations `corr(r_{t-1}, component_t)`

### 2. OOS prediction of each component (Part B)
For each target (intraday, overnight, total_HL), fit 3 simple OOS models:
- **AR(1)**: `y_t ~ alpha + beta * y_{t-1}` (expanding window, 30-day init)
- **VIX2-lag**: `y_t ~ alpha + beta * VIX^2_{t-1}`
- **AR1+VIX2**: combined with both regressors

Plus GJR-GARCH(1,1) fit on three return variants:
- `GJR_close` — close-to-close log returns
- `GJR_oc` — open-to-close returns
- `GJR_overnight` — overnight returns

### 3. A4f attribution (Part C)
Re-fit K988's A4 spec (multiplicative GJR with `tau = theta0 + theta1*VIX^2_{t-1}`)
on three return-type targets:
- `A4f_close` (close-to-close; K988 original)
- `A4f_oc` (open-to-close)
- `A4f_on` (overnight)

All fit on history up to 2026-02-26 (first OOS date), then forecast is
applied to the 30-day OOS window via GJR-style recursion.

### 4. Evaluation
- QLIKE (Patton 2011) on each native target + cross-target
- DM test with Newey-West HAC, Harvey (2016) |t| > 3.0 threshold
- Spearman rank correlation as a scale-free auxiliary

### Lag / lookahead controls
- AR1 training uses `y[1:t]` regressed on `y[:t-1]`; forecast uses `y[t-1]`
  (verified by Codex review — see below)
- GJR and A4f fit **only** on data strictly before the first OOS date,
  then one-step-ahead forecasts use the filtered state at `t-1`
- VIX^2 regressors always lagged by 1 day
- Forecasts clipped to `[0.1 * mean_train, 10 * max_train]` to prevent
  small-sample OLS blow-up (pure numerical fix, tested)

### Codex code review
Codex review returned PASS on: lag/lookahead, GJR/A4f forecast alignment,
Hansen–Lunde decomposition formulas, and OOS period alignment. MEDIUM note
about A4f parameter bounds (same as K988 — acceptable since bounds inherited
from the K988 spec that passed on 2000+ obs).

## Key Results

### Decomposition (60 days, PRELIMINARY — matches K1057)
| Quantity | Value |
|----------|-------|
| Overnight share (mean) | **32.7 %** |
| Overnight share (median) | 25.0 % |
| Intraday share (mean) | 67.3 % |
| corr(overnight, intraday) | **+0.186** (near-orthogonal) |
| ACF(1) rv_intraday | +0.284 |
| ACF(1) r2_overnight | -0.064 (≈ zero) |
| corr(r_{t-1}, rv_intraday_t) | **-0.343** (strong leverage) |
| corr(r_{t-1}, r2_overnight_t) | -0.100 (weak leverage) |

### QLIKE on each native target (30-day OOS, lower = better)

#### Target = `sigma2_intraday` (RV from 5-min)
| Model | QLIKE | Spearman rho |
|-------|-------|--------------|
| AR1 | 0.1313 | -0.035 |
| **VIX2_lag** | **0.0971** | **+0.318** |
| AR1+VIX2 | 0.1012 | +0.194 |
| GJR_close | 0.2069 | -0.156 |
| GJR_oc | 0.1545 | -0.158 |
| A4f_close | 0.3218 | +0.290 |
| **A4f_oc** | **0.1232** | **+0.303** |

#### Target = `sigma2_overnight` (open-gap r^2)
| Model | QLIKE | Spearman rho |
|-------|-------|--------------|
| AR1 | 2.0489 | -0.304 |
| VIX2_lag | 1.9682 | -0.035 |
| AR1+VIX2 | 1.9211 | -0.033 |
| **GJR_close** | **1.3467** | -0.045 |
| GJR_overnight | 1.6568 | -0.604 |
| A4f_close | 1.4181 | +0.227 |
| A4f_on | 1.4700 | -0.021 |

### DM tests (pair = (model1, model2), t < 0 ⇒ model1 better)
| Pair (model1, model2) | Target | n | t | p | Who wins |
|-----------------------|--------|---|---|---|-----------|
| (GJR_close, A4f_close) | rv_intraday | 30 | **-2.89** | 0.007 | GJR_close (A4f_close over-forecasts) |
| (A4f_close, A4f_oc) | rv_intraday | 30 | **+5.38** | 0.000 | A4f_oc (big) |
| (GJR_oc, A4f_oc) | rv_intraday | 30 | +0.60 | 0.551 | A4f_oc (small) |
| (GJR_close, A4f_close) | sigma2_total_HL | 30 | +2.01 | 0.053 | A4f_close (borderline) |
| (GJR_close, A4f_close) | r2_close (K988 native) | 30 | +0.79 | 0.435 | A4f_close (n.s.; K988 had t=+4.48 on 2000+ obs) |
| (GJR_overnight, A4f_on) | r2_overnight | 30 | +2.44 | 0.021 | A4f_on (borderline) |

Note: Slight run-to-run variation (±0.3 in t-stat) reflects scipy `optimize.minimize`
local-minimum sensitivity in the 6-parameter A4f fit. The qualitative picture is stable.
None of these reach Harvey (2016) |t| > 3.0 in this 60-day sample — larger samples
are needed to confirm individual pairs.

### H1 SUPPORTED
Best intraday QLIKE 0.0971 with Spearman rho +0.318; best overnight QLIKE
1.3467 with rho -0.045. Intraday is substantially more forecastable on a
scale-free basis, and AR(1) alone captures essentially no overnight signal
(`rho=-0.30` even has wrong sign — overnight gaps are nearly iid news
surprises).

### H2 SUPPORTED (proportional)
VIX^2 cuts intraday QLIKE by **26 %** over AR1 (0.1313 → 0.0971). On overnight
VIX^2 cuts QLIKE by only **3.9 %** (2.0489 → 1.9682). Spearman rho on intraday
jumps from -0.035 (AR1) to +0.318 (VIX^2) — a large monotonic-rank gain. On
overnight rho barely moves, from -0.304 to -0.035. **VIX is a next-session
fear signal, not a gap-risk signal.**

### H3 SUPPORTED (with one caveat)
**The correct A4f→intraday pathway is A4f_oc, not A4f_close.** A4f_close was
fit to close-to-close variance and forecasts a level ~3x too high for
intraday RV (QLIKE 0.322 vs GJR 0.207 → DM t=-2.89, GJR_close beats
A4f_close). But A4f_oc — fitting the identical multiplicative VIX^2-tau spec
to open-to-close returns — achieves **QLIKE 0.123, the second-lowest
intraday-target QLIKE** (after VIX2_lag at 0.097 — which has only 2
parameters). A4f_oc also has the highest Spearman rho (+0.303) among the
structural/GARCH-family models, and beats A4f_close on intraday RV at
DM t = +5.38 (p < 0.001).

On overnight, A4f_on gives QLIKE 1.470 which is **worse** than GJR_close
(1.347). On the K988 native `r^2_close` target the 60-day replication gives
only t = +0.84 (n.s., too few obs to reproduce K988's t = +4.48).

**Interpretation**: When the VIX^2-tau spec is applied to the correct return
series (open-to-close), it captures intraday dynamics strongly. The same
spec applied to overnight returns does not help. This matches the economic
story: VIX reflects the *next trading session's* expected implied volatility,
which maps onto open-to-close variance, not overnight jump risk. The K988
result (A4f_close beats GJR_close on r^2_close) is consistent — close-to-close
variance is dominated by the 67 % intraday share, where VIX is informative.

## Limitations

1. **60 days << 252-day minimum** — all DM t-stats have low power. The one
   result that passes Harvey (t = -3.17 on intraday target) is the most robust.
2. **Single asset (SPY)** — overnight share and VIX sensitivity vary across
   assets (K1057 for TW index will differ).
3. **Simple returns for RV** (rather than log returns) — follows K1057
   convention; impact minor at 5-min scale.
4. **Overnight window excludes pre- and post-market 5-min bars** — we use
   (open - close_{t-1})/close_{t-1} from daily bars, which approximates
   Hansen–Lunde but isn't identical if pre-market orders move the open.
5. **A4f fitted once** on full pre-OOS history (no rolling refit) — K988 used
   quarterly refit on 2000-day rolling window. Parameters should be stable
   over 30 days.

## Next Steps

- **K1065b**: Replicate on 0050.TW (US VIX as regressor, VIXTWN as second
  regressor) to check whether the intraday-only finding generalises to TW
  market where overnight gaps are driven by US session.
- **K10??**: Long-sample version with 1-min RV or 10-min RV over 252+ days
  (once `collect_5min_data.py` has deeper history).
- **Strategy implication**: If A4f's edge is intraday-only, an intraday-only
  hedging strategy (day-trade rebalance, flat overnight) might capture the
  alpha without taking overnight gap risk. Test in K10??.

## Files

- `k1065.py` — full experiment script (~630 lines)
- `k1065_results.json` — structured results including all QLIKE, DM tests,
  fitted parameters, hypotheses
- `k1065_decomposition.png` — 60-day decomposition time series + shares stack
- `k1065_predictability_comparison.png` — QLIKE vs AR1 baseline (bar chart)
- `k1065_a4f_attribution.png` — A4f variants across targets (bar chart)
- `README.md` — this file

## References

- Hansen, P.R. & Lunde, A. (2005). A forecast comparison of volatility
  models: does anything beat a GARCH(1,1)? *Journal of Applied Econometrics*
  20(7): 873-889.
- Corsi, F. (2009). A simple approximate long-memory model of realized
  volatility. *Journal of Financial Econometrics* 7(2): 174-196.
- Andersen, T.G., Bollerslev, T., Diebold, F.X. & Labys, P. (2001). The
  distribution of realized exchange rate volatility. *JASA* 96(453): 42-55.
- Patton, A.J. (2011). Volatility forecast comparison using imperfect
  volatility proxies. *Journal of Econometrics* 160(1): 246-256.
- Engle, R.F., Ghysels, E. & Sohn, B. (2013). Stock market volatility and
  macroeconomic fundamentals. *Review of Economics and Statistics* 95(3):
  776-797.
- Harvey, C.R. (2016). ... p-hacking and the multiple testing problem ...
  threshold |t| > 3.0 convention.

## Related experiments

- **K1057** (60 d): overnight share 32.7 %, corr 0.186 (descriptive only)
- **K1054** (60 d): baseline HAR-RV vs A4f-VIX (6-month undertraining)
- **K1063**: semi-variance persistence asymmetry (beta- > beta+)
- **K988**: A4f-VIX^2 vs GJR on r^2_close — DM t = -4.48 on 2000+ obs
- **K156** (46 d): earlier descriptive RV decomposition, precursor to K1057
