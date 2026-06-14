# K1499 — BDC（私募信貸影子）壓力作為公開市場波動的多期領先訊號

**Verdict: PARTIAL**

- **BDC 籃已實現波動壓力 = 純大盤 beta**：控制 SPY 波動後，對 HYG/KRE/IWM 三個標的的未來已實現波動都沒有增量預測力（NULL）。
- **唯一倖存訊號 = NAV 折價代理（BIZD 報酬 − HYG 報酬）**：控制 SPY 波動後，仍對 **HYG 的 5 日未來波動**有正向增量（HAC t=3.18，|t|>3），但隨期程衰減（h10 t=2.57、h21 不顯著），且只在 HYG 出現、KRE/IWM 無。
- 這與 K1332 的「HYG 窄 PASS」一致——以**不同方法（forward RV multi-horizon + NAV 折價 proxy）獨立佐證**了同一個方向，但證據範圍很窄（單一標的、單一短期程）。

## 動機（differentiation）

2025-26 私募信貸（private credit / shadow banking）成為金融穩定熱點：FSB 2026-05 發布《Vulnerabilities in Private Credit》報告（違約率上升、估值不透明、槓桿與銀行-非銀行互聯），BCRED 等非交易型 BDC 出現贖回壓力。私募信貸的真實 loan tape / NAV marks 無免費資料，但**上市 BDC（Business Development Company）股價**是私募信貸曝險的公開、免費代理。

研究問題：**上市 BDC 籃的壓力，能不能當「私募信貸危機」的領先波動訊號，預測高收益債（HYG）、區域銀行（KRE）、小型股（IWM）的未來波動？還是它只是大盤 beta？**

### 與 K1332 的明確區隔（非重複）

本實驗是 K1332 的**多期 forward-RV 延伸與穩健性檢查**，不是重新發現。差異：

| 面向 | K1332 | K1499（本實驗） |
|---|---|---|
| 預測標的 | 1 日 r²（squared return），rolling OOS QLIKE | **未來已實現波動 RV（t+1..t+21 多期）** |
| BDC 籃 | 較舊（MAIN/GBDC/HTGC + ARCC/PSEC） | **較新大型（ARCC/BXSL/OBDC/FSK/PSEC）+ BIZD** |
| 折溢價代理 | pc-vs-LQD（投資級） | **BIZD 報酬 − HYG 報酬（NAV 折價 stand-in）** |
| 控制 | own vol | **own vol + SPY vol 增量控制 + SPY placebo** |
| 方法 | OOS QLIKE + DM | **lead-lag 相關矩陣 + HAC 迴歸 + event-study 路徑** |
| 結論 | PASS_NARROW_CREDIT_ONLY（BKLN/HYG） | **PARTIAL（BDC-RV 純 beta；NAV 折價 proxy 對 HYG 5d 增量倖存）** |

K1332 的窄 PASS 是在 1 日 r² 標的 + 不同 beta 控制下成立；K1499 問的是「在 forward RV 多期 + 較嚴的大盤控制下，這個領先關係還在嗎」——答案是：**BDC 籃的整體波動壓力是 beta；但 NAV 折價代理對 HYG 短期程仍倖存，與 K1332 的 HYG 結論一致。**

## 資料（全免費 yfinance, auto-adjusted close）

- BDC 籃：ARCC（2005-）、BXSL（2021-10）、OBDC（2019-07）、FSK（2014-04）、PSEC（2005-）
- BDC ETF 代理：BIZD（2013-02）
- 被預測對象：HYG（高收益債）、KRE（區域銀行）、IWM（小型股）
- 大盤對照／控制：SPY
- 期間：各 ticker 最長可得 → 2026-06。注意 BXSL/OBDC 上市較晚，等權籃在早期由較少成員構成（已記錄於 download_diagnostics）。

## 方法（嚴守研究誠實）

1. **描述統計 + 資料診斷先行**：每 ticker 的上市日、樣本數、年化波動、偏態/峰度（見 results.json `descriptive_stats` / `download_diagnostics`）。
2. **BDC 壓力 proxy**：
   - 主訊號 = 等權 BDC 籃日報酬的 21d 已實現波動，expanding z-score 標準化。
   - 次訊號 = NAV 折價代理 = −(BIZD 報酬 − HYG 報酬) 的 21d 累積（明確標為 proxy；折價擴大 = 壓力升）。
