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
memory_governance / persistent_alert / unfiled_incident_class（WS-F3：alert 同
dedupe key ≥2 次但 error_log 無立案 → 提「此 class 未立案」；訊號源 =
`storage/ops/incident_candidates.jsonl`，由 alerts.py 寄信路徑 append）/
observation_ledger_breach（WS-F5：`storage/ops/observation_ledger.json` 觀察項
逾期未決策 = breach；CLI `volpred ops observation`，permanent 項免 deadline）/
orphaned_experiment。每個 fail-open（warn 後 skip）。**清單以
`scripts/dreaming_review.py::DETECTORS` 為準**，本檔數不進位時以程式為真。
輸出 `storage/ops/dreaming/<date>.json` + 滾動 `baseline.json`（per-signature 連續 run strike count）。

## Auto vs Propose — 硬邊界（研究誠實 + 永遠修流程不修資料）

讀 dreaming report 時依 `remediation` 欄判斷：

- **AUTO（一律安全，dreaming 自己做）**：寫 dated report、append `autonomous_decisions.jsonl`、寄 email。
- **AUTO-DISPATCH（低風險衍生狀態，建修復 task）**：actuator 自 2026-07-12 **預設開啟**。`auto_dispatch` finding（如 missing retry / orphan）在 warn 即進 `storage/next_tasks.json`。`--dry-run` 才不派工。
- **PROPOSE-ONLY（治理檔不自動改寫，但**自動開工單**）**：`docs/error_log.md` / `.claude/rules/*` / `CLAUDE.md` / `storage/memory/knowledge.json` / `docs/refactor_plan_*` 這些檔 dreaming 永不自己寫。但自 2026-07-20（boss telegram「為什麼要我看？你自己處理」）起，propose_only finding **首見即進 `storage/next_tasks.json`**（severity → priority：critical=P2 / warn=P3 / info=P4），由 hourly dispatch 派 agent 判斷後決定是否改治理檔。**接手的是 agent，不是老闆。**
- **HUMAN-ONLY（唯一的人工出口）**：`remediation="human_only"` = destructive 或需要 policy 決策者拍板。這類不自動派工、會出現在 email 的「需要你決策」欄。**數量長期應趨近 0**；不是 0 就代表有東西該被機械化而還沒。

### 為什麼 propose_only 不再等三晚

舊版讓 propose_only 連續出現 3 晚才開單，理由是「持續存在才是訊號」。問題在於**那三晚的等待隊列是老闆的信箱**：期間它被算進「需要你看 N」。等著看一支 cron job 是不是還在 exit 1，不是值得佔用一個人早晨的判斷，那是一張工單。所以等待被**取消**，不是被搬家。

## 對外音量：寄信閘門 = 「有人得動手嗎」（2026-07-19；2026-07-20 修正）

`needs_human_attention(finding)` 是 dreaming 唯一的對外音量判準（接受 DreamFinding 或其 `to_dict()`，規則只有一份實作），順序由強到弱：

1. `severity=critical`（Three-Strike 種子，動不動根是 policy 決策）→ **一律寄**。
2. `quiescent`（底層訊號在最近一個 run interval 內未推進 = 已停火、正在自清）→ 不寄。
3. 其餘只有 `human_only` 要人；`auto_dispatch` 與 `propose_only` 都已有機器出口。

報告 `counts` 因此多四個讀數：`actionable` / `machine_handled` / `quiescent` / `human_only`（`machine_handled` 與 `quiescent` 互斥，可相加），
`main()` 的閘門是 `escalations or actionable_new`。**靜默 ≠ 黑洞** —— 報告照寫、
`autonomous_decisions.jsonl` 照記、skip 理由印在 cron log。

**quiescent 的定義與唯一 owner**（`_is_quiescent()`，2026-07-19 重構）：
「底層訊號在最近一個 `DREAMING_RUN_INTERVAL_HOURS`(=24h，cron 05:25 日跑) 內有沒有推進？」
同一個問題、三種證據來源，依可靠度排序：

