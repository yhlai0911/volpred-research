# Completed Session 2026-04-03~04: 25 Experiments + TAIFEX Paradigm Shift

## Session Summary
- **Experiments**: 25 (K825-K849 + K823v2)
- **Articles**: 37
- **Git commits**: 43
- **Experience records**: E42-E46

## Landmark Findings (★★★)
- **K849**: HAR-RV crushes GJR on 5-min RV target (DM t=-11.14) — proxy ceiling not model ceiling
- **K847**: Overnight gap 61% tradable via TX night session (R²=0.83)
- **K848**: r² captures only 29% of true vol; night vol share 24%→57% (2017→2026)
- **K844**: TX futures VT beats stock VT in every bear market; night=73.7% of return
- **K846**: 50/50 triple moat (diversification + rebalancing premium 54bps/yr + gold crisis alpha)
- **K836**: Cornish-Fisher fixes 0050.TW 1% VaR (only Trinity PASS)
- **K833**: VRP consistently positive 78-83% of weeks
- **K827**: ABM VT crowding tipping point at 30-50%

## Completed Experiments Detail

### VaR Series (K825, K829, K830, K836, K837)
- K825: Conformal VaR — HistSim/Student-t best, C2 Proxy-Robust Trinity PASS but 2x wider
- K829: Cross-Asset VaR — HistSim 75% pass rate best. GLD all PASS, QQQ only HistSim, 0050.TW all FAIL, BTC paradox
- K830: BTC Skewed-t NULL — positive skew vanishes in GJR residuals (0.619→-0.19). Problem is GARCH variance over-prediction
- K836: 0050.TW EVT VaR — Cornish-Fisher 3/481 Trinity PASS! Pure EVT-POT fails. CF uses skew+kurtosis directly
- K837: BTC Regime VaR NULL — 87-92% of 2023-2024 is low-vol, regime switching degenerates to Normal

### Model Comparison (K826, K814v2, K839)
- K826: KAN-GARCH-MIDAS NULL — ML ceiling #7. GJR QLIKE -8.680 beats KAN -8.582 (DM t=-3.16)
- K814v2: Bayesian MCMC fix — 3 bugs fixed. P(γ>0)=1.000 genuine (not prior artifact). MLE wins QLIKE (DM t=4.23)
- K839: Hierarchical Bayesian NULL — gamma SE -50% but QLIKE unchanged. GLD has negative gamma

### Strategy (K811v2, K828, K833, K840, K846)
- K811v2: Insurance Premium fix — VoV conditioning reduces cost 74% (4.62%→1.22%/yr). But Cross-OOS 1/4
- K828: VIX-Only Conditioning NULL — VIX sufficiency #33. 12/VIX already optimal
- K833: CBOE IV Straddle POSITIVE — VRP 78-83% positive weeks. Proxy Sharpe 1.8-3.7 (real likely halved)
- K840: Return Prediction NULL — 55.6% hit rate ≠ profit. EMH confirmed for SPY daily
- K846: Rebalancing Premium — theoretical 81.5 bps/yr, empirical 53.7 bps/yr. Explains 50/50 dominance

### Connectedness & ABM (K834, K827)
- K834: IV Connectedness NULL — TCI partial r=-0.003 after controlling VIX. VIX sufficiency #34
- K827: ABM VT Crowding — tipping point 30-50%. <5% safe. Negative Sharpe above 70%

### Congressional Trading (K823v2)
- K823v2: Real data (15,674 House trades). Disclosure-day alpha = 0 (t=0.245). Oracle t=2.51 (fails Harvey). Large trades >$50K only exception (t=3.94, n=353)

### TAIFEX Futures Series (K838-K845, K847-K849)
- K838: Night momentum NULL — same-instrument price-in (r=-0.08)
- K841: Futures VT hedge NULL — VIX is T-2, timing gap fatal
- K842: Futures profit trading NULL — SPY signal priced in too fast
- K843: Intraday futures — BH night session Sharpe 0.788 (9/10yr positive). Night IS the alpha
- K844: TX VT vs 0050 VT — TX Sharpe 1.465 vs 0050 1.370. Bear market: TX wins 3/3. TX cost 97% lower
- K845: TX VT listing eval — FAIL Test 1 (Sharpe 1.76 < median 2.28). Not listed separately
- K847: Overnight gap decomposition — 61% tradable (Slot B 16.2% + C 39.8% + D 5.3%). R²=0.83
- K848: 5-min RV from ticks — r² captures 29% median. GJR 5.8x better on RV target. Night vol 24%→57%
- K849: HAR-RV vs GJR — HAR QLIKE 0.181 vs GJR 0.531 (DM t=-11.14). Cross-OOS 5/5. PROXY CEILING confirmed

### Taiwan VT (K835)
- K835: VIXTWN Blend NULL (74 days exploratory) — 8.63/VIX remains best. VIXTWN level r=0.91 with VIX

## Codex Suggestions
- 9th round: K833 tested (POSITIVE), K834 tested (NULL), K835 tested (NULL), K831/K832 blocked (5-min data)

## Derived Directions (written to research_program.md)
- SPY HAR-RV (needs yfinance 5-min, ~04/07-08)
- HAR-RV-Night component analysis
- HAR-RV based VaR for Taiwan
- Realized GARCH (Hansen, Huang & Shek 2012)
- Paper 2 update with K844/K847/K849
- Jump dynamics (74.9% days have jumps)
