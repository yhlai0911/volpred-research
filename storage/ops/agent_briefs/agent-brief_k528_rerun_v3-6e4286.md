# K528 官方日曆 rerun v3 — 修 Codex v2 三個 BLOCKER + findings 3-8

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Task id**: assign_de5398c8 (P1, source=user)
**Worktree (你的 cwd)**: `.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp`

## 背景（不要重新發明）

K528 是 NFP 事件研究。原本用「每月第一個週五」proxy 當 NFP 發布日，已知約 20% 錯誤，
改用官方 BLS 日曆（ALFRED / FRED release id 50）重跑。但 Codex v2 review 判 **FAIL**，
三個 blocker 全部指向同一個根因：accessor 對「同月多筆 release 條目」取 `max()`，
把後續修訂／off-cycle 發布誤當成 monthly Employment Situation。

**根修已經在 main 完成，不要重寫**：commit `305d118a3`
（`src/volpred/data/event_dates.py`：per-month `min()` 選擇 + 13–110 天 cadence
fail-closed 驗證 + regression tests；6 個問題月份已用 live ALFRED 資料驗證 6/6 正確）。
你的 worktree 副本仍是舊的 `max()` 版本（worktree `src/volpred/data/event_dates.py:125`）。

必讀（都在 worktree 內）：
- `experiments/k528/codex_review_v2.md`（FAIL 全文，findings 1-9）
- `experiments/k528/review_verdict.json`（blocking_defects 三條）
- `experiments/k528/README.md`

## 工作項目

1. **同步根修進 worktree**：把 main 的 `event_dates.py` 根修帶進來（rebase 到含
   `305d118a3` 的 main，或直接同步該檔 + 對應 regression tests）。同步後跑一次
   accessor，**自行驗證** Codex 點名的六個錯誤日期已修正：
   2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21
   （例如 2024-08 的 regular release 應是 2024-08-02，不是 08-21）。
   ⚠️ 現有 42 個 tests 全綠但**測不到這個 bug**——fixture 事先刪掉了同月第二筆。
   請補一個用真實 raw-response 語義（同月多筆）的 regression test。

2. **用正確日曆重跑** `k528_nfp_event_study.py` 的 official-dates 分析。
   Codex 已預算：NFP-vs-Friday 約 **1.1779×、p≈0.02488** —— 仍達 5% 顯著。
   **核心的「顯著→不顯著」翻轉不成立**。你的結果若與此預算差距大，先查自己的規格
   （yfinance 抓取窗口、交易日對映），不要直接推翻，也不要為了對齊而調參。

3. **重生文章更正清單**：原 18 條更正**作廢禁用**（它們對齊的是被污染的 JSON，且
   包含錯誤的方向翻轉，見 `build_article_correction.py:58`、`:109`）。依新 results
   重建。Codex finding 3 已抽查出新值供交叉檢核：樣本數 253 不變；NFP 均值約 0.845%
   （非 0.828%）、全體 ratio 約 1.11（非 1.08）、Friday ratio 約 1.18 且顯著、
   regime 約 2.03、組數 128/125、Spearman 約 0.35、斜率約 0.043 個百分點；
   16.69 門檻與 worked example 大致不變。

4. **處理 findings 4-8**：
   - **4 (HIGH) fail-closed 不完整**：accessor 的部分已在 main 修好；
     `k528_nfp_event_study.py:77` 與 `:128` 仍需補——缺月份、同月歧義要報錯；
     發布日找不到三日內交易日時目前靜默略過或映射到下一交易日，需補一對一完整性 assertion。
   - **5 (HIGH) Friday baseline estimand 不乾淨**：目前把全部 NFP 事件（253 中僅 231
     在週五）直接和非 NFP 週五比（`:212`、`:234`），p 值混入 weekday composition。
     修法：事件組限定 Friday releases，或改用 weekday-matched controls。**兩者擇一並說明理由**。
   - **6 (MEDIUM) 方向性敘述超過證據**：results.json 宣稱 "insignificant across all
     tests"，但同一份 artifact 的單尾 Mann–Whitney p=0.00884 明確顯著。改成只說
     Welch mean-difference 未顯著；不得推成「不是 NFP 本身」，非顯著也不是零效果證明。
   - **7 (MEDIUM) 原子寫入**：主結果與 audit 改 temp file + `os.replace`
     （`:832`、`:869`）；builder 的 dry-run 必須真的不寫（`:173`、`:227` 目前無條件覆寫）。
   - **8 (MEDIUM) superseded metadata**：`k528_nfp_event_study_results_PROXY_SUPERSEDED.json`
     本體要加 `superseded=true` + proxy 日期來源 + 撤回原因，讓它離開檔名/README 也可機器判別。

5. **Codex 三審**：全部改完後用 `codex exec` 跑 review（`.claude/skills/codex-cli`），
   把裁決寫成 `experiments/k528/review_verdict_v3.json`（同 v2 schema：kid / verdict /
   reviewer / reviewed_at / reviewed_commit / review_artifact / blocking_defects /
   reviewed_sha256），review 全文寫 `experiments/k528/codex_review_v3.md`。

## 硬性規則

- **PASS 才可 merge、才可套文章更正**。若 Codex 三審仍 FAIL：**不要 merge、不要套更正**，
  把剩餘 blocker 誠實寫進 verdict_v3 並在 knowledge 記錄，這是可接受的結束狀態。
- **禁止**：假數字、為了對齊 Codex 預算而調參、force push、`--no-verify`、
  由 agent 直接寫 `storage/knowledge.json`（K1259）。
- 研究誠實 > 一切。如果新結果顯示「原本的更正方向是錯的」，就照實寫。
- 所有 commit 留在 worktree branch；不要 push main。

## 產出（必要）

寫 `experiments/k528/k528_rerun_v3_summary.json`，至少含：
```json
{
  "kid": "k528",
  "rerun_at": "<ISO8601>",
  "event_dates_fix_synced": true,
  "six_problem_months_verified": {"2006-05": "...", "2012-12": "...", "2013-05": "...",
                                  "2020-05": "...", "2024-01": "...", "2024-08": "..."},
  "headline": {"nfp_vs_friday_ratio": 0.0, "p_value": 0.0, "n_events": 0,
               "significance_flip_holds": false},
  "findings_addressed": {"4": "...", "5": "...", "6": "...", "7": "...", "8": "..."},
  "corrections_rebuilt": {"old_count": 18, "new_count": 0, "old_list_voided": true},
  "codex_v3_verdict": "PASS|FAIL",
  "merge_allowed": false,
  "notes": "..."
}
```
外加 `experiments/k528/review_verdict_v3.json` + `codex_review_v3.md` + 更新後的
README（要說明 18 條作廢的原因與新清單），以及重跑後的 results JSON。
