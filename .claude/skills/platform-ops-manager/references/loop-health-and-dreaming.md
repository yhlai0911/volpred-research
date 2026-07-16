# Loop-health 指標 + Dreaming 慢 loop（2026-06-29 loop-engineering 層）

本文件是運營經理「系統有沒有在變好」自省層的操作參考。被動載入；觸發 ops 相關 path 時隨 platform-ops-manager skill 一起可用。

## 為什麼有這層

既有監控回答兩個問題：「loop 還活著嗎」（`alerts.py` 的 freshness / dead-man switch）、「基礎設施健康嗎」（`health.py`）。都不回答 loop-engineering 的核心問題：**「loop 有沒有在變好？」**—— 同類錯誤是否反覆、任務是否一次完成、糾正是否變多。近期一串事故（FB rot、daily_update 假警報、dbcddc0 CI 紅、「安靜 tick」）共通點：**該被系統先抓到、卻靠老闆人工抓到**。這層補上那個閉環。

## 兩個 loop（刻意分層）

| | Fast loop | Slow loop |
|---|---|---|
| 模組 | `src/volpred/ops/loop_health.py` | `scripts/dreaming_review.py` |
| 何時跑 | 搭既有 hourly fire 便車（`ops_dashboard` / `check_alerts`），零新排程 | 每日 05:25 cron（`dreaming_review` job） |
| 做什麼 | 聚合 4 個指標成 snapshot | 跨 session 找重複失敗模式、產 findings + proposal |
| 入口 | `uv run volpred ops loop-health` | `uv run volpred ops dreaming-run [--dry-run]` |

## 4 個 loop-health 指標（全部 derived，附信號強度）

- **first_pass_success** — 近 14d 成功任務中一次完成的比例（從 work_log failed→succeeded 序列推導）。`status_history` 覆蓋率低 → 自帶 `coverage`；不足時回 `low_coverage`（info，不 breach）。
- **task_outcome** — 近 14d 任務終態 success/fail/blocked 比例（支撐紮實，主「有沒有在出貨」訊號）。
- **error_recurrence** — 重複的 cron 非零退出 + diagnostics tag。exit142 標 `known`（自癒，不升級）。**注意：cron-exit 即時告警是 `host_cron_fail` 的責任，loop_health 只記錄重複數據供 dashboard + dreaming，不獨立寄 alert。**
- **correction_trend** — 近 4 週糾正事件斜率（上升=品質退化）。

`overall` = 最差子狀態（`unknown`/`low_coverage` 不升級）。

## Dreaming detector

目前涵蓋 repeated_tool_failure / recurring_error / stale_knowledge /
missing_retry_strategy / loop_metric_regression / semantic_concentration /
memory_governance / persistent_alert / orphaned_experiment。每個 fail-open（warn 後 skip）。
輸出 `storage/ops/dreaming/<date>.json` + 滾動 `baseline.json`（per-signature 連續 run strike count）。

## Auto vs Propose — 硬邊界（研究誠實 + 永遠修流程不修資料）

讀 dreaming report 時依 `remediation` 欄判斷：

- **AUTO（一律安全，dreaming 自己做）**：寫 dated report、append `autonomous_decisions.jsonl`、寄 email。
- **AUTO-DISPATCH（低風險衍生狀態，建修復 task）**：actuator 自 2026-07-12 **預設開啟**。`auto_dispatch` finding（如 missing retry / orphan）在 warn 即進 `storage/next_tasks.json`；`propose_only` finding 連續 3 晚仍存在才進 queue，且 task 只要求 agent 審核，不直接改治理檔。`--dry-run` 才不派工。
- **PROPOSE-ONLY（治理檔，絕不自動改）**：`docs/error_log.md` / `.claude/rules/*` / `CLAUDE.md` / `storage/memory/knowledge.json` / `docs/refactor_plan_*`。dreaming 只把建議寫進 report 的 `proposal` 欄 + `governance_target` + email。**主線程審完才手動套用。**

