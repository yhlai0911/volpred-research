---
paths:
  - "experiments/**"
  - "paper/**"
  - "storage/**"
  - "research_program.md"
  - "scripts/daily_update.py"
  - "scripts/evaluate_new_strategy.py"
  - "scripts/recalc_metrics.py"
---

# VolPred 研究方法論規範

**原位於 `research_program.md` line 9-130，2026-04-18 搬到此處作為 Claude 觸發實驗 / 論文 / 策略操作時自動載入的 rule 檔。**

研究/實驗/策略實作必守以下 9 節。違反任何一節的結果應標記為 preliminary / unreliable，不可作為結論。CLAUDE.md §6b 等高層引用也指向此檔。

## 1. 統計有效性（最重要，違反即無效）

| 項目 | 最低要求 | 建議 | 依據 |
|------|---------|------|------|
| GARCH 估計 window | ≥500 | ≥2000 | Hwang & Valls Pereira (2006): w<500 persistence bias >5% |
| OOS 評估期間 | ≥252 天 | ≥504 天 | 至少 1 年才能涵蓋不同 regime |
| DM test 樣本 | ≥200 | ≥500 | t-test 漸近分配需要足夠樣本 |
| Cross-sectional 測試 | ≥7 資產 | ≥15 | N<7 的 Spearman 很不穩定 |
| Bootstrap | ≥1000 reps | ≥5000 | <1000 CI 不精確 |
| Harvey (2016) threshold | t>3.0 | — | 多重檢定下 t>1.96 不夠 |
| Sharpe CI | SE ≈ 1/√N_years | — | 19 年 SE=0.23，差異<0.1 不顯著 |

## 2. 模型比較公平性標準（2026-03-31 建立，K777/K778 教訓）

**不同類型波動率模型（GARCH/MEM/HAR）預測不同 target（σ²/|r|/RV）。比較必須公平。**

| 評估層次 | 方法 | 為什麼需要 | 依據 |
|---------|------|----------|------|
| **各自最佳** | 每個模型在原生 target 評估 | 展示各自天花板 | — |
| **統一 proxy-robust** | QLIKE on r²（squared return） | r² 是 σ² 的無偏估計，排名有理論保證 | Patton (2011) |
| **分配無關** | Spearman rank correlation | 不需要任何轉換或分配假設 | — |
| **多模型控制** | MCS（Model Confidence Set） | 控制 data snooping，找不可區分最佳集 | Hansen, Lunde & Nason (2011) |
| **經濟價值** | 策略 Sharpe/MDD/Utility | 預測好 ≠ 交易好（K770b 教訓）| — |
| **高頻標準**（若有 5-min） | QLIKE on RV | 最精確的真實 vol proxy | Hansen & Lunde (2005) |

**每次模型比較實驗必須至少包含前 3 層。不可只報告對自己有利的 target。**
**MEM 可直接建模 r²（不需轉換）——與 GARCH 在相同 σ² 空間公平比較。**
**K782 教訓：Proxy 比模型更重要——HAR 在 |r| 目標 DM=-15.45（K530），但在 r² 目標全輸 GJR。**

## 3. 經濟顯著性評估（VaR/ES）

**不同模型預測不同東西，計算 VaR 時必須做正確的分配轉換，不可直接用預測值當 VaR：**

| 模型 | 原生預測 | → VaR 轉換 | 注意 |
|------|---------|-----------|------|
| GARCH/GJR | σ² | VaR = σ × z_α | z_α 取決於創新分配（Normal/Student-t/Skewed-t）|
| MEM(\|r\|) | E[\|r\|] | σ = E[\|r\|] / C_gamma → VaR | C 來自 Gamma 分配，非 √(2/π) |
| MEM(r²) | E[r²] | σ = √E[r²] → VaR | Gamma 創新 |
| HAR-RV | E[RV] | σ = √RV，需 HAR 殘差分配 | log-normal 或 F |

- Backtesting: Kupiec + Christoffersen + Basel traffic light
- K768 Conformal VaR: model-agnostic 後校準（避開分配假設）

## 4. 多頻率研究約束

| 頻率 | 最低 OOS obs | 適合模型 | 不適合模型 | 資料年限需求 |
|------|------------|---------|-----------|------------|
| 日頻 | ≥252 | GARCH, EWMA, HAR | — | 8+ 年 |
| 週頻 | ≥104 (2yr) | EWMA, rolling std, GARCH | — | 10+ 年 |
| 月頻 | ≥60 (5yr) | EWMA, rolling std, regime | GARCH (收斂不穩) | 20+ 年 |
| 季頻 | ≥20 (5yr) | rolling std, regime | GARCH, HAR | 30+ 年 |
| 年頻 | ≥10 | descriptive only | 所有參數模型 | 50+ 年 |

## 5. 跨資產假日處理

- 多資產投組中若某資產無當日價格（假日），使用**前一交易日價格** forward-fill
- 假日資產的當日 return = 0（非交易日不計入報酬）
- 不可混用不同市場的交易日期——各市場用自己的 return，合併時 ffill 價格
- `DataManager.get_price_data()` 預設已做 ffill，但計算 return 時需額外檢查

**歷史教訓**：
- w=252 的 GARCH 有 persistence bias -3%（M1 發現）
- w=504 仍有偏誤，w=2000 近乎無偏（M4 驗證）
- N=7 的 Spearman ρ=1.000 看似完美但 LOO 後仍然 1.000 才可信（N95 驗證）
- 模擬的 options P&L（N178-N180）因缺乏真實數據而完全不可靠

