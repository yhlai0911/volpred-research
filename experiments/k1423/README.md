# K1423 — 「打敗市場的超額報酬，是真 Alpha，還是還沒被命名的因子？」

**Status: COMPLETE**

## 核心發現（一句話先講）

美股半導體 ETF（SMH）對市場（SPY）做迴歸，會跑出年化約 **9.2% 的「alpha」（t=1.91，邊際顯著）** — 看似免費午餐。但在一個**乾淨的 disjoint leave-out proxy**（用一半半導體股建 sector factor、用另一半完全不重疊的股票當被解釋標的）上，加入一個**帶有平均報酬的 sector 共同因子**後，這個 alpha 點估計從 11.4%/yr 大幅縮到 **4.0%/yr 且不再顯著（t=0.85）**。證據**傾向（suggestive，非決定性）**支持：sector ETF 的 alpha 主要是**未命名的 sector 共同因子曝險**，不是真正的異常報酬。台股這邊 alpha 一開始就不顯著（t=0.53），沒有東西可被吸收；台股的 sector 凝聚度也較弱（PC1 解釋 46% vs 美股 63%）。

**誠實邊界**：美股的 mkt-only alpha 本身只到邊際顯著（t=1.88, p=0.060），且結果對 split 敏感（35 個 balanced split 的 residual-alpha 範圍 [-5.6%, 17.0%]，74% 的 split 不顯著）。因此結論是「suggestive」而非「decisive」，不過度宣稱「alpha 完全消失」。

## 動機與差異化

「Sector ETF 不選股、不擇時，卻打敗市場」這件事常被當成 alpha。本實驗用 **data-driven 的 PCA** 抽出半導體籃子的 latent common structure，檢驗這個 alpha 是不是只是「還沒被正式命名的 sector 因子曝險」。Meta 結論：**AI / PCA 找出的 latent structure 不必然是 alpha — 它常常正是讓 alpha 消失的那個遺漏變數。**

差異化（vs feed 既有文章，避免 narrative-arc 重複）：
- **vs mile_8a82b298**（泛論「控制因子後 alpha 差 5 倍」）：本實驗用 **PCA**（data-driven latent factor，非預設因子），並做**真正的 disjoint leave-out 識別**（不是把同一批股票塞回去）。
- **vs mile_f972159f / VT-alpha 系列**（K654 VT 不是 alpha，volatility-timing 角度）：本實驗角度完全不同 — **sector ETF 的橫斷面共同因子**，不是 volatility timing。
- **跨市場**：台股 vs 美股半導體 sector-factor 結構對比（PC1 解釋比例、alpha 吸收幅度），這是既有文章沒有的。
- 具體案例聚焦**半導體 sector**，不是泛論。

## 資料

- **來源**：yfinance（`auto_adjust=True`，日 log 報酬）。
- **期間**：2014-01-01 至 2026-06-01。
- **美股籃子**：NVDA, AMD, TSM, ASML, AMAT, MU, QCOM, AVGO（8 檔，全到齊，dropped=[]）。ETF baseline：SMH；市場 proxy：SPY。
- **台股籃子**：2330.TW, 2454.TW, 2303.TW, 3711.TW, 2379.TW, 3034.TW, 3037.TW, 2308.TW（8 檔，全到齊，dropped=[]）。市場 proxy：0050.TW；無純半導體 ETF → sector 用籃子自建。
- 報酬對齊用 inner join；缺值 drop（對齊階段 drop 數記在 `k1423_results.json` 的 `n_drops_in_alignment_stage1`）。
- **seed = 42**（np.random + PCA random_state 全固定）。

## 方法

這是 **contemporaneous risk-attribution 迴歸（sector_t ~ mkt_t [+ factor_t]），不是 forecast → 無 lookahead 問題**（README 明記，符合研究誠實）。alpha 年化 = 日 alpha × 252；t-stat 用 **Newey-West HAC 標準誤（lag=5）**（迴歸殘差有自相關）。

三階段 + 一個 robustness：

1. **PCA（描述）**：對每個市場的「全籃子」原始日報酬做標準化 + PCA，報告 PC1/PC2 解釋變異比例與 PC1 loadings（是否全同號 = 共同上下）。
2. **市場模型 baseline**：sector_y ~ α + β·mkt。預期 α 顯著為正。
3. **加入 sector factor — 兩種 attribution（關鍵）**：
   - **Variance attribution（市場中性 PC1）**：把各股先對市場 residualize，再 PCA 抽 PC1（z-space loadings 經 `w_raw = comp/std` back-transform 回 return space + unit-L2 normalize，避免單位混用），當第二個解釋變數。此因子近乎零均值且與截距正交 → **數學上只吸收 variance（R² 升、beta 顯著），不動 alpha LEVEL**。
   - **Premium attribution（帶 mean 的 leave-out sector-long）**：用 disjoint factor pool 的等權 long return（帶有 sector premium 的平均報酬）當解釋變數 → **這才是能吸收 alpha LEVEL 的測試**。
4. **Split robustness**：premium-attribution 在全部 35 個 balanced disjoint split 上重跑，報告 residual-alpha 的 mean/min/max 與不顯著比例。

### 為什麼要 disjoint leave-out（Codex review 修正史）

