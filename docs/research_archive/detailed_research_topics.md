# 待深入研究主題（詳細版）

從 research_program.md 搬移，保留完整描述。未完成項目仍列在 research_program.md 的摘要中。

---

## 除權息研究方向（用戶指定）→ K917 完成 NULL
- [x] ~~除權息前後波動率是否系統性改變~~ → K917 NULL。夏季 RV=0.169 < 其他 0.185。Welch t=-1.03 p=0.30。VIX 控制後 t=-0.10 p=0.92。填息中位 0 天。VIX sufficiency #27
- [x] ~~高股息 ETF 除息日前後~~ → K917: 0056.TW 也 NS (t=0.09 p=0.93)
- [ ] 「填息率」與波動率的關係——填息快的股票 vol 是否較低？
- [ ] 除息日對 0050.TW 的 vol 影響（0050 成分股集中除息期間）

## SEC Filings 研究與文章方向（用戶提出）
美股的 10-K（年報）、10-Q（季報）、8-K（重大事件即時揭露）是重要的資訊來源和內容題材：

*文字探勘 (Text Mining)*
- [ ] SEC filing 語調分析：用 Loughran-McDonald 金融情緒詞典對 10-K/10-Q MD&A 段落做正負情緒打分，看情緒變化是否預測後續 vol/return
- [ ] 10-K 可讀性（Fog Index / 文件長度）與後續 vol 的關係
- [ ] 8-K filing 文字 surprise：用 TF-IDF 或 embedding 計算 8-K 與前次 filing 的文字差異度
- [ ] Risk factor section 的年度變化：新增風險因子 vs 刪除風險因子 → 對 vol 的預測力

*情緒 (Sentiment)*
- [ ] Management tone（管理層語調）：法說會逐字稿 vs 10-K 書面語調的差異
- [ ] Forward-looking statements 的情緒：MD&A 中「expect」「believe」「risk」的頻率變化趨勢
- [ ] 跨公司情緒傳染：SPY 前 10 大成分股的 filing sentiment 彙總 → 是否預測 index vol？

*財務 (Financial)*
- [ ] 10-K/10-Q filing 前後 SPY vol 是否有系統性模式？
- [ ] 8-K filing（unexpected events）對個股和 index vol 的 surprise 效果
- [ ] Accruals quality（應計品質）vs 後續 vol：低品質 earnings → 高未來 vol？
- [ ] 財務比率的年度變化（debt/equity, current ratio）vs 後續 vol

*管理 (Governance & Management)*
- [ ] CEO/CFO turnover 的 8-K 揭露 → 對 vol 的即時和延遲影響
- [ ] 審計意見變更（going concern, material weakness）→ vol spike 預測
- [ ] 內部人交易揭露（Form 4）與後續 vol/return 的關係
- [ ] TSMC 20-F（外國公司年報）filing 對 TSM/0050.TW 的影響

*台灣重大訊息（MOPS 公開資訊觀測站）*
- [ ] MOPS 重大訊息公告：台灣上市櫃公司的即時揭露，包括營收公告、董事會決議、私募、合併、訴訟等
- [ ] 台股重大訊息公告頻率/內容 vs 後續 vol/return
- [ ] 0050 成分股重大訊息的彙總 sentiment → 是否預測 0050 vol？
- [ ] 法說會逐字稿語調分析

*文章方向（一般讀者）：*
- [ ] 「10-K、10-Q、8-K 是什麼？散戶為什麼該關心美股年報」(general 教育文)
- [ ] 「財報季前後的波動規律——數據告訴你什麼時候最危險」(general)
- [ ] 「如何從 SEC filing 讀出公司的真實風險」(general 教學文)
- [ ] 「CEO 換人了——股價會怎樣？8-K 告訴你的事」(general)
- [ ] 「年報越厚越危險？文件可讀性與股價波動的關係」(general)

## 經濟政治不確定性 & 搜尋趨勢（用戶提出，持續議題）
過去研究：G14 Google Trends (partial r sig but 反轉)、J3 (IS r=0.634 but VT null)、K446 GPR (reversed causality)、K473 (OOS null)。
這些主題作為 vol research 已被 VIX sufficiency 限制，但作為讀者內容和市場解讀仍然重要：

*定期文章（每月至少 1 篇）：*
- [ ] 「本月 Google 搜尋趨勢告訴你什麼？」
- [ ] 「經濟政策不確定性指數（EPU）最新動態」
- [ ] 「地緣政治風險現在有多高？」
- [ ] 「恐懼與貪婪指數解讀」

*研究更新（當重大事件發生時）：*
- [ ] 特定事件的 Google Trends spike → VIX 反應速度和幅度分析（event study）
- [ ] EPU/GPR 在 tariff/sanction/election 期間的特殊行為
- [ ] 台灣選舉/兩岸關係事件 → VIXTWN/0050 vol 反應（需更長 VIXTWN 數據）

## 成交量作為波動率預測因子（用戶提出）
過去研究多 null（K113/K135/K418/K527）。K519 上架暫停（需 5AM-9AM 可執行機制）。

### 台指期貨 Overnight Gap Strategy（K515 延伸）
- [ ] TX cost ~2-3bp，overnight gap alpha 真實（t=4.06）但 ETF 成本致命。用台指期測試。

## MEM 模型文獻（2026-03-31 搜尋）
- [ ] **基礎 MEM**：Engle & Gallo (2006) 原始 MEM。非負值序列（RV, volume）的條件期望×隨機擾動。[提出: 用戶 + 文獻]
- [ ] **AMEM（Asymmetric MEM）**：加入不對稱效果（正負衝擊不同影響）。VOLARE 平台已實作 [提出: 文獻]
- [ ] **DMEM（Doubly MEM）**：長短期雙成分（Spline-MEM, Component-MEM, MEM-MIDAS）。ScienceDirect 2023 [提出: 文獻]
- [ ] **Vector MEM**：多變量 MEM（Cipollini, Engle & Gallo）。跨資產 vol 聯合建模 [提出: 文獻]
- [ ] **AMEM-MV**：分解 RV 為 base + meaningful volatility events 成分。2025 [提出: 文獻]

## Gemini 建議（2026-03-31）[提出: Gemini 2.5 Pro]
- [ ] **Wasserstein Volatility Drift (WVD)**：用 2-Wasserstein 距離測量日內 RV 分布漂移。假說：WVD 領先 VIX regime shift 1-3 天。需 5-min 數據（ETA 04/11）
- [ ] **Gamma-Trap 零售回饋迴路**：0DTE option flow → MM hedging → vol pin/explosion。⚠️ BLOCKED 需 option flow 數據
- [ ] **Transfer Entropy VT Budgeting (TE-VT)**：用 Fed liquidity → VIX 的 transfer entropy 動態調整 VT 保險。FRED 數據可得

## 用戶提出方向（2026-03-31）
- [ ] **K770 修正版：統一 forecast target**：MEM/HAR 預測 |r| 但 GARCH 預測 σ。需統一到同一 target（close-to-close RV = intraday + overnight）。Hansen & Lunde (2005) 提出最優加權方案
- [ ] **Overnight volatility component**：隔夜波動約佔全日 20%（Hansen & Lunde 2005）。加入隔夜 r² 到 HAR/MEM 作為額外 regressor
