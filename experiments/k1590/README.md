# K1590 — Merger Arbitrage Deal-Spread Vol (Diagnostic Phase)

**Status**: Diagnostic complete. **Verdict: GO** (Codex review:
**CONDITIONAL_PASS**, with caveats — see §6).
**Run**: 2026-07-01 00:28 Asia/Taipei. Price request window
2020-01-01 .. 2026-07-01; MNA return sample N=1,629 trading days.
**Code**: `experiments/k1590/k1590_diagnostic.py` (reproducible, seed=42).

---

## 1. Motivation

Merger arbitrage spread vol is the canonical vol-regime variable for risk-arb funds:
when antitrust enforcement tightens or financing conditions deteriorate, the
post-announcement spread between target price and offer price widens and
becomes volatile, reflecting elevated deal-break probability (Mitchell & Pulvino
2001 JoF; Baker & Savaşoglu 2002 JFE). Individual deal-spread micro data sits
behind expensive feeds (Bloomberg M&A, Refinitiv); we test whether a free
portfolio-level proxy — the **IQ Merger Arbitrage ETF (MNA)** — carries enough
deal-spread vol signal to support a research line for VolPred.

The hypothesis: high-VIX / antitrust-stressed regimes → deal-break risk ↑ →
MNA realized vol rises **disproportionately** versus a passive equity (SPY) or
credit (HYG) proxy. If true, MNA is a usable portfolio-level vol target. If
MNA is just a low-beta SPY clone, the proxy fails and a Phase-2 experiment
would need individual deal data.

This serves Mission #2 (rigorous research) and #1 (reader-facing article
follow-up if PASS).

## 2. Data

| Ticker | Field | Period | Source |
|---|---|---|---|
| MNA | Adj Close | 2020-01-02 .. 2026-06-30 | yfinance, `auto_adjust=False` |
| SPY | Adj Close | same | yfinance |
| IWM | Adj Close | same | yfinance |
| HYG | Adj Close | same | yfinance |
| ^VIX | Close | same | yfinance |

1,629 trading-day intersection. `auto_adjust=False` is explicit per `docs/error_log.md`
2026-04-13 lesson — silent adjusted-vs-raw swap pollutes downstream stats.

## 3. Methods

1. Daily log returns r_t = log(P_t / P_{t-1}) for MNA / SPY / IWM / HYG / VIX.
2. Excess relative returns: (MNA − SPY), (MNA − HYG).
3. Descriptive stats (mean, std, skew, excess kurt) full sample + VIX-regime split.
4. VIX regime classification (same-day VIX level): low <20, mid 20-30, high >30.
5. Pearson + Spearman correlations across MNA / SPY / IWM / HYG / VIX-return / VIX-level.
6. Rolling 21-day MNA annualized realized vol time series (plot vs VIX).
7. **Vol regime test**: Welch two-sample t-test on |MNA daily log return|
   between high-VIX (>30) and low-VIX (<20) days.
   - Same-day classification is primary (descriptive symmetry).
   - **Robustness**: t-1 VIX classification → day-t |MNA| (forward-safe form,
     no lookahead even if read as inference).
8. Verdict gate: GO requires (a) p < 0.05 (b) magnitude ratio high/low ≥ 1.5
   (c) Pearson(MNA, SPY) < 0.9 (not a clone).

**Seed**: `np.random.seed(42)` set globally (no resampling used here; placeholder
for Phase 2).

**Lag policy**: this is a diagnostic — no signal → forecast mapping. Vol regime
test reports both same-day and t-1 lagged classifications transparently. No
lookahead claim is made; no model is trained.

## 4. Key Results

### 4.1 Full-sample MNA characteristics
| stat | value |
|---|---|
| N | 1,629 |
| mean daily log ret | 7.8e-05 (~2.0% annualized) |
| std daily | 0.473% (~7.5% annualized) |
| skew | **−2.89** |
| excess kurtosis | **66.4** |
| min | −7.69% |
| max | +5.04% |

The skew/kurt profile is **extreme** for an equity ETF — strongly left-tailed
and fat-tailed. SPY in the same sample has skew ~−0.6 and excess kurt ~13.6.
This is consistent with the merger-arb payoff structure: long stream of small
positive carry punctuated by deal-break crashes — **not a SPY characteristic**.
First piece of evidence MNA is structurally distinct.

### 4.2 Correlations (Pearson)

| | SPY | IWM | HYG | VIX return | VIX level |
|---|---|---|---|---|---|
| MNA | **0.517** | 0.537 | **0.487** | **−0.317** | −0.103 |

MNA's SPY correlation 0.52 is far from a clone (cond_c PASS). VIX-return
correlation −0.32 is meaningful (VIX up days hurt MNA). HYG correlation 0.49
shows shared credit-risk loading, important because deal financing risk is
a credit phenomenon — supportive of the deal-spread interpretation.

### 4.3 VIX-regime split

Day counts: low (VIX<20) = 924, mid (20-30) = 556, high (>30) = 149.

|stat | low VIX | high VIX |
|---|---|---|
| n | 924 | 149 |
| mean \|MNA\| × 10⁴ | 21.01 | 64.09 |
| mean abs return | 0.00210 | 0.00641 |

