# research_functional_role

## Verdict

`NULL_MIXED_RESPONDER_EVIDENCE`

多層避險組合相對 SPY 的左尾風險確實較低，但「TLT / DBMF / vol-target overlay 各自穩定扮演不同 responder」沒有通過跨危機型態驗證。結果可作為 null finding，不應寫成可交易 alpha 或穩定避險分工定律。

## Motivation

文獻與 practitioner framework 常把防禦層拆成不同功能：直接或代理避險處理急跌，趨勢跟隨處理慢熊，risk overlay 管理部位大小。本實驗把這個說法放到可重跑的 ETF proxy：

- SPY：核心風險資產
- TLT：long-duration first-responder proxy
- DBMF：managed-futures / trend-following proxy
- vol-target overlay：只調整 multi-layer 組合總風險，不新增訊號

參考脈絡：

- Schwalbach and Auret (2025), *Enhancing global equity returns with trend-following and tail risk hedging overlays*: https://www.tandfonline.com/doi/full/10.1080/10293523.2025.2553254
- J.P. Morgan Asset Management 2026 LTCMA: https://am.jpmorgan.com/content/dam/jpm-am-aem/global/en/insights/portfolio-insights/ltcma/noindex/ltcma-full-report.pdf
- Eastspring, *Smarter risk management overlays for multi-asset portfolios*: https://www.eastspring.com/insights/deep-dives/smarter-risk-management-overlays-for-multi-asset-portfolios
- Goldman Sachs Asset Management (2026), *Finding the True Value of Tail-Risk Hedging*: https://am.gs.com/en-us/advisors/insights/article/2026/finding-true-value-tail-risk-hedging

## Data

- Source: yfinance daily close, `auto_adjust=True`
- Tickers: SPY, TLT, DBMF
- Aligned prices: 2019-05-08 to 2026-06-12
- OOS evaluation: 2020-01-02 to 2026-06-12
- OOS observations: 1,620 daily returns
- DBMF starts only in 2019, so this is a post-inception ETF-proxy test, not a long historical CTA study.

## Method

Strategies are daily-rebalanced constant-weight ETF proxies:

| Strategy | SPY | TLT | DBMF |
|---|---:|---:|---:|
| SPY | 100% | 0% | 0% |
| SPY_TLT_80_20 | 80% | 20% | 0% |
| SPY_DBMF_80_20 | 80% | 0% | 20% |
| MULTI_LAYER_70_15_15 | 70% | 15% | 15% |

`MULTI_LAYER_VT_70_15_15` applies a 12% annualized volatility target to the base multi-layer return with 63-day realized volatility and scale bounds `[0.50, 1.50]`.

Anti-lookahead line in code:

```python
vt_scale = (VOL_TARGET / lagged_realized_vol).clip(SCALE_MIN, SCALE_MAX).shift(1)
```

The 2020 / 2022 / 2025 crisis windows are hard-coded ex-post stress labels for contribution decomposition only. They are not used for fitting, selection, or trading signals.

Formal uncertainty check:

- Paired moving-block bootstrap on OOS daily returns
- `BOOTSTRAP_REPS = 1000`
- `BOOTSTRAP_BLOCK = 21`
- `SEED = 42`

## OOS Performance

| Strategy | CAGR | Ann vol | Sharpe | MDD | <= -2% days |
|---|---:|---:|---:|---:|---:|
| SPY | 15.5% | 20.3% | 0.81 | -33.7% | 68 |
| MULTI_LAYER_70_15_15 | 12.1% | 14.6% | 0.85 | -23.5% | 30 |
| MULTI_LAYER_VT_70_15_15 | 11.0% | 13.2% | 0.85 | -19.5% | 27 |

The multi-layer variants reduce left-tail frequency and drawdown versus SPY, but the CAGR sacrifice is material. This is risk-shaping evidence, not alpha evidence.

## Crisis Role Decomposition

Arithmetic contribution approximation for `MULTI_LAYER_VT_70_15_15`; compounded strategy returns are in `research_functional_role_results.json`.

| Window | SPY return | Multi-layer VT return | SPY contrib | TLT contrib | DBMF contrib | VT overlay contrib | Role result |
|---|---:|---:|---:|---:|---:|---:|---|
| 2020 COVID liquidity | -33.4% | -19.0% | -26.4% | +2.2% | -0.9% | +4.7% | TLT helped, DBMF did not; overlay dominated. |
| 2022 rate shock | -24.1% | -16.7% | -17.7% | -5.4% | +4.4% | +1.1% | DBMF + overlay matched expected slow-bear role. |
| 2025 policy shock | -18.6% | -14.3% | -14.0% | +0.2% | -1.2% | -0.1% | Expected DBMF / overlay roles failed. |

Role score:

- Expected responder pair positive: 1 / 3 windows
- Expected first responder top-ranked: 1 / 3 windows

## Bootstrap Results

`MULTI_LAYER_VT_70_15_15` vs SPY:

- CVaR5 improvement: +1.04 percentage points, 95% CI `[+0.51, +1.73]`, one-sided p = 0.000
- <= -2% day frequency reduction: +2.53 percentage points, 95% CI `[+1.48, +3.83]`, one-sided p = 0.000
- MDD improvement: +14.20 percentage points, 95% CI `[-1.49, +19.96]`, one-sided p = 0.038

`MULTI_LAYER_VT_70_15_15` vs unscaled `MULTI_LAYER_70_15_15`:

- CVaR5 improvement: +0.16 percentage points, 95% CI `[-0.14, +0.52]`, p = 0.197
- <= -2% day frequency reduction: +0.19 percentage points, 95% CI `[-0.49, +0.93]`, p = 0.354
- MDD improvement: +4.03 percentage points, 95% CI `[-4.87, +7.85]`, p = 0.375

Interpretation: the layered allocation beats SPY on left-tail measures, but the vol-target overlay's incremental value over a static TLT/DBMF multi-layer is not statistically robust.

## Files

- `research_functional_role.py`: executable experiment script
- `research_functional_role_results.json`: full metrics, bootstrap output, methodology metadata
- `fig_strategy_drawdowns.png`: OOS drawdown paths
- `fig_crisis_contributions.png`: crisis-window component contributions

## Caveats

- No direct option-based tail hedge is tested; VT is only a risk-budget overlay.
- Daily ETF rebalancing costs, taxes, and slippage are not subtracted.
- DBMF is one managed-futures ETF proxy and is not a full CTA history.
- Crisis windows are ex-post descriptive windows, not a train/test selection rule.
- The result supports cautious risk-shaping language only. It does not support a publishable claim that each hedge layer has a stable functional role across crisis types.
