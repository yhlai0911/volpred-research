---
experiment_id: K439
title: VRP 跨資產預測力測試：恐慌溢酬到底能預測誰的波動？
audience: general
length_zh: 1750
data_period: 2005-02-03 至 2026-03-23（IS 4509 日 + OOS 808 日）
oos_period: 2023-01-01 起
assets: SPY, QQQ, EEM, GLD, TLT
references:
  - K436（SPY VRP daily DM p=0.018, bootstrap p=0.000）
  - K430（VRP IS t=4.38 通過 Harvey 門檻）
  - Bollerslev, Tauchen, Zhou (2009) RFS — VRP predicts equity returns
  - Bekaert & Hoerova (2014) JoE — VRP decomposition
---

# VRP 跨資產預測力測試：恐慌溢酬到底能預測誰的波動？

## 一句話結論

**Variance Risk Premium（VRP，變異數風險溢酬）對股票類資產（SPY、QQQ）的未來波動具有顯著預測力，但對新興市場股票（EEM）、黃金（GLD）、長債（TLT）則無法擊敗純歷史波動 baseline。** 這個結果驗證了「VRP 是股票市場 fear premium 的指標」，而不是一個能 generalize 到所有資產類別的通用波動率因子。

## 為什麼要做這個實驗

VRP 是學術文獻裡少數同時被理論支持（Bollerslev-Tauchen-Zhou 2009, RFS）與實證確立（多篇 follow-up）的「能擊敗 random walk 的波動率因子」。它的定義很乾淨：

> **VRP_t = IV_t − RV_{t-22:t}**

其中 IV_t 是 t 日的隱含波動率（VIX），RV_{t-22:t} 是過去 22 個交易日（約一個月）的已實現波動率。直觀解讀：投資人在期權市場願意為「未來一個月的波動」多付多少（相對於最近一個月真的發生的波動）— 這個「多付」的部分就是 fear premium。

K436 已經在 SPY 上單獨驗證 VRP 的日頻預測力（DM p=0.018, bootstrap p=0.000）。但 SPY 是 S&P 500 的 ETF，VIX 也是基於 S&P 500 的選擇權算出來的 — 換句話說，K436 是「自家對自家」的測試。**真正的問題是：VRP 這個訊號到底是 SPY-specific 的，還是能 generalize 到其他資產？**

這個問題對實務有直接影響：
- **如果 VRP 能 generalize**：可以把 VRP 當成跨資產的 panel 因子，用單一訊號做多資產波動率擇時。
- **如果 VRP 是 SPY-specific**：那它本質上是 S&P 500 fear gauge，跨資產應用要有對應的 implied vol（GVZ for GLD、MOVE for TLT），而不是直接套 VIX。

## 實驗設計

### 資料來源

- **數據源**：yfinance（SPY、QQQ、EEM、GLD、TLT、^VIX）
- **樣本期**：2005-02-03 至 2026-03-23
- **In-sample**：4509 個交易日（用來估迴歸係數）
- **Out-of-sample**：807-808 個交易日（2023-01-01 起，用來公平比較預測誤差）
- **Bootstrap**：n=10000，block size=21（一個月）
- **實驗 ID**：K439

### 方法

對每個資產 i ∈ {SPY, QQQ, EEM, GLD, TLT}：

1. **Baseline 模型**：用過去 22 日 RV 預測下一日 |return|
   `|r_{t+1}| = α + β · RV_{t-22:t} + ε`

2. **VRP-augmented 模型**：把 VRP 加進去
   `|r_{t+1}| = α + β · RV_{t-22:t} + γ · VRP_t + ε`

3. **三項顯著性檢定**（10% 門檻；通過 ≥2 項算 SIGNIFICANT）：
   - **Diebold-Mariano 檢定（HAC 校正）**：兩模型 OOS MSE 是否顯著不同
   - **Block bootstrap p-value**：MSE 改善是否大於 random reshuffle
   - **Forecast encompassing test**：baseline 是否 encompass VRP 訊息

### Lookahead audit（重要）

**所有訊號嚴格用 t 之前的資訊預測 t+1**：
- VIX_t 是 t 日**收盤後可觀測**的 close price
- RV_{t-22:t} 是 t 日及之前 22 日的歷史已實現波動率
- VRP_t = VIX_t − RV_{t-22:t} 完全用 t 日及之前資訊
- 預測標的是 |r_{t+1}|（t+1 日的絕對報酬）