## 6. 資料期間

- **OOS 期間（主）**: 2023-01-01 ~ 2024-12-31
- **OOS 期間（驗證）**: 2025-01-01 ~ 2026-03-31（R8 確認 15 個月驗證通過）
- **OOS 期間（高波動）**: 2022-01-01 ~ 2023-12-31
- **評估獲利期間**：2025-01-01 ~ 2026-03-21（隨時間延伸）
- **策略評估 COMMON_START**：2023-01-04（新策略必須從此日期比較，見 `evaluate_new_strategy.py`）
- **Rolling window 預設 2000**（w=504 僅在特殊情況使用，gamma sign invariant to window）
- ⚠️ **K783/K783b 結論**：expanding window 在 SPY 勝 w=2000 但在 QQQ 反向（小 window 勝）。**最優 window 因資產而異，w=2000 仍是合理通用預設。**
- 5-min 數據：SPY / 0050.TW 由 `collect_5min_data.py` 自動收集（`collect_us_data.py` 觸發）

## 7. 評估指標

- **統計性**：QLIKE (主), MSE, MAE, HMSE, Mincer-Zarnowitz R², DM test, MCS, GW test
- **風險管理**：Trinity test (Kupiec+CC+DQ), Fissler-Ziegel, Acerbi-Szekely ES, Basel traffic light
- **經濟性**：Sharpe (Harvey t>3), MDD (bootstrap p<0.001), Calmar, Sortino, CRRA utility, CE return, Net Sharpe (after TX), Turnover
- **跨模型**：CCS Score, FDR audit, Cross-OOS 5 periods, Weight StdΔw
- 每個實驗必須 re-estimate each window（no lookahead）

## 8. 研究多元化原則

**不要停留在模型舒適區。** 已驗證的結論（VIX sufficiency 23 次、50/50 不可動搖 8 次）不需要繼續堆積 null results。研究應同時在兩條軸推進：

**漸進式延伸（從已知出發）**
- 從現有面向自然衍生新問題
- 用新數據重新驗證舊結論
- 把已知方法應用到新資產/新市場

**跳躍式探索（進入未知領域）**
- **每個 session 至少 1 個「完全不同方向」的實驗**
- 不同領域的模型：NLP 情緒分析、替代數據（衛星/網路流量）、圖神經網路、因果推論
- 不同資產生態：加密 DeFi 協議、私募市場、碳權交易、大宗商品指數
- 不同研究方法論：行為金融實驗設計、市場微結構（order flow）、網絡/傳染模型、agent-based simulation
- 不同應用場景：ESG 整合波動率、氣候風險定價、地緣政治事件驅動策略
- 不同視角：投資人行為偏誤利用、制度摩擦套利、監管變化影響

**判斷「是否在舒適區」的檢查清單**
- [ ] 這個實驗是否只是「換一個 overlay 測 VT」？→ 可能在舒適區
- [ ] 這個模型/方法是否已經在其他實驗中用過？→ 考慮全新方法
- [ ] 預期結果是否又是一個 null result？→ 如果連續 3 個 null，換方向
- [ ] 這個問題能否用完全不同的方法回答？→ 嘗試不同方法論

## 9. 研究主題來源（必須多元）

| 來源 | 頻率 | 做法 | 寫入位置 |
|------|------|------|---------|
| **學術前沿文獻檢索** | 每 session 至少 1 次 | **先讀 `storage/research/arxiv_candidates.json`**（週度 cron `arxiv_scan` 自動 seed 的 staging 候選池，status=new 待 review）→ 把真正相關的 promote 到「待探索方向」+ seed experiment、無關的標 status=rejected；池空或要補深度再 WebSearch arXiv/SSRN/JFE/JFM。工具：`scripts/scan_arxiv_topics.py`（ground-truth RSS，不經 LLM 避免 hallucinate citation） | 待探索方向區 + 對應面向 |
| **Codex/Gemini 建議** | 每 5-10 個實驗 | 主動詢問「接下來該研究什麼方向？」→ 標注 `[提出: Codex/Gemini]` | 對應面向 |
| **用戶指定** | 隨時（最高優先） | 用戶提出的方向立刻寫入 research_program.md | 對應面向 |
| **會員問題** | 每 6 小時 cron | 評估排名會員提問 → 高分問題轉為研究方向 | 對應面向 |
| **實驗過程中衍生** | 每個實驗後 | A 的結果暗示 B → 記錄 B 為新待辦 | 對應面向 |
| **跨 AI 交叉驗證** | 不定期 | 一個 AI 提出假說 → 另一個設計實驗 → Claude 執行 | 對應面向 |

**學術文獻檢索的標準流程：**
1. 搜尋關鍵詞：volatility forecasting, optimal hedge ratio, realized variance, VIX, GARCH extensions, risk management + 年份 2024-2026
2. 對每篇論文提取：標題、作者、期刊、方法、核心發現、與我們研究的關聯
3. 判斷可行性：數據是否可得（yfinance/FRED）？方法是否可複製？
4. 寫入 `research_program.md`「待探索方向」區，標注來源論文和 BLOCKED 狀態
5. 優先執行與現有研究路線互補的方向（而非重複已飽和的方向）
