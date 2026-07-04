# K1621 — EM sovereign-credit volatility as a cross-asset uncertainty forestaller?

**Verdict: NULL** (with a suggestive, statistically *insignificant* regime nuance)

## Research question

Do EM USD-sovereign-bond ETF realized volatility (EMB / PCY / VWOB) and EM
credit-spread changes (ICE BofA EM HY Corporate OAS) **lead** — and help forecast
— the realized volatility of EM equity ETFs (EEM, EWZ 巴西, EWY 南韓, EWT 台灣,
INDA 印度), with a VIX-regime interaction?

**Motivation.** Sovereign-credit uncertainty is documented as a macro-uncertainty
indicator (Macroeconomic Dynamics 2025, "Sovereign CDS volatility as an indicator
of economic uncertainty"; IMF GFSR Apr-2026 Ch.1 on EM spreads vs UST; NBER
w13658 on a common sovereign-credit factor). If EM sovereign-credit *volatility*
prices stress earlier than EM equities, its free ETF/spread proxies could act as a
cross-asset forewarning signal. This axis has **zero prior coverage** in the
project backlog and is orthogonal to K1336 (EM FX carry, carry-vol gate),
tariff-USD wedge, and private-credit (K1343/K1344).

## Proxy disclaimer (important)

This experiment uses **only free ETF and public FRED-spread proxies** and treats
every series as a **diagnostic proxy for sovereign-credit uncertainty**. It does
**not** use raw sovereign-CDS quotes and does **not** replicate deal-level or
single-country CDS data. EMB/PCY/VWOB are USD EM-sovereign *bond funds* whose
realized vol mixes EM credit risk with US-duration risk; the ICE BofA series is an
EM *HY-corporate* OAS, an imperfect stand-in for pure sovereign spread.

## Data

| Group | Series | Source | Span used | n |
|---|---|---|---|---|
| EM USD sovereign bond ETFs | EMB, PCY, VWOB | yfinance (auto-adj close) | 2015-01-05 → 2026-07-02 | 2,889 |
| EM equity ETFs | EEM, EWZ, EWY, EWT, INDA | yfinance | same | 2,889 |
| Vol regime | ^VIX | yfinance | same | 2,892 |
| EM spread | `BAMLEMHBHYCRPIOAS` (ICE BofA HY EM Corp OAS, %) | FRED official API | **2023-07-04 → 2026-07-02** | 787 |

Annualized daily-return vol over the sample: EMB 9.6%, PCY 12.4%, VWOB 9.0%
(bonds); EEM 21.0%, EWT 21.9%, INDA 21.4%, EWY 27.7%, EWZ 35.1% (equities).

**Data-availability limitation (honest).** After a 2024 ICE licensing change, FRED
ICE-BofA OAS series retain only a rolling ~3-year window. The intended
`BAMLEMHBHYCRPIUSOAS` from the brief does not exist on FRED (HTTP 400); the valid
EM HY corporate OAS `BAMLEMHBHYCRPIOAS` starts only 2023-07-04. Consequently:

* **PRIMARY forecasting test** uses the EMB **realized-vol** credit proxy
  (full 2015+ sample) and drives the verdict.
* The **EM-OAS spread-change** feature is a **secondary, short-sample (2023-07+)
  robustness check** + descriptive lead-lag, explicitly flagged as underpowered.

Missing-value handling: log returns; OAS forward-filled to trading days for the
5-day change; any row with a NaN feature/target dropped (`dropna`). No imputation
of prices, no fabricated values.

## Method (Phase-1 diagnostic — no GARCH MLE, no large bootstrap)

1. **RV proxy.** Daily variance proxy `rv_d = r²` (log-return squared). HAR
   components: daily `rv_d`, weekly `mean(rv_d, 5)`, monthly `mean(rv_d, 22)`.
   Target = **5-day forward realized variance** `mean(rv_d[t+1..t+5])`.
2. **Lead-lag CCF.** `corr(EMB-RV(t), equity-RV(t+k))` and
   `corr(OAS-change(t), equity-RV(t+k))` for k ∈ [−5, +5] on de-noised 5-day
   annualized realized vol. `k>0` ⇒ EMB/OAS leads equity.
3. **Forecasting (log-HAR, Corsi 2009).** Per equity ETF, baseline log-HAR (own
   lagged RV) vs augmented log-HAR + EMB-RV (and, short sample, + OAS-change).
   Expanding-window OOS, monthly refit. Variance forecast =
   `exp(ŷ + ½·resid_var)` (lognormal bias correction ⇒ strictly positive, stable).
   Loss = **QLIKE** in the canonical `actual/predicted − log(actual/predicted) − 1`
   direction (via `volpred.stats.model_evaluation.qlike_pointwise`).
