# K1652 — Wrapped-token basis stress and crypto volatility regimes

**Verdict: CONDITIONAL_MIXED_DAILY_PROXY.** Daily wrapped-token basis/liquidity features improve out-of-sample QLIKE for several BTC/ETH pairs, but high-vol regime classification is weak and liquid-staking token basis can be structural rather than stress. This is a useful lead, not a publication-ready price-discovery result.

---

## 1. Research question

This experiment asks whether wrapped-token market stress contains incremental information about native BTC/ETH volatility regimes:

> Do daily wrapped-token basis and liquidity proxies, known at t-1, improve prediction of native BTC/ETH squared return at t beyond a native lagged-volatility baseline?

The motivation comes from `research_program.md` line 1483: wrapped tokens such as WBTC, stETH, cbETH, and WETH may reveal DeFi-specific stress before it appears in native BTC/ETH volatility. A positive result would suggest that crypto-native wrapper markets deserve deeper high-frequency / on-chain study. A null result would mean daily public wrapped-token prices are too coarse.

This version is deliberately conservative:

- It uses **daily Yahoo Finance data only**.
- It does **not** estimate Hasbrouck or Gonzalo-Granger information share.
- It does **not** use bridge supply, DEX pool depth, or on-chain liquidity.
- It treats liquid-staking basis with caution because stETH/cbETH can trade away from ETH for structural reasons.

---

## 2. Literature context

- *Price Discovery through Wrapped Tokens* (SSRN / Economics Letters, 2025): motivates the wrapped-token price-discovery channel and reports that WBTC contributes to BTC price discovery in high-frequency data.
- BIS Working Paper 1268, *Towards verifiability of total value locked (TVL) in decentralized finance* (2025): warns that DeFi liquidity / TVL measurement is not standardized.
- IMF Working Paper 2023/213, *New Evidence on Spillovers Between Crypto Assets and Financial Markets*: motivates volatility spillover framing.
- *The Economics of Liquid Staking Derivatives: Basis Determinants and Pricing* (Journal of Futures Markets, 2025): motivates treating liquid-staking basis as partly structural, not purely a peg-stress signal.

Platform priors:

- K1089 / K1096 / K1119: crypto volatility forecasting often fails against simple baselines, even with VIX or DVOL-style information.
- K1620: crypto low-vol regime dependence was null; do not over-read crypto regime patterns.
- K1237 / K124x: crypto spillover structure can exist in-sample while OOS forecasting remains weak.
- K1626 / K1626f: price-discovery claims require careful time alignment; daily data cannot substitute for high-frequency information share.

---

## 3. Data

Source: Yahoo Finance via `yfinance`, daily adjusted close and volume.

Period requested: 2019-01-01 to 2026-07-05 exclusive. Effective samples differ by wrapped token availability.

| Pair | Effective sample | Total rows | OOS rows | Mean abs basis | 95% abs basis |
|---|---:|---:|---:|---:|---:|
| BTC / WBTC | 2019-10-10 to 2026-07-04 | 2460 | 984 | 21.4 bp | 71.9 bp |
| ETH / stETH | 2021-09-02 to 2026-07-04 | 1767 | 707 | 55.3 bp | 276.1 bp |
| ETH / cbETH | 2023-05-04 to 2026-07-04 | 1158 | 464 | 801.1 bp | 1216.3 bp |
| ETH / WETH | 2019-09-11 to 2026-07-04 | 2489 | 996 | 42.5 bp | 98.4 bp |

The cbETH basis is much larger because cbETH is a liquid-staking derivative with accrual and structural basis. It is not directly comparable to WBTC or WETH peg deviations.

---

## 4. Method

Target:

- `target_rv_t = native_log_return_t^2`, a daily realized variance proxy.

Baseline features:

- lagged log squared return
- lagged 7-day average log RV
- lagged 30-day average log RV
- lagged absolute native return

Wrapped-token features:

- wrapped/native log basis
- absolute basis
- basis widening
- 30-day rolling basis z-score
- large-basis indicator, `|z| > 2`
- log wrapped/native volume ratio
- wrapped-token absolute return

Robustness:

- `stress_only` removes basis level and wrapped absolute return, keeping only absolute basis, widening, z-score, large-basis indicator, and volume ratio.

Evaluation:

- Chronological 60/40 split.
- Forecast model: `StandardScaler + Ridge(alpha=1)` on log RV.
- Classification model: `StandardScaler + balanced LogisticRegression` for high-vol label.
- QLIKE uses `actual / predicted - log(actual / predicted) - 1`.
- DM test uses `volpred.stats.model_evaluation.dm_test` on pointwise QLIKE / MSE losses.
- Harvey gate: `|t| > 3`; negative t means augmented model has lower loss.

Lookahead policy:

- Every feature is shifted by one day: `raw_features.shift(1)`.
- High-vol threshold is an expanding 75th percentile of native RV, also shifted by one day.
- Signal comes from t-1; return / RV target is at t.

---

## 5. Results

### 5.1 Volatility forecast loss

| Pair | QLIKE improvement | DM t | Harvey pass | Stress-only QLIKE improvement | Stress-only DM t | Stress-only pass |
|---|---:|---:|---:|---:|---:|---:|
| BTC / WBTC | +2.14% | -4.23 | yes | +3.48% | -4.06 | yes |
| ETH / stETH | +8.16% | -1.95 | no | +8.16% | -1.90 | no |
| ETH / cbETH | +56.51% | -5.93 | yes | +56.59% | -5.94 | yes |
| ETH / WETH | +3.06% | -3.37 | yes | +3.06% | -3.16 | yes |

QLIKE results say the wrapped-token stress features help reduce variance forecast loss for BTC/WBTC, ETH/cbETH, and ETH/WETH under the Harvey gate. ETH/stETH improves economically but not statistically under the `|t| > 3` rule.

However, QLIKE is not the whole story. MSE improvements are much smaller and never pass the Harvey gate. For BTC/WBTC, MSE improvement is only +0.27%; for ETH/WETH it is +0.27%; for ETH/cbETH it is +4.43% but DM t is only -1.05.

### 5.2 High-vol regime classification

| Pair | AUC delta | Brier improvement | Stress-only AUC delta | Stress-only Brier improvement |
|---|---:|---:|---:|---:|
| BTC / WBTC | -0.0003 | +2.80% | -0.0013 | +2.65% |
| ETH / stETH | -0.0131 | +6.28% | -0.0119 | +6.28% |
| ETH / cbETH | -0.0531 | -48.57% | -0.0528 | -47.93% |
| ETH / WETH | -0.0002 | +1.08% | +0.0001 | +0.99% |

Classification is weak. AUC does not improve in any meaningful way, and cbETH classification gets materially worse. The signal appears more like a variance-loss calibration improvement than a clean high-vol regime classifier.

---

## 6. Interpretation

This is not a null result, but it is also not a clean positive result.

What the evidence supports:

1. Daily wrapped-token basis/liquidity proxies can add information to QLIKE variance forecasts.
2. The BTC/WBTC result is the cleanest wrapped-token interpretation because WBTC is a wrapped BTC token rather than a staking derivative.
3. The result survives a stress-only robustness that excludes basis level and wrapped absolute return.

What the evidence does not support:

1. It does not prove wrapped tokens lead native crypto volatility regimes in a tradable sense.
2. It does not support a high-vol regime classification claim; AUC is flat or worse.
3. It does not estimate price discovery or information share.
4. It does not show that cbETH basis is a stress signal; cbETH has structural liquid-staking basis.

Overall: K1652 identifies a promising proxy worth deeper study, especially BTC/WBTC, but publication-grade evidence requires high-frequency DEX/CEX data or on-chain liquidity / bridge supply.

---

## 7. Research honesty checks

- No same-day signal: features are shifted by one day.
- Random seed fixed: `SEED=42`.
- Results JSON is written through temp-file validation and `os.replace`.
- Null / mixed result reported directly.
- No Sharpe strategy is reported, so no Sharpe inflation issue.
- Daily data limitation is explicit; no high-frequency price-discovery claim is made.

---

## 8. Outputs

- `experiments/k1652/k1652.py`
- `experiments/k1652/k1652_results.json`
- `experiments/k1652/k1652_basis_stress.png`

---

## 9. Suggested next steps

1. BTC/WBTC high-frequency test: CEX BTC spot vs WBTC DEX pools, estimate information share / lead-lag directly.
2. Add on-chain bridge supply, DEX liquidity depth, and pool imbalance to separate peg stress from price feed noise.
3. Treat stETH/cbETH separately as liquid-staking basis, with staking rewards and redemption frictions explicitly modeled.
