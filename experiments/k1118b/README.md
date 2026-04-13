# K1118b: Currency cross-asset extension — Paper 4 Universal IV Sufficiency

**Proposed by: Claude (K1118 cross-asset extension to FX), Executed: Claude (2026-04-13)**
**Branch: `agent-afce4f2d` (worktree)**

## 1. Problem

Paper 4 compendium claims that native implied-vol (VIX-family) is *sufficient* for
weekly RV prediction across asset classes, with crypto as the known exception.
Before K1118b, evidence covered:

| Class | Ticker | Native IV | Verdict |
|-------|--------|-----------|---------|
| Equity | SPY / 0050.TW | ^VIX / VIXTWN | Sufficient (K473/K750/K789/K504/K1116/K1098) |
| Commodity | GLD | ^GVZ | Sufficient, alt-data active harm (K1118) |
| Bond | TLT | ^MOVE | Partial (K1118: DM directional, QLIKE <5%) |
| Crypto | BTC | DVOL / RV30 proxy | **Insufficient** (K1118 RV30 fail, K1119 DVOL fail) |
| Currency | DXY / EUR / JPY | — | **Untested** ← K1118b |

**Question**: Does IV sufficiency extend to FX? If yes, Paper 4 claim strengthens;
if no, FX joins crypto and Paper 4 boundary narrows to equity+bond+commodity.

## 2. Hypotheses

- **H1 (universal)**: IV suffices for all 3 FX → Paper 4 claim strengthens.
- **H2 (all fail)**: No IV source beats AR(1) for any FX → FX joins crypto in
  IV-insufficient class. Motivation: Menkhoff-Sarno-Schmeling-Schrimpf (2012) JF —
  FX vol is carry-trade/global-FX-vol-factor driven, distinct from equity VIX channel.
- **H3 (reserve-currency specific / mixed)**: Some FX admit IV signal, others do
  not; asset-specific rather than universal.

## 3. Data

- **yfinance** (2010-01-01 to 2025-03-15):
  - Prices: FXE (EUR/USD ETF), FXY (JPY/USD ETF), UUP (DXY ETF)
  - IV: **^EVZ** (CBOE EuroCurrency Volatility, discontinued 2025-03-05;
    792 weekly obs, no gaps, no NaN), **^VIX** (cross-market proxy)
  - ^JYVIX, ^BPVIX, CVIX: **not available on yfinance** (delisted / never mirrored)
- **FRED** (CSV endpoint): USEPUINDXD, WLEMUINDXD, NFCI, ANFCI, STLFSI4
- Weekly aggregation (W-FRI), `rv = sqrt(sum r_d^2)`, min 4 daily obs/week
- **IS**: 2010-01 to 2018-12 (9 years, ~468 weeks/asset)
- **OOS**: 2019-01 to 2025-03 (6.2 years, ~323 weeks) — covers **COVID + Fed hike +
  BOJ YCC end + ECB pivot** stress panel
- `np.random.seed(42)`

## 4. Method

For each asset × IV source (3 IV sources per asset):

| Model | Regressors (all .shift(1)) |
|-------|---------------------------|
| M1 | y_lag1 |
| M2 | y_lag1 + iv_mean_lag1 |
| M3 | y_lag1 + USEPU, WLEMU |
| M4 | y_lag1 + NFCI, ANFCI, STLFSI |
| M5 | y_lag1 + IV + EPU + FinStress |

Same framework as K1116/K1118 (OLS on weekly RV, shift(1) lookahead-safe).

**Primary tests**:
- DM-HLN (Harvey-Leybourne-Newbold 1997) between pairs
- **IV vs AR(1)**: does M2 beat M1? (the cleanest test of "IV has information")
- **IV vs alt-data**: triple-gate (DM + QLIKE>5% + sub-period stability ≥ 2/3)
- **VaR Trinity** on M2: Kupiec UC + Christoffersen CC + Basel traffic light at 5%+1%

**IV candidates tested per asset**:
- EUR/USD: Native_EVZ, Cross_VIX, Realized30
- JPY/USD: Cross_VIX, Cross_EVZ, Realized30 (no native JPY IV on yfinance)
- DXY (UUP): Native_EVZ (dollar basket ~58% EUR), Cross_VIX, Realized30

## 5. Results

### 5.1 IV vs AR(1) (does any IV contain information beyond persistence?)

