# K1642 — Volatility Laundering in listed BDCs: reported NAV vol vs de-smoothed "true" vol

**Mode:** `empirical_layer1` (real reported NAV, not a mechanical illustration)
**Verdict:** `CONDITIONAL_PASS` — H1 (the laundering gap) confirmed strongly and unanimously; H3-basic (NAV positive AR(1)) confirmed but the *appraisal-specific* differential is not established (market returns also show positive AR(1) in this short window); H2 (strong form) rejected. The core, robust claim is H1.

## Motivation

Private-credit / direct-lending vehicles report **appraisal-based, quarterly, smoothed NAV** returns. The econometrics literature (Getmansky–Lo–Makarov 2004) and practitioner commentary (Asness 2023, "volatility laundering"; FSB 2026 private-credit warning) argue this systematically **understates true volatility and tail risk**. The mechanism is well understood in theory but rarely measured on the private-credit asset class itself, because non-traded vehicles have no observable market price.

**Listed BDCs solve this**: each one publishes *two* observable return series for the *same* underlying loan book —

- **market price** (daily, mark-to-market) → economic-vol proxy
- **reported NAV / share** (quarterly, appraisal-smoothed) → the "laundered" reported vol

so we can quantify the laundering gap with 100% free, public, structured data.

### Difference from K1343 / K1332 / K1344

K1343 (and the K1332/K1344 line) asked whether **BDC price *pressure* forecasts future volatility** in HYG/KRE/IWM — a *signal / causality* question (verdict NULL). K1642 is a completely different, **measurement** question: *how much does the reported NAV series understate the true volatility, and does that understatement carry the statistical fingerprint of appraisal smoothing?* No forecasting is involved.

## Hypotheses

- **H1** — σ(reported NAV return) ≪ σ(market return): laundering ratio σ_reported/σ_market < 1.
- **H2** — after Getmansky–Lo–Makarov (GLM 2004) de-smoothing, the recovered "true" vol converges *toward* the market vol (i.e. appraisal smoothing, not lower fundamentals, drives most of the gap).
- **H3** — reported NAV quarterly returns show significant positive AR(1) — the appraisal-smoothing fingerprint — while market returns do not.

## Data (100% free, real reported NAV)

| Series | Source | Notes |
|---|---|---|
| Market price + distributions | `yfinance` `Ticker.history(auto_adjust=True)` daily close + raw `.dividends` | total-return price; dividends built into adj close |
| Reported NAV / share | **SEC EDGAR XBRL** `companyconcept` `us-gaap:NetAssetValuePerShare`, forms 10-Q / 10-K | *originally-reported* value = earliest-filed per period-end (avoids restatement look-back); `User-Agent` header required |

**Universe (7 listed BDCs, CIKs in results JSON):** `ARCC`, `BXSL`, `OBDC`, `FSK`, `PSEC`, `MAIN`, `GBDC`.
**Excluded:** `BIZD` — it is a fund-of-BDCs ETF whose NAV is struck daily (no appraisal smoothing to measure).

**Sample per BDC:** 14–19 consecutive quarterly returns. See *Data limitations* — the continuous quarterly NAV chain begins 2021Q3–Q4 because `NetAssetValuePerShare` was tagged only annually in pre-2021 10-Ks. The window spans the **2022 bear market and 2023 regional-bank stress**, so the gap is measured through a genuine drawdown.

## Method