## Three-strike 升級

一個 signature 連 **3 次** dreaming run 都出現 → severity 升 `critical`、email level=critical。這是 `docs/refactor_plan_<topic>.md` Three-Strike 根治的種子。dreaming 不自動建 refactor_plan（屬 docs/，propose-only）—— 主線程開檔。

## 主線程收到 dreaming email 時做什麼

1. 看 `storage/ops/dreaming/<date>.json` 完整 findings。
2. 治理類 proposal → 評估是否套用（改 error_log / rule / knowledge），**手動**做，不讓 dreaming 改。
3. escalations(critical) → 開 refactor_plan 走 Three-Strike。
4. auto_dispatch 類（orphaned failure）→ 決定 retry 或 mark blocked（controlled reason）。
5. loop_metric_regression → 查對應 work_log / correction 根因。

## 已知 follow-up（2026-06-29 建置時發現）

- `alerts._parse_cluster_cap_drift_state` 的 `recent_cluster_counts` 不吃 `storage_dir` → 讀真實 feed，測試無法隔離（`tests/test_alerts.py` 用 monkeypatch quiet）。應 refactor 成 storage_dir-aware。
- 首次 dreaming run 抓到 `hourly_dispatch.log:exit1` 在 06-26/27 近全班失敗（API 死，06-29 已恢復）—— 真事故，dreaming 正確 surface。

## Enforcement Layer Map（2026-07-02 owner 指令「不要疊床架屋」落地）

每個 concern 只有一個 enforcement owner。新增約束時**先查此表挑既有落點**，不開新 runner/cron/hook file：

| 層 | Owner 機制 | 管什麼 | 現駐 checks |
|---|---|---|---|
| **L1 機械不變量** | project/user `.claude/settings.json` hooks + `scripts/git_hooks/pre-push`（單一 runner）+ `.github/workflows/` | 每 turn / 每 push 必須成立的格式性約束 | Stop: project final-text、user-global receipt-gated task-completion speech、save_session_state；PreToolUse deny（`pretooluse-bash-optimizer.sh`，單一 deny 清單）: worktree remove --force、zeabur deploy 直呼、整檔讀 canonical JSON、**共用 main checkout 上的 `git commit --amend`**（2026-07-10 補；amend 假設「HEAD 是我剛做的」，主 checkout 多 actor 併發時不成立 — 曾覆蓋他人 commit message 並吞掉其在途檔案；worktree 內 amend 不擋）；pre-push: encoding sweep + silent-fallback baseline；CI: provenance、encoding、silent-fallback、**pytest**（2026-07-10 補；此前約 1700 個測試在 CI 零執行，兩個紅燈爛數週。**零憑證下必須全綠** — 這性質本身擋掉 import-time side effect 再爬回來；why 見 error_log 同日兩條 entry）；**cron wrapper manifest**（2026-07-10 補；`scripts/tests/test_cron_wrapper_manifest.py` — 改了 `scripts/cron_*.sh` 卻沒跑 `sync_cron_wrappers.py --apply`，`config/cron_wrapper_manifest.json` 的 sha256 就對不上 → CI 紅。launchd 執行的是 `~/.volpred/bin/`，CI 看不到那條機器本地路徑，manifest 是唯一可驗證的耦合證據）；**tree-clean**（2026-07-10 補；pytest.yml 內 `Assert the suite mutated no repo state` step — 「測試寫 canonical state」整個 class 的唯一 owner。判準不是「哪些檔算 canonical」而是「跑完測試 checkout 有沒有變」。**只放 CI 不放 pre-push**：開發機的 cron 本來就會改那些檔） |
| **L2 營運存活** | `check_alerts`（hourly piggy-back，單一 alert registry）+ email dedup | 「X 還活著/新鮮嗎」 | release gap / draft low / host cron fail / knowledge stale / paper stale / push backlog / **wrapper_drift**（2026-07-10 補；live `~/.volpred/bin` 副本 ≠ repo canonical → 你的編輯根本沒上線。收編進既有 `_check_piggy_back_drift` 的 `wrapper_missing` 回報路徑，不新增 script/cron） |
| **L2b 派工失敗** | `dispatch_supervisor/alerts.py`（daemon 內建，唯一 owner — 2026-07-05 明確化） | hourly dispatch 的失敗/掛/額度/認證 alert | completion_failure / hang / quota（outage-scoped，一次事故一信）/ auth / orphan / loop_crash。`host_cron_fail` **刻意不覆蓋** supervisor（legacy log 已凍結）；dashboard health_cron 只量 daemon 存活（dispatch_state.json mtime），不量成敗——成敗歸這層 |
| **L3 改善迴圈** | `loop_health`（fast）+ `dreaming_review`（slow，propose-only） | 「loop 有沒有在變好」 | 4 指標 + 5 detector；事故經 error_log 結構化 entry 餵進來，不另建 watchdog |
| **L4 行為指引** | CLAUDE.md（頂層 mandate）→ `.claude/rules/`（path 觸發）→ memory（背景 why）→ skills（SOP） | 需要判斷的行為 | 同一 concern 在 L4 內也只佔一個主位，其他位置放 pointer |

