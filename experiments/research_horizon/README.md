# research_horizon: 偏度風險溢酬「期限結構」作長 horizon 尾部訊號

## 動機

任務池 brief 指向一個明確問題：如果只用免費資料 `SPY + ^VIX + ^SKEW`，能不能做出一個
**short vs long skew-premium proxy**，並檢驗長端 proxy 是否比短端 proxy 更能預測
6-12 個月後的 SPY 報酬與 drawdown？

這不是重跑舊的「SKEW 有沒有增量預測力」問題。相鄰知識已經很清楚：

- `K979`：SKEW 對短 horizon 波動率預測沒有超越 VIX 的增量。
- `K535`：HAR-VIX 框架下，SKEW / realized skewness 對日頻 RV 也沒有穩健增量。
- `K1452`：VRP 的 segment sign-split 在免費 proxy 下多半是 NULL，且 horizon mismatch 必須明講。

所以這次改問：

1. **不是** 預測明天波動率，而是預測 **6-12 個月** 的 tail outcomes。
2. **不是** 單看 SKEW level，而是用 option-implied tail fear 對照
   short/long realized skewness，做出一個「類期限結構」proxy。

## 文獻先備

本實驗直接對應以下文獻方向：

1. Chang, Wu, and Borochin, *The Information Content of the Term Structure of Risk-Neutral Skewness*,
   *Journal of Empirical Finance* 58 (2020).
   核心點：短端與長端 risk-neutral skewness 對未來報酬的訊息可能不同，term spread 比單一 level 更有資訊。
2. Dew-Becker and Giglio, *Recent Developments in Financial Risk and the Real Economy*,
   NBER Working Paper 31878 / Annual Review of Financial Economics (2023/2024).
   核心點：financial risk 的 term structure 與 conditional skewness 是近年主題。
3. *Variance and Skewness Risk Premium and Expected Equity Returns* (SSRN, 2025).
   核心點：variance 與 skewness risk premia 的 term structure 可能對未來 equity outcomes 有預測力。

## 實驗設計

### 資料

- `SPY`, `^VIX`, `^SKEW` from `yfinance`
- 樣本：2010-01-01 到腳本執行日

### Proxy 定義

- `implied_tail_fear = ((SKEW - 100) / 100) * (VIX / 100)`
  - 用 SKEW 偏離 100 的程度乘上 VIX level，當作「被定價的左尾恐懼」粗略 proxy。
- `realized_tail_22 = - rolling 22d realized skewness`
- `realized_tail_126 = - rolling 126d realized skewness`
- `short_skew_premium = implied_tail_fear - realized_tail_22`
- `long_skew_premium = implied_tail_fear - realized_tail_126`
- `term_structure_gap = long_skew_premium - short_skew_premium`

這個設計是 **free-data reduced-form proxy**，不是期權市場真正的多到期 skew swap term structure。
因為免費資料只有單一 `^SKEW` 指標，沒有不同到期 option-implied skew 曲線。

### Targets

- `fwd_ret_126`, `fwd_ret_252`: 從 `t+1` 開始累積的 6m / 12m future log return
- `fwd_mdd_126`, `fwd_mdd_252`: 從 `t+1` 開始往後看 6m / 12m 的最大 drawdown

### 模型

控制變數固定為：

- `vix_lag1`
- `ret_21_lag1`
- `rv_21_lag1`

三個候選模型：

- `M1_short`: controls + `short_skew_premium_lag1`
- `M2_long`: controls + `long_skew_premium_lag1`
- `M3_gap`: controls + `term_structure_gap_lag1`

### 評估

- OOS: annual expanding-window refit，OOS start = 2018-01-01
- 指標：OOS R², MSE
- 正式檢定：`M2_long` vs `M1_short` 的 squared-error DM-HAC test
- 多重檢定：4 個 primary tests 一律做 BH-FDR
- Lookahead 防護：所有 predictors 均 `shift(1)`；target 從 `t+1` 起算

## 要回答的核心問題

1. 長端 proxy 的 OOS loss 是否低於短端 proxy？
2. 這個優勢是否集中在 **drawdown** 而不是單純 return？
3. 經過 BH-FDR 後，證據是 robust、mixed，還是 NULL？

## 產物

- `research_horizon.py`
- `research_horizon_results.json`
- `figures/proxy_timeseries.png`
- `figures/oos_r2_bars.png`

## 執行

```bash
uv run python experiments/research_horizon/research_horizon.py
```
