# Error Log — 活教訓索引（Root-Cause Class Index）

> 本檔 2026-07-14 由 **7,739 行 / 433 條 entry** 壓縮為「活教訓索引」（WS4c，見 `docs/refactor_plan_token_ops_waste.md` §WS4c）。
> 目的：讓「實驗前必讀 error_log」重新可執行 —— 掃 class 標題找到你這類任務，讀該 class 的「規則 + 機械 gate」兩行即可，不必讀舊全文。
> 歷史 entry **全文逐字保留、未刪改**於 `docs/error_log_archive/{2026-Q1,2026-Q2,2026-Q3}.md`（原檔出現順序）。
> 回滾點：`git tag error_log_pre_compaction`（= 壓縮前的完整 7,739 行 commit）。

## 如何使用本索引（實驗 / 修復前必讀入口）

1. **開跑 `experiments/` 或動手修 bug 前**：掃下方〔Class 目錄〕→ 命中你的任務類型 → 讀該 class 的 **規則** + **機械 owner** 兩行。
2. **規則已機械化的 class**：信任 gate（CI / hook / ratchet / audit 會擋），你只需知道它存在、別繞過它。
3. **查某條歷史 incident 全文**：看該 class「代表 incident」行末的 archive 檔（`Q1`=`2026-Q1.md`，`Q2`=`2026-Q2.md`，`Q3`=`2026-Q3.md`），用日期在該檔內 `grep '^## <日期>'`。
4. **踩了新坑做完根因修正**：在對應 class 加一行代表 incident（日期 + 一句 + `Qn`），把全文 entry 追加進當季 archive；季度結束把當季 entry 併入 archive。
5. **anti-stacking**：一個 concern 只有一個 enforcement owner；修復要收編進既有 gate，不要每次疊一層新機制（見 §H 與 `loop-health-and-dreaming.md` Layer Map）。

## Class 目錄（TOC）

| # | Class | 復發強度 | 機械化 |
|---|-------|---------|--------|
| A | 並發 / dispatch / daemon 生命週期（orphan・killpg・setsid・競態・hang） | 極高（~75+） | 部分 |
| B | Git owner / canonical-write / `git add -A` 中毒 / 排程 writer 不 commit | 高 | 是（CI + hook） |
| C | Worktree merge / 實驗檔遺失 / 審查認證 | 中 | 是（merge gate） |
| D | Silent fallback / fail-open guard / exit-code masking | 極高（~123） | 是（pre-push + CI baseline） |
| E | Dedup / narrative-arc / 重複內容 / recycling / K-id 撞號 | 高（~24） | 部分 |
| F | Timestamp / 發布日 / provenance / vintage 造假 | 中（~28） | 部分 |
| G | Lookahead / DM-HAC / MDD / 方法論硬規則 | 高 | 是（ratchet + audit） |
| H | Turn final-text / notify-first / boss-facing report / alert-as-task | 高 | 是（Stop hook） |
| I | Chart / CJK 豆腐字 / renderer domain model | 中 | 部分 |
| J | Alert / dreaming / detector false-positive / 轟炸 | 高 | 部分 |
| K | Pool / release cadence / starvation / 池枯竭 | 中 | 部分 |
| L | Paper narrative / 裁決 / review-cert SHA-pin / 規格漂移 | 中 | 是（certify gate） |
| M | Source-of-truth drift / registry / supabase / 系列身分 | 中 | 部分 |
| N | FB / social publishing 冪等與附圖 | 低 | 部分 |
| O | Data freshness / 交易日曆 / RV 隔夜跳空 / 交易成本 | 中 | 部分 |
| P | Test / CI / guard leakage / hermetic | 高 | 是（CI tree-clean） |

3-STRIKE 總覽：**26 條**帶明確 `3-STRIKE TRIGGER` 標記（含大小寫變體共 36 條提及）；Q2=12、Q3=14、Q1=0。分布見文末〔§3-STRIKE 分布〕。

---

## A. 並發 / dispatch / daemon 生命週期

**規則**：任何 fire / dispatch / agentic CLI 逾時處理都必須用 process-group 語義（`killpg`）殺整棵子孫樹，且 spawn 必有界（不可 fire 內無界 spawn）。單一 owner + lock + hang detect + orphan cleanup 是設計前提，不是事後 patch。看到「雙擁有者競態」「孤兒堆積」「killpg 被拒」就直接三層重構，不等 strike 3。
**規則 2 — 父程序的壽命必須 ≥ 子程序的工作**：≥10 分鐘的 Codex 工作，**Codex 自己就是 job**，不要在它上面蓋一層 Claude agent 當父程序（父等子 → 燒完 cap；父先走 → 子成孤兒）。review / 裁決 → `scripts/codex_review_job.sh`；≤10 分鐘、你會坐著看完的短問答 → `scripts/codex_exec_bounded.sh`。`enqueue-agent` 只給「Claude 需要自己動手」的長工作，不給「Claude 去叫別人做事」。
**規則 3 — 未執行的工作單必須可修，已執行的必須不可修**：queued job 的 spec 用 `compute_queue.py amend / cancel`（只吃 `status=queued`），**不要手改 queue JSON**；agent brief 在 enqueue 當下已凍結成 snapshot，改原始檔沒有用。
**機械 owner**：`com.volpred.dispatch-supervisor`（`scripts/dispatch_supervisor/*.py` 常駐 daemon）取代舊 shell wrapper；改完必 `bash scripts/reload_dispatch_supervisor.sh`（禁裸 `kickstart -k`）。
**代表 incident**（全文見 archive）：
- 2026-06-23 **3-STRIKE META** 全系統缺並發紀律：codex_loop 24-orphan 堆積 + release burst + K-id 撞號同源 — Q2
- 2026-07-12 **3-STRIKE** fire 內 spawn 無界 agentic 子程序（hang_killed ×3）— Q3
- 2026-07-12 **3-STRIKE** agentic CLI 逾時只殺一個 pid，孫程序活著繼續寫 — Q3
- 2026-07-13 codex worker setsid 逃出 process group，killpg 殺不到（同根因第 2 次）— Q3
- 2026-07-12 hang 告警是瞎的：雙擁有者競態，輸家寄信 — Q3
- 2026-07-11 supervisor 說它 SIGKILL 了 worker，但 killpg 被拒（屍體 / 權限）— Q3
- 2026-06-30 daily_update 結尾 sync 在網路 blip 無限 hang（持有 lock）— Q2
- 2026-05-29 hourly-dispatch keychain auth 3-strike RESOLVED（permanent）— Q2
- 2026-07-14 23:15 Codex 審查被塞進 Claude agent，父 turn 結束把它殺在寫裁決前一秒（跑完 20 分鐘、844KB transcript、零產出）— 修法早存在（`codex_review_job.sh`）只是沒路由過去 — Q3
- 2026-07-14 23:20 queued job 的 spec 改不了 → 「enqueue 後修 brief」是跟 worker 賽跑且輸了沒人告訴你（晚 48 秒 = 一輪 30 分鐘 xhigh 審查報廢）；修：enqueue 凍結 brief + `amend`/`cancel` — Q3
- 2026-07-21 11:30 **FIXED** stale reaper 看不見 compute queue，把在飛的 task 放回池等著被二度派工：`task_pool_claim.py cleanup` 只用 `claimed_at` 年齡判 stale，但長研究 job 的 timeout 是 5400s（遠超 `--stale-hours 2`）→ dispatch 到 compute queue 的 task 每 2h 被 flip 回 `pending`，重新進 starvation lockout 名單。實例：`assign_5aa9d5f5` 於 07-19 06:50 與 07-20 03:12 連兩次 `auto_release_stale_2h`，其 agent job 全程在 queue 上正常執行；本班 dispatcher 又把它列進「本班只能從這裡挑」，差一步就開第二個 worktree + 第二個 agent job（21 個孤兒 worktree 的一條來源）。**修**：`cleanup` 增 `_compute_job_alive()` guard — task 帶 `compute_job_id` 且該 job 狀態仍在 `{pending,queued,running,claimed}` 就跳過回收，並回報 `skipped_compute_in_flight`；job 進終態或 job 檔讀不到則照原邏輯回收（fail-open，不因 IO 錯誤把 task 永久釘住）。dispatch 到 queue 時用 `annotate --set-json compute_job_id=...` 立 receipt。commit 見本 fire receipt — Q3
- 2026-07-23 **3-STRIKE CONTAINED** `supervisor hang_killed` 12 次其實混了三類事件：真正的無界子工作、外部 SIGTERM，以及正常進展但撞 3000s work cap 的過大 task。生產者先把 own-deadline kill 分為 `supervisor work_timeout` WARN，只有孤兒／驗屍失敗繼續算 `hang_killed` CRITICAL；根因的 pre-claim work-admission 與 unchanged-timeout 禁重試規格見 `docs/refactor_plan_dispatch_work_admission.md`。未實作 admission gate 前只能稱 contained。
- 2026-07-14 22:20 **RESOLVED** agent-job 的認證牆被歸檔成「研究失敗」：repo 有兩處 spawn `claude -p`，只有 supervisor 的 `worker.py` 分得出 auth / quota / transient，`run_agent_job.py` 只看得到 exit≠0 → K1709 rev3 重審 agent 5 秒死於 `Not logged in`（同時段 supervisor fire 認證正常＝暫時性刷新競態），queue 標 failed，followup brief 派下一班 fire「去 worktree 翻可搶救成果」— 那裡什麼都沒有，agent 從未啟動。**修**：分類邏輯抽成單一 owner `scripts/dispatch_supervisor/failure_class.py`（worker.py 改引用，行為不變）；runner 用同一份定義，auth → 有界重試（3 次 / 120s，且只在剩餘 budget 塞得下正事時），真失敗 → 一如既往不重試；`failure_class` 寫進 metadata receipt，compute_queue 據此把 auth 類 followup 改成「re-enqueue，不要 triage、不要記任何研究裁決」。Gate: `scripts/tests/test_agent_job_auth_class.py`（break-then-verify 確認會咬）。commit b4b2db64d — Q3

## B. Git owner / canonical-write / `git add -A` 中毒

**規則**：每個會寫檔的流程（排程 writer、compute job、驗證副產物、auto-commit）都必須有明確 Git owner，用 **explicit-path** commit，**禁止 `git add -A`**（會捲進他人在途檔、毀掉 before/after、洩漏未完成工作）。共用 main checkout 的 Git mutation 是一整段 transaction：ownership/HEAD recheck → stage/stash → commit/merge/ref adoption → index/stash 收尾必持同一把 common-dir lease；只鎖最後一個 `git commit` 仍是 race。「排程 writer 沒 commit」是類別漏洞，逐案補 `git commit` 不收斂 → 立 class-level gate。**反向陷阱：ownership guard 若用「dirty」當「別人在編輯」的 proxy，會 latch 成死鎖** —— 被排除在寫入集外的路徑，同一個 flag 也把它排除在 commit 集外；當這個 job 就是該路徑唯一的 committer，「這輪跳過」＝「每輪都跳過」。這些檔沒有人手作者，dirty 幾乎只代表「sibling daemon 寫了還沒人 commit」。**真正的判別器是 lock + parse（`volpred.ops.machine_churn`），不是 dirty flag**；且「git 答不出來」(`unprobed`) 必須與 dirty 分開，否則「我不知道」會被升級成「有人擁有它」。
**機械 owner**：`src/volpred/ops/git_writer_lock.py` + `scripts/git_writer_lock.py`（跨 process、stable inode、finite timeout、exact-path/index rollback）統一包 PHASE-Z / scheduled writers / reaper / worktree merge / Codex backfill；common-dir `reference-transaction` hook 對 main ref fail-closed（raw commit / `--no-verify` / update-ref 都須 inherited lease），pretooluse 提早擋 shared-main 裸 commit。agent compute job 強制使用 registered linked worktree，不再預設 main；push 另綁 immutable audited SHA。
**代表 incident**：
- 2026-07-23 **CONTAINED** PHASE-Z foreign incident `785413a1dbd4d6c0`：`CLAUDE.md`、`CONTEXT.md` 與三份 `docs/agents/*` 跨檔治理變更已連續四班無 owner。兩份 immutable quarantine refs 與 main working bytes 逐檔 blob identity 完全一致，原 worktree liveness 已 dead；內容交叉驗證為同一 coherent ChangeSet（CLAUDE 三個 pointer 都有對應文件，CONTEXT 術語與 accepted ADR-0001–0004 一致），故用 explicit-path transaction 收養為 `aa20cd9fa`。原始 `foreign_incident --check` 回讀 `closeable=true`、五路徑 `still_dirty_in_main=false`、`deferred=[]`；Phase-Z／foreign incident／slot-budget 106 tests 通過。這次只算 contained：quarantine + persistent incident + admission control 已防止靜默與資料遺失，但「跨檔輸出從產生起就由 durable ChangeSet 原子擁有」仍待 Operations Core 正式接管。
- 2026-07-23 **3-STRIKE FIXED** PHASE-Z receipt 警報連續 8 天 fire、dreaming 連續 5 晚升級，但最新實例的「agent 產出」其實全是 agent 結束後才由 supervisor/worker 改寫的 `storage/ops/agent_jobs/**`、`compute_queue/**` 與其他控制面狀態。`_is_machine_state` 已是 namespace 單一 owner，Stop hook 也正確排除它；只有 `run_phase_z` 仍先用 `dirty_now - baseline` 把 during-fire machine state 塞進 `owned`，導致「agent 沒留 receipt」假歸因，且繞過 machine-churn 的 lock+parse gate。修成 machine state 不論何時變髒都走 `_classify_machine_churn`，只有非 machine path 能進 receipt subject/alert；回放 7/22 16:21 的 12-path commit 後，5 個 queue/job state 全歸 churn、agent-owned=0。規格與驗證：`docs/refactor_plan_phase_z_receipt_attribution.md` — Q3
- 2026-07-15 **3-STRIKE 根因收斂**：6/28 保留現場證明直接 producer 是未解的 `stash pop/apply` conflict（非「兩個普通 commit 產生 AUTO_MERGE」）；共享 main 的多 writer 是結構性 enabling condition。盤點當下 misrouted K1695 compute agent 確實直接在 main 落兩個 commit。修成 common-dir transaction lease + 不可重建 capability FD、atomic installed main/HEAD ref hook、canonical symbolic-main gate、repo-external launcher + project pretool、compute cwd fail-closed；移除 broad `merge=ours`，guard 不再 reset/checkout 作者 bytes；補 concurrent writer、crash stale-token、late-staged collision/index rollback、descendant FD cleanup 與 audit→push immutable SHA regression — 詳見 `docs/governance/2026-07/git_single_writer_transaction.md`（原 6/28 entry 在 Q2，並非不存在）
- 2026-07-10 **3-STRIKE（第 4 次）** PHASE-Z auto-commit `git add -A` 沒有作者概念 — Q3
- 2026-07-10 **3-STRIKE** canonical-write gate round 3：一支一支修不收斂，改立 class-level CI gate — Q3
- 2026-07-13 populate_upcoming_events 寫 config 不 commit：排程 writer 缺 commit 步驟第 3 例 — Q3
- 2026-07-13 排程 writer 沒有 Git owner 是類別漏洞，不能逐案補 `git commit` — Q3
- 2026-07-14 論文驗證副產物連續多班無主（reproduce 就地重寫 volatile 欄位）— Q3
- 2026-07-13 compute job 執行失敗後，已生成產物沒有 Git owner — Q3
- 2026-07-14 20:10 pre-commit Gate 0 從**當前分支 HEAD** 取可信 auditor → base 落後的 worktree 全面 commit 死鎖（agent 成果裸躺工作區）；改從 main 取（hook 與 auditor 同源），順帶堵掉「先 commit 弱化 auditor、下個 commit 就受它審」的篡改路徑 — Q3
- 2026-07-15 00:0x **同一死鎖 class 的第二次**：上一條只修了 Gate 0 的 auditor，Gate 1/2 的 audit 工具與 baseline 仍從**提交當下的工作區**讀 → base 落後的 worktree 沒有 baseline 檔就再次全面 commit 死鎖，而且 CI 連紅 3 次（`tests/test_pre_commit_trusted_auditor.py` 從沒綠過）。**教訓：修死鎖 class 要一次掃完 hook 驅動的每一個工具，只修觸發那次的那一個 = 把死鎖往下一道 gate 搬。** 現在每道 gate 都從 hook 的部署來源 ref 取工具；唯一例外是 baseline（吃 staged 版，否則「接受新 finding」變成永遠 landable 不了的另一種死鎖）。連帶根因：`audit_silent_fallbacks.py` / `audit_source_encoding.py` 用 `Path(__file__).parents[1]` 推導 repo root，從 trusted ref 抽到暫存檔就指到 `/tmp` → 補 `--root`（`audit_test_imports.py` 早有此旗標，是它一直沒被複製到姊妹工具）— Q3
- 2026-07-15 02:xx **同一 class 的第三次（正是上一條預言的「往下一道 gate 搬」）**：上一條把 **pre-commit** 路徑的 auditor 改成從 trusted ref 取樹（補 `--root`），但 **push 路徑**沒一起修 —— `cron_git_push_backup.sh` 仍用預設 root 掃**活的工作區**。共享 checkout 上 codex-vscode 未提交的 3 行 silent fallback 於是把 **4 個乾淨 commit 擋了整晚**，而 alert 寫著「HEAD 帶 3 個新 silent fallback」——**HEAD 一個都沒有**（實證：工作區 new=3、HEAD new=0，同 baseline）。gate 判的是「即將 push 的 commit」，就不能拿工作區當證據。**修法**：`audit_silent_fallbacks.py` 加 `--rev`（把該 rev 的受審子樹抽到 temp dir 當 `--root`；只抽 `scripts/` `src/volpred/` `.claude/hooks/`，因為 `paper/` 帶絕對 symlink 會被 tarfile data filter 擋），wrapper 傳 `--rev HEAD`。**教訓再強化：這個 class 的 sweep 單位是「每一條會讀樹的 gate 路徑」，不是「每一支工具」** — Q3
- 2026-07-16 **3-STRIKE（同 latch class 第 4、5 次）** daily_update dirty-guard 把自己鎖死：dirty → 排除寫入 → 同 flag 排除 commit → 唯一會清它的那輪被自己擋掉。`frontend-v2-fix/data/strategy_metrics.json` 是純粹型態（PHASE-Z churn 掃描不及巢狀 repo → **無人搭救**）：**11 天沒 commit、每輪 exit 0、零 alert**；`feed.json` 只是被 PHASE-Z 每小時當 churn 收掉才顯得間歇（7/15 14:00、7/16 08:03 兩次擲硬幣輸掉 → 整輪 abort）。前 3 次同 class（phase_z deleted-path「every fire, forever」7/12 修；`work_log.json` / `next_tasks_archive/`「foreign for 35 fires」`a8ecca38c`）都是**往硬編清單追加一檔**的 per-file patch，故本次改為移除 latch 本身：classifier 收斂為單一實作 `volpred.ops.machine_churn`（lock gate + parse gate），`scheduled_writer_commit` 新增 `probe_dirty_outputs`（dirty / unprobed 分離）+ `adoptable_churn`（churn / conflict 二分）。**guard 未弱化**：live flock / 內容不可解析 / probe 失敗照擋。順帶查證推翻兩個既有敘事：`git_push_backup` 同分鐘競態**不存在**（它只 push 既有 commit，classified `no_repo_tracked_output`），`host_cron_fail` 13 天跨度是**泛用 signature 聚合了不同根因**（guard 7/13 才誕生）。**教訓：一個「安全地不動它」的排除，若沒人接手就是永久資料停更 —— 而且它長得跟健康一模一樣（exit 0）。** 全文：`docs/fix_56ddf72b_dirty_guard.md`
- 2026-07-19 **3-STRIKE 外部裁決（本 class 第 6+ 次）** PHASE-Z 有 40 個檔連續 **78 班**沒人收。**先推翻原假設**：不是「post-commit 測試閘門紅擋住收班」——那道閘門在 commit 之後跑且只發警報，且那條紅燈（`test_orphan_reaper.py::…symlink_and_ignored_paths`，`StopIteration`）現在**沒人修就自己綠了**（66 passed，`f0350b91294c..HEAD` 對該檔零 commit）＝ 環境相依 flaky，而 78 班遠早於它。堆積是 `owned = dirty_now - baseline` **照規格運作的必然結果**。因已達 3-STRIKE，改走**外部第二意見**（老闆指定 Claude Desktop；headless fire 無法驅動 GUI 且 repo 無 bridge，改用 `codex exec` 異廠模型，已揭露此替代）。外部裁決：**集合差不是 ownership，只是「這段時間內首次被觀察到變髒」**，在共享 checkout 上有三個必然誤判（開班前已髒但本班又改 → 貢獻遺失；human/codex 改 → 誤算本班產出；同 path 並行 → 無法拆 diff）；歷次修復的共通失敗是**用結果特徵（目錄／suffix／mtime／receipt／測試變綠）反推 producer identity**，`orphan_namespaces.json` 的「在 `experiments/` 裡就可收編」即 semantics-as-provenance（K1380 那 8 個含 `*_INVALID_*` 的檔正是反例）。**核心盲點逐字**：「你一直在讓 cleanup layer 解 ownership。Ownership 必須由 execution isolation 產生，不能由 cleanup layer 事後推理。」**採納方向**：D1 停止一切「再加一個 recognizer／收編條件」型補丁；D2「不確定 ⇒ 自動 checkpoint 到 immutable ref，絕不自動進 main」（dirty working tree **不是** durable preservation）；D3 streak 過門檻改建**持久 incident + scheduler admission control**（沒有 actuator 的 CRITICAL 只是紅色日誌——這就是 78 班零行動的結構原因）；D4 終態走 producer-scoped workspace。**機械 gate**：`scripts/tests/test_phase_z_ownership_class_gate.py`（釘住 provenance-guessing 位置census＋namespace 清單，新增第 4 個就紅；D2 缺口以 xfail-strict 釘住，落地自動要求轉綠）— 全文：`docs/governance/2026-07/phase_z_ownership_external_review.md`
- 2026-07-16 PHASE-Z candidate 被 gate 擋下後只保留 3 次短期 baseline；重試上限一到便丟失原 fire 的 ownership 證明，修 gate 的下一班反而只能把 20 個正確產物視為 foreign，最久卡 54 班。修成 git-dir durable failed-closeout receipt（exact paths + SHA-256 / deletion state）；下班前只重試 byte-for-byte 未變的原產物，任何後續修改 fail-closed。同期抓到 `market_closure_detect` 空檔其實是 host crontab 錯誤重導向且與 LaunchAgent 雙觸發；canonical schedule 改為 launchd-only — 全文：`docs/error_log_archive/2026-Q3-phase-z-failed-closeout.md`

