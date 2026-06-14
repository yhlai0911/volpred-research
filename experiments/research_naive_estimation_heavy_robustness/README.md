# research_naive_estimation_heavy_robustness

## 動機

任務池要求檢定：

> 危機期 naive 對沖是否因為免估計誤差，而比 beta / vol / CVaR 這類 estimation-heavy 對沖更穩健。

這題若直接拿 `VXX` 或 put proxy 做主比較，容易被產品 carry bleed 主導，最後測到的是「產品太貴」，不是「估計法有沒有價值」。所以本實驗拆成兩個 panel：

1. **Panel A: 單一 inverse-equity proxy (`SH`)**
   - 固定同一個 25% hedge budget。
   - 比較 `naive_fixed`、`rolling_beta`、`inverse_vol`、`rolling_cvar`。
   - 目的是盡量隔離「估計誤差」本身。
2. **Panel B: 25% defensive sleeve (`SH/TLT/GLD`)**
   - 比較 `naive_equal`、`beta_negative_beta`、`inverse_vol`、`rolling_cvar`。
   - 目的是檢查如果複雜法看起來有優勢，那到底來自 timing/estimation，還是只是因為它把部位長期塞到 `SH`。

## 與既有知識的差異化

- **I5** 已發現 `SPY/ES` hedge ratio 在 VIX regime 間幾乎不動，dynamic OHR 無明顯價值。
- **I1b** 已發現多數 commodity / cross-asset hedges 下，static 常常打平或勝過 rolling / EWMA。
- **K544** 講的是 tail-hedge overlay 的長期 NPV；本題不是問要不要買保險，而是問**估計密集的對沖規則是否真比 naive 穩健**。
- **K1334 / K1494** 講的是 tail-aware risk control；本題則是 hedge allocation / defensive sleeve 配置。

## 文獻

至少 3 篇：

1. Cao & Conlon (2025), *Tail Risk Hedging: The Superiority of the Naive Hedging Strategy*  
   https://onlinelibrary.wiley.com/doi/full/10.1002/fut.22602
2. *Hedging with Futures: Does Anything Beat the Naive Hedging Strategy?*  
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2462728
3. *Estimation of Optimal Hedge Ratio: A Wild Bootstrap Approach* (2024)  
   https://www.mdpi.com/1911-8074/17/7/310

## 資料

- 來源：`yfinance` auto-adjusted close
- 標的：`SPY`, `SH`, `TLT`, `GLD`
- 期間：2006-06-22 至 2026-06-12（依實際下載可得資料）
- 樣本頻率：日

## 實驗設計

### Panel A: 單一 `SH` 對沖

- `naive_fixed`: 固定 25% 放在 `SH`
- `rolling_beta`: trailing 63d 估計最小變異混合權重，再用 IS 校準到平均 25% hedge budget
- `inverse_vol`: trailing 63d inverse-vol rule，再校準到平均 25%
- `rolling_cvar`: trailing 252d 搜尋最小化 5% CVaR 的 `SH` 權重，再校準到平均 25%

策略報酬：

`r_t = (1 - h_t) * r_SPY,t + h_t * r_SH,t - cost_t`

其中 `h_t` 全部都 `shift(1)`，避免 lookahead。

### Panel B: `SH/TLT/GLD` defensive sleeve

- `naive_equal`: 25% hedge sleeve 等分成三份
- `beta_negative_beta`: 用 trailing 63d 的負 beta 大小分配 hedge sleeve
- `inverse_vol`: 用 trailing 63d inverse-vol 在 defensive assets 間分配
- `rolling_cvar`: 用 trailing 252d 在 `SH/TLT/GLD` simplex grid 上找 5% CVaR 最低組合

策略報酬：

`r_t = 0.75 * r_SPY,t + w_SH,t * r_SH,t + w_TLT,t * r_TLT,t + w_GLD,t * r_GLD,t - cost_t`

### 共同設定

- In-sample：2007-06-01 至 2017-12-29
- OOS：2018-01-02 起
- Stress windows：
  - `2018Q4`
  - `2020_crash`
  - `2022_bear`
  - `2025_correction`
- 成本：單邊 5 bps
- bootstrap：1000 reps, block length 21, seed 42

## 主要結果

以結果 JSON 為準，先給高層摘要：

1. **Panel A**：在同一個 `SH` hedge budget 下，`naive_fixed` 幾乎和 `rolling_cvar` 完全打平，且略優於 `rolling_beta` / `inverse_vol`。  
   這表示在最乾淨的 single-instrument 設定下，**complex estimation 沒有創造可驗證增量**。
2. **Panel B**：複雜法若在 crisis metrics 上看起來比較強，主要是因為它長期把 hedge sleeve 壓到 `SH`，而不是因為 timing 特別準。  
   換句話說，差異比較像是 **asset choice effect**，不是 **estimation skill effect**。
3. **整體結論**：本題拿到的是 **mixed / mostly-null** 證據，不支持「estimation-heavy hedge 普遍更 robust」這個說法；對「naive 因免估計誤差而更穩」也只能在 **Panel A** 這個乾淨設計下成立。

## 研究誠實 / 局限

- `SH` 是 inverse ETF，Panel A 有一部分是刻意設計出的「乾淨 identification」，因此不能把它誇大成普遍對所有 hedge instrument 都成立。
- `VXX` / 實際 put overlay 沒有納入主規格，因為那會把問題改寫成 carry / option-pricing 問題。
- 若要進一步回答「tail hedge 產品」層面的 naive vs complex，需要另一個 options / VIX futures 專題實驗。

## 產出檔案

- `research_naive_estimation_heavy_robustness.py`
- `research_naive_estimation_heavy_robustness_results.json`
- `fig_panel_a_single_asset.png`
- `fig_panel_b_multi_asset.png`
- `data/prices.csv`

## 重現

```bash
cd /Users/yhlai0911/Desktop/volpred-research
uv run python experiments/research_naive_estimation_heavy_robustness/research_naive_estimation_heavy_robustness.py
```