代碼在迴歸層面有明確的 t / t+1 切分，沒有用 t+1 資訊回頭計算 t 的訊號 — 這是 K1213 之後我們在所有 VRP 類實驗都做的標準動作。

### 設計限制（誠實揭露）

> **所有資產都用 VIX 當 implied vol proxy**。

VIX 本質是 SPY 的 implied volatility。對 QQQ、EEM、GLD、TLT，理論上應該用各自的 implied vol（VXN for QQQ、VXEEM for EEM、GVZ for GLD、MOVE for TLT），但這些指數在 yfinance 上沒辦法穩定取得長序列。所以 K439 對非 SPY 資產的「VRP」實際上是 **cross-asset fear spillover** measure，不是 asset-specific VRP。這個設計選擇後面會直接影響結果解讀。

## 主要結果

### 跨資產顯著性表

| 資產 | Corr(VIX, RV) | IS VRP t-stat | OOS MSE 改善 | DM p-value | Bootstrap p | Encompassing p | Verdict |
|------|---------------|---------------|--------------|------------|-------------|----------------|---------|
| SPY  | 0.872 | 10.33 | +14.99% | 0.0526 | 0.0813 | <0.0001 | **SIGNIFICANT (3/3)** |
| QQQ  | 0.820 | 9.32  | +8.72%  | 0.0523 | 0.0860 | <0.0001 | **SIGNIFICANT (3/3)** |
| EEM  | 0.780 | 5.76  | +1.42%  | 0.5625 | 0.5148 | 0.0103 | BORDERLINE (1/3) |
| GLD  | 0.507 | 4.19  | +0.53%  | 0.6122 | 0.6190 | 0.0763 | BORDERLINE (1/3) |
| TLT  | 0.623 | 6.38  | −1.28%  | 0.4199 | 0.4552 | 0.1827 | NOT SIGNIFICANT (0/3) |

### 怎麼讀這張表

**SPY / QQQ — 通過 3/3 檢定**：
- IS 階段，VRP 係數 t-stat 都遠超 Harvey (2017) 建議的 |t|≥3.0 門檻（SPY 10.33、QQQ 9.32）
- OOS MSE 改善有實際幅度（SPY +15%、QQQ +9%）
- DM 檢定 p≈0.052 在 10% 門檻通過、5% 門檻邊緣
- Bootstrap CI 95% 下界都 >0（SPY 0.0099、QQQ 0.0067）— 表示改善統計上不是 zero

**EEM — BORDERLINE**：IS 通過 Harvey t-stat 門檻（5.76），但 OOS DM/bootstrap 完全不顯著（p=0.56 / 0.51），改善幅度只有 +1.4%。Encompassing test 通過反映 EEM 還是與美股相關（VIX 飆時新興市場也跟著飆），但這個 spillover 太微弱不足以擊敗純歷史波動 baseline。

**GLD — BORDERLINE**：黃金與 VIX 的相關係數只有 0.507（五個資產裡最低），意味著 VIX 並不是黃金的好 fear proxy。OOS 改善 0.5%，DM p=0.61 — 統計上跟 baseline 沒差。

**TLT — NOT SIGNIFICANT**：長債最有趣。它的 IS VRP t-stat 高達 6.38（樣本內擬合很漂亮），但 **OOS MSE 改善 −1.28%**（VRP-augmented 反而變差）。這是教科書級的 in-sample overfit 案例 — IS 看起來顯著的訊號完全沒有 OOS 預測力，DM 檢定（p=0.42）和 bootstrap（p=0.46）都拒絕「有改善」。

## 機制解讀：為什麼 VRP 只對股票類有效？

把第 2 欄（Corr(VIX, RV)）和最後一欄（verdict）擺在一起看，模式很清楚：

> **VIX 跟資產 RV 的相關係數越高，VIX-based VRP 對該資產的預測力越強。**

- SPY 0.872 → SIGNIFICANT
- QQQ 0.820 → SIGNIFICANT
- EEM 0.780 → BORDERLINE
- TLT 0.623 → NOT SIGNIFICANT
- GLD 0.507 → BORDERLINE / 統計上 null