## C. Worktree merge / 實驗檔遺失 / 審查認證

**規則**：worktree agent 只產 `experiments/kXXX/`，禁改共享狀態；主線程用 `scripts/merge_worktree.sh` 合併，**禁 `git worktree remove --force`**（L1 hook 擋）。實驗進 main 的唯一門票 = `experiments/<kid>/review_verdict.json` 且 sha256 綁「現在這份 bytes」（PASS 後又改 code 也擋）。裁決檔一律由 `verdict-template` 產生，不手抄。**保留 branch ≠ 收割成果**：clean tree 只證明沒有未提交檔案，不證明那些 commits 進了 main；移除 unmerged checkout 就是在製造下一個殭屍。**任務引用的資源會消失，必須有東西去 reconcile**——否則任務永遠 blocked 又永遠不關單。
**機械 owner**：`scripts/merge_worktree.sh` → `scripts/experiment_gates.py certify`；`worktree-merge-verification` skill；`scripts/reclaim_stale_worktrees.py` 的 **unmerged gate**（dirty 與 unmerged 兩道都 fail-closed，只放行「clean 且已進 main」）；`scripts/daily_checkup.py::check_worktree_reconcile`（open 任務 ↔ 磁碟 reconcile，branch 也沒了 → critical）。
**代表 incident**：
- 2026-07-21 K1623 arm C：review subagent **執行了它被指派審查的實驗碼**（違反「先審後跑」），產出未經 queue / gate 的 artifact — Q3
- 2026-07-19 **k1709 殭屍任務**：任務指向的 worktree 消失了，任務卻沒有任何機制發現 —— 自 07-14 起 blocked 5 天，不會被 dispatch 也不會被關單。根因是 **task pool 與磁碟從來沒有 reconcile**：`reclaim_stale_worktrees.py` 的安全條件只查 dirty，漏查 merged，於是「clean 但未合併」的 checkout 可被回收、branch 隨後也消失，而指著它的任務無人聞問。裁定結果 3 個 commits 其實已進 main（無遺失）。同次修復發現另外 4 個 worktree 共 9 個 commits 正處在同一個懸崖邊上，被新 gate 攔下 — Q3
- 2026-07-12 **3-STRIKE（K1032 class）** `.claude/worktrees/` 底下「獨立 repo」對 merge 的破壞 — Q3
- 2026-07-14 Merge 認證聲稱可用裸 `python3`，卻在解析子命令前 eager-import 專案套件 — Q3
- 2026-07-14 Review 對移動中的樹裁決：verdict 沒綁 commit SHA，一落地就過期 — Q3
- 2026-07-13 orphan branch：三個 commit 全被平行實作取代而丟棄 — Q3
- (K1032 原始教訓：merge_worktree 誤判「no commits」但 reflog 有 commit → 檔案遺失) — Q2

## D. Silent fallback / fail-open guard / exit-code masking

**規則**：不可用 silent fallback / try-except swallow / 靜默降級掩蓋 schema 或流程缺陷；護欄不可放在 fail-open 的 `try` 內（等於沒護欄）。hook / wrapper 不可把 shell pipeline exit code 當 tool outcome（pytest false-green）。silent fallback **當場修**，不丟下一班。
**機械 owner**：`.claude/rules/no-silent-fallback.md`（規則本體）+ pre-push silent-fallback baseline sweep + CI silent-fallback check（baseline 只准變少）。
**代表 incident**：
- 2026-07-19 review_verdict.json 全 FILL 佔位仍被 compute job 標 completed（k528 一審「存在≠內容」）→ `_review_verdict_unfilled` 內容後置條件 + test；同日互動 session 兩度把 `cmd | tail` 的 pipeline exit code 當 tool outcome（claim/complete 在 commit 失敗後照跑）— 關鍵步驟禁 pipe 尾接、驗證一律無管道直測 — Q3
- 2026-06-22 ~ 06-23 silent-fallback batch fix（多筆，governance sweep）— Q2
- 2026-06-23 **3-STRIKE** 測試 hook 假報「Tests passed」（exit-code masking）— Q2
- 2026-06-20 **3-STRIKE** host_cron_fail false-critical on exit-as-findings — Q2
- 2026-07-14 05:45 護欄放在 fail-open 的 `try` 內，等於沒有護欄 — Q3
- 2026-07-14 06:20 dedup gate 說 `clean`，其實是「我沒看」（STRIKE 2）— Q3
- 2026-07-10 canonical-write：silent ignore of `sync_article()` 回傳（K1021 同根因）— Q2

## E. Dedup / narrative-arc / 重複內容 / recycling / K-id 撞號

**規則**：派寫作 agent 前主線程做 3-layer 查重；同邏輯 arc 換外殼也算重複（arc-dedup）。dedup gate 若 fail-closed default 會變 8-day 內容黑洞（要 fail-open + audit trail）。K-id 配號前 `ls experiments/` + `ls .claude/worktrees/`，禁雙 agent 同號。鬼打牆根因在**釋出端**非研究端。**實驗做完沒寫進 knowledge.json = 對 dedup 完全隱形**（查重查不到 → 系統宣稱「全飽和」還去重跑同一題）——「寫 KB」不是收尾禮儀，它是 dedup 的資料前提。
**機械 owner**：3-layer dedup（`.claude/rules/publishing.md`）+ arc-dedup gate + `.claude/rules/dedup-gate-audit.md`；release_dedup TTL 別凍死全池。**KB 覆蓋率**：`scripts/reproduce_check.py` 的 `KNOWLEDGE_UNRECORDED` issue（經 `daily_checkup.py` reproducibility 維度曝光）。**member_qa 重複答覆**：`volpred.ops.content.assert_member_qa_publish_allowed`（發佈端硬 gate，唯一守在讀者可見面）+ `questions.claim_question_for_research` / `ensure_member_qa_task` 的 `question_similarity` 意圖端 gate + `answer_internal_question` 冪等；regression pin = `tests/test_member_qa_duplicate_gate.py`。
**代表 incident**：
- 2026-07-19 **STRIKE 2｜同一會員同一問題被完整研究並發佈兩次**：`yaoxk1431` 的「30 年每年成長 15%／7%」只改數字重問，`e79a7097`→`mile_d84aa7d0`（07-12 發佈）、`3e258ba2`→`mile_0205a444`（07-19 發佈）。根因是**全系統一律拿 `question_id` 當「同一個問題」的識別鍵**（`ensure_member_qa_task` docstring 明寫 "Dedupe key is question_id"）：新 row = 新 id = 不算重複。**為什麼前次修法沒擋住**：(a) 2026-03-31 修的是**並發**（同時被claim兩次），不是**重複**（隔一週再問一次），兩者根本不同軸；(b) 當日 `33cf84b8f`/`dde8e1666` 加的 `question_similarity()`/`find_duplicate_question()` 方向對，但兩道 gate 都守在**意圖端**（建 task、claim），主線程手寫文章直接呼叫 publish 即可整段繞過；(c) member_qa 被**明文排除**在發佈端查重外（`content.py` `_RELEASE_DEDUP_AUDIENCES={general,research}`、`publisher.py` topic-cluster type-exempt），即「讀者實際看到的那個 artifact 是唯一沒有 owner 的環節」。修復＝在 `publish_milestone` 加發佈端硬 gate（同 question_id 已有 published/scheduled 答覆即拒發，只認 `details['supersedes']` 具名續作通道）+ `answer_internal_question` 冪等（不重複綁文章、`answered_at` 只記首答）— Q3
- 2026-03-31 **STRIKE 1｜同上 class（當時未立案）**：同一會員的台灣經濟提問 7 小時內被答兩次（`mile_530a28bc` / `mile_42ee876c`，前者事後 unpublished）。當時只當作並發競態處理、**沒有建立 class 條目**，因此沒有 3-STRIKE 計數、沒有升級路徑；2026-07-19 再犯時系統對「這是老問題」完全無知——這正是老闆問「為什麼**又**重複」的結構原因。教訓：class 沒立案 = 第二次發生時等於第一次 — Q1
- 2026-07-19 K-id 撞號 STRIKE 2（k1732）：interactive session 掃 worktrees 取 max+1，撞上 registry 已預留題目（registry last=1739 vs experiments/ 最大 1718 的必然缺口）→ 機械化：`experiment_gates.py` certify 新增 `kid-registry` gate（K≥1719 無預留擋 merge，讀 canonical main registry）+ `kid_reserve.py reassign` 修復撞號 + rule 一行；被擠掉的題目查實為已完成 dup（k_etf_vs_etf_fragility_2026_06_14），順帶關掉重複生成的 pool task — Q3
- 2026-07-14 136/1252 已完成實驗從未進 knowledge.json（對查重隱形）；同時 `research_program.md` 把 `experiments/k1536/` 誤標成 K1537 並編造「K1536 已被預留」的理由，衍生出一個要 scaffold 幽靈 K1537 的 stale task — Q3
- 2026-06-10 **3-STRIKE** 文章 narrative-arc 重複（K1449/K1091）→ arc-dedup 三層重構 — Q2
- 2026-06-24 arc_dedup gate 過粗 entity granularity → K1547 被 K1417 誤擋 — Q2
- 2026-06-23 **3-STRIKE** 並行 cron agent 撞同一 journal-discovery 題 + K-id 雙佔 — Q2
- 2026-06-23 release_dedup_skipped 21 天 TTL 凍結 46/46 draft（「可以發文了嗎」）— Q2
- 2026-06-08 Refill_task_pool 8th belt — research-saturated K narrative-arc dup — Q2

## F. Timestamp / 發布日 / provenance / vintage 造假

**規則**：時間戳一律取自實際 `date` 命令輸出，不可臆造（時間也是數據）。事件研究的「發布日」不可用猜的（污染已發佈數字）。總經修訂序列 OOS 必用 real-time vintage，且不得在首次 ALFRED release date 前評分（否則改稱 final-vintage pseudo-OOS，撤回 real-time claim）。文章 cite 的數字必對得上 git-tracked artifact（「曾經跑過」≠「現在可復現」）。
**機械 owner**：`.claude/rules/experiments.md`（PIT/vintage 硬規則）+ `scripts/validate_knowledge_provenance.py`（CI invariant）+ `src/volpred/memory/provenance.py`。
**代表 incident**：
- 2026-07-23 **root_cause_fixed_and_verified** K741 first-Friday proxy 更正第一輪只修 `content/details`，首頁／SEO `description` 與兩個含舊數字的 title 仍服務 195 次、0.498/1.488、3 倍與「高 VIX 效果消失」；`article_correction` 現以 fail-loud exact-match 同時擁有 title/description/content/details，七篇 published 全走同一 gateway 回讀 Mirror+Supabase，retracted 篇不動。驗證：七個 public URL=200、feed-sync 無 drift、published reader-visible 舊 claim/anti-AI 掃描為空、correction/update-gateway tests 全綠 — Q3
- 2026-07-19 「官方日曆」也會選錯日：`event_dates.release_dates` 對同月多筆 FRED entries 取 `max()`，把 off-cycle 修訂/特發誤當 NFP headline（6 個月份錯），k528「顯著→不顯著」翻轉在正確日期下不成立（p≈0.025 仍顯著）→ 18 條文章更正整批作廢禁用；根修 = per-month `min()` + 13–110 天 cadence fail-closed（2013 關門 17 天壓縮與 2025 缺月 76 天皆為真實日曆）+ 6/6 live 驗證 + regression tests。教訓：接了 primary source 不等於選對 row — 選擇規則本身要有對抗性驗證 — Q3
- 2026-07-16 daily digest 發佈前近失：把 7/15 VIX/OVX 收盤誤當成已反映 7/16 最新攻擊、把 60 日係數寫成 4,693 日全樣本統計，並誤稱 WTI 79.5 已觸發 98.26 前高門檻；跨模型 gate 在 publish 前攔下，未流到讀者端。已把 as-of／rolling-window／trigger-current 雙值規則寫進 publishing canonical（全文：`docs/governance/2026-07/daily_digest_cross_vintage_nearmiss.md`）
- 2026-07-12 CPI 事件研究的發布日是「每月 13 號」猜出來的（已發佈數字受污染）— Q3
- 2026-07-09 Paper2 headline TWII γ=0.272 UNTRACEABLE，實際 ≈0.109（provenance-sweep）— Q3
- 2026-07-11 NFCI vintage / back-stamp（K1655：2011 才公開卻從 2004 評分）— Q3
- 2026-05-27 mile_91af7c48：文章數字歷史真實但 K562 patch + rerun 從未 commit — Q2

## G. Lookahead / DM-HAC / MDD / 方法論硬規則

**規則**：Lookahead 是最高風險 —— code 要有明確 `signal.shift(1)`；forward-label target 訓練列須 `target_end < forecast_origin`。DM 的 HAC lag 不可只用 `h-1`（h=1 時退化成 iid）；先量 loss differential 的 acf 再決定 lag。raw MDD 不可跨不同曝險比較（scale artifact）；正 exposure-matched gap 仍需對照 phase-randomization null。QLIKE 用 actual/predicted；套件限制 ≠ 模型無效。**完整硬規則見 `.claude/rules/experiments.md` §Methodology 硬規則。**
**機械 owner**：`scripts/experiment_gates.py run`（自檢 / compute queue）+ `scripts/experiment_gates.py certify`（worktree merge 的 stdlib-only MDD 硬 gate）+ `scripts/tests/test_dm_hac_lag_ratchet.py` + `scripts/tests/test_mdd_scale_artifact_ratchet.py` + `audit_dm_hac_lag.py` / `audit_mdd_scale_artifact.py`（凍結 baseline 只准變少）。
**代表 incident**：
- 2026-07-15 **K841 方法修復**：local `range(h)` 在 h=1 只留下 gamma0，七格策略平方報酬風險 DM 都是 iid；重建舊 returns 後用 canonical Bartlett-HAC lag=13，七格 t 全變但 `|t|>3` 分類未翻。完整重跑另修正開盤才知道的權重誤套隔夜 gap、每晚平倉再開倉卻只在 ratio 改變時計成本、S5 漏 stock cost、Monday 檔漏 Saturday-AM。舊「S1 最佳」及「夜盤避險普遍不可行」因此撤回/收窄；`feed×5 + knowledge×2` 實為兩篇文章與同一筆 knowledge 的字串命中。稽核器已補 `range(h)` regression 並退休此站點。
- 2026-07-15 **K1386 三重方法缺陷修復**：h=1 local DM 的 autocovariance 迴圈空轉；兩份來源各 10 個完全相同重複日期使 inner merge 形成 2×2 膨脹；HAR 最後一個 IS feature row 誤吃第一個 OOS target。改用 canonical `dm_test`（lag=11）、duplicate identity check + one-to-one merge、IS target boundary 後，n_eval=1,097，DM t=3.437/3.452，原 NULL 質性結論不變但舊精確數字作廢。連帶教訓：`feed×N` 的 grep 命中數不可當文章數；本案 6 次命中只在一篇文章。稽核器已補 `max(1,h)` / `max(h,1)` h=1 退化 regression。
  - 2026-07-16 **K1386 frozen slice 跨平台 hash 漂移**：同一份 source file SHA、4,119 列與 one-to-one merge 在 macOS/ARM 得 `45160d...`、Linux/x86 CI 得 `500376...`；根因是 pandas 預設 C float parser 可有 1 ULP 平台差。兩個 frozen CSV reader 改用 `float_precision="round_trip"`，canonical slice hash 更新為 `9bce8a...`；完整重跑兩次所有 results/NPY/PNG byte-identical，QLIKE 八位小數、DM 判定與 NULL 結論均未變。class sweep 的另一個 analysis-slice pin K841 原已使用 round-trip parser。
- 2026-07-14 **K1709** 重犯 K1701 教訓：ratchet 抓得到，但它在 worktree 裡沒牙齒 — Q3
- 2026-07-15 **MDD class 交件機制補洞**：K1695 招牌 drawdown protection 是 exposure artifact：raw ΔMDD +12.61pp（13/13 市場為正）在同曝險口徑下變 **−0.87pp（只剩 7/13）**；`compare_max_drawdown` 對 13/13 市場亮 `exposure_mismatch`（vol ratio 0.61–0.68，遠超 20% 門檻），`k1695_results.json` 卻無任何 exposure 欄位。時間線訂正：K1695 commit `a20099d99`（7/12 14:45）早於 auditor/baseline `a3858edbe`（7/13 08:17）與 runner gate `1f6097af4`（7/14 13:20），故交件當時不存在「audit 抓得到卻沒跑」；隔日 sweep 才找到 k1695.py 5 個 production `RAW_COMPARISON`，並凍入 legacy baseline。後續真正的 enforcement gap 是 merge `certify` 只驗 review SHA，不跑 MDD gate；現已補上 trusted-main merge gate。數值證據：`storage/ops/k1695_exposure_artifact_verification.md`（文末原 certification 狀態已訂正）；完整根因：`docs/governance/2026-07/mdd_merge_certification_gate.md`。連帶 paper `vt-trend-following` Table 5 + 第三項 contribution 暫緩。
  - **2026-07-15 05:30 hourly-05 class sweep 補記 —— 這個 artifact 已經流到讀者端，不只卡在實驗與論文**：feed 有 3 篇 published + 2 篇 archived 文章的結論建立在 raw 口徑上（`mile_0d595dfb`「13 個國際市場實測：美國 VIX 是全球股票的通用避險信號嗎？」整篇、`mile_2d4edb65`、`mile_ee473d5a`）。**數字本身沒造假（raw ΔMDD 確實 13/13 為正），被推翻的是「這是抗跌保護」的因果解讀** —— 這正是 scale artifact 最陰險的地方：它不會讓 audit 抓到假數字，它讓真數字撐起假結論，於是機械 gate（掃 code）永遠掃不到已經發出去的散文。教訓：**MDD class 的 blast radius 必須從 code 一路掃到 feed，不能只掃 `experiments/**`**。paper hold 寫進 `storage/paper_pipeline_status.json` 的 `awaiting_correction`（vt-trend-following）；文章回溯更正 = task `feed_correction_k1695_exposure_artifact`（P1，blocked 等認證，因為沒 null 分佈前只能說「約等於零」不能說「顯著為負」）。
  - **2026-07-15 07:15 hourly-07 collect_completed 收尾（closure）**：rerun 補上 circular-shift/phase-randomized null（common p=0.559、inception p=0.212 均未拒絕、Holm 0/13）+ no-timing 常數減碼 reference（複製 59–85% raw gap、matched gap ~0），commit `bdf6b451f`。主線程獨立重算兩樣本 byte 對齊；fresh-context code-reviewer 判 PASS（7/7 checklist 無 blocking defect）→ `experiments/k1695/review_verdict.json`（PASS，pin 現行 sha）+ certify PASS。knowledge append 更正條目 `8f80b2ee`（撤回舊 PASS `f4a73c83`）。paper 決定＝**撤除第三 contribution**（非把 null 包裝成 finding），routed to `paper_body_vt_trend_withdraw_k1695_contribution`。`feed_correction_k1695_exposure_artifact` 認證後已解除 blocked→pending P1。primary-path Codex re-verify 已 enqueue（`agent-brief_k1695_codex_reverify-be9cd6`）作 belt-and-suspenders。**流程觀察**：knowledge store append-only、無 in-place retract CLI，舊 PASS 條目仍在庫（靠 correction 條目 + `content_correction_scanner` 覆蓋）——若日後同類撤回頻繁，值得補 supersede 機制。
  - **2026-07-15 09:xx hourly-09 reader-facing 回溯更正完成（closure）**：`feed_correction_k1695_exposure_artifact` 執行完畢。3 篇 published（`mile_0d595dfb` 招牌篇、`mile_2d4edb65`、`mile_ee473d5a` VT 完全指南）於 feed.json `content` 前置「編者更正聲明」——保留原數字未刪，明寫舊結論被推翻＋推翻理由（曝險假象：VT 實現波動 0.61–0.68× B&H，同曝險口徑平均 ΔMDD −0.87pp/7-of-13、null p=0.559，一個固定減碼策略即複製 85%）；嚴守強度邊界（不寫「擇時有害」、不宣稱 inception +4.96pp 被否證）。2 篇 archived（`mile_f2e26f43`/`mile_9eaadbd1`）加「更正註記」。anti_ai_gate PASS；`storage/reports/<id>.json`（存在的 2 檔）同步；`supabase_sync full` 推平台（5 篇皆入 sync log、reconcile no_drift 1810=1810）。blast radius 從 code→paper→feed 全數收口。
