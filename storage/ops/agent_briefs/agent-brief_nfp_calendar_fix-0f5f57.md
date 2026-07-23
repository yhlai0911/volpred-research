# Task: volatility-absorption 論文 NFP 表污染修復（canonical 日曆重跑）

**Task ID**: `assign_1238781f`（P1，投稿前 blocker）
**Model**: opus / xhigh (per model_router, task_type=experiment)
**Worktree (你的 cwd)**: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-b5fbc1f4-nfpcal`

## 背景

`paper/volatility-absorption/main_v3.tex` 的 NFP 表（abstract L43/L72、Results L368-396、`tab:nfp`、4 個 VIX regime 列、Wilcoxon p=0.0037）逐位對齊
`experiments/k741/k741_nfp_event_study_results.json` 的 `part_a_historical`。

但 k741 與 k904 的 NFP 日期是 **first-Friday proxy**（`get_nfp_dates()` 自己算每月第一個週五），已知 13 錯 7 類缺陷。
根修已於 2026-07-19 完成：`volpred.data.event_dates.nfp_release_dates`（FRED release calendar + `min()` + cadence gate）。

已驗證 canonical 可用：`nfp_release_dates('2010-01-01','2026-03-30')` → 194 dates，首筆 `2010-01-08`（proxy 會給 2010-01-01，錯）。

先讀：`docs/governance/2026-07/firstfriday_proxy_sweep_20260719.md` §3（污染判定與範圍）。

## 必做

### 1. 換日曆（不要重寫實驗，只換日期來源）
- `experiments/k741/k741_nfp_event_study.py` L40-52 `get_nfp_dates()`
- `experiments/k904/k904_paper8_shock_nfp_fix.py` L413-425 `get_nfp_dates()`（注意 `cutoff_date` 語意要保留）
- 改用 `from volpred.data.event_dates import nfp_release_dates`。**保留舊函式但停用**（加 `_legacy_first_friday_proxy` 名稱 + docstring 註明為何棄用），讓 diff 可追。
- k904 副本在 `paper/` 下、主檔在 `experiments/` 下 — 兩處都要同步，不要只改一處。

### 2. 重跑並保留對照
- 新結果寫到**新檔名**（如 `k741_nfp_event_study_results_canonical.json`），**不要覆蓋舊 JSON**（舊的是論文現行數字的來源，要留作對照證據）。
- k904 同理（`task_s4_nfp` 段）。

### 3. 新舊對照表（這是本任務的核心產出）
產出 `experiments/k741/nfp_calendar_fix_comparison.md`，逐項列：
proxy 值 → canonical 值 → 差異 → 方向是否翻轉。至少涵蓋 main_v3 用到的每一個數字：
NFP mean |r|、non-NFP mean |r|、ratio、Welch t / p、Wilcoxon p、N、4 個 VIX regime 列。

### 4. 更新論文
- 更新 `paper/volatility-absorption/main_v3.tex` 的 abstract（L43/L72 附近）+ Results（L368-396）+ `tab:nfp`。
- **若統計顯著性方向翻轉或不再顯著 → 誠實降級敘事**，不要為了保住結論調整檢定。研究誠實 > 一切。降級寫法在 comparison.md 說明理由。
- 確認 `xelatex` 能編過。

### 5. Feed 回溯範圍判定（判定即可，不要自己改文章）
k528 / k661 對應的 feed 文章（feed×7 / ×2）屬同 class 污染。依重跑結果判定：
數字變動幅度是否需要更正、哪幾篇。把清單與判準寫進 comparison.md，**不要在本 worktree 動 feed.json**。

### 6. 驗證
- `uv run pytest` 相關 NFP gate 測試（有三個 tolerance 已收緊到 3%，見 `aef29afe4`）— 若因數字更新而 fail，是**預期**的，更新測試 fixture 並在 comment 註明來源 commit。
- **Codex 二審**：`Skill(codex:review)` 或 `codex exec` 審 diff，重點問「日期來源替換是否完整、有無殘留 proxy 路徑、論文數字是否逐位對齊新 JSON」。把 verdict 記進 README。

### 7. 收尾
- 寫 `experiments/k741/README.md` 補一段本次修復（不要自己寫 knowledge.json — 那是主線程職責）。
- 在 worktree 內 commit（worktree 內可直接 git commit）。**不要**自己 merge 回 main、**不要** force push、**不要** `--no-verify`。

## 產出契約

`--result-artifact` = `experiments/k741/nfp_calendar_fix_summary.json`，schema：
```json
{
  "task_id": "assign_1238781f",
  "calendar_source": "volpred.data.event_dates.nfp_release_dates",
  "n_dates_proxy": <int>, "n_dates_canonical": <int>, "n_mismatched": <int>,
  "k741_rerun": {"old": {...}, "new": {...}, "sign_flipped": <bool>},
  "k904_rerun": {"old": {...}, "new": {...}, "sign_flipped": <bool>},
  "paper_updated": <bool>, "narrative_downgraded": <bool>,
  "xelatex_ok": <bool>, "tests_pass": <bool>,
  "codex_verdict": "PASS|FAIL|<摘要>",
  "feed_articles_needing_correction": ["<slug>", ...],
  "commits": ["<sha>", ...]
}
```

## 禁止

- 假數字 / 手調結果 / 為保住結論改檢定
- 覆蓋舊 results JSON（那是對照基準）
- 動 `storage/feed.json`、`storage/knowledge.json`、`storage/next_tasks.json`
- merge 回 main（由主線程走正式 `merge_worktree.sh`）