**「測試不得寫 canonical state」的三道防線分工**（2026-07-10 三振後定案，勿再加第四層）：
- **預防** = `volpred.ops.canonical_write.guard_canonical_write()`，接在 writer 上（不是每個 caller），env 會被 `subprocess` / `uv run` / 孤兒孫程序繼承。**鎖是例外**：`shared_lock.sandboxed_lock_path()` **重導向**而非 raise，因為受測程式真的需要一把 fcntl 鎖才能跑完（raise 會刪掉覆蓋率）。判準：受測碼需不需要這個 side effect 才能跑完？需要→重導向，不需要→raise。
- **偵測（本機）** = `tests/conftest.py::_forbid_canonical_state_mutation`，指名是哪支測試。它盯一張硬編清單，**天生會漏**（三振中漏了四條路徑）。
- **不變量（CI）** = pytest.yml 的 tree-clean step。判準不是「哪些檔算 canonical」而是「跑完測試 checkout 有沒有變」。**這才是 class-level owner**；上面兩層是輔助。**不要**複製到 pre-push（開發機 cron 本來就改那些檔，會誤報）。

**收編規則**：
1. 新 invariant → 落 L1（既有 hook/runner 加 check），不建新 hook file。
2. 新 freshness/liveness 檢查 → 落 L2（alerts.py 加 entry），不建新 cron。
3. 新失敗模式偵測 → 落 L3（dreaming 加 detector），不建新 patrol script。
4. 行為被機械化（L4→L1）後，同 commit 把 L4 的長段 prose 縮成一行 pointer；why 留 error_log。
5. 違反此表 = 疊床架屋，code review / dreaming 應標 finding。

**前例**：encoding sweep（2026-07-02）正例 — 收進既有 pre-push runner + CI，零新層；final-text hook（同日）修正案例 — hook 上線同 commit 未收編 CLAUDE.md 長段，後補（見 error_log 14:25 entry）。

**pytest gate 的教訓（2026-07-10）**：一個 gate 只要沒有任何 job 在執行它，它就等於不存在（同日「幽靈欄位」是同一病灶：reader 讀一個沒有 writer 的 key）。而且**「本機零憑證跑綠」不蘊含「runner 跑綠」**：本機綠了才開 push trigger，第一次真實 ubuntu run 仍 12 紅 —— 剩下的耦合是 OS 與工具身分（`rg` 未宣告相依、macOS-only wrapper、只存在於一台機器的 binary 路徑），不是 secret。**新 gate 一律以「一次真實 CI run 變綠」為開通條件，不接受本機綠燈代打。** 其中兩個測試更在 Linux 上「因為錯誤的理由而通過」（腳本提早 exit 0，從未執行受測程式碼）—— 沒跑到受測碼的綠燈比紅燈更危險。
