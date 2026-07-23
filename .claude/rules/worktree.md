---
paths:
  - ".claude/worktrees/**"
  - ".codex/worktrees/**"
  - "scripts/merge_worktree.sh"
  - "scripts/reclaim_stale_worktrees.py"
  - "experiments/**/*"
---

# Worktree / Agent 規則

以內建 Read/open 讀取 `.claude/worktrees/**`、`.codex/worktrees/**`、`scripts/merge_worktree.sh`、`scripts/reclaim_stale_worktrees.py` 或 `experiments/**` 時 auto-load；Bash `git` / `rg` 不觸發，派 worktree 前仍須由 experiment / dispatch workflow 顯式載入。

## Worktree agent 禁忌（硬規則）

1. **只能產出 `experiments/<kXXX>/` 內的檔案**（實驗三件套：README.md / kXXX.py / kXXX_results.json + 圖表）。
2. **禁止修改共享狀態**：
   - `storage/reports/feed.json`（feed 主文件）
   - `storage/memory/knowledge.json`（研究發現）
   - `storage/memory/thinking_journal.json`（思考記錄）
   - `storage/memory/experiment_experiences.json`（經驗索引）
   - Supabase / Mirror sync 流程（`scripts/supabase_sync.py` 等）
3. **禁止動 `paper/*/body.tex` / `main*.tex`** — 論文寫作由主線程負責（`.claude/rules/paper-workflow.md` L188 加強條款）。

## 合併流程

0. **實驗要進 main，先有審查認證**（2026-07-14）：branch 只要動到 `experiments/`，merge 前會對每個
   `experiments/<kid>/` 跑 `experiment_gates.py certify` —— 需要一份 `review_verdict.json`，verdict=PASS
   且 pin 住的 sha256 等於現行 bytes。沒裁決 / FAIL / 審完又改 code（sha 漂移）→ **拒絕合併，保留 worktree**。
   契約與 why 見 `.claude/rules/experiments.md` §審查認證。K1709 就是被判 FAIL 仍 merge 進 main，害 CI 連紅 4 次。
1. Worktree agent 完成後**必須 commit** 它產出的檔案到 worktree branch。
2. 主線程用 `bash scripts/merge_worktree.sh <worktree-name>` 合併。
3. **絕對禁止** `git worktree remove --force` — 以免未 merge 的 commits 消失（2026-04-18 K1032 教訓有記）。
4. Merge 後**主線程手動 check**：`git log --oneline -5` 驗證 commits 真的進了 main。
5. **K1143-v2 (2026-04-19) hardening**：script 若偵測到 `rev-list=0` 但 worktree `experiments/` 仍有主目錄沒有的檔，會主動 ABORT 並顯示手動 copy 指令。**看到 ABORT 不是 bug，是防禦**；按 hint 執行即可。
6. Regression test：`bash scripts/tests/test_merge_worktree.sh`（修 script 後必跑；case / assertion 數以 script 當次 summary 為準，不在規則重複硬編）。
7. **stale-base overlap gate（2026-07-23）**：worktree 落後 main 本身不是錯；但若 main 與
   worktree 從 merge-base 起修改了**相同路徑**，`merge_worktree.sh` 必須在 merge 前 ABORT，
   保留兩側 branch / bytes，待 worktree 明確 rebase 或人工整合並重跑驗證。禁止讓 `-X ours`
   代替語意裁決。兩側路徑不相交才可繼續；worktree 相對 base 呈現純刪除的路徑會另行告警。

## Agent brief 規範

- Brief 必含 6 要素（任務 / 動機 / context 指引 / 規範引用 / 成功標準 / scope 限制）— 完整說明見 `.claude/rules/agent-delegation.md`。
- 標準 template：`.claude/skills/autonomous-research/references/agent-brief-template.md`
- **所有 agent（含 Codex）一律引用 `.claude/skills/<name>/SKILL.md`** —— `.claude/` 是唯一 canonical surface。
  舊規則寫「Codex agent 引用 `.agents/skills/*.md`（Codex 讀不到 `.claude/`）」，**兩句都不成立**：
  (a) Codex 是有完整檔案系統存取的 CLI，你把路徑寫進 brief 它就讀得到 `.claude/` —— 它只是不會
  *自動* 發現那裡的 skill（Codex 0.144.1 的 skill auto-discovery 只走 plugin marketplace
  `<home>/.agents/plugins/marketplace.json`，binary 對 `agents/skills` 命中 0 次）；
  (b) 因此 `.agents/skills/` 從來就沒有被 Codex 載入過 —— 它是個沒有讀者的 render 複本，
  已於 2026-07-14 廢止（gate: `tests/test_skill_surface_single_source.py`；決策記錄:
  `docs/skill-registry.md`）。派 Codex 時**在 brief 裡明寫要讀哪個 `.claude/skills/...` 路徑**。

## 踩過的坑

