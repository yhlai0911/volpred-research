# 運作指示文件 drift audit — 2026-07-21

Task: `governance_self_revise_operating_docs_20260721`（Telegram msg 604 standing directive 的日期化 successor）
前一份：`docs/governance/2026-07/operating_docs_drift_audit_2026-07-14.md`

## 結論

上週兩項 residual **全部已收斂**（不是靠這班補的，是 follow-up task 各自落地的，本班只做驗證）。
本週新開 6 條 finding，無 critical、無 high。主軸從「文件說謊」轉成「文件說對了但沒指路」——
L1 機械 deny 已經蓋掉三條 `AGENTS.md` 的散文禁令，散文卻沒有 pointer，這是 anti-stacking 的漂移方向。
4 條已直接修掉，2 條列入下週追蹤。**沒有新增任何 enforcement**。

## 上週遺留項現況

| # | 上週 residual | 現況 | 證據 |
|---|---|---|---|
| 1 | `.agents/skills` 是 Codex discovery surface 但被 gitignore；26 skill 中 18 個與 `.claude` 分歧；`agent-specs/` 幾乎為空 | **已修（結構性消滅）** — `.agents/` 與 `agent-specs/` 兩個目錄現在都**不存在**，三方 drift 的另外兩方已被移除，`.claude/skills/`（26 個）成為唯一 surface | `ls .agents` / `ls agent-specs` → No such file or directory；`.gitignore:54-56` 保留當時的決策註記 |
| 1b | `config/models.json` 對 Fable 的自相矛盾 availability | **已修** — 明確拆成 `available`（backend 能不能服務，live probe 為證）vs `dispatchable_now` vs `subagent_policy`（policy），並寫下「不要把 policy 寫進 availability 欄位」的防復發註記 | `config/models.json:6`、`:43`、`:68` |
| 2 | `daily_checkup.py` 有 wrapper、沒有 canonical host schedule（上週誠實改標為 GAP） | **已修** — schedule 已 materialize，含 wrapper 與 log path | `config/runtime_schedules.json:574`（`"id": "daily_checkup"`）、`:577` wrapper_script、`:578` log_path |
| 3 | 13 份 rules frontmatter 需維持以 `---` 起始（上週修 2 份 LF-at-byte-0） | **仍成立、無回歸** — 13/13 全數 frontmatter 可辨識 | 逐檔 head 掃描，13 檔首行皆 `---` |

上週修的 9 個 drift class 本班抽驗未見回歸；`ScheduleWakeup` deny hook、`enforce_final_text`、
`read_context_budget` 三支 hook 均仍註冊於 `.claude/settings.json`。

## 本週 findings

| 維度 | 檔案:行 | 問題 | 建議動作 | 嚴重度 |
|---|---|---|---|---|
| 2 path-trigger | `.claude/rules/context-hygiene.md:11`（修前） | 寫「當 Claude **觸及** 這些路徑時自動觸發」。"觸及" 涵蓋 Bash `jq`/`grep`，與 `CLAUDE.md:84` 的精確版本（只有內建 Read/open 會 auto-load）矛盾。更尖銳的是：本規則自己指定的合法入口就是 `jq` / `ops_snapshot`（`:18`、`:20`、`:23`），所以**照規則做事的路徑永遠不會載入這條規則** | 改寫觸發條件並明寫此自我矛盾 | med → **已修** |
| 3 anti-stacking | `AGENTS.md:103-104` | 「禁止整檔讀取 feed.json / knowledge.json」整段散文，但 Bash 側已由 `.claude/hooks/pretooluse-bash-optimizer.sh:146` 機械 deny、Read 側由 `scripts/hooks/read_context_budget.py:148-150` 機械 bound。`CLAUDE.md:168` 已有 L1 pointer，`AGENTS.md` 沒有 | 補 pointer，指向唯一細則 owner `.claude/rules/context-hygiene.md` | low → **已修** |
| 3 anti-stacking | `AGENTS.md:151` | 「絕對禁止 `git worktree remove --force`」純散文；實際已機械 deny 且涵蓋 `git -C <dir>` 與 `-ff` 等價寫法 | 補 `file:line` pointer | low → **已修** |
| 3 anti-stacking | `AGENTS.md:319-320` | 「共用 main checkout 禁止裸跑 `git add`/`git commit`」純散文；實際 deny 範圍比散文更寬（stage/merge/checkout/ref 全 mutation），且有散文沒講的例外（registered linked worktree 不受攔截） | 補 pointer + 標明例外 | low → **已修** |
| 1 doc↔實作 | `.claude/rules/paper-workflow.md:42`、`:59` | 要求復現包裡「`scripts/README.md` 從乾淨 clone 能走到每張主表/主圖」，但 `scripts/README.md` **不存在** | 這是投稿時才需交付的 artifact，不是即時 drift；但目前沒有任何 gate 檢查它，投稿當天才會發現 → 建議在 `paper-submission-pipeline` 的 compliance gate 加一項檢查（**不是新增 enforcement，是把既有 gate 的檢查清單補一條**） | low（下週追蹤） |
| 1 doc↔實作 | `scripts/check_skills_complete.sh --json` 輸出 | `stale_skills` 有 7 個：`agent-result-verification`、`citation-verifier`、`external-data-sources`、`latex-academic-reviewer`、`memory-health`、`web-ui-ux-review`、`worktree-merge-verification`。`missing_skill_md` / `empty_frontmatter` / `dead_references` / `workflow_drift` 皆為空 | 需逐一判定「真的過時」vs「穩定所以沒動」——stale 是時間戳啟發式，不等於 drift。本班時間不足以逐檔判讀 | low（下週追蹤） |