- 2026-07-19 **K1623 rev2**：`dm_hln` 的 `for lag in range(1, h)` 在 h=1 空轉 → 40 個 DM 全無 HAC。改 canonical `dm_test`（lag=10）後 **31 格 |t| 縮小、9 格放大**（4 個 acf(1)<0 的全部放大），3 格 5% 判定翻面。再次坐實 **漏 HAC 是雙向誤設，不是單向灌水**；稽核時先讀 loss differential 的 acf 再判方向，不可預設「本來就 null 所以安全」— Q3
- 2026-07-12 DM helper 在 h=1 退化成 iid，K565 的 Harvey PASS 被推翻 — Q3
- 2026-07-13 K1702 把 MDD/vol 比率誤當尺度不變，原 Codex gate 因此失效 — Q3
- 2026-07-11 FEVD 取錯軸：`decomp[-1]` 把「最後一個變數」當成「最後一個 horizon」（K865 作廢）— Q3
- 2026-07-13 K1701 巢狀 QLIKE 用 expanding raw DM 承載 NULL，修正後只能判 inconclusive — Q3
- 2026-06-16 K445 article OOS 用 origin-aligned forecasts（off-by-one / lookahead 風險）— Q2
- 2026-05-06 K547 lookahead audit sweep：`weights * ret` 同期 pattern 跨 11 檔 — Q2

## H. Turn final-text / notify-first / boss-facing report / alert-as-task

**規則**：互動 turn 收尾必須是**給用戶的文字**（email 不能替代 session 內回覆）；ScheduleWakeup 互動 turn 禁用。不要把修復中間狀態 / 待辦丟給老闆（alert body 寫「已自動修復」非「建議老闆行動」）；alert 預設自動變 task。回報禁列「還需要你做 X」。
**機械 owner**：`scripts/hooks/enforce_final_text.py`（Stop hook）+ `scripts/hooks/deny_wakeup_interactive.py`（互動 turn 擋 wakeup）；alert→task remediation bridge；逐程序進度回報格式 = `scripts/progress_report.py`（`--status done` 沒 `--verified` / `--verified-cmd` 直接 exit 1，白話欄貼指令也擋）。
**代表 incident**：
- 2026-07-15 老闆 msg 796/808/810 「發現問題→設計任務→下輪解決，我無從得知做完沒、驗證沒」→ 回報格式機械化：`done` 與 `queued` 是不同 status 不是不同講法；驗證欄白話先於指令 — Q3
- 2026-07-02 14:25 **3-STRIKE** 「turn 結尾無文字回報」同日第三波 → Stop hook 機械化 — Q3
- 2026-07-02 13:58 turn 結尾無最終文字回覆（同日復發，3-STRIKE TRIGGER）— Q3
- 2026-07-14 12:41 CI 紅燈 notify-first：把修復中間狀態丟給老闆 — Q3
- 2026-07-13 01:10 警報把工作派給老闆：24/27 個 alert body 是寫給人看的待辦清單 — Q3
- 2026-07-13 21:45 「修好 CI」宣告後老闆連環收 failure 信（修復不完整 + 未 push）— Q3

## I. Chart / CJK 豆腐字 / renderer domain model

**規則**：每篇 reader-facing 文章要有真圖表，不可用 ASCII / 文字框冒充；中文圖必設 CJK 字型（有 helper 還要有 enforcement，否則復發）。懶人包 renderer 是 data-bound plan.json 渲染，**主線程 LLM** 只草擬文案 / 選 evidence path，**絕不重寫渲染 code**（每篇都讓主線程 LLM 即興重寫 = domain model 錯誤）。〔2026-07-15 boss directive 補充：codex bespoke path（`gen_lazypack_codex.py`）是**受控例外** — codex 寫的 per-article 腳本 bounded、存檔、可重跑、receipt 驗證，與本條禁的「主線程即興重寫、無留痕」不同類；現行順位 codex=PRIMARY、deterministic=logged FALLBACK，見 `lazypack-infographic` skill。〕
**機械 owner**：`scripts/gen_lazypack_codex.py`（PRIMARY）+ `scripts/lazypack_render.py`（strict data-bound FALLBACK）+ font enforcement + `lazypack-infographic` skill。
**代表 incident**：
- 2026-07-14 09:07 **3-STRIKE** 豆腐字圖表第三次上線 + CI 時間炸彈測試 — Q3
- 2026-07-13 22:48 CJK 圖表豆腐字第二次復發：有 helper、沒有 enforcement — Q3
- 2026-07-13 19:26 **3-STRIKE** 每篇懶人包都讓 LLM 重寫 renderer（domain model 錯誤）— Q3

## J. Alert / dreaming / detector false-positive / 轟炸

**2026-07-24 root_cause_fixed_and_verified**：B3.7 piggy-back drift assertion
已在 `check_alerts.py` 執行，ledger 卻仍標未完成；live 回讀更固定把健康的
`gmail_poll`／`handoff_regen` 報成 `never_ran`。根因有兩層：schedule 的
`log_path` 指向 domain log／不存在的 storage log，而非 LaunchAgent wrapper 真正含
exit receipt 的 `~/.volpred/logs/*`；共用 banner parser 又只擷取空白前的日期，
把 `2026-07-23 23:50:02 CST` 解成台北午夜，造成 1,445 分鐘假 stale。canonical
schedule 現綁回 wrapper execution log；單一 `job_liveness` owner 同時支援 ISO 與
既有 host-local CST receipt。兩個 RED→GREEN regression 固定 log identity 與 timestamp
語義，48 個 liveness／check-alerts／schedule／wrapper 相鄰測試通過，live
`_check_piggy_back_drift` 回讀由 2 個假 finding 收斂為 `drift_count=0`。

**2026-07-23 root_cause_fixed_and_verified**：dreaming 把 `Claude→Codex failover 已接手（Claude 端：quota）`（dedupe key `31bfa7e7f9289f4c`）的成功降級 telemetry 當成持續故障；七天 10 次的真實 fire 證明 generic persistent/unfiled detector 會為「已成功接手」另開治理工單，與已負責 provider outage 的 `supervisor quota_blocked` 雙 owner。anti-stacking registry 現新增該精確 quota-success title，persistent 與 unfiled 兩個 detector 共用同一 registry；`auth` 與「接手失敗」title 不排除。真實 ledger 回放後 `31bfa7e7f9289f4c` 不再產生 finding，而 `b74691d14763e77c` 失敗路徑仍會被偵測；兩條負向回歸測試鎖住分流。production 回讀另揭露歷史 archive 的非 UTF-8 bytes 會讓 unfiled detector 整體 crash，已改成逐檔 fail-open + warning，並以 malformed-archive 回歸鎖住。

**2026-07-23 root_cause_fixed_and_verified**：`supervisor quota_blocked（額度恢復後自動復工）`（dedupe key `e46b1923cd3787a9`）13 次／15.7 天、跨過三輪 dreaming 後仍被 generic persistent/unfiled detector 重複立案；fresh detector 修前回放仍命中，但 7/22 之後 production receipts 是連續 `codex_failover_recovered`，證明 supervisor 的 outage-scoped dedup、探測與 failover 已是 canonical owner，真正的 outcome loss 另由「接手失敗」title 表達。根因是 anti-stacking registry 只排除成功 failover telemetry，漏掉它所屬的 quota outage notice。現以 exact title 補入同一 registry；真實 ledger 修後回放不再產生 `persistent_alert:e46b1923cd3787a9`，而 persistent/unfiled 兩條負向測試都確認 `Claude→Codex failover 接手失敗（Claude 端：quota）` 仍可見。三振計畫與五步證據見 `docs/refactor_plan_quota_alert_ownership.md`。

**規則**：detector 的 dedup key 必須是 root-cause identity（不是 umbrella / 帶 {hhmm} 的 title，否則 24h dedup 永不命中 → 轟炸老闆）。detector 要看得見自己派的補救任務（否則假 critical）。「N findings 全 severity=critical」是 detector 設計缺陷。無界重試 + snapshot 消耗時機錯 = 每 64 秒連發。
**規則（false-negative 面，2026-07-16 補）**：**探針與復原都要架在 outcome 上，不是架在便宜的中間節點**。凡是**收 → 處理 → 回**的管線（Telegram / Gmail / 發文 / 派工），量「收得到」不等於量「做到了」；處理端死掉時，ingress 心跳會誠實地全綠 —— 「它死了」與「它沒事做」在 proxy 儀器上同形。量末端 outcome 的附帶好處：多個根因（依賴消失 / 額度耗盡 / claim 後卡死）由**同一支探針**覆蓋，不必各立一支。**推論（同日 strike 2）**：event-driven 處理器失敗後若無獨立 driver 重試，復原條件就是「同一個外部事件再來一次」= 把復原責任外包給老闆；retry 也要由**佇列殘留**驅動，不是由事件到達驅動。**且註解裡的安全網要當宣稱查證**（「hourly 兜底」寫在三處、跨多次修改沒人質疑，routing rule 從頭就排除它）。此條與 §D「靜默 fail-open」、control-plane.md「靜默的守門員最危險」同源。
**規則（可終止性，2026-07-18 補）**：**每一個會發 alert 的條件都必須有「它怎麼停」的答案，且答案不得是「人去刪某個檔」**。設計時把停止路徑寫進 docstring —— 寫不出來就是設計缺陷，不是待辦。特別是**用查詢當判準時要先問這個查詢對邊界輸入的值域**：`git log` 對 untracked 檔恆為 false（是「定義上不可能」不是「還沒」），拿它當 resolved/conflict 的唯一判別式，等於造出一個沒有出口的 bucket。同型邊界：已刪除路徑、symlink、被 .gitignore 的檔。
**機械 owner**：`src/volpred/ops/alerts.py`（check_alerts 每小時，condition-based）+ dreaming detector（dedup key = root-cause identity）。
**規則（音量，2026-07-19 補）**：**通知的閘門要判「收件人有事可做嗎」，不是「系統有新資料嗎」**。偵測器的產出天然全是新資料；用新奇度當閘門，等於把機器自己 auto-remediate 的例行工作、以及已停火自清中的條件，全寄給人。已經算出來的「不需要人」判斷（如 dreaming 的 `quiescent`）必須存進 finding 活到閘門那一刻，否則會在別處被用錯的方式重算。
**規則（自主性，2026-07-19 補）**：**已經定位到根因的洞，不得以「已知邊界」的形式寄給老闆** —— 老闆對它唯一能做的動作就是叫你去補，那封信因此仍是「收件人無事可做」的雜訊（同上條音量規則的變形）。報告邊界只在**真的需要人做取捨**時才成立（產品方向 / 治理權衡 / 資源優先序）；「補它要動到既有抽象」是工程判斷，屬機器職責。**推論**：當你寫下「不補，因為會形成雙 owner」時，先反查那個 owner 的**定義**是不是被現行實作綁架了 —— 多數「補它會變雙 owner」其實是「現行實作只覆蓋了定義的一個特例」，把定義抬高一層即可用同一個 owner 涵蓋。
**代表 incident**：
- 2026-07-19 **同日 strike 2（自主性面）**：上一則修好音量閘門後，把 `quiescent` 剩下的洞（首見即已停火的 alert 仍吵一次）寫成「刻意不補的已知邊界」寄給老闆，理由是「補它要另立判定 → 雙 owner（anti-stacking）」。老闆回：「不是叫我做，你判定後就去優化執行啊，立刻重構底層」。**那個理由是錯的** —— 它把「跟上一輪 marker 比」誤當成 quiescence 的**定義**，其實定義是「訊號在一個 run interval 內沒推進」，相對式只是有前值時的特例。把定義抬高一層後，首見改問同一判準的**絕對**形式（marker 距今 ≥ `DREAMING_RUN_INTERVAL_HOURS`=24h），仍是同一個 owner `_is_quiescent()`，不是第二套判定。改：`reconcile()` 兩條分支全委派給 `_is_quiescent()`，並加 test 鎖住判定不得散回 `reconcile`。真實 alert 資料首見重放：7 個 finding 中 2 個（停火 25.3h / 31.2h）靜音、5 個 24h 內仍在燒的照樣送達；今日實跑 3 個首見 finding marker 皆 <10h → 全判活躍（反向鎖成立）。178 tests passed（新增 6）— Q3
- 2026-07-19 dreaming 寄信閘門 `if new_findings or escalations` 判新奇度而非可行動性：老闆收到的 WARN 內含 4 個 actuator 已派 task 的 auto_dispatch + 5 個停火 12.8–46.5h 自清中的 persistent_alert、escalations=0，信裡自己寫著「不需要重構」。`reconcile()` 早算出的 `quiescent` 只擋 strike、算完就丟。改：`quiescent` 升為 finding 欄位 + `needs_human_attention()` 單一音量 owner + 閘門改 `escalations or actionable_new`，信中逐項標「機器已派修復 task」/「已停火、自清中」。真實資料重放確認那封信不會再寄、三振升級路徑未削弱（60 tests）— Q3
- 2026-07-18 PHASE-Z failed-closeout 對 **untracked 檔**產生永久 CRITICAL：被 pin 過又被編輯的 untracked 路徑，dirty（不算 landed）、fingerprint 漂移（不算 unresolved）、`git log --since` 永遠列不到它（不算 carried）→ 必落 conflicts，每小時發一次，**唯一 off switch 是人工刪 `.git/volpred_phase_z_failed_closeout.json`**。老闆隔 25h 被同一則警報點名兩次。改為三 bucket 全可終止（landed / unresolved / **released**）：pin 的 bytes 已不存在 = 沒東西可救，claim 在**發警報的同一趟**就從 receipt 移除，下一趟自然安靜（一個 path 一輩子最多 warn 一次）；`_paths_carried_forward` 降為 advisory，只決定放得多大聲，不再決定能不能結案。同 class sweep 另修兩處無出口狀態：unreadable receipt 改為 quarantine（原本 fail-closed，會讓模組**永遠**再也記不了 ownership 且不出聲）、單一 path 無法 fingerprint 不再連坐整批 receipt。**教訓：2026-07-17 的前一次修法只治 tracked 檔（放寬「已 commit 就別吵」），沒問「有沒有哪類輸入連進入判準的資格都沒有」—— 同一個 bug 的 class 版本因此原樣復發。** gate `scripts/tests/test_phase_z_untracked_closeout.py`（6 條，含 untracked+drifted / untracked+未漂移 / tracked+carried 不回歸）— Q3
- 2026-07-18 dreaming email「建議行動」用 if/else 文案分支修補 —— 老闆糾正一次語氣就多插一個 branch，`level` 判定與文案兩處各自 if，形同遺留產線。改為 `DREAMING_SEVERITY_TIERS` 資料表（severity → level + actions 同源）。**教訓：alert body 的文案分支是遺留來源；「加一級嚴重度」必須等於加一筆資料，不是加一個 if。** — Q3
- 2026-07-16 22:2x host_cron_fail 連續 critical，兩個來源**都不是失敗**：(a) `paper_sync_all` 一次 socket timeout 就 exit 1（同一 flake 也讓當天 digest 的 publish read-back 誤報，實際已同步）→ 修在 `supabase_sync._urlopen` 單一出口加 bounded retry，且**只重放 replay-safe 請求**（GET/PATCH/DELETE + 帶 on_conflict 的 POST；裸 POST 不重放否則複製 row），gate `tests/test_supabase_transient_retry.py`；(b) `daily_update` 偵測到 feed.json 已 dirty、正確拒絕覆寫他人在途編輯，卻用 exit 1 回報 → 與真 infra failure 撞號，alert 建議「chmod +x / 檢查 FDA」完全不相干。**這是 `.claude/rules/alert.md` §Severity taxonomy「Guard-held success 要用 distinct exit code」已寫明、但未落實的第 3 個位置**（前兩個：2026-06-20 exit-as-findings、2026-07-03 push-held）→ 收編既有 sentinel 120（不新建機制），gate `tests/test_daily_update_guard_held_exit.py` 釘住它與 `alerts._PUSH_HELD_EXIT_CODE` 不漂移。**教訓：規則寫進 rules 檔不等於落地——同一 taxonomy 條目已被違反三次，每次都是新 caller 沿用 exit 1。新增任何會 hold/abort 的 guard 時，exit code 的語義分類要與程式同時寫。** 驗證：wrapper 端到端 exit 0；資料實際新鮮（策略全到 7/15 最新收盤），故無 outcome damage — Q3
- 2026-07-16 22:27 **同日 strike 2**：宣告「已修好並驗證」後 41 分鐘，同一通道再次靜默 — responder 純 event-driven（只在新訊息到達時 spawn）、失敗後無重試，額度恢復也不會自己回來；且它三處註解自稱的「hourly dispatch 兜底」**根本不存在**（task-routing.md:40 明排除 telegram_reply）。改由 poll daemon 的 while-loop 兼任 retry driver（佇列殘留 >2min 重 spawn，5min backoff）— Q3
- 2026-07-16 20:33 Telegram poll 全綠但 responder 死透（brew `jq` 消失 FATAL + 前一段 Claude 週額度 exit=1），老闆訊息無人回、只有老闆本人發現；補 `telegram_reply_backlog` outcome 探針（量「有沒有被回」非「process 活著沒」）+ responder 移除 brew `jq` 硬編碼依賴 — Q3
- 2026-07-16 legacy hourly-dispatch 把 EPERM/getcwd/EINTR 硬判成已退役的 Desktop TCC 根因，會寄錯誤 CRITICAL 與誤導處置；改為中性 runtime/filesystem WARN + Codex failover（全文：`docs/governance/2026-07/hourly_dispatch_tcc_copy_retirement.md`）
- 2026-07-01 **3-STRIKE** dreaming-run 7 findings 全 severity=critical + occurrence 灌水 — Q3
- 2026-07-13 21:55 PHASE-Z「沒有 fire 起始基線」warn 每 64 秒轟炸（snapshot 時機 + 無界重試）— Q3
- 2026-07-13 22:10 PHASE-Z title 帶 {hhmm} 使 24h dedup 永不命中 — Q3
- 2026-07-14 01:40 dreaming 把 umbrella alert dedup key 當成 root-cause identity — Q3
- 2026-07-14 09:56 dreaming missing_retry_strategy 假 critical：detector 看不見自己派的補救任務 — Q3

## K. Pool / release cadence / starvation / 池枯竭