- **v1 bug**：把 raw standardized PCA score 直接當 regressor，且 sector proxy 由同一批股票組成 → 機械共線，R² 衝到 0.99、t 爆到 15-50、alpha 反而被擠大。Codex FAIL。
- **v2 修正**：因子改成市場中性 + return 單位，但發現市場中性零均值因子**不會移動 alpha LEVEL**（只吸收 variance）。Codex 指出：要吸收 alpha LEVEL 必須用**帶 mean 的 traded factor**。
- **v3 修正**：兩市場都改用**真正 disjoint 4/4 leave-out split**（factor pool 與 sector_y 完全不共享股票），SMH~SPY 降為單獨的 descriptive baseline（SMH 持有同批股，不能用於識別）；PCA factor 建構一致化（z→raw back-transform）；加 35-split robustness。Codex **CONDITIONAL_PASS**（機械共線已破除、PCA 一致性修對；唯一條件 = 結論寫成 suggestive 不可過度宣稱，已照辦）。

## 結果

| 指標 | 美股 (US) | 台股 (TW) |
|---|---|---|
| 全籃子 PC1 解釋變異 | 63.0% | 46.4% |
| 全籃子 PC2 解釋變異 | ~ | ~ |
| PC1 全同號（共同因子） | 是 | 是 |
| ETF baseline (SMH~SPY) α 年化 / t | 9.2% / 1.91 | — (無純半導體 ETF) |
| Leave-out proxy: Mkt only α / t / R² | 11.4% / 1.88 / 0.574 | 2.8% / 0.53 / 0.554 |
| +PC1 (variance attr) α / t / R² | 11.4% / 2.42* / 0.765 | 2.8% / 0.60 / 0.613 |
| +SectorLong (premium attr) α / t / R² | 4.0% / 0.85 / 0.761 | 0.8% / 0.16 / 0.597 |
| 35-split residual-α 範圍 | [-5.6%, 17.0%] | [-0.3%, 4.5%] |
| 35-split 不顯著比例 | 74% | 100% |

（* = |t| > 1.96。完整數字見 `k1423_results.json`。）

**解讀**：
- **Variance attribution（PC1）**：R² 大幅上升（US 0.57→0.77、TW 0.55→0.61）、PC1 beta 顯著 → 半導體籃子確實有強烈的共同因子；但 alpha LEVEL 完全不動（11.4%→11.4%）— 這是設計使然（零均值市場中性因子），它回答的是「波動有多少來自 sector 共動」，不是「alpha 是不是 sector premium」。
- **Premium attribution（leave-out sector-long）**：這才回答 alpha LEVEL。US alpha 從 11.4% 縮到 4.0% 且轉不顯著；TW 本就不顯著。
- **跨市場**：US sector 凝聚度（PC1 63%）明顯高於 TW（46%）；US 才有「看似 alpha」的現象，TW 沒有。

## 結論（誠實版）

Sector ETF 的「alpha」**傾向是未命名的 sector 共同因子曝險**，不是免費午餐 — 一旦把 data-driven 抽出的 sector 共同因子（帶有自身平均報酬）放進迴歸，截距的正向點估計就大幅縮小並失去顯著性。但這是 **suggestive 證據而非鐵證**：美股原本的 alpha 只到邊際顯著、結果對 split 敏感；台股則從頭就沒有顯著 alpha。

**Meta 結論**：PCA / AI 找到的 latent structure 不是 alpha 的證明，反而常常是「模型不完整」的證據 — 它正是那個一旦補進去就讓 alpha 消失的遺漏變數。「打敗市場」之前，先問自己有沒有把所有共同因子都命名完。

## 產出檔案

- `k1423.py`：完整可重現腳本（seed=42）。
- `k1423_results.json`：所有數字（PCA 解釋比例、loadings、三階段迴歸 α/t/R²、35-split robustness、台美對比、honest_conclusion）。
- `fig1_pca_explained_var.png`：台美 PC1/PC2 解釋變異對比。
- `fig2_alpha_before_after.png`：alpha 三階段（Mkt only / +PC1 / +SectorLong）台美 6 條 bar + t-stat。
- `fig3_pc1_loadings.png`：台美籃子 PC1 loadings（全同號 = 共同因子）。

## 防錯與限制

- **無 lookahead**：contemporaneous attribution，非預測；無 signal/return 時序錯位。
- **seed 全固定**（np.random.seed(42) + PCA(random_state=42)）。
- **HAC 推論限制**：t-stat 是 conditional on generated regressor，未修正第一階段 factor estimation error；屬 conditional inference，不宜當強結論（這也是結論寫 suggestive 的原因之一）。
- **Fama-French 未做**：台股 FF factors 不易取得，為維持台美對稱（symmetric）口徑，本實驗只用「市場模型 + PCA / sector-long factor」，不硬湊 FF（誠實註明）。
- 數據來源：yfinance（2026-06-08 抓取）。所有結論來自實際 `k1423_results.json`，無手改。

## Review

Codex CLI（gpt-5.4）三輪 review：v1 FAIL（機械共線 + PCA 單位錯位）→ v2 設計討論（variance vs premium attribution）→ v3 **CONDITIONAL_PASS**（兩 FAIL 已修，條件 = 結論寫 suggestive，已照辦）。
