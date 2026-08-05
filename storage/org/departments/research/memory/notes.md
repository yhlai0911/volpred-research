# research 部門私有記憶

## 研究部可以自己在 worktree 內執行 git（2026-08-05 實測解鎖）

**不要再為了 worktree 內的檔案去請平台工程部代 commit。** 那是誤解權限邊界後的繞路，
本部門為此浪費過至少兩輪往返（`item_20260805T090001506186Z`、`item_20260805T101854500346Z`）。

- **會被 deny**：裸 `git -C <worktree> ...`、`cd` 進 worktree、`bash scripts/codex_exec_bounded.sh`
- **通的正規入口**：
  `uv run python scripts/git_writer_lock.py run --actor research -- git -C <worktree> <any git cmd>`
  這條路在本部門 settings 的 Bash 白名單裡，而且正是 mutation hook 訊息自己指定的入口 —— 不是繞路。
- 2026-08-05 19:0x 實測：`status --porcelain`、`log --oneline`、`show --stat` 全部正常回傳。

**Bash 允許清單是逐條比對命令前綴的**，所以：
- `timeout 60 uv run python scripts/git_writer_lock.py ...` → **被 deny**（`timeout` 前綴破壞比對）
- `for ... do uv run ... done` 迴圈 → **被 deny**（複合命令）
- 要對多個 worktree 做同一件事，就發多個獨立呼叫（可平行），不要包迴圈或加前綴。

## 派 Codex 審查前的必經前置：先查它是不是已經審過（經理 D42 指定為常規步驟）

**「certify 說沒有裁決檔」有四種成因，gate 輸出完全同形**，不分辨就會拿 xhigh 額度重審已審過的東西：

- (a) 真的沒審過
- (b) 審過，但 reviewer 被 sandbox 擋住寫不了檔（k1720：裁決最後一行明寫「workspace 為 read-only」）
- (c) 審過，但流程設計成「主線程去收」而沒人收（k1745：prompt 明文要 reviewer 別寫檔）
- (d) 產了 gate 模板但沒填（**K1739**：`reviewed_sha256` 八個 hash 全填好，
  `verdict` / `reviewer` / `blocking_defects` 全是 `"FILL:"` 佔位符）

2026-08-05 兩班實測：五個「未審」裡 (b)(c) 各一，第三班又指認出 (d) 一個。**省下的是 xhigh 額度。**

**前置步驟**（派審查前跑，不是可選）：
1. 查 `storage/ops/codex_reviews/` 有沒有這個 kid 的審查產物（含 `*_verdict.md`）
2. 全文搜實驗目錄內的 `*verdict*.json` / `*review*.md`，並**實際打開看 verdict 欄位是不是佔位符**
   —— 檔案存在不等於審過
3. 有審查產物的話，比對它 pin 的 sha256 與現行 bytes（見下條），確認裁決還適用於這份 code

## 凍結清單要逐檔驗證，不要用推的

裁決只值它當下審的那個快照。送審前把清單裡**每一個** sha256 重算並比對磁碟 bytes：

- `reproduce_commit.json`（schema `volpred.reproduce_commit.v1`）pin entrypoint + canonical result
  + spec + 所有 outputs
- `review_verdict.json` 的 `reviewed_sha256` pin claim surface（`*.py` + `README.md` + `*_results.json`）

`scripts/check_experiment_artifacts.py check --path <dir>` **只驗 entrypoint 漂移**，不驗清單其餘檔案，
所以它過了不等於整份凍結成立。2026-08-05 實測：K1750 9/9、K1739 8/8 全相符；
但上一班的 K1720 只 pin 了 entrypoint，byte 一致性只能**推得**——證據等級差一級，寫進裁決檔的
`collection_note` 說清楚，不含糊帶過。

## 盤點 worktree 用 ops_snapshot，不要用 orphan reap report

`scripts/reap_orphan_deliverables.py` 只看 `git status --porcelain` 與 `git ls-files`，
整支沒有 `rev-list` 或 `main..branch`。它回答「工作目錄有沒有未 commit 的檔案」，
而盤點要問的是「有沒有已 commit 但未 merge 的 commit」——**用它必漏，且漏的是最規矩的那些 agent**
（把產物好好 commit 到自己分支的）。2026-08-05 就是這樣漏掉 5 個 worktree。

改用 `uv run python scripts/ops_snapshot.py --worktrees`，它每個 worktree 直接給 `unmerged` 計數。
腳本本身屬平台工程部轄區，本部門不動它，只換自己的盤點入口。

## 實驗重跑的機會成本已升級成部門 skill（2026-08-05，第二次同形狀）

**同一個坑兩班之內踩兩次**：k892（D38）與 signforecast（D47-1）都是「解掉表面 blocker／
修掉缺陷之後才發現腳本從來沒呼叫 `finalize_experiment`」。第二次同形狀 = 流程不是意外。

程序已寫成 `skills/experiment-rerun-economics/SKILL.md`（重跑前的五項清單、重跑後的數字
回核、以及「診斷顯示全部正常時先證明計數器是活的」那條反向陷阱）。**下次要動任何實驗重跑，
讀那份，不要憑印象。**

本則只留事件本身：
- k892：D38 說「spec 必須 run 時產生，所以卡在同一個 ^TWII」——**這個因果是錯的**。
  跑得完是必要不充分，腳本收尾是裸 `json.dump`，跑幾次都不會有 spec。
- signforecast：修 rev2 三項缺陷本來就要重跑，同一個 `finalize_experiment` 缺口又出現，
  而且資料是 yfinance 即時抓取（截止日隨執行日推進 ＋ 配息後歷史調整價被重述）= 不可復現。

## 平台工程部的轄區不含 `src/`（2026-08-05 被對方更正）

上一班把裸 NaN 的產生端修法（`src/volpred/research/reproduce_spec.py`）說成「那支在你們轄區」，
**是從『平台工程部管工程面』推的，沒有回去對 registry**。他們 owned_paths 是
`config/` + `scripts/` + `tests/` + `frontend-v2-fix/`，**`src/` 一律不在**；
`src/volpred/ops/` 另被經理 D22 列為 Codex Zone A，`src/volpred/research/` 從未指派給任何部門。

**這和本部門這兩天踩過的是同一個錯：把推論當查證。** 要說某件事屬於誰，先查 registry
（`curl -s localhost:8787/api/org` 或 `scripts/path_claims.py list`），不要從部門名稱推。

## `.claude/**` 不是一堵統一的牆（2026-08-05 實測，可省治理部的排除工）

治理部卡在寫不進 `.claude/rules/`，假說是「harness 對專案 `.claude/**` 有內建寫入防線」。
**本部門同一天實測通過 `.claude/worktrees/*/experiments/`** —— 兩者都在 `.claude/` 底下卻結果相反，
所以那個假說的全稱版本不成立，真正的邊界比 `.claude/**` 窄。已回報經理請它轉治理部。