**規則**：draft 池不可空、release 節奏不可斷；pool < 4 一次補滿（非一次一個），補池前查 `current_job`、寫入走 flock。pool-empty critical 反覆觸發 = 根因雙修（供給 + 消耗對齊），不是重試。
**機械 owner**：`refill_reader_facing_pool` + release cadence + journal-discovery 冷卻對齊。
**代表 incident**：
- 2026-07-22 general lane 結構性餓死：auto-refill brief 只寫「general article」，卻沒有裁決全域「K 編號／統計方法要 visible」與 general「禁 K-id／裸術語」的優先級；K1597 忠實放入 K-id + QLIKE/DM/Harvey 後被 `_infer_audience` 升為 research，補池任務成功但 general coverage 仍為零。**root_cause_fixed_and_verified**：不放寬 audience gate；新增 `volpred.ops.article_brief.GENERAL_AUDIENCE_BRIEF_CONTRACT`，兩個 task generator 共用同一條 metadata/prose 邊界（精確數字、樣本、視窗、as-of 與統計強度保留；K-id/路徑只進 `details.experiment_refs` / `evidence_source_paths`；成功前回讀 inference 必為 general），並在 publishing rule + feed-publisher skill 補 research-only 適用範圍；generator/refill/audience regression 通過 — 全文：`docs/error_log_archive/2026-Q3-general-audience-brief.md`
- 2026-07-22 `trending_repost_2026_07_18_台股崩跌` 的 scanner seed 虛構台股「崩跌 2953 點（-6.5%）」；writer 才發現 ^TWII 目標日 bar=NaN，證明生成端只有查重、沒有數字來源閘門。**root_cause_fixed_and_verified**：scanner 契約改為量化 prose 必附 `quant_claims`；`refill_reader_facing_pool.py` 在寫 `next_tasks.json` 前逐項回讀 yfinance/FRED，百分比／點數／成交量／金額若缺 spec、缺日、NaN、標的與 ticker 不符、來源不支援或超 tolerance 一律拒絕，並寫 `trending_primary_source_verification.jsonl`（不得把 NaN 當 0/通過）。事故文字回放正規化出 points=-2953、percent=-6.5；24 個直接相關 refiller/scanner 測試 exit 0，含 NaN、標的 identity 與成功 receipt 回讀 — Q3
- 2026-06-14 **Three-Strike** pool-empty critical 反覆觸發 → 根因雙修 — Q2
- 2026-06-14 pool warn 反覆復現 → journal-discovery 冷卻對齊消耗 — Q2
- 2026-06-19 三根因：release pool 枯竭 / member_qa dispatch 誤分類 / M2 供給斷 — Q2
- 2026-07-13 **3-STRIKE RESOLVED**（dreaming persistent_alert e1aa596aac4a2172，連 9 次 5.8d）「發文脫班補救失敗：force-release/refill 皆為 0」— 根因不是補救失效，是**refill 把一整個連載 cluster 塞爆 → 池裡有稿但全不可釋出（同 cluster 節奏鎖）→ force-release 見無 releasable=0、refill added>0 但淨釋出=0**，dead-man 判為雙 0 升 critical。修：`refill_task_pool.py` 加 per-cluster budget，補池「看得見釋出閘門」不再自製單一 cluster 死鎖 + 回歸測試 `test_refill_cluster_budget.py`（commit e96554041，另動 `src/volpred/ops/content.py`）。alert 07-10 已停火、48h 自清；驗證 `remediate_publish_drought.py --dry-run` = no drought — Q3
- 2026-07-16 daily_digest 脫班（boss 點名）— 兩層根因：(a) 上午 09:00–11:47 五班 dispatch 全 quota_blocked（外部）；(b) 下午恢復的三班全被 compute followup 吃掉 — 舊 PHASE A「命中 followup 即本小時派工結束」使 followup backlog 持續時 P1 時效任務被無限餓死（priority inversion，違反 CLAUDE.md「時效 P1 插隊所有 scheduled」）。修：dispatch prompt 加 **PHASE A0 時效 P1 優先**（event_article/trending_repost/daily_digest/user P1 先於 followup；commit 7e1a180ec）；digest 由主線程當場補發（mile_f9c70bd0）— Q3
- 2026-07-16 anti-AI publish gate `_anti_ai_fb_mode` 把所有 general/digest feed 長文誤套 **FB 短文排版檢查**（3.2 段落 ≤4 行、3.4 列表 ≥3 項即 WARN）→ 與 digest 規格「文末必列 5-8 篇精選清單」結構性矛盾，兩檢查恆貢獻 2 WARN、再加任一風格 WARN 即達 3-WARN hard-block。warn-only 遷移期（至 07-13）掩蓋了矛盾，strict 生效後第一篇 digest（07-16 補發）即被擋。修：feed 文章一律 `fb_mode=False`（FB 文案走 fb-publishing 流程不經 publish_milestone）+ regression `test_fb_mode_never_applies_to_feed_items`。教訓：**gate 從 warn-only 轉 strict 前，必須拿受影響 content_type 的真實樣本（尤其規格強制含列表/長段的類型）跑 dry-run 校準** — Q3

## L. Paper narrative / 裁決 / review-cert SHA-pin / 規格漂移

**規則**：單一實驗不直接改 `paper/*/body.tex`（只更新 research_program + knowledge）；≥3 互補實驗 + 用戶 confirm 才進 body rewrite。gating 實驗完成必須機械地產生**裁決義務**；handoff 隊列項禁止複製裁定內容（只放 pointer，否則變第二個會漂移的 SoT）。表面 gate 過 ≠ 語義無漂移。
**機械 owner**：`scripts/experiment_gates.py certify` + `review_verdict.json` sha-pin + `paper_adjudication_gap` alert（`src/volpred/ops/alerts.py`）。
**代表 incident**：
- 2026-07-14 Gating 實驗完成後無人裁決 + handoff 抄到已撤回裁定（差點錯殺一篇 JBF 論文）— Q3
- 2026-07-19 **K1623 reviewer 可靠度**：同一份 code，gpt-5.5 判「no CRITICAL/HIGH」、4 週後 gpt-5.6-sol 判 **FAIL（7 條）**。前輪確認的是**機械正確性**（lookahead / QLIKE 方向 / 索引，複驗仍成立），漏掉的全部是**「README 對人類說的話有沒有被數字支撐」**：識別宣稱無定理支撐、DM 只跑了 2 個 loss 中的 1 個、`range(1,h)` 使 HAC 失效、「多處顯著更差」實際只有 1 格名目顯著。教訓：**「Codex 判 no CRITICAL/HIGH」≠「宣稱與證據相符」** —— claim-vs-evidence 是與 code review **不同的檢查面**，不明確要求就不會被執行；審查 brief 須把 README 宣稱逐條列為受審對象（claim surface 含 README 正是為此）— Q3
- 2026-07-12 K1025_v3 初稿通過表面 gate，語義審查仍抓出四類規格漂移 — Q3
- 2026-07-14 paper snapshot pin 的 auto_adjust 硬規則張力（prg v7 重寫時發現）— Q3
- 2026-05-22 **3-STRIKE** K1380 SPA/RC Test — valid_all joint-mask n_valid=0 結構 — Q2

## M. Source-of-truth drift / registry / supabase / 系列身分

**（2026-07-16 追加，歸本 class：dual task queue + 雙回覆）**
- 2026-07-16 **3-STRIKE 級結構修復（老闆直接下令「該單一關口的就單一關口」）**：`volpred ops assign` 寫入的 `storage/ops/tasks/` queue **無任何 dispatcher 消費**（唯一 reader=手動 claim-next，無人跑）→ 16 任務黑洞 5 天，含結論已推翻仍在排隊的 K1695 舊敘事文章（執行=發錯誤內容）；同晚兩個並行互動 session 對老闆同一則 Telegram（msg877）**矛盾雙回覆**（msg879 排 credit→vol 研究 vs msg880 判 aggregate 版全 NULL），本 session 亦違反 claim-first（先做事先回覆最後才 claim）。**修**：(a) assign 重定向為 next_tasks.json thin wrapper（`append_next_task`，flock）；(b) 存量 17 個非終態 triage（4 終態含 1 deprecated 有害任務 + 13 遷入 canonical queue，credit 題合併雙方判斷成單一 brief）；(c) reply-right guard：`telegram-send --reply-to-task` 對已完成/他人持有任務拒發（break-then-verify 過）；(d) 機械 gate `scripts/tests/test_ops_tasks_receipts_only.py`（先 FAIL 於存量、遷移後轉綠，證明會咬）。設計：`docs/refactor_plan_single_gateway_task_system.md` — Q3


**規則**：文章系列身分 / 成員 / 格式一律讀 machine-readable registry（`config/article_series.json`），禁從標題 / 代號重新推導（無 SoT → 同系列反覆搞錯）。config 是唯一源頭；registry 存第二份 status = dual SoT。Supabase 1000-row cap 要 explicit 處理。
**機械 owner**：`scripts/series_registry.py --audit`（drift 每小時 check_alerts 告警）+ config single-source 規則。
**代表 incident**：
- 2026-07-06 **3-STRIKE STRUCTURAL** 文章系列身分無 single-source-of-truth → 反覆搞錯 — Q3
- 2026-07-14 09:50 series_registry 品牌漂移：registry 存了第二份 status（dual SoT）— Q3
- 2026-07-15 **事件內容走 general pipeline → 漏掛系列品牌**：台積電 7/16 法說會前夕 IV 定位文（`mile_5a20a332`）本應是「🌡️ 事件溫度計」時效事件文，卻以 `general_article` draft（`tsmc_earnings_iv_..._general_draft.md`）派工發佈 → 無 `event_series_slot` marker → 未進 registry members → **`series_registry --audit` 靜默（audit 只驗 registered members 是否掛前綴，看不到「該屬某系列卻沒註冊」的漏網文章）**。boss 巡檢抓到。修：手動歸位 members + `--apply` 掛前綴 + `supabase_sync`。**根因在 dispatch 分類**（時效 dated-event 文被當一般文），非 registry：帶 marker 的 5 篇 auto-path 全對。**教訓：時效性 dated-event 文（財報/FOMC/CPI 預告）選題時就要判為 event_article（→ 事件溫度計 + 立即發 + FB），不是 general_article；audit 只能抓 registered drift，dispatch 誤分類要靠選題紀律擋** — Q3
- 2026-07-15 **3-STRIKE TRIGGER（第 4 次）PostgREST 1000-row cap：v3 統計「1000 篇研究」vs 真值 1612**：boss 抓到 v3 報頭統計錯、原版正確。根因 = `fetchArticleSummaries` 無分頁 → diversify=cluster 路徑 total=1000 且 diversify/載入全部只看得到最新 1000 篇（一般路徑走 RPC 正確 → 兩版數字脫鉤）。同 class 第 4 次：paper_trades(03-18)、knowledge(04-17)、article_tags(06-23)、本次。已修 3 站點（summaries 分頁 / tags 150-id chunk + 退役 06-23 page-level 補撈 workaround / market_daily 分頁 — 後者 ascending ~880 列逼近 cap，溢出會先砍最新行情）。**2026-07-16 結構性收尾**：`data-server.ts` 統一由 `fetchAllRows` 負責所有會成長 select 的 range loop，relations / member-QA / reactions / questions / digest / paper trades 全部收編；`strategy_signals` / `strategy_metrics_cache` 以有理由的 bounded exemption 保留。新增機械 gate 掃描每個 `.from().select()`，缺 `fetchAllRows` / `range` / `limit` / `single` / `in` 或 `// row-cap-exempt: <reason>` 即 fail。production deployment `6a57ce173d3d099ed2f12794` 驗證 cluster feed total=1614、tagCounts=2082、market latest=2026-07-15。**同日老闆立 standing rule：原版=核心內容數據、v3=美化呈現、不能脫鉤**（`.claude/rules/frontend-and-deploy.md` 主從關係段）（frontend 3e72eef + b0325d1）— Q3
- 2026-07-15 **v3 報頭連環假資訊 — SoT 遷移後 consumer 未跟上 + 前端 workaround 掩蓋根因**：boss 抓到報頭「2026-07-14 · 星期日」（當天 7/15 週三）+ ticker 全 ▲0.00%。三層根因：(a) `星期日`/`台北·晴·24°C`/`Vol. IV No. 128` 是 mock 設計殘留硬編碼；(b) market 價格 SoT 遷移到 `market_daily` 表後 `buildStrategyOverview` 仍從 `paper_trades.entry` 撈（欄位已被 strip）→ API 回 null 多時**無人發現**，因為 (c) 前端 `useV3Data` 加了 portfolio-overview enrich workaround 把 null 蓋掉 — workaround 讓 API 根因隱形存活。修：API 改讀 market_daily（+change_pct/trade_date），移除前端 workaround（註解明令勿重引入），報頭全真值化。**教訓：client-side workaround 蓋 API 缺陷 = 把根因變隱形；發現 API 欄位 null 要修 API，不是在 consumer 補刀**（frontend aa62215）。資料端 SPY/GLD carry-forward stale 另開 task `market_daily_stale_spygld_backfill_verify` — Q3
- 2026-07-15 **v3 研究動態摘要裸露 md 符號 — helper 副本漂移**：`stripMarkdown` 存在 3 份本地副本（FeedBrowser 2026-06-11 修 / radar-data / reports metadata），v3 `useV3Data.adaptFeedItem` 沒有自己的副本 → 同 bug 原版修過、v3 再犯（boss 抓到）。修：收編為 `src/lib/strip-markdown.ts` 單一 util，v3 在資料組裝層 strip（全 variant 生效）；class sweep 同補兩版書籤頁裸 excerpt。**教訓：display-sanitize 這類 cross-cutting helper 第一次出現第二個 call site 時就該進 lib/，不是等第三份副本漂移**（frontend commit 13cbecb）— Q3
- 2026-06-23 首頁 feed 標籤消失 + tw/us 篩選慢（同根：Supabase 1000-row cap）— Q2

## N. FB / social publishing 冪等與附圖

**規則**：outward-facing 動作必須有冪等 guard；發 FB 前查老闆是否已手動發過。主貼文必附圖（結果圖 + 懶人包）；連結放第一則留言（壓觸及）。FB 完稿要持久化到 canonical draft 位置（非只 /tmp）。
**機械 owner**：FB idempotency guard + `fb-publishing` skill（CDP-attach 持久 profile Chrome）；`task_pool_claim.py complete` 對 `trending_repost` / `event_article` 的 feed-published receipt 回讀 `storage/drafts/fb_mile_<id>.md`，缺稿拒絕標 succeeded；`audit_fb_pipeline.py` 對所有非終態 FB 狀態做同一 invariant 的 backstop（不等 TTL）。
**代表 incident**：
- 2026-07-16 MCP Chrome 剪貼簿跨機器：本機 pbcopy ≠ 老闆主力機剪貼簿，Cmd+V 貼出老闆私人研究文字進 FB 留言框（送出前截圖驗證抓到、當場清除）。規則：MCP extension Chrome 上貼上後**必截圖驗證再送出**；ASCII URL 用 `type` 不走剪貼簿；中文長文只走本機 CDP Chrome（pbcopy 同機 + 雙驗證）。memory `reference_fb_chrome_browser_autoselect` 已更新 — Q3
- 2026-07-08 fb_realchrome_post 附圖偵測器連 4 次假 ABORT（縮圖 count mismatch + 跨 dialog 洩漏）— Q3
- 2026-07-07 FB real-Chrome CDP-attach 接的其實是假 profile — Q3
- 2026-07-07 FB 完稿未持久化到 canonical draft 位置（text-only-in-tmp）— Q3
- 2026-07-20 **root_cause_fixed_and_verified** 31 篇 expired_skip 中 23 篇從未產生 FB 稿：發佈班只建 `fb_repost_*` follow-up 仍可標 succeeded；完成邊界現 fail-closed 要求 canonical 稿，audit 同步擴到所有非終態狀態，live pool 已無非終態 `fb_repost_*` 殘留 — Q3
- 2026-06-03 FB pipeline 4 天 100% 失敗根因 — Q2

## O. Data freshness / 交易日曆 / RV 隔夜跳空 / 交易成本

**規則**：freshness 判斷用**交易日曆**不是日曆天（否則同時誤報與漏報）。日內 RV 不可把隔夜跳空混入日內第一筆報酬。交易成本計算要對市場正確（台股 vs 美股）。資料落後追到產生它的 job，不手補資料。
**機械 owner**：`data-collection-ops` skill（新鮮度判準 + recovery）+ market calendar。
**規則 2 — 等值檢查不是 freshness 檢查**：發布 gate 對抗「上游資料倒退」必須用**單調規則**（資料日期只准前進），`==` 只擋 rerun 擋不住 stale 回應；被 dup_waiver 豁免其他 gate 的內容，僅存 gate 必須獨自扛住所有失效模式。owner：`scripts/daily_update.py::daily_publish_decision` + `tests/test_daily_publish_decision.py`。
**代表 incident**：
- 2026-07-16 K1410 partial-month guard 依賴「目前月份」，快取跨月後讓已排除的 TWII 2026-06-01 單日資料復活；改為資料本身的尾月完整度判斷並加跨月回歸測試 — 全文：`docs/error_log_archive/2026-Q3-k1410-partial-month.md`
- 2026-07-15 15:10 每日更新一天雙發：yfinance 回傳倒退資料（7/13）繞過等值 guard，還誤刪早班正確文（owner 抓包；stale 對 unpublish + 誤刪文 git 還原 + guard 改單調）— Q3
- 2026-07-14 10:15 live_freshness 拿日曆天當交易日曆，同時誤報與漏報 — Q3
- 2026-07-11 0050 五分鐘 RV 把隔夜跳空混入日內第一筆報酬 — Q3
- 2026-03-28 台股交易成本計算錯誤 — Q1

## P. Test / CI / guard leakage / hermetic

**規則**：測試與原始碼要一起上（測試先上、code 沒跟 → main 紅）。pytest guard 要覆蓋 worktree（不能只在被忽略的 root conftest）；collection 不可讀 production `.env.local`。驅動 git 的測試須隔離（臨時 repo，不碰真庫）。「測試寫 canonical state」整個 class 由 CI tree-clean owner 擋。機器要訂閱自己的 CI 狀態（別紅 12 小時沒人看見）。
**機械 owner**：CI pytest（零憑證必全綠）+ pytest.yml tree-clean step（唯一 owner）+ hermetic-git 測試規則 + cron wrapper manifest。
**代表 incident**：
- 2026-07-23 **root_cause_fixed_and_verified** Issue #7 shadow replay：54 個綠測試只證明兩套 replay 專用 selector copy 彼此自洽；第一輪 Matt Spec review 回讀 production claim／acquire 後抓到 dispatch lane、preferred agent 與 expired-lease reclaim 全缺，第二輪又抓到 replay 把 blocked／same-owner claimed 排進虛構 winner，且漏掉 dreaming live revalidation；reimplementation 複審再抓到 importer 先過濾 raw winner、duplicate id 讓 dict 覆蓋跨 record evidence、missing id 使整次 replay crash、未送入 Coordinator 的 record 被冒稱有 selector reason、跨來源 duplicate 因一份 record 無法映射而從母體消失，以及 parent 位於 TaskRecord 時因 replay 只把 `next_tasks` 傳入 selector 而虛構 `parent_missing`。修復規則：shadow／audit 不得複製或拼湊 production policy；legacy selector 必須先吃 hash-bound raw snapshot，candidate filter、identity uniqueness、判定與 ranking 必須由 production caller 也執行的 pure seam 組成；full-population identity reconciliation 必須在 mapping 前掃 supplied raw records，不能讓 importer filter 決定真實母體；unrepresentable record 以 ordinal + content hash 留存並由 reconciliation 分類，未實際進 selector 就只能標 migration `not_evaluated`；selection scope 外的 parent 只能透過 production selector 的 non-selectable dependency context 提供 status，不得進入 winner pool；無法由 immutable snapshot 重播的 live gate 必須帶穩定 reason fail closed，SQL adapter 另用 integration contract 做 parity；差異分類必須由 selector／reconciliation reason code + 顯式 oracle 驅動，禁止按 dimension 名稱猜 `policy_change`。機械 owner：`volpred.ops.task_pool_selection`、`volpred.ops.work.selection`、`volpred.ops.dreaming_revalidate.requires_live_revalidation`、`tests/test_work_shadow_replay.py` — Q3
- 2026-07-16 CI run 29450374699：`refill_task_pool` 的 candidate/task paths 已指向隔離 storage，但 cluster planner 仍偷讀 live feed/knowledge，讓 K1120 fixture 被 production VIX 飽和度擋掉；修成 planner/classifier 與 `NEXT_TASKS.parent` 共用同一 storage root，回歸測試驗證 exact binding — 全文：`docs/error_log_archive/2026-Q3-ci-294503.md`
- 2026-07-15 00:57 module-import 時算好的路徑常數不吃 monkeypatch ROOT：frozen-brief 寫進真 repo，auto-commit 再捲進 main，tree-clean gate 連紅兩班 — 修在 writer（enqueue+amend 皆 guard_canonical_write）+ 測試補 patch AGENT_BRIEF_DIR（4e52f1351）— Q3
- 2026-07-14 11:15 測試先上、原始碼沒跟上，main Test Suite 紅了兩班 — Q3
- 2026-07-14 06:07 pytest guard 曾只存在於被忽略的 root conftest，worktree 無防護 — Q3
- 2026-07-14 02:48 pytest remote guards 已全開，collection 仍讀 production `.env.local` — Q3
- 2026-07-13 16:40 CI 紅了 12.5 小時系統看不見：機器沒有訂閱自己的 CI 狀態 — Q3
- 2026-07-13 05:20 CI 紅 4 班：重構搬走接縫，舊 global 留原地，monkeypatch 靜默 no-op — Q3

## 其他 / 未分類（少量）

不落上述 class 的個案（前端 AbortError、compact 門檻對 1M 模型失效、FEVD 軸向等）分散在各季 archive，用日期 `grep` 檢索。代表：
- 2026-03-28 Paper Trading 頁面 AbortError + 重複資料 — Q1
- 2026-06-03 compact 目標值對 1M 模型結構性失效 → 降門檻 — Q2
- 2026-07-14 13:40 驗證 grep 的符號編碼盲區（abm v6 review B1 class 教訓）— Q3

---

## 近期完整記錄（active reference window）

最近 30 天（2026-06-14 起）的 entry **全文**保留在 `docs/error_log_archive/2026-Q3.md`（7 月，153 條）與 `2026-Q2.md` 尾段（6/14–6/30）。
> 註：原「近 30 天全文留主檔尾段」因近 30 天達 363 條 / 6,023 行、與「主檔 ≤800 行」不相容（單是 07-14 一天就 636 行），改為在此列近 2 日快速索引 + 指向 Q3 全文。

