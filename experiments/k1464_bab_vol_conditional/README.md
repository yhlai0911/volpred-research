# K1464 — BAB return conditional on prior-month realized volatility

## 動機

JFE 2025 *The volatility puzzle of the beta anomaly* 的核心命題是：
BAB premium 主要集中在**前月低波動**之後，高波動月份之後則收縮甚至轉負。

本次 rework 目的不是再做一次「長得像對」的 replication，而是把第一版被 Codex 判定為不可採信的三個方法缺陷修掉：

1. tertile 切點改成 **expanding recursive quantiles**
2. low-high 差異改成 **原始月序列上的 HAC 線性限制檢定**
3. bootstrap 改成 **full-series stationary block bootstrap**

## 相關文獻

1. Frazzini, A., & Pedersen, L. H. (2014). *Betting Against Beta*. JFE.
2. Asness, C., Frazzini, A., Gormsen, N. J., & Pedersen, L. H. (2020). *Betting Against Correlation*. JFE.
3. Bali, T. G., Brown, S. J., Murray, S., & Tang, Y. (2017). *A lottery-demand-based explanation of the beta anomaly*. JFAR.
4. JFE 2025 *The volatility puzzle of the beta anomaly*.
5. Adrian, T., & Shin, H. S. (2010). *Liquidity and leverage*. JFI.

## 設計

| Dimension | Choice | Notes |
|---|---|---|
| Universe | 205 hand-curated US large-cap equities | **ETF 已移除**；9 檔無足夠資料後保留 196 檔 |
| Period | 2000-01 to 2025-12 daily | 60m beta warm-up + recursive tertile warm-up 後，有效樣本 2008-01 to 2025-12 |
| Returns | Daily log returns aggregated to monthly simple returns | 每月至少 15 個交易日 |
| Market | SPY adjusted close | 市場報酬與市場 RV 都由 SPY 生成 |
| Beta | Rolling 60-month monthly beta vs SPY | 需 80% 非缺值 |
| BAB construction | **FP-style approximation** | full-cross-section rank weights + inverse-beta leg leverage；`rf=0`、無 shrinkage-to-1 |
| Conditioning signal | lagged market monthly RV | `mkt_rv.shift(1)` |
| Regime assignment | expanding tertiles | 每月只用更早的 lagged RV 歷史；`min_history=36` |
| Inference | Welch t, HAC(6), stationary block bootstrap(12, 10000, seed=42) | bootstrap 在**完整月序列**上抽 block |
| Secondary | BAB_t ~ recursive RV percentile | HAC SE |

## Lookahead 防護

1. **Beta lag**：`betas.loc[prev_idx]` 形成 `t` 月投組，報酬在 `t+1` 月實現。
2. **RV lag**：regime signal 取 `mkt_rv.shift(1)`。
3. **Tertile cutoffs**：每個月的 q33/q67 只用 `t-1` 以前的 RV 歷史。
4. **Bootstrap**：重抽單位是完整 `(BAB_t, regime_t)` 月序列，不是先切子樣本再抽。

## 主結果

### Recursive tertile by lagged market RV

| Regime | N | Ann. Return | Ann. Sharpe | NW t-stat |
|---|---|---|---|---|
| Low vol | 65 | 12.07% | 0.801 | 1.97 |
| Mid vol | 75 | 16.60% | 0.964 | 3.85 |
| High vol | 76 | -2.20% | -0.119 | -0.25 |
| **Unconditional** | 216 | 8.62% | 0.502 | 2.19 |

### Low vol vs high vol

| 統計量 | 值 |
|---|---|
| Mean diff (low − high), monthly | 0.0119 |
| Mean diff annualized | 14.28% |
| Welch t-stat | 1.46 (p = 0.147) |
| HAC low − high | 0.0119 |
| HAC t-stat | 1.45 (p = 0.147) |
| Bootstrap mean diff | 0.0111 |
| Bootstrap 95% CI | [-0.0070, 0.0274] |

### Continuous robustness

| Coefficient | Value | t-stat | p | N |
|---|---|---|---|---|
| Recursive RV percentile slope | -0.0094 | -0.96 | 0.336 | 180 |
| R² | 0.31% | — | — | — |

## Verdict: **NULL**

方向上仍然是 `low > high`，而且 high-vol bucket 的平均年化報酬已轉負，但證據強度仍不足：

- `HAC t = 1.45`
- bootstrap CI 含 0
- continuous slope 仍不顯著

所以結論只能是：**在這個 large-cap survivor universe、這個樣本期、這套近似 FP BAB 構造下，沒有足夠證據支持 JFE 2025 的 conditioning effect。**

## Power

以 low/high 兩組樣本波動與樣本數估算，雙尾 5% 顯著水準、80% power 下：

- `MDES ≈ 0.0229 / month`
- 約 **27.4% annualized** 的 low-high 差距才有合理檢出力

本次估到的 `0.0119 / month` 明顯低於這個門檻，所以這個 NULL 比較接近「power 不足下的未能拒絕」，不是強否證。

## 解讀

1. 修正方法缺陷後，low-vol 與 high-vol 的方向差距比第一版更大，但顯著性仍不足。
2. 真正最強的 bucket 變成 **mid vol**，不是原假說預期的 low vol 主導。
3. Unconditional BAB 在同一有效樣本上仍有正報酬，但強度已降到 `NW t = 2.19`，顯示第一版部分強度來自較早樣本與不正確的 regime 切法。

## Limitations

- **Survivorship bias**：hand-curated large-cap survivors 會抬高 unconditional BAB，也可能因 crisis composition shift 扭曲 conditional diff。
- **Universe 不夠廣**：196 檔 large-cap 與 FP/CRSP 全市場差距很大，small-cap driver 幾乎沒被捕捉。
- **BAB 僅為 FP-style approximation**：`rf=0`、無 beta shrinkage-to-1、不是原文的完整資產庫。
- **Regime N 有限**：65/75/76 個月不足以精準分辨 10-15% 年化等級的差距。

## 後續方向

1. 換成 survivorship-free universe（CRSP / 歷史 constituents）。
2. 測試 3m/6m RV 或 VIX term-structure conditioning。
3. 拆解 low-beta long leg 與 high-beta short leg，確認 effect 來源。
4. 做 subperiod split，檢查 GFC / COVID / post-2022 是否主導結果。

## Deliverables

- `k1464_bab_vol_conditional.py`
- `k1464_bab_vol_conditional_results.json`
- `figures/bab_cumulative_by_regime.png`
- `figures/bab_sharpe_by_tertile.png`
- `figures/rv_vs_bab_scatter.png`

## 復現

```bash
cd experiments/k1464_bab_vol_conditional
uv run python k1464_bab_vol_conditional.py
```
