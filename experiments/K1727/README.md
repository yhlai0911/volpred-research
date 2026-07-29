# K1727: Volatility targeting — risky-asset-only efficacy, cross-asset re-validation

## Motivation

The backlog question re-tests a well-known finance claim on free data:

> Volatility targeting (VT) improves **risk-adjusted returns** for risky assets
> (equities, credit) but is **near-useless for bonds, FX, and commodities**.

Source hypotheses: JPM, *The Impact of Volatility Targeting* (Harvey, Hoyle,
Rattray, Sargaison, Balvers, Van Hemert, 2018) and Man Group (2025). The stated
mechanism is a negative relationship between volatility and returns in risk
assets (the "leverage effect"), combined with volatility clustering: because a
big rise in volatility tends to accompany bad returns, de-levering after
volatility rises lets VT sidestep the worst risk-adjusted periods. Bonds, FX and
commodities have a weaker or absent vol–return relationship, so VT only rescales
their return stream without shifting the risk-return trade-off.

This is a re-validation, not a new claim. It is distinct from prior VolPred VT
work (which is almost entirely SPY-centric) because the object of study is the
**risky vs non-risky partition across a cross-asset ETF panel**, not the tuning
of a single equity VT rule.

## Literature / project preamble

- Harvey et al. (2018), *The Impact of Volatility Targeting* (J. Portfolio Mgmt):
  VT's Sharpe benefit is concentrated in risk assets and is modest even there;
  it works at the monthly frequency over multi-decade futures panels.
- Man Group (2025) commentary reiterating the risk-asset concentration.
- Project priors (`storage/memory/knowledge.json`): SPY VT Sharpe is essentially
  flat across 6–16% targets ("VT just moves along the same risk-return line");
  multiple entries conclude VT's value is in drawdown/tail control, not Sharpe or
  alpha; GLD VT Sharpe looks high but is a gold-bull selection artifact.

## Method

For **each asset independently**, over its own longest available history:

1. **Realized vol** = trailing 20-day std of daily simple returns, annualized by
   `sqrt(252)`. (Robustness: also run at a 60-day window.)
2. **Lookahead policy (the single most important guard):** the vol-scaling
   signal is `signal.shift(1)`.
   ```
   realized_vol_t = rolling_20d_std(returns through t) * sqrt(252)
   raw_scale_t    = clip(target_vol / realized_vol_t, 0, leverage_cap)
   position_t     = raw_scale.shift(1)          # <-- uses info through t-1 only
   vt_excess_t    = position_t * excess_return_t # = raw_scale_{t-1} * excess_t
   ```
   The position held on day *t* is built entirely from data available through
   *t−1*; it never touches the day-*t* return or later.
3. **Two portfolios** (both on **excess** returns, `r − rf`, JPM-faithful):
   - `fixed_notional`: constant unit exposure (`position ≡ 1`).
   - `vol_targeted`: `position_t · excess_t`, target = **10% ann**, leverage
     capped at **2.0**.
   - Risk-free rate: `^IRX` 13-week T-bill (annualized %/100/252, forward-filled);
     falls back to 0 with a documented note if the download fails.
4. **Comparisons:**
   - **Sharpe gain (VT − fixed)** — PRIMARY. Sharpe is scale-invariant, so this
     is a legitimate comparison even though VT and fixed run at different
     exposure. Paired **moving-block bootstrap** (block = 21, reps = 1000,
     seed = 42) gives a 95% CI on the gain per asset.
   - **Left-tail extremes** — frequency of days beyond −3σ and the mean of the
     worst 1% of days, both **standardized by each series' own sigma** so they
     are scale-invariant and comparable.
   - **Max drawdown** — delegated to `volpred.stats.drawdown.compare_max_drawdown`,
     which reports raw MDD for both series **and** the exposure-matched gap
     (raw MDD is NOT comparable across different exposure; see that module).
   - `vol_return_corr` — `corr(realized_vol_{t-1}, return_t)`, a diagnostic for
     whether the JPM vol–return channel is even present at this frequency.
