# K1669 — 動能因子崩盤：動態 vs 常數波動率縮放（MDD / 尾部聚焦）

## 動機與差異化
動能（momentum）因子有著名的「動能崩盤（momentum crash）」：市場由熊轉牛的劇烈反轉期
（2009-03、2020-03），過去輸家暴漲、贏家暴跌，動能組合承受巨大回撤。文獻兩大處方：

- **Barroso & Santa-Clara (2015, JFE)「Momentum has its moments」**：**常數目標波動率縮放**
  （用過去已實現波動率把組合曝險 scale 到固定 vol 目標），大幅改善 Sharpe 與尾部。
- **Daniel & Moskowitz (2016, JFE)「Momentum crashes」**：崩盤可預測（熊市 + 反彈時），
  提出**動態縮放**（依熊市 / 波動率狀態調整曝險）。

**本實驗差異化**：在**同一組動能組合、同一 OOS 期間、同一縮放慣例**下，公平比較
(a) 無縮放 baseline、(b) 常數波動率目標縮放（Barroso 式）、(c) 波動率狀態動態縮放
（Daniel-Moskowitz 精神的簡化：高 vol expanding 分位 regime 額外 haircut）。
**指標聚焦 MDD 與左尾（CVaR(5%) / 最差月），而非只看 Sharpe**，並刻意把「槓桿水準效應」
與「分佈形狀效應」分開（Panel A vs Panel B），這是文獻常混淆之處。

## 資料與樣本
- 資料源：`yfinance` auto_adjust 收盤價（快取於 `data/prices.csv`，2004-01-02 ~ 2026-07-09）。
- **組合 1：MTUM ETF**（iShares MSCI USA Momentum Factor，2013-04-19 起，n=3,325 日）—— 現成
  **long-only 多元動能**組合 proxy。
- **組合 2：自建橫截面類股動能**（2004-03-01 ~ 2026-07-09，n=5,625 日）：universe = 10 檔
  SPDR 類股 ETF（XLK/XLF/XLE/XLV/XLI/XLY/XLP/XLU/XLB/XLRE，XLRE 2015 起動態納入）。
  每月依過去 **12-1 月報酬**（跳過最近 1 月）排序，做多前 tertile、做空後 tertile
  （**long-short**）+ 只做多前 tertile（**long-only**）兩版。月頻 rebalance。
  涵蓋 **2008-09 動能崩盤 + 2020-03 COVID + 2022 熊市**。

## 方法與 Lag 慣例（研究誠實原則落地）
- **日頻縮放槓桿一律 lookahead-safe**：t 期槓桿 = f(σ̂_{t-1})，程式碼 `realized_vol().shift(1)`
  （`build_leverage`）。**baseline 與縮放策略同 lag 慣例**（baseline 槓桿恆 = 1，日期完全相同）。
- **月頻動能訊號**：t 月持倉權重 = t-1 月底的 12-1 動能訊號（權重 `.shift(1)`，`build_sector_momentum`）。
- **常數 vol 縮放**：inverse-vol `lev = σ_ref / σ̂_{t-1}`，`σ_ref` = **expanding median(σ̂)**
  使平均槓桿 ≈ 1（lookahead-safe，只用歷史），槓桿 cap = **2.0**。
- **動態 vol 縮放**：`lev = (σ_ref/σ̂_{t-1}) × haircut`，當 σ̂_{t-1} 落在其 **expanding 分位 > 0.80**
  （top-quintile 高 vol regime）時 haircut = 0.5（曝險腰斬），cap 2.0。門檻 0.80/0.5 為
  **ex-ante 預先指定、非 tuning**（DM「崩盤群聚於高 vol 反彈」精神的最低自由度實作）。
- **已實現波動率窗**：primary = **126 日**（Barroso 6 個月）；robustness = 21 / 63 日。
- **公平比較兩面板**：
  - **Panel A（primary，完全 ex-ante）**：不含任何 ex-post 資訊，報實際槓桿下的絕對指標。
  - **Panel B（robustness，risk-matched）**：各策略用**單一 ex-post scalar 均勻縮放**到 baseline
    全期 vol（僅 level 對齊、無 timing 資訊）。這是文獻標準的**等風險比較**，用來隔離分佈「形狀」，
    避免「跑較低槓桿 → 當然回撤較小」的假象。
