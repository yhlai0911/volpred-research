# Agent Brief — K1603：Direct-Indexing / Tax-Loss-Harvesting Crowding 與年末個股 RV Reversal

**Model**: opus (high effort) — per task_type=experiment routing
**Task id**: research_direct_indexing_tax_loss_harvesting_crowding_sin
**K-id**: k1603（已確認無碰撞；只可寫 `experiments/k1603/` 內檔案）
**Worktree agent 規則**：只產出 `experiments/k1603/` 內檔案；**禁改**任何共享狀態（`storage/memory/*.json`、`feed.json`、Supabase/Mirror sync、其他 experiments）。完成後在 worktree 內 `git add experiments/k1603 && git commit`。

## 開工前必讀（依序）
1. `docs/error_log.md`（尤其 yfinance 相關教訓，見下方「防錯硬規則」已幫你摘出）
2. `.claude/skills/autonomous-research/references/experiment-preamble.md`
3. `research_program.md` 的公平比較 / Patton / seasonality 相關段（如有）
4. 至少 **3 篇文獻**（自行 WebSearch 補足；建議起點）：
   - Rozeff & Kinney (1976) turn-of-the-year seasonality
   - Constantinides (1984) / Grinblatt & Moskowitz — tax-loss selling hypothesis 與最優實現時點
   - Sialm & Starks / 近期 direct-indexing crowding 或 tax-aware investing 文獻（找 2020+ 的）
   - （加分）任何討論 realized volatility seasonality / turn-of-year vol 的文獻

## 研究動機與差異化
- **假說**：direct-indexing / tax-loss-harvesting（TLH）在年末（12 月）對「年內大幅虧損個股」形成擁擠賣壓，推高該群個股的 **12 月 realized volatility（RV）**，並在 **1 月 RV reversal**（賣壓解除、RV 回落 / 均值回歸）。
- **差異化（不只是重炒 January effect）**：January effect 講的是**報酬**季節性；本研究測的是 **RV（波動率）** 的年末擁擠 → reversal，且要檢驗 direct-indexing 普及後（~2015+）此效應是否**增強**（TLH 擁擠度上升）。這是 volatility-adjacent、VolPred 切題的新角度。
- **Monetization angle**：direct indexing 是 ~$800B 且高速成長的 wealth-management 市場；「年末個股波動擁擠」對 retail / advisor 讀者有實務含義（避開 / 利用年末個股波動），支撐 Mission #2 研究深度 + #1 文章題材 + #5 曝光。
- **相關 K**：knowledge 無 tax-loss/turn-of-year 前作（新方向）；single-stock RV 方法可參考現有 71 個 cross-section/single-stock K 的做法。

## 實驗設計（可調整，但須守方法論硬規則）
1. **Universe（要 bounded 且註明 survivorship 限制）**：取一組流動性高的美股（例：現行 S&P 100 / 一組 ~100 大型股），期間建議 **2010-2025**。⚠️ 用現行成分會有 **survivorship bias** —— 必在 README 明列此限制，並論證方向（delisted losers 被排除 → 對「找到 reversal」是**保守**偏誤）。若能用 point-in-time 成分更佳但非必須。
2. **TLH candidate 定義**：每年以 11 月底 YTD 報酬分組（bottom tercile/decile = TLH 候選 loser；top/mid = 對照）。signal 用 11 月底（含）以前資料 → 12 月/1 月為 forward window，**嚴禁 lookahead**。
3. **RV 度量**：以日報酬平方和的根（或 Parkinson high-low）計 12 月 RV 與次年 1 月 RV。年末→年初 window 明確標日期邊界。
4. **檢定**：
   - 橫斷面：loser 群 vs 對照群的 12 月 RV 差、以及 1 月 RV reversal（1 月 RV 相對 loser 自身 baseline 的回落）。
   - 正式檢定：cross-sectional regression 控制 size / 前期 vol；**跨年度聚合**（避免把 same-year 跨股票當 iid — 見 K1355 教訓：同日跨資產有共同 shock，先按年度/事件聚合再對序列做檢定，或用 cluster-robust SE）。
   - **direct-indexing 增強測試**：pre-2015 vs 2015+ 兩子期比較效應大小（diff-in-diff 風格）。
   - Bootstrap CI（**固定 seed**）。
5. **對照 baseline**：非-loser 群、以及「無季節性」的隨機月份 placebo（測 12→1 是否真的異於其他月對）。

## 防錯硬規則（違反即研究失敗）
- **Lookahead 最高風險**：signal 來自 t-1 / 11 月底；forward RV window（12 月、次年 1 月）不可洩漏未來。分組用的 YTD 報酬只能用截至分組日的資料。
- **yfinance 必顯式 `auto_adjust=False`**（error_log 硬教訓：預設 True 會靜默給 adjusted close → 污染 RV/vol）。同時存 raw `Close` 與 `Adj Close` 兩欄。
- **Pin 本地 CSV snapshot** 到 `experiments/k1603/data/`（yfinance 有 retroactive backfill，不 pin 就不可復現）。第一筆數字在 README 記錄以便日後 assert。
- **所有隨機程序固定 seed**（bootstrap / 任何抽樣 / split）。
- **Survivorship bias** 明列限制 + 方向論證。
- **Null result 如實報告**：若無顯著 reversal / direct-indexing 無增強 → 據實寫，不過度宣稱。失敗也是有效結果。
- **QLIKE/DM 若用到** 遵守 canonical 方向（actual/predicted）；本實驗以 RV level 比較為主，若引入預測損失才需。

## 三件套產出（`experiments/k1603/`）
- `README.md`：動機 / 差異化 / 文獻（≥3，含 cite）/ 資料來源+期間+樣本數 / 方法 / 結果 / 限制（survivorship 等）/ 結論（含 null 可能）
- `k1603.py`：完整可復現腳本（含 seed、auto_adjust=False、snapshot load）
- `k1603_results.json`：所有統計量（效應大小、檢定 p、bootstrap CI、子期比較、樣本數）
- `data/`：pinned CSV snapshot
- `figs/`：≥2 圖（例：loser vs 對照的 12→1 月 RV 軌跡；pre/post-2015 效應大小）

## Scope / 效能
- Universe ~100 股 × 2010-2025 的日報酬 RV 是**輕量計算**，可 inline 完成（squared-return RV + seeded bootstrap B≤2000 皆快）。**不需**進 compute_queue。
- 若任一步驟意外過重（>15 min），**縮小 universe / 縮短期間**，不要 hang，不要 partial —— 交出一個 bounded 但完整的結果。

## 成功標準
- 三件套齊全、README 含 ≥3 文獻 cite、results.json 有正式檢定 + bootstrap CI + 子期比較 + 樣本數。
- 明確 verdict：假說（12 月 RV 擁擠 + 1 月 reversal）是否成立、direct-indexing 是否增強、以及所有限制（survivorship / universe）如實揭露。
- 通過後由主線程做 Codex code review，PASS/CONDITIONAL 才寫 knowledge.json（agent 不自行寫 knowledge）。
- worktree 內 commit `experiments/k1603/`。