**近 2 日（2026-07-13/14）entry 快速索引**（全文在 `2026-Q3.md`，以日期 `grep '^## 2026-07-14'` 定位）：
- 07-14 18:18 **3-STRIKE** PHASE-Z live-checkout 誤歸因 + partial candidate transaction §B/§P
- 07-14 16:15 experiment-level reproduce report 為 0 + 「166」窄 regex 漏兩個 K-family
- 07-14 15:55 論文驗證副產物連續多班無主（PHASE-Z streak 根因）§B
- 07-14 15:30 Gating 實驗無人裁決 + handoff 抄已撤回裁定 §L
- 07-14 14:40 Merge 認證裸 `python3` eager-import 專案套件 §C
- 07-14 14:20 Review 對移動中的樹裁決：verdict 沒綁 SHA §C
- 07-14 13:40 驗證 grep 的符號編碼盲區（abm v6 review B1）
- 07-14 12:41 CI 紅燈 notify-first 丟中間狀態給老闆 §H
- 07-14 12:30 K1709 重犯 K1701：ratchet 在 worktree 沒牙齒 §G
- 07-14 12:05 無人載具連載一天發完 + 集數亂序（release 缺系列節奏）
- 07-14 11:52 paper snapshot auto_adjust 硬規則張力 §L
- 07-14 11:15 測試先上原始碼沒跟，main 紅兩班 §P
- 07-14 10:15 live_freshness 日曆天當交易日曆 §O
- 07-14 09:56 dreaming missing_retry 假 critical §J
- 07-14 09:50 series_registry 品牌漂移 dual SoT §M
- 07-14 09:07 **3-STRIKE** 豆腐字圖表第三次 + CI 時間炸彈 §I
- 07-14 06:20 dedup gate 說 clean 其實沒看（STRIKE 2）§D
- 07-14 06:07 pytest guard 只在被忽略 root conftest §P
- 07-14 05:45 護欄放 fail-open try 內 §D
- 07-14 02:48 pytest collection 讀 production `.env.local` §P
- 07-14 01:40 dreaming umbrella alert dedup key §J
- 07-13 22:48 CJK 豆腐字第二次（有 helper 無 enforcement）§I
- 07-13 22:20 修好的 code 從沒上線 — daemon 自我重載 §A
- 07-13 22:10 PHASE-Z title {hhmm} 使 dedup 永不命中 §J
- 07-13 21:55 PHASE-Z warn 每 64 秒轟炸 §J
- 07-13 21:45 「修好 CI」後老闆連環收 failure 信 §H
- 07-13 19:26 **3-STRIKE** 懶人包每篇讓 LLM 重寫 renderer §I
- 07-13 16:40 CI 紅 12.5h 系統看不見 §P
- 07-13 16:13 compute job 失敗後產物無 Git owner §B
- 07-13 16:05 populate_upcoming_events 寫 config 不 commit §B
- 07-13 14:20 codex worker setsid 逃出 process group §A
- 07-13 05:47 K1701 巢狀 QLIKE expanding raw DM 承載 NULL §G
- 07-13 05:22 orphan branch 三 commit 被平行實作取代丟棄 §C
- 07-13 05:20 CI 紅 4 班 monkeypatch 靜默 no-op §P
- 07-13 01:10 24/27 alert body 是寫給人看的待辦 §H
- 07-13 00:15 pre-commit 審了你沒要 commit 的檔 §B
- 07-13 K1702 MDD/vol 比率誤當尺度不變 §G
- 07-13 無人載具把 Green UAS 當 Blue UAS 替代查核
- 07-13 排程 writer 沒 Git owner 是類別漏洞 §B

## 3-STRIKE 分布

- 明確 `3-STRIKE TRIGGER` 標記 entry：**26 條**（含大小寫變體共 36 條提及）。Q2=12、Q3=14、Q1=0。全文在對應季 archive。
- 依 class（明確標記為主）：**§A 並發/dispatch** 最密集（2026-06-23 META、07-12 ×2、07-01 hourly-auth 等）；**§B git-owner/canonical-write**（07-10 ×2）；**§D silent-fallback**（06-20、06-23 test-hook）；**§E dedup/K-id**（06-10、06-23、07-19 K-id 撞號、07-19 member_qa 重複答覆＝該 class 首次立案，STRIKE 1 為 2026-03-31 追認）；**§H final-text**（07-02 ×2）；**§I chart**（07-14、07-13）；**§J dreaming**（07-01）；**§K pool**（06-14）；**§L paper**（05-22）；**§M series**（07-06）；**§C worktree**（07-12 K1032）。
- 查全部：`grep -rn '3-STRIKE' docs/error_log_archive/`。

## 2026-07-16 dreaming memory-skill gap 聚合 signature 吞掉新問題，且 owner 只靠名稱猜測 — FIXED

**根因**：`detect_memory_governance` 把所有候選聚成固定
`memory_skill_gap:uncodified_process`。Task queue 又按 signature-derived id 去重，因此舊 task
一旦 succeeded，往後不同的 memory gap 會被永久視為「已處理」。Coverage 只檢查 index 文字
是否含 skill 資料夾名，且把泛用 `auto` 當 cadence，造成已有 skill/reference 的流程連續入池，
同時沒有驗證 owner 內容是否已 drift。

**修復**：每個 memory stem 使用獨立 signature；memory 可宣告指向實存檔案的
`process_owner`，並保留既有 skill cross-link 掃描；移除 `auto` 泛關鍵字。逐筆稽核時另修出三個
真 drift：Telegram responder 以 responder-only `autoMemoryDirectory` 綁回 canonical memory、
paper submission 同步 2026-07-09 自主投稿授權、platform-ops dreaming 文件同步 7/12 actuator
預設開啟。`detect_memory_governance` 對真實 memory 回傳 0 個未歸屬流程；46 個 dreaming tests、
1 個 responder canonical-lease test、shell syntax、Python compile、`git diff --check` 全通過。

**教訓**：會漂移的 evidence 不得共用固定 dedup identity；「owner 存在」必須是可驗證路徑，
而不是名字相似。隔離 cwd 的 agent，`--add-dir` 只授權工具存取，不等於切換 auto-memory
namespace；同一大腦契約要在 runtime setting 明確綁定。

## 2026-07-16 完成語音從 always-loaded prose 降成從未觸發的 command — FIXED

**現象 / 根因**：2026-04-26 為省 context，把「完成後 `say`」從 CLAUDE.md 移到
`/task-done`；歷史 session 沒有實際 invocation，等同功能消失。直接新增另一支 Stop hook 又會
違反 L1 單一 owner，且背景 hourly/worktree agent 每次 stop 都播會形成噪音風暴。

**修復**：project `enforce_final_text.py` 恢復只管 final text；同一 runner 的 `--speech-only`
由 user-level Stop hook 全域呼叫。`~/.claude/CLAUDE.md` 只在真正完成且驗證通過時產 hidden
`task-done` receipt；hook 獨立驗最後 block、只允許 `claude-desktop|claude-vscode`、排除 API
error/subagent/background/cron，使用 `session_id + assistant.uuid` one-shot 去重。任務名 NFKC、去
控制字/URL/敏感字、限 24 字；鎖內先 persist receipt，鎖外 detached argv 直呼 `/usr/bin/say`
（不經 shell、不阻塞 Stop）。`/task-done` 不再手動 say。user settings/CLAUDE 雙寫到
`ops/claude_user_backup/`。

**教訓**：Stop 是 turn-end，不是 task-completed；任何非空文字都算完成會把 no-op、拒絕、timeout
誤播。語意層必須提供明確 receipt，機械層才 consume；外部文字不可拼 shell command。

## 2026-07-19 dreaming 寄信閘門判「有沒有新東西」而非「有沒有人得動手」 — FIXED

**根因**：`main()` 的寄信條件是 `if new_findings or escalations`。這判的是**新奇度**，但
dreaming 的設計目標（`loop-health-and-dreaming.md` §Auto vs Propose）把責任切得很清楚：
`auto_dispatch` 是 actuator 的事（自 2026-07-12 預設 ON，finding 一出現就自己進 next_tasks），
`propose_only` 才是人的事。兩者都算「新」，於是機器正在處理的照樣寄給老闆。

第二個放大器：`reconcile()` **早就算出** `quiescent`（底層訊號自上次 run 起未推進 = 已停火、
正在 48h 自清），但只拿來擋 strike，算完就丟 —— 一個正在自清的 alert 仍以 active warn finding
的身分出現在信裡。

標本 = 老闆 2026-07-19 回信點名的那封（email-12141，報告 `2026-07-18.json`）：9 findings =
4 個 auto_dispatch（其中 2 個 `remediation_ref` 已寫著派出去的 task id）+ 5 個 quiescent
persistent_alert（停火 12.8–46.5h）、escalations=0。**零項需要老闆，信照寄**，而且信的
「建議行動」自己寫著「escalations=0 → 不需要重構」——**一封告訴收件人「你不用做事」的 WARN**。
附帶查到文案與行為脫節：信裡仍寫「`--apply-auto` 才會派修復 task（預設關）」，而 actuator
一週前就已預設開啟。

**修復**：把 `quiescent` 升為 `DreamFinding` 欄位（reconcile 存下來而非丟棄）；新增
`needs_human_attention(finding)` 作為對外音量的**單一** owner（critical 一律寄 > quiescent 不寄 >
其餘只有 propose_only 要人）；`build_report` 加 `actionable` / `actionable_new` /
`machine_handled` / `quiescent` 讀數；閘門改 `escalations or actionable_new`；tier 表的
warn 條件由 `new` 改 `actionable_new`；信中逐項標「機器已派修復 task」/「已停火、自清中」且需要人
的排最前面；修正 actuator 文案。靜默不等於黑洞 —— 報告、decision log 照寫，skip 理由印在 cron log。

**驗證**：`tests/test_dreaming_review.py` 60 passed（新增 10 個，含把那 9 個 finding 當標本的
回歸鎖）。真實資料重放（唯讀，未動 canonical）：還原 07-18 當晚 → `actionable_new=0`、
escalations=0 → **那封信不會寄**；把同一批 finding 餵進今晚 → 5 個 quiescent + 3 個機器自理
全靜音，僅一個累到三振的 `missing_retry_strategy` 升 critical 送出，升級路徑未被削弱。

**教訓**：**通知的閘門要判「收件人有事可做嗎」，不是「系統有新資料嗎」**。偵測器的產出天然全是
「新資料」，用新奇度當閘門必然把機器自己的例行工作寄給人，而人一旦學會忽略這個寄件人，真正的
escalation 也會一起被忽略 —— 這是把 §J（alert 轟炸）的傷害從 alert 層複製到 dreaming 層。
另一條同樣通用：**一個已經算出來、卻沒有存下來的判斷，遲早會在別處被重新用錯的方式再算一次**
（quiescent 擋得住 strike，卻擋不住寄信，只因為它沒活過那個函式）。

## 2026-07-18 反射式文案 if/else 是遺留來源：dreaming email「建議行動」重構 — FIXED

**根因**：`send_dreaming_email` 的建議行動是一疊寫死的模板字串。老闆指出 escalations=0 時仍反射式
建議「從底層重構」是過度反應（email-12149），上一輪的修法是在字串堆疊中間插一個
`if c["escalations"]: ... else: ...` 文案分支。老闆隨即指出**這個修法本身就是要停止的行為**
（telegram-942：「不可以只用修補的方式，以後不可以再出現這種遺留的狀況」）。結構上的問題有兩層：
(1) 每收到一次語氣糾正就多一個 branch，函式無界成長；(2) `level = "critical" if escalations else
(...)` 與文案分支是**兩處各自 if 同一個條件**，任何一邊改動都會讓 level 與內文語意漂移，而且沒有
任何測試會發現。

**修復**：抽成 module-level 資料表 `DREAMING_SEVERITY_TIERS`（frozen dataclass
`DreamingSeverityTier`：`matches` 條件 + `alert_level` + 該級專屬 `actions`），通用行動放
`_DREAMING_COMMON_ACTIONS_HEAD/TAIL`，由 `select_dreaming_tier` 選、`render_dreaming_actions`
渲染（編號用 enumerate 產生，不寫死在字串裡）。level 與文案自此同源於一筆 tier。舊 if/else 分支
整段移除，無 legacy fallback。新增 4 個測試釘住三級 level 與各自文案、以及編號的位置性；
`tests/test_dreaming_review.py` 50 passed，連同 alerts / check_alerts 共 119 passed。

**教訓**：**boss-facing 文案的 if/else 分支是遺留的孵化器** —— 文案糾正頻率高、每次糾正的最小
修補都是「再加一個 branch」，於是修補本身變成復發機制。凡「條件 → 文案」的對應，第二個分支出現時
就該轉成資料表；且同一條件不得在兩個地方各自 if（level 與內文必須由同一筆資料決定），否則漂移
無人察覺。此條與 §H「alert body 是寫給人看的待辦」同源：alert 內文是產品介面，要有結構與測試，
不是可以隨手貼字串的地方。

## 2026-07-19 實驗進 main、artifact 沒進：CI 連三班紅 → 機械 gate — FIXED

**根因**：experiment 目錄合併進 main 時，`storage/memory/knowledge.json` 條目與
`reproduce_spec.json` 沒有任何東西強制它一起進來。2026-07-19 一天內 CI 連三班紅：k1732 缺
knowledge 條目 → 補；k1719 缺條目 → 補；第三班測試寫 canonical → 補。**三次都是逐筆補、沒有人修
流程**，所以第四次只是時間問題。這是典型的「清庫存當成修 bug」：庫存清完，產生庫存的那道門還開著。

**修復**：`scripts/check_experiment_artifacts.py` 一支腳本、兩個門，規則只有一份 ——
`scripts/merge_worktree.sh`（pre-merge，擋合併，接在既有 certify gate 之後）與
`.github/workflows/experiment-artifacts.yml`（push / PR，擋分支）。帶 archived `*_results.json`
的 experiment 目錄必須同時有 (a) knowledge.json 中提及其 K-id 的條目、(b) 可通過
`reproduce_check.load_spec` 的 `reproduce_spec.json`。失敗訊息直接印出可貼上執行的補救指令。

**三條刻意畫死的邊界**（每一條都是為了不製造假歷史）：
1. **前進式 ratchet**：只審本次 push / merge 新增或修改的實驗，不追殺 1,261 筆歷史缺 spec。
   `reproduce_spec.json` 是 2026-07 才成形的慣例，替沒人跑得動的舊 run 補 entrypoint / input hash /
   seed 等於發明歷史 —— 那正是這道 gate 要防的事。
2. **無 results 的目錄不入 scope**（sweep 掃到 232 個：論文撰寫 session、`.gitkeep`、廢棄 stub）。
   沒有結果就沒有發現可記、沒有輸出可釘，硬要求只會逼人捏造條目。
3. **無 K-id 的目錄不審 knowledge 半邊**（如 `paper2_taiwan_indiv_rolling_gamma`）：knowledge.json
   以 K-id 為 key，對這種目錄 gate 根本無 key 可查，「請補一筆提及 paper2_… 的條目」是查不到也做不到
   的指令。**做不到的 gate 只會被繞過，不會被遵守**。它們仍要交 `reproduce_spec.json`。

**驗證**：`scripts/tests/test_check_experiment_artifacts.py` 12 passed（含刻意造缺條目 / 缺 spec
目錄被擋、無 results 不被擋、無 K-id 只審 spec、knowledge.json 讀不到時 fail-closed）；
`check --changed-since origin/main` 當場抓到真實漏網的
`experiments/paper2_taiwan_indiv_rolling_gamma`（orphan reaper 於本日收進 main、無 spec），已依其
腳本實際的 `SEED = 20260713` 與 `data/` 13 個檔的 sha256 補上 spec，非事後編造。

**教訓**：**逐筆補同一個 bug class = 把偵測成本外包給下一班的紅燈**。同一種紅燈出現第二次時，該修的
就不是那一筆而是那道門。另一條更通用：**gate 的要求必須可被執行**——當規則對某類目標無法滿足時，
正解是把該類明確排除並說明理由，不是留一條沒人做得到的規則等著被 `--no-verify` 繞過。

## 2026-07-19 會員提問被答第二次：三道 gate 全守在「意圖」，讀者看到的 artifact 沒有 owner — FIXED（STRIKE 2）

**incident**：會員 `yaoxk1431` 把同一個問題只改數字（每年成長 15% → 7%）重問一次，兩次都被完整
研究、完整發佈：`e79a7097` → `member_qa_e79a7097_evaluate`（07-11）→ `mile_d84aa7d0`（07-12 published）；
`3e258ba2` → `member_qa_3e258ba2_evaluate`（07-18）→ `mile_0205a444`（07-19 published）。老闆來信第一個字
是「**又**」——2026-03-31 同一位會員的台灣經濟提問已經在 7 小時內被答過兩次（`mile_530a28bc` /
`mile_42ee876c`）。

**根因**：全系統把「同一個問題」定義成「同一個 `question_id`」。新 row = 新 id = 系統認定不是重複。
歷次修法都只是把這個字面鍵放寬一格，沒有換軸：03-31 修的是**並發**（兩個 session 同時 claim），
07-19 當日的 `33cf84b8f` / `dde8e1666` 加了 `question_similarity()` / `find_duplicate_question()`，方向正確，
但**兩道新 gate 都站在意圖端**（建 task、claim question）。主線程手寫一篇文章直接呼叫
`publish-milestone`，一道都不會經過。而 member_qa 恰好被**明文排除**在既有的發佈端查重外
（`_RELEASE_DEDUP_AUDIENCES = {general, research}`；publisher 的 topic-cluster type-exempt），
所以**讀者實際看到的那個 artifact，是整條鏈上唯一沒有 owner 的環節**。

**修復（發佈端 = 最後一道，且是唯一守在讀者可見面的）**：
1. `volpred.ops.content.assert_member_qa_publish_allowed()` — 同一 `question_id` 已有
   published/scheduled 答覆時，`Publisher.publish_milestone` 直接 raise
   `MemberQaDuplicatePublishError`（訊息列出既有文章 id）。上游全部被繞過它仍成立。
2. **具名續作通道**：刻意的「先發初步、後補深入」用 `details['supersedes']`（CLI `--supersedes`）通過，
   且必須**列出全部**既有答覆的文章 id。不做無條件旁路旗標——無條件旗標會退化成「一律加上」，
   要求具名則逼作者去看已經存在什麼。
3. `answer_internal_question()` 冪等：已有 published 答覆文章時不再綁第二篇（回傳
   `skipped/already_answered`，需 `allow_reanswer=True` 明確覆寫）；`answered_at` 只記首答，
   重跑不再往前推（會讓兩次答覆在稽核軌跡上看起來像兩個正當事件）。

**fail-closed 但不靜默停擺**：本地 `feed.json` 是這個 repo 發佈過的一切的權威鏡像、且不需網路；
Supabase 只是加強覆蓋。因此 (a) 本地 feed 讀不到 = 全盲 → 丟**不同的** exception 型別
`MemberQaPublishGateIndeterminate`（「我沒查到」永遠不得被算成「確定沒有重複」）；(b) 本地判定 clear
但 Supabase 查詢失敗 → 明確印出 DEGRADED 並放行，不讓外部服務中斷把整條 member_qa 線悶掉。

**教訓（本次真正的那一條）**：這個 class **從未在 error_log 立案**，所以沒有 3-STRIKE 計數、沒有升級
路徑，第二次發生時系統對「這是老問題」是無知的——老闆說「又」，系統說「新問題」。**沒立案的 class，
第二次發生等於第一次。** 另一條：**查重要守在產出端，不能只守在意圖端**；意圖端的 gate 都是可繞過的，
只有讀者看得到的那個 artifact 是無法繞過的必經點。

## 2026-07-20 feed「排列時間亂」二度被老闆點名 → 顯示層 cluster 重排全面退役 — FIXED（STRIKE 2）

**現象**：老闆問「前端文章排列時間為什麼是亂的？」。實查：跨日單調 invariant（2026-07-07 day-bucket 修復）仍成立，亂感來自**同日內 diversify interleave**（設計保留的日內重排）+ 首頁精選區塊夾舊文。同類感知問題第二次（前次 2026-07-07「7/5 排在 7/6 後」）。

**根因（domain model）**：「主題分散」這個 concern 有兩個 owner — 發佈端 per-cluster cadence budget（正確層）+ 顯示層 `diversifyFeedItems` 重排（錯誤層）。上次只把顯示層重排「加界」（day-bucket），沒有收斂 owner；日內重排殘留照樣違反讀者「新的在上面」心智模型。

**解決（anti-stacking 收斂）**：顯示層重排全面退役 — `feed-diversify.mjs` + 舊 chronology 測試刪除；`page.tsx`/`FeedBrowser`/`v3 useV3Data`/`radar-data`/feed API 的 `diversify` 參數全移除；`getCachedClusterFeed`→`getCachedFeedViaRpc`（保住 2026-06-22 首頁 TTFB cache 教訓）。主題分散唯一 owner = 發佈端 cluster cadence（既有 cluster-cap alert 續管）。`verify-regressions.mjs` 改立**硬 invariant：feed published_at 嚴格不增**；順修 7/1 起就紅的 paper formatUpdated guard。前端 commit `1f3cab0`，deploy-zeabur-safe 上線。

**驗證**：線上 `/api/publications/feed?limit=12` 12/12 非增序；draft 正確排除；typecheck/build/static regression 全綠。附帶查證非本因：Supabase 3 筆 published_at NULL 列皆 `unpublished`（前端 status filter 已排除）；最新兩篇未現身為 `draft`（release 前正常）。

**教訓**：顯示層「有界重排」仍是重排 — strike 2 就該把 concern 收斂回單一 owner，而不是把錯誤層修得更精緻。讀者面順序類 invariant 一律寫進 regression verifier，且 verifier 要真的有人跑（本次發現它自 7/1 紅著沒人知 → 已修，後續由 F1 layer-map audit 把 verify:regressions 掛進 CI 的缺口記入 ops master plan WS-F1）。