4. **Cluster-robust pooling (K1355).** PRIMARY pooled claim aggregates the
   cross-asset loss differential **by date first**, then runs **DM-HLN (h=5)** on
   the date series. Stacked asset-day DM is reported **only as a diagnostic**
   (understates SE).
5. **VIX-regime conditional.** Low vs high VIX (median split and the 20 cut).
6. Fixed `seed=42`.

**Lookahead controls.** Predictors sit at forecast origin `t`; target uses
`[t+1, t+5]`. Expanding refit enforces `target_end < forecast_origin` — a training
row `j` is admissible for a fit used at origin `i` only if `j + H < i`. DM-HLN
horizon = H = 5 (single horizon). See `self_review.md`.

## Results

### 1. Lead-lag CCF — contemporaneous co-movement, **no lead**

EMB realized vol and EM-equity realized vol are strongly **contemporaneously**
correlated, and the cross-correlation **peaks at lag 0** for every equity ETF,
with `lag +1` (EMB leads) ≈ `lag −1` (equity leads) — i.e. symmetric, no lead.

| Equity | corr lag 0 | lag +1 (EMB leads) | lag −1 | peak lag |
|---|---|---|---|---|
| EEM | 0.653 | 0.623 | 0.631 | **0** |
| EWZ | 0.651 | 0.621 | 0.637 | **0** |
| EWY | 0.512 | 0.498 | 0.493 | **0** |
| EWT | 0.542 | 0.525 | 0.518 | **0** |
| INDA | 0.641 | 0.640 | 0.614 | **0** |

Interpretation: EM sovereign-bond vol and EM equity vol move together as a
**common global-risk factor**, not as a lead/lag chain at daily frequency.

### 2. Forecasting — no significant gain (PRIMARY, full sample 2015+)

Per equity ETF, QLIKE gain% = (baseline − augmented)/baseline; DM-HLN (h=5),
positive t ⇒ EMB-RV feature helps. OOS n = 2,332 each.

| Equity | QLIKE gain % | DM-HLN t | p |
|---|---|---|---|
| EEM | −0.90 | −0.96 | 0.34 |
| EWZ | +1.89 | +0.73 | 0.47 |
| EWY | −1.92 | −1.48 | 0.14 |
| EWT | −1.19 | −0.73 | 0.46 |
| INDA | +6.07 | +0.90 | 0.37 |

**Pooled cluster-robust (PRIMARY, date-aggregated, K1355):** gain **+1.02%**,
**DM-HLN t = 0.41, p = 0.68** — not significant (Harvey |t|>3.0 required).
Stacked asset-day diagnostic: t = 0.60, p = 0.55 (also null; SE understated).

### 3. VIX-regime split — suggestive sign flip, **not** Harvey-significant

| Regime | n dates | QLIKE gain % | DM-HLN t | p |
|---|---|---|---|---|
| low VIX (< median) | 1,165 | −1.78 | −2.46 | 0.014 |
| high VIX (≥ median) | 1,167 | +3.33 | +0.75 | 0.46 |
| VIX < 20 | 1,555 | −2.33 | −2.96 | 0.003 |
| VIX ≥ 20 | 777 | +5.93 | +1.00 | 0.32 |

The EMB-RV feature's contribution **flips sign by regime**: in calm markets it
marginally **hurts** (VIX<20: −2.33%, t=−2.96, borderline vs Harvey |t|>3), while
in stress it is **positive but statistically insignificant** (VIX≥20: +5.9%,
t=1.0). This is consistent with "EM credit vol carries information only in stress"
but the high-VIX sample is too small to confirm it — reported as a hypothesis for
future work, **not** a claim.

### 4. Secondary OAS short-sample (2024-07 → 2026-05, underpowered)

Adding the EM-HY-OAS 5-day change to the augmented model over the short OAS window
**hurts** forecasts: pooled gain **−17.2%**, DM-HLN t = −1.66, p = 0.10; all five
assets negative. Given the ~460-day OOS window this cannot support any claim
either way, but it gives **no support** for OAS-change as a forecasting feature.

## Conclusion

**NULL.** Free EM sovereign-credit volatility proxies (EMB realized vol; EM HY
OAS change) do **not** robustly lead, nor materially improve daily forecasts of,
EM equity realized volatility over 2015–2026:

* CCF peaks at lag 0 (contemporaneous co-movement, no lead).
* Pooled cluster-robust DM-HLN gain +1.0% is statistically indistinguishable from
  zero (t=0.41).
* No individual equity ETF shows a Harvey-significant gain.
* The only structured pattern — a regime-dependent sign flip (hurts in calm, helps
  in stress) — is not Harvey-significant and rests on a small high-VIX subsample.

Economically, EM sovereign-bond vol behaves as a **contemporaneous common-factor
proxy** for EM risk rather than a **forewarning** indicator at daily frequency.
This is a clean, honest null consistent with EM assets sharing a global risk
factor; it does not contradict the "sovereign-CDS vol = uncertainty indicator"
literature (which is contemporaneous/monthly), but it does **not** extend that to
a daily cross-asset *lead*.

## Limitations

1. **Proxies, not CDS.** EMB/PCY/VWOB mix credit + US-duration risk; ICE BofA OAS
   is HY-corporate, not pure sovereign. A true sovereign-CDS-vol test needs raw CDS
   (paid data) and is out of scope.
2. **FRED OAS is only 3 years** (2024 ICE license change) ⇒ the spread-change test
   is short-sample and underpowered; treat as descriptive only.
3. **Daily frequency & r² proxy.** r² is a noisy variance proxy; a monthly or
   intraday-RV design (or aggregating CDS-vol at lower frequency) might reveal a
   lead that daily r² cannot detect.
4. **Phase-1 diagnostic:** no GARCH/EGARCH MLE, no MCS, no bootstrap CIs; the
   regime hypothesis warrants a powered follow-up (e.g. threshold-HAR or interacted
   feature with more high-VIX data).
5. **EMB tail data gap (disclosed post-review).** The primary OOS window ends
   `2026-05-15`, not `2026-07-02`, because the augmented model's `EMB rv_d.rolling(5)`
   feature has a ~33-trading-day NaN tail (yfinance bond-ETF availability quirk),
   which `dropna` silently trims from the `base ∩ aug` intersection. This reduces
   the OOS n but does **not** bias the sign of the null (fewer, not distorted,
   observations).
6. **OAS as-of dating (secondary test only).** The EM-HY-OAS series is
   forward-filled on its FRED as-of date; ICE BofA OAS can publish with a T+1 lag,
   a possible minor look-ahead confined to the **secondary, already-underpowered**
   OAS test. Because that secondary result is already negative (−17.2%, NS), any
   such leak would only flatter it — it cannot rescue the null.

## References (trend/concept-level)

1. *Sovereign CDS volatility as an indicator of economic uncertainty*,
   **Macroeconomic Dynamics** (2025). — concept-level: sovereign-credit vol proxies
   macro uncertainty (contemporaneous framing).
2. **IMF Global Financial Stability Report**, Apr-2026, Ch.1 — EM sovereign spreads
   vs US Treasuries; EM-vs-DM risk transmission (motivational).
3. Pan, J. & Singleton, K. (NBER w13658 / JF 2008) — a common latent factor drives
   sovereign credit spreads across countries (supports the "common factor, not
   lead" interpretation).
4. Corsi, F. (2009), *A simple approximate long-memory model of realized
   volatility*, **J. Financial Econometrics** — HAR specification used here.
5. Patton, A. (2011), *Volatility forecast comparison using imperfect volatility
   proxies*, **J. Econometrics** — QLIKE proxy-robustness.
6. Harvey, D., Leybourne, S. & Newbold, P. (1997), *Testing the equality of
   prediction mean squared errors*, **IJF** — DM small-sample (HLN) correction.

## Files

* `k1621.py` — reproducible script (seed=42, explicit lags, inline data fetch).
* `k1621_results.json` — all numbers (descriptives, CCF, per-asset & pooled
  DM-HLN, regime split, secondary OAS).
* `plots/correlation_heatmap.png` — contemporaneous log-RV correlation matrix.
* `plots/leadlag_ccf.png` — EMB-RV → equity-RV cross-correlation, lags −5..+5.
* `plots/regime_forecast_gain.png` — per-asset QLIKE gain + VIX-regime annotation.
* `self_review.md` — self-audit (lookahead / seed / QLIKE direction / K1355).

**Reproduce:** `uv run python experiments/k1621/k1621.py` (needs `FRED_API_KEY` in
`.env.local`; without it, ETF-only analysis still runs).