5. **Grouping:** risky = SPY, QQQ, HYG, LQD; non-risky = TLT, UUP, DBC, GLD. The
   hypothesis predicts the Sharpe gain is concentrated in the risky group.

### Data

yfinance auto-adjusted close, download start 2003-01-01. Each asset uses its own
longest history (start dates differ by ETF inception, documented per-asset in the
results JSON). Prices cached to `data/prices.csv`.

| Ticker | Bucket | Group | Sample start | Sample end | n_obs |
|---|---|---|---|---|---:|
| SPY | equities | risky | 2003-02-03 | 2026-07-27 | 5907 |
| QQQ | equities/tech | risky | 2003-02-03 | 2026-07-27 | 5907 |
| HYG | credit HY | risky | 2007-05-10 | 2026-07-27 | 4833 |
| LQD | credit IG | risky | 2003-02-03 | 2026-07-27 | 5907 |
| TLT | long UST | non-risky | 2003-02-03 | 2026-07-27 | 5907 |
| UUP | USD index | non-risky | 2007-03-30 | 2026-07-27 | 4861 |
| DBC | commodities (broad) | non-risky | 2006-03-08 | 2026-07-27 | 5128 |
| GLD | gold | non-risky | 2004-12-20 | 2026-07-27 | 5433 |

## Success criteria

- **CONDITIONAL_PASS minimum**: results reproduce, lookahead is correct
  (`shift(1)`), and the risky-vs-non-risky Sharpe-gain contrast is quantified,
  with the direction reported honestly even if it contradicts the hypothesis.
- A NULL or contradicting result is a valid outcome. No fabricated numbers.

## Result — weak / directional, does not cleanly reproduce at daily ETF frequency

**Verdict: the daily-ETF re-validation does NOT reproduce the JPM "VT improves
Sharpe for risky assets only" claim at significance. The Sharpe-improvement
channel is not statistically distinguishable from zero for any asset in either
group — every bootstrap CI straddles zero, so the study is underpowered rather
than proof of a true null; the risky-minus-non-risky mean gap (+0.043) is in the
hypothesized direction but tiny, not robust to the vol window, and internally
inconsistent (see below).**

### Sharpe gain (VT − fixed), 20-day vol window

| Ticker | Group | Sharpe fixed | Sharpe VT | **Gain** | Boot 95% CI | vol-ret corr |
|---|---|---:|---:|---:|---|---:|
| SPY | risky | — | — | **+0.081** | [−0.137, +0.300] | +0.01 |
| QQQ | risky | — | — | **+0.100** | [−0.076, +0.287] | +0.01 |
| HYG | risky | — | — | **−0.044** | [−0.336, +0.249] | +0.01 |
| LQD | risky | — | — | **+0.076** | [−0.099, +0.256] | +0.04 |
| TLT | non-risky | — | — | **+0.052** | [−0.097, +0.202] | +0.01 |
| UUP | non-risky | — | — | **+0.039** | [−0.102, +0.174] | −0.00 |
| DBC | non-risky | — | — | **−0.091** | [−0.287, +0.100] | −0.00 |
| GLD | non-risky | — | — | **+0.040** | [−0.140, +0.218] | +0.01 |

- **Every one of the 8 bootstrap CIs straddles zero.** No single asset shows a
  statistically distinguishable Sharpe gain from VT.
- Group means: risky **+0.053** vs non-risky **+0.010**; difference **+0.043**.
  The sign is in the hypothesized direction but the magnitude is tiny, and it is
  **not robust**: at a 60-day vol window the contrast **reverses** (risky mean
  **+0.012** < non-risky mean **+0.031**, driven by UUP +0.10 and GLD +0.09).
- It is also **internally inconsistent** with the partition: HYG (risky credit)
  is the most negative gain in the panel (−0.044), while TLT (non-risky bonds) is
  positive (+0.052), mid-pack, and larger than one of the four risky assets
  (HYG). So "concentrated in risk assets" does not hold at the individual-asset
  level.
- `vol_return_corr ≈ 0` for every asset. At daily frequency the vol→return
  channel the JPM mechanism relies on is not detectable in these series, which is
  a coherent explanation for why the Sharpe gains are near zero everywhere.