這個對應關係是「設計上的限制」直接造成的。VIX 只觀測美股 fear，當資產與美股高度相關（SPY、QQQ），VIX 是好的 implied vol proxy，VRP 訊號就有效；當資產有自己的動態（黃金的 inflation hedge、長債的 duration risk），VIX 就只能 capture 微弱的 spillover，VRP 就失去預測力。

換言之，這個結果不是「VRP 在跨資產 fail」，而是「**VIX 不是這些資產的 implied vol，所以用它算的 VRP 不該叫 VRP**」。要真正測試 VRP 在 GLD 是否有預測力，必須用 GVZ 重做；要測 TLT，必須用 MOVE 重做。

## 對實務交易者的啟示

1. **股票類波動率擇時可以用 VRP**：SPY / QQQ 上的 OOS MSE 改善 +15% / +9% 是有 economic significance 的幅度，搭配 K436 的日頻顯著結論，這是條穩固的訊號。

2. **跨資產不能直接套 VIX-VRP**：想做多資產波動率因子模型，必須用 asset-specific implied vol（GVZ、MOVE、VXEEM）。直接拿 VIX 套到 GLD/TLT 會得到 noise。

3. **長債的 IS-OOS 反差是重要警訊**：TLT 的 IS t=6.38 / OOS −1.28% MSE 改善是現代 backtest 流程裡最常見的失敗模式 — 樣本內看起來金光閃閃的訊號，OOS 完全 break。任何看 IS 結果就上線的策略都該被這個案例 calibrate。

4. **Borderline 結果不是「失敗」，是訊息**：EEM / GLD 的 borderline 告訴我們 fear spillover 確實存在但太弱，未來如果加上 GVZ / VXEEM 等 asset-specific implied vol，可能就能 push 過顯著門檻 — 這是 K439 留給後續實驗的 actionable 待辦。

## 後續研究方向

- **K440+（規劃中）**：用 GVZ 重測 GLD VRP、用 MOVE 重測 TLT VRP，分離「設計 artifact」與「真實 VRP 跨資產有效性」。
- **VRP 月頻測試**：日頻 |return| 太 noisy，VRP 是慢變量，月頻或季頻 horizon 應更顯著。
- **Crisis-period 子樣本**：OOS 期 (2023-2025) 相對平靜，限制了 stress regime 推論。要擴 IS 期或加 2008/2020 子樣本看 VRP 是否在恐慌期才特別有效。

## 結論

K439 用 5 資產 × 3 統計檢定的標準化框架，誠實回答了「VRP 能不能跨資產 generalize」這個問題：

> **以 VIX 為 implied vol proxy 時，VRP 預測力侷限於股票類（SPY、QQQ）— 不是因為 VRP 概念失敗，而是因為 VIX 只 capture S&P 500 的 fear。**

這個結論同時 (a) 確認 K436 的 SPY 結果在 QQQ 上 robust、(b) 提醒實務 user 不要直接套用 VIX-VRP 到非美股資產、(c) 為下一輪 GVZ / MOVE based VRP 實驗鋪好設計理由。

研究的價值不只在「找到顯著結果」，也在「誠實 document 訊號的邊界」。K439 屬於後者。

## 資料來源

- **實驗檔案**：`experiments/k439/k439_cross_asset_vrp_results.json`
- **實驗 ID**：K439（Cross-Asset VRP Predictability Test）
- **時間戳**：2026-03-25
- **資料來源**：yfinance（SPY、QQQ、EEM、GLD、TLT、^VIX）日頻收盤價
- **樣本期**：2005-02-03 至 2026-03-23（5316-5317 個交易日）
- **OOS 起點**：2023-01-01（每資產 807-808 日）
- **IS 樣本**：4509 日（每資產一致）
- **Bootstrap**：n=10000，block size=21
- **相關 K**：K436（SPY VRP 日頻顯著）、K430（VRP IS t=4.38 通過 Harvey 門檻）

## 圖表

![跨資產 VRP 預測力：OOS MSE 改善百分比](experiments/k439/k439_mse_improvement.png)

![三項檢定的顯著性對比](experiments/k439/k439_pvalues_3tests.png)

![VIX 與各資產實現波動率相關係數](experiments/k439/k439_corr_vix_rv.png)