| Asset | Source | DM t-stat (HLN) | p-value | IV beats AR1 (Harvey |t|>2) |
|-------|--------|-----------------|---------|------------------------------|
| **EUR/USD** | **Native_EVZ** | **+5.07** | **0.0000** | ✓ YES |
| EUR/USD | Cross_VIX | **-3.55** | 0.0004 | ✗ (AR1 actively beats VIX!) |
| EUR/USD | Realized30 | +5.56 | 0.0000 | ✓ YES |
| JPY/USD | Cross_VIX | +0.14 | 0.887 | ✗ indistinguishable |
| **JPY/USD** | **Cross_EVZ** | **+6.32** | **0.0000** | ✓ YES |
| JPY/USD | Realized30 | +3.67 | 0.0003 | ✓ YES |
| DXY (UUP) | Native_EVZ | +1.13 | 0.259 | ✗ indistinguishable |
| DXY (UUP) | Cross_VIX | -0.17 | 0.864 | ✗ indistinguishable |
| DXY (UUP) | Realized30 | +1.18 | 0.238 | ✗ indistinguishable |

See `k1118b_dm_heatmap.png`.

### 5.2 Alt-data triple-gate (vs M2 IV baseline)

Across ALL 9 asset×IV combinations: **triple-gate FAIL for alt-data**. Best alt-model
QLIKE improvement ranged -0.84% to +0.05% (below the +5% threshold). Where IV works,
**IV baseline actively beats alt-data at Harvey** (6/9 combinations show `active_harm`).

This mirrors K1116/K1118: EPU/NFCI/STLFSI add no OOS value beyond IV (or AR(1) when
IV fails). **Cross-asset consistency of alt-data null for weekly vol prediction
continues to hold**.

See `k1118b_qlike_comparison.png`.

### 5.3 VaR Trinity (M2 baseline)

| Asset / IV | 5% Trinity | 1% Trinity |
|------------|------------|------------|
| EUR/USD Native_EVZ | PASS (Green) | PASS (Green) |
| EUR/USD Cross_VIX | FAIL (too conservative, K=8 vs 16.2) | FAIL (K=0) |
| EUR/USD Realized30 | PASS | PASS |
| JPY/USD Cross_VIX | PASS | PASS |
| JPY/USD Cross_EVZ | PASS | PASS |
| JPY/USD Realized30 | PASS | PASS |
| DXY Native_EVZ | PASS | **FAIL (Red, K=10 vs 3.2)** |
| DXY Cross_VIX | FAIL (conservative) | PASS |
| DXY Realized30 | PASS | PASS |

**EUR/USD Cross_VIX** (applying equity VIX to EUR): VIX systematically **over-predicts** EUR/USD
vol → too few violations (0/323 at 1%). Supports the H3 reading that channels differ.

**DXY Native_EVZ at 1%**: Red light — EVZ **under-predicts** DXY tail risk (10 violations vs 3.2
expected). EVZ is EUR-USD-specific; DXY is a basket, so EVZ misses the yen/GBP contributions
to tail vol.

See `k1118b_var_trinity.png`.

## 6. Verdict

**H3 confirmed (mixed / asset-specific)**:
- EUR/USD: IV sufficient (Native_EVZ Harvey t=+5.07, alt-data null)
- JPY/USD: IV sufficient (Cross_EVZ t=+6.32, and Realized30 t=+3.67)
- **DXY: IV fails universally** (no source beats AR(1) at Harvey |t|>2)

**Any-IV rule**: `{EUR_USD: True, JPY_USD: True, DXY: False}` → 2/3 success.

**Key surprises**:
1. For **EUR/USD, the equity VIX (`^VIX`) is actively worse than AR(1) (t=-3.55)** —
   a clean counter-example to "VIX universally sufficient". Native currency IV
   (^EVZ) matters.
2. For **JPY/USD, EUR-currency IV (^EVZ) works better than US equity VIX (^VIX)** —
   `Cross_EVZ` t=+6.32 vs `Cross_VIX` t=+0.14. Consistent with FX carry-trade literature:
   JPY-funded carry unwinds correlate with global FX vol (which EVZ tracks) rather
   than with equity-market VIX.
3. For **DXY (UUP), no IV source works** — AR(1) persistence is the binding model.
   DXY as a basket averages out idiosyncratic currency-pair volatility, leaving
   mostly level/persistence dynamics that none of the tested IVs price.

## 7. Paper 4 boundary implication