## 沒找到 drift 的面向（查了但乾淨）

誠實列出，避免下週重複查：

- **hook 註冊完整性**：`.claude/settings.json` 的 5 個 event（SessionStart / UserPromptSubmit / Stop / PreCompact / PreToolUse）所引用的 8 支腳本**全部存在**。`scripts/hooks/git_mutation_guard.py`、`commit_message_guard.py`、`.claude/hooks/run-compact-bash.sh` 未直接註冊，但這是**已知且已記錄**的設計（由 bash optimizer 內部呼用，見 `.claude/hooks/pretooluse-bash-optimizer.sh:72`、`:97`；`platform-ops-manager/references/loop-health-and-dreaming.md:152` 已明載）——不是 drift。
- **L1 deny 宣稱逐條驗證**：`CLAUDE.md:168`（feed/knowledge 整檔讀）、`CLAUDE.md:217`（worktree force remove）、`.claude/rules/frontend-and-deploy.md:35`（zeabur deploy）三條括號內的「已攔截」宣稱，在 `pretooluse-bash-optimizer.sh:141`、`:144`、`:146` 逐條對上。**沒有虛報機械化**。
- **死路徑掃描**：`CLAUDE.md` + `AGENTS.md` + 13 份 rules 抽出的 148 個檔案路徑引用，逐一 stat。除上表 `scripts/README.md` 外全部存在（另 3 個 apparent miss 為我的 regex 截斷造成的偽陽性，已人工排除）。
- **維度 4 Codex discovery surface**：26 份 `SKILL.md` 全數有 frontmatter、`description` 非空、長度皆 > 40 字元且含具體 trigger phrase。`dead_references` 與 `workflow_drift` 皆空。**本週無 drift**。
- **dedup-gate audit rule 活性**：`.claude/rules/dedup-gate-audit.md:18` 宣稱每次 gate 決策寫 `storage/logs/dedup_decisions.jsonl` — 檔案存在、最後一筆 `2026-07-21T01:23:41Z`、9 支 producer 在寫。**宣稱與實作一致且仍活著**。
- **dispatcher**：`scripts/continue_task_dispatch.py` 與 `scripts/dispatch_supervisor/`（含 `decision.py`、`codex_failover.py`、`phase_z.py` 等）均存在，AGENTS/CLAUDE 對其角色的描述未見矛盾。

## 已直接修掉的

1. `.claude/rules/context-hygiene.md:11` — 觸發條件改寫為「內建 Read/open 才 auto-load」，並**明寫**「照規則用 jq/ops_snapshot 做事的路徑不會載入本規則」這個 counter-intuitive 事實，指向 `CLAUDE.md` §Rule path-trigger 時序原則。
2. `AGENTS.md` Token 紀律段 — 加 L1 pointer（Bash deny + Read bound 分開講，因為兩者行為不同：一個 deny、一個只 bound），並宣告細則唯一 owner 是 context-hygiene rule。
3. `AGENTS.md` worktree 段 — `git worktree remove --force` 加 `file:line` pointer 與等價寫法涵蓋範圍。
4. `AGENTS.md` commit 慣例段 — 裸 git mutation 加 pointer，補上散文漏掉的**例外**（registered linked worktree）與**更寬的實際範圍**（不只 add/commit）。

四處都是**additive pointer**，沒有刪改任何既有治理規範文字（遵守 `AGENTS.md:243`），也沒有新增第二套 enforcement。

## 需老闆決策

**無。** 本班未修改 `.claude/skills/*` 任何檔案，因此**不需要寄 email 通知**。
（`.claude/rules/context-hygiene.md` 屬 rules 不屬 skills，且該修改是修正機制描述的事實錯誤，落在「可直接改」範圍。）

## 下週追蹤清單

1. **`scripts/README.md` 復現包缺口** — 判定該建檔還是該把 `paper-workflow.md:42/59` 的要求改成「投稿時 materialize」，並考慮收編進 `paper-submission-pipeline` 既有 compliance gate 的檢查清單（不新開 gate）。
2. **7 個 stale_skills 逐檔判讀** — 區分「內容真的過時」與「穩定所以沒動」，只修前者。
3. **`read_context_budget.py` 的 escape hatch** — 該 hook 對帶 explicit `limit` 的 Read **從不覆寫**（`:108`、`:138`）。這是刻意設計（避免改變行為），但意味著 `Read feed.json limit=999999` 在機械層是**放行**的；`AGENTS.md` / context-hygiene 的「禁止整檔 Read」在 Read 路徑上仍是 prose-only。**本班不動它**——補洞就是新增第二套 enforcement，違反本任務硬性限制。列出來讓老闆知道這個 gap 是知情選擇，不是疏漏。
4. 維度 3 本班只掃了 `AGENTS.md` 與 rules，**未掃 `.claude/skills/*/SKILL.md` 內部的機械化散文**（時間限制）。下週補。

## Cadence

下一個日期化 instance：`governance_self_revise_operating_docs_20260728`。
沿用既有 `blocked_until` + hourly `unblock_expired_blocked_tasks.py --apply` 機制，不重用固定 id。