3. **Forward RV 標的**：未來 t+1..t+h（h=5,10,21）日報酬的 std。1 日期排除（單點 std 無定義；1 日通道由 K1332 r² 與本文 event-study |ret| 路徑覆蓋）。
4. **Lookahead guard（最高優先）**：所有訊號 `.shift(1)`；forward RV 用 `rolling(h).std().shift(-h)`，嚴格只取 signal date 之後的報酬；expanding 標準化不偷看未來。
5. **HAC 迴歸（Newey-West）**：重疊視窗 → `maxlags = h+5` 修正自相關。三個模型：
   - Model A：BDC 壓力 + own vol
   - Model B：BDC 壓力 + **SPY vol** + own vol（增量檢定）
   - Model C：NAV 折價 proxy + SPY vol + own vol
6. **SPY placebo**：BDC 壓力是否同樣預測 SPY 波動？若是 → 訊號主要是大盤 beta。
7. **Event study**：top-decile（90 pct）BDC 壓力日後，HYG/KRE/IWM 未來 |報酬| 路徑（t+1..t+21），2000 次 bootstrap CI（seed=42）。
8. **門檻**：重疊視窗下用 Harvey 式 |t|>3（非 1.96）；區分統計顯著 vs 經濟顯著。

## 預期

若 BDC 壓力含私募信貸特有資訊，控制 SPY vol 後仍應對 credit-sensitive 標的（HYG/KRE）有正向增量。若控制後消失，則它只是大盤 beta。

## 結論（PARTIAL，誠實報告）

| 證據 | 結果 |
|---|---|
| Lead-lag 相關（raw, BDC-RV） | 高：0.49–0.55（h5/10/21，全標的） |
| Model A（BDC-RV + own vol） | KRE/IWM t≈2.1（未達 \|t\|>3）；HYG 不顯著 |
| **Model B（BDC-RV 加 SPY vol）** | **BDC-RV 係數塌到 ≈0 / 微負（\|t\|<2），三標的全 NULL — SPY vol 吸收全部訊號** |
| **Model C（NAV 折價 proxy 加 SPY vol）** | **HYG h5 t=3.18（>3，正向）倖存；h10 t=2.57、h21 不顯著；KRE/IWM 全不顯著** |
| SPY placebo | BDC-RV 弱預測 SPY vol（t≈1.3–1.6）→ 佐證 BDC-RV 是 beta |
| Event study | top-decile 壓力後未來 \|報酬\| 仍 2.0–2.9x（p<0.001），但**無 beta 控制**，反映高波動 regime |

**機制**：BDC 籃的整體已實現波動（BDC-RV）與未來波動的高 raw 相關，幾乎全來自共同的大盤波動 regime——控制 SPY 已實現波動後增量預測力消失（純 beta）。但**相對訊號**（BIZD 相對 HYG 的折價 proxy）剝離了共同 beta，對 HYG 自身的 5 日未來波動仍保留小幅增量（t=3.18），隨期程衰減、且不外溢到 KRE/IWM。Event study 的 2-3x 放大是 unconditional 的——壓力日本身就是高波動日。

**結論強度限制**：
- 這是免費公開代理（BDC 股價）的結果，不能延伸成「私募信貸對公開市場（無）外溢」的一般性結論。真實 loan tape / NAV marks / 非交易型 BDC 贖回流仍不可得（FSB 點名的資料缺口）。
- 倖存訊號很窄：**單一標的（HYG）× 單一短期程（5d）× 單一 proxy（NAV 折價）**，且係數小、隨期程衰減。屬「方向性一致、經濟量級有限」，不足以宣稱穩健的可交易領先訊號。
- 與 K1332 的關係：K1499 以獨立方法佐證了 K1332 的「HYG 方向」，同時釐清了**整體 BDC 波動是 beta、唯有相對折價 proxy 帶 credit-specific 增量**——這是對 K1332 的一個 mechanism refinement，不是推翻。

## 檔案

- `k1499.py` — 可重跑（yfinance deterministic，seed=42）
- `k1499_results.json` — verdict + 描述統計 + lead-lag + HAC（A/B/C 三模型）+ SPY placebo + event study + research_honesty_notes
- `k1499_lead_lag_corr.png` — 各標的 × 各期領先相關長條圖
- `k1499_event_study_path.png` — top-decile 壓力後未來 |報酬| 路徑

## 文獻

- FSB (2026), *Report on Vulnerabilities in Private Credit*
- IMF GFSR (2024), *The Rise and Risks of Private Credit*
- VolPred K1332（內部 prior：1d r² 上 BKLN/HYG 窄 PASS）