1. **NAV total return** at quarter *i*: `(NAV_i − NAV_{i−1} + Σ per-share distributions ex-date in (t_{i−1}, t_i]) / NAV_{i−1}`. Only consecutive period-ends 75–125 days apart are kept (guards mergers / annual-only gaps).
2. **Market total return** over the same window: `adj_close(report_i) / adj_close(report_{i−1}) − 1` (last trading day ≤ each report date; requires match within 7 days).
3. **Frequency-matched vols** (both series on the *same* quarter-end grid): quarterly σ × √4 = annualized. Daily-based annualized market vol (× √252) is reported *separately* as a reference — the two conventions are never mixed into the ratio.
4. **GLM de-smoothing** (Getmansky–Lo–Makarov 2004): reported return `x_t = Σ_{j=0..k} θ_j e_{t−j}` with `Σθ_j = 1, θ_j ≥ 0`, `e_t ~ N(0, σ²_true)`. Reported variance = σ²_true·ξ where ξ = Σθ_j² (smoothing index ≤ 1); de-smoothed variance = σ²_true = Var(reported)/ξ. Fitted by an **exact Gaussian MA(k) likelihood** (banded Toeplitz covariance, Cholesky) with a **120-random-start constrained MLE** (softmax simplex reparam, seed 42). `statsmodels` ARMA is fragile on n≈14–19 quarters — this is a package limitation, not a model failure (K1213). Reported at **k=2 (primary)** and **k=1 (robustness)**, plus a **Geltner (1993) AR(1) unsmoothing** cross-check.
5. **H3 AR(1)**: OLS AR(1) with Newey–West HAC robust *t* + Ljung–Box, on both NAV and market quarterly returns.
6. **Cross-section inference** (avoids the K1355 asset-day iid trap): every statistic is aggregated to **one value per BDC first**, then a **Wilcoxon signed-rank** test is run across the 7 BDCs. Asset-quarters are never stacked as iid.
7. **Seed 42** for all bootstrap and random MLE starts. This is a measurement study, so no predictive `signal.shift(1)` applies; the only lead/lag alignment (daily price → quarter-end NAV date) is documented in `_price_asof`.

## Results

### H1 — laundering gap: **CONFIRMED**

*(span = calendar coverage of the return series, first window start → last window end; n_q = number of quarterly returns)*

| BDC | n_q | span | σ reported (ann) | σ market (ann, q-basis) | laundering ratio |
|---|---:|---|---:|---:|---:|
| ARCC | 18 | 2021-09 … 2026-03 | 2.28% | 11.97% | 0.191 |
| BXSL | 17 | 2021-12 … 2026-03 | 1.78% | 18.95% | 0.094 |
| OBDC | 18 | 2021-09 … 2026-03 | 2.69% | 16.97% | 0.159 |
| FSK  | 14 | 2022-09 … 2026-03 | 6.18% | 24.46% | 0.253 |
| PSEC | 19 | 2021-06 … 2026-03 | 7.22% | 17.97% | 0.401 |
| MAIN | 18 | 2021-09 … 2026-03 | 2.80% | 17.10% | 0.164 |
| GBDC | 18 | 2021-09 … 2026-03 | 2.73% | 12.47% | 0.219 |

Cross-section: **median laundering ratio 0.191** (mean 0.212, range 0.094–0.401). Wilcoxon signed-rank vs 1: **p = 0.0156** (the minimum attainable p for n=7 — every BDC is below 1). Reported NAV vol is roughly **one-fifth** of market vol.

### H2 — does de-smoothing explain the gap? **Strong form REJECTED (only directional)**

| Method | de-smoothed / market (median) | gap closed (median) |
|---|---:|---:|
| Reported (no de-smoothing) | 0.191 | 0% |
| GLM k=2 (primary) | 0.300 | **7%** |
| GLM k=1 (robustness) | 0.246 | ~4% |
| Geltner AR(1) (ex BXSL) | 0.370 | 19% |

De-smoothing inflates NAV vol (1.4–1.8× via GLM) but the de-smoothed vol is **still significantly below market** (Wilcoxon de-smoothed vs 1: p = 0.0156). Under *any* of three unsmoothing methods, only a **small fraction** of the market–NAV gap is recovered. **Interpretation:** appraisal return-smoothing (the MA autocorrelation that GLM corrects) is a *real but minor* contributor; the bulk of the gap reflects that **market price embeds premium/discount, equity-beta, and liquidity volatility absent from the fundamental NAV**. This does *not* weaken the laundering finding — it sharpens it: naive de-smoothing does **not** rescue the reported vol back to market levels.

### H3 — appraisal AR(1) fingerprint: **BASIC confirmed, appraisal-specific NOT established**