- **K1032** (2026-04-12) worktree agent commits 存在但 `merge_worktree.sh` 判定 no-commits → 實驗檔案遺失。修復：主線程手動 check reflog + 補 cherry-pick。
- **K1114** (2026-04-13) 同 bug 再現 → commit 34817184 加了 rev-list 雙重驗證。
- **K903/K904/K1100g_d9** (2026-04-18/19) 再現：auto-commit 漏偵、detached HEAD、或 gitignore 吃掉檔案都會讓 rev-list=0 但工作目錄仍有 orphan `experiments/` 內容。
- **K1143-v2** (2026-04-19) **systemic fix**（Paper 8 diagnostic 觸發）：
  1. Line 126 原本有 `git worktree remove --force` fallback（違反 CLAUDE.md L168）→ 移除 fallback，remove 失敗直接 abort
  2. Line 78 `git status --porcelain 2>/dev/null || true` 會 silent skip → 改 `git status` 失敗就 abort
  3. Auto-commit 後要驗證 HEAD 前進，detached 狀況直接 abort
  4. rev-list=0 path 加 pre-remove 掃 `experiments/<kXXX>/`：orphan 資料夾或 worktree-only 檔就 abort
  5. Orphan branch cleanup 用 `git for-each-ref` 取代 `git branch | tr -d ' '`（後者不清 `+` 標記）
  6. 新增 `scripts/tests/test_merge_worktree.sh`：4 cases / 7 assertions，合併流程的 regression gate
- **K1261** (2026-04-27) `-X ours` 對 experiments/ 內 fork 檔同樣坑（不只 shared JSON）→ 加 K1261-v3 post-merge -X-ours-dropped detection layer。
- **K1262-v4** (2026-04-27) `merge_worktree.sh` silent drop bug **第三次重現**（K1032 same root cause）：
  1. **rev-list cd-context fix** — 所有 ref 比較強制 `git -C "$MAIN_DIR"`（rev-list、log、diff-tree、diff），不再依賴 cwd-relative 解析。過去 cwd-shift 是 silent drop 主因。
  2. **Primary file-presence diff layer**（最高優先）— 在原 rev-list double-check 之前先跑 `git -C "$MAIN_DIR" diff-tree --diff-filter=A main..branch -- experiments/`，發現 worktree-only 檔就強制走 merge path（不信 rev-list false negative）。
  3. **K1262-v4 post-merge file-presence verification** — merge 後逐檔 `git cat-file -e HEAD:<path>` 驗證 K-experiment 真在 main HEAD git tree（不只 working tree）。失敗時 ABORT loud + 列 cherry-pick hint + 保留 worktree。
  4. **Locked worktree hint** — `git worktree remove` 失敗時印 unlock + remove + branch -D 三段式 recovery hint，**禁止** `--force` fallback (CLAUDE.md L168)。原 L444-458 的 `--force` / `unlock + -f -f` 階梯已移除。
  5. **Test gate 擴充** — `scripts/tests/test_merge_worktree.sh` 新增 case 5/6/7（rev-list false negative / post-merge verification / locked worktree hint），現為 7 cases / 17 assertions PASS 7/7。
- **K1618** (2026-07-04) **STRIKE 2**（K1032 same root class 第 2 次）：主線程 shell cwd 停在待合併 worktree 內（Bash cwd 跨呼叫持久）+ 相對路徑 `bash scripts/merge_worktree.sh` 呼叫 → 舊版 `BASH_SOURCE`-相對解析把 `MAIN_DIR` 指到 **worktree root** → `main_branch` = worktree 自己的分支 → `main_branch..branch` 自比自 = 0-commit false-negative → 5 層防禦全繞過 → 未 merge 就砍 worktree（靠 branch 存活救回）。**systemic fix**（詳 `docs/error_log.md` 2026-07-04 04:25 RESOLVED）：
  1. `resolve_main_dir()` 用 `git -C "$script_dir" rev-parse --git-common-dir` anchor 到**腳本實體目錄**（非裸 cwd），從任何 cwd 都回主 repo；`-d "$root/.git"` 拒絕誤指 worktree。
  2. HEAD=worktree-agent 分支 / `main_branch==branch` self-compare / git log rc≠0 三道 fail-loud guard；`ensure_cwd_outside_worktree()` 在兩個 remove 前擋。
  3. 當時對 `-X ours` drop 的 modified 檔採**自動還原 agent 版本**；此契約已由
     2026-07-23 stale-base overlap gate 取代：現在必須在 merge 前保留兩側並要求明確整合，
     不再於 merge 後武斷覆成任一側。
  4. Test 加 case 8/9/10，現為 **10 cases / 25 assertions PASS 10/10**。**merge 前主線程必先 `cd $REPO_ROOT`、永不從 worktree 內部觸發 merge**（memory `feedback_no_cd_into_worktree_before_merge`）。
- **86e142305 / D6b reaper** (2026-07-23)：main 與 stale worktree 同改
  `scripts/compute_queue.py`，`-X ours` 產出的 merge 相對 main parent 看似正常，
  相對 worktree parent 卻是 `+0/-192`，已驗證活碼被靜默丟棄；舊 detector 又只掃
  `experiments/`。修復為 merge 前比較兩側自 merge-base 起的 path set：有交集即
  fail-closed，無交集才放行；另對 pure-deletion shape 顯式告警。
- Session 停止時 `git worktree remove --force` 清掉未 merge worktree → 重要 session recovery 永遠走 reflog 不走 remove force。
