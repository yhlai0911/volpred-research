# assign_358decfa — 改用官方 NFP 發布日並修正線上事件 metadata

**Model**: opus / xhigh (per model_router)
**Worktree（你的工作區，已建好）**: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-0bd07fce-nfpdates`（branch `task/nfp-official-dates`）
**Task id**: `assign_358decfa`（已 in_progress，owner=`hourly-slot-1-0bd07fce62c74c6dbebcb892c4421508`）

## 背景

K1442 的同類污染掃描發現 `experiments/event_article_nfp_2026_07_03_t1` 用 **first-Friday proxy** 當 NFP
發布日。13 個歷史樣本至少 7 筆錯；2026-07 的正確發布日是 **07-02**，不是 07-03。稽核來源：K1442
`related_event_date_audit`。

線上文章 `mile_35eef830` 的**正文已經在 07-03 改成正確的 07-02**，且主要引用 K528/K513。

## 要做什麼

1. **改用官方日曆**：把該實驗的發布日來源換成 `volpred.data.event_dates.nfp_release_dates`，
   移除 first-Friday proxy。**保留 `AS_OF=2026-07-01` 的 T-1 快照**（那份快照本身是對的，
   不要因為改日期就重抓 — 重抓會引入 lookahead）。
2. **重跑受影響產物**：README、results、歷史 CSV、`fig2`、lazypack 的第 2/3 張。
   逐一確認哪些數字真的因日期改變而變動，變動的照實更新，沒變的不要動。
3. **regression tests**：為官方日曆加測試 — 至少覆蓋「first-Friday proxy 與官方日期不一致的那 7 筆歷史樣本」
   ，確保未來不會再回退到 proxy。測試放在 repo 既有測試目錄，跟隨既有命名慣例。
4. **線上 metadata 修正（注意邊界）**：
   - **不要發第二篇更正文**。
   - 只透過**正式 publisher** 修正 `details.event` 與 phase metadata。禁手改 DB / 禁繞過 publisher。
   - **核對 `mile_35eef830` 正文是否仍有受污染的數字**（正文日期已改對，但引用的統計量可能還是 proxy 版）。
     若有 → 一併透過 publisher 修正；若無 → 在報告裡明說「已核對，正文數字無污染」。
   - 最後跑 sync 並做 **live verify**（curl 實際線上頁面確認，不要假設）。

## 硬規則

- 實驗代碼跑之前：確認 `signal.shift(1)` 之類的 lag 在代碼裡、baseline 用同樣 lag。結果好得不像真的 = 90% 有 bug。
- **禁假數字**。任何你沒實際跑出來的數字都不准寫進 README / 文章 / 報告。研究誠實 > 一切。
- **不要寫 knowledge.json**（主線程的職責，K1259 教訓）。
- 不要 force-remove 任何 worktree；不要 `--no-verify`；不要 force push。
- 所有改動 commit 在你自己的 branch `task/nfp-official-dates` 上。**不要自己 merge 回 main** —— 合併走
  正式 `scripts/merge_worktree.sh`，由收件的那一班處理。

## 完成前自檢（Mission sanity check）

- [ ] proxy 已完全移除，grep 不到殘留的 first-Friday 邏輯
- [ ] 7 筆錯誤歷史樣本現在都對得上官方日曆，且有測試釘住
- [ ] 重跑的每個產物都有對應的實際執行紀錄（不是憑推理更新數字）
- [ ] `mile_35eef830` 正文數字污染狀況已明確核對並記錄結論
- [ ] publisher 路徑修正 + sync + live verify 三步都做完且有證據
- [ ] 全部 commit 在 branch 上，工作區乾淨

## 產出

在 worktree 內寫 `experiments/event_article_nfp_2026_07_03_t1/nfp_official_dates_fix_report.md`：
改了什麼 / 哪些數字動了哪些沒動 / 7 筆歷史樣本的前後對照表 / live verify 的實際證據 /
還有什麼沒解決。最後一節明寫「本任務未做的事」。
