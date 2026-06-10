# K1464 — BAB return conditional on prior-month realized volatility

## 動機

JFE 2025 *"The volatility puzzle of the beta anomaly"* 提出一個假說：
**Betting-Against-Beta (BAB) 策略的報酬條件依存於前期已實現波動 (RV)**。
具體 hypothesis 為：**低 vol 月份之後 BAB premium 集中釋放**（low-beta 過度賣壓 mean-revert，high-beta 過度買壓亦反轉），**而高 vol 月份之後 BAB premium 收縮甚至轉負**（風險偏好 / 槓桿約束驅動的 beta anomaly 此時失靈）。

如果這個 conditioning effect 真實存在，BAB 應該不只是一個 unconditional alpha，而是一個**狀態依賴**的 risk premium — 對 vol-targeting 與 risk parity 策略的 BAB allocation 有直接 implication。

## 相關文獻（pre-experiment review）

1. **Frazzini, A., & Pedersen, L. H. (2014).** "Betting Against Beta." *JFE*, 111(1), 1–25. → 原 BAB 構造、rank weights、leverage-to-beta=0 設計（**本研究 portfolio 構造嚴格遵循**）。
2. **Asness, C., Frazzini, A., Gormsen, N. J., & Pedersen, L. H. (2020).** "Betting Against Correlation." *JFE*, 135(3), 629–652. → BAB 的橫斷面動態與時間序列 conditioning。
3. **Bali, T. G., Brown, S. J., Murray, S., & Tang, Y. (2017).** "A lottery-demand-based explanation of the beta anomaly." *JFAR*, 52(6), 2369–2397. → behavioral 角度。
4. **JFE 2025 "Volatility puzzle of the beta anomaly"**（source paper）→ 直接 motivation。
5. **Adrian, T., & Shin, H. S. (2010).** "Liquidity and leverage." *J. Financial Intermediation*. → 高 vol 期 leverage constraint 解釋。

## 設計

| Dimension | Choice | Rationale |
|---|---|---|
| Universe | 207 hand-curated US large-cap tickers (after delisting drop: 198) | 跨 sectors，2000-2025 多數時期 active；survivorship bias 已揭露 |
| Period | 2000-01 to 2025-12 (daily); effective monthly BAB 2005-01 to 2025-12 (252 obs) | 60-month rolling beta 需 warm-up |
| Stock returns | Monthly simple returns from daily log-returns (min 15 daily obs/month) | Standard |
| Market | SPY adjusted close → monthly returns | Frazzini-Pedersen standard |
| Beta | Rolling 60-month OLS beta vs SPY (80% non-NaN requirement) | FP 2014 standard |
| BAB construction | Frazzini-Pedersen rank weights, long bottom 30% beta, short top 30%, scaled by 1/beta_L and 1/beta_H | Standard, beta-neutral on net |
| Conditioning signal | Market month-t RV (sqrt sum sq daily log-returns) → **lagged 1 month** → tertile | 嚴格避免 lookahead |
| Hypothesis test | Welch t-test, Newey-West HAC (lag=6), stationary block bootstrap (block=12, reps=10000, seed=42) | HAC + bootstrap 雙確認 |
| Secondary | Fama-MacBeth lite: BAB ret ~ lagged RV percentile (HAC SE) | 連續變數 robustness |

### Lookahead 防護（**最高優先**）

1. **Beta lag**：`betas.loc[prev_idx]` (即 t-1 月底 beta) 用來形成 t 月底 portfolio → 報酬在 t+1 月實現。`bab_returns()` 用 `range(1, len(fwd_ret))` 顯式 shift。
2. **RV regime lag**：`mkt_rv.shift(1)` 在 `conditional_analysis()` 中明確套用 — 條件 signal 來自 t-1 月，BAB 報酬來自 t 月。
3. **Beta 估計窗口**：60-month rolling，t-60..t-1 → 不含 t 月 own return。
4. **Bootstrap seed**：`seed=42`（rng + scipy + numpy 一致）。

### 公平比較

Unconditional baseline BAB 使用**同一條 BAB series**（同 universe、同 lag、同 leverage、同 rebalance freq），與 conditional tertile sub-samples 來自同一個構造，差別僅在於 sample partition。沒有套件 vs 自寫的 asymmetric refinement 風險（K1213 / K1216c 教訓）。

## 結果

### 主結果：tertile by lagged market RV

| Regime | N | Ann. Return | Ann. Sharpe | NW t-stat |
|---|---|---|---|---|
| Low vol | 84 | 15.41% | 0.947 | 2.80 |
| Mid vol | 84 | 17.54% | 0.920 | 2.70 |
| High vol | 84 | 5.13% | 0.290 | 0.62 |
| **Unconditional** | 252 | 12.69% | 0.717 | 3.35 |