| 情境 | 證據 | 判定 |
|---|---|---|
| 有前一輪 marker | **相對**：marker 未推進 | quiescent |
| legacy baseline（無 marker 欄） | advance 未知 | 保守 hold，下輪自我修正 |
| **首見**（無前值） | **絕對**：marker 距今 ≥ 一個 run interval | quiescent |

第三列補於 2026-07-19（boss email-12144）。舊版只有相對式，於是「初見即已停火」的 alert
必吵一次、隔晚才靜音；當時記成「已知邊界」，理由是補它會形成雙 owner。**那個理由是錯的**
—— 它把相對式誤當成 quiescence 的定義本身。定義是「一個 run interval 內沒推進」，相對式
只是它在有前值時的特例；首見改問同一判準的絕對形式，仍是同一個 owner，不是第二套判定。
`reconcile()` 兩條分支都委派給 `_is_quiescent()`，有 test 鎖住不得散回去。

## Three-strike 升級

一個 signature 連 **3 次** dreaming run 都出現 → severity 升 `critical`、email level=critical。這是 `docs/refactor_plan_<topic>.md` Three-Strike 根治的種子。dreaming 不自動建 refactor_plan（屬 docs/，propose-only）—— 主線程開檔。

## 主線程收到 dreaming email 時做什麼

收到信 = 至少有一項需要人（escalation 或 live 治理 proposal）；信裡標了「機器已派修復 task」
/「已停火、自清中」的項目是背景資訊，不用動手。

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
| **L1 機械不變量** | `.claude/settings.json` hooks + `.claude/hooks/pretooluse-bash-optimizer.sh`（單一 deny 清單）+ `scripts/git_hooks/`（4 hook + 1 helper）+ `.github/workflows/` | 每 turn / 每 commit / 每 push 必須成立的格式性約束 | **逐條清單見下方 L1 實況盤點（4 張 AUDIT 表）**——此格刻意不再列散文清單：2026-07-20 盤點發現它漏了 3 個 hook / 4 條 deny / 1 個 workflow / 全部 5 個 git hook 檔（A8 finding）。散文清單維護不了，改由 `scripts/audit_enforcement_map.py` 機械比對 |
| **L2 營運存活** | `check_alerts`（hourly piggy-back，單一 alert registry）+ email dedup | 「X 還活著/新鮮嗎」 | release gap / draft low / host cron fail / knowledge stale / paper stale / push backlog / **wrapper_drift**（2026-07-10 補；live `~/.volpred/bin` 副本 ≠ repo canonical → 你的編輯根本沒上線。收編進既有 `_check_piggy_back_drift` 的 `wrapper_missing` 回報路徑，不新增 script/cron） |
| **L2b 派工失敗** | `dispatch_supervisor/alerts.py`（daemon 內建，唯一 owner — 2026-07-05 明確化） | hourly dispatch 的失敗/掛/額度/認證 alert | completion_failure / hang / quota（outage-scoped，一次事故一信）/ auth / orphan / loop_crash。`host_cron_fail` **刻意不覆蓋** supervisor（legacy log 已凍結）；dashboard health_cron 只量 daemon 存活（dispatch_state.json mtime），不量成敗——成敗歸這層 |
| **L3 改善迴圈** | `loop_health`（fast）+ `dreaming_review`（slow，propose-only） | 「loop 有沒有在變好」 | 4 指標 + detector 清單以 `dreaming_review.py::DETECTORS` 為準（硬編數字已兩度 drift）；事故經 error_log 結構化 entry + incident_candidates.jsonl（F3）餵進來，不另建 watchdog |
| **L4 行為指引** | CLAUDE.md（頂層 mandate）→ `.claude/rules/`（path 觸發）→ memory（背景 why）→ skills（SOP） | 需要判斷的行為 | 同一 concern 在 L4 內也只佔一個主位，其他位置放 pointer |

