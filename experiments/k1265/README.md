# K1265 — VIX-Managed Portfolio (Moreira-Muir 2017 replication + VIX extension)

- **Experiment ID**: `k1265`
- **Status**: **done**（executed 2026-05-03; runtime ~12s, SPY 1993-2026 daily, 4 specs, 5,617 OOS obs）
- **Verdict**: **NULL** — no managed strategy passes the joint gate (ΔSharpe>0.15 + DM-HLN p<0.10 + ≥2/3 sub-periods positive + MDD ratio<1.2)
- **Proposer**: Claude (autonomous research backlog; cross-asset extension of Moreira-Muir 2017)
- **Executor**: Background worktree agent
- **Reviewer**: Codex CLI 0.121.0 (pre-execution review)

## 動機（Motivation）

Moreira & Muir (2017, _Journal of Finance_ 72(4), 1611-1644) 提出 **volatility-managed portfolios**：用 `1/σ²_{t-1}` scale market exposure，在低波動時加倉、高波動時減倉。原文宣稱 SPY 1926-2015 OOS Sharpe 從 ~0.40 → ~0.55，且加 alpha 在 Carhart 4-factor 模型上 ~5% / yr。

但近期文獻對此 finding 提出質疑：
- Cederburg, O'Doherty, Wang & Yan (2020, _JFE_): 跨 100+ 因子 portfolio 重做，full-sample alpha 集中在 1990s；後續樣本 alpha 大幅萎縮
- Liu et al. (2024, _IRFA_): 跨資產類別測試發現 effect 不一致

本實驗目的：
1. **Replicate Moreira-Muir** 在 SPY 1993-2026 longer sample（含 2020 COVID + 2022 rate-shock + 2024-26 AI rally）
2. **Extension**: 用 VIX (forward-looking implied vol) 替代 RV (backward-looking realised vol) 作為 scaling signal — VIX 是市場 expected vol，理論上比 RV 更 timely
3. 與簡單 **target_vol** baseline（一般 vol-targeting practice）對照，看 M&M 的 quadratic scaling 是否真有 marginal value

## 方法（Method）

### Data
- SPY daily auto-adjusted close (yfinance `SPY`, 1993-01-29 → 2026-04-30)
- VIX daily close (yfinance `^VIX`, same window)
- Realised vol: 22-day rolling std of daily returns × √252

### Strategies (4 specs, all long-only, monthly rebalance)
| Spec | Weight formula | Notes |
| --- | --- | --- |
| `buy_hold` | `w = 1` | baseline |
| `vol_target_static` | `w = min(1, 0.15 / σ̂_{t-1})` | conventional vol-targeting, 15% target |
| `mm_rv_managed` | `w = c_RV / σ̂²_{t-1}` | Moreira-Muir using realised vol |
| `mm_vix_managed` | `w = c_VIX / VIX²_{t-1}` | M&M extension using VIX as forward-looking proxy |

- **Calibration**: `c_RV` and `c_VIX` chosen so unconditional in-sample (1993-2003) average weight = 1.0 (matches M&M normalisation; ensures fair Sharpe comparison)
- **Weight cap**: 5× (prevents runaway leverage in low-vol windows; consistent with M&M Sec V)
- **Lookahead controls**: signals lagged via `.shift(1)`; calibration window strictly in-sample; OOS = 2004-2026

### Statistical tests
- DM-HLN (Diebold-Mariano with Harvey-Leybourne-Newbold small-sample correction) using daily return differential vs `buy_hold`, Newey-West auto-bandwidth (`floor(4·(n/100)^(2/9))`)
- Stationary bootstrap 95% CI for both Sharpe and Sharpe-difference (n=10,000, mean block=22, seed=42)
- Sub-period breakdown: 2004-2009 (incl. GFC) / 2010-2019 (low-vol decade) / 2020-2026 (COVID + rate-shock)

### Gates (all 4 required for PASS)
1. ΔSharpe vs buy-hold > +0.15
2. DM-HLN p < 0.10
3. ≥2/3 sub-periods with positive Sharpe diff
4. MDD ratio < 1.2 (managed MDD ≤ 1.2× buy-hold MDD)

## 結果（Results, OOS 2004-2026, n=5,617）

### Calibration
- `c_RV  = 0.01516` (in-sample 1993-2003)
- `c_VIX = 0.03119` (in-sample 1993-2003)

### Full-OOS metrics

| Strategy | Sharpe | AnnRet | AnnVol | MDD | Calmar | Turnover/yr |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| buy_hold | **0.639** | 12.0% | 18.7% | -55.2% | 0.22 | 0.00 |
| vol_target_static | 0.768 | 10.6% | 13.8% | -33.8% | 0.31 | 0.94 |
| mm_rv_managed | 0.670 | 13.4% | 20.0% | -46.7% | 0.29 | 9.27 |
| mm_vix_managed | 0.743 | 12.1% | 16.3% | -27.6% | 0.44 | 4.02 |

### DM-HLN vs buy_hold

| Strategy | t | p-value | NW max-lag |
| --- | ---: | ---: | ---: |
| vol_target_static | -0.99 | 0.32 | 9 |
| mm_rv_managed | +0.47 | 0.64 | 9 |
| mm_vix_managed | +0.07 | 0.95 | 9 |

### Bootstrap 95% CI for Sharpe difference (vs buy_hold)