### Where a risky/non-risky split *does* appear: exposure-matched drawdown

The cleanest risk-asset pattern is in the **exposure-matched MDD gap** (MDD of VT
minus MDD of the fixed series rescaled to VT's realized vol — a same-risk, zero-
timing benchmark):

| Ticker | Group | raw MDD fixed | raw MDD VT | vol ratio | **exposure-matched gap** |
|---|---|---:|---:|---:|---:|
| SPY | risky | −0.561 | −0.272 | 0.60 | **+0.104** |
| QQQ | risky | −0.543 | −0.220 | 0.51 | **+0.098** |
| HYG | risky | −0.357 | −0.295 | 0.91 | +0.036 |
| LQD | risky | −0.271 | −0.324 | 1.20 | −0.005 |
| TLT | non-risky | −0.515 | −0.417 | 0.75 | −0.005 |
| UUP | non-risky | −0.224 | −0.285 | 1.31 | +0.002 |
| DBC | non-risky | −0.778 | −0.589 | 0.57 | −0.035 |
| GLD | non-risky | −0.457 | −0.404 | 0.61 | **−0.105** |

- Equities (SPY, QQQ) keep a large drawdown improvement even after removing the
  pure de-levering effect; gold (GLD) and DBC do not — their raw-MDD "benefit" is
  mostly just lower exposure. This is the sharpest risky/non-risky contrast in the
  study, and it is directionally consistent with the hypothesis.
- **Caveat (repo hard rule):** a positive exposure-matched gap is *necessary but
  not sufficient* for timing skill — it can be produced by a dispersed weight
  path with backwards timing. Confirming timing skill would require testing each
  gap against its own circular-shift (phase-randomized) null, which this
  experiment does **not** run. So this is a *suggestive* drawdown result, not a
  certified timing claim, and it lives outside the Sharpe channel the hypothesis
  is stated in.

### Left-tail severity

Standardized 1% expected-shortfall (in units of each series' own sigma) becomes
**less negative under VT for nearly every asset in both groups** (e.g. SPY
−4.23→−3.84, TLT −3.18→−2.97, GLD −3.87→−3.64). VT thins the standardized left
tail generally — a de-clustering effect that is **not** risk-asset-specific.

## Honest bottom line

- **Sharpe channel (the hypothesis as stated): NOT reproduced.** No asset has a
  significant VT Sharpe gain; the risky-vs-non-risky contrast is small, not
  significant, not robust to the vol window, and internally inconsistent. This is
  consistent with the project's prior finding that daily VT "moves along the same
  risk-return line" rather than improving Sharpe.
- **Drawdown channel:** a genuine risky-vs-non-risky split does appear in the
  exposure-matched drawdown gap (strong for equities, absent/negative for gold &
  DBC), but it is necessary-not-sufficient evidence and sits outside the Sharpe
  claim.
- **Scope caveat:** the JPM result is documented at monthly frequency over
  multi-decade, multi-instrument futures panels, and is modest even there. A
  daily-frequency, single-ETF-per-bucket test with a 20-day realized-vol
  estimator is a noisier, shorter proxy; "does not reproduce here" bounds the
  claim to this setup, it does not refute the source paper on its own terrain.

## Files

- `K1727.py` — reproducible; `signal.shift(1)`, `seed=42`, writes the results JSON.
- `K1727_results.json` — per-asset Sharpe(fixed/VT), gain + bootstrap CI, left-tail
  metrics, exposure-matched MDD, sample start/end, n_obs; group contrast; 60d
  robustness.
- `K1727_sharpe_gain.png` — Sharpe gain by asset with bootstrap CIs.
- `data/prices.csv` — cached yfinance adjusted closes.

## Review status

Claim surface = `K1727.py` + `README.md` + `K1727_results.json`. Certification
review (Codex primary path; subagent audit fallback) and any `knowledge.json`
entry are handled on the main thread after collection, per the dispatch brief —
this agent leaves the results + README for collection and does not self-certify.