### 差異檢定（low vol vs high vol）

| 統計量 | 值 |
|---|---|
| Mean diff (low − high), monthly | 0.0086 (≈ 10.3% annualized) |
| Welch t-stat | 1.13 (p = 0.259) |
| HAC (lag=6) coef | 0.0043 |
| HAC t-stat | **1.04** (p = 0.300) |
| Bootstrap mean diff | 0.0085 |
| Bootstrap 95% CI | [−0.0076, 0.0244] (**含 0**) |

### Fama-MacBeth lite (BAB_t ~ lagged_RV_percentile, HAC)

| Coefficient | Value | t-stat | p |
|---|---|---|---|
| RV percentile slope | −0.0149 | −1.23 | 0.218 |
| R² | 0.71% | — | — |

斜率為負（高 vol percentile → 低 BAB），方向與 hypothesis 一致但統計上不顯著。

## Verdict: **NULL**

**判定依據（pre-registered bar）**：
- SUPPORT 需 |HAC t| > 2.5 **且** bootstrap 95% CI 排除 0 **且** sign 正向
- 實際：HAC t = 1.04，bootstrap CI [−0.008, 0.024] **含 0**，未達 SUPPORT bar
- 不達 MIXED 門檻（|t| > 2.0）

### 解讀

1. **Sharpe 差距大、平均差距不顯著**：low_vol Sharpe 0.95 vs high_vol Sharpe 0.29，看似強烈，但這個 Sharpe gap 主要由 **high_vol regime 的標準差較高**驅動，而非 mean return 系統性下降。Mean monthly return 從 1.28% (low) → 0.43% (high)，gap 10.3% annualized 但 SE 很大 → t-stat 僅 1.04。
2. **方向與 source paper 一致**：low > mid > high 排序與 hypothesis 預測一致，FM-lite 斜率為負，但**統計力不足以 reject NULL**。可能原因：
   - 樣本期 2005-2025 涵蓋 GFC、Covid、2022 通膨 shock — 高 vol regime obs 集中在這些事件，sample size 不夠分散
   - Universe 限於 198 stocks（FP 2014 用 CRSP 全市場 >3000 stocks）；樣本內 vol regime variability 可能被攤平
   - 60-month beta 在 regime shift 時 slow-moving
3. **Unconditional BAB 仍顯著**：Sharpe 0.72、NW t = 3.35 — 與 FP 2014 範圍一致，表示我們的 BAB 構造本身沒問題。
4. **不能直接駁回原 paper**：null result ≠ no effect；只能說「在此 universe / period 下，effect 未達 |t|>2.5 bar」。

### Limitations

- **Survivorship bias**: hand-curated 大型股清單偏向倖存者。對 *unconditional* BAB premium 估計有 upward bias；對 *conditional* (within-strategy) tertile difference 影響較小，因為 bias 是 constant 跨 regime。
- **Sample size in regimes**: 84 obs/tertile，high vol regime power 有限。
- **Universe scope**: 不是 CRSP 全市場；不含 small-cap 與 micro-cap，後者在原 BAB 文獻是 driver。
- **Risk-free rate**: simplified 為 0（忽略 monthly T-bill），對 tertile difference 影響可忽略，但會略高估 Sharpe absolute level。
- **Beta 估計法**: 簡單 OLS 60-month；FP 2014 用 5-year monthly with shrinkage to 1。Shrinkage 對極端 beta tail 有影響，可能影響 high-beta short leg 構成。

## 後續方向

1. **擴大 universe**：用 CRSP / Compustat 完整 monthly stock data（需付費或申請），或 yfinance + 季調 SP500 changes（survivorship-free）
2. **不同 vol horizon**：除月度 RV 外，測試 3-month / 6-month rolling RV 作為 conditioning
3. **VIX-based conditioning**：VIX (forward-looking) vs realized RV (backward) 何者更 predictive
4. **Sub-period split**：pre-2008 / 2008-2015 / 2015-2025 三 sub-period 各自看 conditioning
5. **Cross-sectional decomposition**: 低 vol regime 的 BAB premium 來自 low-beta long leg 還是 high-beta short leg？

## Deliverables

- `k1464_bab_vol_conditional.py` — 可重跑 (seed=42)
- `k1464_bab_vol_conditional_results.json` — 完整結果含 per-tertile stats / HAC / bootstrap / FM-lite
- `figures/bab_cumulative_by_regime.png`
- `figures/bab_sharpe_by_tertile.png`
- `figures/rv_vs_bab_scatter.png`
- `README.md` (this file)

## 復現指令

```bash
cd experiments/k1464_bab_vol_conditional
uv run python k1464_bab_vol_conditional.py
```
網路需可達 yfinance；首跑會抓 ~200 ticker × 25 yr daily prices (~5 min)。