### 出站通道矩陣（2026-07-20 WS-H2；對老闆的每一種出站訊息 = 一個 cadence 一個 owner）

老闆收信量**只降不升**。新增任何對外班次（email / Telegram）前先查此表：同類訊息已有 owner 就收編進去，
不開第二班。歷史教訓：token 曾同時掛三個 spec（host cron email + 已停用 cloud trigger + session cron 落檔），
boss 定期信曾 boss_report（4h 六班）+ work_summary（6h 四班）日收 ~14 封 —— WS-H2 全部收斂如下。

| 通道 × 用途 | 唯一 owner | cadence | 備註 |
|---|---|---|---|
| Telegram · 互動回覆 | telegram responder（`telegram_responder.sh` 派發） | 事件驅動 | 先回覆再 complete（memory `feedback_responder_reply_before_complete`） |
| Telegram · 逐程序進度回報 | `scripts/progress_report.py` | 每個工作程序 | 唯一 owner（老闆 msg 796）；宣稱完成必附實測 |
| Email · 定期營運報告 | `scripts/boss_report.py`（job `boss_report_4h`） | 08:10 / 14:10 / 20:10，20:10 = `--daily-close` 日結（已併退役的 work_summary_6h） | 唯一的定期 boss email；host crontab 舊行 `10 */4` 須用 `install_host_crontab.sh` 對齊 |
| Email · token 用量報表 | `scripts/token_report_email.py`（job `token_report_daily`，wrapper 先跑 token-usage-maintain 落檔） | 每日 08:00 一封 | token 唯一排程與唯一 email；`token_usage_daily_report`（cloud）與 `token_usage_daily`（session cron）已除役 |
| Email · alert / 異常 | L2 `check_alerts` registry（`send-alert` CLI 同一 EmailNotifier 出口） | 事件驅動 + email dedup | 新 freshness 檢查落 L2，不開新信 |
| Email · dreaming 摘要 | `dreaming_review`（寄信閘門 = `needs_human_attention`） | 每日 05:25，靜默班次不寄 | 見上方「對外音量」節 |
| Email · skill 修改通知 / 重大決策 | 主線程手動 `send-alert` | 事件驅動 | per memory `feedback_skill_autonomy` / `feedback_email_on_major_decisions` |

違反（同 concern 第二個寄信者 / 第二個班次）= 疊床架屋，處置同收編規則第 5 條。

### L1 實況盤點（2026-07-20 WS-F1 全量重盤；由 CI 機械守）

下面四張表**不是文件，是被機械比對的清單**。`scripts/audit_enforcement_map.py` 會從磁碟重建同樣四份 inventory 並 diff；不一致就 exit 1，掛在 `.github/workflows/knowledge-provenance.yml` 的 `audit` job。**新增／移除任何 hook、deny、CI job、git hook，必須同 commit 改這裡**，否則 CI 紅。

#### L1-a Claude Code hooks（`.claude/settings.json`；`settings.local.json` 目前無 hooks 區）