## 2026-07-20 main_thread lane 隔離讓 hourly fire 全面餓死 — FIXED

**現象**：12:17 那班 fire 跑 PHASE A0 得 `count=7`（7 張 `[refactor-master]` P1，`source=user`，03:12 建單），
但逐一 claim 全數回 `reason=main_thread_lane`。A0 的規則是「lane 還有殘留 → 本班不進 PHASE A」，
而這 7 張 headless fire **永遠** claim 不到 ⇒ **11:48 之後每一班 fire 都卡死在 A0，一般排班工作全面餓死**。
下游證據：`continue_task_dispatch --report` 同時報 STARVATION LOCKOUT，P1 `assign_67f56b79` 已餓 42.2h。

**根因（anti-stacking：同一 concern 三個 owner，詞彙各自漂移）**：
`dispatch_lane` 的判定散在三處且互不相同 —
`continue_task_dispatch.py:109` 認 4 種拼法（main / main_thread / manual / interactive）、
`task_pool_claim.py:496` 的 claim gate 只硬比對字面 `"main_thread"`、
`task_urgency.py`（PHASE A0 的判定 owner）**完全不認得 lane**。
commit `f23d870c4`（11:48）把隔離 enforce 在 claim 入口是對的，但沒有同步 A0 的候選判定 —
於是「擋得住 claim」和「排不進 lane」變成兩件事，claim 不到的任務照樣排在 A0 最前面。
副作用二：`lane="manual"` 的任務進不了 PHASE B 候選、卻擋不住 burst 點名 claim（詞彙不一致的直接後果）。

**解決（收斂回單一 owner）**：lane 詞彙移進 `src/volpred/ops/next_tasks.py`（controlled-vocabulary owner，
同 `TASK_STATUSES` 的形狀）：`AGENT_/MAIN_THREAD_/BLOCKED_DISPATCH_LANES` + `normalize_dispatch_lane()`
+ `is_agent_claimable_lane()`（未設 lane 一律可派 — 絕大多數存量任務沒有這個欄位，預設保留會凍住整個佇列）。
三個消費端全部改用同一套：ctd 改 import、claim gate 改用 canonical set（順帶補上 manual/interactive 破口）、
`task_urgency` 新增 `LANE_DEFERRED`。這類任務不進 A0 可動 lane、`is_urgent()` 回 False
（不叫醒一班誰都做不了的 fire），但 CLI 仍以 `deferred_main_thread` / `deferred` 獨立列出 —
**不進 lane ≠ 消失**，主線程的 backlog 要看得見。

**驗證**：`uv run python -m volpred.ops.task_urgency` 實測 `count=0` / `deferred_main_thread=7`（7 張 id 全在），
死鎖解除；claim 仍正確回 `main_thread_lane`（隔離語意未被洗掉）；
`test_urgent_task_lane.py` 42 passed（新增 6 case 釘死餓死方向 + 誤擋防線 + 兩端共用同一詞彙）；
ctd `--report` 正常，claim/vocab 相關套件全綠。

**教訓**：**隔離只做一半 = 餓死**。把某類任務「擋在 claim 入口」而不同步「排出候選 lane」，
會製造一種最惡劣的形狀 —— 任務看得見、排得進、清不掉，而清不掉的 lane 剛好是「清完才能往下走」的前置條件。
新增一個 gate 時必須同時問：**誰在產生候選？它認得這個 gate 嗎？** 另一條：控制詞彙（status / lane / reason）
一旦出現第二份字面值就會漂移，且漂移處必然是破口 —— 這次是 `manual` 擋不住 burst。

## 2026-07-20 daily_update watchdog 誤殺 + 「跑過」被當成「跑成功」 — FIXED

**現象**：老闆報「intraday 週六沒 fire、collect_us 最後成功停在 07-18」。實查兩條指控**都不成立**：
`daily_update_intraday` 07-18(六) 14:04 有跑且 rc=0；`collect_us` cron 是 `3 7 * * 2-6`，
週日/週一本就不 fire，07-18 成功後下一班本來就是 07-21(二) —— 兩者皆為正常行為。
但同一次 audit 撈出**真故障**：`daily_update_intraday` 07-16 與 07-20 兩班 `rc=142 duration=600s`
（撞 perl alarm watchdog 被 SIGALRM 殺），且**沒有任何監控報過**。

**根因一（監控盲區：mtime ≠ 成功）**：`daily_checkup.py::check_data_freshness` 判新鮮度只用 cron log 的
**mtime** + croniter 漏班數。失敗的 job 照樣把失敗訊息寫進 log、照樣更新 mtime ⇒ 一個天天失敗的 job
在 data_freshness 眼中**永遠是新鮮的**。加上 `daily_update_intraday` 根本不在 `DATA_JOBS_EXPECTED_H`
名單裡 —— 雙重盲區，只能靠老闆肉眼發現。

**根因二（watchdog margin 建立在過期常數上）**：兩支 wrapper 的 600s alarm 是 2026-06-30 為防 lock cascade
所加，註解寫「正常 ~2min 的 5x」。但 7/02–7/18 實測 duration 已是 **250–390s**（sync 步驟長大），
真實 margin 只剩 ~1.6x ⇒ 偶發 Supabase `URLError timed out` retry 就衝破上限。
watchdog 沒有壞，它是**照著一個早就不成立的 baseline 在開火**。

**解決**：
1. `daily_checkup.py` 新增 `_last_exit()`（只讀 log 尾 16KB）→ data_freshness 對每個 job 額外檢查
   最後一筆 `exit N`，rc≠0 直接 critical，rc=142 特別標示為撞 watchdog；「有跑但失敗」與「根本沒跑」
   各自獨立報。`daily_update_intraday` 補進 `DATA_JOBS_EXPECTED_H`。
2. `cron_daily_update.sh` / `cron_daily_update_intraday.sh` watchdog 600s → **1200s**（對實測 p95 ~3x
   margin；14:00+20min 仍遠早於下一班，lock cascade 防護不變），註解改寫實測 baseline 而非過期臆測。
   canonical `scripts/` 與 runtime `~/.volpred/bin/` 同步（diff 確認改動前無 drift）。

**驗證**：改後跑 `daily_checkup.py --json` → data_freshness 恰好 1 筆 critical，正是
`daily_update_intraday 撞 watchdog timeout（duration=600s）`；其餘 rc=0 的 job 無誤報。

**教訓**：**「有 log」不等於「有成功」** —— 任何以 mtime 為新鮮度指標的監控，都會對「持續失敗但持續寫 log」
這種故障完全失明，而這正是最常見的故障形狀。第二條：**watchdog / timeout / 門檻類常數必須把實測 baseline
寫進註解，並在 baseline 漂移時一起改** —— 註解裡的「正常 ~2min」放著沒人維護，就是它後來誤殺兩班的原因。
第三條：老闆報的症狀可以是錯的，但**值得照著 audit 一遍** —— 這次兩條指控都不成立，卻挖出一個更嚴重的真問題。

### 補記 2026-07-20 20:15 — 同一次誤殺的下游代價：13 班 slot cap 減半 — FIXED

上面只修到「誤殺」與「沒人報」，漏了追**被殺之後工作區長什麼樣**。07-20 14:04 那班的實際順序是：
14:04:59 `build_feed_index()` 重建完 `storage/reports/INDEX.md` + `index.json` → 之後的 sync health check /
alert checks 吃掉剩餘時間 → 14:10:05 `rc=142` 被 SIGALRM 殺，**還沒走到檔尾的 `commit_owned_outputs()`**。
兩個 derived artifact 就這樣被改寫卻沒提交，留在 main checkout。

PHASE-Z 認得「這不是本班 fire 產出的檔」，於是照 D3 開出 foreign incident `assign_f71399a3`
（fingerprint `6d1d05803b30ef94`）。而 incident 未關會經 `scripts/dispatch_slot_budget.py` **把 slot cap
從 4 降到 2** —— 也就是一次 watchdog 誤殺，讓後續 **13 班**每班能派的工都少一半，
而那 13 班沒有任何一班看得出自己為什麼被降載。

**處置**：兩個檔的 bytes 早已 checkpoint 進 immutable ref
（`refs/volpred/quarantine/20260720T065846820394Z`，本次 `cmp` 逐 byte 確認與工作區一致），且是
可由 `feed.json` 完整重建的 derived artifact ⇒ 經 `git_writer_lock.py run` restore 回 HEAD，
下一班 `daily_update` 自然重建並提交。`foreign_incident --check` 轉 `closeable: true`，cap 回 4。

**教訓**：**修 timeout 只修了一半 —— 還要問「被殺在哪一行、留下什麼」**。凡是「產出 → (一段長工作) → 提交」
這種順序，watchdog 的實際切點就決定了會不會留下無主檔；margin 加大只是降低機率，沒有消除形狀。
第二條：**降載這類懲罰要能反查原因** —— 被降載的 13 班只看得到 cap=2，看不到「因為某班 14:04 被 SIGALRM
殺在提交前」。`dispatch_slot_budget.py` 的 reason 字串有帶 incident id，這次就是靠它一路追回根因，
這個設計要保留。

### 2026-07-20 22:17 — dispatch worker「Execution error」15-byte log + hang 16 分鐘（今日五次）— FIXED

兩班 worker（11:23 `slot-4.d85d3cf2`、22:01 `slot-1.46f4806a`）log 都只有 15 bytes「Execution error」：
claude CLI 落地即 fatal 但**行程不退出**，supervisor hang-kill 於 960s 收屍。安全網有效（claim
`ci-red-29744499806` 正確 re-pend、下一班重派），但代價 = 每次白吃 16 分鐘 slot + 一封 CRITICAL。
「Execution error」是 CLI 端 terse fatal（API/session-limit 類），log 無 stderr 細節、無法歸因。
已開 P1 main_thread 單 `assign_exec_error_fastfail`：(1) worker 偵測 fatal-marker + 輸出停滯 → 秒級
kill、分類 transient、當場 release claim（不等 hang cap）；(2) claude CLI stderr 導入 worker log 供歸因。
**教訓**：hang cap 是 last-resort，不是 first detector — 已知 fatal 訊息出現時等 16 分鐘毫無意義；
以及 15-byte log 這種「有殼無屍」形狀本身就該是可分類訊號。

**FIXED 2026-07-20 22:5x**（`assign_97bf1e6d`，slot-1 主線程）。盤點修正：當日**不是兩班而是五班**
中此形狀（`slot-1.46f4806a` / `slot-1.746b2d2f` / `slot-3.b5fbc1f4` / `slot-4.13e1fcab` /
`slot-4.d85d3cf2`），每檔精確 15 bytes、無換行。

- **偵測**：`failure_class.is_terse_fatal_only()` — 整份 output 只由 fatal marker 行組成才算數。
  刻意不是「出現 marker 就算」：worker log `slot-1.4684d8b7` 第 15 行是**正常 agent 中文散文**內含
  「Execution error」字樣，寬鬆比對會殺掉健康 fire。誤判方向是不對稱的：漏判只賠今天已經在賠的一個
  slot，誤判會殺掉正在工作的 fire。
- **收屍**：`worker._wait_with_fatal_probe()` 取代單發 `proc.wait(timeout=)`，每 5s 探一次；
  marker-only 且 60s 無成長 → 立刻 kill pgid，回 `FATAL_FASTFAIL_SENTINEL`。**注意**：健康的
  `claude -p` 整段執行期間 log 是 0 bytes（本機所有 in-flight worker log 皆然），所以「輸出停滯」
  單獨不具鑑別力 —— marker 才是訊號，停滯只是給 grace window。
- **不是 hang**：分類為 `fatal_fastfail` → 當場 `repend_killed_job_claims`（claim 立刻回池）→ 併入
  transient 契約走既有 retry ladder。**不發 hang alert**，改記 completions `outcome=fatal_fastfail`。

**補記 2026-07-21 00:4x — 上面的 marker probe 是 patch on wrong model，00:07 第六次殺證明其盲**
（3-strike 重設計 `5e36d1720`）。實測翻案：六個 incident log 的 **mtime 全部等於 kill 時間** —
「Execution error」是 CLI 死掉那一刻才 flush 出來的，活著的整段 hang 期間主 log 是 **0 bytes**，
而健康的 `claude -p` 主 log 也是 0 bytes。**主 log 這個通道在活體期間結構性無資訊**，marker probe
永遠等不到 marker（00:07 班 fired 00:08、殺於 00:18，probe 全程只看到空檔案）。重設計改用**正向
活性訊號**：debug sidecar（`--debug-file`）每 attempt 必開（原本只 attempt≥2 — 恰好所有事故都在
attempt 1）；健康 CLI 從啟動起持續寫 debug 事件，DOA 的在出生幾秒內凍結。判死條件 = 主 log 安靜
且（sidecar 180s 零 bytes，或 sidecar 凍結在啟動窗 120s 內達到的大小且 240s 無成長）；啟動窗**之後**
才安靜的 run（長 tool call 形狀）永不誤殺。附帶：hang 警報標題那句「hang > 50min cap」對每次事故
都是假的（實際 10-16 分鐘）— 改為由 started_at 算實際卡住時長（**警報文案不得超出事實**，同
SELF_REMEDIATING truth-gate 教訓）。**教訓**：偵測器要建立在「訊號真的存在於該通道」的驗證上 —
11:48 的 probe 假設 marker 會早印，沒有先 stat 一次 mtime 對 kill 時間，一個 `ls -la` 就能戳破的
假設跑了 13 個小時。16+16+18 regression tests 綠（含五形狀 fake-clock pins）。
- **歸因**：原判定「stderr 沒進 worker log」有誤 —— `_spawn` 早就 `stderr=subprocess.STDOUT`，那 15
  bytes 就是 CLI 吐的全部。真正缺口是 CLI 太安靜，改用 `--debug-file` 側寫 sidecar，且**只從
  attempt 2 起啟用**：`--debug-file` 會隱含開 debug mode，本機未驗證 debug 是否也走 stdout；若會，
  worker log 就不再是 marker-only，sidecar 會反過來把 fast-fail 靜默關掉。attempt 1 保持乾淨拿秒級
  收屍，attempt 2 換歸因。下次真實事故留下的第一份 sidecar 決定能否放寬到 attempt 1。
- **測試**：`tests/test_worker_fatal_marker_fastfail.py`（11 cases）—— 真實 15-byte incident bytes 與
  真實散文反例都進 fixture；含非空心對照組（持續產出的 child 必須不被誤殺）與 e2e（claim 有回池、
  hang alert 未發、耗時秒級）。
- **未解**：960s 那一刀是誰下的仍未查明（`exit=143` SIGTERM，非本專案 timeout 路徑、非 health.py 的
  3000s cap）。fast-fail 讓它變成無關緊要，但若日後有其他 16 分鐘現象，這條線索還在。

### 2026-07-21 00:29 — 測試與其相依實作被拆成兩個 commit，main 紅 32 分鐘（CI ci-red-29744499806 收尾時查出）

`5e36d1720`（00:29，3-strike sidecar-liveness 重設計）commit 了 `alerts.py` / `worker.py` /
`tests/test_worker_fatal_marker_fastfail.py` 三個檔，**獨漏 `failure_class.py`** —— 而後兩者都
import 它。main 從 00:29 起 16 個測試 `AttributeError: module ... has no attribute 'is_terse_fatal_only'`
（run 29761977060 / head b20d0e97e 實測）。`99aa30d7b`（01:01）的 PHASE-Z hash-pinned recovery
把該檔補交，紅燈窗口約 32 分鐘。

**比測試紅更嚴重的一面**：`worker.py` `:314`/`:324` 是 **production 判死路徑**，直接呼叫
`failure_class.is_terse_fatal_only()`。那 32 分鐘內任何 worker 走到 fatal-fastfail 分支都會
AttributeError —— 也就是前一則條目剛修好的 DOA 偵測器，在自己落地的當下是壞的。CI 紅只是這件事
最吵的症狀，不是全部。

**教訓**：PHASE-Z 的 failed-closeout recovery 機制**有效但粒度錯了** —— 它以「路徑」為恢復單位
（逐檔比對 fingerprint、逐檔補交），而正確性的單位是「變更集」。一組同進同出的檔案被部分 commit，
留下的中間狀態必然是紅的、而且可能是**會執行的壞碼**，不只是紅測試。恢復機制把窗口從無限縮到
32 分鐘，但沒有消除「部分 commit」這個形狀本身。同 2026-07-20 22:17 條目的教訓形狀：安全網有效
≠ 缺陷已消除。

**FIXED 2026-07-22（`assign_commit_atomicity_gate`）**：PHASE-Z 原本已有 alternate-index +
`commit-tree` + `update-ref` CAS，candidate 內的路徑會整批落地或整批不落地；00:29 真正漏掉的是
**candidate closure**：`failure_class.py` 在 HEAD 已存在，所以 Gate 0 接受
`from scripts.dispatch_supervisor import failure_class`，卻沒驗證測試隨後讀取的新屬性
`failure_class.is_terse_fatal_only` 是否也存在於 candidate 版模組。現在
`scripts/audit_test_imports.py` 會在 candidate tree 靜態解析 module-level submodule alias 的直接屬性
讀取；新符號只留在 working tree、consumer 單獨 staged 時 fail closed，source 與 consumer 一起 staged
才通過。PEP 562 `__getattr__` 動態模組維持 opaque，避免把不可靜態列舉的 API 誤判為缺漏。
Regression：`scripts/tests/test_audit_test_imports.py::test_index_mode_rejects_worktree_only_submodule_attribute`
重建 5e36d1720 同形 index，釘住「舊模組 + 新 consumer」不可能成為 commit candidate。

### 2026-07-22 01:21 — K741 NFP canonical 重跑推翻既有文章結論：mile_eda69bfb 回溯更正（1/7，AGENTS.md 第 13 條）

`k741-nfp-canonical` 改用官方 BLS 發布日曆 + forward-only 交易日對應後（已於 `dde428fab` /
`620b16755` 認證合併 main），既有 8 篇 feed 文章引用的全部 Part A/B 數字失效。本班更正第一篇
`mile_eda69bfb`，走 `volpred.publisher.article_correction`（errata `numbers_correction`），
所有新數字由 `experiments/k741/k741_nfp_event_study_canonical_results.json` 讀出、不手打。

**更正幅度比原任務描述大**：任務 `assign_759a28f3` 寫的是「sign 未翻轉，數字與顯著性敘述需更正，
Low-VIX 從 p=0.069 變 p=0.009」。但 Codex 三輪 review 後的認證終態（`k741_cert_merge_summary.json`）
是 **顯著性整個撤回**：對「vs 全體」「vs 週五」兩個總體檢定做 Holm 校正後 p=0.0722，regime 層級
無一存活（Low/Medium 校正後 0.1039、Elevated 0.533、High 0.707），`anything_clears_5pct_under_any_family
= false`。原文寫的「這個差異…確實存在，不只是碰巧」（依據無母數 p=0.00369）必須降級為
「方向站得住，顯著性站不住」，不是換個數字就好。

**第二個陷阱**：canonical scope 只有 Parts A/B。策略回測（13.97%/11.896%、Sharpe 0.816/0.720）與
T±n 漂移數字屬 Parts C/D，**沒有重跑**。這些數字留在文中但已明文標註「在舊的替代日曆下算的」——
靜默保留等同把舊日曆結果冒充成 canonical。

**教訓**：任務描述是**建單當下**的認知快照，不是交付規格。這張單建於 07-20 04:09，而顯著性撤回
發生在其後的 Codex round 1-3。照描述做會產出「數字對、結論錯」的更正，比不更正更糟——因為它會
帶著新鮮的 errata 時戳。更正類任務開工前必須重讀**認證終態產物**（此處 `*_cert_merge_summary.json`），
以它為準，不以建單描述為準。

**未完**：另 6 篇（d721672b / 630d0010 / 44fb4b90 / a1fd229a / ffb14405 / 76475146）待同深度處理；
`mile_d9129566` 已 retracted，不需更正。`assign_759a28f3` 已 release 回池並帶 progress/finding 註記。
另發現 `article_correction` 無法更正 title，而 `mile_eda69bfb` / `mile_d721672b` 標題都寫著「195 次」
——目前只能改內文，標題仍是舊數，需補 title 支援。

### 2026-07-22 08:2x — 10 張任務（含 4 張 P1）被一個寫死的「額度重置日期」凍結 3 天 — FIXED

查 K1708 為何餓死時的順帶發現。`experiments/K1708/REMEDIATION_rev2.md` 寫著「Codex 額度**實測**耗盡，
重置 2026-07-25 13:30 台北」，於是 round-2 二審沒跑、`review_verdict.json` 沒產出、
`merge_worktree.sh` 認證閘門正當 ABORT——實驗跑完了卻合不進去。

本班用有界 wrapper 實測兩次：`codex_exec_bounded.sh --timeout 100 "reply with exactly: QUOTA_OK"`
→ `QUOTA_OK` exit 0；再問一則實質問題 → 正常作答 11,486 tokens exit 0。usage limit 是全域擋所有
呼叫的，**有呼叫成功就代表限制沒生效**。前提推翻，成本：約 90 秒。