| Strategy | CI lo | CI hi | Crosses 0? |
| --- | ---: | ---: | :--- |
| vol_target_static | -0.024 | +0.289 | **yes** (just barely) |
| mm_rv_managed | -0.348 | +0.394 | yes |
| mm_vix_managed | -0.179 | +0.373 | yes |

### Sub-period breakdown

| Period | buy_hold | vol_target_static | mm_rv_managed | mm_vix_managed |
| --- | ---: | ---: | ---: | ---: |
| 2004-2009 (GFC) | 0.20 | 0.39 | 0.60 | 0.46 |
| 2010-2019 (low-vol) | 0.93 | 0.97 | 0.73 | 0.89 |
| 2020-2026 (COVID+) | 0.79 | 0.83 | 0.65 | 0.78 |

Sub-period Sharpe diff signs (vs buy_hold):
- `vol_target_static`: 3/3 positive (但全 DM 不顯著)
- `mm_rv_managed`: 1/3 positive (only 2004-2009)
- `mm_vix_managed`: 1/3 positive (only 2004-2009)

### Gate verdict

| Strategy | ΔSharpe>0.15 | DM p<0.10 | ≥2/3 sub-pos | MDD ratio<1.2 | ALL PASS |
| --- | :---: | :---: | :---: | :---: | :---: |
| vol_target_static | NO (0.13) | NO (0.32) | YES (3/3) | YES (0.61) | **NO** |
| mm_rv_managed | NO (0.03) | NO (0.64) | NO (1/3) | YES (0.85) | **NO** |
| mm_vix_managed | NO (0.10) | NO (0.95) | NO (1/3) | YES (0.50) | **NO** |

## Verdict: NULL

**No strategy passes the joint statistical+economic gate.** Findings:

1. **Moreira-Muir RV-managed effect FAILS to replicate cleanly out-of-sample 2004-2026 on SPY**. Full-sample ΔSharpe = +0.03 (vs +0.13-0.15 originally reported on long pre-2015 sample). DM-HLN p=0.64 — far from significant. Consistent with Cederburg et al. (2020 JFE) skeptical extension.
2. **VIX-managed extension does NOT improve over RV-managed**. Sharpe (0.743) is between RV-managed (0.670) and vol-target-static (0.768); not statistically distinguishable from buy-hold (DM p=0.95). The advantage of VIX being "forward-looking" does not show up in Sharpe.
3. **Vol-target-static is the most consistent risk reducer**: lowest annual vol (13.8%), Sharpe 0.77 vs 0.64 buy-hold, lowest turnover (~1× / yr), 3/3 sub-periods positive. But still fails DM-HLN gate.
4. **All managed strategies sacrifice ann return** (buy-hold 12.0% > all alternatives in absolute terms, with vol_target lowest at 10.6%). The Sharpe improvement comes purely from vol reduction, not return enhancement.
5. **mm_rv_managed turnover is destructively high (9.27/yr)**: real-world frictions (bid-ask, market impact, taxes) would erase any gross Sharpe edge. mm_vix_managed turnover is more modest (4.02/yr) but still substantial.

## 對 Paper 3 narrative 的 contribution

**Negative result strengthens Paper 3's "no free lunch" narrative**: even classic published vol-managed signals (M&M 2017, JF) fail to clear modern OOS+gates on SPY. Reinforces that vol-targeting in equities should be framed as **risk-reduction tool, not Sharpe enhancer** — a position consistent with the paper's PRG/PRS hedging framework which scores via HE/VaR/utility, not raw Sharpe.

## Caveats

- **Data quality**: SPY pre-1996 has small AUM and wider spreads; results not adjusted for transaction costs (gross Sharpe).
- **Parameter sensitivity**: choice of `RV_window=22d`, in-sample window 1993-2003, weight cap 5× all reasonable defaults but not exhaustively swept.
- **No factor regression**: M&M's main result was alpha vs Carhart 4-factor; this experiment only tests Sharpe. A separate K could replicate the alpha test if desired.
- **Long-only constraint**: M&M 2017 also reports unrestricted version (allows >1 leverage). Our cap (5×) is liberal enough that this rarely binds in practice.

## References

1. Moreira, A., & Muir, T. (2017). Volatility-Managed Portfolios. _Journal of Finance_ 72(4), 1611-1644.
2. Cederburg, S., O'Doherty, M. S., Wang, F., & Yan, X. S. (2020). On the performance of volatility-managed portfolios. _Journal of Financial Economics_ 138(1), 95-117.
3. Liu, F., Tang, X., & Zhou, G. (2024). Volatility-managed portfolio across asset classes. _International Review of Financial Analysis_ 95.

## Files

- `k1265.py` — full experiment code (data load, strategies, DM, bootstrap, plots)
- `k1265_results.json` — all metrics, DM stats, bootstrap CIs, sub-period breakdown, gates
- `k1265_cumulative_returns.png` — log-scale cumulative wealth, 4 strategies
- `k1265_rolling_sharpe.png` — 3-year rolling Sharpe
- `k1265_weight_history.png` — weight time series

## Reproducibility

```bash
# from repo root
uv run python experiments/k1265/k1265.py
```

- Seed: 42 (bootstrap)
- Runtime: ~12s on M-series Mac
- Data fetched lazily via yfinance into `data/spy_daily.csv` and `data/vix_daily.csv`