- **交易成本 robustness**：10 bps × turnover（槓桿變動 + 底層月頻 rebalance 換手），三策略同一 bps。
- **統計檢定**：Sharpe 差異用 circular block bootstrap（block=21、reps=5,000、**seed=42**）。
  MDD / CVaR / 最差月為主 framing，報 point estimate + 數字表，不看圖下結論。
- rf = 0（三策略一致，比較公平）。

## 主要結果（數字全部對回 `k1669_results.json`）

### 表 1 — Panel A（ex-ante，實際槓桿）vs Panel B（risk-matched 等全期 vol）

| 組合 / 策略 | Panel A Sharpe | Panel A MDD | Panel A CVaR5% | Panel A annVol | **Panel B MDD** | **Panel B CVaR5%** | **Panel B worstM** |
|---|--:|--:|--:|--:|--:|--:|--:|
| **MTUM** baseline | 0.857 | −34.1% | −3.07% | 20.0% | −34.1% | −3.07% | −12.7% |
| MTUM const_vol | 0.844 | −25.0% | −2.46% | 15.8% | −30.9% | −3.11% | −12.6% |
| MTUM dynamic_vol | 0.769 | −26.1% | −2.32% | 14.4% | −35.3% | −3.22% | −13.8% |
| **Sector L-S** baseline | −0.093 | −55.3% | −2.37% | 15.3% | −55.3% | −2.37% | −16.0% |
| Sector L-S const_vol | −0.062 | −39.5% | −1.71% | 11.5% | −50.6% | −2.27% | −11.6% |
| Sector L-S dynamic_vol | −0.027 | −34.9% | −1.60% | 10.7% | −48.3% | −2.29% | −11.9% |
| **Sector L-only** baseline | 0.605 | −47.6% | −2.91% | 19.0% | −47.6% | −2.91% | −18.4% |
| Sector L-only const_vol | 0.658 | −26.3% | −2.37% | 15.1% | −32.1% | −2.97% | −15.1% |
| Sector L-only dynamic_vol | 0.649 | −26.1% | −2.28% | 14.4% | −33.5% | −3.01% | −15.9% |

### 表 2 — 崩盤窗口內報酬（cum return / 該窗 MDD）
| 組合 / 策略 | 2009 動能崩盤 | COVID 2020-03 | 2022 熊市 |
|---|--:|--:|--:|
| MTUM baseline | — | −12.8% / DD −33.8% | −18.3% / DD −28.2% |
| MTUM const_vol | — | −16.6% / DD −24.2% | −13.1% / DD −19.0% |
| MTUM dynamic_vol | — | −15.8% / **DD −19.5%** | −11.7% / **DD −15.2%** |
| Sector L-S baseline | −24.5% / DD −34.9% | +2.1% | +28.0% |
| Sector L-S const_vol | −7.5% / DD −11.7% | +7.5% | +20.3% |
| Sector L-S dynamic_vol | **−3.8% / DD −6.0%** | +11.2% | +19.0% |

### bootstrap ΔSharpe（Panel A，seed=42, reps=5000, block=21）
| 組合 | const − base | dyn − base | dyn − const |
|---|--:|--:|--:|
| MTUM | −0.013 (p=0.90) | −0.088 (p=0.52) | −0.075 |
| Sector L-S | +0.031 (p=0.71) | +0.066 (p=0.55) | +0.035 |
| Sector L-only | +0.051 (p=0.49) | +0.042 (p=0.64) | −0.009 |

**所有 ΔSharpe 皆不顯著（全部 p>0.05；9 個兩兩比較 p 值範圍 0.196–0.896，最小 p≈0.196 出現在 MTUM dynamic−const）。** Sharpe > 2× baseline 情況不存在（已排除 lookahead/槓桿 bug）。

## 誠實結論

1. **「vol scaling 大幅改善 MDD / 尾部」大部分是槓桿水準效應，不是分佈形狀改善。**
   Panel A 看似亮眼（MTUM MDD −34%→−25%、Sector L-only −48%→−26%），但那是因為縮放策略
   **實際跑較低平均槓桿**（annVol 20%→14-16%）。一旦 **risk-match 到等全期 vol（Panel B）**，
   改善大幅縮水甚至消失：MTUM 的 MDD 只 −34.1%→−30.9%（const）、dynamic 反而 −35.3% 略差，
   CVaR / 最差月在 MTUM 皆**未改善或微幅變差**。→ 對 **long-only 多元動能 ETF（MTUM）**，
   等風險下 vol scaling **不是尾部 free lunch**。