- Median NAV AR(1) φ = **0.390** (range 0.011–1.052). Wilcoxon φ_NAV vs 0: **p = 0.0156** (all 7 positive) → NAV returns *do* carry positive serial correlation (H3-basic **CONFIRMED**).
- **But market quarterly returns are ALSO positively autocorrelated in all 7 BDCs** (median φ = 0.202, Wilcoxon vs 0 p = 0.0156). So "NAV has positive AR(1)" alone does not isolate appraisal smoothing over this window.
- The appraisal-*specific* test — NAV φ **>** market φ — is only p = **0.078** (paired Wilcoxon, n=7): directional but **not significant** at 5%. So the differential fingerprint is **not established** here. (Caveat: Codex review flagged this; language downgraded accordingly.)
- Ljung–Box significant at 5% in only 1/7 (small-sample power).
- **BXSL φ = 1.052 > 1** is a small-sample explosive artifact (17 quarters, newer very-smooth fund); flagged `ar1_nav_reliable=false`, `geltner_ar1.valid=false`, excluded from the Geltner cross-section. GLM's bounded simplex is robust there.

## Interpretation

Listed BDCs let us *directly and freely* quantify volatility laundering in private credit. Over 2021–2026, **reported appraisal-based NAV volatility is ~1/5 of the same fund's mark-to-market volatility** (median ratio 0.19, significant across all 7 BDCs) — this is the robust headline. Reported NAV returns are positively autocorrelated (median AR(1) 0.39), consistent with appraisal smoothing, but market quarterly returns are *also* positively autocorrelated over this short window, so the AR(1) evidence does not by itself cleanly isolate an appraisal-specific fingerprint (NAV φ > market φ only p = 0.078). Separately, **mechanically un-smoothing the NAV closes only a small part of the gap** — most of the market–NAV vol difference is not statistical return-smoothing but the economic difference between mark-to-market and mark-to-model. The honest framing is a *bracket*: reported NAV vol is a **lower bound** on true risk, market price vol an **upper bound** (it over-counts discount-rate/sentiment noise), and the true private-credit portfolio vol sits between the de-smoothed NAV vol and the market vol.

## Caveats / Data limitations

- **Short, stress-dominated window.** The continuous quarterly NAV chain begins 2021Q3–Q4 (14–19 quarters) because SEC XBRL `us-gaap:NetAssetValuePerShare` was tagged only annually pre-2021. The sample is dominated by 2022–2023 stress where mark-to-market vs appraisal divergence is largest, so the 0.19 ratio may **overstate a full-cycle average**.
- **Market vol is an upper bound**, not "true" vol (premium/discount + beta + liquidity noise).
- **Share issuance/buybacks at premium/discount** to NAV cause accretion/dilution in NAV/share — a second-order contaminant not separated here.
- **n ≈ 14–19 quarters** limits per-BDC power; the cross-section Wilcoxon (n=7) is the primary inference and is robust because the effect is unanimous.
- Not a claim about any single fund's loan marks; it is a cross-BDC measurement of the appraisal-vs-market vol wedge.

## References

1. **Getmansky, M., Lo, A. W., & Makarov, I. (2004).** An econometric model of serial correlation and illiquidity in hedge fund returns. *Journal of Financial Economics, 74*(3), 529–609. (GLM smoothing-profile de-smoothing.)
2. **Asness, C. (2023).** Why does illiquidity make investments less risky? ("Volatility Laundering.") *AQR Capital Management.* (Coins the "volatility laundering" framing for appraisal-based reporting.)
3. **Geltner, D. (1993).** Estimating market values from appraised values without assuming an efficient market. *Journal of Real Estate Research, 8*(3), 325–345. (First-order AR(1) unsmoothing of appraisal returns.)
4. **Financial Stability Board (2026-05-06).** FSB warns on private-credit vulnerabilities: transparency, valuation, leverage, liquidity. https://www.fsb.org/2026/05/fsb-warns-on-private-credit-vulnerabilities/

## Reviewer

Codex `codex exec` code review — see final section / commit message. Bar: CONDITIONAL PASS or above on data alignment, frequency confounding, GLM implementation, and provenance.

## Artifacts

- `k1642.py` — reproducible script (SEC + yfinance fetch with local cache in `data/`, all tests, seed 42).
- `k1642_results.json` — all numbers, per-BDC + cross-section, `mode`, `verdict`, `data_limitations`.
- `data/` — cached NAV / price / dividend CSVs (re-run reads cache; delete to re-fetch).
- `fig_laundering_ratio.png` — reported vs de-smoothed vs market annualized vol per BDC.
- `fig_desmoothing.png` — GLM smoothing index ξ per BDC + gap closure (reported vs de-smoothed ratio to market).