(Full per-regime mean/std/skew/kurt in `k1590_diagnostic_results.json` →
`vix_regime_stats`.)

### 4.4 Vol-regime breakpoint test (primary)

Welch two-sample t-test on |MNA daily log return|, classification by same-day VIX level:

| | low VIX (<20) | high VIX (>30) |
|---|---|---|
| n | 924 | 149 |
| mean abs ret | 0.00210 | 0.00641 |
| std abs ret | 0.00190 | 0.01022 |

**t = 5.13, p = 8.79 × 10⁻⁷, magnitude ratio (high/low) = 3.05.**

Robustness (lagged t-1 VIX classification): t = 4.77, p = 4.33 × 10⁻⁶. Effect
survives forward-safe formulation.

### 4.5 Plots
- `plots/rolling_vol_vs_vix.png` — MNA 21-day annualized RV vs VIX level.
- `plots/regime_split_box.png` — MNA daily log return distribution by VIX regime.

## 5. Verdict: **GO**

| Cond | Threshold | Observed | Pass? |
|---|---|---|---|
| (a) p < 0.05 | 0.05 | 8.79e-07 | ✓ |
| (b) magnitude ratio ≥ 1.5 | 1.5× | 3.05× | ✓ |
| (c) Pearson(MNA, SPY) < 0.9 | 0.9 | 0.517 | ✓ |

All three pass. MNA is **not a SPY clone**, carries a clear high-VIX vol
amplification (3× absolute return in stress regime), and the regime split
survives the t-1 lagged robustness check. The extreme skew/kurt profile
(skew −2.89, excess kurt 66) further differentiates MNA payoff from passive
equity.

## 6. Limitations & Honest Caveats

1. **Proxy ceiling**: MNA aggregates many deals; idiosyncratic deal-break
   shocks average out. Individual deal-spread vol could be far larger and
   more antitrust-sensitive than MNA shows. Conclusions here apply to
   portfolio-level vol, not per-deal vol.
2. **Mechanical regime amplification**: "high-VIX days have larger |returns|"
   is a near-universal property of risk-on assets. The GO verdict is gated
   on the **non-clone** condition (Pearson 0.52, skew −2.89, kurt 66) — those
   are the structurally informative observations, not the t-test alone.
3. **Sample period**: 2020-2026 spans COVID, 2022 rate hikes, Lina Khan
   antitrust era. Result may not generalize to pre-2020 / lower-VIX regimes.
4. **VIX cutoffs {20, 30}**: conventional but unoptimized. Sensitivity to
   alternative breakpoints not tested in diagnostic.
5. **No event study**: FTC second-request / DOJ filings would be the
   sharpest antitrust signal — deferred to Phase 2 (data engineering
   required: parse SEC EDGAR DEF14A and FTC HSR filings).
6. **No GARCH / HAR-RV / forecasting**: this is descriptive only. Phase 2
   needs MLE-based vol modeling + OOS DM tests before any prediction claim.
7. **Codex review completed 2026-07-01** with CONDITIONAL_PASS. The
   diagnostic GO is acceptable as a Phase-2 gate, but not as a prediction,
   causal antitrust, or trading claim.

## 7. Suggested Phase-2 Roadmap (if approved)

- **Phase 2a — data layer**: pull individual deal-spread series via SEC
  EDGAR DEF14A + cash-merger target price. Align deal-window
  announcement-to-close.
- **Phase 2b — vol modeling**: GJR-GARCH on MNA daily returns with VIX
  exogenous regressor (Glosten-Jagannathan-Runkle 1993). HAR-RV on
  intraday MNA tick data if vendor allows.
- **Phase 2c — event study**: FTC second-request / DOJ filing windows →
  cross-sectional MNA spread-vol pulse.
- **Phase 2d — regime switching**: Markov 2-state on MNA |ret|, identify
  "antitrust-stress" state. Test against Khan-era 2021-2024 indicator.
- **Phase 2e — forecast OOS**: 252-day OOS forecast of MNA RV with VIX
  exogenous; DM test vs HAR-RV baseline; Patton QLIKE.

## 8. References

- Mitchell, M., & Pulvino, T. (2001). Characteristics of Risk and Return in Risk
  Arbitrage. *Journal of Finance*, 56(6), 2135-2175.
- Baker, M., & Savaşoglu, S. (2002). Limited arbitrage in equity markets.
  *Journal of Financial Economics*, 64(1), 91-115.
- Glosten, L. R., Jagannathan, R., & Runkle, D. E. (1993). On the relation
  between the expected value and the volatility of the nominal excess return
  on stocks. *Journal of Finance*, 48(5), 1779-1801.
- Patton, A. J. (2011). Volatility forecast comparison using imperfect
  volatility proxies. *Journal of Econometrics*, 160(1), 246-256.

## 9. Files

- `k1590_diagnostic.py` — reproducible end-to-end script
- `k1590_diagnostic_results.json` — full numerical results + verdict
- `plots/rolling_vol_vs_vix.png` — 21d RV vs VIX time series
- `plots/regime_split_box.png` — VIX-regime distribution boxplot
- `README.md` — this file
- `codex_review.md` — Codex review receipt and caveats