2. **真正的機制在「崩盤窗口內」成立，且集中於真正 crash-prone 的 long-short 動能。**
   自建類股 **L-S 在 2009 動能崩盤**：baseline −24.5%（窗內 DD −34.9%）→ dynamic **−3.8%
   （DD −6.0%）**；MTUM COVID 窗 DD −33.8%→−19.5%、2022 熊市 DD −28.2%→−15.2%。縮放確實在
   vol 飆升期 de-lever、少賠。這與 Barroso / DM 一致——**但效果集中在崩盤事件，攤到全期後
   （尤其 risk-matched）就被稀釋**。

3. **動態（vol 分位）縮放 ≈ 常數縮放，無統計顯著優勢。** dynamic 在崩盤窗口（2009、COVID）
   給邊際額外防護（L-S 2009 DD −11.7%→−6.0%），但在非崩盤期略拖累，Panel B 未一致贏過 const，
   bootstrap ΔSharpe(dyn − const) 不顯著。**低自由度的 vol-quantile 動態規則，在此樣本無法宣稱
   優於單純常數縮放。**

4. **Sharpe 面全 null**：三組合、三兩兩比較（共 9 個）的 bootstrap ΔSharpe 全部 p>0.05（範圍 0.196–0.896，最小 MTUM dyn−const 0.196、Sector L-S dyn−const 0.354）。vol scaling 在此樣本
   **沒有顯著改善風險調整報酬**；它改變的是**回撤/尾部的時間分佈**（把大回撤攤平），代價是可能
   犧牲一點極端上行。

5. **次要發現（robustness）**：**較短 vol 窗（21/63 日）反應更快**，在 MTUM 上 Panel A Sharpe
   反而升到 0.90（vs 126 日的 0.844）、MDD 也壓更低（−34%→−17% dynamic/21d）。→ 縮放的價值對
   **估計窗反應速度敏感**；126 日 Barroso 窗較遲鈍。10 bps 成本幾乎不改變任何結論（Sharpe 變動 <0.03）。

**一句話**：在此樣本，**point estimates 顯示**波動率縮放的尾部好處**主要來自「少冒險」而非「聰明擇時」**；等風險比較下
只剩溫和、且**僅對真正 crash-prone 的 long-short 動能、且在崩盤事件當下**才明顯的改善；
動態 vs 常數縮放無顯著差別。**不宣稱 vol scaling 是普適的動能尾部解方（honest null-leaning）。**

> **推論範圍註記（Codex review CONDITIONAL_PASS 後補）**：bootstrap block CI 只建立在 **ΔSharpe** 上；
> MDD / CVaR / 最差月 / 崩盤窗改善均為 **point estimate（無 CI）**，故「尾部好處來自少冒險」是
> point-estimate 觀察而非顯著性結論。另：自建類股組合前 250 交易日為 0-return burn-in（已納入全期指標，
> 屬保守納入）；const/dynamic 因首個 σ_lag 無效各少 1 天（baseline 5625 vs 縮放 5624 日），對全期統計量影響可忽略。

## 檔案
- `k1669.py` — 主腳本（資料、組合建構、縮放引擎、指標、bootstrap、繪圖、原子寫 JSON）
- `k1669_results.json` — 三組合 × 三策略 × Panel A/B/成本 + 崩盤窗 + bootstrap + robustness
- `figs/k1669_mtum_cum_dd.png` — MTUM 三策略累積淨值 + 回撤（risk-matched，崩盤窗陰影）
- `figs/k1669_sector_ls_cum_dd.png` — 自建類股 L-S 三策略累積淨值 + 回撤（涵蓋 2008-09）
- `data/prices.csv` — 價格快取（復現用）

## 限制與後續
- 自建類股動能 universe 僅 10 檔 ETF，橫截面動能較股票層級 WML 弱（L-S baseline Sharpe 為負），
  是 crash 機制的**弱代理**；真正的股票層級 WML long-short 崩盤更劇烈，效果或更強（需個股資料）。
- 動態規則刻意低自由度（單一 vol 分位門檻）以避免 overfitting；完整 DM 實作會再加**熊市狀態
  條件**（市場 < 過去 N 月 MA）與條件式做多輸家，本實驗未納入。
- 縮放的 σ_target level 已用 expanding median 中性化；level-match 為單一 ex-post scalar（無 timing
  lookahead），Panel A 已提供完全 ex-ante 對照。