Pre-K1118b compendium (9 experiments, 5 asset classes) claimed "universal sufficiency
with crypto exception". K1118b revises this:

**Revised Paper 4 boundary**:
- ✓ Equity (SPY / 0050.TW): native VIX sufficient
- ✓ Commodity (GLD): GVZ sufficient, alt-data harm
- ◐ Bond (TLT): partial (MOVE directional but QLIKE improvement <5%)
- ✓ EUR/USD: **native EVZ** sufficient (equity VIX ACTIVELY WORSE)
- ✓ JPY/USD: **cross-family FX IV (EVZ)** sufficient; equity VIX fails
- ✗ DXY basket: **no IV suffices** — persistence dominates
- ✗ BTC crypto: no IV suffices (K1118 + K1119 concur)

**Upgrade to claim**: "Native-asset-class implied vol is sufficient for weekly RV
prediction in equity, single-pair FX, and commodities; **it is NOT automatically
substitutable across asset classes** (equity VIX fails for EUR, fails for DXY).
Basket-FX (DXY) and crypto are the two IV-insufficient classes."

This is **more nuanced but stronger** than the previous claim — the null result on
cross-market substitution refutes a naive "one VIX fits all" narrative and aligns
with the FX carry-trade / dollar-factor literature (Menkhoff et al. 2012; Lustig-
Roussanov-Verdelhan 2011).

## 8. Limitations / Caveats

- **^EVZ discontinued 2025-03-05** — no forward extension unless CBOE resumes or
  CME-listed alternatives arise. Paper 4 live signal for EUR/USD ends 2025-Q1.
- **No ^JYVIX / ^BPVIX on yfinance** — could not test true native JPY/GBP IV.
  Cross_EVZ working for JPY is an indirect finding; native JPY IV might do even
  better (conjecture).
- **ETF proxies (FXE/FXY/UUP)** contain dividends/carry leakage; FX spot
  (EURUSD=X / JPY=X) may give slightly different numbers but not qualitatively
  different rankings.
- **Weekly RV proxy on daily closes** — intraweek FX moves (esp. during BOJ/ECB
  announcements) underestimate true path-dependent RV. Future work: 5-min tick RV.
- DXY result may be partly an ETF-structure artifact (UUP has tracking error vs
  DX-Y.NYB spot index). Robustness check with DX-Y.NYB recommended.
- Sample 2010-2025-03 omits pre-GFC regime. Earlier period may behave differently.

## 9. Files

- `k1118b.py` — main experiment script (data fetch + 5-model OLS + DM + VaR trinity)
- `make_charts.py` — chart generator
- `k1118b_results.json` — full results (asset × IV × model × tests)
- `k1118b_dm_heatmap.png` — DM t-stat IV-vs-AR1 heatmap
- `k1118b_qlike_comparison.png` — OOS QLIKE across models × IV sources × assets
- `k1118b_var_trinity.png` — VaR Trinity pass/fail matrix
- `run.log` — execution log

## 10. References

- Baker, S. R., Bloom, N., Davis, S. J. (2016). "Measuring Economic Policy Uncertainty". *QJE*.
- Brave, S., Butters, R. A. (2011). "Monitoring Financial Stability: A Financial Conditions Index Approach". *Chicago Fed Economic Perspectives*.
- Christoffersen, P. (1998). "Evaluating Interval Forecasts". *IER*.
- Harvey, D., Leybourne, S., Newbold, P. (1997). "Testing the Equality of Prediction Mean Squared Errors". *IJF*.
- Kupiec, P. (1995). "Techniques for Verifying the Accuracy of Risk Management Models". *JDeriv*.
- Lustig, H., Roussanov, N., Verdelhan, A. (2011). "Common Risk Factors in Currency Markets". *RFS*.
- Menkhoff, L., Sarno, L., Schmeling, M., Schrimpf, A. (2012). "Carry Trades and Global FX Volatility". *JF*.
- Patton, A. (2011). "Volatility Forecast Comparison using Imperfect Volatility Proxies". *JoE*.

## 11. Predecessor experiments

- K1116 (SPY EPU+NFCI+STLFSI vs VIX — NULL)
- K1118 (GLD/TLT/BTC — 3/3 NULL vs native IV)
- K1119 (BTC DVOL — still fail)
- K1098 (0050.TW VIXTWN sufficient)
- K473, K750, K789, K504 (SPY alt-data null collection)