<!-- AUDIT:HOOKS -->
| 事件 | matcher | owner script（repo 相對路徑） | 擋什麼 / 做什麼 | 觸發時機 |
|---|---|---|---|---|
| `SessionStart` | `*` | `scripts/auto_start_codex_loop.sh` | 冪等啟動 detached `codex_loop.sh`（非 gate，是 bootstrap） | 每次 session 開始 |
| `SessionStart` | `*` | `scripts/warm_tcc_authorization.sh` | macOS TCC 授權預熱。**已是 legacy**：repo 2026-07-02 搬離 Desktop 後根因已消失，腳本自述現為 no-op/降級路徑 | 每次 session 開始 |
| `UserPromptSubmit` | `*` | `.claude/hooks/email_pool_reminder.sh` | `next_tasks.json` 有 pending `email_reply` 時注入提醒，防止互動 session 略過老闆回信去做 feature | 每個互動 prompt |
| `Stop` | `*` | `scripts/save_session_state.sh` | 落 session state 快照 | 每次 turn 結束 |
| `Stop` | `*` | `scripts/hooks/enforce_final_text.py` | turn 以 tool call 收尾、無最終文字回報 → block stop（3-strike 後升級的機械層） | 每次 turn 結束 |
| `Stop` | `*` | `scripts/hooks/enforce_fire_receipt.py` | dispatch fire 有產出卻沒寫 `fire_receipt.py` → block stop（2026-07-16：14 天內 186/266 fire 漏 receipt） | 每次 turn 結束 |
| `PreCompact` | `*` | `scripts/save_session_state.sh` | 同上，compact 前保存 | context compact 前 |
| `PreToolUse` | `Bash` | `.claude/hooks/pretooluse-bash-optimizer.sh` | **L1 deny 清單唯一 owner**（7 條，見 L1-b）+ 非 deny 的指令改寫／提示 | 每次 Bash tool call |
| `PreToolUse` | `ScheduleWakeup` | `scripts/hooks/deny_wakeup_interactive.py` | 互動 turn（非 autonomous fire）禁用 ScheduleWakeup；fail-open | 每次 ScheduleWakeup tool call |
| `PreToolUse` | `Read` | `scripts/hooks/read_context_budget.py` | 無 limit/offset 的整檔 Read 補預設行數上限（token 紀律，非安全 gate） | 每次 Read tool call |

盤點註記：`.claude/settings.json` 與 `.claude/settings.local.json` 的 `permissions` 皆**只有 `allow`（5 / 91 條）、`deny` 為空陣列**。真正的 deny 全在 L1-b 的 hook 層，不在 `permissions.deny`——查 deny 時不要只看 settings。`scripts/hooks/` 另有 `commit_message_guard.py`、`git_mutation_guard.py` 兩支**未直接註冊為 hook** 的模組（由 bash optimizer 呼用）；`.claude/hooks/run-compact-bash.sh` 同樣未註冊。

#### L1-b PreToolUse deny 規則（8 條）

key = deny 訊息開頭到第一個 `（` 或 `。` 為止（audit 用同一規則從磁碟重建）。

<!-- AUDIT:DENY -->
| deny key | owner | 擋什麼 | 為什麼 |
|---|---|---|---|
| `禁止在 dispatch fire 內 spawn headless agent` | `pretooluse-bash-optimizer.sh` | fire 內 `claude -p` / `agy -p` | fire 有 3000s hard cap，研究 agent 要 20-60min → 三次 `hang_killed`（2026-07-12）。改走 `compute_queue.py enqueue-agent` |
| `禁止 git worktree remove --force` | `pretooluse-bash-optimizer.sh` | `git worktree remove --force` | K1032 / K1618 誤刪未合併實驗。改走 `merge_worktree.sh` |
| `禁止直呼 zeabur deploy` | `pretooluse-bash-optimizer.sh` | `zeabur deploy` 直呼 | 部署須走 `deploy-zeabur-safe.sh`（鎖 service ID） |
| `禁止整檔讀取 feed.json / knowledge.json` | `pretooluse-bash-optimizer.sh` | `cat`/整檔 reader 讀 canonical JSON | token 紀律；`jq`/`grep`/`head` 不受攔 |
| `禁止裸跑 codex exec` | `pretooluse-bash-optimizer.sh` | 裸 `codex exec` | 2026-07-11 卡 >30min 撞 hard cap。改走 `codex_exec_bounded.sh --timeout` 或 compute queue |
| `共用 main checkout 禁止裸 Git mutation` | `pretooluse-bash-optimizer.sh` | 共用 main checkout 上的 stage/merge/checkout/ref mutation | reference-transaction hook 只能在 ref 階段擋，太晚。改走 `git_writer_lock.py commit`。registered linked worktree 不受攔 |
| `禁止用 git commit -m 內嵌非 ASCII` | `pretooluse-bash-optimizer.sh` | `git commit -m` 內含中文/emoji | strike 3；shell 會產出非 UTF-8 message，push 後只有 force push 改得掉＝不可回復。改用 `-F /tmp/msg.txt` |
| `hook:scripts/hooks/deny_wakeup_interactive.py` | 該 hook 自身 | 互動 turn 的 `ScheduleWakeup` | 該 tool 回應會被模型當回合終點，用戶問題被吃掉（2026-07-02 五犯） |