隨即掃 `next_tasks.json` 找同源凍結，命中 **10 張 `status=blocked` 且 `blocked_until` 全指向
2026-07-25** 的任務（P1：`assign_67f56b79` / `assign_24ebe308` / `k1623_round3_codex_primary_review_gate`
/ `assign_50256f5f`；另 6 張 P2 含 K528、K1729、K1730/K1731 合併）。全部走
`scripts/mark_task_blocked.py --unblock` 解封並 annotate 推翻證據。blocked 23→13，pending P1 1→5。
其中多數是「實驗早已跑完、只差一次審查與合併」的收尾工作。

**根因不是額度，是流程。** 某一班撞到 usage limit，把 CLI 回報的重置日期當事實寫進 `blocked_note`
與實驗文件，之後每一班**沿用那個日期而不重探**。`blocked_until` 是單向的：它只會等到日期，
不會反問「現在還成立嗎」。額度提早恢復時，沒有任何機制會發現。

**教訓**：外部資源可用性（額度 / 認證 / 配額）**不可以寫成日期常數當事實流傳**。它是一個
一秒就能實測的**狀態**，探測成本遠低於誤判成本（本例 3 天 × 10 張，其中 4 張 P1）。凡是以
「外部資源不可用」為由 block 的任務，解封條件應該是**重探成功**，不是**日期到期**。
此條與上一則「任務描述是建單當下的認知快照，不是交付規格」同形——都是把某一刻的觀測凍結成
事實往後傳；也與 §J「探針要架在 outcome 上，不是架在便宜的中間節點」同源，只是這次那個
便宜的中間節點是一個寫死的日期字串。

**未完**：`scripts/unblock_expired_blocked_tasks.py` 目前只比對日期。對
`reason=codex_quota_reset_pending` 這類「可實測」的 block reason，應加一條**主動探測**路徑：
探測成功即解封，不必等到日期。沒有這條，同樣的凍結會再發生一次。

### 2026-07-22 10:xx — K1623：同一份稿子連過 5 位審查者，每一位都放行了下一位才抓到的 blocking defect

`assign_5aa9d5f5`（K1623 修復單）的第 6 項要求把「reviewer 可靠度」記進 error_log。當時只有
兩個資料點；到今天已累積五輪，形狀比原本那條觀察更清楚，所以在收單時一次寫完。

| 輪次 | 審查者 | 路徑 | 判定 | 下一輪在同一份稿子上找到什麼 |
|---|---|---|---|---|
| 1 | codex gpt-5.5 | primary | **no CRITICAL/HIGH** | ↓ |
| 1' | codex gpt-5.6-sol（獨立二審） | primary | **FAIL**（7 項） | 識別宣稱不成立、DM 只跑 QLIKE 而 MSE 方向相反且未揭露、20 個比較無多重比較修正、ELW 方法描述與 code 不符…… |
| 2 | codex | primary | **FAIL** | claim-alignment 仍未對齊 → rev3 |
| 3a | agy | **fallback** | **PASS** | ↓ |
| 3b | `feature-dev:code-reviewer` | **fallback** | **CONDITIONAL PASS** | ↓ |
| 3c | codex 0.144.6 / gpt-5.x `-s read-only` | **primary** | **FAIL**（3 項） | arm A 重跑 BIC 同時選斷點**個數與位置**，故 A−B/`f3` 混合了 break-count selection 與 break-location estimation，並未隔離它宣稱的通道（`k1623_rev3_armc_mc.py:170`）；500 reps 下 2/2/1 dominant-channel attribution 不可識別（SPY gap 0.31% vs MC SE ≈3.2%）；README §1 line 77 與 Arm C／§6.4 直接自相矛盾 |

**兩條不同的教訓，別混為一談。**

其一（已知，K1259）：**fallback PASS ≠ primary-path PASS**。3a/3b 兩位 fallback 審查者都放行，
primary path 一跑就是 3 個 blocking defect，其中第一個是 **arm 設計本身的口徑錯誤**，不是措辭問題。
這正是把 primary path 訂為放行前置條件的理由，round-3 這一輪證明它不是形式主義。

其二（新）：**同路徑、同等級的審查者之間，變異也一樣大**。輪次 1 與 1' 都是 primary path 的
codex，一個說「no CRITICAL/HIGH」，另一個判 FAIL 並列出 7 項——其中「DM 只跑了 QLIKE、MSE
方向相反」這種缺陷，是把 README 的宣稱對著 artifact 讀一遍就會撞見的，不需要任何領域直覺。
所以差異不能全歸因於模型強弱；**一次 PASS 只是「這一位這一次沒看到」的證據，不是「沒有問題」的證據**。

**可操作的推論**：單一 PASS 不足以放行，這在 K1259 之後已經是規則；但本案再加一條——
**連續多輪 PASS 也不等於收斂**，只要每一輪找到的缺陷層級沒有下降。K1623 五輪的缺陷層級是
宣稱層（rev1）→ 宣稱層（rev2）→ **設計層**（rev3），**不降反升**：越審越深，代表前幾輪的
PASS 根本沒觸及那一層。放行條件應該看**缺陷層級是否收斂到瑣碎**，不是看**連過幾次**。

**現況**：rev2 已把 `assign_5aa9d5f5` 要求的撤回／補做全部落在 branch
`worktree-dispatch-slot-2-c5cafe39-k1623`（README §0 撤回總表 8 條、MSE 的 DM 補齊、
BH FDR + Bonferroni、ELW／FD_MAXK／VIX cap binding／BreakRobustHAR 描述更正）。
merge 仍由 round-3 的 3 項 blocking defect 封鎖，出口是
`k1623_rev4_remediation_after_codex_round3_fail`。**main 的 `experiments/k1623/README.md`
目前仍是未修復的第一輪版本**（仍寫著「純假象假說被拒絕」「不可交易」「多處顯著更差」），
在 rev4 合併前不可引用。

### 2026-07-23 — stale-base worktree merge 讓 `-X ours` 靜默刪掉 192 行活碼 — root_cause_fixed_and_verified

**症狀與物證**：merge commit `86e142305` 對第一父系 main 的
`scripts/compute_queue.py` 是 `+38/-7`，但對第二父系 worktree 是 `+0/-192`；worktree
上已驗證的 D6b stale-running reaper 沒有進入 merge 結果。既有 post-merge drop detector
只檢查 `experiments/`，所以 `scripts/` 下的活碼可消失而 merge 仍成功。

**根因層級**：這是 merge contract 缺口，不是單次衝突。worktree base 落後 main 時，
main 與 worktree 可能從共同 merge-base 起修改同一路徑；`git merge -X ours` 會替無人審核的
語意衝突選 main 版本，且「merge exit 0」不證明 worktree 變更仍在。

**底層修復**：`scripts/merge_worktree.sh` 在 merge 前解析 merge-base，分別建立 main /
worktree 的 changed-path set。main 已前進且 set 有交集時 fail closed，列出重疊路徑並保留
worktree / branch，要求明確 rebase 或人工整合後再跑；路徑不相交才允許 stale merge。
worktree 相對 merge-base 呈現 `+0/-N` 的 pure-deletion path 另行告警，避免把活碼覆成舊版。

**回歸與回讀**：Case 23 先在舊版重現 merge exit 0、worktree 被移除，再於修後確認
pre-merge ABORT、main bytes 不變、worktree/branch 仍存在、重疊路徑與 pure-deletion 路徑
均出現在輸出。Case 9 確認舊的「merge 後自動覆回 agent」契約改為兩側 bytes 都保留；
Case 11 確認 cron 只改 `feed.json`、agent 只加實驗時仍可合併，避免把所有 stale base
誤封鎖。制度契約同步寫入 `.claude/rules/worktree.md`。

### 2026-07-22 23:21 — 撤稿只有手改 feed、同步又丟掉 successor metadata — root_cause_fixed_and_verified

`storage/reports/feed.json` 原有 13 篇 `status=retracted`，但只有 `mile_ebb5d6f5` 帶
`retracted_superseded_by`；repo 沒有任何撤稿 writer 或 schema。這不是 12 筆資料漏填，而是共享 canonical
state 沒有 owner：欄位名已在任務間漂成 `superseded_by` / `retracted_superseded_by`，無後繼者時也沒有
「未知」與「忘了填」的機械區分。

**底層修復**：新增 `volpred.ops.retraction` + `scripts/retract_article.py`，所有撤稿走
`publisher_feed` lock、guarded atomic replace、read-back 與 writer provenance；CLI 強制二選一：至少一個
`--superseded-by`，或帶理由的 `--no-successor`。已存在的非空 metadata 若衝突會 fail closed，不容許把
二次改寫偽裝成 idempotent rerun。`config/article_retraction.schema.json` v1 固定四個 audit 欄位與 successor
/ no-successor XOR 契約，canonical-writer ratchet 同步登記新 owner。

**下游 class sweep 找到第二個根因**：第一次跑 canonical incremental sync 回報 `articles: 0`。原因不是
遠端已一致，而是 `projected_details()` 只投影原本的 `details`，把 feed top-level 的 retraction metadata
全部丟掉；因此 differ 與 writer 都認為「status 已是 retracted」就沒有變更。現在五個 v1 欄位會映射進
Supabase `details`，仍由同一 `projected_details()` 同時服務 differ 與 writer。

**回填與回讀**：13 篇全數經新 CLI 正規化；4 篇有明確 successor（只採既有可證的
`mile_ebb5d6f5`，以及任務核定的 `ec28b1cc→1a6d9369`、`beb61a8a→490d38ec`、
`b5a91c4d→bad0d545`），其餘 9 篇明示 successor unknown，沒有猜測。逐篇 Supabase sync + cache purge
成功後，fresh remote `compute_diff` 對這 13 篇回報 `insert=[] / update=[] / delete=[]`。相關 projection、
cache、diff、writer 與 auditor regression 共 68 passed / 1 env-gated skip；canonical writer audit 為
0 unguarded / 0 owner mismatch。

### 2026-07-23 20:49 — 老闆要求清空任務池後，既有 gateway 沒有全域停寫模式 — contained

**症狀與 live 物證**：Telegram msg 1329 要求先備份、清空
`storage/next_tasks.json`，並暫停所有新工作入池。切換前 deterministic probe 為
`pool_count=3338 claimed_pending=1 direct_mode=false`；現有 `pool_pressure` 只管
部分自動 generator，`append_task_record`、低階 whole-file writer、claim 與 handoff
都不知道「池已暫停」。直接把 JSON 寫成 `[]` 會讓下個 producer／:50 handoff 立刻
補回或重新 claim，清池本身不是可持續狀態。

**根因層級**：task writer 雖已在 A1b 收斂到
`next_tasks.write_tasks_to_handle()`，但 admission policy 仍散在 generator、append
gateway、claim CLI 與 prompt。最低共同 seam 只保證 serialize／lock，不擁有
runtime mode；因此沒有一個 transaction 能同時證明「備份已落地、後續新 id 已封鎖、
queue 已清空」。

**底層 containment**：新增 deep module `volpred.ops.task_pool_mode` 與
`scripts/task_pool_control.py`。`enter-direct` 在 queue `LOCK_EX` 內依序做 exact-byte
backup + fsync/read-back、寫入 enabled mode receipt、只保留明示的控制 task；最低
write seam 比對 write 前後 task identities，direct mode 只准既有 row lifecycle
更新或刪除，任何新 id／匿名 row fail closed。`task_pool_claim.py claim` 另在 claim
seam 封鎖；`generate_handoff.py` 看到 mode 後停止輸出 claim/refill/error-log fallback
指令。回復路徑只接受 active receipt 綁定且 SHA 相符的 backup，live pool 非空即拒絕。

**回歸與下游回讀**：切換備份
`sha256=89863b056e1dc4fb8a661a9ccf5caf1eeb058b063b42c528a25ce602f186d8f3`、
3,041,206 bytes、3,338 rows，清除 3,337 rows並暫留本控制 task。68 個
claim／mode／handoff tests 通過，canonical writer audit 為 0 unguarded / 0 routing
violation；live `direct-mode-canary-must-not-land` 被拒絕且前後 pool count 不變，
supervisor 回讀 `current_job=null`、health-check ok。測試另實際演練 SHA 綁定 restore。

**結案界線**：這只把老闆要求的「可回復清池＋暫停入池」做成不可靜默繞過的
containment。ADR-0001 的正式 Work Coordinator ownership cutover、Change Delivery、
commit fencing 與 manifest-based residue convergence 尚未完成七天 shadow／live
read-back，所以整體「派工／claim／commit／殘留」問題維持 **contained**，不得標
`root_cause_fixed_and_verified`。

### 2026-07-23 21:24 — 七日 cutover gate 信任 caller mode／時間並以跨日 union 對帳 — contained

**症狀與物證**：Issue #9 初版 assessment `d53a705a6` 的 CLI 允許 caller 傳
`--queue-owner-mode`、`--assessed-at`、`--required-days` 與 `--max-gap-hours`。
Matt Standards／Spec review 實證：live canonical mode 已是 `direct_execution` 時，
只要宣告 `legacy_queue_shadow` 即可得到綠燈；八筆全部晚於 assessment clock
30–37 天的 receipt 也能 `ready_for_cutover=true`。另有單日
`source_counts.next_tasks=1`、`comparisons=[]`，卻被其他日期的 dimension union
掩蓋；任意填 `classification=policy_change` 亦可繞過 blocking difference。

**根因層級**：這是 evidence-boundary 與 gate contract 缺陷。production verdict
把 owner mode、clock 與 acceptance window 當成 caller assertion，而不是 canonical
read-back；reconciliation 只證明整段期間「曾看過某欄」，沒有逐 observation／逐
candidate 證明完整；policy classification 沒綁回 Issue #7 的顯式 oracle。

**底層修復**：production `work-shadow-assess` 不再暴露上述 overrides，固定七日 window
與 26 小時 gap，並從 project-root canonical `storage/ops/task_pool_mode.json`
以**同一次 byte read**解析 mode／enabled 並產生 state SHA-256，避免 atomic replace
期間 mode B 配到 SHA A。append seam 把 receipt 升為 `work-shadow-replay.v3` 並自行寫入
`recorded_at`；七日 soak 用 append wall-clock，不再用可由 replay CLI 指定的
`observed_at`，兩者超過五分鐘即 fail closed。assessment 拒絕未來 receipt，逐份核對
queue row count、candidate identity 與五個必要 dimensions；`policy_change` 必須帶
candidate／dimension、snapshot、contract 與 oracle evidence refs，且完整 legacy /
Coordinator reason sets 必須符合 `work_shadow_replay.is_registered_policy_change()`
同一條 oracle rule 的 prerequisites，不能只借用已登錄的 reason-code 名稱。
selection difference 必須與 legacy／Coordinator selection views 精確一致；selected /
eligible refs 都要存在於 comparisons，eligible list 無重複且必須與各 comparison 的
`legacy_eligible`／`coordinator_eligible` flags 精確相等；winner 存在 iff eligible
set 非空。非 ranking reason 只能取自實際兩個 winner，不能借用未被選中 candidate
的合法差異。
所有 early failure 統一走單一 report constructor，避免欄位漂移。

**回歸與結案界線**：新增 caller spoof、future time、單日 row/dimension 缺口、
duplicate candidate、backdated replay clock、mode/SHA 單讀競態與
forged/registered policy-change prerequisites、ghost winner、missing difference、
unrelated-candidate borrowed reason 與 eligibility-view contradiction cases；
shadow assessment／
replay、direct-mode、claim 與 handoff targeted suites 通過。live mode 仍是
`direct_execution`，沒有七日 soak、CAS cutover、唯讀 legacy projection 或 rollback
rehearsal，所以 Issue #9 仍為 **contained**；七日真實 receipts 完成前不得標
`root_cause_fixed_and_verified`。assessment slice 最終 Matt
Standards／Spec 雙軸均 PASS（0 findings），135 個 targeted regressions 通過；但
live read-back 仍是 `mode=direct_execution`、`observation_count=0`、
`ready_for_cutover=false`，所以七日證據與正式 cutover gate 尚未達成。

### 2026-07-23 22:05 — task-pool owner mutation 在鎖外讀 state，過期程序可覆寫較新 transition — root_cause_fixed_and_verified

**症狀與證據**：`restore_task_pool_backup()` 與
`reconcile_direct_execution_pool()` 先在 queue lock 外讀
`task_pool_mode.json`，之後才取得 `next_tasks.json` 的 `LOCK_EX`；`enter-direct`
也沒有 expected owner identity。若另一個 operator／process 在兩者之間完成 owner
transition，舊程序仍可依過期 preserve set 清 row，或把較新的 owner state 改回
`queued_execution`。既有 backup SHA 只驗 backup 內容，沒有證明 mutation 仍針對
caller 最初讀到的 owner generation。Matt 首輪 review 另實證兩個同層缺口：
使用 active direct-mode 的**最新** SHA 重跑 `enter-direct` 仍會用已清空 queue
替換原始 rollback receipt；missing queue 的 enter／restore 則會在 CAS 前建立 `[]`，
把「canonical 遺失」靜默改寫成「合法空池」。

**根因層級與底層修復**：owner state 缺少 compare-and-set contract。現在
`task_pool_control.py status` 從同一份 state bytes 回傳 `state_sha256` 與 byte count；
`enter-direct`、`reconcile-direct`、`restore` 都強制要求
`--expected-state-sha256`（首次無 state 必須顯式傳 `absent`）。三個 mutation 在
queue `LOCK_EX` 內、任何 backup／clear／restore side effect 前重新讀同一份 state
bytes 並比對 SHA；不一致拋出 typed `TaskPoolModeConflict`，queue、backup 與 owner
state 保持不變。`enter-direct` 的合法 source transition 另固定為 state absent，或
`enabled=false, mode=queued_execution`；active direct／未知或不一致 mode 即使 SHA
最新也拒絕。enter／restore 遇 missing queue 會先核對 CAS identity，再 fail closed，
不建立 parent directory 或 queue。

**回歸、回讀與制度化**：public function／operator CLI tests 覆蓋 stale restore、
stale reconcile、stale enter、missing-queue no-materialization、fresh-SHA direct
reentry 不可替換 receipt且原 backup 仍可 restore，以及 status CAS identity；既有 exact-byte backup、
admission deny、lifecycle、reconcile 與 restore regression 同時通過。live read-only
`status` 回讀目前 owner state SHA-256
`45aa8ca239f8b33fd6790e6a022d2277e44491e01c1581101082119e71d630b4`、
mode=`direct_execution`、pool_count=1。canonical `docs/architecture.md`、
`docs/quick-commands.md` 與自動 handoff 已改成先讀 SHA、再 mutation，舊的無 CAS
命令不再被產生。Matt 首輪 Standards／Spec 各找出一個 P1（fresh-SHA reentry 與
missing-queue restore side effect），兩項均以 public regression 修復後複審 PASS，
0 個剩餘 P1/P2；Issue #9 相鄰套件 142 passed。最終 full suite 為
4,630 passed／1 skipped／3 failed；三項仍是 direct-mode containment 的已知相鄰
失敗（urgent-lane fixture 洩漏 live mode，以及 queue clear 後兩個 roadmap P1
缺 backing task），沒有新增 CAS failure，也沒有用本切片掩蓋。

**Issue #9 界線**：這個 stale-owner race 已完成五步 gate；但跨 JSON/state 的
crash-atomic restore、七日 receipts、Work Coordinator 正式 ownership transaction、
legacy read-only projection 與 rollback rehearsal 仍未完成，所以 Issue #9 整體
維持 **contained**。最終 Matt Standards／Spec 雙軸 review 均 PASS（0 P1／P2）；
direct-mode／claim／handoff／shadow assessment／replay targeted suite 142 passed。
完整 suite 為 4,630 passed、1 skipped、3 failed；三項均為 direct-mode 清池後已知的
相鄰狀態（兩個 urgent-task fixture 洩漏 live mode、兩個 roadmap P1 缺 backing task），
未以本修正掩蓋。

### 2026-07-23 22:58 — task-pool restore 在跨檔 commit 中途先重開 admission — root_cause_fixed_and_verified

**症狀與證據**：原 `restore_task_pool_backup()` 先把
`task_pool_mode.json` 寫成 disabled `queued_execution`，才透過 canonical writer
把 backup rows 寫回 `next_tasks.json`。一般 Python exception 雖會嘗試把 direct-mode
receipt 寫回，但 process death／machine crash 不會執行補償；crash window 內的 durable
狀態會是「admission 已開、queue 仍空白或只寫一部分」。另一個 automation 可在此時
合法 claim／refill，破壞 rollback 的唯一 owner 與 backup identity。

**根因層級與底層修復**：這是跨兩個 JSON owner surfaces 的 transaction ordering
缺陷，不是資料內容錯誤。Restore 現在先在 queue `LOCK_EX` 內以 atomic replace 寫入
schema v2 `enabled=true, mode=restore_in_progress` receipt，綁定原 direct-mode state
SHA、resolved queue path、backup SHA／bytes／row count、request actor／reason；接著才把 backup exact bytes
寫回 queue、fsync 並逐位元 read-back，最後才 commit disabled `queued_execution`。
若 crash 發生在 queue write 前、途中或後，普通 writer、claim 與 handoff 全部仍 fail
closed；使用 `status` 取得 prepared state 的最新 SHA，沿用同一 backup 重跑 public
`restore` seam，會覆寫空白／部分／已完整 recovery bytes，驗證後冪等 finalise。缺欄、
非 64 位 lowercase hex 的 source／target SHA、或與 active backup identity 不符的
prepared receipt，都在碰 queue 前拒絕。State atomic replace 在 rename 後 fsync
parent directory，避免 reboot 遺失 prepared marker；`status` 遇
`restore_in_progress` 的 partial／invalid queue 不再先崩潰，而是保留 state SHA 並輸出
`queue_readable=false` 與解析錯誤，讓 operator 能完成 receipt-bound retry。原 backup
bytes/count、target bytes/count 與非空 started_at／actor／reason 都在 queue mutation
前驗證。

Prepared retry 即使發現 queue path 上的 bytes 已等於 backup，也會在 final owner-state
前無條件對 locked queue fd flush/fsync；不能把前一個 crash process 留在 page cache
但尚未 durable 的完整 bytes 當成已提交。handoff JSON loader 同步捕捉
`UnicodeDecodeError`，queue 若剛好截斷在 UTF-8 多位元字元中，仍會產生
`RESTORE TRANSACTION：IN PROGRESS` recovery 指示。

Matt Spec 首輪複審另實證：若只綁 backup、不綁 queue，caller 可拿 q1 的 active
state／backup 改對另一個空 q2 執行 restore，造成 q1 仍空、q2 收到 rows，owner state
卻已重開 admission。現在 mode schema 解析並保留 `queue_path`；direct、
`restore_in_progress`、reconcile 與 restored receipt 都 exact-match 同一 resolved
identity，prepared payload 不再採用 retry caller 的路徑。public wrong-queue regression
證明 q1、q2、state 與 backup bytes 全部不變。

Matt Spec 第二輪再實證 queue 與 state_path 仍可拆開：detached state 可顯示 gate
enabled，但 canonical writer 會從 queue parent 讀另一個不存在的 state，等同清池時
admission 仍開。現在 `task_pool_mode_path()` 先 resolve 真實 queue（含 symlink），再
唯一衍生 `ops/task_pool_mode.json`；所有 control transition 與 status 都在副作用前
驗證 exact pair。detached state 與 symlink alias-state regressions 證明 queue、兩個
state candidates 與 backup inventory 均不變。

後續複審再找到兩個 identity 邊界。第一，同一 parent 的 `next_task.json`（少 s）
原本也能配到同一 state，造成「錯檔已切換、canonical queue 未動」卻回報成功；現在
resolved queue basename 強制為 `next_tasks.json`。第二，symlink 雖先用來推導 state，
後續 open/read-back 仍曾沿用 lexical alias，alias 若在驗證後 retarget 會形成 TOCTOU。
現在 enter/reconcile/restore/status 在入口只 resolve 一次，後續全用固定真實 path；
restore 的 compare/write/fsync/read-back 更只用同一 locked binary fd。Sibling filename
typo與 validation 後 symlink retarget regressions 均證明 canonical queue/state identity
不會被替換。

Matt Standards 後續複審又指出 handoff 原本先讀 queue、後讀 state，沒有共用 lock：
restore write 中途可把 partial queue fallback 成 `[]`，隨後卻讀到 final queued state，
誤輸出「空池應補題」。現在 handoff 以 queue `LOCK_SH` 包住 owner state 與 queue bytes
的同一 snapshot，與所有 control mutation 的 `LOCK_EX` 互斥；queue JSON／UTF-8
不可讀或檔案缺失時，即使 owner state 看似 queued，也一律輸出
`TASK POOL SNAPSHOT：UNREADABLE` 並封鎖 claim/refill。Lock-order regression 與
queued-mode corrupt-queue regression 固定此 fail-closed contract。

同一複審也延伸到 owner-state 半邊：先前 handoff 對 malformed state 使用 `{}` fallback，
仍可能輸出正常 claim/refill。現在只有 state 檔案不存在可代表預設 queued execution；
現存但 JSON／UTF-8 損壞、root 非 object、enabled/mode 型別錯誤或 enabled unknown mode
都回報 invalid snapshot，與 canonical writer／claim 的 fail-closed 契約一致。三種
invalid-state regressions（壞 JSON、list root、unknown enabled owner）均禁止空池 fallback。

**回歸、回讀與制度化**：public regression 分別重建「prepared、queue 尚空」與
「queue 已是 exact backup、final state 尚未寫」兩種 durable crash snapshot，兩者都
恢復 exact bytes、保留原 rollback actor／source state identity，並落地 transaction
state SHA；prepared／final owner state 也逐位元 read-back，storage 回讀不符時不會
誤回報成功。malformed receipt 測試證明 queue 與 state bytes 完全不動。handoff regression
證明 `restore_in_progress` 不再被當成一般空池，而是明示 retry `restore` 並禁止
claim/refill；CLI help、`docs/architecture.md` 與 `docs/quick-commands.md` 同步成同一
recovery 契約。此「先開 admission 的 crash window」完成五步 gate，狀態為
**root_cause_fixed_and_verified**；Issue #9 的七日 receipts、正式 Coordinator
ownership cutover、legacy read-only projection 與 live rollback rehearsal 仍未完成，
所以 Issue #9 整體仍為 **contained**。

Matt Standards／Spec 經多輪 adversarial review 與 immutable commit 回讀後均 PASS
（0 個剩餘 P1／P2）。Post-commit Standards 曾再抓出 handoff 對 list 內 malformed
row 仍會 `.get()` 崩潰的 P2；follow-up locked loader 現要求 `id/status/task_type`
為必要非空字串，`title` 可省略但若存在必須是字串。14 組 non-object、wrong-type、
missing、null、empty 與 whitespace public regressions 都輸出 unreadable/fail-closed，
不再產生 claim/refill 指示。最終 direct-mode、claim、handoff、shadow、queue pairing、
roadmap 與 urgent-lane 相鄰套件 242 passed。主要程式修正後的 full pytest assertions
為 4,656 passed／1 skipped／0 failed；
process exit code 仍為 1，唯一原因是 CI-parity session auditor 偵測既有未追蹤 live
`.claude/worktrees`／ops receipts 被部分 tests 讀取。這個 repo-wide fixture hygiene
問題與本 slice 無因果關係，未把路徑加入永久 parity baseline、未 skip、未掩蓋；
follow-up focused suite 66 passed，exact-path diff check 與 compile check 均通過。

### 2026-07-24 — Cutover 若只信 `ready_for_cutover` boolean，證據與 mutation 仍可脫鉤

**症狀與根因層級**：Issue #9 已有 shadow assessment、legacy importer 與唯讀
projection，但三者仍是分開的回傳值。若未來 ownership transaction 只檢查
`assessment.ready_for_cutover`，caller 可重建 dataclass、沿用 stale owner-state SHA，
或把一份通過的 assessment 配到另一份 legacy snapshot／Coordinator projection。
這是 cutover evidence identity 與 CAS transaction 尚未綁定的流程契約缺口；不是
live queue 資料錯誤。

**底層修復與回歸**：新增 read-only
`prepare_work_ownership_cutover()`。最終 seam 不接受 caller 建好的 assessment、
import report 或 SHA：它從 immutable receipt directory 用 trusted wall clock 重跑
canonical assessor，從同一次 owner-state bytes 取得 mode／CAS SHA，並從 raw legacy
bytes 自行計算 SHA、decode 與重建 import report。最終 seam 不再接收 queue／state
path：它固定解析 repo canonical queue，由 queue 唯一衍生 paired state，並在 shared
queue lock 內取樣，避免 detached fake owner。Canonical assessor 同時產生 receipt-set
digest 與最後 snapshot identity；最後一筆必須 exact-match 本次三來源 cutover
snapshot，不能拿 task-1 的七日 ledger 切 task-2。Projection payload 再自行
canonicalize，row count／SHA 不信任 public dataclass metadata；既有 importer
round-trip 逐 identity 比對 priority、claim ownership／started timestamp、parent、
deadline、dispatch／fallback policy、row created／updated timestamp 與 terminal
disposition；無法由 Coordinator 表示的 policy 直接阻擋。公開
regression 證明 staged projection 只漂移 `created_at`／`updated_at` 也會 fail closed，
不能取得 manifest。通過後 manifest 以 canonical SHA-256
綁定五份 derived evidence。public regressions 覆蓋短／過期 receipt ledger、
cross-wired raw snapshot、ledger/cutover mismatch、detached owner spoof、
forged projection metadata、dispatch/timestamp drift 與 running
`started_at` drift；preflight／assessment／projection／replay／direct-mode／claim／
handoff／claim 相鄰 suite 230 passed。

Standards 第三輪另抓到 `LegacySnapshots` shallow-frozen 的 mutable-row TOCTOU：
同一 caller object 若在 queue equality、import 與 snapshot hash 三次讀取間改動，
仍可能交叉綁定不同 generation。最終 seam 入口先 canonicalize 三來源一次並 decode
成 private copy，後續所有 evidence derivation 只讀該 copy；adversarial importer
mutation regression 證明原 caller row 雖被改動，manifest 仍只反映入口 generation。
Spec final smoke 再把同一根因追到 canonical replay producer：舊
`replay_legacy_selection()` 先後三次 canonicalize caller，A→B→A 可讓中間 B 的
snapshot hash 配到第一次 A 的 selector/comparison，結尾 equality 又因回到 A 而通過。
現在 replay 入口也只做一次 `freeze_legacy_snapshots()`；hash、import、兩側 selector
與 comparisons 全部只讀 private copy。ABA public regression 固定原 caller 只被讀一次，
且三個 ledger SHA 均等於入口 generation。

**狀態**：此 preflight 缺口已制度化止血，但尚無正式 DB/filesystem CAS ownership
transaction、七日 live receipts、unique-owner 下游回讀或 live rollback rehearsal。
因此本切片與 Issue #9 整體都仍是 **contained**，不得宣稱
`root_cause_fixed_and_verified`。

### 2026-07-24 — Active claim 欄位 parity 不等於 lease continuity

**症狀與物證**：`prepare_work_ownership_cutover()` 原本只要 legacy row 與 staged
projection 的 `claimed_by`、`claimed_at`、`started_at`、expiry 等欄位相同，就能為
`claimed`／`running` work 產生 manifest。Public RED regression 實際建立兩側完全相符的
active claim，舊實作兩例都未拒絕。可是 legacy worker 持有的 mutation token 不存在於
read projection，也沒有可由 ownership transaction 驗證或移交的 durable token identity；
欄位相同只能證明 read model parity，不能證明舊 worker 在切換後仍有合法寫入權。

**根因層級與底層修復**：這是 ownership transaction 前置契約缺少 quiescence gate，
不是 queue 資料錯誤。Preflight 現在仍先完成完整 projection parity，確保 timestamp／
policy drift 保留原本的精確錯誤；其後才要求 canonical `next_tasks` 的 imported status
不存在 `claimed`／`running`。任一 active lease 會列出排序後 work id 並在 manifest
hash 產生前 fail closed，不用無法證明的欄位一致冒充 lease continuity。

**回歸、回讀與制度化**：兩個 public cases 覆蓋 claimed 與 running（含 acquired／
started event）且先 RED 後 GREEN；Issue #9 preflight／projection／assessment／replay／
import／direct-mode／handoff／claim 相鄰 suite 為 232 passed。Live read-only status
仍是 `direct_execution`、pool_count=1、claimed_pending_count=0、owner state SHA-256
`45aa8ca239f8b33fd6790e6a022d2277e44491e01c1581101082119e71d630b4`，沒有執行 live
cutover。契約同步寫入 architecture、operations-core module design 與 improvement
status。

**狀態**：此 active-lease preflight 漏洞已完成五步 gate，為
**root_cause_fixed_and_verified**；Issue #9 仍缺七日 live receipts、正式
DB/filesystem CAS ownership transaction、unique-owner 下游回讀與 rollback rehearsal，
所以 Issue 整體仍為 **contained**。

### 2026-07-24 — Cutover manifest 未綁定 projection schema identity

**症狀與物證**：`prepare_work_ownership_cutover()` 只重算 staged projection 的
payload SHA／row count，沒有驗證 `schema_version`，manifest 也沒有保存該 identity。
Public RED regression 把 production projection 以 `dataclasses.replace()` 改成未知
`next-tasks-read-projection.v999`，舊實作仍產生有效 manifest。這代表未來不相容的
projection contract 只要碰巧輸出相同 bytes，就能跨過 ownership preflight。

**根因層級與底層修復**：這是 evidence identity 契約缺口，不是 payload 對帳錯誤。
Production projection module 現在公開唯一 schema constant；preflight 在讀 payload
前要求 exact-match，未知 schema fail closed。Cutover manifest 升為 v2，並把
`projection_schema_version` 與 projection SHA 一起納入 canonical manifest hash，
使 transaction caller 無法把「內容相同」誤當成「相容性契約相同」。

**回歸、回讀與制度化**：未知 schema case 已先 RED 後 GREEN；preflight 全套 16
tests 通過，manifest regression 同時核對 v2 與 production projection schema identity。
Canonical architecture、operations-core module design 與 improvement status 均已同步。
Live owner status 會在提交前再次只讀回讀，本切片不執行 cutover 或 task-pool mutation。

**狀態**：此 projection-schema evidence gap 已完成底層 seam、回歸與制度化，
為 **root_cause_fixed_and_verified**；Issue #9 仍缺七日 live receipts、正式
DB/filesystem CAS ownership transaction、unique-owner 下游回讀與 rollback rehearsal，
所以 Issue 整體仍為 **contained**。

### 2026-07-24 — SMTP acceptance 仍可被誤當成通知已送達 — contained

**症狀與根因層級**：Effect Delivery 已有 durable request／outbox／settlement，但沒有
任何 production-shaped provider adapter；現行 EmailNotifier 的 transport seam 在 SMTP
呼叫未拋例外後即標記 `sent=true`。這只能證明 local call／SMTP acceptance，不能證明
下游 Sent mailbox 有 exact message，也無法讓 outbox replay 在重寄前辨認已送出的同一
effect。根因是 provider acknowledgement 契約缺少獨立 read-back，不是補一個 success
boolean 能解決。

**底層 containment**：新增窄的 `EmailNotificationEffectAdapter`，只接受 safe、單一
收件人的 typed email effect。Raw payload bytes 必須與 EffectRequest SHA-256 相符；
effect／target／acknowledgement 綁定後導出穩定 Message-ID。Adapter 在 SMTP 前先查
Sent mailbox；存在且 recipient／subject／plain／HTML body 精確相符便冪等 acknowledge，
不再重寄。SMTP 後必須經獨立 IMAP adapter 回讀 exact RFC822 bytes 才回傳
`AcknowledgedEffect`，evidence SHA-256 直接取自回讀 bytes；查無訊息為 retryable，
已存在但內容漂移則 terminal fail closed。`EmailNotifier` 只新增可選 Message-ID
threading，未複製第二套 SMTP implementation。

**初始回歸與結案界線**：fake Sent mailbox 與 production IMAP adapter contract
覆蓋成功 read-back、可驗證 replay 不重寄、SMTP 成功但 Sent 缺失、transport timeout、
raw payload drift、header injection、recipient／subject／body drift 與 exact evidence
hash；連同 Effect Delivery PostgreSQL settlement 及既有 EmailNotifier 共 133 tests
通過，全程未連網、未寄信。此 slice 已把 adapter interface 與 failure semantics
制度化，但尚未接 durable outbox worker／settlement、Primary Authority 或正式 caller，
也沒有 live send/read-back receipt；因此 program commit 13 與 notification ownership
仍是 **contained**，不得宣稱 live delivery 已完成。

**live shadow 追查出的真實根因**：第一個 controlled attempt 在 provider write 前即回報
`email_provider_error`。Gmail 對未 quote 的 `[Gmail]/Sent Mail` 回覆 command parse
failure；quote 後又證明此帳號的 Sent special-use mailbox 是在地化名稱，硬編英文名稱
仍無法選取。另一條 live migration 路徑也揭露本機 superuser 測試遮住的 PG17 差異：
非 superuser `CREATEROLE` executor 的自動 membership 形狀，以及 object ownership
transfer 前後 schema CREATE／role membership 的必要順序。這些都是 adapter／migration
contract 根因，不是 Gmail 或 Supabase 資料要手補。

**底層修復與正式驗證**：IMAP adapter 現在對 explicit mailbox 做 quoted-string encoding，
未設定時以 RFC 6154 `LIST` 的 `\Sent` special-use 自動發現在地化 mailbox。Migration
在 object owner transfer 期間才暫授 schema CREATE，並保留 definer membership 到所有
function privilege mutation 完成；PG17 fixture 以 non-superuser executor 重播全部
migrations。`EffectOutboxWorker.run_once` 將 claim、authority、payload、provider、
settlement 與 receipt 回讀收進同一 deep module；settlement 強制保存 token-redacted
authority evidence 並移除舊 unfenced overload。Supabase advisor 另發現 receipt outbox
foreign key 缺 covering index，已由 forward migration 補上。

Controlled live shadow attempt 2 已成功寄送 stable Message-ID email、從 Gmail Sent Mail
回讀 exact RFC822 bytes，將 evidence SHA-256 原子 settlement，並回讀 EffectRequest／
outbox `delivered` 與 attempt receipt `acknowledged`；143 個 scoped regressions、
PG17 migration replay、security／performance advisor 複驗均通過。IMAP mailbox、
PG17 migration 與 receipt index 三個具體根因為
**root_cause_fixed_and_verified**；但現行 production caller 仍未由 live Primary
Authority adapter、durable payload writer 及 ownership transaction 接管，因此原本的
notification success-semantics／program commit 13 整體仍是 **contained**。

### 2026-07-24 — Effect settlement 可偽造 authority，payload 也沒有 durable owner

**症狀與物證**：authority-fenced worker checkpoint 的 production shape 仍使用 Python
fake authority 與 file payload reader；SQL settlement 只檢查三個 authority 欄位非空，
未證明它們由 Primary Authority 簽發，也未綁定當下 outbox claim。Payload reference
同樣沒有 durable writer 或 immutable storage owner。新增 live-shaped path 後，PG17
fixture 首次插入 EffectRequest 又暴露第二個具體症狀：
`verify_durable_effect_payload` 明明以 definer SELECT policy 讀已存在 payload，卻回報
`unknown effect payload`。

**根因層級**：第一層是 authorization evidence 契約缺口：worker 自述的非空 references
不是 database-issued capability，settlement 無法辨識 stale lease、另一個 attempt 或
漂移 identity。第二層是 payload ownership 缺口：hash 只存在 request metadata，
provider 前沒有 durable bytes 與獨立 integrity check。PG17 假 unknown 則是 RLS
contract 錯誤：trigger 的 `SELECT ... FOR KEY SHARE` 在 FORCE RLS 下需要 UPDATE policy，
但 immutable payload 的 definer 刻意只有 SELECT，row 因而不可見。

**底層修復**：新增 private immutable payload store、Primary Authority lease／grant／
receipt store 與 effect authority grant store。`PostgresEffectPayloadStore` 透過 named
functions 寫入 bytes，資料庫重算 SHA-256，ref 只能等價 replay；worker 在 provider
之前重新驗證 hash，漂移時 terminal fail closed 且不呼叫 provider。
`PostgresAuthorityStore` 使用 database clock、單調 epoch 與 hashed fencing token；
`PostgresEffectAuthority` 原子驗證 exact lease、outbox claim、EffectRequest、WorkItem、
payload 與 acknowledgement identity。Settlement trigger 只接受 matching
database-issued grant。Payload verification 移除不必要的 row lock；immutable table
無更新路徑，因此維持 SELECT-only policy 才符合最小權限。

**回歸、回讀與制度化**：9 個 worker tests 與 23 個 PostgreSQL delivery tests 通過；
後者使用 PostgreSQL 17 non-superuser／CREATEROLE executor，重播所有 migrations，
並把 canonical migration 再執行一次驗證冪等。測試覆蓋 payload privacy／replay／hash
binding、lease replay／takeover／stale fencing／release replay、DB-issued grant
settlement、無 grant fail closed、FORCE RLS、function owner／fixed search path／grants
與 indexes。Supabase migration API 已套用 exact canonical bytes，remote receipt
`20260723230547 operations_core_effect_payload_primary_authority` 以同名 local no-op
receipt stub 對齊，較晚 canonical migration 保留給 clean replay。Live PostgreSQL
17 回讀為五表全 FORCE RLS、anon／authenticated 無 payload 或 authorize 權限、worker
只有必要 function 權限、兩個預期 index 存在；`volpred_ops` security advisor 為
0 lint，performance advisor 只有 10 個 shadow-table unused-index INFO。專案原有八筆
remote／local migration-history drift 未做 repair，未把歷史問題冒充本切片變更。

**狀態**：durable payload、database-issued Primary Authority grant、worker pre-provider
integrity check 與 FORCE RLS row-lock 四個具體根因均完成五步 gate，為
**root_cause_fixed_and_verified**。但 program commit 13 尚未有正式 Work Coordinator
caller、production ownership transaction、unique-owner downstream acknowledgement
與 rollback rehearsal，因此整體 notification ownership 仍為 **contained**。