#### L1-c CI（`.github/workflows/`，5 workflow / 5 job；全部 `push`(main) + `pull_request` + `workflow_dispatch`）

<!-- AUDIT:CI -->
| workflow 檔 | job id | 跑什麼 step | 擋什麼 |
|---|---|---|---|
| `experiment-artifacts.yml` | `artifacts` | Resolve base commit → Gate experiments added or modified | 新增/修改的實驗必須帶齊 artifact |
| `knowledge-provenance.yml` | `audit` | Validate knowledge.json provenance baseline；Validate next_tasks.json status vocabulary baseline；**Validate Enforcement Layer Map**（2026-07-20 本次新增） | jq/Edit 繞過 Python writer 的手改；map 過期 |
| `pytest.yml` | `pytest` | 裝依賴 → 蓋 sentinel → Validate feed audience consistency → Run test suite → Assert the suite mutated no repo state | 測試紅燈；**tree-clean**＝「測試寫 canonical state」整個 class 的唯一 owner。cron wrapper manifest 由 `scripts/tests/test_cron_wrapper_manifest.py` 在此 job 內執行（不是獨立 workflow） |
| `silent-fallbacks.yml` | `audit` | Audit silent fallbacks | 新增裸 `except: return []` 類靜默 fallback（baseline 制） |
| `source-encoding.yml` | `audit` | Audit source encoding | mojibake / 非 UTF-8 原始碼 |

#### L1-d git hooks（canonical = `scripts/git_hooks/`；`.git/hooks/` 為安裝副本，兩者現逐 byte 相同）

無 `core.hooksPath` 設定（`git config --get core.hooksPath` 空），故 Git 讀的是 `.git/hooks/`；`scripts/git_hooks/install.sh` 負責同步。audit 會在有 `.git/hooks/` 的機器上額外比對部署一致性（CI 上 `.git/hooks` 不存在，該檢查自動跳過）。

<!-- AUDIT:GITHOOKS -->
| 檔名 | 擋什麼 | 觸發時機 |
|---|---|---|
| `pre-commit` | Gate -1 hook deploy/source 原子性；Gate 0 candidate-index 測試相依閉包（`audit_test_imports.py` 不得被自己移除）；Gate 1 source encoding；Gate 2 silent fallbacks。**只審本 commit 觸及的 `.py`**（tree-wide 會讓 A 被 B 的半成品擋住） | `git commit` |
| `pre-push` | Gate 1 encoding／Gate 2 silent-fallback／Gate 3 test-import，**逐一對「被推的 commit 自己的 tree」**跑（非工作區）。權威層：`--no-verify` 與 supervisor auto-commit 都躲不掉 | `git push` |
| `prepare-commit-msg` | commit message 非 ASCII/非 UTF-8 位元組。**`--no-verify` 不會跳過此 hook**，故這是不可回復錯誤的真正 gate；PreToolUse 那條只是更早的 UX 警告 | 每次產生 commit message |
| `reference-transaction` | `refs/heads/main` 或主 worktree HEAD 移動時，必須已持有 canonical Git-writer lease（只驗不取，避免與 Git ref lock 反向鎖序死結） | 任何 ref transaction |
| `git-writer-lease-verify.py` | 上一條的驗證實作（helper，非 Git 事件本身） | 由 `reference-transaction` 呼用 |

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
