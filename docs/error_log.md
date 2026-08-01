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
5. **anti-stacking**：一個 concern 只有一個 enforcement owner；修復要收編進既有 gate，不要每次疊一層新機制（見 §H 與 `docs/governance/enforcement_layer_map.md`）。

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
- 2026-07-26 **ROOT_CAUSE_FIXED_AND_VERIFIED** Operations Core owner audit 漏查 active KeepAlive daemon，曾在 `com.volpred.dispatch-supervisor` 完全未載入時誤報 0 conflict；reconciler 現把 `runtime_schedules.json.daemons` 納入 required surface，缺失即轉紅且 `--apply` 從 canonical plist 自癒 bootstrap。dispatch 通知標題另統一加 `[新架構派發]`，避免與退役 legacy 通知混淆 — `error_log_archive/2026-Q3-dispatch-supervisor-daemon.md`
- 2026-07-27 **CONTAINED** terminal-failed compute job 若 `followup_next_task_id == source_task_id`（自我 re-remediation 處置），source task 的 `compute_job_id` 從未被 reset → 每條重派路徑 by-design 拒絕：`enqueue-agent` binding gate（`_link_source_task`：bound_job_id 已設且非本 job → not-legally-bindable）與 `requeue`（followup_dispatched=true → disposition owned by followup）雙雙 refuse，task 永久卡 pending 進 starvation lockout。實例：`assign_k1731_rev9` 綁在早失敗 job `agent-k1731-armb-rev9-remediation`（exit 1、無 commit/artifact、worktree HEAD 未動）上卡 112h。**本班止血**：`task_pool_claim.py annotate --set-json compute_job_id=null`（該欄位不在 `ANNOTATE_PROTECTED_FIELDS`）清 stale pointer → sanctioned `enqueue-agent` 重綁 `agent-brief_k1731_rev9-c47c03` → task 進 awaiting_agent_job。**待 root fix**（非 slot-2 權限，需授權 slot 補測）：followup dispatcher 在 re-pend 自我 followup task 時應一併 reset `compute_job_id`，或 `cleanup`/reclaim 對「pending 且 compute_job_id 指向終態 job」的 task 補 pointer 清理（現行 cleanup 只處理 stale-claimed）。副作用：本班誤建的未綁定重複 job `agent-brief_k1731_rev9-87d87e`（source_task_link=error）run-next 依 state!=linked 永久跳過（inert），cancel 因 binding 不匹配無法移除，待 reaper GC — Q3
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
- 2026-07-31 **K1733 收件 gate 找錯位置，差點把好的 full-production 產物判成「必須重跑」**：`k1733-split-stage1-full-run` 的 followup brief 把 freshness gate 寫成「`reproduce_spec` 必須存在於 `K1733_results.json` 之內，否則代表 run 在最後崩掉，必須 re-run 而非 collect」。但 canonical writer `volpred.research.reproduce_spec` 的契約是**寫成 sibling 檔**（模組 docstring：「writes `K1750_results.json` 和 `reproduce_spec.json` side by side」），從不 inline 進 results JSON → 這條 gate 對任何正常完成的 run 都會誤判。實地驗證：`reproduce_spec.json` 的 `canonical_result_identity.sha256` 與 `K1733_results.json` 實際 bytes 逐位元相符（`9b4ead33…`, 322,085 bytes），證明 spec 是在 results 落地**之後**寫的，finalize 有跑完、run 沒有崩。**教訓：後置條件要對準 canonical writer 實際的產出契約，不要憑「應該長怎樣」寫 gate**；照這條 gate 執行的代價是丟棄一份完整實驗產物並重跑一次 heavy compute。狀態 **`contained`**（已證偽該 gate 條件並留證，但產生此 brief 的 split/followup 撰寫路徑尚未重構、亦無機械 gate 擋下同類錯誤斷言）— Q3
- 2026-07-21 K1623 arm C：review subagent **執行了它被指派審查的實驗碼**（違反「先審後跑」），產出未經 queue / gate 的 artifact — Q3
- 2026-07-19 **k1709 殭屍任務**：任務指向的 worktree 消失了，任務卻沒有任何機制發現 —— 自 07-14 起 blocked 5 天，不會被 dispatch 也不會被關單。根因是 **task pool 與磁碟從來沒有 reconcile**：`reclaim_stale_worktrees.py` 的安全條件只查 dirty，漏查 merged，於是「clean 但未合併」的 checkout 可被回收、branch 隨後也消失，而指著它的任務無人聞問。裁定結果 3 個 commits 其實已進 main（無遺失）。同次修復發現另外 4 個 worktree 共 9 個 commits 正處在同一個懸崖邊上，被新 gate 攔下 — Q3
- 2026-07-12 **3-STRIKE（K1032 class）** `.claude/worktrees/` 底下「獨立 repo」對 merge 的破壞 — Q3
- 2026-07-14 Merge 認證聲稱可用裸 `python3`，卻在解析子命令前 eager-import 專案套件 — Q3
- 2026-07-14 Review 對移動中的樹裁決：verdict 沒綁 commit SHA，一落地就過期 — Q3
- 2026-07-13 orphan branch：三個 commit 全被平行實作取代而丟棄 — Q3
- (K1032 原始教訓：merge_worktree 誤判「no commits」但 reflog 有 commit → 檔案遺失) — Q2

## D. Silent fallback / fail-open guard / exit-code masking

**規則**：不可用 silent fallback / try-except swallow / 靜默降級掩蓋 schema 或流程缺陷；護欄不可放在 fail-open 的 `try` 內（等於沒護欄）。hook / wrapper 不可把 shell pipeline exit code 當 tool outcome（pytest false-green）。silent fallback **當場修**，不丟下一班。
**機械 owner**：`.claude/rules/no-silent-fallback.md`（規則本體）+ pre-push silent-fallback baseline sweep + CI silent-fallback check（baseline 只准變少）。**gate 的 scope 必須等於 rule 宣告的 scope** —— pre-commit Gate 2 只餵 `scripts/` / `src/volpred/` / `.claude/hooks/` 的 staged path 給 auditor（其餘印明確 skip 行），regression pin = `scripts/tests/test_pre_commit_staged_scope.sh` case 8/9。
**代表 incident**：
- 2026-07-27 **STRIKE 2｜gate 的 enforcement scope 超出它 baseline 的 scope**：pre-commit Gate 2 把**所有** staged `.py` 餵給 auditor，覆蓋掉 auditor 自己的 `default_targets()`。baseline（`storage/qa/silent_fallback_baseline.json`，60 筆）只涵蓋 `scripts/` + `src/volpred/`，光 `experiments/` 就有 1237+ 個 finding 從未入 baseline → 研究腳本裡**早就存在**的 bare `except` 沒有 baseline entry 可比對，只要無關的編輯讓行號位移就被判 `NEW`，且**沒有任何 in-scope 修法能清掉**。當天 k1391/k1592 的 snapshot-dup 清潔重跑因此被擋，成果在工作區滯留數小時無人認領（PHASE-Z 的 pre-fire dirty baseline 又正確地把它們排除在自動 commit 外 → 誰都不會收）。**為什麼前次沒修好**：2026-07-21（`f7d9d1400`）已診斷出「子集稽核 vs 全 repo baseline」，但只修**訊息**（加 `scope_is_full` → 印 partial audit 註記），沒修 **scope 本身**，於是 gate 照擋。修法＝在 hook 內把 staged path 過濾到 rule `paths:` 宣告的範圍（與 `default_targets()`、CI 呼叫、baseline 內容四者一致），out-of-scope-only 的 commit 印明確 skip 行、保留 PHASE-Z 認的 `scope=` receipt。教訓：**gate 被繞不過去時，先問「它判的範圍是不是它有能力判的範圍」，不要先改訊息** — Q3
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
- 2026-08-02 **ROOT_CAUSE_FIXED_AND_VERIFIED** `publisher_arc_dedup` 已是 warn-only，NFP T-7 也在 warning 後 6 分鐘成功發佈，lifecycle 卻先因 event identity 漏接、再因沿用 blocking gate 的 `unjoined=harm` 定義而反覆誤報；統一 feed identity 現涵蓋事件 stage，warn-only policy 排除普通 unjoined、但任何舊硬鎖 resurrection 仍一筆即開 PDCA，不復活內容鎖 — `docs/error_log_archive/2026-Q3-publisher-arc-event-join.md`
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
- 2026-07-27 **root_cause_fixed_and_verified** 原版/v3 first-paint共用server snapshot後，
  原版stats API仍把knowledge count當實驗數在hydration覆寫；Zeabur env全量同步另刪
  analytics key，初版補救又把secret放進upload tree。Metric seam現統一
  `n_experiments`，Keychain只經source tree外temp env送variable API，container回讀
  無`.env.production`；desktop/mobile與production DB beacon驗收通過 — 全文：
  `docs/error_log_archive/2026-Q3-issue8-frontend-analytics.md`
- 2026-07-24 **root_cause_fixed_and_verified** generic effect outbox claim不帶
  provider capability，所有 narrow worker都會拿全域最舊 row；第二個 family上線後
  可能把他族合法 effect當 unsupported而 dead-letter。Provider現強制宣告
  `effect_kinds`，PG claim在同一 `SKIP LOCKED` transaction按 family篩選，worker回讀
  後再做 provider前 fence；舊 unfiltered RPC已移除。PG17交錯 family、production
  function／ACL／owner／definition與 active-claim=0回讀通過（publisher cutover及
  operations-core umbrella仍 contained）— Q3
- 2026-07-24 **root_cause_fixed_and_verified** `email.ops_alert` ownership RPC在
  host keepalive之外自行 acquire／release Primary Authority，讓 keepalive只是可選
  helper；caller改為三階段重驗同一 lease，SQL begin只接受預持 lease、settle不再
  越權 release，PG17 rollback contract與 production function／ACL／owner／zero-live-
  lease read-back通過（program commit 34 umbrella仍 contained）— Q3
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
- 2026-07-27 **root_cause_fixed_and_verified** CI watcher建立的`ci-root`雖為
  `platform_ops`，卻沒有producer-isolation execution contract；supervisor能fire但
  不能preassign，worker只能重複診斷。Watcher現從完整failed log只抽known-root literal
  repo paths，拒絕absolute/traversal/storage/glob，並把exact paths綁
  `repo_patch` contract；paths與run key持久化避免restart失憶。真run 30258321227
  回放精確取得3路徑，74 regressions綠 —
  全文：`docs/error_log_archive/2026-Q3-ci-root-execution-contract.md`
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

### 2026-07-24 — 正式 alert caller 首次 live read-back 被 SMTP CRLF 假漂移擋下

**症狀與物證**：`email.ops_alert` 已由 CAS 從 `legacy/1` 切到
`operations_core/2`；第一個正式 `volpred ops send-alert` 確實建立 durable
WorkItem、payload、EffectRequest／outbox、Primary Authority grant 並寄出郵件，但
settlement 終態為 `email_sent_mail_readback_mismatch`。DB 即時計算 payload SHA-256
與 EffectRequest 的 `f2e7e0a7…ecc8d37` 完全一致，Message-ID／subject／recipient
也相同。獨立 IMAP 診斷顯示 plain body 比 expected 多 3 bytes、HTML 多 57 bytes，
每個差異都來自 Gmail raw MIME 使用 CRLF，而 canonical payload 使用 LF。

**根因層級**：這是 downstream acknowledgement verifier 的 transport-normalization
契約缺口。`_transport_text()` 只 `rstrip(\"\\r\\n\")`，沒有把 SMTP wire format 的
CRLF／CR canonicalize；fake mailbox 又用預設 LF policy 產 raw bytes，因此既有測試
從未走過 production newline 形狀。這不是資料漂移，也不能靠手改 receipt 或放寬
exact-body gate 收尾。

**底層修復與回歸**：read-back comparison 現在先將 CRLF／CR 正規化為 LF，再只移除
transport 尾端 newline；subject、recipient、Message-ID、plain／HTML 內容與 raw
evidence hash 的其他 exact checks 不變。Fake Sent mailbox 改用 `email.policy.SMTP`
產生 CRLF raw bytes，讓同一 class 未來必須通過 production wire format。PG17 suite
另覆蓋 CAS cutover、request replay、active-attempt transfer rejection、Work／outbox／
Primary Authority、settlement、rollback replay、stale generation rejection 與
recutover；相關 suite 共 267 tests 通過。

**Production 回讀與 rollback rehearsal**：修後使用新唯一 key 寄出的
`effect_owned_email_1408c5e8812e08612817e355601b1561` 回讀 Work=`succeeded`、
effect／outbox／owned attempt=`delivered`。Durable payload SHA-256
`82c8a16c43f76f2afcec1ef9c34a102811b27ca201bb7e5578114ed901aa0155`
與 DB 重算一致；Gmail Sent 原始 bytes SHA-256
`da61bcddd154387d44aaa5b1b57370c5710d6aaf24d2e2bdce712cf0dc7a0846`
與 effect evidence 一致，Message-ID hash 也精確對應 evidence ref。之後成功執行
`operations_core/2 → legacy/3`，舊 generation request 被拒且 DB 零 row，再執行
`legacy/3 → operations_core/4`；final live read-back 是單一 owner row、零 active
attempts、四代 immutable ownership receipts。

**制度化與狀態**：formal caller 每次先讀 DB owner；owner DB 不可用即 fail closed，
不 fallback。Ownership tables FORCE RLS，五個 PostgREST RPC 只授權 service role，
function owner／fixed empty search path／definer CREATE revoke 均由 PG17 與 live
read-back 驗證。Remote receipts
`20260723234435 operations_core_notification_ownership` 與
`20260723235106 operations_core_notification_ownership_index` 有同名 local stubs，
較晚 canonical migrations 可 clean replay。Security advisor 沒有本 scope lint；
performance advisor 發現的 owner-generation FK covering index 缺口已修，複驗只剩
新 index 尚未累積使用統計的 INFO。`email.ops_alert` 的正式 caller、ownership
transaction、unique-owner acknowledgement 與 rollback rehearsal 五步全過，狀態為
**root_cause_fixed_and_verified**；其他 effect family 不在本結案範圍。

### 2026-07-24 — Commit actuator 的雙 fence 仍只有 fake authority — contained

**症狀與根因層級**：`GitCommitActuator` 已把完整 commit intent、WorkLease token 與
Primary Authority fencing token 交給 `CommitAuthority`，但唯一 adapter 是測試 fake。
既有 PostgreSQL Primary Authority 只能驗證 primary lease，不能在同一 transaction
證明 WorkItem 仍為 exact running version、claim token 尚有效；若薄包兩次查詢，兩個
lease generation 可在中間漂移。這是 Change Delivery durable authorization seam 缺口，
不是 Git writer 本身的 path／HEAD fence 錯誤。

**底層修復**：新增 private `PostgresCommitAuthority` 與
`authorize_commit_write` transaction。Adapter 在入 DB 前依 production canonical
encoder 重算整份 write-intent SHA-256，拒絕 caller 把合法 hash 配到修改後的 repo、
HEAD、path、content、message 或 token。Database function 先鎖 WorkItem，要求 exact
`running` version、非空 holder、matching/unexpired WorkLease，再沿用 durable
`authorize_primary_write` 驗證 database-clock Primary Authority。成功 grant 保存
proposal、Work holder、commit worker、repository／HEAD 及兩個 token-redacted refs；
raw tokens 不進 grant table。相同 request 冪等 replay，任何 durable identity drift
fail closed 且整個 transaction rollback。

**回歸、回讀與制度化**：public integration cases 覆蓋成功／等價 replay、stale
WorkLease、stale Primary Authority 與 forged request digest；新 migration 在
PostgreSQL 17 non-superuser／CREATEROLE executor 下重播全部 migrations，並把自身再跑
一次驗證冪等。Privilege read-back 確認 grant table FORCE RLS、PUBLIC 無 SELECT／
function EXECUTE、worker 只有 named-function EXECUTE、function 為 no-login definer
owner 且固定 `search_path`。Change／Effect Delivery 相鄰 suite 138 passed。

**狀態界線**：此 commit-grant adapter 未部署 live；grant transaction 結束後才進入
external Git writer，尚缺 `ChangeDelivery.land`、durable post-commit settlement／
receipt、external-write interval 的 lease revalidation、正式 caller 與 rollback
rehearsal。因此 fake-only authorization 缺口已被 durable contract containment，但
Change Delivery ownership 整體仍是 **contained**，現行 Git owner 不變。

### 2026-07-24 — Direct-mode preserved control row 被誤報為 pending drift／production backlog

**症狀與物證**：owner receipt 為 `direct_execution`，live queue 只有 receipt 明列的
`assign_f3f36d75`，`task_pool_control.py reconcile-direct` 回讀
`removed_task_ids=[]`、`retained_task_ids=[assign_f3f36d75]`，證明沒有 stale-writer
drift。然而 handoff 仍把該 row 標成「pending drift」並要求 reconcile；dashboard 也把
它算成 production pending，持續產生 `1 pending tasks` warning。該 row 已被 direct-mode
claim gate 機械封鎖，兩個建議都不可執行。

**根因與底層修復**：兩個 reporting consumer 只看 legacy lifecycle status，沒有把
owner receipt 的 `preserve_task_ids` 納入 backlog classification。handoff 現在先把
preserved control pending 與 receipt 外 drift pending 分開：clean receipt 只提示直接
續做控制任務，只有真正 breach 才提供 receipt-bound reconcile。dashboard 同樣回讀
owner mode；direct／restore mode 的 row 不再流入 production backlog、in-flight 或 stale
orphan 計數，direct receipt 外 identity 另以 drift warning 顯示。owner state 不可讀或
出現未知 enabled mode 時 fail closed，不會建議 claim／refill。

**回歸、live 回讀與狀態**：clean preserved row、receipt breach、direct-mode claim gate
與 pool control 共 86 個 targeted cases 通過；Python compile 與 `git diff --check`
通過（環境未安裝 Ruff executable）。live dashboard 回讀
`production_pending.status=ok`、`pending_count=0`、
`direct_control_row_count=1`、`direct_receipt_drift_count=0`；重生 handoff 顯示
`direct_mode_receipt: clean` 與 `Direct-mode preserved control rows: 1,
claimable: 0`，且不再要求 reconcile。此 reporting／control-plane 假告警完成五步
gate，為 **root_cause_fixed_and_verified**；owner 指定的整體 operations-core
重構仍是 **contained**，preserved control task 不在 legacy pool 內結案。

### 2026-07-24 — Commit grant 後到 Git 落地間沒有第二道 fence／durable receipt — contained

**症狀與根因層級**：`PostgresCommitAuthority` 只證明 external write 開始前
WorkLease 與 Primary Authority 有效；grant transaction 結束後，Git writer 才執行。
若任一 lease 在這段 interval 到期／被接管，舊流程仍可能產生 commit；process 若在
commit 後 crash，亦沒有 durable receipt 可分辨「尚未寫」與「已寫但未 settle」。
這是 Change Delivery transaction boundary／idempotency 契約缺口，不是補一筆 JSON
或延長 lease 可解。

**底層修復**：實作 `ChangeDelivery.land()` 兩階段 orchestration。Immutable
ChangeSet 先交給既有 authority-fenced actuator；一旦 exact commit/parent/path/blob
read-back 成立，狀態即成 `commit_unsettled`，DB failure retry 只續 settlement，不再
重跑 Git。新 `PostgresCommitSettlement`／`settle_commit_write` 會在 external write
後重新核對 exact running WorkItem version、holder、WorkLease token/expiry，並用同一
authority request 再驗 database-clock Primary Authority，才保存 immutable
`change-delivery-receipt.v1`。Receipt 不含 raw token；等價 replay 在 lease 日後過期
仍回原 receipt，任何 identity drift 都 fail closed。

**觀察先於修正的 PG17 物證**：第一輪 integration 回報
`commit settlement authority grant is unknown`，但 grant table 確有同 SHA row。
根因是 settlement 對 FORCE-RLS immutable grant 使用 `SELECT ... FOR UPDATE`；row lock
要求 UPDATE policy，而最小權限設計只有 SELECT/INSERT，於是 row 對 definer 不可見。
Final seam 對 immutable grant 使用 plain SELECT、只鎖可變 WorkItem；沒有為了讓測試
變綠而擴張 UPDATE 權限。

**回歸、read-back 與狀態界線**：unit cases 覆蓋 land success、等價 replay、
post-commit DB failure resume、landing-command drift 與 adapter missing；PG17
non-superuser cases覆蓋雙 fence 成功、WorkLease／Primary lease 在 external interval
失效、conflicting replay、settled 後 lease 到期的 durable read-back，以及 table／
function owner、FORCE RLS、PUBLIC revoke、worker-only execute。Supabase current
security/performance advisors 已回讀；174 個 Change／Effect Delivery 相鄰 tests
通過。Live read-only catalog 明確回傳 commit authority／delivery tables 與兩個
named functions 全為 `null`，確認沒有把 shadow migration 誤報成 deployed；現存
advisor findings 都是此 migration 尚未部署前的既有 public-schema 項目，本 slice
沒新增 public exposure。此 post-commit
authorization／receipt 根因已完成底層與隔離 DB 驗證，但 migration 尚未 live、
formal caller／workspace materializer／ownership cutover／rollback rehearsal 也未完成，
所以目前只能標 **contained**；不得把 Change Delivery 整體稱為完成。

### 2026-07-24 — Actuation wall-clock 未驗證便進入 durable settlement

**症狀與物證**：公開 `ChangeDelivery.land()` regression 讓 actuator 分別回傳
`not-a-timestamp` 與沒有 UTC offset 的 `2026-07-23T14:30:00`。修正前兩例都未拋錯，
直接呼叫 settlement 並把 ChangeSet 標成 landed。可是 `observed_at` 同時進入
settlement SHA-256 與 PostgreSQL `timestamptz`；非法字串會在 external Git write
之後才失敗，naive wall-clock 則可能被 database session timezone 隱式解讀。

**根因層級與底層修復**：這是 Change Delivery evidence-identity interface 的驗證缺口，
不是資料庫格式問題。既有 actuation receipt gate 只有 `strip()` 非空檢查；現在它在跨入
settlement seam 前以 ISO datetime parser 驗證，並要求 `tzinfo`／UTC offset 都存在。
失敗一律回報 `CommitActuatorBlocked`，ChangeSet 保持 `proposed`，settlement adapter
零次呼叫。

**回歸、回讀與制度化**：兩個 public-interface cases 已先 RED 後 GREEN；
`tests/test_change_delivery.py` 22 passed。Canonical architecture、operations-core
module design 與 improvement status 已同步這項 identity 契約；提交前會再回讀
direct-execution control gate 與相鄰 actuator tests。此具體缺口為
**root_cause_fixed_and_verified**；shadow migration、formal caller、durable proposal
store、Git ownership cutover 與 rollback rehearsal 仍未完成，所以 Change Delivery
整體仍為 **contained**。

### 2026-07-24 — `commit_unsettled` 只存在 process memory，restart 會再進 Git actuator — contained

**症狀與根因層級**：第一個 `ChangeDelivery` instance 在 actuator 已回傳 verified
commit、settlement 暫時失敗後，能靠 instance dict 記住 `commit_unsettled`；換成新
instance 即無法 `inspect` 原 ChangeSet，也沒有 actuation receipt 可續 settlement。
這是 proposal／actuation lifecycle 的 durable-state seam 缺口，不是多 retry 一次或
延長 lease 能修。公開 restart regression 在修正前會得到 unknown ChangeSet，且設計上
會重新進 Git actuator。

**底層修復**：新增 private `ChangeSetStore`，external
`propose／inspect／land` interface 不變。in-memory adapter 支援 interface tests；
`PostgresChangeSetStore` 以 immutable create、actuation checkpoint、landed linkage
三個 transaction 保存完整 lifecycle。checkpoint 只落 token-redacted receipt 與
canonical landing-command SHA-256，不保存 raw WorkLease／Primary token；landed
transition 必須 join 已存在且 exact-match 的 commit settlement receipt。Store
FORCE RLS，PUBLIC 無 table/function access，worker 只有 named functions 與
token-redacted read view。

**回歸、live 回讀與狀態**：跨兩個 `ChangeDelivery` instance 的測試證明 checkpoint
後 restart 時第二個 actuator 零呼叫；PG17 non-superuser migration replay、durable
reload、conflicting replay、RLS／PUBLIC 權限與相鄰 Change／Effect／Git 共 68 tests
通過。Production Supabase `qxhfgdfzazwpkdgesavm` 唯讀 catalog 回讀
`change_sets`、三個 lifecycle functions、commit authority／settlement tables 全為
`null`，確認 shadow migration 未部署。checkpoint **已提交後**的 restart 重複寫風險
已被底層封閉；但 Git commit 成功到 checkpoint transaction 提交之間仍有窄 crash
window，且 live migration／workspace materializer／formal caller／ownership cutover／
rollback rehearsal未完成，因此本項與 Change Delivery 整體都只能標
**`contained`**，不得宣稱 `root_cause_fixed_and_verified`。

### 2026-07-24 — Git commit 成功但 checkpoint 前遺失 return 會重入 writer

**症狀與根因層級**：durable `ChangeSetStore` 只能處理 actuation checkpoint 已提交後
的 restart。若 canonical writer 已建立 commit，但程序在 receipt return 或
`checkpoint_actuation` 前中斷，store 仍顯示 `proposed`；新 process 會以舊
expected HEAD 重入 actuator。先前 actuator 只看到 stale HEAD 並拒絕，既無法續
settlement，也無 durable evidence 說明現有 child 是否就是原 write intent。這是
external Git transaction lost-return seam，不是延長 DB lease 或重試 checkpoint 可解。

**底層修復**：`GitCommitActuator` retry 仍先重驗完整 WorkLease／Primary Authority
grant。HEAD 已前進時，只檢查 expected parent 後第一個 first-parent commit；candidate
必須同時符合 exact parent、完整 commit message、sorted exact path set 與每個
committed blob SHA-256，才以 Git committer 的 timezone-aware timestamp 重建
`commit-actuation.v1`。Mismatch 維持 stale-HEAD fail closed，canonical writer 不會被
呼叫；candidate 上方已有後續 mainline commits 仍可精確回讀。

**回歸、狀態界線與制度化**：Git actuator cases 覆蓋 exact historical recovery 與
不同 message 的 lookalike refusal；跨 `ChangeDelivery` process case 直接讓第一個
actuator 在 commit 後遺失 return，確認第二個 process 從仍為 `proposed` 的 store
recovery、checkpoint、settlement，且 expected parent 到 HEAD 只有一筆 ChangeSet
commit。Change Delivery／Git actuator scoped suite 37 passed。此 lost-return 根因在
shadow interface 為 **root_cause_fixed_and_verified**；production workspace
materializer、formal caller、live migrations、ownership cutover 與 rollback rehearsal
尚未完成，所以 Change Delivery 整體仍為 **`contained`**。

### 2026-07-24 — ChangeSet 已驗證但 canonical checkout 沒有 production materializer

**症狀與根因層級**：`propose()` 只驗證 linked worktree，`GitCommitActuator` 卻假設
candidate bytes 已在 canonical checkout。公開 lost-return regression 修正前必須由
test 手動 `read_bytes()/write_bytes()` 搬兩個檔案才可落地；正式 caller 若照 interface
直接 `land()`，writer 讀到的是 base／其他作者 bytes。若另在 writer lease 外先 copy，
則會留下 overwrite race、commit 失敗殘留與 source drift window。這是 Change
Delivery workspace→writer transaction boundary 缺口，不是多一個 copy helper 可解。

**底層修復**：`ChangeDelivery.land()` 將 immutable proposal 的 `workspace_ref` 傳入
private actuator。Canonical `git_writer_lock.py commit --source-workspace` 在同一把
common-dir lease 內要求 registered non-main linked worktree，重驗 exact HEAD、clean
index、完整 dirty set 與每個 content hash，完成 atomic-file materialization、stage、
staged-blob fence、commit 與 object read-back。Canonical target 只可為 base bytes 或
前次 kill 留下的 exact candidate residue；foreign bytes、symlink 與 unowned deletion
均在覆寫前拒絕。一般 hook／commit failure 會 reset index 並還原 preimage；kill residue
則在重跑時以 proposal content hash 收斂，不需猜 producer。

**回歸、回讀與狀態界線**：四個新 writer cases 分別證明完整 materialization、
source drift 零 main mutation、foreign target bytes 保留，以及 pre-commit hook failure
還原；原 lost-return process case 已移除手動 copy，直接走正式 seam並驗證 canonical
bytes。Git writer／Change Delivery／actuator scoped suite 72 passed；canonical writer
audit 回讀 107 個 owner mutations，結果為 0 unguarded、0 owner mismatch、0 routing
violation。Direct-mode status 再回讀仍只含 owner-preserved control row。此
materializer overwrite／rollback 根因已達
**`root_cause_fixed_and_verified`**；formal Work Coordinator caller、live migrations、
Git ownership cutover 與 rollback rehearsal 尚未完成，因此整體 task 仍只能標
**`contained`**。

### 2026-07-25 — Primary Authority outage演練缺少安全operator seam，第一次receipt又保存stale expiry

**證據化症狀與根因層級**：Program commit 34雖已有`HostAuthorityKeepalive`與fake
renew-failure測試，但production outage仍只能靠臨時片段切transport，沒有機械限制
authority family、effect path、publisher owner或RTO證據。第一次正式300／60 live
演練成功demote與接管後，receipt的`primary.expires_at`卻取自initial acquire object，
不是healthy renew後的lease；控制流程正確，但保存證據少一代。根因是operator
transaction／evidence boundary未制度化，且renew read-back未成為rehearsal的canonical
lease identity，不是Supabase lease transaction本身失效。

**底層重構**：新增`scripts/rehearse_primary_authority_outage.py`。CLI只生成隔離的
`operations-core-outage-smoke-*` key，在第一個remote mutation前驗
publisher=`operations_core/8`；模組沒有authorize、outbox、provider或settlement
caller。一次healthy renew後，先以`current_lease()`固定最新lease evidence，再把整個
authority store切到實際不可達的`127.0.0.1:1` PostgREST transport。Keepalive demote
後立即證明local gate關閉；transport恢復時standby仍須等DB-clock expiry，成功只能是
exact next epoch。Receipt以temporary file + fsync + replace原子保存並逐欄JSON
read-back。

**回歸、production回讀與狀態界線**：28個outage／keepalive／session／Supabase adapter
tests通過，compileall與`git diff --check`通過。修正後production 300秒lease／60秒renew
replay的primary renewed expiry為`2026-07-24T17:27:27.770913+00:00`；transport outage
使local gate在60.526秒內demote，standby在239.962秒內取得epoch `1 → 2`並以release
receipt停在`stopped`。Durable receipt
`storage/ops/primary_authority_outage_rehearsal_latest.json`回讀successful claims=2、
duplicate claims=0、effect requests=0、provider calls=0；publisher fence前後都是
同一`operations_core/8`。因此live Supabase renewal-outage／五分鐘RTO operator seam為
**`root_cause_fixed_and_verified`**。兩個session仍位於同一台Mac process；真正跨兩台
實體Mac的network partition與其餘effect-family cutover尚未完成，program commit 34與
operations-core umbrella維持**`contained`**。

後續回歸也證實單process runner的demotion觀測有 thread exit競態：keepalive先把狀態
設成`demoted`，worker才真正退出，原本只等待state便立即assert liveness，會偶發失敗。
接受條件已改為`state=demoted AND worker_alive=false`。同一operator seam新增明確
`primary`／`standby`角色，以shared rehearsal ID跨主機共用隔離authority key；第三個
`verify-pair`角色會驗兩份machine fingerprint、implementation/receipt hash、
exact next epoch、primary DB-clock expiry後最多300秒handoff、固定publisher fence及零
duplicate/effect/provider。6個failure-injection/interface tests、compileall與
diff check通過。這個跨process演練介面缺口為
**`root_cause_fixed_and_verified`**；但尚無兩台實體Mac的live paired receipts，
operations-core umbrella仍為**`contained`**。

### 2026-07-24 — ChangeSet content identity 未綁 Git executable bit

**症狀與根因層級**：`changeset.v1`、commit authority 與 writer fence 都只綁定
exact path／blob SHA-256。公開 regression 證明同一 proposal 的 tracked 或 new file
可在 source 端切成 executable 而仍通過 `propose()`；materializer 會真的建立
`100755` commit。若程序遺失 writer return，stale-HEAD recovery 也會把 parent、
message、paths、bytes 全相同但 tree mode 不同的 lookalike 當作原 commit。這是
immutable write-intent 的 identity 缺口，不是 chmod cosmetic difference。

**底層修復**：目前 durable schema 尚未 live cutover，因此不以半套 migration 新增
欄位；bounded ChangeSet v1 明確禁止 mode transition。Tracked regular file 必須保留
base tree 的 `100644`／`100755`，new file 固定 `100644`。`propose()` 核對 workspace
與 base tree；canonical writer 在同一 common-dir lease 內再核對 source 及 target
mode，避免覆蓋 foreign chmod；post-commit verification／lost-return recovery 最後
比較 expected 與 observed tree mode。未來若需 executable new file，必須先把 mode
正式納入 proposal、authority request 與 durable receipts。

**回歸與狀態界線**：tracked／new proposal mode drift、writer executable new file、
recovery mode-lookalike 四個 RED cases 已轉 GREEN；完整 Change Delivery、Git actuator、
Git writer scoped suite 76 passed。此具體 mode identity 根因為
**`root_cause_fixed_and_verified`**；formal caller、live migrations、Git ownership
cutover 與 rollback rehearsal仍未完成，Change Delivery 整體維持 **`contained`**。

### 2026-07-24 — Lost-return recovery 未證明 commit 來自本次 authority grant

**症狀與根因層級**：公開 Git actuator regression 先由另一個 writer 在 expected
parent 上建立一筆與 command 相同 message、paths、blob bytes 與 file modes 的 commit，
再呼叫 actuator retry。修正前 `_recover_prior_commit()` 直接接受該 first child 並
產生帶本次 WorkLease／Primary Authority refs 的 receipt。也就是內容 identity 雖相同，
Git object 卻沒有任何證據證明由本次 authorize call 產生；這是 external transaction
的 provenance identity 缺口。

**底層修復**：Actuator 仍先重算並 authorize 完整 `commit-authority-request.v1`，
但交給 canonical writer 的實際 commit message 固定附加
`Volpred-Commit-Authority-Request: <request_sha256>` trailer。Digest 已綁 proposal、
WorkItem/version、Git owner generation、兩個 fencing token、repository/parent、
paths/hashes、原 message 與 commit-worker actor；raw token 不進 argv message、Git
object或 receipt。正常 writer
return 後的 object verification 與 historical lost-return recovery 共用同一個 bound
message constructor，trailer 缺失或不同都 fail closed。

**回歸、回讀與制度化**：unbound bitwise lookalike case 已先 RED（舊實作未拋錯）
後 GREEN；正常 commit 回讀的 trailer 與 `commit-actuation.v1` receipt 中
`authority_request_sha256` 精確一致，既有真 lost-return recovery 仍通過。提交前另跑
owner-generation regression，證明舊 generation 的合法 trailer 不可被新 generation
recovery 接受；並跑完整 Git actuator／Change Delivery／canonical writer scoped
suites、compile 與 direct-mode owner-state read-back。此具體 provenance identity 根因為
**`root_cause_fixed_and_verified`**；formal caller、live migrations、Git ownership
cutover 與 rollback rehearsal仍未完成，因此 Change Delivery 整體維持
**`contained`**。

### 2026-07-24 — Formal caller 沒有 durable Git owner generation

**症狀與根因層級**：ChangeSet store、commit authority、Git actuator 與 settlement
各自存在，但沒有一個 formal Work Coordinator caller 串接全部 durable adapters；
Git commit 權限也沒有可 CAS、可回讀、可 rollback 的 owner generation。若只在 Python
先讀「目前 owner」，owner 可能在 authorize 前改變；既有無 owner 參數 RPC 仍可繞過
新檢查。這是 ownership／transaction boundary 根因，不是補一個 caller wrapper 可解。

**底層修復**：新增 private `commit_owners`／append-only owner receipts 與
approver-only CAS transfer。`OwnedChangeDelivery` 只接受 current
`operations_core` generation，並把 generation 綁入 landing command SHA、authority
request／grant、Git actuation、ChangeSet checkpoint、settlement SHA 與 final receipt。
Authorize／settle functions 在 transaction 內鎖定並重驗 owner；舊無 owner overload
對 worker失權。Settlement 落 immutable receipt 後在同一 transaction 呼叫
`complete_work()`，formal caller 再回讀唯一 terminal WorkItem。Rollback 在有未
settlement grant 或 `commit_unsettled` ChangeSet 時 fail closed。

**回歸、回讀與狀態界線**：PostgreSQL 17 以 non-superuser migration executor 從乾淨
schema replay，回讀 FORCE RLS、PUBLIC deny、worker／approver 分權、function owner
與 fixed search path。臨時 canonical repo + registered linked worktree 的 non-live
E2E 實際完成 owner generation 2 commit，核對 durable ChangeSet／grant／receipt／
WorkItem 後，演練 generation 3 rollback、同 request 冪等 replay、stale CAS refusal
及 generation 4 re-cutover；另有未 settlement grant 專例證明 rollback 被阻擋。
這個 formal caller／ownership 根因在 shadow 為
**`root_cause_fixed_and_verified`**。Production Git owner 未切換，Change Delivery
umbrella 仍是 **`contained`**，不可宣稱正式 cutover 完成。

### 2026-07-24 — Change Delivery live schema deployment 暴露 receipt FK 無 covering index

**部署與觀察**：在 PG17 non-superuser replay、119 個 Change／Git／PostgreSQL scoped
tests 與 canonical writer audit 通過後，依序以 migration API 套用 commit authority、
settlement、owner generation 與 ChangeSet store。Owner 初始化後 live 回讀仍為
`git.commit=legacy/1`，grant／delivery receipt／ChangeSet 都是 0，沒有執行 owner
transfer。五張新表全部 FORCE RLS、PUBLIC 無 SELECT；新 functions 都由
`volpred_ops_definer` 持有、固定 `search_path`，worker 對舊無 owner overload 失權。

**Advisor 缺口與底層修復**：第一次 live performance advisor 指出
`change_sets_delivery_authority_request_sha256_fkey` 沒有 referencing-side index。
新增 forward-only `change_sets_delivery_authority_request_idx`，只索引非空 immutable
delivery authority request；PG17 migration contract 直接回讀 index shape，避免只在
文件宣稱。Production migration receipt 為
`20260724072403 operations_core_change_set_receipt_index`，部署後同一 advisor finding
消失；`volpred_ops` security advisor 為 0 findings。

**驗證與狀態界線**：兩個 owner／ChangeSet PostgreSQL cases通過；完整 pytest 的
4,911 tests 本體全通過、1 skipped，但 session-level CI-parity plugin 因 canonical
checkout 內既有未追蹤 worktree/runtime files 將 exit 改為 1，因此不可記成 full-suite
green。此 FK advisor 根因為 **`root_cause_fixed_and_verified`**；schema deployment
已完成，但 production owner 仍是 legacy，正式 CAS、live commit smoke 與 rollback
rehearsal尚未執行，所以 Change Delivery 整體維持 **`contained`**。

### 2026-07-24 — Production commit owner 只有 private PG adapter，管理面無正式 read/CAS seam

**證據化症狀與根因層級**：Change Delivery private migrations 已部署，但 Supabase
Management SQL 直接呼叫 `volpred_ops.read_commit_owner()` 收到
`permission denied for function read_commit_owner`；catalog 雖顯示 session user
`postgres` 對 worker／approver 有 membership，卻沒有直接 function privilege，也
不能 `SET ROLE`。拒絕本身符合 least privilege，但 production 只有
`PostgresCommitOwnerStore`，沒有 service-role／PostgREST adapter；若用 privileged
SQL 或暫時 grant 繞過，就會把正式 ownership transaction 退化成 session workaround。
這是 remote-owned adapter 與 operator interface 缺口，不是 owner row 資料錯誤。

**底層重構**：forward migration 新增
`public.volpred_read_commit_owner()`／`volpred_transfer_commit_owner()`，只委派既有
private read／CAS functions，因此未複製 ownership state machine；unsettled grant、
`commit_unsettled` ChangeSet、generation 與 rollback-of-generation fences 全保留。
Functions 由 no-login `volpred_ops_definer` 持有、`SECURITY DEFINER` 且
`search_path=''`，只授權 service role；anon／authenticated／PUBLIC 無 EXECUTE，
service role 仍無 private table SELECT。`SupabaseCommitOwnerStore` 將 production
HTTP transport 藏在同一 owner-store seam 後，嚴格驗證 schema、capability、owner、
positive generation 與 timezone-aware timestamp，CAS 衝突轉成 typed
`CommitOwnershipLost`，也禁止 publishable／anon key fallback。

**回歸、live 回讀與制度化**：unit interface、PG17 non-superuser clean replay、
service-role `legacy/1 → operations_core/2 → legacy/3` transaction、ACL 與 direct-table
denial regressions均通過。Production migration receipt 是
`20260724074117 operations_core_commit_ownership_rpc`；live service-role HTTP 回讀
仍為 `git.commit=legacy/1`，catalog 八項 hardening／ACL predicates 全 true，兩類
advisor 對新 RPC 均為 0 findings。本次沒有執行 owner transfer。這個 operator seam
根因為 **`root_cause_fixed_and_verified`**；但完整 production Change Delivery
adapters、正式 live commit smoke 與 rollback rehearsal仍未完成，umbrella 保持
**`contained`**。

### 2026-07-24 — ChangeSet durable lifecycle 只有直連 PostgreSQL adapter

**證據化症狀與根因層級**：commit owner 已有 service-role PostgREST seam，但 formal
caller 的 ChangeSet proposal／checkpoint／landed state 仍只能透過
`PostgresChangeSetStore`。Production runtime 若沒有 direct database connection，
無法使用已部署的 durable lifecycle；若讓 service role 直接讀 private view 或在
caller 重組 SQL state machine，會破壞 RLS 與單一 transaction owner。這是 remote
persistence adapter 缺口，不是 owner row 或 ChangeSet 資料錯誤。

**底層重構**：新增五個 service-role-only public RPC，逐一委派 private create、
by-id／by-idempotency read、actuation checkpoint 與 landed linkage；回傳只來自既有
token-redacted `change_set_reads`。`SupabaseChangeSetStore` 實作同一 store protocol，
共用 owner adapter 的 narrow HTTP transport，將 JSON 轉回 canonical
`ChangeSetRecord`，並保留 typed conflict／validation errors、timezone-aware timestamp
gate 與 delivery exact-match read-back。Environment builder 只接受 service-role key，
不會退回 publishable／anon key。

**回歸、回讀與狀態界線**：HTTP interface cases 通過 create、missing lookup、typed
conflict 與 credential fail-closed；PG17 non-superuser 從 clean schema replay全部
migrations，再重播本 migration 驗證 idempotence，並以 service role 實際 create、
by-id／by-idempotency read。Catalog 回讀五個 functions 都是 no-login definer owner、
`SECURITY DEFINER`、空 search path；anon／authenticated／PUBLIC 無 EXECUTE，
service role 無 private table／view SELECT。Production migration receipt 是
`20260724081714 operations_core_change_set_rpc`；live catalog 七項 hardening／ACL
predicates 全 true，正式 HTTP adapter 的 missing idempotency lookup 精確回傳 null，
owner 仍為 `legacy/1`、ChangeSet count 仍為 0，沒有執行 transfer 或建立 proposal。
此 ChangeSet remote persistence seam 達
**`root_cause_fixed_and_verified`**；commit authority／settlement／Work read model
的 HTTP adapters、live ownership CAS、commit smoke 與 rollback rehearsal仍缺，
所以 Change Delivery umbrella 維持 **`contained`**。

### 2026-07-24 — Commit authority 只有直連 PostgreSQL adapter，production caller 無法跨 HTTP fence Git write

**證據化症狀**：ChangeSet 與 commit owner 已有 service-role adapters，但 formal
caller 的 `CommitAuthority.authorize()` 仍只接受 `PostgresCommitAuthority`。Production
runtime 若沒有 direct database connection，就無法在 Git writer 前同時回讀 WorkLease、
Primary Authority 與 owner generation；若在 caller 自行拼 PostgREST table reads 或
重寫判斷，會讓 database-clock transaction 不再是唯一授權 owner。

**根因層級**：這是 remote-but-owned authority adapter 與 PostgREST interface 缺口，
不是 live owner row、grant 資料或 Git writer 錯誤。ChangeSet store 可遠端持久化並不
代表 commit 已獲授權；缺這一層仍不得切換 owner。

**底層重構**：新增 `SupabaseCommitAuthority`，維持既有
`CommitAuthority.authorize()` seam。Adapter 在送網路前重算包含 proposal、WorkItem、
owner generation、兩個 fencing token、repo／HEAD、paths／hashes、message 與 actor
的 canonical SHA-256；public RPC 只委派既有 private owner-fenced
`authorize_commit_write` transaction，不複製 policy。回傳僅含 token-redacted grant，
不保存 raw token。Environment builder 只接受 service-role key，不會退回
publishable／anon key。

**回歸與 live 回讀**：unit transport cases涵蓋 exact payload、pre-network digest
rejection、typed ownership failure、untrusted JSON boolean generation 與 credential
fail-closed。PG17 non-superuser 從 clean schema replay全部 migrations並二次 replay
本 migration，實際以 service role authorize／等價 replay，同時確認 private grant
table denial。PostgreSQL delivery 39 tests與 Change Delivery／Git writer／Supabase
adapter 相鄰 96 tests 均通過。Production migration receipt 是
`20260724085535 operations_core_commit_authority_rpc`；catalog 回讀 function owner、
security-definer、空 search path、service-role-only execute、private table／view
deny與 definer 無 public CREATE 共八項全 true，security／performance advisors 無
指向新 RPC 的 finding。正式 HTTP adapter 在 live `legacy/1` 下精確回傳 typed
`CommitActuatorBlocked`；smoke 前後 grant／delivery receipt／ChangeSet 皆為 0，
沒有執行 owner transfer 或 Git write。

**制度化與狀態界線**：migration、PG17 ACL/read-back contract、HTTP interface tests、
architecture、operations-core module design 與 improvement status 已同步，使這個
adapter 不可在沒有 digest／ACL／live zero-write 證據時靜默上線。此 production
commit-authority adapter seam 為 **`root_cause_fixed_and_verified`**；但 settlement
與 Work read model 的 HTTP adapters、live ownership CAS、commit smoke 及 rollback
rehearsal仍缺，Change Delivery umbrella 維持 **`contained`**。

### 2026-07-24 — Commit settlement 只有直連 PostgreSQL adapter，remote caller 無法 durable acknowledge Git write

**證據化症狀與根因層級**：commit owner、ChangeSet 與 commit authority 已有
service-role adapters，但 `CommitSettlementStore.settle()` 仍只接受
`PostgresCommitSettlement`。沒有 direct database connection 的 production runtime
即使取得 Git read-back，也無法重驗 WorkLease／Primary Authority／owner generation
並原子保存 receipt、完成 WorkItem。若 caller 自行串 table reads／writes，就會讓
private transaction 不再是唯一 settlement owner。這是 remote-but-owned adapter 與
PostgREST interface 缺口，不是 live receipt 資料錯誤。

**底層重構**：新增 `SupabaseCommitSettlement`，維持既有單一 `settle()` interface。
Adapter 先重算 exact actuation 的 settlement SHA-256，再把兩個 raw fencing token
交給 narrow service-role RPC；public wrapper 只委派既有 owner-fenced
`settle_commit_write` transaction，不複製任何 lifecycle policy。回傳只含
token-redacted durable receipt；adapter 逐欄核對 proposal、WorkItem/version、owner
generation/ref、authority refs、repo、commit/parent、paths、actor、timestamps、
status、settlement ref 與 digest。Malformed JSON、boolean version、timestamp 或
read-back drift 都轉成 typed `CommitSettlementBlocked`。Environment builder 只接受
service-role key。

**回歸與 live 回讀**：HTTP interface cases涵蓋 exact payload、untrusted receipt、
typed fencing failure、credential 與 command-type fail-closed。PG17 non-superuser
從 clean schema replay全部 migrations並二次 replay本 migration，實際以 service role
settle並確認 private receipt table denial。Change Delivery／Git writer／Supabase
adapter 相鄰 100 tests及 PostgreSQL delivery 40 tests 通過。Production migration
receipt 是 `20260724092237 operations_core_commit_settlement_rpc`；catalog 回讀
function owner、security-definer、空 search path、service-role-only execute、private
table／view deny與 definer 無 public CREATE 全 true，security／performance advisors
無指向新 RPC 的 finding。正式 HTTP adapter 在 live `legacy/1` 下精確回傳 typed
`CommitSettlementBlocked`；probe 前後 grant／delivery receipt／ChangeSet 皆為 0，
沒有 owner transfer、Git write或 Work completion。

**制度化與狀態界線**：migration、PG17 ACL/read-back contract、HTTP interface tests、
architecture、operations-core module design 與 improvement status 已同步。此
production commit-settlement adapter seam 為
**`root_cause_fixed_and_verified`**；但 Work read model HTTP adapter、完整 remote
caller composition、live ownership CAS、commit smoke 與 rollback rehearsal仍缺，
Change Delivery umbrella 維持 **`contained`**。

### 2026-07-24 — Formal remote Change Delivery 無法回讀 terminal WorkItem

**證據化症狀與根因層級**：commit owner、ChangeSet、commit authority 與 settlement
都有 service-role adapters 後，`OwnedChangeDelivery.deliver()` 的最後一步仍只能靠
direct PostgreSQL `WorkCoordinator.inspect()` 回讀 settlement transaction 產生的
terminal WorkItem。Production runtime 無 direct database connection 時，無法用同一
formal caller 證明 WorkItem 已成 `succeeded`、version 已遞增、result ref 等於
settlement ref 且 claim 已清除。這是 Work read-model／remote composition interface
缺口，不是補一筆 receipt JSON 或讓 service role 直接 SELECT private tables可解。

**底層重構**：新增 exact-id `volpred_read_work_snapshot`，一次從 private FORCE-RLS
sources 讀回 item、events、verified checkpoints 與 receipts；public wrapper 由
`volpred_ops_definer` 持有、固定空 search path，只有 service role 可執行，且不授予
四個 private sources 的 SELECT。`SupabaseWorkReadModel` 驗證 schema、lifecycle、
positive versions、timezone-aware timestamps、checkpoint SHA-256 與 nested WorkItem
identity。`build_supabase_owned_change_delivery()` 將 owner、ChangeSet、authority、
Git actuator、settlement 與 read model 接成完整 formal caller，owner check 仍在任何
proposal 或 Git write 之前。

**回歸、live 回讀與制度化**：public-interface TDD、PG17 non-superuser clean migration、
二次 replay、實際 service-role bounded read、anon／authenticated／PUBLIC denial、
private table denial與相鄰 114 tests 通過。Production migration receipt 是
`20260724101005 operations_core_work_read_model_rpc`；catalog hardening predicates
全 true，security／performance advisors 對新 RPC 都是 0 findings。Live HTTP adapter
對一筆 `succeeded/v4` WorkItem 回傳 items=1、events=4、receipts=1，missing id 回傳
空 snapshot；probe 前後 WorkItem count=19、ChangeSet／commit grant／commit receipt
均為 0，owner 保持 `legacy/1`。此 remote read/composition seam 為
**`root_cause_fixed_and_verified`**；尚未執行 production owner CAS、真實 commit、
exact Git read-back與 rollback rehearsal，因此 Change Delivery umbrella 仍是
**`contained`**。

### 2026-07-24 — Primary Authority 只有直連 PostgreSQL adapter，remote caller 無法持有同一 DB-clock lease

**證據化症狀與根因層級**：production Change Delivery 已能用 service-role HTTP
組合 owner、ChangeSet、commit authority、settlement 與 Work read model，但
`PrimaryAuthority` 本身仍只有 `PostgresAuthorityStore`。沒有 direct database
connection 的 runtime 只能由 caller 手造 `PrimaryLease` 或旁路 private tables，
使 acquire／renew／authorize／release 不再由同一 database-clock transaction owner
控制。這是 remote-owned adapter 與 operator interface 缺口，不是 live lease 資料錯誤。

**底層重構**：新增 `SupabaseAuthorityStore` 與四個 service-role-only public RPC，
全部只委派既有 private Primary Authority functions，不複製 lease state machine。
Raw fencing token 只作 database revalidation，public response、grant 與 receipt 都
不含 token。Adapter 逐欄驗證 authority key、holder、positive epoch、resource、
timezone-aware timestamp 與 lease window，untrusted JSON drift fail closed；
environment builder 只接受 service-role key。Functions 由 no-login
`volpred_ops_definer` 持有、固定空 search path，anon／authenticated／PUBLIC 無
EXECUTE，service role 對 private authority tables 仍無 SELECT。

**回歸、live 回讀與制度化**：HTTP interface、PG17 non-superuser clean migration、
二次 replay、實際 service-role acquire→authorize→renew→release、ACL 與 private-table
denial contracts 通過。Production migration receipt 是
`20260724101355 operations_core_primary_authority_rpc`；live smoke 的 resource 固定為
`smoke:no-external-effect`，沒有 Git／effect side effect。下游 canonical read-back
確認 release 後 holder 與 token digest 都為 null，且 exact epoch 各保存 1 筆 immutable
grant／receipt；兩類 advisor 無新 RPC finding。Migration、adapter、PG17／HTTP tests
與四份 canonical architecture status 已同步，使 remote runtime 不必再手造 lease。
此 remote Primary Authority seam 為 **`root_cause_fixed_and_verified`**；但 Git owner
CAS、live commit、rollback rehearsal與 program commit 34 host
acquire／renew／demote workflow都尚未執行，umbrella 仍為 **`contained`**。

### 2026-07-24 — Remote lease primitive 存在，但 host 沒有 fail-closed session lifecycle

**證據化症狀與根因層級**：`PrimaryAuthority` 與 Supabase RPC 已能個別
acquire／renew／release，但 runtime caller 仍須自行保存 raw lease、判斷本機是否
active，以及處理 renew／release 的 network failure。若 caller 在 renew 失敗後仍沿用
記憶體中的舊 lease，本機會繼續自認 primary；雖然正式 PostgreSQL write 最終仍會被
database fencing 擋下，host scheduling／enable state 卻沒有單一 fail-closed owner。
這是 host workflow／local authority state seam 缺口，不是 lease table 或 RPC policy
錯誤。

**底層重構**：新增 `HostAuthoritySession`，在 process lock 內持有唯一 active lease。
等價 activate 重入只回同一 lease；token-redacted status 不洩漏 fencing token。
Renew 會核對 authority／holder／epoch／token、acquired timestamp 與 lease window；
control plane unavailable、stale identity、malformed read-back 或 local expiry都會先
清掉 raw lease並 demote，再回 typed `AuthorityInactive`。Explicit demote 也在 remote
release 前先停用本機 authority；即使 response 遺失，本機不能再取出 stale token，
remote holder 只會保留到 database-clock expiry。

**回歸與狀態界線**：共享 authority store 的雙 host injection 證明 primary active 時
standby acquire 被拒，release 後 standby 只取得下一個 epoch，舊 session 不可再取 lease。
Renew unavailable、release unavailable與 local expiry 三個 failure cases全部 fail
closed；連同 Supabase HTTP 與 PG17 RPC contracts 共 12 passed，compileall 通過。
Architecture、operations-core design 與 improvement status 已同步。這個 host session
局部根因為 **`root_cause_fixed_and_verified`**；canonical keepalive、全 effect-family
enable gate、真實雙 Mac network partition 與五分鐘 RTO rehearsal仍缺，所以 program
commit 34 整體維持 **`contained`**。

### 2026-07-24 — Host session 可手動 renew，但沒有 canonical keepalive owner

**證據化症狀與根因層級**：`HostAuthoritySession` 已能 fail closed，但週期性 renew
仍由未定義的 runtime caller負責。Caller 忘記排 renew、renew thread 無聲退出，或 stop
卡在 remote call 時，session 在 local expiry 前仍可能被其他 host component誤當 active；
正式 PostgreSQL write雖會逐次 fencing，host enable state卻沒有單一 liveness owner。
這是 host keepalive／enable-gate workflow 缺口，不是 lease row 或 fencing policy錯誤。

**底層重構**：新增 `HostAuthorityKeepalive`，以單一 daemon thread擁有 activate、
periodic renew、stop與demote；production builder直接組合 service-role
`SupabaseAuthorityStore`。Effect／commit caller只能經 keepalive `current_lease()`；
renew failure、unexpected `BaseException`、dead worker、session drift、release failure
或 join timeout一律先把 state 設為 `demoted`／`stopping`，再做可能阻塞的 cleanup。
因此 control plane 卡住時本機 gate 已關閉，remote raw lease最晚由 database clock
expiry fence。Status只回 token-redacted authority、renew count、expiry、worker
liveness與 failure type；renew interval若不短於 lease，在剛 acquire 後立即 demote
並 release，不能帶著無 renewal margin 的 authority啟動。

**回歸、live 回讀與制度化**：unit／concurrency cases覆蓋 successful renew、clean
release、renew failure、thread `BaseException`、release response lost、blocked-renew
stop timeout、invalid margin、environment composition與 token redaction；連同既有
session／Supabase authority adapters為 22 passed，compileall通過。Production
no-effect rehearsal使用唯一 authority key
`operations-core-keepalive-smoke-2a249b5a100e4352a76c848f5ca394c1`：A host
acquire後由 keepalive實際 renew 1 次並 release，B host隨即以同 key acquire；
epoch精確 `1 → 2`，兩個 durable release refs均回讀且 final state都是 `stopped`。
Architecture、module design、improvement status與 public package exports已同步。這個
canonical keepalive owner 根因為 **`root_cause_fixed_and_verified`**；全
effect-family enable gate、真實雙 Mac network partition、Supabase outage與五分鐘
RTO rehearsal仍缺，因此 program commit 34 整體維持 **`contained`**。

### 2026-07-24 — Keepalive acquire 未納入本機 transition，並行 start／stop 可破壞單一 owner gate

**證據化症狀與根因層級**：`HostAuthorityKeepalive.start()` 原先只在進入時用
`self._lock` 檢查 `standby`，隨即放鎖執行 `HostAuthoritySession.activate()`，最後才
重新取鎖 publish worker 與 `running`。可重現的 barrier injection 證明兩個 starter
會同時跨入 activate 並各建 renew thread；stop 也可在第一個 acquire 尚未返回時把
`standby` 標成 `stopped` 並先返回，之後 starter 仍會 publish `running`。資料庫 fencing
仍會保護正式 write，但本機「單一 renew owner／stop 後 gate 不可重開」契約已被破壞。
根因是 start transition 的 process-lock 範圍不完整，不是 Supabase lease row 或 DB-clock
政策錯誤。

**底層重構**：Remote acquire、renew worker 建立與 `running` publication 現在共用同一個
keepalive `RLock` critical section。第二個 starter 會在 transition 完成後直接回讀同一
lease，不會呼叫第二次 activate或建立第二個 worker；並行 stop 必須等 start 落定，再從
`running → stopping → stopped` 關 gate。Acquire 阻塞期間 gate仍是 `standby`，
`current_lease()` 無法取出 raw token，所以等待 lock 不會擴大 effect／commit 權限。

**回歸、回讀與狀態界線**：新增兩個 deterministic barrier cases，修正前分別實際觀察到
第二次 activate 與 stop 提前完成，修正後均通過；keepalive／session／Supabase authority
相鄰套件共 **24 passed**。Architecture、operations-core module design與 improvement
status 已同步，這個 startup 原子性缺口為
**`root_cause_fixed_and_verified`**。全 effect-family enable gate、真實雙 Mac
network partition、Supabase outage與五分鐘 RTO rehearsal仍未執行，所以 program
commit 34 umbrella 保持 **`contained`**。

### 2026-07-24 — Effect worker command 可繞過 host keepalive 傳入 stale raw lease

**證據化症狀與根因層級**：`HostAuthorityKeepalive` 雖已是 canonical renew owner，
但 `EffectWorkerCommand` 仍公開 authority key、holder、epoch 與 raw fencing token。
任意 caller 可保存舊 command，在 keepalive demote 後仍先 claim outbox；只有較後面的
database authorization 可能攔住。這使本機 enable gate 不是必經 seam，且每個
provider caller 都要自行知道完整 lease identity。根因是 Effect Delivery worker
interface 暴露了應由 keepalive implementation 擁有的 authority state，不是 outbox
或 provider 資料錯誤。

**底層重構**：`EffectOutboxWorker` 改依賴內部 lease-gate seam，command 只保留
worker id 與 outbox lease duration。Worker 在 claim 前、authorize 前與 provider 前
各回讀 `current_lease()`；authority key 必須是 `operations-core-effects`，同一 attempt
的 holder／epoch／token／acquired identity不可漂移。Renew 可更新 expiry，不會被誤判
成換主。Closed gate、wrong family 或 replacement lease 都轉成 typed
`EffectWorkerBlocked`，provider 呼叫為 0；raw fencing token不再出現在 caller command。

**回歸、回讀與制度化**：Email notification 與 publisher article sync 兩個現有
provider family 都經相同 worker interface 驗證；failure injection 覆蓋 claim 前
demote、claim 後 demote、grant 後 demote、wrong family、lease replacement與正常
renew。Authority／Effect Delivery／PG17 相鄰套件共 **88 passed**，compileall與
`git diff --check` 通過；acknowledgement與 durable settlement receipt仍由原 external
interface逐欄回讀。Architecture、operations-core module design與 improvement status
已同步。這個 generic worker seam 為 **`root_cause_fixed_and_verified`**；production
`email.ops_alert` 的 ownership RPC仍自行 acquire family-specific lease，尚未改成
revalidate host keepalive lease，所以全 effect-family enable gate與 program commit 34
umbrella 維持 **`contained`**。

### 2026-07-24 — Effect worker 的 provider keepalive gate 早於 durable payload read

**證據化症狀與根因層級**：既有文件宣稱 worker 在 provider 前重驗 keepalive，但
`EffectOutboxWorker.run_once()` 的第三次回讀實際位於
`EffectPayloadReader.read()` 之前。Public-interface RED injection 讓 reader 在回傳
正確 payload bytes 後關閉 gate；舊實作沒有拋出 `EffectWorkerBlocked`，而是完成 email
provider call。根因是 lease revalidation 放在可能阻塞的 payload boundary 前，不是
payload hash、provider adapter或 PostgreSQL fencing資料錯誤。

**底層重構**：Worker 保留 claim前、authorize前與 grant後的既有 gate，並在 payload
bytes 通過 EffectRequest SHA-256 後、呼叫 `EffectProvider.deliver()` 的前一刻再次
回讀同一 holder／epoch／token／acquired identity。Payload read期間發生 demotion或
lease replacement現在會 fail closed；provider與 settlement都不執行，避免失去主控
租約的 host產生正式外部寫入。

**回歸、回讀與制度化**：新 regression 修正前實際得到「DID NOT RAISE」，修正後轉
GREEN，並回讀 payload ref已讀、provider calls=0、settlement outcomes=0。Email、
publisher與PostgreSQL相鄰套件共 **68 passed**；architecture、operations-core module
design與 improvement status同步保存這個真正的 provider boundary。此局部 race為
**`root_cause_fixed_and_verified`**；本切片沒有 live effect或 owner mutation，
其餘 family cutover與真實 outage／RTO rehearsal仍缺，因此 program commit 34 umbrella
維持 **`contained`**。

### 2026-07-24 — Publisher settlement response 遺失後重播會重新 begin terminal WorkItem

**證據化症狀與根因層級**：formal caller 的 request idempotency雖會回到同一
WorkItem／EffectRequest，但成功 settlement後若 caller遺失 HTTP response，再送同一
request只得到 work/effect identity，接著呼叫 begin；既有 WorkItem已是
`succeeded`，因此 begin拒絕。這不會重複寫 provider，卻使「外部寫已成功」無法從
durable state收斂回 receipt。根因是 request／settlement transaction boundary缺少
terminal receipt recovery，不是再加 client retry或手補資料可解。

**底層重構**：新增 forward-only migration，在相同 idempotency request已存在時讀取
最新 `delivered`／`dead_lettered` attempt並組回
`owned-publisher-article-receipt.v1`；新 request明確回 `receipt=null`。
`SupabaseOwnedPublisherArticleStore`解析 typed terminal receipt，
`OwnedPublisherArticleSync.sync()`在驗證 owner generation、Work／Effect identity與
terminal disposition後直接返回，begin／provider／settlement全部不再執行。現有
17:00 ownership migration原件未改寫，production只套用新的 forward migration。

**回歸、production回讀與狀態界線**：PG17完整
cutover→delivery→lost-response replay→rollback案例通過，重播 receipt逐欄等於原
settlement且 attempt count維持 1；caller／adapter 22 cases與完整 PostgreSQL 45 cases
通過。Production migration receipt為
`20260724152359 operations_core_publisher_article_terminal_replay`；catalog回讀
SECURITY DEFINER、空 search path、service-role-only EXECUTE、private table FORCE
RLS／direct SELECT denial與 function rewrite markers全正確，publisher scope仍是
`legacy/1`、0 request、0 active attempt、0 lease。此 terminal-replay seam為
**`root_cause_fixed_and_verified`**。

---

## 2026-07-30 — GitHub Test Suite 被 CJK font mirror stall 吃完整個 job timeout

**證據化症狀**：GitHub Actions run `30490697153` 在 21:03:40Z 開始從
`azure.archive.ubuntu.com` 下載 61.2MB `fonts-noto-cjk`，直到 21:21:09Z 仍未完成，
最後被 20 分鐘 job timeout cancel；`uv`、Python 與 pytest 都尚未開始。前一個正式
run `30486814276` 全綠，故這不是 test failure，也不能拿 cancelled run 當新 commits
的驗收證據。

**根因層級（CI dependency execution contract）**：workflow 以一條 raw
`sudo apt-get update && apt-get install` 同時承擔 package index、runtime ripgrep 與
61.2MB CJK font，沒有 connect/read timeout、沒有 outer process-group deadline，也
沒有有限 retry；唯一界線是整個 pytest job 的 20 分鐘上限。單一 mirror stall 因而
可在測試前耗盡所有驗證預算。

**底層修復與制度化**：workflow 改委派可測的
`ci_install_system_test_dependencies.py`。真實 `ripgrep` 與 `fonts-noto-cjk` 仍為
必要 package，不以 skip、假 font 或降級測試繞過；bounded supervisor 本身由 workflow
以 root 啟動，apt／dpkg 不再透過另一層 sudo，確保 TERM／SIGKILL 與 descendants
同權限；非 root 直接執行會 fail loud。apt connect/read/lock 均 20 秒，
update 每次 30 秒、install 每次 120 秒，各最多兩次。每次 command 在獨立 process
group，outer timeout 先 TERM、5 秒後 KILL，避免只殺 `sudo` 留下 apt 子程序；attempt
間保留 apt partial cache。cleanup 不信任已退出的 `sudo` leader，而是有界輪詢整個
process group；SIGKILL 後亦不使用無 timeout 的 wait。TERM／KILL grace 全計入後，
最壞 dependency budget 346 秒，job 上限改為 30 分鐘，既容納 retry，也不允許
mirror 或 reap 無限卡住。若 SIGKILL 後 group 仍未消失則回專用 rc125 並立即
fail closed，不啟動下一個會與殘存 apt／dpkg 競爭 lock 的 attempt。

**回歸與 read-back**：deterministic RED 先證明 workflow 仍含 unbounded raw apt；
修正後 bounded workflow／retry／fail-closed／真 dependency／surviving-descendant
contract 11 tests，連同 checkout-history、Postgres workflow 與 enforcement-map 共
**22 passed**；Ruff、py_compile、YAML consumer 與 diff check 通過；Matt
Standards／Spec 最終複審均 PASS。後續 full-suite gate 又正確抓出 bounded helper
本身仍以 raw `os.killpg` 送 TERM／KILL，違反「所有 system-owned termination 先有
durable intent」的全域契約。commit `ca41186c4` 把 helper 收斂到 canonical
stdlib-only termination owner；sudo Python 在專案環境尚未安裝時直接載入唯一 owner
檔案，runner-local ledger 先持久化 intent／attempt receipt再送 signal，receipt
無法建立或寫入時 fail closed，不會退化成 raw kill。TERM／KILL沿用同一 generation，
相鄰 termination／dependency tests **36 passed**，Matt Standards／Spec 雙審 PASS。
GitHub successor run `30500807966` 的 dependency step成功，完整 suite
**6645 passed、11 skipped**，其餘四道 gates亦全綠。此 bounded root class現為
**`root_cause_fixed_and_verified`**。

### 2026-07-27 — runtime task `succeeded` 誤關仍為 contained 的 GitHub umbrella issue

**證據化症狀**：Issue #18 closure-audit slice 的 result 明寫
`Issue #18維持contained/OPEN`，但 `task_pool_claim.py complete --status succeeded`
仍無條件產生 `issue_close_pending`；exact-path commit `72beed8fa` 隨即由 settlement
關閉整張 #18，必須人工reopen。Task outcome與issue disposition被混成同一狀態，
使五步Gate只存在於文字規範，控制面反而能機械違反它。

**根因與底層修復**：新增正交的`issue_disposition` lifecycle。Linked task成功預設
`contained`並保持issue OPEN；只有整張issue acceptance與五步Gate全過後明確傳
`--issue-disposition close`，才產生commit-bound close receipt。Disposition加入
annotate protected fields；explicit close遇invalid issue或讀不到HEAD時，在任何
terminal mutation前fail closed。Settlement candidate與ack CAS都exact-match
disposition、task id、canonical issue ref、completion timestamp與完整pending receipt；
legacy、ambiguous或漂移receipt不呼叫GitHub。

**回歸與live read-back**：tight RED先重現default completion產生close receipt及
settlement呼叫closer；最終task-pool／issue-sync／writer-lock／supervisor測試
**315 passed**，Matt Spec／Standards雙軸PASS。Live task `assign_e474aaf2`以預設
contained完成後，commit `6036b7c6a`回讀#47仍OPEN、marker=0、無close receipt；
只有closure task `assign_abe5bb43`明確close，commit `9677d28bb`後GitHub才CLOSED，
comment marker與`issue_closed_commit` exact match。Issue #47狀態為
**`root_cause_fixed_and_verified`**。

Python owner router與 active frontend owner fence已實作，後者在獨立 repo commit
`ae14890`；但 frontend尚未 push／deploy。若現在切 production owner，舊 live
`/api/sync`仍可能保留競爭 writer，因此 publisher整體只能標 **`contained`**。下一個
不可跳過的 gate是部署 frontend、回讀 live version／owner-fence，再做唯一 owner
article acknowledgement與rollback rehearsal；本輪未執行 owner transfer或文章寫入。

### 2026-07-25 — Publisher formal caller 未驗 settlement 與 terminal replay lifecycle

**證據化症狀與根因層級**：兩個 public-interface injection分別讓 settlement receipt
指向另一個 Effect，以及讓 `disposition=delivered` 搭配
`work_status=failed/effect_status=dead_lettered`。修正前兩案都得到
`DID NOT RAISE`：provider完成 downstream read-back後，formal caller直接信任
service-role response；terminal replay也只核對 identity與 disposition集合，沒有核對
lifecycle tuple。根因是 transaction response boundary缺少 caller-side read-back
contract，不是 PostgreSQL durable row或 provider projection錯誤。

**底層重構**：`OwnedPublisherArticleSync`現在逐欄核對 receipt schema、owner
generation、Work／Effect／attempt、Primary Authority ref、provider evidence與三組合法
lifecycle tuple。Acknowledged outcome只接受 delivered；non-retryable failure只接受
dead-lettered；retryable failure只接受 retry-scheduled或已耗盡重試的dead-lettered。
Terminal replay共用 lifecycle驗證。任何漂移在回到 publisher上游前轉成
`PublisherArticleSyncOwnershipLost`，不會把另一個 transaction或矛盾 terminal state
誤報成功。

**回歸、下游回讀與制度化**：兩個 RED injections均轉 GREEN；publisher formal caller、
effect adapter與 PG17 delivery contracts共 **69 passed**，compileall與
`git diff --check`通過。擴大到含 Supabase hash suite時，83個 test assertions全過，但
既有 CI-parity ratchet另擋兩個測試讀未追蹤 `.env.local`，未把該聚合命令誤報為成功。
Architecture、operations-core design與 improvement status已同步；本切片無 remote
write、owner transfer或 frontend deploy。這個 response-boundary根因為
**`root_cause_fixed_and_verified`**；program commit 14仍因 frontend live fence、
唯一 owner acknowledgement與rollback rehearsal未完成而維持 **`contained`**。

### 2026-07-25 — Publisher owner fence 已部署，但人工 rehearsal 在 CAS 後才驗 input／猜 receipt 欄位

**證據化症狀**：active frontend `ae14890` 從 clean detached worktree部署成功，
Zeabur deployment `6a6393ea4727f1da77de7137` 為 `RUNNING`，live API通過。第一次
generation 2 cutover後，兩條 live fence已分別回 409／delegated，但 operator script
才發現從 feed選到的 `mile_30b22ca5` 沒有 single-report檔。第二次 generation 4 已完成
canonical article delivery並取回 typed terminal receipt，呈現證據時卻讀取不存在的
`work_item_id`欄位。兩案都由 `finally` 自動 CAS rollback，owner依序回到
`legacy/3`與`legacy/5`；第一案未建立 request／attempt，第二案只對同一 canonical
article做已確認的冪等 projection。

**根因層級與底層重構**：缺口在 operator transaction seam：本地 immutable input
preflight與 typed receipt呈現沒有收進 cutover interface，而不是 frontend、RPC或
Supabase article資料錯誤。新增 `scripts/rehearse_publisher_cutover.py`，在任何 remote
mutation前驗 article檔存在、slug path-safe、id一致且 status為 published；idempotency
key綁 deployment、cutover generation與 slug。Live probe先以空 full-feed證明 409，
再以完整 canonical article驗 single-report delegated，避免 branch drift時寫入殘缺
dummy row。Receipt只接受 typed `OwnedPublisherArticleReceipt`、同 generation、
attempt 1與合法 delivered lifecycle，輸出直接 `dataclasses.asdict()`，不再手抄欄位。
任何 cutover後例外均從 live owner read-back取得目前 generation做 exact rollback。

**回歸、production回讀與制度化**：四個新 cases覆蓋 mutation前缺檔、成功 ack／rollback、
live fence failure automatic rollback與 receipt generation drift。正式 generation 6
rehearsal回讀 full-feed 409、single-report delegated；article
`crisis_protection_20260316_002220` receipt為
`work_owned_publisher_110068f9062bfe12d5a501935f1a631c`／
`effect_owned_publisher_110068f9062bfe12d5a501935f1a631c`、attempt 1、
`succeeded/delivered`，evidence SHA-256
`9ecceb0468f16bec17b2e0a418db4a4ae4c512850c1e39723122996ef33bcbe1`。Exact rollback
回到 `legacy/7`後，final recutover為 `operations_core/8`；stale generation 7 transfer
被拒，generation 8兩條 frontend fence再次通過。故 operator seam與 program commit 14
為 **`root_cause_fixed_and_verified`**；整體 operations-core umbrella仍為
**`contained`**。

### 2026-07-25 — Publisher cutover 後舊 projection tests 在 clean CI 誤走 formal caller

**證據化症狀與根因層級**：GitHub Actions runs `30107632406`、`30111281248`
連續以同四案失敗：兩個 cache purge regression與兩個 server-resident details
regression都在 `ServiceRoleRpcClient` 建構時拋出
`ValueError: Supabase URL and service-role key are required`。從 tracked `HEAD`
建立不含 `.env.local` 的 clean archive後，0.17秒最小重現可連續兩次得到同一錯誤。
根因不是 CI 缺 production credential，也不是 production owner router應回退；
commit `35242068a5` 已把 `sync_article()` 切到 owner-fenced Operations Core formal
caller，但四個只驗 direct projection provider 的舊 tests仍 mock `_post`／
`_select_rows`後呼叫 router。Developer checkout的 gitignored `.env.local`把 stale
test seam 推進到 live RPC，掩蓋了 clean-checkout credential failure。

**修正與安全邊界**：四案改為直接呼叫正式 provider seam
`sync_article_projection()`，與同一 cutover已遷移的 effect-adapter regression一致。
Production `sync_article()`、owner lookup、service-role composition、keepalive與
fail-closed路由完全未改；測試也不注入假 production credentials或放寬 remote-access
guard。

**回歸與制度化**：原始 clean-archive兩檔命令由4 failed轉為
**22 passed, 1 skipped**；publisher ownership／effect／rehearsal相鄰套件的
**47個 assertions通過**。完整CI命令
`uv run --extra dev python -m pytest -q -p no:cacheprovider`為
**5005 passed, 1 skipped**，`git diff --check`通過，且沒有 remote write、email、
canonical write、owner transfer或live effect。本CI test-contract根因為
**`root_cause_fixed_and_verified`**；跨兩台實體Mac的Primary Authority receipt pair
仍缺，故整體operations-core umbrella維持 **`contained`**。

### 2026-07-25 — Full sync 在 provider 失敗後仍推進 cursor 並回報成功

**證據化症狀與根因層級**：四個 hermetic failure injections在修正前得到
`4 failed, 14 passed`。Article provider回 `False`後，`sync_full()`仍把
`feed_mtime`寫成當前檔案時間；memory第二筆失敗後仍繼續第三筆並把 count設為檔案
總長；risk provider失敗仍回報 `risk_forecast=1`；CLI沒有任何通用 failure contract。
另有相依漏洞：cache purge retry即使 prerequisite article write失敗，也會被清空。
根因在 acknowledgement/cursor transaction契約：本地進度代表「迭代過」，不是
「下游已確認」，因此 unchanged gate會讓未落地 projection永久不可達。這不是資料內容
錯誤，也不能靠手改 sync state收尾。

**底層重構**：Article path新增 persistent `article_retry_slugs`，provider失敗不推進
`feed_mtime`；retry slug本身也是下一輪 gate輸入，避免由其他原因開 gate時發現的 drift
在失敗後再次消失。`purge_retry_slugs`只在 projection prerequisite成功後清除。Memory
count改為下游 acknowledgement的連續前綴，第一個失敗即停止，不跨洞；risk與delete
reconcile失敗也進 `counts["failures"]`。`_report_counts()`遇任何 projection failure
一律非零，不再印假 `Done.`。

**回歸、回讀與制度化**：同四個 RED injections轉 GREEN；article retry第二輪確實再
呼叫同 slug並在成功後才推進 mtime，memory第二輪從失敗 id接續後才到尾端，state與
exit code均逐欄回讀。Supabase hash、cache purge與delete reconcile相鄰 suite為
clean tracked snapshot **31 passed, 1 skipped**，`git diff --check`通過；沒有 remote write、canonical
研究資料修改、owner transfer或live effect。此 silent cursor advancement根因為
**`root_cause_fixed_and_verified`**；program commit 15的 formal EffectRequest／
outbox ownership、週期 convergence receipt與rollback rehearsal尚未完成，因此
program commit 15與 operations-core umbrella仍為 **`contained`**。

### 2026-07-25 — Projection audit 只查 local slug，Supabase orphan 永遠不可見

**證據化症狀與根因層級**：`audit_publish_sync.py`的契約列出 remote-only orphan，
實作卻把 local published slug組成 `in (...)`交給Supabase；remote集合因此必為local
集合子集，`remote - local`在資料取得前就被機械消除。Local視窗為空時函式還直接回
空集合，不需要credential或remote observation，receipt仍可標converged。這是
convergence observation domain錯誤，不是Supabase資料或單篇writer漂移。

**底層重構**：Receipt schema升為
`publisher-projection-convergence.v2`；remote read改查與local完全相同的72小時
`published_at` window及published status，不再接受local slug白名單；exact count與
Range分頁保證完整讀完視窗。Audit雙向保存`missing_supabase`與
`orphan_supabase`，兩者都計入mismatch與alert；即使local為空也照常查remote。
Credential、transport與response-shape failure維持typed
`unavailable`，禁止用空remote集合冒充證據。

**回歸、production回讀與狀態界線**：新增remote-only與empty-local兩個failure
injections，另鎖定PostgREST URL必含published/window filter且不得含slug `in`，
並覆蓋多頁remote projection；audit與schedule scoped suite共 **11 passed**，
compileall與`git diff --check`通過。
Production read-only smoke只寫臨時receipt，回讀v2 `converged`：local=14、
Supabase=14、missing=0、orphan=0、live 404=0、observation error=0；沒有remote
mutation、owner transfer或canonical receipt寫入。此false-convergence根因為
**`root_cause_fixed_and_verified`**；program commit 15的週期convergence receipt
gate完成，formal outbox ownership與rollback rehearsal仍缺，故commit 15與
operations-core umbrella維持 **`contained`**。

### 2026-07-25 — Hourly feed-sync 已記 effect failure，cron receipt 仍 exit 0

**證據化症狀與根因層級**：failure injection讓
`sync_feed_to_supabase(..., dry_run=False)`回傳
`result.failed=1`與具體 slug／operation，但 `volpred ops feed-sync --apply`仍得到
`exit_code=0`。每小時 wrapper忠實傳遞 CLI code，因此 `cron_emit_exit`會把未確認的
Operations Core article projection記成成功。根因在 CLI／scheduler
acknowledgement seam：effect adapter、durable outbox與 per-article caller已回報失敗，
最外層卻只列印 nested counters，沒有 aggregate acknowledgement contract。

**底層重構**：feed-sync模組的 external interface現在明確回傳
`acknowledged=True|False`；只有 apply模式且所有嘗試的 projection effect均確認才為
true，dry-run則為 `None`。CLI仍先輸出完整 JSON evidence，但 apply結果不是明確
`True`時 fail closed為 exit 1；`--quiet-when-clean`的 clean路徑仍安靜 exit 0。
`config/runtime_schedules.json`同步登記 0／1語意，wrapper contract regression固定
`cron_emit_exit`與最終 `exit "$_ec"`，避免日後吞掉 CLI code。

**回歸、下游回讀與狀態界線**：原始 RED由 `exit_code=0`轉為1；成功、quiet-clean、
aggregate acknowledgement與wrapper propagation共5案通過，與 feed diff、
full-sync cursor、publisher owner／effect相鄰套件合計 **69 passed**。
Production read-only dry-run回讀 `feed=1877`、`db=1877`、insert/update/delete均0，
cron wrapper canonical／manifest／host副本 lockstep。沒有 remote write、owner
transfer或 canonical research data mutation。此 scheduler false-green根因為
**`root_cause_fixed_and_verified`**；program commit 15仍缺 full-sync formal outbox
ownership與rollback rehearsal，故 program commit 15及 operations-core umbrella維持
**`contained`**。

### 2026-07-25 — Full-feed reconcile 沒有 immutable batch EffectRequest

**證據化缺口與根因層級**：single-article projection已有payload-bound formal caller，
但 hourly reconcile的batch intent仍由caller讀live feed、算diff後逐篇呼叫；若直接把
這層包進outbox，worker retry會在EffectRequest建立後重新讀可能已變動的feed，原請求
identity與真正執行的article集合便可分離。根因是batch transaction seam缺少immutable
intent，不是diff演算法或Supabase row錯誤。

**底層contained切片**：新增
`prepare_publisher_article_reconcile(...) -> PreparedPublisherArticleReconcile`單一
interface，將canonical feed SHA-256及本次完整articles綁入deterministic payload，
effect kind／target／safe risk／typed acknowledgement與payload hash全由module擁有。
`PublisherArticleReconcileEffectAdapter`只接受唯一slug canonical排序；先read-back、
只upsert mismatch、再要求全batch exact read-back。Payload／contract漂移為terminal，
provider與read-back failure為retryable，generic durable worker可據此dead-letter或
重試。Delete因具destructive語意刻意不混入safe family。

**回歸、回讀與狀態界線**：八個新cases覆蓋EffectRequest replay、部分已收斂batch、
provider failure、非法evidence、schema/order/risk拒絕與durable dead-letter；與
single-article及worker相鄰套件共 **36 passed**，compileall及`git diff --check`通過。
Production adapter read-only回讀`mile_30b22ca5`為exact match，evidence SHA-256
`b8b20a3bddd6c5035f821ac0572f38b1c6785b83e2b51d6658f6837289e6dff6`；沒有remote
write或owner mutation。因hourly producer尚未接production payload store／outbox owner，
且family owner CAS、delete effect與rollback rehearsal未完成，本項與program commit 15
均維持 **`contained`**，不可宣稱cutover完成。

### 2026-07-25 — Mixed audit exit contract 讓 Test Suite 連續紅燈

**證據化症狀與根因層級**：GitHub Test Suite runs `30122387928`與`30126175832`
連續只紅
`test_runtime_schedule_marks_known_findings_exit_jobs`：`audit_publish_sync.log`
不再被辨識為findings job。該job的真實contract是exit 0=converged、1=findings、
2=observation unavailable；舊helper只接受整欄精確等於`"findings"`，資料模型只能
「全豁免」或「全當infra failure」。因此保留精確0/1/2描述會讓exit 1假critical，
改回整欄findings又會吞掉真正的exit 2。根因是alert metadata缺少per-code分類。

**底層修復**：runtime schedule新增typed `findings_exit_codes`，目前
`audit_publish_sync=[1]`。新helper回傳log→code set；legacy
`exit_semantics=findings`仍代表所有nonzero皆為finding。Host-cron parser先讀latest
exit code，只豁免typed set命中的code；已登記mixed contract的audit不再套用
`audit_*`整支豁免fallback，且consecutive-failure計算也忽略同一typed findings code。

**回歸與制度化**：新增同一audit exit 1不breach、exit 2仍breach的對稱測試；canonical
schedule inventory再次包含`audit_publish_sync.log`。Alerts、feed-sync CLI、
projection audit、publisher effect相鄰套件共 **121 passed**，JSON parse、
compileall與`git diff --check`通過。這個CI／alert contract根因為
**`root_cause_fixed_and_verified`**。

### 2026-07-25 — Immutable reconcile存在，但hourly safe intent仍由caller擁有

**證據化症狀**：shadow batch contract已能固定canonical feed SHA與完整articles，
但production `feed_sync`仍由caller讀live feed、算diff後逐篇送出；production沒有
batch family owner、private payload、outbox transaction或exact rollback。因而即使
worker contract正確，hourly producer重試仍可能在不同時間重新建立另一個intent，
也無法從durable receipt證明「哪一批」由哪一代owner執行。

**根因層級與底層修復**：根因是production ownership／transaction seam，不是Supabase
row或diff資料。新增`publisher.article.supabase.reconcile` family及generation-CAS
owner；五個service-role-only PostgreSQL RPC把request、begin、settle、owner read與
transfer收進formal transaction。Request保存完整canonical payload並建立WorkItem、
EffectRequest/outbox；begin要求同代owner與active primary lease；settle要求同一
work、outbox、authority receipt與typed read-back。`feed_sync`只依owner選legacy逐篇
或Operations Core單批路徑，article objects與feed SHA由同一份byte snapshot產生，
避免並行改稿造成舊objects綁新hash；destructive delete不共用safe authority。

**回歸、回讀與制度化**：最終tracked-snapshot selected suite 91案通過（含完整
47-case PostgreSQL contract檔），涵蓋routing、exact replay、generation fence、
active-attempt transfer拒絕、security ACL、success、rollback與再cutover。第一次
post-commit schedule-equivalent驗證另抓到caller仍走`_load_feed()`、未綁新SHA變數；
根因是先前測試只直呼batch helper，未跨`apply_diff()`邊界。Caller現以單次
`_load_feed_snapshot()`同時取得objects與SHA，新增回歸會讓任何第二次feed read直接
失敗；修後同一CLI安靜exit 0。Production operator rehearsal完成
`legacy/1 → operations_core/2 → legacy/3 (rollback_of=2) →
operations_core/4`；回讀WorkItem `succeeded`、Effect/outbox `delivered`、attempt與
authority receipt一致，local/Supabase均14且drift=0；schedule-equivalent hourly
command exit 0。Canonical schedule、wrapper、架構、module design與operator script均
寫回，讓同類ownership缺口無法再靜默退回caller。Safe reconcile ownership切片為
**`root_cause_fixed_and_verified`**；獨立destructive delete effect／owner／rollback
及physical two-Mac evidence仍未完成，所以program commit 15與operations-core
umbrella維持 **`contained`**。

### 2026-07-25 — Publisher read-back期間換代後舊attempt仍可upsert

**證據化症狀與根因層級**：single-article與safe reconcile formal callers已在request、
begin及provider入口核對Primary Authority，但兩個provider的第一個動作都是真實
Supabase read-back。Failure injections在該read-back返回前把keepalive換成新epoch／
fencing token，舊attempt仍進入upsert；database settlement fence即使之後拒絕，也
無法撤回已發生的外部write。根因是authority revalidation放在external boundary之前，
而不是緊貼mutation，不是owner RPC、Supabase row或keepalive renew錯誤。

**底層修復**：兩個owned callers都將進入attempt時的完整lease identity綁成mutation
authorizer；single與batch adapters對每一筆確實需要upsert的article，在provider write
前重新核對authority key、holder、epoch、fencing token及acquired-at。任何漂移直接
拋ownership loss，不降級成retryable provider failure，也不settle舊attempt。已收斂
的read-only replay維持零write，不虛耗mutation authorization。

**回歸與制度化**：兩條failure injections修後都回讀projection write=0、settlement=0；
owned callers、single／batch effects、兩套operator rehearsals、feed sync及CLI相鄰
套件共 **82 passed**，compileall與`git diff --check`通過。此mutation-boundary fencing根因
為 **`root_cause_fixed_and_verified`**；destructive delete的獨立EffectRequest／
owner／rollback仍缺，所以program commit 15與operations-core umbrella維持
**`contained`**。

### 2026-07-25 — Publisher destructive delete缺少不可變scope與完整rollback bytes

**證據化症狀與根因層級**：legacy `reconcile_article_deletes()`雖集中floor、cap與
dump-before-delete，但dump只保存article與impressions；其他會cascade消失的
article_reactions／雙向article_relations／article_tags／comments／question_articles
沒有進rollback artifact。
既有函式也以當下mutable feed與remote read直接跨越delete，沒有先形成scope-bound
destructive EffectRequest或顯式approval identity。這代表safe reconcile已正式接管時，
delete仍不能借用同一無人值守權限。

**底層checkpoint**：新增零I/O的publisher delete deep module。第一段從exact canonical
feed bytes與完整remote candidate rows建立唯一scope，機械執行feed floor、delete cap、
候選不仍存在於canonical feed、slug／article identity唯一性，以及六個cascade table
／七條FK edge逐row article identity綁定；同時產生canonical JSONL recovery bytes與
SHA-256。第二段只有在
durable approval的scope SHA-256精確相符時，才materialize
`publisher.article.supabase.delete`、risk=`destructive`的EffectRequest；approval ref、
approver、timestamp、scope、recovery ref/hash與全部候選均受payload digest保護。
本module沒有provider adapter，也沒有接入hourly producer，因此本切片零remote mutation。

**回歸與誠實狀態**：新增contract cases涵蓋canonical ordering、floor／cap、canonical
overlap、cascade completeness／錯綁、approval drift、idempotency conflict及plan
tamper；連同Effect Delivery、safe reconcile、legacy delete與feed-sync相鄰套件共
**156 passed**，
compileall與`git diff --check`通過。Destructive intent contract checkpoint為
**`contained`**：尚需獨立owner transaction、provider mutation-boundary fencing、
durable approval verifier、exact restore executor及live rollback/convergence rehearsal，
因此program commit 15與operations-core umbrella狀態不變。

### 2026-07-25 — Delete rollback聲稱完整但漏掉雙向article_relations

**證據化症狀與根因層級**：intent checkpoint初版把cascade contract手寫成五張表，
並假設所有dependent row都以`article_id`連回article；production `pg_constraint`
回讀實際是六張表、七條`ON DELETE CASCADE` edge，其中`article_relations`分別以
`source_id`與`target_id`連回。Legacy dump又只保存article的部分欄位與impressions，
且impressions讀失敗時仍繼續delete。根因是destructive recovery以靜態、不完整的
應用層清單描述live FK graph，沒有database contract gate。

**底層修復**：cascade table/column contract現在由delete intent deep module單一持有；
shadow plan與legacy runtime共用它。Plan可接受relations任一端綁回candidate，兩端都
不符則fail closed。Legacy runtime先透過service-role-only catalog RPC精確比對live
七條edge，再讀完整article row與六張cascade table；任一RPC／child read失敗、
feed SHA在capture期間漂移、或recovery artifact的fsync後read-back不一致，都在任何
DELETE前中止。Recovery v2使用每次唯一檔案、保存canonical feed SHA與dump SHA。

**回歸與制度化**：migration function由`volpred_ops_definer`持有、空search path，
anon/authenticated/PUBLIC皆無EXECUTE，僅service_role可呼叫；production RPC回讀七條
edge與code contract完全一致。Read-only live reconcile為local=1877、remote=1877、
ghost=0、deleted=0。Contract drift、child-read failure、feed generation drift、
relations endpoint錯綁與完整cascade dump均有failure injection；generic Effect
Delivery、delete/safe/owned reconcile、feed sync及Supabase相鄰套件共
**200 passed, 1 skipped**，compileall與`git diff --check`通過。本不完整rollback根因為
**`root_cause_fixed_and_verified`**；destructive provider／owner CAS／restore executor
與live rollback rehearsal仍未完成，所以program commit 15與umbrella仍為
**`contained`**。

### 2026-07-25 — Delete intent已有approval bytes，但worker沒有destructive execution contract

**證據化症狀與根因層級**：delete intent已把canonical feed、完整candidate/cascade
rows、recovery SHA與operator approval綁成immutable EffectRequest，但沒有worker
adapter去回讀durable approval、比對remote scope或證明delete後真的absence。若直接
沿用safe reconcile provider，approval可能已撤回、第二筆candidate已漂移，或authority
在read-back阻塞期間換代；舊attempt仍可能部分刪除。根因是destructive effect
execution seam缺失，不是intent hash、legacy floor/cap或Supabase資料內容。

**底層重構**：新增`PublisherArticleDeleteEffectAdapter`與窄版approval/projection
interfaces。Adapter先驗effect contract及canonical payload，再讀回active approval，
把全部candidate的article及六表cascade bytes exact preflight；任一scope drift皆全批
零mutation。每筆delete前再次exact read-back與approval read-back，再讓owned caller
緊貼mutation重驗原Primary Authority epoch；projection的delete contract必須atomic
compare完整candidate後才刪。Authority loss刻意向外拋，不轉retry或settle stale
attempt。只有每筆typed absence read-back都帶合法evidence ref/hash才產生
acknowledgement，provider回true但row仍存在會fail closed。

**回歸、下游回讀與狀態界線**：failure injections覆蓋全scope preflight、approval在
mutation boundary撤回、authority換代零write、already-absent冪等replay與delete缺少
absence read-back及malformed provider readback；delete contract本檔 **19 passed**，
與Effect Delivery、safe reconcile及Supabase相鄰套件合計 **127 passed**。本切片無production provider、
remote mutation、owner transfer或live effect。Worker execution-contract根因為
**`root_cause_fixed_and_verified`**；production Supabase projection、owner CAS、
exact restore executor與live delete→rollback→convergence rehearsal仍缺，故program
commit 15及operations-core umbrella維持 **`contained`**。

### 2026-07-25 — Destructive adapter完成但production沒有owner、approval store或atomic projection

**證據化症狀與根因層級**：worker adapter雖能驗scope、approval與typed absence，但
production沒有`publisher.article.supabase.delete` owner row、durable approval store、
WorkItem/EffectRequest/outbox transaction或真正compare-delete RPC。把現有Python
protocol直接接到legacy HTTP DELETE，仍會留下跨transaction的owner／approval／authority
TOCTOU。根因是production ownership與database mutation seam缺失，不是adapter、
canonical feed或Supabase article資料。

**底層重構**：新增獨立destructive family與owner generation CAS；正式caller只接受
immutable prepared intent，保存原始canonical payload bytes，再由attempt-bound factory
建立approval verifier與projection。Approval使用private RLS/FORCE RLS table並提供
service-role-only record/read/revoke。Compare-delete在同一PostgreSQL transaction內鎖定
owner、started attempt、approval、Primary Authority lease、article與六表child rows；
durable effect payload中的authorization/candidate、live七條cascade contract及database
candidate任何一項不一致都禁止DELETE。十個public wrapper皆空search path、no-login
definer owner，PUBLIC／anon／authenticated無EXECUTE。

**回歸與下游回讀**：首次production smoke在任何INSERT前抓到approval function的
PL/pgSQL `approval_ref`欄位／局部變數ambiguity；原migration保持immutable，另以
forward-only migration把local重新命名並用table alias限定，重跑後approval
record→read-back→revoke成功，最終evidence SHA-256為
`d92fef088e81089f49c53556fcb521a25a63ef0c45c13fe0f73b6f122fe05df1`。
Production candidate read-back確認六張dependent tables與64字元evidence hash；owner
CAS完成`legacy/1 → operations_core/2 → legacy/3 rollback`，故意compare-delete被拒，
前後candidate與evidence完全相同，零article mutation。相鄰Effect/outbox、safe
reconcile、publisher sync與Supabase suites共
**222 passed**。本production owner／approval／projection根因為
**`root_cause_fixed_and_verified`**；exact restore executor、manual-only
delete→rollback→convergence rehearsal及physical two-Mac receipts仍未完成，故program
commit 15與operations-core umbrella維持 **`contained`**。

### 2026-07-25 — Recovery JSONL存在但沒有可驗證的exact restore execution contract

**證據化缺口與根因層級**：destructive delete已在任何mutation前保存完整article與
六張cascade table，但consumer尚未定義如何拒絕hash漂移、如何處理部分已恢復的replay，
以及如何證明整批restore後逐row bytes完全相同。若operator自行逐表INSERT，第二筆失敗
會留下partial rollback，或已存在但漂移的row被靜默覆寫。根因是recovery artifact與
provider之間缺少atomic transaction／typed read-back seam，不是dump capture或FK graph。

**底層checkpoint**：新增`PublisherArticleDeleteRestoreExecutor`單一interface。Executor
只接受SHA-256精確相符、canonical且slug排序的recovery JSONL；schema仍要求完整六表並
沿用雙向`article_relations`identity gate。它先read-back全部candidate，只允許absent或
exact match；任何scope drift全批零write。真正缺row時必須提供mutation authorizer，
再委派一個「全批compare + restore」atomic projection；完成後逐candidate要求typed
evidence與exact byte-equivalent read-back。全批已恢復的replay不取mutation authority，
仍產生hash-bound receipt。

**回歸與狀態界線**：failure injections覆蓋dump hash／canonical order、preflight drift、
缺authority、authority loss、provider未落地及idempotent replay；delete、owned delete、
safe reconcile、Effect Delivery與Supabase相鄰套件共 **157 passed**，compileall與
`git diff --check`通過。沒有production RPC、remote write、owner transfer或live effect。
本execution contract checkpoint為 **`root_cause_fixed_and_verified`**；production
service-role atomic restore projection與manual-only live delete→restore→convergence
rehearsal仍缺，故program commit 15與operations-core umbrella維持 **`contained`**。

### 2026-07-25 — Exact restore contract存在，但production仍沒有原子restore projection

**證據化症狀與根因層級**：`PublisherArticleDeleteRestoreExecutor`已把recovery hash、
canonical JSONL、全批absent／exact preflight與typed post-readback釘死，但production
只有read-candidate與compare-delete RPC，`restore_batch`仍只存在Protocol與test fake。
若operator直接逐表INSERT，article成功而任一child失敗會留下partial restore；
`article_relations`同時連到兩個待恢復article時也可能重複INSERT或違反FK順序。根因是
database transaction projection缺失，不是recovery bytes、executor或live FK catalog。

**底層重構**：新增`SupabasePublisherArticleDeleteRestoreProjection`與唯一
`volpred_restore_publisher_article_delete_batch(jsonb)` RPC。RPC由no-login
`volpred_ops_definer`持有、`SECURITY DEFINER`且空search path，只授權service role
EXECUTE；PUBLIC／anon／authenticated均撤權。Transaction先驗production七條cascade
edge、逐row round-trip table shape與article binding，再鎖全批parent／child rows；
所有candidate只准absent或exact，任何漂移都在首筆INSERT前拒絕。真正restore先一次
插入全部articles，再依序插六張child tables；雙向relation用PK identity去重。任一
constraint／trigger／readback例外由同一transaction全批rollback；全批已存在的replay
回`restored_count=0`且不寫。

**回歸、live回讀與狀態界線**：隔離PG17把兩份migration各重套兩次，failure injections
**6 passed**，涵蓋六表exact restore、read-only replay、雙edge relation去重、scope
drift全批零write、nullable child脫離candidate必拒，以及article／前三張child已INSERT
後在article_tags觸發例外仍全批rollback。首版production migration
`20260725020432`套用後，failure injection再抓到SQL三值邏輯
`NULL <> expected = UNKNOWN`；依forward-only原則保留原migration，另以
`20260725020935` wrapper使用`IS DISTINCT FROM`防守六表binding，舊v1撤掉service-role
EXECUTE只留no-login owner內呼叫。Catalog回讀確認function owner、空search path、
service-role-only ACL、14個INSERT／UPDATE RLS policies、七條cascade contract及
no-login definer無public CREATE均正確；Supabase security／performance advisors沒有
新增此function告警。沒有執行production article restore或delete。
本production atomic projection slice為 **`root_cause_fixed_and_verified`**；manual-only
live synthetic delete→restore→feed convergence rehearsal與physical two-Mac authority
receipt pair仍缺，故operations-core umbrella維持 **`contained`**。

### 2026-07-26 — Production delete／restore都存在，但人工演練仍靠operator手工串接

**證據化症狀與根因層級**：destructive owner、approval、compare-delete、完整recovery
與atomic restore projection都已上production，但沒有單一入口固定實際演練順序。
Operator若手工串RPC，可能重用同一EffectRequest做restore後cleanup、delete response
遺失時直接rollback owner，或restore失敗後跳過approval revoke。根因是operator
transaction choreography缺失，不是database projection或Effect adapter。

**底層修復**：新增manual-only
`scripts/rehearse_publisher_delete_restore.py`，機械限制單筆固定prefix synthetic
candidate與explicit confirmation。入口在任何remote mutation前freeze並read-back
recovery bytes；再依序record scope-bound approval、generation-CAS cutover、第一個
owned delete、atomic exact restore、第二個不同idempotency/work identity的cleanup
delete、standing convergence read-back、CAS rollback與approval revoke。不確定delete
一律先exact restore；cleanup code會分別嘗試restore、owner rollback與approval revoke，
不因前一步exception跳過後兩步。

**回歸與誠實狀態**：failure injections涵蓋happy path、第一個delete response遺失、
cleanup response遺失、approval response遺失、restore failure仍rollback/revoke，以及
非synthetic scope在任何remote mutation前拒絕；與owned delete、restore contract及
PostgreSQL restore suites共 **56 passed**，CLI help、compileall與`git diff --check`
通過。本輪沒有pre-seed production synthetic row或執行live mutation，因此operator
seam根因為 **`root_cause_fixed_and_verified`**，但actual live rehearsal evidence與
physical two-Mac receipt pair仍缺，operations-core umbrella維持 **`contained`**。

### 2026-07-26 — Live publisher delete rehearsal被WorkItem admission與RLS row lock連續擋下

**證據化症狀**：首輪production synthetic rehearsal在建立destructive WorkItem時回報
`invalid submitted work policy or initial state`；修正後，owned request／attempt／effect
與Primary Authority都已落盤，但compare-delete連續回`P0002 query returned no rows`。
每次失敗後都由rehearsal cleanup確認synthetic exact restore、owner回`legacy`及approval
revoke，沒有以手補row或重寫receipt止血。

**根因層級**：第一層是workflow contract——scope-bound delete approval沒有被提升成
generic WorkItem的`required/awaiting_approval → approved/pending`狀態。第二層是database
RLS／locking contract——append-only `owned_notification_requests`刻意只有SELECT／INSERT
policy，但compare函式對它做`SELECT ... FOR SHARE`；PostgreSQL會把UPDATE policy也套到
`SELECT FOR UPDATE/SHARE`，default-deny把已存在的request row過濾成零列。Live
service-role-only preflight在同一lease內證明九項identity全為true，exception wrapper再
把位置收斂到compare函式`line 47`的owned request locking read。

**底層修復與制度化**：forward migrations
`20260725202655_promote_publisher_delete_scope_approval.sql`先由正式
`approve_work`完成WorkItem promotion；
`20260725204038_publisher_delete_compare_preflight_diagnostics.sql`與
`20260725204444_publisher_delete_compare_exception_context.sql`保留service-role-only、
token不外洩的typed diagnostics；最後
`20260725205013_remove_owned_request_share_lock.sql`在已鎖住owner generation後，對
immutable request改用plain exact SELECT，不新增UPDATE policy、不放寬append-only
invariant。Python projection會在database error時附上SQLSTATE／line及read-only
failed-check集合，provider boundary不再靜默吞掉原始根因。

**回歸與live回讀**：隔離PG17重現同一RLS差異（plain SELECT可見、`FOR SHARE`不可見）
並驗證新函式；`live-20260726-0503`隨後完整完成primary delete、exact restore與不同
effect的cleanup delete。DB回讀確認兩筆WorkItem皆`succeeded`、Effect與attempt皆
`delivered`、Primary Authority epoch 8／9皆有release receipt、synthetic row absent、
owner=`legacy/19`、approval inactive；standing convergence為`converged`且
`mismatch_total=0`。本incident為 **`root_cause_fixed_and_verified`**；physical
two-Mac authority receipt pair仍缺，所以operations-core umbrella維持
**`contained`**。

### 2026-07-26 — Cross-host verifier只雜湊operator，兩端依賴漂移仍會假綠

**證據化症狀與根因層級**：physical pair receipt原本的`implementation_sha256`只讀
`scripts/rehearse_primary_authority_outage.py` bytes。若primary與standby checkout的
authority session、keepalive、Supabase adapter或publisher fence reader不同版，只要
operator檔相同，verifier仍會誤判「相同implementation」。Verifier也只比較兩端
authority key相等，沒有重新從shared rehearsal ID導出隔離key。根因是evidence identity
過淺，不是lease CAS或database clock。

**底層修復與驗證**：implementation identity改為canonical source manifest，涵蓋
operator與`src/volpred/ops/**/*.py`全部Python source，逐檔SHA後再aggregate；verifier
另要求authority key精確等於rehearsal ID derivation。針對性與相鄰authority suites
**31 passed**，`py_compile`與`git diff --check`通過；Ruff在本repo環境未安裝，沒有以
缺工具宣稱lint通過。本輪沒有remote acquire或effect。此false-positive根因為
**`root_cause_fixed_and_verified`**；physical two-Mac receipt仍需真實兩機執行，
operations-core umbrella維持**`contained`**。

### 2026-07-26 — Cross-host receipt在結束時才雜湊，可能記到未執行的新code

**證據化症狀與根因層級**：兩個process role原本在組receipt時才呼叫
`_implementation_sha256()`。Shared checkout若在primary已import modules並開始live
rehearsal後被其他writer更新，primary仍執行舊loaded code，receipt卻雜湊新disk bytes；
稍後由新code啟動的standby會得到相同hash，pair verifier因而可能假綠。根因是run-time
code identity沒有包住實際執行窗口，不是authority CAS或DB clock。

**底層修復與驗證**：Primary／standby均在第一個remote read／mutation前快照canonical
implementation aggregate，remote cleanup後、receipt construction前重驗；任何source
drift都raise且不產receipt。兩個role新增failure injection，standby路徑另確認lease已
release；相鄰authority suite、compile與diff gate通過。本false-positive根因為
**`root_cause_fixed_and_verified`**；第二台實體Mac目前無可操作remote session，故沒有
執行production role，physical pair與operations-core umbrella仍為**`contained`**。

### 2026-07-26 — Physical rehearsal到mutation後才驗第二台host readiness

**證據化症狀與根因層級**：正式流程原本直接在第一台執行`primary`，完成live
authority acquire／renew／demote後才把兩份role receipt交給`verify-pair`。第二台若
credential不可用、source aggregate不同、publisher fence漂移或其實不是distinct
machine，都只能在第一台已mutation控制面後發現。根因是operator sequencing缺少
pre-mutation cross-host compatibility gate，不是Primary Authority CAS。

**底層修復與驗證**：新增只讀`prepare-host`與`verify-readiness`，先綁定兩端machine
fingerprint、canonical source aggregate、shared rehearsal-derived key與publisher
owner；正式primary／standby CLI都強制帶同一paired readiness，並在任何authority RPC
前重驗本機role與source。Code mismatch、same-machine、wrong-role與readiness後source
drift（含CLI validation後窄race）failure injections均fail closed；相鄰authority
suites **36 passed**，
`py_compile`與`git diff --check`通過。Production只讀preflight回讀
publisher=`operations_core/8`與安全隔離key，未acquire authority、未呼叫provider。
此sequencing根因為 **`root_cause_fixed_and_verified`**；沒有第二台可操作remote
session，故physical pair與operations-core umbrella仍為 **`contained`**。

### 2026-07-26 — Final cross-host pair沒有綁定mutation前的readiness

**證據化症狀與根因層級**：`primary`／`standby` CLI雖強制讀paired readiness，process
receipt卻沒有該artifact identity；`verify-pair`只接兩份role receipt，也完全不讀
readiness。事後因此無法證明實際roles使用的是mutation前驗過的那組主機、source與
publisher fence，另一組相容role receipt可脫離原preflight重新配對。根因是evidence
schema與function interface沒有端到端bind readiness，不是lease CAS或DB clock。

**底層修復與驗證**：兩個role function改為直接要求typed readiness並在function boundary
重驗，process receipt升v2且各自寫入同一readiness SHA-256；final verifier新增必填
readiness，重驗structural invariants、兩端host／source／safe key／publisher fence及
receipt hash binding，final receipt亦升v2保存該SHA。Failure injections涵蓋不同
readiness receipt、edited same-machine artifact、role identity drift與validation後
source race；相鄰authority suites **37 passed**，`py_compile`與diff gate通過。
Production只讀preflight回讀`operations_core/8`與implementation
`cc02ab8d5a073f2bd85aa08045abcd285b2a3151059192c7b99dea40563043cc`，沒有authority
acquire或provider call。此evidence-chain根因為
**`root_cause_fixed_and_verified`**；第二台實體Mac尚未執行roles，physical pair與
operations-core umbrella仍為 **`contained`**。

### 2026-07-26 — Hash-fenced exact-path commit只驗hook前的candidate

**症狀與根因層級**：canonical writer雖在`git commit --only`前驗
`--expected-content-hash`，commit後卻只驗changed path scope。Failure injection讓
pre-commit hook在同一個已授權path重新寫bytes並`git add`；最終commit仍只有exact path，
helper因此rc=0，但commit blob已不是reviewed ChangeSet。只切executable bit也有同樣問題，
因blob SHA不變且scope合法。根因是immutable content identity沒有跨越hook boundary，
不是pathspec或authority grant失效。

**底層修復與驗證**：writer在hook前保存每個hash-fenced staged entry的Git mode，commit
後從實際tree object回讀blob SHA-256與mode；任一漂移都在同一writer lease內以HEAD CAS
回退、還原原index，並保留一般working bytes供診斷。Bytes rewrite、mode-only rewrite與
foreign-path injection三種failure injection均通過；相鄰writer／reference-hook／Change
Delivery suites **98 passed**，`py_compile`與diff gate通過。此post-hook identity假成功根因為
**`root_cause_fixed_and_verified`**；operations-core umbrella仍只因physical two-Mac
authority receipt pair未完成而維持 **`contained`**。

### 2026-07-26 — Standby先改live lease，最後才知道primary evidence不相干

**證據化症狀與根因層級**：standby正式入口只接operator手抄的
`expected_primary_epoch`，沒有讀primary receipt。它會先嘗試acquire live authority，
final `verify-pair`才檢查epoch、readiness與primary fail-closed evidence是否屬於同一
次rehearsal；錯檔、舊檔或不完整primary evidence會先mutation控制面、事後才失敗。
Primary／standby function另接受caller自填`holder_ref`，authority lease identity可與
receipt宣稱的physical host脫鉤。根因是standby function interface缺少primary evidence
的pre-mutation binding，並把identity derivation外洩給caller，不是lease CAS或DB clock。

**底層修復、回歸與live回讀**：standby function／CLI改為強制接收primary v2 receipt，
在任何publisher read或authority RPC前驗shared rehearsal-derived key、readiness SHA、
primary host／source、lease window、healthy renewal、local gate closure、partition
probe、terminal demotion、零effect/provider counters與exact publisher fence，再由
receipt直接導出epoch。兩端holder改由rehearsal、role及host fingerprint內部唯一導出，
final verifier同樣重驗。Failure injection將primary
`local_gate_closed`改為false，回讀standby零新增remote read／零新增claim；holder drift
亦被拒。相鄰authority suites **38 passed**，`py_compile`與diff gate通過。Production
只讀preflight `standby-preflight-20260726-0830`原子落檔並exact read-back
publisher=`operations_core/8`、安全隔離key及implementation
`a273e8bc7ae65fb0f0205dbc9caadf8485f88422bda6bdceccc0a0796d6fab52`，沒有authority
acquire或provider call。此standby sequencing／identity根因為
**`root_cause_fixed_and_verified`**；第二台實體Mac仍無可操作session，physical pair與
operations-core umbrella維持 **`contained`**。

### 2026-07-26 — Cross-host implementation identity漏掉dependency lock與實際runtime

**證據化症狀與根因層級**：physical pair的`implementation_sha256`雖已涵蓋operator與
`src/volpred/ops/**/*.py`，但兩台Mac若source完全相同、`uv.lock`／`pyproject.toml`
不同，或實際Python／OpenSSL runtime漂移，readiness仍會判成相同implementation。
原回歸只assert Python source paths，重現測試加入lock與runtime identity後先紅燈。
根因是implementation boundary仍只等同source tree，不是Supabase lease CAS。

**底層修復、回歸與狀態**：canonical manifest現同時雜湊全部Operations Core Python
source、`pyproject.toml`、`uv.lock`，並把實際Python implementation／version與OpenSSL
version序列化後納入aggregate；任一端dependency spec或stdlib HTTPS runtime不同，
`verify-readiness`都會在authority RPC前拒絕。Failure injection改寫runtime version
後digest必須漂移；相鄰authority suite **44 passed**，`py_compile`與diff gate通過；
Ruff在本repo環境未安裝，未以缺工具宣稱lint通過。本false-green根因為
**`root_cause_fixed_and_verified`**；第二台實體Mac仍無可操作session，physical pair與
operations-core umbrella維持 **`contained`**。

### 2026-07-26 — Physical host fingerprint誤用network node，同一Mac可被當成兩台

**證據化症狀與根因層級**：同樣`host_id="Mac"`的既有readiness保存fingerprint
`32a72d…`，本輪第一次readiness卻變成`8a336d…`；緊接著另一個process的
`uuid.getnode()`又回不同node。原實作把hostname與`getnode()`雜湊，網路介面選擇漂移
就足以讓同一台實體Mac通過`primary_fingerprint != standby_fingerprint`。根因是把
network-interface identity誤當physical-machine identity，不是pair比較條件本身。

**底層修復、回歸與live回讀**：macOS現只從`/usr/sbin/ioreg`讀`IOPlatformUUID`，
receipt僅保存其SHA-256前綴、不暴露raw UUID；讀不到穩定hardware anchor就fail closed。
Failure injection在同一platform anchor下切換兩個network node，fingerprint必須不變。
相鄰authority suite **44 passed**，`py_compile`與diff gate通過。Production只讀preflight
`physical-anchor-preflight-20260726-0925`已原子落檔並exact read-back
publisher=`operations_core/8`、stable host fingerprint=`6652d01267d664d621c957b8`及
implementation=`ef95ccf23a39a3fa4b9c724214ff07afc4d1fc5d7b3f0cc5c1d5c37a4fa192b7`；
沒有authority acquire或provider call。本physical-identity false-green根因為
**`root_cause_fixed_and_verified`**；第二台實體Mac仍無可操作session，physical pair與
operations-core umbrella維持 **`contained`**。

### 2026-07-26 — Standby驗過primary receipt但沒有留下exact artifact identity

**證據化症狀與根因層級**：standby正式入口已在任何publisher read／authority RPC前
驗完整primary v2 receipt，但standby v2 receipt只保存`expected_primary_epoch`。Failure
injection先讓standby正常完成，再只改final verifier收到的primary `completed_at`；
舊verifier仍產出`cross_host_verified=true`。根因是pre-mutation evidence identity沒有
跨越standby receipt boundary，epoch相等被誤當成exact artifact相等，不是Authority CAS。

**底層修復、回歸與live狀態**：standby在完整primary驗證後、remote read前計算canonical
primary receipt SHA-256，standby schema升v3保存該digest；final verifier重算目前primary
artifact並要求exact match，final schema亦升v3沿用相同
`primary_receipt_sha256`。上述failure injection修前紅、修後fail closed；相鄰authority
suites **41 passed**。Production只讀preflight
`primary-artifact-preflight-20260726-0940` exact read-back
publisher=`operations_core/8`與implementation
`bfa6af660456fb3292b00fbda334c4c21a1dceb79e6e694942077fc24ed34168`。本機Tailscale
backend由Stopped恢復Running後，live peer狀態顯示候選第二台Mac離線且ping timeout，
所以沒有執行authority acquire或provider call。本artifact-binding根因為
**`root_cause_fixed_and_verified`**；physical pair與operations-core umbrella仍維持
**`contained`**。

### 2026-07-26 — Paired readiness有hash欄位但consumer拿不到raw host artifacts

**證據化症狀與根因層級**：readiness pair v1記錄primary／standby host receipt
SHA-256，但pair沒有內嵌原始artifacts，正式roles與final verifier也不接收它們。只修改
pair的standby host identity並保留兩個既有digest，primary role仍會接受並開始publisher
read；這讓「兩端都先完成read-only preflight」只剩無法重算的宣告。根因是raw evidence
沒有跨越paired receipt boundary，不是Primary Authority CAS。

**底層修復、回歸與live狀態**：pair schema升v2並內嵌兩份typed host readiness receipts；
每個consumer先重算canonical digest，再逐欄核對rehearsal、authority key、host identity、
source aggregate及publisher fence。上述identity-drift failure injection在零新增remote
read、零authority acquire下fail closed；相鄰authority suites **42 passed**，
`py_compile`與diff gate通過，Ruff未安裝。Production只讀preflight
`raw-host-binding-preflight-20260726-1010` exact read-back
publisher=`operations_core/8`、fingerprint=`6652d01267d664d621c957b8`及implementation
`66030247729b74be53645bd0d9da87fbe3940f2ba4443034083340691b973c38`，沒有authority
acquire或provider call。本raw-artifact binding根因為
**`root_cause_fixed_and_verified`**；第二台實體Mac仍離線，physical pair與
operations-core umbrella維持 **`contained`**。

### 2026-07-26 — Paired readiness完整綁artifact但沒有有效期限

**證據化症狀與根因層級**：pair v2會重算兩份raw host receipt，卻只檢查
`observed_at`能解析。修正前failure injection顯示16分鐘前的host observation仍能形成
pair；20分鐘前形成的完整pair交給primary後，流程真的開始publisher read與authority
acquire。根因是readiness interface缺少temporal validity contract，讓「曾經online」
被當成「mutation前仍ready」，不是Primary Authority CAS。

**底層修復、回歸與live狀態**：pair schema升v3，從較早host observation導出15分鐘
`valid_until`，pairing拒絕stale observation及領先verifier clock超過60秒的時間戳；
primary／standby共用active-window validator並在任何remote read前執行。Final verifier
重算歷史窗口，不以稽核當下時間誤判舊evidence。三條failure injections修後在零新增
publisher read、零authority acquire下fail closed；相鄰authority suites
**44 passed**，`py_compile`與diff gate通過，Ruff未安裝。Production只讀preflight
`freshness-window-preflight-20260726-103436` exact read-back
publisher=`operations_core/8`、fingerprint=`6652d01267d664d621c957b8`及implementation
`4feea2fb05dc0db72eedc92afe13f665586e4e5148a64c120d12454cd707e809`，沒有authority
acquire或provider call。本freshness-window根因為
**`root_cause_fixed_and_verified`**；第二台實體Mac仍離線，physical pair與
operations-core umbrella維持 **`contained`**。

### 2026-07-26 — Standby只在role入口驗freshness，過期後仍可重試acquire

**證據化症狀與根因層級**：paired readiness v3已帶15分鐘`valid_until`，但standby只在
進入role時呼叫active-window validator。Primary lease尚未到期時，standby會在最長五
分鐘RTO內重試；因此pair可在第一次「already held」後過期，舊loop仍繼續呼叫remote
authority acquire。根因是temporal fence只放在function入口，沒有包住真正可能成功的
每個mutation boundary，不是Primary Authority CAS。

**底層修復、回歸與live狀態**：standby現在於每一次`standby.start()`前重新驗同一
readiness窗口；failure injection讓第一次acquire被既有primary拒絕、隨後把wall clock
推過`valid_until`，第二次嘗試前即以`readiness receipt expired`停止，store
`acquire_attempts`維持1。相鄰authority suites **45 passed**，`py_compile`與diff gate
通過。Production只讀preflight
`retry-freshness-preflight-20260726-1111`已原子落檔並exact read-back
publisher=`operations_core/8`、fingerprint=`6652d01267d664d621c957b8`及implementation
`44b9c4059dd4ad35da8a0c5574e2ebadb38c04d81942c1e8c41369127273cbdc`；沒有authority
acquire、effect或provider call。本retry-window根因為
**`root_cause_fixed_and_verified`**；第二台實體Mac仍離線，physical pair與
operations-core umbrella維持 **`contained`**。

### 2026-07-26 — Cross-host readiness沒綁backend，clone DB可形成假綠pair

**證據化症狀與根因層級**：兩份host readiness只比較machine、source、isolated key及
publisher fence。Failure injection讓primary與standby分別連到兩個backend，但兩邊都
回`operations_core/8`；舊pairing沒有任何backend欄位可拒絕。兩個獨立DB的authority
epoch若碰巧相鄰，final receipt即可假稱physical failover成功。根因是Supabase backend
identity沒有跨越RPC port與evidence artifacts，不是Primary Authority CAS。

**底層修復、回歸與live狀態**：Service Role RPC base URL現只以SHA-256暴露backend
identity；host readiness／pair／primary／standby／final schema依序升
v2／v4／v3／v4／v4。Pair要求兩份raw artifacts的backend digest exact match，role在
首次publisher read／authority acquire前再驗本機adapter，final verifier重驗整條chain。
不同backend但相同fence，以及pair後role換backend的failure injections均fail closed；
後者零publisher read、零authority acquire。相鄰 suites **48 passed**，compile與diff
gate通過。Production只讀preflight `backend-binding-clean-20260726-1158`已由合併後
乾淨commit worktree原子落檔
並exact read-back backend=`c6a1e836…a1404`、publisher=`operations_core/8`、
fingerprint=`6652d01267d664d621c957b8`及implementation=`aacc1959…dd8c`；沒有authority
acquire、effect或provider call。本backend false-green根因為
**`root_cause_fixed_and_verified`**；第二台實體Mac仍離線，physical pair與
operations-core umbrella維持 **`contained`**。

### 2026-07-26 — Cross-host receipt回讀成功但rename沒有directory durability

**證據化症狀與根因層級**：`_write_receipt()`原本先fsync temporary file，再
`os.replace()`並exact read-back；failure injection記錄實際fsync target只得到
`[regular-file]`。因此process可回報receipt已保存，但host在rename metadata落盤前
重啟時，final pathname仍不具durable保證。根因是filesystem transaction少了rename
後的directory commit，不是JSON payload或receipt hash錯誤。

**底層修復、回歸與制度化**：receipt persistence seam現在於replace後開啟實際父目錄、
fsync該directory descriptor，關閉descriptor後才做exact read-back與回報成功；任何
directory open／fsync失敗都會fail closed。介面回歸保留真實filesystem call並驗證
fsync順序精確為`[regular-file, directory]`；修前RED、修後GREEN。Outage與Primary
Authority相鄰 suites **49 passed**，`py_compile`與diff gate通過。這個receipt
durability缺口為 **`root_cause_fixed_and_verified`**；第二台實體Mac仍離線，尚未
產生physical paired receipt，所以program commit 34與operations-core umbrella維持
**`contained`**。

### 2026-07-26 — Work owner CAS 可繞 gate、expired lease 阻擋 rollback、nested caller 斷鏈

**證據化症狀**：Issue #9 第一版 owner migration 的 Matt Spec／Standards 雙軸審查
均 FAIL。`transfer_work_owner()` 只驗 64-hex，卻直接授權 approver 執行；測試用
`"a" * 64` 即可切換 owner。Transfer 也把所有 claimed／running row 當 active，
不看 DB-clock expiry；crashed worker 可永久擋 rollback。最後，legacy signature
wrapper 固定 assert `legacy`，但既有 notification／publisher／commit stored
procedures 仍呼叫該 signature，owner 一切到 operations_core 就會中斷正式 workflow。

**根因層級與底層修復**：三者都是 ownership transaction 契約缺口。Durable
preflight gate row 尚未存在前，private transfer 現在不授權 worker、approver 或
PUBLIC；任意 manifest hash 無法從 runtime claim owner。CAS 交易依 database clock
原子回收 expired claimed／running lease，保留 work id、增加 version、清 token 並寫
release event；有效或無 expiry lease 仍 fail closed。Legacy runtime mutation grants
在取得 owner row 前撤銷、rollback 時同交易恢復；legacy wrapper 仍明確 assert
`legacy`，所以已過 ACL 檢查但排隊中的 invocation 也不能越過 cutover。九個既有
formal workflow 由白名單、count-checked migration 明確 rebind 到 definer-only
internal seams；runtime roles 對 internal seams 無 execute 權限。

**回歸與回讀**：claimed／running expiry cases 先 RED 後 GREEN，驗證 rollback 後
identity、version、token clearing 與 event；ACL test 回讀 approver 無 transfer 權限，
generation lifecycle 驗證 legacy grant 在 rollback 後恢復。Barrier concurrency
regression 讓 transfer 先排 exclusive owner lock、已通過 ACL 的 legacy invocation
後排 shared lock；transfer 得鎖後舊 invocation 重新核對 owner 並 fail closed，未留下
WorkItem。PG17 full migration chain 以 non-superuser executor replay，formal caller
catalog read-back確認七個 fixture／九個 production caller topology只能改走 internal
seam；owned-email transaction另在 Work Coordinator operations_core generation 下
完成 request／delivery／rollback。最終以外部模型金鑰 unset 且
`VOLPRED_CI_PARITY=0`（排除只針對本機 untracked checkout 的稽核）重跑 repository
full suite：**5,156 passed、1 skipped、0 failed**。

**狀態**：owner fencing、expired-lease reconciliation 與 in-flight legacy race
三個根因在 local schema／tests 層為 **`root_cause_fixed_and_verified`**。但本
checkpoint 仍未把七日 preflight manifest持久化成可消耗 gate row，所以 formal
transfer operator刻意不可用；migration未部署production、沒有live unique-owner
read-back或rollback rehearsal。Issue #9 整體維持 **`contained`**，不得把 local
CAS schema稱為完成 cutover。

### 2026-07-26 — Work owner transfer 只綁 hash、沒有 durable evidence freshness／一次性消耗

**證據化症狀與根因層級**：前一切片先撤銷 runtime transfer 權限，已阻止 worker／
approver 用任意 64-hex 接管，但 migration-owner 仍只能把裸 hash 傳進 CAS；資料庫
沒有 manifest bytes、freshness、來源 generation 或 consumed state，因而無法證明
一次 owner transfer 真正對應哪份七日 preflight evidence。這是 ownership transaction
缺少 durable authorization object，不是 ACL 或文字說明問題。

**底層修復**：preflight manifest 升為 v3，由同一 trusted clock 綁定
`prepared_at` 與精確 15 分鐘 `valid_until`，並公開 deterministic canonical bytes。
新 migration 以 private FORCE-RLS gate table 保存 exact bytes、來源 owner／generation
與 `ready → consumed → rolled_back` 狀態，append-only receipts 保存三個轉移事件。
Stage function 在 DB 端重算 SHA-256，驗證 exact top-level contract、production
projection schema、row-count parity、所有 evidence digests 與 freshness，再以 owner
shared lock做 source-generation CAS，並在 lock 返回後、INSERT 前重驗 expiry。
Timestamp contract 強制 `Z` 或明確 UTC offset；
naive wall-clock 不再交由 session `TimeZone` 解讀成不同 instant。正式 transfer wrapper
先鎖 gate，只有未過期
`ready` 可 cutover；owner CAS 成功後同交易標 `consumed`。首次實作只在進入底層
CAS 前檢查 expiry，owner-row lock 若等待到 `valid_until` 之後仍可能成功，形成
freshness TOCTOU。Owner-row BEFORE UPDATE trigger 現在把 freshness fence 放在真正
mutation boundary；wrapper 也會在底層 CAS 返回、consume 前以 database clock 再檢查。
等待期間過期就 raise，讓 owner、legacy ACL、owner receipts、lease
reconciliation 與 gate mutation 全部隨 transaction rollback。Rollback 僅接受該 gate
保存的 consumed generation，同交易標 `rolled_back`。未 staged hash、stale manifest、
衝突 replay 全部 fail closed；ungated primitive 與 stage／transfer 對 runtime roles
維持不可執行。

**回歸、回讀與狀態**：TDD 先以 manifest v3／freshness expectation 得到 RED，再完成
GREEN；local PG17 contracts 回讀 unknown hash 與 stale manifest 不留 gate／owner
mutation、exact stage／transfer replay 只各寫一筆 receipt、cutover 與 rollback durable
state，以及 worker／approver 對 gate tables、stage、ungated transfer 都無權限。Owner
lock race regression 另在 gate 尚有效時開始 transfer，持鎖跨過 expiry 後才放行；修前
實際錯誤切換 owner，修後回讀 owner 仍為 `legacy/1`、gate 仍為 `ready`，且 receipts
只有 `staged`。Owned-email nested workflow 也在新 gate 後完成 operations_core
generation 流程。另以 `Pacific/Honolulu`／`Asia/Tokyo` 兩個 session timezone 回歸：
naive timestamp 均在 stage 前拒絕，帶 offset 的同一 manifest 則解析成同一 UTC instant。
另一個 barrier case 讓 stage 等 owner lock 跨過 expiry，修前會落 stale gate，修後
回讀 gate 與 gate receipt 均為零。
此 local evidence-bound gate 根因為 **`root_cause_fixed_and_verified`**；但 migration
尚未部署 production、七日真實 receipts 尚未累積，也未做 live cutover／rollback
rehearsal，所以 Issue #9 整體仍為 **`contained`**。

### 2026-07-26 — Work owner durable gate 已部署，live owner 刻意維持 legacy/1

**部署範圍與安全界線**：Production 依序套用
`20260726061130 operations_core_work_ownership` 與
`20260726061244 operations_core_work_cutover_gate`。本輪只部署 owner fencing 與
evidence gate schema；沒有產生 preflight manifest、沒有 stage gate、沒有呼叫
transfer。Catalog 回讀確認 owner／receipt／gate／gate receipt 四表均 FORCE RLS，
owner-row gate trigger 已啟用；stage、gate read、gated transfer 與 ungated primitive
全由 no-login definer 持有、固定 search path，PUBLIC、worker、approver 與 deployment
role 均無 EXECUTE。九個既有 formal callers 全部回讀為 definer-only internal seam。

**Live 回讀與回歸**：PostgreSQL table statistics 顯示 owner row／receipt 各只有
migration 建立的 1 insert、0 update，gate／gate receipt 都是 0，因此 live owner
仍是初始 `legacy/1`，沒有任何 ownership mutation。四個 Work Coordinator／cutover／
ownership suites **96 passed**。Supabase security advisor 對本 scope 無 finding；
performance advisor 只有剛建立、尚無 workload 的
`work_owner_receipts_capability_changed_idx` unused-index INFO，不在零使用樣本下誤刪。
Production schema deployment 與 ACL/catalog read-back 已完成，但七日真實 receipts、
正式 unique-owner downstream read-back 及 rollback rehearsal 仍缺，故 Issue #9 與
operations-core umbrella 維持 **`contained`**。

### 2026-07-26 — Work shadow 能 replay 但沒有 producer；release 留下 started_at 污染 pending lifecycle

**證據化症狀**：Issue #7 已有 pure replay／append seam，Issue #9 也有固定七日
assessment，但 `config/runtime_schedules.json` 沒有任何 Work shadow job，
`storage/ops/work_shadow_observations/` 不存在，故 observation count 一直是 0。
建立 producer 後第一張 live receipt 又抓到 preserved
`assign_f3f36d75` 已由 stale cleanup 從 `in_progress` 回到 `pending`，卻仍保留
`started_at`；Coordinator 因 `unclaimed status carries active claim trace` fail
closed。直接把全部 99 筆 TaskRecord 與 11 筆 terminal ops_jobs 歷史餵入 pending
cutover replay，也把 receipts-only history 誤當 owner migration population。

**根因層級**：第一層是 schedule／actuator 缺口——有 verifier 沒有 evidence
producer。第二層是 task lifecycle mutation 分叉：manual／owner release 走
`_repend_task()`，stale cleanup 另複製一套欄位清理，而兩條都沒有清
`started_at`。第三層是 snapshot scope 混淆：`storage/ops/tasks/` 是 execution
receipts，不是 pending queue，terminal `ops_jobs` 也不是 owner cutover residue。

**底層修復與回讀**：新增 scheduled `observe_work_shadow()` public seam、canonical
Python entrypoint、120 秒 bounded wrapper、single-owner hourly :15 schedule、
wrapper manifest 與 scheduled-writer ownership 分類。Producer 對 next_tasks 用 shared
lock，只納入同 id／parent dependency、TaskRecord 非終態 anomaly及 queued/running
ops_jobs，然後用 Issue #7 同一 immutable replay seam 追加 gitignored receipt；
runtime log 只輸出 bounded summary。Wrapper live smoke exit 0，
`cron_last_run.work_shadow_observe=2026-07-26T06:26:57+00:00`，修正後 receipt
source counts `1/0/0`。Re-pend 現在一律走 `_repend_task()` 並清除 `started_at`，
manual 與 stale cleanup RED→GREEN。既有 preserved row 依「修流程、不手改資料」與
direct-mode owner instruction 未被修改，因此 live assessment 仍有 missing parent／
invalid lifecycle，加上七日 window 與 queued-execution mode 未滿；Issue #9 保持
**`contained`**。相鄰回歸 **161 passed**；全專案
**5,171 passed、1 skipped、0 failed**。

**Matt review 後續根因修正**：初版 scheduled receipt 是 v3，未記錄 observation-time
owner state；assessment 只看評估當下 mode，日後切回 `queued_execution` 可能錯把
direct-mode evidence 算入七日窗口。另 `_record_identity()` 只讀 `id`，與 production
`task_identity(id | task_id)` 契約分叉，會漏掉 `task_id`-only row 的 terminal
TaskRecord／ops-job 對帳。Scheduled producer 現改寫 owner-bound
`work-shadow-replay.v4`，在同一 queue shared lock 內取得 paired owner-state bytes，
receipt 綁定 mode／gate flag／resolved path／SHA-256／byte count。Assessment 只計入
與當下 owner evidence 完全相符的 v4 receipts；舊 v3 為 append-only audit evidence，
不污染也不計入新窗口。Identity scoping 改為直接共用 production `task_identity()`。
因此 producer 已開始運作，但在 live `direct_execution` 下
**cutover-eligible 七日時鐘尚未開始**；必須切至核可的 queued owner state 後重新
連續累積七日。這個 remediation 不改 queue、gate 或 owner。

### 2026-07-26 — Direct-mode restore 帶回 pending claim residue，舊 cleanup 完全跳過

**證據化症狀**：正式 restore 3338 筆備份後，canonical queue 有 5 筆
`status=pending` 卻仍帶 `claimed_by`／`claimed_at`／`claim_session_id`／`started_at`
之一；其中 `assign_580c1b3e` 保留舊 hourly worker 的完整 claim trace。原本
`cleanup --stale-hours 2` 回報 0 release，因為只掃 `claimed`／`in_progress`，這些
矛盾 row 會永久避開 stale reaper，並可能被 claim eligibility fail closed。

**根因層級與底層修復**：restore 正確保留備份原貌，但 task lifecycle cleanup 把
「status 是 pending」誤當成「claim trace 必定乾淨」，缺少歷史 schema／備份回復後的
正規化 seam。`task_pool_claim.py cleanup` 現在先辨識 pending claim residue，經既有
`_repend_task()` 單一 mutation site 清除四個 active trace 欄位，並留下
`pending→pending`、`normalize_pending_claim_residue` audit history。若 row 綁定仍在
執行的 compute job 則 fail closed 跳過，避免清 metadata 後被重複派工；正常 pending
row 不變。輸出另列 `normalized_pending_claim_residue`／`normalized_count`，不混入
既有 stale `released` 計數。

**回歸與 live 回讀**：TDD 先得到 3 個 RED，再以 residue normalize、live compute
skip、clean pending no-op 三案轉 GREEN；cleanup suite 6 passed。正式 cleanup 回報
`normalized_count=5`、`released=0`、`skipped_compute_in_flight=0`，回讀五筆均已清除
active trace、保留 normalization history，整池 `pending_claim_residue=0`。根因已
**`root_cause_fixed_and_verified`**；未手改 `storage/next_tasks.json`。

### 2026-07-26 — 測試 guard 未包住 owned-email RPC，三筆 WorkItem 誤寫 production

**證據化症狀**：full suite 執行後，production 在 06:34–06:35 UTC 新增三筆
`source=ops.alerts.send_alert`、`kind=ops.alert.email` 的 WorkItem。三筆事件都只有
`submitted → acquired → started`，沒有 Work receipt；lease 約五分鐘後過期。
當時 live owner 仍為 `legacy/1`，cutover gate／gate receipt 仍為 0，因此這不是新版
owner 正式流量。精確 regression 在 `VOLPRED_NO_REMOTE_WRITE=1` 下替換
`urllib.request.urlopen`；修正前仍呼叫 network，得到 RED。

**根因層級與底層修復**：這是 remote-write safety boundary 缺口。
`SupabaseOwnedEmailStore` 直接使用 `urllib`，未經 repo 其他 publisher 的 guard。
共同 `_rpc` boundary 現在把唯一 read-only function
`volpred_read_notification_owner` 與 mutation functions 明確分離；任何 mutation 在
`VOLPRED_NO_REMOTE_WRITE=1` 時都於建立／送出 HTTP request 前 fail closed。現有三筆
production rows 不手改、不刪除，保留作 incident audit evidence。

**相鄰 evidence 修正**：Matt Standards re-review 同時發現 Work shadow observer
自建 active-status set 漏掉 canonical `blocked` TaskRecord。Observer 已改為直接共用
`local_control_plane.NONTERMINAL_TASK_STATUSES`，並以五種 canonical nonterminal state
的 public-seam regression 鎖定，避免七日 cutover ledger被靜默美化。

**回歸與 production 回讀**：修後在 service-role key unset、
`VOLPRED_NO_REMOTE_WRITE=1` 下重跑 full suite，**5,177 passed、1 skipped、0 failed**。
以事故最後一筆 `2026-07-26T06:35:28.127882Z` 為 cutoff 回讀，測試形狀
`Claude→Codex failover 接手失敗%` 新增數為 **0**。同窗口另有三筆 07:01 UTC
正式巡檢告警，均可在 `storage/ops/incident_candidates.jsonl` 對到同 timestamp／
dedupe key，且 production WorkItem 全為 `succeeded`、version 4、各有一筆 durable
Work receipt；它們是新版 owned-email runtime 的真實健康流量，不是測試洩漏。

**Failover 最終重驗與狀態**：在包含 pytest guard-removal regression 與 read-only
owner RPC regression 的 immutable HEAD 上，再以外部模型金鑰 unset、
`VOLPRED_CI_PARITY=0` 跑完整 repository suite，結果為
**5,182 passed、1 skipped、0 failed**。Production 在 suite 前
`2026-07-26T07:15:03.344446Z` 的同一 `source/kind` 基準為 6 筆、最新
`created_at=07:01:49.8944Z`；12 分鐘後 `07:27:46.537877Z` 回讀仍精確為 6 筆、
相同最新時間，基準後新增列為 **0**。因此 remote-write guard 根因為
**`root_cause_fixed_and_verified`**。原三筆 test-shaped running rows不手改、不刪除，
保留 audit evidence；Issue #9 的 Work Coordinator queue owner 仍是 `legacy/1`、
gate／gate receipt 都是 0，所以 Issue #9 整體仍為 **`contained`**。

另以未關閉 CI-parity 的標準 `uv run pytest -q` 重跑，功能測試為
**5,183 passed、1 skipped、0 test failure**；exit 1 僅是 post-hook 發現 live checkout
讀到未追蹤 `.claude/worktrees`／ops receipts。Production 在
`07:16:50.782473Z → 07:29:50.790468Z` 回讀仍為 136 筆、最新仍是
`07:01:49.8944Z`，baseline 後新增 **0**；不以 post-hook 紅燈掩蓋功能結果，也不把它
誤報成全套綠燈。

### 2026-07-26 — Work-shadow owner mismatch 被過濾可隱藏 A→B→A；assessor 允許部分 owner evidence

**證據化症狀**：Matt 第三輪 Spec review 發現 assessor 先丟棄 owner evidence 不符的
v4 receipts，再計算 window／gap。若 owner A 連跑、短暫切到 B、又以同 bytes 回 A，
B receipt 會消失，剩餘 A timeline 只形成小於 26h 的 gap，可能錯過「連續七日無
simultaneous owner」要求。Standards review 同時發現 public assessor 的 gate／state
path／state SHA 都有 `None` default；只傳 mode 也能在測試中回 ready，與 canonical
文件宣稱的完整 match 不一致。

**根因與修正**：這是 assessment state-model／interface contract 缺口。Public seam
現在只接受單一必填 `TaskPoolModeEvidence`，mode／enabled／resolved path／SHA／byte
count 全部逐欄 match，partial caller 直接 TypeError。所有 owner-bound v4 receipts
先依 append `recorded_at` 排序；最後一張 mismatch 是新的 epoch boundary，assessment
只從其後連續同 owner generation 起算。v3 仍為 audit-only，不形成 boundary。

**回歸**：A→B→A 精確 regression 在舊版錯誤回 `ready=true`／count 8；修後回
`observation_window_too_short`／count 5，`recorded_from` 從 B 後第一張 A receipt
開始。mode-only API regression 由未拋錯轉為 TypeError。Shadow assessment＋cutover
preflight **45 passed**，最終 Matt Standards／Spec 雙軸複審皆 **PASS**；Issue #9
仍為 **`contained`**。

### 2026-07-26 — Owned-email begin 後程序中斷，過期 attempt 沒有 recovery actuator

**證據化症狀**：production 在 `2026-07-26T07:40:39Z` 回讀 owner
`operations_core/4`，owned-email 已有 118 次 delivered，但另有 22 筆
`owned_notification_attempts.status=started`；對應 WorkItem=`running`、
outbox=`claimed`、EffectRequest=`requested`，三層 lease 全部過期。最近 24 小時新增
13 筆、最近兩小時新增 5 筆，故不是單一事故或只需補資料的歷史殘留。

**根因層級**：`volpred_begin_owned_email_notification` 本來就能重新取得過期
WorkItem/outbox；provider adapter 也會把 SMTP／IMAP exception 轉成 retryable
`FailedEffect`。真正缺口是程序若在 begin 後、settle 前 crash，repo 沒有任何 reader、
worker 或 schedule 會列出並回收過期 attempt。這是 actuator／schedule contract 缺失，
不是資料庫 reacquire、provider exception mapping 或 ACL 故障。

**底層修復**：新增 service-role-only 原子 recovery RPC，以
`FOR UPDATE SKIP LOCKED` 選最舊過期 attempt，重用 canonical begin 完成新 lease／
authority fencing，原子關閉舊 attempt，並寫入 private FORCE-RLS append-only
recovery receipt。Python 公開 seam `OwnedEmailRecovery.recover(limit)` 對一小時內
alert 先用 deterministic Message-ID 做 Sent Mail exact read-back／必要補送；超過一小時
以 terminal `owned_email_recovery_stale` 結案，避免大量補寄失去時效的告警。
`config/runtime_schedules.json` 與同步 wrapper 建立每小時單一 piggy-back actuator。

**Matt review 更正**：初版仍讓 ordinary
`volpred_begin_owned_email_notification` 直接重領過期 WorkItem/outbox。若 ordinary
begin 先於 recovery，outbox attempt count 會前進，但 predecessor 不會關閉；後續
settlement 又讓 recovery selector 永遠無法再選到舊 row。ordinary-first PG17
regression 在初版實際「沒有拋錯」而 RED，證明不能宣稱同類錯誤已被制度化封死。
Follow-up migration 現強制任何看見 `started` predecessor 的普通 begin fail closed；
只有 recovery transaction 能先關閉 predecessor、寫 receipt，再呼叫 canonical begin。
Python delivery/recovery 的 owner、lease、token 與 Primary Authority 驗證也收斂到同一
execution context。

**回歸與 live 回讀**：PG17 先以「attempt 1 crash → 三層 lease 過期 → recovery
attempt 2」得到 UndefinedFunction RED，再驗 old attempt、new attempt、receipt、RLS、
owner、ACL 與 search path 全部 GREEN。Python 回歸涵蓋近期補送與 stale 不呼叫 provider。
Production migration 套用後首跑回收 22/22：21 stale dead-letter、1 exact Sent read-back
delivered；回讀 `expired_started=0`、`active_started=0`、22/22 recovery receipts、
22/22 WorkItem 與 outbox terminal。相同 wrapper 第二次執行
`recovered_count=0`，證明 idempotent。ordinary-first RED 經 follow-up migration
轉 GREEN，且 read-back 確認 failed ordinary begin 未新增 attempt、未增加 outbox count、
未改 WorkItem。Final Matt Standards／Spec 均 PASS；production receipt
`20260726081120 fence_owned_email_expired_retry` 套用後，catalog 回讀 begin gate
存在、recovery 的 predecessor UPDATE 先於 nested begin，兩個 functions 都是
no-login definer owner／SECURITY DEFINER／空 search path／service-role-only。
資料回讀仍為 `started_total=0`、`expired_started=0`、22 receipts、
21 dead-lettered + 1 delivered、0 nonterminal。16:00 台灣時間的第一個自動
piggy-back fire 另以 `recovered_count=0` exit 0 並寫回 cron marker。Post-fix
全專案功能回歸（外部模型 key unset、`VOLPRED_CI_PARITY=0`）為
**5,191 passed、1 skipped、0 failed**；標準 CI-parity-on 相鄰套件另為
**111 passed、exit 0**。此 incident 現已完成五步 gate，狀態為
**`root_cause_fixed_and_verified`**。

**Due retry follow-up**：只查 attempt status 的初版驗證把其他 effect family 的
`retry_scheduled` 混進 email 數字；按 `owned_notification_requests.effect_family`
重算後，email 自身仍有 1 筆 `WorkItem pending + outbox pending` 且早已超過
`available_at`。這證明「settlement 寫出 retry」不等於「有人會消費 retry」。
Recovery RPC 現同時原子選取 expired `started` 或 due `retry_scheduled`；後者不改寫
原 provider settlement evidence，另追加 `retry_due_without_actuator` recovery receipt。
初版 selector 只綁 owner generation，但 generation 是 per-family counter，不是跨 family
authority boundary；same-generation cross-family RED fixture 證實 email worker 可誤領
別的 family。Forward migration
`20260726083559_fence_owned_email_recovery_family` 將 request effect family 納入
SQL selector；production 實際另以
`20260726083856_fence_owned_email_recovery_family` 加入 effect kind。兩筆 ledger
stored statement bytes 已各自保存到同版號 repo migration，避免事後合併改寫
已套用 migration。Production catalog 回讀
`explicit_family_fence=true`，且原有 9 筆 publisher／delete due retry 數量不變。
Follow-up 首跑將唯一 email due retry stale dead-letter；exact-family 回讀
`expired_started=0`、`due_retry=0`、`nonterminal=0`、recovery receipts=23，第二次
wrapper no-op。此 actuator 缺口同樣為 **`root_cause_fixed_and_verified`**。

### 2026-07-26 — Publisher sync durable retry 沒有 actuator，缺省 tags 又造成永久 mismatch

**證據化症狀**：owned-email recovery 完成後，production exact-family query 仍有
3 筆 `publisher.article.supabase.sync` 的 `WorkItem=pending`、
`EffectRequest=requested`、`outbox=pending` 與最新 attempt=`retry_scheduled`；
`available_at` 均已過期約兩天，owner 仍是匹配的 `operations_core/8`。另 6 筆
publisher delete retry 屬舊 owner generation，故不能混入本 actuator。

**根因層級**：sync settlement 能寫 durable backoff，但沒有 reader／schedule 會消費
due retry，process 在 begin 後中斷也沒有唯一 supersede seam。首輪 actuator 另以真實
payload 抓到第二個 contract bug：payload 未帶 `tags` 時，writer 正確保留既有 tag
links，readback 卻把缺欄位解讀成「期望空 tags」，因此寫後永遠
`publisher_article_sync_readback_mismatch`。這是 actuator 與 projection contract
語義不一致，不是資料錯誤。

**底層修復**：production migration
`20260726093801 operations_core_owned_publisher_article_recovery` 新增
service-role-only recovery RPC。它以 `FOR UPDATE SKIP LOCKED` 原子選取 exact family、
exact effect kind、current owner generation 的 expired `started` 或 due
`retry_scheduled`，保存既有 provider evidence、追加 private FORCE-RLS immutable
receipt，再走 canonical begin。普通 begin 遇到尚無 recovery receipt 的
`started/retry_scheduled` predecessor 會在任何 Work/outbox mutation 前 fail closed。
Python delivery／recovery 共用 owner、token 與 Primary Authority execution context。
Projection readback 現在只在 payload 明確帶 `tags` 時比較 tags；缺欄位與 writer
同義為「不在本次 mutation scope」，明確 `tags: []` 仍會清空並精確驗證；
present `tags` 必須是 `list[str]`，`null`／object 會在 immutable payload decode
階段 fail closed，不能用第二種表示法繞過 destructive-clear 契約。

Matt Standards review 另抓到 recovery RPC 原先未承接 repo-wide
`VOLPRED_NO_REMOTE_WRITE` 邊界。共用 `ServiceRoleRpcClient` 現以 explicit
read-only RPC allowlist 分流，其他 function 在 remote-write guard 或 pytest runtime
都於建立 HTTP request 前 fail closed。需要驗證 transport／decoder 的測試必須明確
opt in `mocked_operations_core_rpc_transport`；fixture 先把真實 transport 換成必定
失敗的 sentinel，未再注入 fake 就不可能碰網路，不能以關閉 guard 當測試 workaround。

**回歸、live readback 與制度化**：PG17 migration chain、ordinary-first 零 mutation、
due retry、ACL／RLS／search-path 與相鄰 caller／schedule suites共 96 passed；tags
缺省、`tags:null` 與 remote-write guard 都先取得 RED，再於含 shared RPC clients 的
相鄰 suite **165 passed**。Production 首輪 3 recovery 中 2
delivered、1 暴露上述 tags mismatch；修 contract 後該筆 attempt 3 delivered，
再跑為零 mutation no-op。最終 DB 回讀未被 receipt 消費的
`sync_due_retry=0`、`sync_started=0`、4 recovery receipts，ordinary begin fence
存在；歷史 retry predecessor 仍原樣保留作 audit，不冒充 current work；6 筆 delete
old-generation retry 未變。Canonical `owned_publisher_article_recovery` 每小時由
`check_alerts → run_due_jobs` 單一 piggy-back owner 執行，wrapper 已原子同步至
`~/.volpred/bin`，最小 cron environment smoke 為 no-op exit 0。此 publisher-sync
incident 完成五步 gate，狀態為 **`root_cause_fixed_and_verified`**；publisher delete
stale-generation reconciliation 與 Issue #9／Work Coordinator umbrella 仍為
**`contained`**。

### 2026-07-26 — Operations Core scheduler 已上線，但 writer policy 沒有它的正式身份

**證據化症狀**：publisher recovery 完整 suite 的唯一 failure 是
`test_launchagent_population_is_registered_when_available`；canonical
`ops/launchd/com.volpred.operations-core-scheduler.plist` 已存在且 live LaunchAgent
正在執行，但 `config/scheduled_writer_ownership.json` 沒有同 label。補第一筆後，
population ratchet 又指出新 `event_jobs_materialize` process 未分類，證明這不是單一
測試字串，而是 scheduler cutover 新增兩個 runtime identities 時漏了 canonical
writer inventory。

**根因與底層修復**：`schedule_materialization` 只有 daemon label／plist，沒有正式
`job_id`；policy population 又只枚舉 `system_crontab.items`、`cron_jobs`、`daemons`，
所以若直接新增 policy row 會被反判為 stale。Canonical runtime config 現明確宣告
`job_id=operations_core_scheduler`，population ratchet 同步把這個身份視為 runtime
process。writer policy 將 scheduler 定義為 `no_repo_tracked_output`：它只寫
gitignored receipt／lock／log，實際 materialized job 仍各自保留 writer policy。
`event_jobs_materialize` 則正式歸入 `phase_z_machine_state`，exact outputs 是
`storage/next_tasks.json` 與 `storage/ops/event_ledger/**`。

**回歸、live readback 與制度化**：兩個政策測試先 RED，修後完整 policy suite
**17 passed**，scheduler/runtime/reconcile/wrapper 相鄰 suite **71 passed**。
`launchctl print` 回讀 daemon `state=running`、active count 1；canonical validator
回報 `ok=true`、47 jobs、5 個 operations-core canary owners。唯讀 owner reconcile
仍回報 `audit_publish_sync`、`feed_sync` 的 legacy host-crontab conflicts；本輪沒有
為追求綠燈直接 apply ownership mutation。故「scheduler writer-policy 身份缺漏」
完成五步，狀態 **`root_cause_fixed_and_verified`**；Issue #9 queue/schedule cutover
仍因這兩個 live simultaneous-owner conflict 保持 **`contained`**。

### 2026-07-26 — Publisher-delete rollback 後的舊世代 retry 沒有合法終止路徑

**證據化症狀**：production owner 已是 `legacy/19`，但六次 destructive restore
rehearsal 留下 generation 6/8/10/12/14/16 的 `retry_scheduled`。六筆 WorkItem、
EffectRequest、outbox 分別仍是 `pending/requested/pending`，六個 approval 卻都
`active=false` 且已有 `revoked_at`；原 immutable attempt receipt 均是
`retryable_failure/retry_scheduled`。重試它們會跨 owner generation 且使用已撤銷
授權，直接改狀態或覆寫原 receipt 又會破壞 audit chain。

**根因層級與底層修復**：既有 settlement 只接受 current
`operations_core/generation` 與 active leases，rollback 後沒有專門的
stale-generation terminalization state transition。新增 migration
`20260726103201_reconcile_stale_owned_publisher_delete`：service-role-only、
`SECURITY DEFINER`、空 search path 的 RPC 僅選 exact delete family/kind、
attempt/request 同一舊 generation、current generation 較新、approval 已撤銷、
原 retry receipt 存在、work/effect/outbox 仍為精確 nonterminal lifecycle 的列。
它以 `FOR UPDATE OF attempt SKIP LOCKED` 領取，保留原 attempt/attempt receipt，
另寫 private FORCE-RLS immutable reconciliation receipt，再把三層 parent state
dead-letter。Python 公開 seam 不接受 provider factory、Primary Authority 或
delete projection，因此這條路徑在介面上即無法刪 article。

**回歸、production 回讀與制度化**：Python seam/store 與 PostgreSQL 真交易都先
RED 後 GREEN；PG 測試另驗證第二次執行零筆且原 retry receipt 未改。Production
migration 上線後一次收斂六筆，回讀 `receipt_count=6`、
`fully_converged=6`、`approvals_still_revoked=6`、`work_receipts=6`，隨即重跑
`reconciled_count=0`。既有 hourly publisher recovery 入口升級為 v2，每輪先執行
零-provider reconciliation；production smoke 為 delete=0、sync=0。五步 gate
全部完成，狀態 **`root_cause_fixed_and_verified`**。

**Matt review remediation**：首次複審判定 selector 雖逐表檢查狀態，卻未證明
`owned_request.work_id`、`effect.work_item_id`、`message.effect_id` 與
`attempt_receipt.outbox_sequence` 都屬同一 request chain；各自 FK 不能取代 composite
identity。另有 RPC decoder 未驗證 generation 單調性／固定 reason，以及 canonical
schedule metadata 仍宣稱 sync-only。負向 PostgreSQL 測試把 request work_id
cross-link 到另一個合法 WorkItem，修前確實錯誤收斂 1 筆；forward migration
`20260726104730_fence_publisher_delete_reconciliation_identity` 補全 request SHA、
work/effect/outbox/receipt/worker/evidence/lifecycle identity 後變成零 mutation。
decoder 與 metadata ratchet 同步補齊。Production `pg_get_functiondef` 回讀
request-work、outbox-effect、receipt-outbox fences 均存在，replay count 仍為 0。

## 2026-07-26 — Business schedule 有三套 owner，session cron 又把已退役 queue 當控制面

**證據化症狀**：cutover 前同一份 `runtime_schedules.json` 同時由 host crontab、
per-job LaunchAgent 與 `check_alerts → run_due_jobs` piggy-back 解讀；
`feed_sync`／`audit_publish_sync` 曾被 owner audit 證實 simultaneous owner。
另有七條 session-local `CronCreate` 在 session 關閉時只累積
`pending_sessions.json`，NDC freshness 已落後至 expected `2026M05`，卻沒有可靠
executor。新 NDC materializer 首輪又嘗試新增 legacy next_tasks id，被正式
`TaskPoolAdmissionClosed` guard 擋下；queue bytes 未受污染。

**根因層級**：canonical schedule spec 只有「何時跑」，沒有可機械執行的單一 owner
generation；host installer、launchd installer、piggy-back 與互動 session 各自推論
ownership。NDC follow-up 同時違反 `direct_execution` 期間 GitHub Issues 才是唯一新
工作登記面的契約。這是 schedule/control-plane architecture 缺陷，不是補 cron marker
或手改 pending JSON 能解。

**底層修復**：Operations Core scheduler 現以 generation、immutable fire key、
activation boundary、fenced lease、retry／timeout、catch-up policy 與 terminal
receipt 擁有 business clock。`cron_owner_gate.py`／`cron_lib.sh` 在 wrapper effect
前 fail closed；reconciler 原子安裝核心 daemon、移除 legacy host／launchd surfaces
並回讀。2026-07-26 18:38 台灣時間正式改為 active：49/49 executable jobs 由
Operations Core 擁有，VolPred host crontab entries=0，legacy per-job LaunchAgents=0。
session crons 以 `items=[] / status=retired` 制度化退役；knowledge index 另建真正的
六小時 executable wrapper。NDC 在 queue admission 關閉時改為 exit 1 並留下 scheduler
failure evidence，實際資料工作登記為 GitHub Issue #38，禁止繞過 gate 或假綠。

**回歸與 live 回讀**：scheduler／runtime／owner／wrapper／liveness focused suites
持續通過；wrapper manifest 已同步 live copy。owner audit 回報
`owner_surfaces_verified`、49 core／0 legacy、conflicts=[]、
dormant_legacy_surfaces=[]。active boundary 後第一個自然 fire
`event_jobs_materialize@2026-07-26T10:40:00Z` 於 10:40:18Z 啟動、attempt 1 exit 0，
且重複 tick 未產生第二個 identity；18:30 的回歸 fire 亦證明修正後不再提前跨分鐘。

「三套 schedule owner 與 session recorder 假控制面」根因已完成五步，狀態
**`root_cause_fixed_and_verified`**。Issue #28 的長窗 sustained-clean 與 Issue #9
Work Coordinator 七日 queue ownership evidence 是不同 gate，仍標
**`contained`**，不得用本次 scheduler 成功冒充完成。

### 2026-07-26 — NDC 月資料排程只會派人工工作，模型額度耗盡時無法更新

**證據化症狀**：`景氣領先指標不含趨勢指數(點)` 停在 `2026M01`，
`景氣對策信號(分)` 停在 `2026M04`，而 freshness gate 已要求 `2026M05`。
舊 `collect_ndc_bci.py` 明知 Angular 頁面不能用 plain GET，仍只印出「請用
Claude / Chrome 手動更新」；Operations Core 的月排程也只嘗試把工作寫進已關閉的
legacy queue，因此 direct-execution guard 正確 exit 1 後，沒有不依賴模型額度的
資料 executor。舊註解另把真正端點誤記成需 reverse-engineer 的 POST body。

**根因層級與底層修復**：這是 data-ingestion／schedule contract 缺陷，不是補 CSV
一列能結案。正式 collector 現由 Playwright 啟動本機 Chrome，從官方頁實際使用的
`/n/json/data/eco/indicators` 回應擷取固定代碼 `SR0051`／`SR0005`；逐次驗證
origin、endpoint、series code/name/unit、期間單調性、數值有限性與 snapshot
SHA-256。完整官方 current-vintage 先保存為
`storage/macro/ndc_bci_source_latest.json`，再原子 upsert canonical CSV、逐列回讀、
freshness 回讀，最後只對兩個宣告 output 做 path-scoped self-commit。月排程 wrapper
已直接執行 collector，不再產生 agent task，也不消耗 Claude／Codex 額度。

**回歸、live readback 與研究限制**：2026-07-26 官方回應
`source_latest_date=2026-06-26`，領先指標 533 筆（1982M01–2026M05）、
信號 509 筆（1984M01–2026M05）；最新值分別為 `103.81` 與 `39`。同步補回 17 個
缺月並納入官方明載的全歷史回溯修正，CSV 回讀兩條 latest 均為 `2026M05`，
freshness=`true`。snapshot 明確保存官方「每月發布均回溯修正歷史資料」說明；
因此本檔代表 **current vintage**，不可冒充歷史各時點實際可得 vintage。Git 會從
本次開始保存每月 snapshot 版本，但 2026-07-26 以前的 point-in-time vintages
無法由本流程倒推。自動收集／schema drift／hash tamper／atomic upsert 測試與
schedule/writer policy gate 均納入回歸。此「NDC 排程依賴互動模型」incident 五步
完成，狀態 **`root_cause_fixed_and_verified`**。

### 2026-07-26 — Operations Core 上線後，模型派發仍有兩個獨立時鐘

**證據化症狀**：business schedule 已全量切到 Operations Core，但 live process 同時有
`com.volpred.dispatch-supervisor` 自己的 60 秒 scheduler loop 與
`scripts/codex_loop.sh` 的一小時 sleep loop；兩者都能從同一任務來源啟動模型工作。
`git_writer_lock`／task claim 只能降低同時寫壞或同 task 重抓，不能防兩套架構各自挑不同
task、各自改設計。更嚴重的是舊 Codex loop 由 Claude Code SessionStart hook 呼叫
`auto_start_codex_loop.sh`，手動 kill 後重新開 session 仍會復活。

**根因層級與底層修復**：Operations Core cutover 只收斂 `system_crontab` business jobs，
把 dispatch supervisor 當 required daemon 稽核，卻沒有把 daemon 內部 scheduler 也視為
clock surface；SessionStart 自動啟動的 Codex loop 又完全不在 schedule registry。
production supervisor 現改為無時鐘 executor：本機 Unix socket（mode 0600）只接受
Operations Core `agent_dispatch_tick`，每次 trigger 以
`scheduler._tick_once(background=True)` 做 admission，保留 4 slots、health、
Claude→Codex failover、quota derating、worktree isolation 與 PHASE-Z。
`auto_start_codex_loop.sh` 預設改為 retired no-op；明確 rollback env 只有在先停用
canonical tick 後才可使用。

**回歸、live 回讀與制度化**：socket round-trip／非法 request／executor 不存在／production
`_run_async` 無 `scheduler_loop`／SessionStart no-op 均有回歸測試；runtime schedule、
wrapper manifest、writer ownership 與 architecture/ownership 文件同步。live executor
經 planned reload 後 PID 更新、socket 建立，Operations Core 自 19:43 起連續產生
`agent_dispatch_tick` immutable receipts（attempt 1、exit 0），wrapper decision 回讀
`not_due`，dispatch heartbeat 由新 PID 持續更新。owner audit 為 50 core／0 legacy、
0 conflict；process readback 只有 Operations Core 與無時鐘 dispatch executor，
沒有 `codex_loop.sh`。排程 trigger receipt 與模型 completion receipt 分離，所以
Claude／Codex quota 用盡只留下 `quota_blocked`，不會讓純程式排程停止或假綠；下個
合法 hourly/requested tick 在 quota reset 後自然再試。此雙時鐘 incident 五步完成，
狀態 **`root_cause_fixed_and_verified`**。

### 2026-07-26 — Direct-mode preserve receipt 讓正式 restore 永久不可達

**證據化症狀與根因層級**：direct-mode receipt明列
`preserve_task_ids=[assign_f3f36d75]`，`reconcile-direct`也依契約永久保留該control
row；但`restore_task_pool_backup()`只接受完全空的live queue。兩條各自正確的規則
組合後，正式退出在任何合法狀態都不可達。Production backup另含兩筆cutover前的
`in_progress`，原restore會無提示原樣復活；若先移除control row又會遺失direct-mode
期間新增的checkpoint。這是owner transition／evidence boundary契約缺陷，不是手動
清一列即可結案。

**底層修復與回歸**：public restore seam現在只允許live queue包含active receipt明列
的preserved IDs；receipt外、anonymous與duplicate rows在任何archive／state／queue
mutation前fail closed。合法control rows會先以exact bytes寫入backup旁的durable
archive，file與parent directory均fsync並read-back；prepared與final owner receipt
綁定archive path、SHA-256、bytes及row count，crash retry先重算完整identity。Backup
中的`claimed`／`in_progress` IDs也必須由operator透過重複
`--expected-active-task-id`精確確認整個集合，prepared transaction持久保存該確認，
漏列、多列或後續backup漂移都拒絕。

Public function、CLI、receipt外drift、active-set mismatch與prepared archive tamper
failure injection共 **37 passed**；compile與diff check通過。這個「合法狀態永久無法
restore／控制進度可能遺失／舊claim靜默復活」根因完成五步，狀態
**`root_cause_fixed_and_verified`**。Production仍維持direct mode，待live exact
archive、receipt-bound restore、canonical stale cleanup與內容下游acknowledgement
回讀後，才可把上線切換本身標完成。

### 2026-07-26 — 第二台Mac其實在線，但缺remote identity與同質runtime部署

**證據化症狀與根因層級**：先前Tailscale snapshot把候選
`IvanLai的MacBook Pro`標為offline，實際喚醒後ping為31ms；真正阻塞是Mac Studio沒有
SSH identity、MacBook短帳號為`apple`且未授權key。SSH打通後又發現MacBook沒有repo／
`uv`，只有Python 3.9；第一次依`>=3.12`同步還選到3.13.3。若只把「機器開著」當ready，
會在正式mutation後才發現source/runtime不相容。根因是physical deployment／access
precondition缺失，不是authority CAS。

**底層排除與live驗證**：Studio建立專用ED25519 key，MacBook只授權其public key；
透過SSH部署不含Git history、storage、frontend與排程的最小Operations Core checkout，
再以`uv.lock`和顯式`--python 3.12.10`建立同質環境。兩端回讀Python
`3.12.10`、OpenSSL`3.0.16`、implementation
`b83f7bbc6fdee3d82aafebf7f83ed7212e53bffd1351948c8ee2ad3c332e5003`與backend
`c6a1e836…a1404` exact match；不同實體fingerprints為`6652d012…57b8`／
`d9fca0a4…fbde`。

正式rehearsal `operations-core-two-mac-20260726-2000`由Studio取得epoch`1`，
完成一次健康renew後在transport partition下59.220721秒demote、local gate關閉；
MacBook在DB-clock expiry後0.162352秒取得exact-next epoch`2`並release。Final receipt
為`cross_host_verified=true`、successful claims=2、duplicate=0、effect=0、
provider=0，publisher fence始終`operations_core/8`。Canonical evidence為
`storage/ops/primary_authority_outage_cross_host_latest.json`及其readiness／primary／
standby SHA鏈。Physical two-Mac gate與Program commit 15／Operations Core umbrella
完成五步，狀態 **`root_cause_fixed_and_verified`**。

### 2026-07-26 — 只查 Claude home，誤判 Codex 全域 Matt skills 不存在

**證據化症狀與根因層級**：`AGENTS.md` 同一節同時寫著「Matt Pocock skills 已安裝」與
「`ask-matt` 不存在」，後者只檢查 `~/.claude` 就推論所有 runtime 都缺少 skill。
Live 回讀 `$HOME/.agents/skills/` 可見九個必要 manifest，且 `ask-matt/SKILL.md`
明確定義既有多 session tickets 應逐張走 `implement`、內部 `tdd`、最後 `code-review`。
這是 runtime skill-surface 身分混淆與 living-doc verification contract 缺口，不是
Matt workflow 或既有 plan/spec/tickets 遺失。

**底層修復與制度化**：`AGENTS.md` 改記實際全域 surface，並明確區分
`$HOME/.agents/skills/`、`~/.claude` 與 repo 內已退役的 `.agents/skills/`。
新增 `scripts/check_matt_skills_installation.py`，逐一驗證九個必要目錄的 `SKILL.md`
及 frontmatter `name`，缺漏或錯名即 non-zero；living-doc regression 同時禁止舊的
「router 不存在」字句復活，並固定既有 GitHub Issue #3 → master spec → Issues #5~#36
流程。全 repo current-doc 關鍵字稽核沒有找到第二份現行錯誤聲明；archive 與 worktree
歷史物證不回寫。

**回歸與 live readback**：稽核器 complete／missing／wrong-name／CLI JSON 與
`AGENTS.md` contract 共 4 案；另對本機全域 surface 執行 live audit。錯誤資訊的來源、
文件與機械防再犯 owner 均已收斂，狀態 **`root_cause_fixed_and_verified`**。

### 2026-07-26 — Boss Report 新 scheduler 仍接舊 SMTP 與五月 pseudo-living source

**證據化症狀**：20:10 信件的 exact fire receipt 是
`operations-core-v1:boss_report_4h:d75fd5ab20b1875d6ce9ecb4`，證明排程 owner
已是 Operations Core；但 notification `6e1d914c` 仍由
`cron_boss_report.sh → boss_report.py → EmailNotifier` direct SMTP 產生，沒有
WorkItem／EffectRequest／outbox／Sent evidence。畫面中的 cycle 規劃則來自
2026-05-19 的 `current_cycle_intent.json` 與 `ops_team_structure.md`；另有一筆
歷史 `2026-06-09T03:30:z` 被誤列成當期 report warning。owner-surface audit 同時
確認沒有第二個 host cron／LaunchAgent／session cron fire，所以不是雙排程。

**根因層級與底層修復**：T05/#11 已完成 `email.ops_alert` owned transaction，
但 Boss Report caller 未列入 formal caller inventory；報告 program context 又沒有
typed source contract，把手動維護的暫存敘事檔當 living truth。Issue #39 沿用 #3
plan 與 #11 架構補 caller acceptance gap：抽出單一
`dispatch_email_by_current_owner()`，讓 alert 與 Boss Report 共用 owner read、
Primary Authority、provider 與 settlement；schedule fire key 綁 email
idempotency。新 `boss_report_read_model` 只讀 master spec §7 與 current
task-pool mode，辨認 direct／queued 合法狀態；wrapper 在任何 business effect 前
執行 common schedule owner gate。小寫 `z` 只在 reader boundary 正規化，不更動來源 JSON。

**回歸與狀態**：read-model source selection／queued restore／完成列過濾／timestamp、
wrapper gate、Operations Core／legacy／owner-read-failure／terminal replay 均有回歸；
dry render 已確認舊 cycle、舊 action與假 warning 消失。第二輪 standards review
指出本機 immutable payload 不能等同跨主機不重送，後續把共享邊界補到底層：
service-role-only `volpred_read_owned_email_request` 回傳 immutable command 與 optional
terminal receipt；caller 在 render 前讀它，core→legacy replay 也先被 durable request
擋下。明確 legacy rollback 則使用同一 Primary Authority 與 deterministic Message-ID
先查 Gmail Sent，第二台主機不靠本機 dedupe 判斷。最後一輪 review 再抓出
owner-transfer TOCTOU：transfer 與 PA acquire 現在共用同一 advisory lock，legacy
持有該 PA lease 時 DB transfer 直接 fail closed；
取得 fence 後還要重讀 durable request 與同一 legacy generation，pending core request
拒送、terminal receipt 直接 replay。Schedule identity 同時改由
canonical config 重算 generation／activation／cron slot／digest，假 fire 不能再混入。

本機真 PostgreSQL 已驗證 migration 可由非 superuser executor 套用，request read 在
settlement 前後分別回傳 null／exact terminal receipt；Python 回歸亦覆蓋跨 root reuse、
schema drift、wrong generation 與非 cron minute。Production wrapper 已以 manifest
lockstep 安裝；production migration `20260726134809` 已部署並回讀 owner／ACL／fence。
live acceptance fire 產生單一 WorkItem／EffectRequest／outbox attempt 1，Gmail Sent
exact read-back 為 delivered；同一 fire 重播只回相同 effect／terminal receipt，
attempt_count 仍為 1。2026-07-27 08:10 台灣時間的下一個自然 fire
`operations-core-v1:boss_report_4h:35208392b85064c22499c492` 由
`operations-core-scheduler` 一次成功；canonical RPC 回讀 owner=`operations_core/4`、
WorkItem=`succeeded`、Effect=`delivered`、attempt_count=`1`、Primary Authority epoch
`211`，Gmail Sent evidence 與 scheduler receipt 完全一致，未見 direct SMTP、重送或
owner drift。closure scoped regression 103 passed，五步 gate 全過，狀態為
**`root_cause_fixed_and_verified`**。

### 2026-07-27 — two-Mac isolated lease 被誤報為全系統 Primary Authority 結案

**證據化症狀**：`primary_authority_outage_cross_host_latest.json` 確實證明 Mac
Studio→MacBook Pro 對同一 isolated key 的 epoch `1→2` 與 0.162352 秒 handoff，
但 receipt 同時明載 `effect_requests=0`、`provider_calls=0`。Production code 仍讓
email、publisher sync／reconcile／delete、generic effect 各自使用不同 authority key；
lease table以 key 為 PK，所以不同 Mac 可各持不同 key 而同時成為合法 formal writer。
DB 另只永久保存 release/grant，renew覆寫 current row，expiry只是時間條件，reject
直接 raise 後整筆交易回滾。先前文件把這個 rehearsal slice寫成 Operations Core
umbrella `root_cause_fixed_and_verified`，結論強度超過證據。

**根因層級與底層修復**：這是 Primary Authority domain boundary與 receipt model
錯誤，不是演練少跑一次。Formal production builder 現移除 caller-supplied key，
統一使用 `operations-core-primary`；effect／publisher／email／commit adapters均驗
canonical key，database `primary_authority_grants` trigger再次 fail closed，隔離
rehearsal key可測 lease但不能取得正式 grant。Forward migration
`20260727080000_primary_authority_lifecycle_audit.sql` 新增 append-only transition
trigger及 typed try-functions：失敗的 lease subtransaction先 rollback，外層再保存
token-redacted rejection receipt。初版仍漏了「無後續 takeover 的自然 expiry」與
「backend outage 時 local demote 但 remote release 未確認」；固定基準雙審抓出後，
再補 DB-clock read/reconcile materialization（expired lease會原子清 holder並留下
唯一 expired＋demoted events），以及 fsync＋atomic replace 的 token-redacted local
demotion intent。Store在下一次 acquire 前重播 service-role reconcile；有效 lease
維持 pending，DB expiry後才收成唯一 demoted receipt。acquire／renew／expiry／
demote與reject因此皆可由同一 audit RPC回讀。

**回歸與狀態界線**：TDD先證明 typed rejection未被 adapter辨識、lifecycle table
不存在、capability-scoped key仍可取得 formal grant，修正後 unit／PG17 transaction
tests通過；non-superuser migration executor與重放 idempotency亦納入。這只完成 global
key＋durable lifecycle contract；另以「無 takeover 自然 expiry」及「release backend
unavailable→intent→recovery replay」回歸證明兩個原漏口。production
migration `20260727080000` 已用 exact-file query 部署（未以 drifted ledger 執行全量
`db push`），migration ledger exact repair後本地／遠端皆為 applied；production回讀
確認 event table/view/identity sequence owner、FORCE RLS、service-role-only RPC ACL，
且 legacy capability-key SQL boundaries為0。Global-key live canary取得epoch 1、
renew、拒絕第二holder、authorize synthetic resource、release，RPC回讀依序為
acquired／rejected(already_held)／renewed／demoted，grant與release ref皆為
`primary-authority:operations-core-primary:epoch-1`且無raw token。相鄰最終回歸
**467 passed**，Matt Spec／Standards雙軸複審皆PASS；supervisor經canonical planned
reload後heartbeat正常，兩次reload通知皆被正確suppressed。

這一輪已完成production migration/read-back及安全的global-key transaction canary；
formal Git／email真實mutation-boundary partition canary、direct legacy writers
cutover與retirement仍分別由Issue #18後續、#24與#46接續。因此目前狀態仍只能是
**`contained`**，不得把本次synthetic authorize冒充外部副作用結案。

### 2026-07-26 — owner-gate suppression 新增 exit-0 marker，綠測試仍寫髒 CI checkout

**證據化症狀與根因層級**：GitHub Actions Test Suite run
`30207277676` 在 commit `668ed9a87991e615d3574ea1766b8aa4ae5d0927` 的 pytest step
全數通過，最後 tree-clean gate 才抓到 `storage/ops/cron_last_run.json` 與
`.lock` 被建立。最小化後只有
`test_cron_lib_suppresses_stale_legacy_trigger_before_business_action` 可在約 0.6 秒穩定
重現：該 commit 讓 stale legacy trigger 被 Operations Core owner gate 抑制時也呼叫
`cron_emit_exit(..., 0)`，但測試 subprocess 沒有設定 `VOLPRED_CRON_MARKER_PATH`；
底層 `cron_mark_last_run.merge_last_run()` 又未遵守
`VOLPRED_NO_CANONICAL_WRITE=1`。因此測試 assertions 全綠，正式 marker 卻被寫入。既有
canonical-writer audit 未把 `cron_last_run.json` 列入 target，故也無法在更早階段攔截。

**底層修復與制度化**：`cron_mark_last_run.py` 以 plain system Python 可載入的
`src/volpred/canonical_write.py` 作唯一 guard，在 lock／mkdir／tempfile／replace 前的
`merge_last_run()` 與 `_atomic_write()` 兩個最低寫入邊界 fail closed；production 未設定
test-only flag，正常 exit-0 marker 語意不變。owner-gate end-to-end test 將 marker 明確
導向 `tmp_path` 並回讀 `handoff_regen` key。canonical-writer audit 新增
`cron_last_run.json` target，固定 `cron_mark_last_run` 兩個 low-level owners；擴大監管面
同時發現既有 `check_alerts._record_release_pool_fallback_fire`，其 guard 已存在，現納入
owner-count ratchet。

**回歸與狀態**：獨立乾淨副本的 regression 先以
`DID NOT RAISE CanonicalWriteBlocked` 轉 RED，修正後 GREEN；cron scoped suite
**28 passed**、canonical-writer tests **20 passed**、audit CLI 回讀
`ok=true / violations=[] / owner_count_mismatches=[]`，plain `/usr/bin/env python3`
marker smoke 通過。完整無憑證 suite 為 **5352 passed, 2 skipped**；測試前後
`git_status_delta=clean`、`canonical_mtime_delta=clean`。本機根因、回歸與制度化 gate
已完成；但新 commit 尚待主線 push，GitHub hosted runner 尚未回讀 sustained green，
故目前只能標 **`contained`**。新 run 全綠並確認下游通知收斂後才升級為
**`root_cause_fixed_and_verified`**。

### 2026-07-27 — Parity checker 本身可被 union／regex／symlink escape 騙成假綠

**證據化症狀**：Issue #6 初版雖有route inventory，owner仍是原版／v3 union，
API只標route-level access；`/api/questions` GET與POST因此被歸成同一權限。後續review
再以adversarial cases證明：兩個handler可各缺GET／POST卻靠canonical-route union過關；
註解中的export／redirect可冒充真surface；router type、destructure、alias、optional、
bracket、namespace import與re-export可逃出navigation scanner；source symlink在
validate後仍從原path讀取，存在check-to-read邊界。

**根因層級與底層修復**：根因是checker把文字模式匹配當語意證明，且聚合key低於實際
ownership boundary。Contract改為mode-keyed owner與method-keyed access；method反向
gate以`(rule, canonical route, mode, source_ref)`逐handler驗exact exports。TypeScript
lexical mask排除comment/string並支援alias export；router與`next/navigation` symbols
追蹤所有已消費reference，無法證明的binding/re-export fail closed。Frontend source
resolve後只讀resolved path，audit前後另以nested Git與content tree CAS防並行漂移。

**回歸與制度化**：27個測試固定method互補union、comment/string、dynamic API、path
escape、symlink swap、typed/destructured/direct/aliased router、redirect import／
namespace／multiline re-export等escape。Live report 133 rows／25 rules／7 scenarios，
兩次digest byte-identical；Matt Spec與Standards雙軸review均PASS。教訓是：稽核器的
聚合維度必須至少與被稽核ownership boundary同細，且「無法解析」只能是typed blocker，
不能靠regex未命中當作不存在。#6 checker為`root_cause_fixed_and_verified`；它揭露的
frontend內容缺口仍由#8處理。

### 2026-07-27 — 低層 Supabase script 反向初始化 eager ops package，Operations Core schedule retry exhausted

**證據化症狀與根因層級**：`release_settings_audit` 的 Operations Core fire
`operations-core-v1:release_settings_audit:7993935c6a79e4e4efb529fe` 連續三次 exit 1。
fresh traceback 是
`audit_release_settings → scripts.supabase_sync → volpred.ops.__init__ →
volpred.ops.content → scripts.supabase_sync`；`content` 從尚未完成初始化的 module
取 `_delete_where` 時拋 `ImportError`。這不是 cron/FDA 或暫時網路錯誤，而是依賴方向
違反：低層同步 script 為了 diagnostics 與 public projection contract，反向載入了
會 eager re-export business modules 的整個 `volpred.ops` package。

**底層修復與制度化**：將 dependency-neutral diagnostics 與 public projection
contract 下移為 `volpred.diagnostics`、`volpred.public_article_projection_contract`；
舊 `volpred.ops.*` 路徑只保留完整 compatibility surface。`supabase_sync` 直接依賴
新低層路徑，不再於 module load 初始化 ops。fresh-interpreter regression 固定
`supabase_sync-first`、`audit_release_settings-first` 與「低層 script 禁止 top-level
`volpred.ops` edge」；另固定 legacy projection surface 的四個 public symbols。
Matt 首輪雙審曾抓到 matcher 漏 re-export 的 P1，follow-up `744e18920` 補齊後
Spec／Standards 均 PASS，避免用解除循環換來 production compatibility break。

**回歸與狀態**：相關 credential guard、remote guard、projection convergence、
diagnostics、release audit 與 publisher sync suites為 **104 passed, 1 skipped**。
真實 `audit_release_settings.py --fix --json` 回讀 Supabase
`status=ok / cadence=aligned / starved_drafts=[]`，原 detector fresh read-back 為
`host_cron_fail.breached=false / failing_logs=[]`。2026-07-27 12:17 台灣時間的下一個
自然 Operations Core fire
`operations-core-v1:release_settings_audit:3b48587d8d30502028edc5d2`
由 `operations-core-scheduler` attempt 1 執行成功，receipt 回讀
`state=succeeded / exit_code=0 / duration=0.691004s`，fence token 與前一筆失敗
fire 不同，證明不是重播舊綠燈或 legacy wrapper。五步 Gate 已全過，此 incident
升級為 **`root_cause_fixed_and_verified`**。

### 2026-07-27 — 同 owner 的歷史壞 shadow receipt 永久污染七日 cutover window

**證據化症狀**：Issue #9 live queue 已回到 `queued_execution`，23:37 UTC 後的
scheduled v4 receipts 連續回讀 0 reconciliation issue，selection difference 是
有完整 oracle／snapshot evidence 的 registered capability policy change；但最新
receipt 仍有 8 個 implementation mismatch（active claim 缺 durable expiry、main-thread
lane 未映射 capability），因此 clean suffix 目前尚未開始。除此之外，
`work-shadow-assess` 還會把 12:15–23:15 已修復的 legacy corruption／implementation
receipt 永久納入：即使後續把上述 8 個 mismatch 修完，只要 owner state SHA 不變，
舊 blocker 仍不會離開窗口，ticket 在數學上依舊無法結案。

**根因層級與底層修復**：根因是 observation state machine 只有
「owner evidence 改變」一種 epoch boundary，沒有「同 owner 下修復完成後重新累積
連續乾淨窗口」的語意。這不是刪舊 receipt 或手改 live state 的問題。公開
`assess_shadow_observation_directory()` 現以單一 chronological pass 同時計算內容與
時間邊界：row count、candidate identity、必要 dimensions、selection evidence、
registered policy、reconciliation、非 policy mismatch、超過 max-gap 與 replay clock
非 live 都會重啟 segment。Matt Standards 複審再證明若先信任未驗證的
`recorded_at` 排序，最新 receipt 可大幅 backdate 到完整舊窗口之前，連 owner mismatch
也能被同法藏掉而 false-green；owner epoch 與 clean segment 現統一以
`max(recorded_at, observed_at)` 排序，使非 live receipt 只能留在其 observation
位置或更晚，不能向歷史移動。只有最新 clean segment 的 append wall-clock真正跨滿七日，
assessment 才改以該 segment 裁決；舊 receipt仍完整保留供audit，短窗或近期新
blocker仍fail closed。

**回歸與狀態界線**：兩個 public-interface cases 先分別以
`reconciliation_issue_present`、`receipt_row_count_mismatch`、歷史 observation gap
與歷史 replay-clock violation 重現永久污染，再證明其後八筆／七日乾淨 evidence
可核可；另以近期 gap／clock violation及最新 receipt／owner mismatch 大幅 backdate
證明舊完整窗口不可被誤用。Assessment 全檔 **37 passed**、相鄰 suites
**104 passed**。Live clean suffix
尚未開始，正式 Work Coordinator owner 仍為 `legacy/1`，沒有 stage gate、owner
transfer、下游 acknowledgement 或 rollback rehearsal。因此本 assessor 根因修復可在
完成雙軸 review 後標 `root_cause_fixed_and_verified`；Issue #9 umbrella 仍只能標
**`contained`**。

### 2026-07-27 — diverse-task 排程測試讀到正式 schedule receipt，造成 clean checkout 假紅

**證據化症狀**：全專案回歸唯一失敗為
`tests/test_generate_diverse_tasks.py::test_gen_platform_ops_tasks_still_emits_when_log_missing_and_last_run_stale`；
案例預期建立一張 platform-ops 任務，實際為 0。CI parity 回讀顯示測試使用了正式
`storage/ops/schedule_receipts.json`，而不是 `tmp_path` 的隔離資料。

**根因層級與底層修復**：production 的 receipt precedence 正確，問題在四個測試只
monkeypatch marker／schedule／log 路徑，卻漏掉 module-level `ROOT`；`job_liveness`
因此仍從正式 repo 解析 schedule receipt。四案統一將
`generate_diverse_tasks.ROOT` 綁到 `tmp_path`，沒有更動 production generator、
排程或正式 receipt 判定。修正落於 commit `2769db29d`。

**回歸與制度化**：原始單案先 RED 後 GREEN；`test_generate_diverse_tasks.py`
**28 passed** 且 CI parity clean，相鄰 generator／liveness／schedule／owner suites
**71 passed**，Matt Spec／Standards 雙軸 review 皆 PASS、0 P1／P2。最後以
`VOLPRED_NO_REMOTE_WRITE=1 VOLPRED_CI_PARITY=0` 跑全專案，結果
**5,721 passed、1 skipped、13 warnings**（17m36s）。本 test-isolation incident
完成五步 Gate，狀態為 **`root_cause_fixed_and_verified`**；Issue #9 的七日
continuous-clean suffix 雖已於 04:56:14 UTC 啟動，但 owner transfer、下游
acknowledgement 與 rollback rehearsal仍未完成，因此 umbrella 維持 **`contained`**。

### 2026-07-27 — Git authority grant 與真正 mutation boundary 間存在換代窗口

**證據化症狀**：`GitCommitActuator.commit()` 在持有 canonical writer lock後先呼叫
`CommitAuthority.authorize()`，但取得 grant後便直接啟動Git writer。公開介面failure
injection讓authority在第二次邊界驗證時回報Primary Authority lease lost；修正前因為
根本沒有第二次驗證，案例沒有拋錯且HEAD真的前進。這不是Supabase CAS或Git lock失效，
而是正式外部mutation前缺少緊貼邊界的fencing revalidation。

**根因層級與底層修復**：在writer argv、exact paths與content hashes固定完成後、
`subprocess.run()`前重跑同一durable authorize transaction。既有PostgreSQL／Supabase
transaction會再次驗WorkLease、commit owner generation、全域
`operations-core-primary` epoch／token；回傳grant還必須與第一次完全一致。任何
partition、stale lease、owner或grant漂移都在Git write前fail closed；不abandon原grant，
保留精確recovery所需identity。

**回歸、制度化與狀態**：原案例RED→GREEN並回讀HEAD不變；
`test_git_commit_actuator.py` **26 passed**，authority／Change Delivery相鄰套件
**107 passed**，PostgreSQL commit-authority transaction **8 passed**；後者逐一在
durable grant後使WorkLease、commit owner generation與Primary Authority失效，均拒絕
第二次授權且回讀HEAD／index未改變；全專案回歸 **5,738 passed、1 skipped**。
`git diff --check`通過。Git
mutation-boundary fencing這個根因完成五步Gate，狀態為
**`root_cause_fixed_and_verified`**；Issue #18仍因Email真實partition canary與
#24/#46 legacy writer cutover／retirement未完成而維持 **`contained`**。

### 2026-07-27 — 系統 termination 沒有 durable intent，raw SIGTERM 無法誠實歸因

**證據化症狀**：dispatch worker 收到 signal 15 時只能從 wait status 知道「被
SIGTERM」，無法知道 sender。舊路徑同時散落在 supervisor、agentic CLI timeout、
Git writer cleanup、canonical shell wrappers 與 `launchctl kickstart -k`；因此
`external_signal`、watchdog 與實際 system-owned kill 在事後長得完全一樣。Health
watchdog若先贏 completion CAS，還會先移除 current job，使 worker直接走
`superseded`，連後補歸因都不可達。

**根因層級與底層修復**：新增單一 `volpred.ops.termination` owner。每次 signal
先以 stable flock、`O_NOFOLLOW`、regular-file/owner/mode檢查與 fsync append
`intent_armed`、`signal_attempted`，首次建立檔案／lock再 fsync父目錄；signal後
append `signal_result`。Intent綁定 pid/pgid start-time generation、signal sequence、
job/attempt，且同一 exact target+signal只能 attempt一次；per-pid fallback還要在
syscall前重驗 start identity。Reader持 shared lock、拒絕 symlink及不安全檔案，
malformed row只會fail closed；partial tail會在下一次append前回滾至最後完整newline。
完整row若在file或parent-directory fsync失敗，writer會在同一把exclusive lock內
回滾到append前offset並再次fsync，因此reader不會把未durable的attempt/result當成
歸因證據。Python、Bash與launchd正式路徑均收斂至此 owner；daemon reload改為
精確PID的durable SIGTERM，並回讀KeepAlive產生的新PID，不再透過無法綁定generation
的`launchctl kickstart -k`。AST/shell gate禁止raw
`kill/killpg/terminate/pthread_kill`、subprocess `kill` command及 shell TERM/KILL
重新出現。

**回歸、live rehearsal與狀態界線**：真實 process-group rehearsal證明
attempt receipt在 syscall 前可回讀，TERM後 group確實清空，sent receipt能以
job/attempt/target精確匹配；ledger寫失敗則 sender呼叫為0。Health CAS race保留
raw exit與記憶體中的 exact PGID；sent publication短窗先bounded wait，若 sender
在 syscall後、result fsync前死亡，改記
`system_termination_unconfirmed`，不冒稱已確認，也不誤標
`unknown_external`。無任何 matching sent／unresolved attempt才使用
`unknown_external`，alert與completion口徑一致。Focused termination／supervisor／
Git writer／agentic CLI suites **339 passed**；child-process tests以
`VOLPRED_TERMINATION_LEDGER_PATH`隔離，runtime ledger列入gitignore，沒有再污染
正式 evidence。本 termination-intent bounded slice完成五步Gate後可標
**`root_cause_fixed_and_verified`**；Issue #45完整 checkpoint resume、formal
ChangeSet/outbox/effect零重複與host-restart/lease-expiry演練仍被 #9/#24 阻塞，
umbrella必須維持 **`contained`**、OPEN。

**2026-07-30 operator termination／observe-only 增量驗證**：第一輪以舊
`repo_patch` metadata做 live canary，暴露 operator kill 未綁 producer custody，
且純觀察工作仍會取得可寫 workspace。正式 dispatch contract 現新增
`write_intent=observe_only`、明示空 `declared_output_paths`、task／claim session／
dispatch job／attempt CAS，observe-only worker 在 OS sandbox 及 disposition matrix
均不可寫 repo；admission crash replay亦保留 exact `dispatch_job_id`。Operator
termination 對 custody-backed producer只能使用 `TERM_KILL`，在 signal 前驗 exact
PGID coalition、signal整個 coalition，並以 bounded process-table read-back確認
PID／PGID皆消失；`ps` timeout、stderr、非預期 return code 或 OSError 一律
fail closed，不得把探測失敗冒充「目標不存在」。

最終 live canary job `7394003cc1ec4848a30b137bcf93e55d`／PGID `63096`
產生 durable intent `a639722ce60843eaa00f42f2c7c3d484`，CLI 回
`custody_drained`，completion receipt 回讀 `system_terminated`／exit 143，
task自動 re-pend，observe-only workspace receipt為 `empty_removed`；其後 canary
task正常 claim／start／complete。Clean checkout在 commit `98159061d` 跑
**419 passed、1 skipped**，Matt Spec／Standards雙審均 PASS、0 P1/P2。此
operator termination＋observe-only bounded slice完成五步Gate，狀態為
**`root_cause_fixed_and_verified`**；但Issue #45完整checkpoint resume、
host restart、lease expiry及duplicate commit/effect acceptance仍受#9/#24阻塞，
umbrella繼續 **`contained`**、OPEN。

### 2026-07-27 — Sent read-back 與 SMTP send 間缺少 Primary Authority 再驗證

**證據化症狀**：`OwnedEmailNotification.deliver()`在呼叫provider前會驗證目前
Primary Lease，但`EmailNotificationEffectAdapter.deliver()`內部先查Sent mailbox，
確認沒有既有Message-ID後才真正呼叫SMTP notifier。公開seam使用concrete adapter，
在第一次Sent read-back期間把authority lease換代；修正前案例沒有拋出
`NotificationOwnershipLost`且notifier被呼叫，證明舊holder可在read-back與SMTP間的
窗口越過fence。這是mutation-boundary contract缺口，不是SMTP或IMAP資料錯誤。

**根因層級與底層修復**：adapter新增窄的`authorize_mutation` callback，只在確定沒有
既有Sent copy後、緊貼notifier前呼叫。callback位於provider例外轉換區塊之外，authority
lost／partition會原樣fail closed，不會settle成provider retry或dead-letter。normal
delivery、recovery與legacy rollback都把同一Primary Lease identity綁進callback；
若Message-ID已存在，冪等replay仍直接以true-external evidence acknowledgement，
不會再次寄信。

**回歸、真實回讀與制度化**：原公開案例先RED後GREEN，並回讀notifier calls=0、
settlement calls=0；Email相關完整範圍 **206 passed**，Matt Spec／Standards雙審均
PASS、0 P1／P2。全庫另有3個失敗，精確落在另一個session未提交的termination、
Git hook packaging與K1730 nested-DM變更，未修改或回退；真實驗收改由已審commit的
乾淨archive執行。owner-only正式寄送由`operations_core/4`完成，Gmail Sent evidence
回讀成功，同key重播identity／evidence不變且`attempt_count=1`。authority-loss案在
真實IMAP read後demote全域Primary Authority epoch 35；notification log沒有該subject，
獨立Message-ID再讀亦不存在。token／recipient去敏receipt固定於
`storage/ops/email_mutation_boundary_canary_latest.json`。五步Gate全過，此incident
與Issue #18狀態升級為 **`root_cause_fixed_and_verified`**；#24/#46 legacy writer
retirement屬獨立ticket。

### 2026-07-27 — CI 自動修復把限流拒單誤記為已入池，形成 phantom task

**證據化症狀**：run `30241354854` 因 `KeyError: 'incident'` 紅燈；G6 ledger 明確
拒絕 `ci-red-30241354854`，canonical `storage/next_tasks.json` 卻沒有該 task。
`ci_watch_state.json` 仍把同一 id 寫進 `repair_task_ids`，通知宣稱「已啟動自動
修復」，GitHub 暫時不可用時還會把不存在的 task 當 pending 重複 request fire。
後續 main 轉綠並非該 repair task 的可歸因成果。

**根因層級與底層修復**：`_append_next_task_locked()` 丟棄
`append_task_record()` 回傳的 durable admission record，只保留 `created` bool；
caller 又無條件綁定原始 id。現在 CI owner 保存完整 admission receipt，只有
canonical queue 真有 row 才綁定與派工。一般修復被 G6／semantic dedupe 拒絕時，
建立同 incident 唯一 `ci-root-<run>`、`source=incident_escalation` 的 uncapped
loop-exit task；連此出口都失敗則轉 critical，偵測通知明寫「尚未啟動」。舊
phantom id 會與 queue 回讀對帳、移除並在仍紅時重建；dispatch 對缺 row fail
closed，不再預設 pending。

**時鐘與驗證**：CI state machine 從每小時重型 `check_alerts` 拆成 Operations Core
獨立 `ci_watch`（`*/5 * * * *`），wrapper 已同步至 live `~/.volpred/bin` 並逐 byte
回讀一致；schedule validate 顯示 51/51 jobs 由 Operations Core 擁有。CI watchdog
完整 **63 passed**，涵蓋 throttle fallback、全 admission 失敗誠實通知、舊 phantom
重建與 missing task 禁派工。

**收口時發現的 Primary contention 與最終驗證**：第一次 live recovery 已確認
green run `30244586073` 涵蓋失敗 head，但 email worker 在 durable request 建立前
先搶全域 Primary Authority；另一個同 holder 的長通知 attempt 正續租 epoch 40，
因此新 attempt 收到 `already_held` 並讓 incident 卡在
`recovery_notification_pending`。底層順序已改為先建立 WorkItem/outbox，再嘗試
Primary；正常 contention 回傳 `effect_status=pending`／
`send_error=primary_authority_busy`，不丟失意圖、不假稱已寄送，下一輪以同
idempotency key 重試。成功 delivery 另會清掉舊 `last_error`，避免 sent receipt
同時殘留過期失敗訊息。

完整 alert／owned-email／CI watchdog 回歸 **158 passed**；Ruff 基準比較修前後均
無新增告警。live retry 回讀 `notification_delivered=true`、recovery effect
`effect_owned_email_fda6e6767da5c2f74557697604906fed`，incident
`ci-red-30241354854` 已於 `2026-07-27T07:44:02Z` 移出 active、phase=`recovered`，
verified green head=`0693506341c2`。Primary lifecycle 後續亦回讀 epoch 40
expired → epoch 41 acquired → demoted，證明不是永久霸占。五步 Gate 已全過，
本 incident 升級為 **`root_cause_fixed_and_verified`**。

### 2026-07-27 — Warm standby部署誤疊full repo，且isolated handoff不能證明formal RPO=0

**證據化症狀**：#21 closure audit回讀MacBook目錄時發現沒有`.git`，但含
`.env.local`、`.venv`、storage、experiments與frontend等約3.1GB內容；這不是宣告的
最小tracked snapshot，不能拿來證明guided parity。另有既有
`cross_host_verified=true` receipt，但其`effect_requests=0`、`provider_calls=0`，
只能證明isolated authority key的排他與RTO，不能證明formal effect receipt的RPO=0。

**根因層級與止血**：部署來源邊界與ticket證據口徑混淆。誤疊目錄已完整移到MacBook
垃圾桶`volpred-research-unsafe-20260727T1608`，未刪除；新目錄只從固定Git tree匯出
`src/volpred`、`scripts`、`config`與lockfiles，保留MacBook本機既有mode-600
credential及Python `3.12.10` venv，不從Studio複製secret，也不安裝任何VolPred
LaunchAgent／cron。第一次缺`config`的import preflight在remote read/mutation前
fail closed，補齊tracked config後兩端implementation hash exact match
`9db5479f…e401`。

**live read-back與裁決**：readiness v4確認兩個不同實體fingerprint、相同Supabase
backend、publisher owner `operations_core/8`與相同runtime。演練
`issue21-warm-standby-20260727-1615`由Studio epoch 1健康renew後注入transport
partition，`9.635672s`內關閉local gate；MacBook等待`29.034066s`且只能在舊lease
DB-clock expiry後取得exact-next epoch 2，handoff=`0.528014s`，claims=2、
duplicate/effect/provider=0。aggregate receipt已由final verifier重算SHA chain後落
`storage/ops/primary_authority_outage_cross_host_latest.json`。

**狀態**：誤疊部署已`contained`並留下可復原原件；本次isolated takeover rehearsal
為有效live evidence，但不是formal RPO=0或完整warm standby結案。可重複guided
migration/cold restore、TCC/runtime capability與formal effects分別仍由#17/#16/#24
負責，且#16/#17受#12→#9七日gate阻塞。Issue #21因此維持
**`contained`／OPEN**，不得升級為`root_cause_fixed_and_verified`。

### 2026-07-27 — Dedup health把同一候選重試誤算成多個被吞掉的narrative arc

**證據化症狀**：canonical `audit_dedup_gate_decisions.py`穩定回
`healthy=false`，宣稱三個arc各被block四次；逐筆回讀卻顯示三個arc都只來自同四班
CLI呼叫，其中兩班為同一FOMC標題retry、兩班為診斷標題`x`。同時近24h仍有170次
allow、最後allow距當下不到一分鐘，沒有content black hole。警報把「同一候選重跑」
錯當成「同一arc吞掉三個不同候選」，人工unlock建議因此是false positive。

**根因層級與底層修復**：audit只按`matched_id`累加raw rows，沒有candidate
identity。現在跨structured/legacy schema優先用`target_id`／`candidate_id`，舊
pre-write紀錄則用正規化`new_title`／`title`；只有完全沒有identity的歷史row才維持
逐列計數，避免猜測性合併。arc-repeat條件改計distinct candidates；block-rate與
no-pass仍保留每筆正式decision，不會美化真實hard block或黑洞。

**回歸與live read-back**：公開audit seam先以「同arc、同candidate三次」重現RED，
修後GREEN；原有跨schema三個不同candidate仍會breach。dedup/event/arc/release相鄰
套件**144 passed**，silent-fallback strict=`new=0`。production log不刪、不改，
40個hard block全保留；同一原detector fresh read-back為
`arc_repeat_block.breached=false`、`findings=[]`、`healthy=true`。此alert計數根因
完成五步Gate，狀態為 **`root_cause_fixed_and_verified`**。

### 2026-07-27 — observation window 重啟後，日期式 unblock 可早於真實 gate

**證據化症狀**：Issue #9 的正式 clean suffix 已於
`scheduled_20260727T045614581709Z_def2f814b885` 重啟，但 canonical parent task
仍帶舊 `blocked_until=2026-08-02T12:15:06Z`；真正七日成熟時間應為 receipt
`recorded_at + 7d = 2026-08-03T04:56:16.743114Z`。generic queue maintenance
只要日期過期就把 `blocked` 轉 `pending`，沒有回讀 durable observation gate，
因此可能提早約16小時41分進入 cutover 工作。

**根因層級與底層修復**：`blocked_until` 把「下次可檢查時間」誤當成「外部條件已成立」
的證明。現在 lifecycle 增加 allowlisted `unblock_gate` contract；只能由
`mark_task_blocked.py --unblock-gate` 寫入，free-form annotate 被機械禁止。
`work_shadow_cutover_ready_v1` 在日期到期後重新載入 queue-paired owner evidence與
append-only receipts，跑同一 fail-closed assessment；只有
`ready_for_cutover=true` 才清 block/gate並轉 pending。未知名稱、owner evidence
讀取失敗、窗口不足或任何 historical/recent blocker都保持 blocked。手動 unblock、
release、claim、start、handoff與supervisor preassign都不能越過未滿gate；
非terminal re-block必須保留既有gate，只有成功evaluator或真正terminal transition
可消耗；`mark_task_blocked`以同一queue descriptor的`LOCK_EX`完成
read→mutate→write，避免並行claim被舊snapshot覆蓋。共同
`next_tasks` writer另強制gate必須是allowlist、status=`blocked`、
reason=`awaiting_event_window`且有not-before，任何其他合法writer也無法繞過CLI。

**回歸與live read-back**：expiry-before-ready、ready後解除、not-before不探測、
unknown gate不執行、所有dispatchable transition bypass、whole-writer schema與
CLI reason/gate pairing均有RED→GREEN；production adapter以temp owner evidence與
真receipt shape覆蓋ready、短窗口、owner mismatch及evidence不可讀。
queue lifecycle／assessment／pool-pressure／canonical-writer 相鄰套件 **217 passed**。正式 #9 row 已由受控CLI綁定
正確到期與gate；把該row的日期只在記憶體副本改成過期後執行production probe，
回讀`swept=[]`、`status=blocked`、gate保留，理由含
`observation_window_too_short`。此「提前解除」根因已
**`root_cause_fixed_and_verified`**；Issue #9 umbrella仍須等真實七日與cutover
transaction，維持`contained`。

### 2026-07-27 — Retirement event ledger 不可用 PostgreSQL IDENTITY 證明 gap-free

Issue #46 duplicate-effect producer初版使用`GENERATED ... AS IDENTITY`當作不可缺號的
event cursor，但PostgreSQL sequence不隨交易rollback回捲；一次後續失敗的settlement
就能消耗號碼、移除event row，讓`high_watermark - cursor == event count`永久失敗。
同時，沒有per-effect serialization的AFTER INSERT trigger在並行delivery下可能互相
看不到，漏掉第二次外部效果。底層修正是由受RLS保護的singleton durable head在同一
交易內配號，並以effect-scoped advisory transaction lock序列化分類；event insert
失敗會連head更新一起rollback。完整物證、production receipt與回歸見
`docs/error_log_archive/2026-Q3-duplicate-effect-retirement-signal.md`。

### 2026-07-27 — Orphan evidence 不可把 unreadable identity 或半寫 event 當完成

Issue #46 的orphan sweep若在branch probe失敗後只寫`unresolved`，下一輪直接把actual
branch視為identity drift，會永久卡死；若event final path直接`open("xb")`，process
中止也可能留下partial JSON，使pending intent尚未有機會恢復就先被scanner拒絕。
底層修正為單調的`unresolved → actual`跨事件狀態機、loader獨立語意驗證，以及
pending intent + fsynced temp + no-clobber hard-link + durable head。on-disk格式刻意
維持v1，避免新版部署或回滾拒讀既有證據。完整物證、review與live fire見
`docs/error_log_archive/2026-Q3-orphan-work-retirement-signal.md`。

### 2026-07-27 — Formal owner census 不可把已完成的 Primary Authority 永久 unresolved

**證據化症狀**：Issue #18已完成global Primary Authority與真實mutation-boundary
驗收，但`audit_formal_owners.py`仍把
`host_authority/operations-core-primary`綁到`unresolved`。Live census因此固定產生
第六個`unknown_owner` blocker；即使其餘cutover日後完成，#46仍不可能收斂。

**根因層級與底層修復**：Issue #18的lease lifecycle receipt證明「曾發生租約事件」，
不是「目前formal capability owner」；拿歷史event推owner會在正常release後製造
假證據。現在新增獨立immutable owner singleton與service-role-only typed RPC；
FORCE RLS私表不對service role開放，resolver逐欄驗schema、canonical capability/key、
`operations_core`、generation、contract identity與exact key set；inventory pin
production backend SHA-256，claim使用DB `attested_at`而非本機重標，超過30秒或
未來超過5秒即拒絕；比較clock在owner RPC回傳後取得，避免schedule／其他probe延遲
使新鮮DB timestamp相對audit起始時間看似來自未來。任何backend／ACL／payload／time
drift皆fail closed為unknown，
且read seam不acquire、renew或release lease。

**回歸與live read-back**：公開audit seam先以缺resolver／缺adapter重現RED，並補
wrong backend、stale/future timestamp與extra field案例；修後Primary Authority與
formal census範圍**62 passed**；真PG17驗RLS、ACL、function owner、
non-superuser migration與role cleanup。Production回讀singleton=1、
owner=`operations_core`、generation=1、service table privileges=false、RPC只有
service role可執行；fresh census host-authority=`unique_owner`、probe errors=0，
總blockers 6→5。此slice為 **`root_cause_fixed_and_verified`**；#46仍因其餘五個
formal blockers、physical retirement與14日sustained-clean而維持`contained`。

### 2026-07-27 — 新正式 machine source 未註冊會重置 Work Coordinator soak

**證據化症狀**：Issue #9 的七日 clean suffix 原已從
`2026-07-27T04:56:16Z` 起算；10:16 的正式 CI 根因任務
`ci-root-30256296797` 使用 `source=incident_escalation`，shadow receipt 以
`unknown_source` fail closed並重置窗口。修正 incident family 後的第一次 live
read-back又立即捕捉 12:37 新建的
`lazypack_render_repair_mile_3c83e665`（`compute_queue_lazypack_failure`）造成同類
breach，證明只補單一觀察值不能結案。

**根因層級與底層修復**：machine writer observability registry
`MACHINE_SOURCE_TOKENS`與legacy→Work Coordinator reviewed provenance registry
各自演化，正式 producer 可被 admission 接受，卻在 shadow migration 層變成未知來源。
現在把 `incident_escalation`、`incident_adjudication` 納入 machine registry，並將
兩個 incident source及class sweep找到的
`compute_queue_lazypack_failure`、`daily_checkup_db_landing`、
`phase_z_gate_review`逐字映射為canonical `schedule` ingress。回歸 gate強制所有
`MACHINE_SOURCE_TOKENS`都必須存在於reviewed provenance registry；任一已登記的
machine producer日後漏做migration分類，CI直接失敗。更重要的是canonical
`append_task_record`現在在真正寫入前呼叫同一個exact classifier；即使新producer
同時漏登machine registry與migration registry，也會被creation gateway拒絕且queue
保持原樣，不再等七日live soak才發現。scratch／外部契約測試queue不受此production
admission限制。未知、未review來源仍維持fail closed，沒有 prefix 或 fallback白名單。

**回歸與live read-back**：先以五個正式來源重現 importer/replay RED，再驗證
exact source、schedule classification及incident雙selector一致；相關 importer、
replay、compute queue與pool-pressure套件 **102 passed**；另以rebound canonical
queue證明雙registry都漏登的producer在append前RED→拒絕、queue仍為空，已登記來源
仍正常通過。正式 observer第一次回讀
準確抓到新lazypack來源（issue=1），補完class sweep後第二張v4 receipt
`scheduled_20260727T124014223082Z_f71c43880b3e`回讀
`reconciliation_issues=[]`；selection difference僅剩已註冊的
`coordinator_capability_contract` policy change。此producer/provenance缺口為
**`root_cause_fixed_and_verified`**；#9 umbrella仍需從最後一次bad receipt之後重新
累積真實七日，維持`contained`，不可提前cutover。

### 2026-07-27 — Formal census 不可用未綁定的 Work owner row 宣稱接管

**證據化症狀**：Issue #46 的`work.coordinate`原本永久`unresolved`；初版RPC雖能
讀owner singleton，卻只驗owner、generation與任意64-hex manifest。若資料被錯誤
更新成`operations_core`／generation 999，census仍可能產生`unique_owner`假證據。

**根因層級與底層修復**：owner row本身不是完整cutover證據。RPC現在必須找到逐欄
相同的immutable ownership receipt；Operations Core狀態還必須綁同manifest與
generation的consumed gate，rollback則必須綁rolled-back gate及單調時間順序。
Python adapter再次以exact key set、無首尾空白、receipt/gate identity與chronology
fail closed。已提交的migration不得刪改：原始`20260727123500`保持SHA-256
`8c885d474c0d86ebfef86f7059a3f8d9f53b55d66b846cf7656d355801471070`，
hardening只可追加`20260727124801`。

**回歸與live read-back**：真PostgreSQL依序重播舊→新migration兩次，涵蓋合法
cutover、缺receipt、未來時間、ACL與rollback契約；相關套件**126 passed**，
Matt Spec／Standards雙PASS。Production receipts=`20260727125501`,
`20260727125509`；RPC只有service role可執行，私表FORCE RLS且service role無SELECT。
Fresh census把`work.coordinate`明確回讀為`legacy/wrong_owner`且
`probe_errors=[]`。可觀測性根因為 **`root_cause_fixed_and_verified`**；真正owner
轉移仍受Issue #9七日clean gate約束，umbrella維持`contained`。

### 2026-07-27 — Shadow soak 重置後不可靠人工推算下一次 gate 時間

**證據化症狀**：Issue #9 assessor其實已在每張blocking receipt後更新內部
`clean_start`，但clean suffix未滿七日前，公開report仍只輸出包含歷史breach的整包
`recorded_from`／reason codes。12:38 的新producer breach發生後，正式task的
`blocked_until`只能由人手讀receipt再計算「第一張clean recorded_at + 7d」；漏校正
雖不會繞過named gate，卻會在舊日期到期後每班重探並持續產生過時診斷。

**根因層級與底層修復**：clean segment是cutover state machine的一等狀態，不能只留在
函式區域變數。`work-shadow-assessment.v1`現在以additive fields輸出clean receipt數、
observed／recorded起訖、已覆蓋秒數與`next_eligible_at`；沒有clean receipt時明確為
`null`，完整七日時則ready且不再提供未來日期。expiry sweeper的allowlisted
`work_shadow_cutover_ready_v1` probe改讀同一typed assessment；若gate仍未成熟且新的
eligible time晚於舊not-before，就在同一queue lock交易內把task重新arm到新時間並寫
`blocked→blocked` history。只允許時間向後移、永不縮短七日；observer仍保持read-only，
未知gate、owner mismatch或assessment不可讀仍fail closed。後續adversarial TDD另
封閉三種假成熟時間：最後receipt已超過max-gap、receipt時間在assessment未來、或
queue owner mode不是可累積cutover soak的`queued_execution/disabled`時，
`next_eligible_at`一律為`null`，不讓時間欄掩蓋已知不連續或owner錯誤。

**回歸與live read-back**：先以「中途blocking receipt、其後僅一張clean」及
「expired task遇到較晚clean window」重現缺欄位／不會re-arm的RED，修後assessment、
replay、observer、mark／claim／status lifecycle相鄰套件 **246 passed**。Production
report直接回讀`clean_observation_count=1`、
`clean_recorded_from=2026-07-27T12:40:16.244030+00:00`、
`clean_window_seconds=0`、`next_eligible_at=2026-08-03T12:40:16.244030+00:00`，
與canonical #9 row完全一致；`ready_for_cutover=false`且原四項reason仍保留作歷史稽核。
此人工校時計算根因為 **`root_cause_fixed_and_verified`**；七日尚未經過，#9 umbrella
仍為`contained`，不得stage或transfer owner。

Final hardening commit=`0a0dc7b64`；assessment／gate lifecycle／cutover／replay／
observer相鄰範圍 **225 passed**，Matt Spec與Standards最終雙PASS。

### 2026-07-27 — Formal census 不可把 incident owner 永久留成 unknown

**證據化症狀**：Issue #46 的`incident.lifecycle`在正式inventory中綁定
`resolver=unresolved`。即使incident store與3-Strike流程已運作，census仍無法回答
目前誰持有正式lifecycle mutation authority；unknown owner會讓日後physical retirement
無法區分「尚未切換」與「觀測器壞掉」。

**根因層級與底層修復**：實作存在不等於owner evidence存在。新增私有
`incident_owners` singleton與append-only bootstrap receipt，明確記錄目前仍為
`legacy/generation 1`；service role沒有表權限，只能呼叫STABLE、
`SECURITY DEFINER`、空`search_path`的固定read RPC。RPC必須把owner row逐欄綁到同
generation receipt，且拒絕未來時間。Python adapter再以exact key set、canonical
capability／contract、normalized text、receipt identity與chronology fail closed；
inventory pin exact production backend SHA，stale、future、extra field或RPC失敗皆不
產生claim。此slice沒有transfer function，也沒有incident mutation authority，因此
不會繞過#9/#13。

**並行部署教訓與收斂**：兩個session同時產生`130815`與`131500` migration；
`131500`的replay會從現存owner row補receipt，可能把未經gate的漂移事後合法化。
Matt雙審判P1後，並行convergence commit `714bb25f6`移除未被接受的`131500`，
production ledger亦標reverted；canonical鏈只重播fail-closed `130815`、schema
hardening `132000`與finalizer `132229`。finalizer安裝前要求exact一筆legacy/gen1
owner與exact一筆matching receipt，read RPC另以`NOT EXISTS`拒絕任何額外receipt。
新增真PG回歸先製造owner drift，再重播canonical bootstrap migration；必須raise且
receipt count不增加。

**回歸與live read-back**：adapter/census與相鄰owner契約合計 **122 passed**；
canonical migration replay、ACL/FORCE-RLS、ungated drift與no-mint回歸全綠。
Canonical replay為`130815→132000→132229`；production ledger另誠實保留兩次
並行duplicate apply receipt `131925`與`132700`。`132000`曾被較弱並行版本覆蓋，
最終`132229/132700`均重新安裝extra-receipt fail-closed RPC；直接回讀
`pg_get_functiondef`含`NOT EXISTS`且owner／receipt各恰一筆；四個normalized-nonempty
CHECK與capability FK共5項皆存在且`convalidated=true`。Catalog回讀function
owner=`volpred_ops_definer`、service-role-only execute、私表FORCE RLS。Fresh census
回讀`incident.lifecycle=legacy/wrong_owner`、generation 1、`probe_errors=[]`。
unknown-observability根因為 **`root_cause_fixed_and_verified`**；正式owner切換仍受
#9→#13 gate約束，#13/#46 umbrella維持`contained`。

### 2026-07-27 — Provider module 存在不等於正式 execution owner 已可證明

**證據化症狀**：Issue #12 的zero-paid provider模組與測試已存在，但Issue #46
inventory仍把`provider.execution`寫成`resolver=unresolved`；production caller與
正式持久化owner尚未cutover，因此既不能誠實宣稱Operations Core擁有，也無法分辨
「目前仍是legacy」與「owner observer壞掉」。

**根因與底層修復**：formal ownership沒有production evidence seam。新增私有
`provider_owners` singleton與immutable bootstrap receipt，明確記錄現況
`legacy/generation 1`。Migration只在owner完全不存在時同交易建立兩者，之後要求
exact一筆owner與exact一筆matching receipt；漂移時重播直接raise，不替既存狀態
補造receipt。Read RPC固定只接受legacy/gen1、canonical #12 contract與唯一receipt，
使用STABLE、SECURITY DEFINER、空`search_path`且僅service role可執行；service role
無私表權限。Python adapter再驗exact schema、逐欄receipt identity、chronology與
production backend SHA，census以30秒freshness及future-skew fail closed。

**驗證與邊界**：commits `52157406e`,`23a5ea5bf`；Matt Standards初審另抓到
replay negative test在autocommit下永久留下drift，以及incident/provider parser與
backend-bound resolver metadata的複製。修正後前者改成transaction rollback並回讀
canonical legacy/gen1，後者收斂成共用typed parser/store與單一resolver registry。
相鄰測試117 passed，完整PostgreSQL effect contract 62 passed，ruff／diff-check
全綠，Matt Spec／Standards最終雙PASS。Production migration
`20260727133500` local=remote；catalog、ACL、FORCE RLS、owner/receipt各一筆皆回讀
符合，fresh census為`provider.execution=legacy/generation 1/wrong_owner`且
`probe_errors=[]`。Unknown-observability根因為
**`root_cause_fixed_and_verified`**；此slice沒有owner transfer或provider execution，
#9→#12未完成前兩個umbrella仍為`contained`。

### 2026-07-27 — Task source provenance 不可搶在 direct-mode owner gate 前失敗

**證據化症狀**：GitHub Test Suite run `30268312681` 在5,985案中僅兩案失敗：
`test_direct_mode_rejects_new_ids_at_canonical_write_seam`與
`test_malformed_direct_mode_state_fails_closed`。兩案本應由task-pool owner state拒絕
新id，卻先收到`unreviewed canonical task source: None`，使direct-mode fail-closed
契約被後加的legacy source provenance validator遮蔽。

**根因與底層修復**：commit `dcb3e2c09`把新canonical id的首次mode admission移進
queue `LOCK_EX`，以同一份existing-task snapshot在source validation之前執行；只有
通過owner gate的新record才檢查source。Exact-id replay在鎖內先回既有durable row，
不被新schema追溯拒絕。真正mutation仍由`write_tasks_to_handle`在同一鎖內二次檢查
mode，與enter／reconcile／restore共用鎖序，避免transition TOCTOU。

**回歸與狀態**：新增existing-id replay regression，direct mode／append／claim／
mode pairing／dedupe／provenance importer class sweep **194 passed**；Matt Spec與
Standards雙PASS。程式根因與制度化測試已完成；因本session依規不push，尚待platform
owner推送後由GitHub Test Suite回讀成功，incident目前僅為 **`contained`**，不得提前
宣稱`root_cause_fixed_and_verified`。

### 2026-07-27 — Zero-paid 宣告若未綁到真正 spawn，仍可能暗中走付費 auth

**證據化症狀**：Issue #12 已有 in-memory `ProviderExecution` policy，但 production
Claude supervisor、compute-agent 與 Codex failover 都直接建立 subprocess，沒有讀同一份
registry。單純在 config 寫 `api_key_env=null` 也不足夠：child env、同名假 binary、
Claude `apiKeyHelper`／gateway route、Codex user config 都可能讓實際 provider/model/auth
與宣稱的 `zero-paid` receipt 不一致。

**根因與底層修復**：commits `7e46f10e8`,`dc902d4be`建立 strict
`provider-registry.v1`及不可由 caller 降級的 launcher contracts。每次 subprocess 前
重讀 exact-schema registry，核對 provider/model、固定 semantic/capability/formal=false、
實際 executable realpath+SHA、pinned Claude settings SHA，並檢查 final child env。
API key、gateway token/base URL、Bedrock/Vertex/Foundry skip-auth、AWS profile、
Codex/OpenAI alternate config 與未知欄位一律 fail closed。Claude 只載入 receipt-bound
settings（拒絕 `apiKeyHelper`）；Codex 固定 `gpt-5.6-sol` 並
`--ignore-user-config`。Executable與settings在Popen前再次讀回雜湊，receipt綁定
contract/provider/model/path/hash/registry SHA。

**回歸、live read-back與邊界**：付費模式、同名 wrapper、惡意 symlink、授權後替換、
API-key/gateway env、settings helper、retry stale receipt、三條 real spawn seam及startup
guard的 targeted suite **119 passed**；supervisor class sweep另 **233 tests passed**，
但該次命令最後被既有CI-parity harness偵測到live `dispatch_state.json`／`tmp`讀取而返回
非零，未把它誤報成此slice regression。Live no-spawn回讀三個contract共用registry SHA
`32bb49aac533bdfd47f1f78429f7214edd516840c6bd4b8b399a09519f094f30`，
四種alternate-auth注入均在provider I/O前拒絕；Matt Spec／Standards最終雙PASS。
本三條launcher根因為 **`root_cause_fixed_and_verified`**。Class sweep發現的其他
legacy／utility AI CLI launcher已另立不重疊follow-up `assign_5938ee83`；因此沒有
transfer `provider.execution` owner、沒有繞過#9、沒有關閉#12，umbrella仍為
**`contained`**。

### 2026-07-27 — 三條主路徑受保護，不代表其他AI CLI沒有付費／身分旁路

**證據化症狀**：repo-wide source census在三條主launcher之外找到
`execution_brief.py`、`questions.py`、`scan_trending_agy.py`、兩條lazypack harness與
`prepublish_audit.py`直接建立AI CLI subprocess；另有兩條live shell seam。它們沒有讀
canonical registry，且多數用PATH/default model，實際binary/model/auth可與receipt宣告
不同。第一次live denial也證明`codex_exec_bounded.sh`用到舊system Python，在policy
執行前就因`list | dict`型別語法crash。

**根因層級與底層修復**：provider policy只接在列舉過的caller，沒有「新增spawn必須
被擋」的class invariant。Python AST audit與shell ownership證據現在共同擁有此邊界；
所有business seam在provider I/O前重載strict registry、驗receipt後再以pinned
executable啟動，model明確寫入argv/env。新增`agy-cli`只接受本機既有OAuth surface與
owner先前zero-paid指令，固定一個model；API key、alternate base URL、credits與未知
billing仍拒絕。Shell wrapper綁repo Python及canonical root，Telegram Claude以
authorize→verify→同PID execve消除TOCTOU；retired hourly wrapper不因留作rollback
artifact被誤列live。

**回歸與制度化**：獨立literal inventory與AST discovery互相校驗，測試另動態建立
同檔`codex --version`加`codex exec`，證明diagnostic豁免不能遮住business call；每個
launcher都有policy-denial-before-Popen／execve負向案例。相鄰範圍 **167 passed**；
live以注入`OPENAI_API_KEY=sentinel`回讀bounded Codex、Telegram exec與agy scan都在
provider I/O前exit 126／policy_denied，未呼叫模型。此旁路類根因狀態為
**`root_cause_fixed_and_verified`**；真正owner cutover仍等#9，Issue #12維持
`contained`。

### 2026-07-29 — code SHA 不能證明 results 數值未被事後修改

**證據化症狀**：K1708 round-4 review指出
`test_stored_numbers_are_the_output_of_the_pinned_code`只比對
`K1708.py` SHA、seed、quick mode與樣本數；只改results內的CW、QLIKE或verdict不會
改動程式SHA，測試仍會通過。實際negative test把CW t-stat由`1.968775`改成`3.5`，
舊artifact gate沒有任何violation。

**根因層級（provenance contract）**：run-time spec只承諾entrypoint bytes，沒有獨立
承諾canonical result bytes；「相同程式可重跑」被錯當成「目前results就是該次run的
原始輸出」。兩者不等價。

**底層修復與制度化**：`finalize_experiment`現在從即將寫出的exact result bytes建立
`canonical_result_identity`（path／SHA-256／size），與runtime spec一同落地；
`check_experiment_artifacts.py`在merge與CI fail-closed比對完整results bytes。
舊spec無此欄位維持forward-compatible；新欄位若malformed、指向非canonical result，
或任一數值被改即BLOCKED。修復指引禁止「順手刷新checksum」，只能還原runtime輸出或
正式重跑。

**回歸與live read-back**：兩條精確測試先RED（缺identity、竄改未被擋）後GREEN；
reproduce／artifact／gate-history相鄰範圍共66 passed，Ruff scoped與diff-check全綠。
repo-wide class sweep只找到未合併K1708 worktree一處錯誤宣稱；K1708因缺少run-time
`reproduce_spec.json`仍由真實artifact gate擋住，未補造spec、未merge、未寫knowledge。
此「code-only provenance對result tamper失明」bug class狀態為
**`root_cause_fixed_and_verified`**；K1708實驗本身仍是blocked。

### 2026-07-29 — sustained-clean gate 不可用 bounded observation ring 判跨度

**證據化症狀**：`inc_537a3ff3304f`在最後一次breach後持續收到clean observation，
但`clean_observations`只留12筆；偵測頻率高於每2小時11分時，保留窗永遠涵蓋不到24小時，
因此`RESOLVE_MIN_CLEAN_SPAN=24h`在數學上永久不可達。RED regression以每小時一筆持續
25小時，舊碼仍回傳`resolved=False`。

**根因層級（incident state contract）**：診斷用ring buffer與生命週期需要的持久streak
起點被錯當成同一份狀態。`_clean_criterion_met`用會被修剪的
`clean_observations[0]`當起點，造成判定能力隨觀測頻率改變。

**底層修復與migration**：incident row新增`clean_streak_started_at`；首次clean寫入，
後續ring修剪不動它，breach與resolution則與observations一起重置。舊row在下一次
`observe_clean`時從「當時仍保留的最早一筆」保守回填，不手改`incidents.json`、不提前
放行gate；真正streak只可能更早，因此最壞情況是延後resolution。

**回歸與制度化**：新增高頻25小時仍可resolve、舊row lazy migration、breach重置三道
regression；incident lifecycle與alert／PHASE-Z／Supabase ownership相鄰範圍共
105 passed，scoped Ruff與diff-check全綠。此ring-buffer造成永久不可達的bug class為
**`root_cause_fixed_and_verified`**；個別incident仍須由正式detector在滿24小時後
寫入clean observation，才可依五步Gate轉resolved。

### 2026-07-29 — Git writer lock 的實際 bootstrap interpreter 是 macOS Python 3.9

**證據化症狀**：`merge_worktree.sh`在任何non-dry整合開始前固定以
`/usr/bin/python3 scripts/git_writer_lock.py`取得全域Git writer lease。committed
`git_writer_lock.py`卻直接`from datetime import UTC`；本機實際system Python為3.9，
以committed bytes重播得到`ImportError: cannot import name 'UTC' from 'datetime'`。
dry-run不進lock區塊，因此會呈現「預檢健康、正式merge才全死」。

**根因層級（bootstrap runtime contract）**：lock owner本身是`uv`啟動前的bootstrap，
卻使用Python 3.11才提供的stdlib API；測試只在專案venv執行，沒有覆蓋真正的
`/usr/bin/python3`入口。

**底層修復與制度化**：優先import`datetime.UTC`，Python 3.10以下則以
`timezone.utc`提供同一語意；新增 regression 直接執行system Python CLI `--help`，
把部署契約變成測試，而不是文件假設。

**回歸與live read-back**：`/usr/bin/python3 scripts/git_writer_lock.py --help`通過；
同一interpreter實際執行`git_writer_lock.py run`取得並釋放lease成功；non-dry
`merge_worktree.sh`以不存在target完成完整bootstrap/lock preflight且未移動任何ref；
writer-lock測試55 passed。此「正式merge入口在import階段全滅」bug class為
**`root_cause_fixed_and_verified`**。

### 2026-07-29 — Dry-run parity plan 不能冒充可重複的 cold restore

**證據化症狀**：Issue #21 acceptance要求保留且可重複演練cold restore；既有
`guided_host_migration.py`只有capture／compare／plan，module docstring亦明定沒有
deploy actuator。舊`bootstrap_new_host.sh`會安裝legacy per-job schedules，歷史手冊
又曾允許複製env/session，因此只能止血，不能作新架構restore證據。

**根因層級（host recovery execution contract）**：系統已能證明source與target
parity，卻沒有一條把「已簽章clean immutable Git identity」安全物化到blank target的
正式邊界；人工copy會重新引入working-tree WIP、secret外洩、path traversal、半套落地
與意外啟用scheduler／lease的舊問題。

**底層修復與制度化**：task `assign_b4d6ff44`新增signed cold-bundle／cold-restore
contract。Bundle只從source snapshot綁定的exact Git objects建包，逐group回比
path／kind／mode／size／SHA，排除validated runtime state、`.env*`、Telegram state、
private key與`.volpred` host state。Restore不使用`extractall`，驗verifier簽章、
trust window、canonical member set、hierarchy與逐檔identity；只允許不存在的target，
在mode-0700 staging逐檔fsync＋O_NOFOLLOW回讀，最後以macOS
`renameatx_np(RENAME_EXCL)`／Linux `renameat2(RENAME_NOREPLACE)`原子no-clobber落地。
Target-signed mode-0600 receipt固定記錄`copied_secrets=[]`、
`installed_schedules=[]`、`performed_external_effects=[]`與
`authorizes_primary_lease=false`。

**回歸與live read-back**：43個host-migration tests全綠，負向案例涵蓋payload竄改、
已簽章path traversal、既存target與publish race；Ruff、py_compile、diff-check全綠。
正式CLI以當下四把Ed25519 key建包後，同一bundle在兩個全新temp target重演，兩端
payload tree SHA均為`6064cb7ac218186a4c6efdc7c7357c8ecf9c6b84331965a8298459bd441a8b4b`，
receipt mode均0600，secret／schedule／effect為空且lease=false。此「沒有安全可重複
cold-restore actuator」slice為 **`root_cause_fixed_and_verified`**；MacBook fresh
parity、formal-effect RPO=0與持續warm process仍受#9→#12→#16/#17阻塞，所以#21整體
維持OPEN／`contained`。

### 2026-07-29 — Supabase PG17 bootstrap membership 不能當一般 GRANT／REVOKE

**證據化症狀**：Issue #23 migrations在ephemeral PostgreSQL與測試通過，但production
`ALTER FUNCTION ... OWNER TO volpred_*_worker`回
`must be able to SET ROLE`。Catalog顯示managed `postgres`確實是worker member，
但membership為`ADMIN TRUE / INHERIT FALSE / SET FALSE`；有membership不等於能轉owner。

**根因層級（managed role ownership contract）**：PostgreSQL 16+讓non-superuser
`CREATEROLE` creator取得一筆由Supabase管理的bootstrap membership。跳過
`postgres` grant會缺SET authority；一般`GRANT`後只撤`SET OPTION`則會留下migration
runner自己授予的第二筆membership；全撤又會碰到不屬於自己的bootstrap grant。

**底層修復與制度化**：managed runner建立grantor-owned、
`INHERIT FALSE / SET TRUE` bounded self-grant，使用`SET LOCAL ROLE`直接以最小worker
owner建立／重建函式；最後以`REVOKE ... GRANTED BY CURRENT_USER`只撤自己的grant。
Supabase原生`supabase_admin` grant保持原樣，worker仍NOLOGIN／NOSUPER／NOBYPASSRLS。

**回歸與live read-back**：migration-shape regression與PG17連續套用兩次皆過，member
continuity suite **8 passed**。Production兩檔也連續重跑成功，catalog只剩每個worker
各一筆`supabase_admin` bootstrap grant（SET/INHERIT皆false）；五RPC
owner／ACL／空search_path全符，service-role transaction E2E通過後rollback。此類
managed owner-transfer與migration重跑失敗為
**`root_cause_fixed_and_verified`**。

### 2026-07-29 — macOS `flock` 不會替同程序的第二個 FD 自動重入

**證據化症狀**：`lazypack_async_render.py enqueue` 先取得
`compute_queue._receipt_lock()`，再呼叫同一模組的 canonical `enqueue()`；後者以第二個
FD 對同一 `.receipts.lock` 再做 `LOCK_EX`。macOS 會讓它等待自己而不是重入。Live
PID 13404 因此卡在第二次 `flock`，同時阻塞已於 07:28:04 完成的 K1694 worker
settlement；process sampling與`lsof`都顯示兩條執行緒停在同一把 receipt lock。

**根因層級（跨程序 transaction contract）**：既有 `threading.RLock` 只保護 Python
執行緒，巢狀 context仍會另開 kernel FD；程式把 process-local reentrancy與
cross-process exclusion誤當成一個原語已同時提供。

**底層修復與制度化**：receipt lock仍由 process-wide `RLock`序列化各執行緒、由
`flock`排除其他程序；另以 thread-local depth讓同一執行緒的巢狀 transaction重用
外層kernel lease，不再開第二個FD。最外層的所有例外路徑都會清depth並unlock。
Regression以daemon thread實際巢狀取得兩次；舊碼在1秒後仍死鎖（RED），修正後立即
完成，完整compute／owner／scheduler相鄰範圍 **144 passed**，Matt Spec／Standards
雙PASS。

**Live read-back**：以正式termination intent
`435b6b8daa3f4a56aa7c38af2fc4eeb8`只終止已證實自鎖的exact PID 13404；lock由kernel
釋放後，K1694立即寫出terminal failed receipt與source-task settlement，舊worker自然
退出。原K781 lazypack enqueue隨後在新contract下收斂為唯一queued receipt
`lazypack-mile_35863986`，重播只回`already queued`且沒有第二份job。此
same-process nested-flock自鎖類根因為 **`root_cause_fixed_and_verified`**。

### 2026-07-29 — `cron_jobs` 逃出 Operations Core inventory 會製造假「legacy=0」

**證據化症狀**：正式owner report宣稱全部`system_crontab` jobs已由Operations Core
持有、legacy LaunchAgent為0，但live仍有`com.volpred.compute-worker`每15分鐘觸發。
根因不是cutover後復活，而是compute clock只存在另一個top-level `cron_jobs` registry；
loader與owner audit根本沒有枚舉它。

**底層修復**：compute cadence、wrapper、parallelism與activation全部移入canonical
`system_crontab`；舊row只保留`status=retired`的rollback receipt，任何active
`cron_jobs` row都讓owner plan fail closed。Owner census另對所有loaded
`com.volpred.*`做canonical set difference，Telegram、dispatch與host dashboard三個
KeepAlive control daemons則顯式納入registry。Wrapper在業務動作前執行owner gate；
Core只做60秒內detached dispatch，長job timeout與terminal receipt仍由compute executor
擁有。

**因果退役gate**：physical bootout前不只要求scheduler成功；還必須找到activation後
的natural Core fire，並讓指定downstream compute smoke以
`schedule_dispatch.fire_key`回指同一份success receipt。任何一邊缺失、失敗或key不同，
`reconcile_schedule_owners --apply`都會在live mutation前拒絕。

**回歸與live read-back**：compute／owner／scheduler相鄰範圍 **144 passed**，
Matt Spec／Standards雙PASS。07:45 natural fire
`operations-core-v1:volpred-compute-worker:133ccb319bd393968dde017b`
attempt 1／exit 0；priority-0 smoke同秒completed／exit 0，回讀55/55 Core、legacy 0且
fire key exact match。Gate放行後只bootout `com.volpred.compute-worker`；
`launchctl print`回113/not found，targeted audit
`conflicts=[]`、`dormant_legacy_surfaces=[]`，同時detached Core executor仍持續跑K781，
證明工作未被誤停。此漏網clock類根因為
**`root_cause_fixed_and_verified`**；Issue #46其他capability與14-day sustained-clean
仍保持OPEN／contained。

---

## 2026-07-29 — K1380_v4 的 RC/SPA 兩個欄位都標錯，且方向相反（Paper 9 C3 canonical 指標）

**類型**：統計方法誤標 → 對外結論失真（AGENTS.md 第 13 條回溯更正）

**發現路徑**：2026-07-29 hourly slot-1（37c1e7e0）承接
`k1380_v4_white_rc_snooping_correction_20260729`。前一班（e98b43fc）在裁決
`k1380_stage_refactor_collect` 時讀 code 發現 `white_rc_test` 非 RC，狀態停在
`contained`（只證據化、未修）。本班完成修復與驗證。

**錯誤內容**：`experiments/K1380_v4/k1380_v4_results.json` 兩個檢定欄位都名實不符 ——

1. `white_rc_test`（p=0.000，宣稱「after RC correction」）實為**單一 spec 的 bootstrap
   DM t 檢定，零窺探修正**。`k1380_v4.py:771-782` 的 `max(0.0, t_b_a4f)` 是對純量取
   max，而 White 的 Reality Check 定義上是跨候選集合的 max 型統計量。→ **高估顯著性**。
2. `hansen_spa_test`（p=0.2886，不拒絕）實為 **least-favourable 的 SPA_u**
   （每個 spec 用自己的 d-bar 置中 = studentized White RC），不是 Hansen (2005) 建議
   回報的 consistent SPA_c。→ **低估顯著性**。

第 2 項是本班新發現：先前把它當成「有做多重檢定修正所以可信」的對照組，因此得出
「真正修正過的檢定沒有拒絕」。該讀法建立在一個同樣有缺陷的數字上。

**根因**：兩處都是「按統計方法的名字命名欄位，但實作的是另一個統計量」，且沒有任何
斷言把實作綁回定義（max 型統計量必須跨 spec 取 max；SPA 必須報 c 變體）。

**修復**：`experiments/K1380_v4/k1380_v4_rc_correction.py` 純重新分析 —— `k1380_v4.py:693`
在檢定前已存下完整 17×n_oos QLIKE 矩陣，缺陷全在其下游，**不需重跑 GARCH**。腳本以
**逐位重現 v4 四項數字**（atol=1e-12）為前置斷言，重現失敗即中止；再計算 Hansen 三重
recentering（u/c/l，斷言 p_l ≤ p_c ≤ p_u）、古典非 studentized White RC、以及 Holm
step-down。v4 原始 JSON 未被修改。

**驗證與新結論**：499 次 bootstrap 中 144 次超過觀測統計量，其 max **全部**由
A5(t=-11.2)/C2(t=-21.1)/C3(t=-10.0) 三支遠差於 benchmark 的 spec 取得（77/48/19），
無一次由具競爭力的 spec 取得 —— v4 的「不顯著」量到的是這三支的退化程度。修正後
SPA_c p < 1/499（fixed-omega 與 per-resample 兩種 studentization 慣例下皆然），
Holm 在 FWER 0.10 下 15 支中 11 支拒絕。**聯合窺探修正後的檢定拒絕 H0** ——
與先前記載的方向相反。

**影響面**：Paper 9 C3 在本單收斂前不得以任何一個舊口徑書寫。C3 verdict 由
`C3 MIXED` 更新為 `C3 POSITIVE (snooping-adjusted)`，canonical 數字改指
`k1380_v4_rc_correction_results.json`。

**遺留（未關）**：A5/C2/C3 的極端損失可能是數值退化本身。SPA_c 依統計理由捨棄它們，
但若它們是壞的就不該是候選。已開 followup 追查 + Codex 二審修正腳本。

---

## 2026-07-29 — Issue #46：orphan reaper 把「無主」誤當成「可進 main」，並以非原子 Git 交易收件

**證據化症狀**：K1694 在正式 Codex review 為 FAIL 後，`experiments/` orphan sweep
仍可把結果、spec 與衍生檔收進 main；同時 reaper 的舊交易會直接操作共用 index，
以一般 commit 前進 HEAD，失敗清理由 path-scoped reset 收尾。這使「作者 session 已結束」
被錯當成研究 admission，且 pre-commit hook 或不合作的外部 writer 若在交易途中前進
HEAD，reaper 沒有一個不覆蓋他人 commit 的 compare-and-swap 出口。

**根因層級**：

1. `experiments/` 的 ownership 與 research admission 共用同一個 `default=adopt` 判斷；
   reaper 沒有要求完整 experiment directory、artifact gate、byte-bound review、
   methodology gate 與 K-id registry 同時成立。
2. admission 讀 working tree 的 knowledge、exclusion、baseline 與 registry；未提交的外部
   工作可能替同一批候選提供「已通過」證據，政策與產物不在同一個 Git snapshot。
3. Git writer lock 只序列化合作 writer，舊 commit 路徑仍缺少 exact parent/scope/blob
   read-back 與 ref CAS；失敗後的補償式 reset 不能安全處理不合作 writer。
4. active frontend 是私有 `yhlai0911/volpred-v2`，但 target config 只記本機目錄。
   clean clone／GitHub Actions 因而拿不到前端，讓 route parity 與型別 gate 在「本機有殘留
   checkout、CI 沒有」兩種拓撲間漂移。

**底層修復與制度化**：`config/orphan_namespaces.json` 將 experiment 的 atomic unit
提升為第一層 directory，整個單位必須一起通過 `experiment_ready_for_main`；checker
只從同一個 committed HEAD 讀 knowledge、exclusion、baseline、K-id registry 與 namespace
policy，再把 admission 綁到每個待 stage blob 的 SHA。未知 gate、dirty policy、HEAD
漂移、刪除／改名中的不完整目錄一律 fail closed。Commit path 要求全域 index 起始乾淨，
執行正式 hooks 後重驗 exact staged scope/blob，以 `write-tree` 與 detached
`commit-tree` 建立候選，再驗 parent、tree scope、blob，最後只做一次
`update-ref HEAD <new> <expected>` CAS；外部 HEAD 若先前進，外部 commit 保留且 reaper
不做 ref rollback。

active frontend 的 canonical target 同步補上 private repository 與 immutable revision；
GitHub Actions 以 read-only deploy key checkout 該 revision，不再依賴 root repo 內的
偶然巢狀 checkout。K1694 未通過 review 的衍生 artifacts 已回滾，只保留原始碼與原始
cache；正式產品／交易日曆的 follow-up 已進任務池，不阻擋平台復機。已合併且通過 review
的 K1727、K1812 knowledge 則單獨同步，避免 artifact CI 因另一個 session 的未合併研究
而整體停擺。

**狀態**：本機 affected-suite 與 private frontend gate 已通過；本條在 GitHub CI、
Operations Core deploy 與 live read-back 完成前維持 **`contained`**，不得宣稱
`root_cause_fixed_and_verified`。

---

## 2026-07-29 — immutable supervisor 身分不可繼承到 canonical／provider child

**證據化症狀**：immutable release cutover 後，dispatch supervisor 每分鐘的 admission
settlement 都回 `task_pool_cli_failed rc=1`，沒有新 worker。以 live daemon 的
`VOLPRED_SUPERVISOR_RELEASE_*`、`VOLPRED_SUPERVISOR_BOOTSTRAP_SHA256` 與
`VOLPRED_CANONICAL_REPO_ROOT` 重播 canonical
`scripts/task_pool_claim.py dispatch-pending`，可 100% 重現
`ModuleNotFoundError: No module named 'scripts'`；移除 release marker 後則正常進到
`supervisor_capability_required`。Queue validator 同期為 0/3569 invalid，child PPID
也精確指向 supervisor，故不是壞資料或 parent-proof 誤拒。

**根因層級（process identity／import provenance contract）**：release marker 是
daemon 本身的 process-scoped identity，bootstrap 卻讓所有 subprocess 原樣繼承。
Canonical child 並未由 pinned loader 啟動，但 `volpred.ops` 看到 marker 後改走 pinned
語意，造成 import path 與 writer capability 判斷錯置。原 `_task_pool_command` 又把空
stdout 解成 `{}` 並丟棄 stderr，live 只剩 generic failure，掩蓋真正 traceback。

**底層修復與制度化**：新增 dependency-free
`dispatch_supervisor.child_env.external_child_environment()`；在套用 overrides 後統一
移除所有 `VOLPRED_SUPERVISOR_*`、`VOLPRED_DEFERRED_RELOAD_*` 與
`VOLPRED_CANONICAL_REPO_ROOT`，但保留 PATH、HOME、OAuth、actor、task owner、
provider receipt 與 Git writer lease。Task-pool、pregate、send-alert、Claude、
Codex preflight／reachability／worker、PHASE-Z pre-fire／clone pytest／trusted hook、
workspace merge 全部走同一邊界；stage0→bootstrap 是唯一刻意保留 pinned identity 的
chain。Task-pool 非零退出同時保留 bounded stderr，避免同類事故再被 generic rc
靜默化。

**回歸與狀態**：各邊界先有可重現 RED，再修成 GREEN；bootstrap→grandchild E2E 也斷言
private identity 為空，supervisor／PHASE-Z／workspace／release／task-pool affected
suite 共 **460 passed**。在 immutable live reload、新 worker completion receipt、
連續 scheduler tick 與通知／pregate read-back 完成前，本條仍為 **`contained`**。

---

## 2026-07-30 — Alert 全量鏡像 Telegram，且 durable email conflict 被誤報成 host cron failure

**證據化症狀**：`send_alert()` 曾把每一封 INFO／復原／self-heal 告警都直接鏡像
Telegram，與 `progress_report.py` 的即時進度 owner 重疊；同時相同
`level+title+date` 的 owned-email command 若 body 或路由用途改變，會命中 durable
idempotency conflict。例外向外冒泡後，包住 `check_alerts` 的 cron wrapper 只看到非零
退出，下一輪把 notification transport failure 報成 `host_cron_fail`，使用者收到錯誤
根因與重複通知。

**根因層級**：通道 policy 用 severity／「每封都鏡像」取代 remediation disposition；
Telegram 有兩個外送 owner；email effect key 沒綁 payload identity；typed command
conflict 沒有在 transport boundary 轉成可觀測 receipt，incident candidate 也缺
effect evidence。

**底層修復與制度化**：維持 `send_alert()` 公開 signature 與既有
`sha256(level + "\\0" + title)` 24h 去重契約，另以 typed `AlertDeliveryClass` 做內部
路由。Telegram 回到 `progress_report.py` 單一 owner；owner decision／recovery／record
走 email，自動建單與 self-heal 只進 incident lifecycle，持續失敗才升級。Owned-email
command key 加入 payload hash，route transition 不再被舊 record 擋住；typed
`OwnedEmailCommandConflict` 轉成 `send_error_code=owned_email_command_conflict`，
並把 effect owner／generation／work id／evidence 寫入 incident candidate。所有新版
alert email 標題統一加 `[新架構派發]`。

**回歸與狀態**：alert、incident lifecycle、CI recovery、owned-email、Postgres effect
affected suites 共 **293 passed**，Spec／Standards 兩軸 review 均 PASS。production
smoke `effect_owned_email_c737f1e75e5172720523bf6723459c35` 由
`operations_core` generation 4 以 attempt 1 delivered，Gmail Sent evidence SHA
`8e71849f3b2718b16d3228366dd3b700a1654923865c354711477278d8e1d470`；receipt 回讀
`email=delivered`、`telegram=not_routed`，標題為
`[新架構派發][VolPred Alert][INFO] 通知路由上線驗證`。本 incident slice 已完成五步
Gate，狀態為 **`root_cause_fixed_and_verified`**；Issue #13 umbrella 的其他 acceptance
仍各自驗收，不因本條自動關閉。

**2026-07-30 review follow-up**：Spec review 另抓到 `task_pool_claim.py` 的 burst
completion 仍直接呼叫 Telegram，形成第二個「進度」owner；而 schedule、Telegram
handshake 與 transport docstring 還宣稱 alert mirror／正常入池立即 ack。以公開
`cmd_complete()` 先做 RED，證明 active burst 會繞過 `progress_report.py`；修後 burst
只保留 completion-driven `request_fire`，不再外送 Telegram，下一工仍在空槽時立即
推進。互動回覆、逐程序進度、GitHub typed notification 與 alert email 的 owner
矩陣已同步回 canonical schedule／ops manual／handshake。相鄰
task-pool／burst／notification／Telegram／schedule suites **320 passed**，因此這個
旁路也達 **`root_cause_fixed_and_verified`**。

---

## 2026-07-30 — Starvation lockout 把 generic hourly worker 鎖在不可 claim 的 mutating tasks

**證據化症狀**：hourly fire 三次看到 `STARVATION LOCKOUT` 只列
`platform_ops`／`governance`，隨後同一 fire 呼叫 claim 必定得到
`supervisor_preassignment_required`。最後一個可 claim 的 experiment 被前班收走後，
106 筆 pending 中仍有工作，generic slot 卻只能 idle；而修復此問題的 task 自身也是
`platform_ops`，故 hourly fire 亦無法認領。

**根因層級（selection／admission composition contract）**：
`continue_task_dispatch.build_report()` 把 schema 上 agentable 的 mutating task 直接放進
generic worker 菜單，但 `task_pool_claim.cmd_claim()` 已要求這兩類工作必須在 spawn 前
由 supervisor 綁 execution contract。兩個局部正確的 policy 各自保存 task-type
清單，沒有共用「需 supervisor preassignment」判定；starvation lockout 又只看前者的
候選集，因此會把所有真正可 claim 的工作排除在外。

**底層修復與制度化**：`task_pool_selection.requires_supervisor_preassignment()` 成為
唯一 predicate，由 direct claim gate、supervisor preassign 與 dispatcher 同時使用。
Dispatcher 保留完整 `agentable` 統計，但把 generic worker 菜單拆為
`worker_claimable` 與 `supervisor_only`；starvation 只鎖前者。報表另輸出
`supervisor_preassignment.required_count/tasks/hourly_claimable=false`，文字輸出明示
`SUPERVISOR-ONLY`，所以缺 execution contract 的 mutating backlog 仍可觀測，卻不再
令 generic slot 空轉或誘使 worker 繞過 claim gate。

**回歸與 live read-back**：最小 compose test 先 RED（菜單只含
`starved_platform_ops`），修後同一情境改列 fresh experiment，兩個 mutating task
完整留在 supervisor bucket。Dispatcher／lane／dry-run／claim／preassign 相鄰範圍
**146 passed**。Production queue 的 read-only dry-run 回讀
`agentable=98`、`worker=23`、`supervisor=75`，並逐項列出 supervisor-only tasks；
現場仍因另一個 PHASE-Z incident 將 slot cap 降為 2 且當下 2/2 occupied，故須等自然
空槽再取得「實際不 idle」的 terminal fire receipt。本條在該 receipt 前維持
**`contained`**。

---

## 2026-07-30 — durable reload request 可被下一班 fire 永久餓死

**證據化症狀**：immutable reload request `749b49b3…` 於 00:59 CST 已 durable
寫入，目標 release commit `1a80230c3`；舊 supervisor 在先前 cohort 清空後，卻於
01:17 CST 再 admission worker `5738de9c…`。因此 health loop 始終讀到
`current_jobs != []`，無法進入 release activation；下一班又可在 health 的 30 秒 tick
前搶先補回 slot，使「自然 drain 後上版」沒有必然收斂保證。

**根因層級（deployment intent／scheduler admission concurrency contract）**：
`deferred_reload.process()` 只在 health loop 端等待空槽，但 scheduler admission 不知道
durable reload intent。即使加一次普通 `active.json` 檢查，request 仍可能在 check 與
`state.reserve_fire()` 之間寫入，留下 TOCTOU。Reload root lock 原本只序列化
arm/process，沒有涵蓋最後的 worker reservation。

**底層修復與制度化**：scheduler 在完成既有 worker／PHASE-Z closeout 後、任何新
派工副作用前，先以 validated `active_request_pending()` 關閉 admission；最後把
fire-demand expected-value CAS／consume 與 `reserve_fire()` 收斂成同一個 state-lock
transaction，再把整個 transaction 包入 arm/process 共用的 `admission_gate()`。因此
只有兩種合法排序：reload intent 先 durable，則新 fire 不得 reserve 且 demand 原封
不動；或 reservation 先完成，後來的 reload request 必讀到 in-flight job 並等待完整
closeout。Sibling completion 在 admission 期間寫入 PHASE-Z 時，reservation 會在 consume
前 fail closed，urgent demand 仍完整保留。Malformed／不安全 request 一律 fail closed；
不 force kill worker。測試另將 reload root 自真實 `~/.volpred` 隔離，避免 production
deploy 狀態污染 unit test。

**回歸與 live read-back**：live race 的 tight test 修前進入 worker 路徑而 RED，修後不執行
pre-fire／worker 且保留 `last_fire_at`；另有 deterministic race 鎖住
early-check=false、final-gate=false 時 `fire_requested_at`／reason 不得遺失。
Validated active request、malformed fail-closed、self-reload、wrapper、scheduler 與
durable fire lifecycle 相鄰 suite最終 **336 passed、1 skipped**，Matt Spec／Standards
雙 PASS。修正 commit=`983a8eaf5`。

Production 沒有 force kill：舊 worker `5738de9c…` 與競態期間再被舊 release 收進來的
`11ba9644…` 都自然 `exit=0`，PHASE-Z 完整收尾。切換期間以 token-owned
`cutover_quiesce` 向舊 release 相容地設 `auth_blocked=true`，所以第二個 worker
完成後沒有第三個 stale admission。最新 immutable release commit
`451f9bf61cc0…` 於 02:04:40 CST fresh boot，確認同時包含 `983a8eaf5` 與通知路由
`9a15cede8`；planned-reload restart 通知被正確抑制。

最後另建立控制性 durable request `9b5db49d2642…`，隨即由真實 Unix-socket trigger
送入 Operations Core tick；live decision 精確回傳
`{"action":"skip","reason":"deferred_reload_pending"}`，`current_jobs` 保持 0、
`last_fire_at` 未改、沒有 pre-fire 或 worker。該 request 隨後以相同 release
fresh boot，terminal receipt
`~/.volpred/run/dispatch-supervisor-reload/receipts/9b5db49d2642792e7cf8a20588a443f62b4814081f28ac128a7ca07ddb002f6c.json`
回讀 `state=completed`、observed source SHA 與 supervisor generation 相符；最終
`auth_blocked=false`、`cutover_quiesce=null`、`current_jobs=[]`。本 incident 五步
Gate 已完成，狀態升為 **`root_cause_fixed_and_verified`**。

---

## 2026-07-30 — Issue #42 request CAS 只比 reason，且舊測試誤要求 dry-run 吞 demand

**證據化症狀**：GitHub Actions run `30477972221` 在
`test_requested_fire_consistency_and_request_consumption` 失敗。`983a8eaf5` 已把正式
fire 的 request consume 移進 reservation transaction，但舊測試仍要求 dry-run 清除
`fire_requested_at`。進一步用同一 reason 連續呼叫兩次 `request_fire()`，可證明正式
reservation 的 expected-value CAS 只比較 reason；第二個較新的 request 會被舊 decision
視為相同並清掉。

**根因層級（dry-run contract／request identity／admission state machine）**：
H4 canonical design 規定 dry-run 除 `last_fire_at` 外不得改 dispatch state，Issue #42
也規定只有 reservation 成功才 consume demand；但舊測試把「同一 Decision」誤擴張成
「同一副作用」。同時 request 沒有不可變 identity，`fire_request_reason` 這個展示值被
錯當 CAS token，形成 same-reason ABA。

**底層修復與制度化**：dry-run 恢復 observational demand 語意，只保留既有
`last_fire_at` tracking；正式 `request_fire()` 為每次 demand 產生 UUID
`fire_request_id`，scheduler snapshot 與 `reserve_fire()` 在同一 state-lock
transaction 內同時比較 reason + identity，reservation 成功後才一起清除三個 request
欄位。升級前已存在的 pending request 不重設 state，而以原
`fire_requested_at` 形成穩定的 `legacy:<timestamp>` identity。

**回歸與狀態**：原 CI symptom、same-reason replacement、scheduler CAS retry、
request disappearance 與 legacy timestamp migration 共 5 個焦點測試通過；Matt
Spec／Standards 重審均 PASS、Ruff F 與 diff check 通過；包含最後兩個 reviewer
regression 的完整 dispatch/reload suite **341 passed、1 skipped**。GitHub Test Suite
run `30480617870` 與同一 HEAD 的 Source Encoding、Data Baseline、Silent Fallback、
Experiment Artifacts 四道 gate 全綠。immutable supervisor release
`f9a5d1a9191b0c9039e90b291baf47df88cb02e42ba9f9c07cb1dbda663849ed`
已載入修正 commit `b676122e087d54ef480c081f97910f80168964d0`；terminal receipt
回讀 `state=completed`，release archive SHA-256
`ee1cce9df1deeaa18cf0342250f182541410c3b45b724c9ff752457c33c46434`，
live status heartbeat 新鮮、`current_jobs=[]`、`phase_z_pending=[]`、
`auth_blocked=false`。本 incident 五步 Gate 已完成，狀態升為
**`root_cause_fixed_and_verified`**。

---

## 2026-07-30 — CI watcher live wrapper source 未安裝的 sibling `cron_lib.sh`

**證據化症狀**：Operations Core 的 `ci_watch` 每五分鐘都有執行主要 Python
檢查，但 `storage/logs/cron/ci_watch.log` 在每次 fire 前後都記錄
`cron_emit_start: command not found` 與 `cron_emit_exit: command not found`。
canonical 與 live `cron_ci_watch.sh` bytes 一致，因此不是一般 wrapper drift；
實際回讀 `~/.volpred/bin/cron_lib.sh` 不存在。

**根因層級（deployment dependency contract）**：
`sync_cron_wrappers.py` 明確把 `cron_lib.sh` 列為 `NOT_INSTALLED`，設計上所有 live
wrapper 都應 source repo 內 canonical helper；但 `cron_ci_watch.sh` 是唯一從
`${SCRIPT_DIR}/cron_lib.sh` 載入的 wrapper。既有 manifest gate 只驗 wrapper 自身
bytes／mode／population，沒有驗「已安裝 wrapper 不得引用刻意不安裝的 sibling」，
所以 canonical=manifest=live 全相等仍可部署壞掉的依賴。

**底層修復與制度化**：`cron_ci_watch.sh` 改為 fail-closed source canonical repo
helper；manifest gate 新增全 population invariant，任何 installed wrapper 再引用
`${SCRIPT_DIR}/cron_lib.sh` 都會在 CI 失敗。RED 精確抓出唯一 offender
`cron_ci_watch.sh`，修後 cron wrapper／owner gate／alert script affected suite
**51 passed**，bash syntax與diff check通過。commit `d4e0a8e07` 從 canonical main
經 `sync_cron_wrappers.py --apply` 原子安裝，完整 live population read-back
`ok=true`、drift 0。03:00 CST 自然 Operations Core fire 留下 start marker，CI
run `30480617870` 回讀 `conclusion=success`、`phase=recovered`、
`reason=healthy_no_incident`，最後留下 exit 0／duration 2s 與
`cron_mark_last_run` acknowledgement；同一時點 schedule owner audit仍為 56/56
Operations Core、legacy 0、conflict 0。本 incident 五步 Gate 已完成，狀態為
**`root_cause_fixed_and_verified`**。

---

## 2026-07-30 — daemon audit runtime log 被 Git 追蹤，反覆觸發 PHASE-Z foreign incident

**證據化症狀**：fresh `volpred.ops.foreign_incident --check` 顯示多筆 stuck-files incident
共同只剩 `storage/logs/trending_primary_source_verification.jsonl`；該檔由
`scripts/refill_reader_facing_pool.py::_log_trending_verification` 在排程執行時 append，
但仍在 `git ls-files`，且沒有 ignore policy。migration 前 live 檔為 9 行、
1443 bytes、mode 0644、SHA-256
`eabfe83dc262c5d13b2f180b856159632947c7ee2a8f563af376ecc2a8962e55`。

**根因層級（Git ownership／runtime-state contract）**：producer 已是 runtime daemon，
但其 append-only audit output 仍由 Git 宣告 ownership。PHASE-Z 因此只能把正常 machine
churn 看成共享 checkout 的未知作者；這不是 dedup、recognizer 或警報文案問題，繼續新增
例外只會重複 cleanup layer 猜 ownership 的舊錯誤。

**底層修復與制度化**：committed `.gitignore` 宣告 runtime ownership，並透過 generic
`git_writer_lock.py untrack-preserve` 的 exact-HEAD transaction 移出 index，不刪除 live
artifact。repository-level regression 同時要求 `git check-ignore --no-index` 成功且
`git ls-files --error-unmatch` 失敗，防止日後重新追蹤。migration 前後 live 檔的
SHA／bytes／mode 完全一致。

**回歸與 production read-back**：runtime Git ownership、Git writer recovery、
legacy-retirement migration 與 reader-facing refill 共 **79 passed**。production
reconciler 隨後自動關閉 `assign_0c1eca40` 及另外 13 筆同源 incident；slot budget 回讀
由 incident cap 2 恢復 baseline 4、P1 backlog 0、`auth_blocked=false`。Matt
Standards／Spec review 均 PASS。此 bounded slice 五步 Gate 已完成，狀態為
**`root_cause_fixed_and_verified`**；Issue #41 完整 acceptance 仍被 #9 及全域
writer inventory／recognizer retirement 阻塞，故 umbrella 維持 OPEN／`contained`。

---

## 2026-07-30 — compute queue 在非 UTF-8 locale 下寫中文 argv 於 durable write 崩潰

**證據化症狀**：fire `slot-1 39e21e0f` 以中文 `--title` 呼叫
`compute_queue.py enqueue-agent`；argv 已被 Python `surrogateescape` 解成 lone
surrogates，直到所有 admission checks 完成、`_write_job_file` 寫 UTF-8 receipt 時才拋
`UnicodeEncodeError: surrogates not allowed`。TDD 以相同 surrogateescape bytes 經正式
`main()`／`enqueue-agent` seam 重播，修正前 traceback 精確落在同一 writer。

**根因層級（process argv encoding boundary）**：queue writer 的 atomic replace／fsync
契約正確，但 parsed CLI namespace 沒有編碼邊界；要求 caller 改 ASCII 或逐一清洗
`--title` 只會保留同一 root class，因 `--script-args` 等序列欄位也可能帶入相同 bytes。

**底層修復與制度化**：commit `f3c504abd` 在 argparse parse 完成、分派任何 subcommand
之前一次正規化完整 namespace。合法 UTF-8 bytes 由 surrogateescape round-trip 還原成
原字串；真正無效的 byte sequence 才以可觀察 warning replacement 降級。list／tuple
argv 同走該 process boundary，不新增 caller workaround，也不改 durable writer 語意。

**回歸與 read-back**：全新 `LANG=`／`LC_ALL=`／`PYTHONUTF8=0` process 中，中文
`enqueue-agent` regression 成功寫入 receipt 且回讀 title 完整為 `中文派工`；相鄰
compute queue suites **104 passed**，Ruff F/E9、py_compile、diff check 與 Matt
Standards／Spec review 均 PASS。完整 repository suite 為 **6568 passed、3 skipped、
20 failed**；20 項全部位於未修改的 dispatch-supervisor／agent-auth 測試，失敗證據為
live macOS producer coalition 不靜止與本機注入政策禁止的 `OPENAI_API_KEY`，未把它們
冒充本 task 綠燈。本 Unicode incident 五步 Gate 已完成，狀態為
**`root_cause_fixed_and_verified`**；相鄰 20 項環境隔離問題仍須另行根因收斂。

---

## 2026-07-30 — PHASE-Z 首次建單未持久化 derate verdict，active WIP 被錯降載

**證據化症狀**：production `assign_cf82928c` 的 fresh assessor 回讀
`closeable=false`、`derates=false`、31 個路徑全部 deferred、blocker 0；同一時刻
`dispatch_slot_budget.py` 卻回傳 cap 2，理由指向同一 task／fingerprint。queue row
顯示 `payload.derates` 與 `derates_updated_at` 都不存在。deterministic regression
重播「第一班 PHASE-Z 建單 → durable queue → slot admission」，修正前精確以
`KeyError: derates` RED。

**根因層級（incident lifecycle ordering contract）**：
`_open_stuck_incident()` 先 reconcile 既有 incident、再 upsert 新 incident。新 row
因此不可能在建立當班取得 canonical verdict；slot budget 對缺值採安全的
`default=True`，卻因此把已 quarantine 且仍在 24 小時 authoring grace 內的活躍工作
誤當無主殘留，至少錯降載一班。問題不在 fail-safe，也不在 grace 門檻，而是 assessor
結果沒有接到新 row 的首次生命週期。

**底層修復與制度化**：PHASE-Z 現在對無 stuck 路徑先收斂既有 incident；有 stuck
路徑則先由 canonical writer upsert，再在同一 fire lifecycle 立即呼叫唯一
`foreign_incident.reconcile_incidents` 持久化 verdict。slot budget 保持 read-only，
沒有複製 git／coverage／grace 邏輯；reconcile 失敗時仍保留缺值 fail-safe 降載。
首班 regression 同時要求 durable `derates=false` 與後續 cap 非 DERATE，另將兩組 cap
測試的 occupancy 隔離到 `tmp_path`，消除本機 worktree／agent receipt 造成的
CI-parity 漂移。

**回歸與 production read-back**：PHASE-Z foreign-incident／slot-budget suites
**42 passed**，quarantine／ownership suites **59 passed**，Ruff F/E9（changed tests；
PHASE-Z E9）、py_compile、diff check 均通過；Matt Standards／Spec review PASS。
production reconcile 不關閉任何 WIP，五張 incident 仍為 pending，但都寫入
`derates=false`；`assign_cf82928c` 31/31 deferred。slot budget 隨後由錯誤 cap 2
回到 baseline 4、`open_incident=null`、free 2。此 bounded lifecycle root class
五步 Gate 已完成，狀態為 **`root_cause_fixed_and_verified`**；Issue #44 的完整
Producer Isolation／recognizer retirement acceptance 仍維持 OPEN／`contained`。

---

## 2026-07-30 — GitHub 留言逐則 Email＋Telegram 鏡像造成雙通道通知暴增

**證據化症狀**：`github_comment_notifications` 每五分鐘輪詢一次，舊 v2 contract
對每則 Issue／PR 留言各送一封 Email 與一則 Telegram；production 觀察到同一 Issue
在 85 分鐘內形成 4 Email＋4 Telegram。這些訊息是同一來源的重複鏡像，不是需要即時
打斷 owner 的 incident。

**根因層級（notification routing／durable state contract）**：ingress cadence、
owner visibility 與 escalation channel 被綁成同一件事。comment id 雖有 durable
receipt，但缺少 thread-level aggregation window；Telegram 也沒有單一責任邊界。
直接降低 poll 頻率會延遲 ingestion，單純關 Telegram 則會讓 v2 partial-delivery
狀態在 schema migration 時有漏信或重送風險。

**底層修復與制度化**：state schema v3 將每則完整 comment 先持久化到 Issue／PR
專屬 batch，再前進 source cursor；每個 batch 使用固定 15 分鐘 window，新留言不延長
舊 window，逾期才被觀察的留言另開下一窗。incremental owner visibility 改為一封
Email 摘要，Telegram 僅由互動／progress pipeline 使用。Email 仍使用
`in_flight → delivery_unknown` fail-closed receipt，`pending`／`failed` 可重試；
v2 delivered／partial／indeterminate 狀態均有顯式 migration，避免部署時重播或遺失。
canonical `runtime_schedules.json` 同步記錄 cadence 與 channel ownership。

**回歸驗證**：固定窗邊界、同 thread 合併、跨 thread 分離、Email retry、crash
unknown、cursor repair、v2 delivered／pending／failed／in-flight／unknown migration、
CLI exit semantics 與 scheduler contract 共 **25 passed**；Ruff、py_compile、
JSON schedule parse 與 diff check通過；Matt Standards／Spec review均 PASS。
production schema v3 migration 後，Issue #13 留言在固定窗到期的自然 Operations Core
fire 只產生一筆 Email durable receipt（subject 含 `[新架構派發]` 與「留言摘要」），
delivery 的 `receipt_keys` 僅有 `email`、沒有 Telegram，cursor／batch terminal state
均回讀一致。此 GitHub dual-channel burst root class 五步 Gate 完成，狀態為
**`root_cause_fixed_and_verified`**；24 小時頻率／資訊性 sustained audit 仍是上位
notification policy 的獨立驗收條件，不因單一自然 receipt 而宣稱整體通知已完成。

---

## 2026-07-30 — handoff 將歷史 worktree 目錄誤報為 active slot

**證據化症狀**：每小時 handoff 顯示 `slot 占用 13 / 4`，同時 Operations Core
agent dispatch 的 canonical live admission 只觀察到在途 producer，沒有 13 個
active workers。13 個名稱全是 `.claude/worktrees/` 現存目錄；其中多數已長期無進度。

**根因層級（observer ownership split）**：`dispatch_slot_budget.py` 早已用
HEAD／dirty mtime 與 4 小時 TTL 區分 live/stale，且同時擁有動態 cap 2／4／6；
`generate_handoff.py` 卻另以「目錄存在」重算 occupancy，並硬編 cap 4。handoff 因此
復活已淘汰的 artifact=lease 推理，與真實 scheduler admission 分岔。

**底層修復與制度化**：handoff 改為直接投影 canonical `budget()` 的 cap、
occupancy、live identities 與 stale count，不再重算 TTL 或目錄數。agent metadata
也由同一次 canonical classification snapshot 回傳，消除 classifier 後二次讀檔的
TOCTOU。invalid JSON root、status type、UTF-8、queue row／priority 均會留下 warning
並釋放假 slot，不會讓 observer crash；stale artifacts 仍顯示數量但明確不占 slot。

**回歸與 read-back**：RED 證明舊 observer 把一個 live＋一個 stale 目錄顯示成
2/4；dynamic 2／4／6 cap、stale exclusion、metadata snapshot、四類 corrupt agent
receipt、malformed queue 與 PHASE-Z incident reader 共 **85 passed**，Ruff E9/F/I、
py_compile、diff check通過；Matt Standards／Spec 複審 PASS。live canonical build
由錯誤 13/4 收斂為 3/4，另顯示 11 個 stale artifacts 不占 slot。此 observer
root class 五步 Gate 完成，狀態為 **`root_cause_fixed_and_verified`**；不代表
Issue #44 的 Producer Isolation／recognizer retirement umbrella 已結案。

---

## 2026-07-30 — Operations Core read-only RPC 繞過測試的 no-remote-read gate

**證據化症狀**：GitHub Test Suite run `30473391569` 在
`test_phase_z_test_gate_red_records_machine_self_without_a_task` 讀取 notification
owner 時，CI 因沒有 production Supabase secret 而報 `Supabase URL and service-role
key are required`。原測試的錯誤 monkeypatch 已由 `3c14e0a57` 止血；進一步以四個
side-effect guard 全開重播，`SupabaseOwnedEmailStore` 的兩個 read-only RPC 仍會進入
`urlopen`。同類掃描也發現共用 `ServiceRoleRpcClient` 具有相同旁路。

**根因層級（test egress contract）**：`VOLPRED_NO_REMOTE_READ` 的正式 chokepoint
只存在於舊 `scripts/supabase_sync.py::_urlopen`；後來新增的 Operations Core
PostgREST transports 各自直接呼叫 `urllib.request.urlopen`，只區分 read/write 以套用
write guard，卻沒有在 read RPC 前套用 read guard。測試因而可能依賴 production
資料，並把缺 stub 偽裝成 secret 或當日資料差異。

**底層修復與制度化**：owned-email 專用 transport 與共用
`ServiceRoleRpcClient` 都在任何 request encoding／transport 前，依 canonical
read-only RPC inventory 加 `volpred_read_*`／`read_volpred_*` 命名 ratchet 檢查
`VOLPRED_NO_REMOTE_READ=1` 並 fail loud；`volpred_read_primary_authority_events` 的
漏列也已補回 inventory。RPC mutation
仍只受 write guard 控制。共用 client 的 fake transport 測試必須顯式使用
`mocked_operations_core_rpc_transport` fixture；owned-email 專用 transport 測試則在
安裝 fake 後顯式移除 read guard。兩者都不能靠本機 secret 偷跑。

**回歸與 read-back**：兩條 transport 的 deterministic RED 都證明修正前會進網路
函式；修正後 owned-email／Operations Core RPC／alerts／PHASE-Z／boss-report 相鄰
範圍 **308 passed**。四 guard live no-network probe 分別回讀
`notification ownership remote reads are disabled` 與
`Operations Core RPC remote reads are disabled`。此切片目前為 **`contained`**：
程式、測試與本機 read-back 已完成，仍待 commit 進入 origin 後由新的 GitHub Test
Suite run 回讀全綠，才升級為 **`root_cause_fixed_and_verified`**。

---

## 2026-07-30 — K-COVERAGE 對無 experiment ref 舊文誤報 clean

**證據化症狀**：canonical
`check_arc_dedup.py --k-id k1716 --audience general --title TBD` 對 live feed
回傳 `verdict=clean`，但 `mile_74d12ac6` 已發佈同一個 0DTE／SPY 日內與隔夜波動故事。
該舊文 `details.experiment_refs=[]`，正文也沒有 K 編號；K1716 的結果則明列同題 prior
replication。一般讀者文章 498 篇中有 225 篇缺 experiment refs，這不是單筆髒資料。

**根因層級（coverage observability contract）**：exact K gate 只能證明「有找到相同
K-id」，找不到時卻把「metadata 完整且確定沒覆蓋」與「舊文沒有任何可抽取 K-id」
合併成同一個 clean。arc v4 又因舊文 `descriptive/reader` 與新實驗
`null_no_info/methodology` 的合法軸差異不判 hard duplicate，因此整個 CLI 錯把
「無法精確查」說成「已查且乾淨」。

**底層修復與制度化**：不手改歷史 feed JSON，也不把 lexical similarity 升為 hard
block。共用 `find_k_coverage_gap_hints()` 只掃同 audience、live、且 metadata／正文都
抽不到任何 K-id 的文章；exact K 與 arc 都無判定時，有詞彙重疊便輸出
`warn_coverage_metadata_gap`、列出證據文章並寫 dedup audit。此路徑維持 exit 0
fail-open，但不再給綠色 clearance。

**回歸與 read-back**：deterministic RED 先證明 K1716-like case 仍回 clean；修正後
13 個 K-coverage tests 與 dedup／generator 相鄰範圍共 **182 passed**。live K1716
重播回讀 `warn_coverage_metadata_gap`，第一筆為 `mile_74d12ac6`、overlap 0.238。
此切片目前為 **`contained`**：程式、回歸與 live source read-back 已完成；待正式
commit 進 origin 並取得新 GitHub CI 全綠 receipt 後，才升級為
**`root_cause_fixed_and_verified`**。

---

## 2026-07-30 — loop-health 把同一 dispatch job 的 retry failure 當成最終故障

**證據化症狀**：`loop-health` 持續列出
`dispatch_supervisor:failure:exit1`（count 10、`recovered=false`），但 canonical
`dispatch_state.json` 顯示最新一筆相關工作 `9189c746…` 先在 attempt 1 exit 1，
之後同一 `job_id` 的 attempt 2 已於 16 分鐘後 success／exit 0；supervisor log 與
目前 heartbeat 也都證明工作已成功且 daemon 健康。

**根因層級（observer lifecycle contract）**：dispatch completion ring 保存的是
attempt-level receipts；loop-health 卻逐筆聚合 failure signature，只用「任意較晚成功
且 failure 已過 6 小時」判 recovered。它沒有先依 `job_id` 還原一次 dispatch job 的
終態，因此正常 retry ladder 會被誤判成另一個尚未復原的 production failure。

**底層修復與制度化**：structured-state scanner 現先依 canonical append order 將相同
`job_id` 收斂成最後一筆，且會排除仍在 `current_jobs`／legacy `current_job` projection
中由 supervisor 持有的工作，再做 recurrence 分類。最終成功的 retry 不計 failure；
最終仍失敗的 retry 只計一個 failed job；retry_wait／running 尚無 terminal outcome，
不提早定罪。沒有 `job_id` 的 legacy receipt 無法可靠關聯，維持逐筆相容處理。

**回歸與 read-back**：deterministic RED 先重現同 job failure→success 仍出現在
`top_recurring`，複審再以 RED 鎖定 failure receipt＋同 job retry_wait 的中間狀態；
修正後 loop-health tests **27 passed**。live command 已不再列出
`dispatch_supervisor:failure:exit1`，證明同一 receipt pair 由 active recurrence
移除；其他獨立 signature 仍照實保留。Matt Standards／Spec 複審均 PASS。此切片目前
為 **`contained`**：待正式 commit 進 origin 與 GitHub CI 回讀後，才升級為
**`root_cause_fixed_and_verified`**。

---

## 2026-07-30 — PHASE-Z 路徑集合變動讓同一 incident family 重複寄 CRITICAL

**證據化症狀**：外送 ledger 的固定 dedupe key
`ce0fdba9f1a00af62b4581d40d9d64f8e198ee7dc88b9b83de4be81efb1a35ca`
（標題 `PHASE-Z 無主或過期檔案達處置門檻`）在 2026-07-23 至 07-28 共被呼叫
59 次，中央 dedupe 雖跳過大多數，仍依退避規則於 occurrence
1／6／9／13／26／44 外送六次。這不是 email／Telegram delivery duplication；
每次 PHASE-Z 卡住路徑集合增減都產生 `created=True` 的 successor incident，caller
把每張新 row 都當成新的 page 理由。

**根因層級（incident identity / notification ownership contract）**：task row 的
exact path-set fingerprint 適合追蹤可機械關閉的版本，卻被誤用為 notification
episode identity。只要新舊 path set 有 lineage（重疊或經其他 open row 連通），
就已具備同一個 owner、close condition 與 scheduler consequence；集合增減不會增加
需要 owner 立即知道的資訊。不相交的 set 則可能是另一個根因，不能被舊 row 靜音。
把 task-row identity 直接當 page identity，使中央 dedupe 只能延後噪音，無法從源頭
停止同 episode 的呼叫。

**底層修復與制度化**：`upsert_incident()` receipt 新增 canonical
`page_required`。notification episode 定義為「未關 rows 以 path overlap 形成的
transitive connected component」：`{A}→{A,B}→{B}` 只 page 一次，不相交的 `{C}`
仍是新的根因並獨立 page。page lease 在 canonical queue 的 `LOCK_EX` 內持久化，
同 fingerprint 或不同 fingerprint 的 concurrent creators 都只能有一個 lease；
successor supersede 時 lease／delivery acknowledgement 也會轉移；若 wider set
合併兩個已 lease 的 roots，所有 in-flight tokens 會先合併到 live lineage，任一
predecessor 的成功 receipt 都沿 `superseded_by` 寫到 live successor；只要仍有 token
未過 10 分鐘，下一班不得再 mint 第三個。只有 alert receipt 證明 sent 或同 episode 的 24h transport
dedup 後才標 durable delivered；`sent=false` 立即釋放，crash 未 settle 則 10 分鐘
後自動重試。舊 schema rows lazy migrate 為
已通知，不因部署重寄。incident 使用 fingerprint + episode generation 衍生
deterministic id 並繞過 generic semantic matcher，普通 task 不再能吞掉 incident，
terminal 後同 fingerprint 也能重開。首次 root 的 id 另持久化為
`family_transport_id`；multi-root merge 同時保留所有 predecessor transport aliases
與各 lease 原始 key。retry 會把 aliases 一併交給中央 24h ledger，任一 predecessor
已送達但在 settlement 前 crash，都會以 `dedup_24h` 收斂而非再寄第三封。
delivery acknowledgement 在同一 queue lock 內投影到整個 open overlap component，
因此 AB 關閉後 BC 仍保有 family receipt。A→AB crash retry 仍用 A 的 key；
disjoint family 或 e2 recurrence 才換 key，不會誤用 A/e1 的 delivery receipt。
schema 0 才做「舊 row 已通知」migration；schema 1 的 scalar lease 會無損正規化成
schema 2 list，active 繼續等待、expired／released 照常 retry，不會被升級誤標 delivered。
PHASE-Z 外送 gate 改讀此欄位，
incident task、quarantine、降載與機械 close condition 完全不變；若 task pool
無法建立 incident，仍保留 fail-loud legacy backoff。

**回歸與 read-back**：deterministic RED 先重現第二個卡住檔案成熟後同一 episode
呼叫兩次 CRITICAL；回歸另鎖定 disjoint episode 不得靜音、concurrent overlapping
creator 只能一個 page、普通 semantic duplicate 不得吞單、failed delivery／crash
lease 必須重試、dedup receipt 可 settle、successor lease 必須轉移，以及 upsert
exception 仍 fail-loud；另鎖定 multi-root merge 任一 predecessor success 可
acknowledge live successor、remaining in-flight token 可阻止第三次 page、
A→AB crash retry 沿用 root key、merged alias send-before-settle crash 不重寄、
overlap member 關閉不遺失 delivery、schema 1 active／expired／released migration，
以及 disjoint family／e2 取得不同 dedup key。
successor receipt 回讀
`created=true, page_required=false`。目前狀態為
**`contained`**：歷史 production ledger 雖已逾 25 小時沒有再外送，新的 sustained-clean
48 小時計時必須從本修正正式部署後開始；且 commit 尚待 push／GitHub CI read-back。
兩者完成前不得升級
為 **`root_cause_fixed_and_verified`**。

---

## 2026-07-30 — legacy hourly dispatcher「disabled」被誤當成「已退役」

**證據化症狀**：`com.volpred.hourly-dispatch` 雖未載入，repo仍保留正式
`scripts/cron_hourly_dispatch.sh`、canonical plist、runtime executable references，
host仍保留TCC live copy與user plist。這些surface可被誤 bootstrap／直接執行，
Deliverable 8 observation已逾期；「目前沒跑」不等於「不能復活」。

**根因層級（retirement contract）**：cutover只完成runtime disarm，卻把rollback
artifact留在live namespace。owner audit能證明當下沒有雙clock，不能阻止下一次安裝、
wrapper sync或人工命令把legacy execution重新帶回來。

**底層修復**：wrapper exact bytes移至不可排程的`scripts/_legacy/`，canonical plist
刪除；runtime retired row只保留Operations Core scheduler需要的`schedule`與pregate，
移除`command`／`canonical_script`／`tcc_bypass_copy`；ownership與wrapper manifest
也不再宣告legacy owner。live TCC copy與user plist移入
`~/.Trash/volpred-hourly-dispatch-retired-20260730/`，不是不可復原刪除。

**回歸與回讀**：wrapper前後SHA-256皆為
`65e8bbc27e02ceddb93e5d55cd8c543b30e029ef5f4102cef9947a0252e4e463`；
repository ratchet與cutover/schedule/config相鄰範圍158 tests通過；
`launchctl print`回讀legacy label absent，live/canonical四個surface全 absent。
formal retirement assessor已不再輸出physical blocker，只剩
`formal_owner_census_blocked`與`sustained_clean_blocked`。

**制度化寫回與狀態**：repository test會阻止正式wrapper、plist或executable references
復活；archived wrapper仍由caller/behaviour transfer gates稽核。此bounded dispatcher
slice為 **`root_cause_fixed_and_verified`**；全域Issue #46因五個formal legacy
owners與14日clean gate仍是 **`contained`**。

---

## 2026-07-30 — PHASE-Z closeout 在 trigger decision lock 內阻塞每分鐘派工

**證據化症狀**：Operations Core `agent_dispatch_tick` 在
2026-07-29 22:50–22:54 UTC連續五班 `timeout after 30s`，22:49前每班只需
0.4–0.7秒；同一scheduler daemon的Gmail、GitHub通知與CI watch仍exit 0。直接socket
replay也在4.28秒小窗口內重現TimeoutError。當時state為`current_jobs=[]`但有一筆
`phase_z_pending`，supervisor正執行orphan-half probe與quarantine checkpoint。

**根因層級（executor trigger lifecycle）**：Unix socket server雖以
`background=True`呼叫scheduler，但只有worker本體被detach；restart/orphan後的
PHASE-Z recovery仍在`DispatchTriggerServer._decision_lock`內同步await。一次數分鐘
closeout因此鎖住所有後續每分鐘requests，Operations Core把已交付到executor的合法
背壓誤記成transport timeout。

**底層修復與制度化**：background tick看到durable `phase_z_pending`時，現在只建立
一個process-local single-flight recovery task並立即回
`phase_z_recovery_started`；後續tick快速回
`phase_z_recovery_in_progress`。真正recovery沿用原本的generation、git lock與terminal
receipt契約；`_closeout_only`保證pending若被其他路徑先清掉，背景task只能no-op，
不可越過closeout另開worker。done callback會清single-flight marker並把exception送入
既有loop-crash incident；告警本身透過observed `asyncio.to_thread` task送出，慢速
通知或通知失敗都不會再卡住executor event loop。

**回歸與狀態**：deterministic regression先以0.3秒slow closeout重現同步等待與
無background task，再轉綠：第一次ack <0.15秒、第二次只回in-progress、closeout
exactly once、pending最後清空。trigger／PHASE-Z／restart closeout相鄰範圍
**314 passed、1 skipped**，並另有exception-path regression證明0.3秒慢告警不阻塞
下一次tick。修正 commit `e9231ebf5` 已由 immutable release request
`5bb706310af43be...` 正式載入；LaunchAgent runs由11→12、新 supervisor PID
`26313` 於2026-07-30 07:38:07台灣時間啟動，planned-restart通知正確抑制，
trigger socket與health loop皆恢復。07:39自然Operations Core tick回
`not_due`、exit 0、約4秒，state回讀`current_jobs=0`／`phase_z_pending=0`。
GitHub successor run `30500807966` 最後以 **6645 passed、11 skipped** 完成；
四道相鄰 gates全綠。此 bounded root class為
**`root_cause_fixed_and_verified`**。

---

## 2026-07-30 — Operations Core Token 報表仍繞過 owned-email 且成功語意失真

**證據化症狀**：`token_report_daily` 的排程 owner 已是 Operations Core，但
`scripts/token_report_email.py` 仍直接建 `EmailNotifier`；呼叫後不驗
`sent == true` 就印出 sent／exit 0。新 Token／Boss subject 也沒有新架構來源標示。
所以「排程成功」不能證明 formal effect 已被 owner 接受或 Gmail Sent 已確認，
而跨主機 retry 會重新 render，不具 immutable command replay。

**根因層級（effect ownership／schedule identity contract）**：schedule clock cutover
只改了觸發者，沒有把 caller 的外送、idempotency、recipient 與 acknowledgement
一併納入 `email.ops_alert`。manual dedupe 又只綁日期，指定不同 recipient 會互相
碰撞；`--force` 只靠 timestamp 也不能保證同微秒唯一。

**底層修復與制度化**：Token 報表現在完整驗 canonical Operations Core fire identity，
以 exact fire key 建 owned-email command；任一部分 identity、錯 job／generation／
cron minute、scheduled `--force`／`--to`／`--calibrate` 均在 report、檔案或 provider
effect 前 fail closed。retry 先讀 durable command，核對 idempotency、actor、recipient
與 level 後原樣 replay；delivery 未獲 acknowledgement 回非零。manual daily key
綁 recipient digest，force 加 UTC timestamp＋UUID4。AST regression 阻止 direct
`EmailNotifier` 復活；Boss／Token 新 command 的 subject marker 恰好一次，歷史
markerless command 則保持不可變。

**回歸與狀態**：wrong identity、noncanonical minute、durable recipient drift、
dry-run／calibrate 無 effect、同微秒 force 唯一、歷史 replay、unacknowledged
delivery 等相鄰範圍 **107 passed**，Matt Standards／Spec 均 PASS。目前為
**`contained`**：今天 08:00 natural fire 早於修正，不人工重送以免雙寄；須待下一個
自然 08:00 fire 回讀 exact WorkItem／Effect、attempt 1 與 Gmail Sent evidence，
且 Issue #13 的 24 小時通知頻率 audit 完成後，才可升級。

**2026-08-01 live closure read-back**：修正後已連續兩次由自然 Operations Core
`token_report_daily` fire 成功執行：2026-07-31 fire
`operations-core-v1:token_report_daily:7548a16e4db73cef3f108c8c` 與 2026-08-01 fire
`operations-core-v1:token_report_daily:a565edadccc314a49bc92acf` 都由
`operations-core-scheduler` attempt 1、exit 0。後者 durable receipt 回讀
WorkItem=`succeeded`、Effect=`delivered`、attempt_count=`1`，收件人為
`yihao.lai@gmail.com`，subject 恰好一次帶 `[新架構派發]`；production adapter 以 exact
Message-ID 從 Gmail Sent 讀回後，逐欄驗 To／Subject／text／HTML，原始郵件證據 hash 為
`d72be58f22bb16fcaa13441de808463ff10fee71818b5b5e697d284978c88da3`。同一 fire
人工重播前後 effect id、attempt_count、evidence ref／hash 與 recorded_at 全部不變，
證實零第二封 provider delivery。當前 HEAD 相鄰回歸 **60 passed**。因此本條
Token Report ownership／exactly-once 根因切片升級為
**`root_cause_fixed_and_verified`**；Issue #13 umbrella 的其他通道與整體通知政策
仍依各自 acceptance／觀察窗保持 OPEN，不由本切片代替結案。

---

## 2026-07-30 — 通知雖已切新架構標題，仍可由 identity／旁路／log inode 重複噴送

**證據化症狀**：新架構 dispatch loop crash 在 63 分鐘內寄出 13 封；文章發佈仍
逐篇 direct Email，繞過聚合 owner；Telegram daemon 遇 atomic log rotation 後仍持有
舊 inode，pytest retry 也會寫 production log。單看 `[新架構派發]` 標題或
schedule owner 已切換，不能證明通知政策完成。

**根因層級**：

1. supervisor 用 `--force` 及含動態 task／時間內容的 title 建 dedup identity；
2. article producer 與 Boss Report 同時擁有 Email channel；
3. 長存 logger 與 rotator 沒有共同 pathname／permission contract，測試也沒隔離
   effect boundary。

**底層修復**：所有 supervisor alert 移除 `--force`；loop crash 以正規化的
traceback frame／function／exception cause 建 root，並移除 timestamp、UUID、hex、
path、數字與 canonical `assign_<hex>` identity。completion failure、silent death、
orphan 以 outcome／action 分開，避免不同可處置事件被中央 24h dedup 吃掉。文章
Email 唯一週期性 owner 收斂到 Boss Report，依 immutable schedule fire 的
`scheduled_for` 半開窗聚合；08:10／14:10／20:10 article delta 不重疊。Telegram
每次寫入 reopen current pathname；rotator atomic replace 保留 mode 並使用
private umask；retry tests 改用 temp log。

**回歸與 live read-back**：最終相關 suite **353 passed、1 skipped**，Matt
Standards／Spec 均 PASS。production rotation canary 證明 archive inode 不再增長、
current inode 收到新寫入且兩者均 `0600`；canonical 與 live rotator wrapper exact
一致。immutable supervisor release `41c5b86d…6466b5` 已由 durable request
`5f3cad26…5457` 在 worker drain 後完成 activation；fresh release commit
`71d55be44`、PID 34807、stable receipt、heartbeat／socket與空
`phase_z_pending` 均已回讀。

**class sweep follow-up**：production call graph 移除逐篇 Email 後，仍存在兩條可被
未來 caller 復活的旁路：root `volpred notify` 直接建 `EmailNotifier`，manual
`send_daily_digest` 也直接 SMTP。兩者現分別只走 formal alert router 與 owned-email；
legacy `milestone/alert/error` 明確映射到 `info/warn/critical`。daily digest
日期＋recipient logical key 先讀 durable command，feed 漂移只重播原件；兩 caller
同時 read-none 時，loser 捕捉 payload conflict後回讀並重播 winner，`force_send`
才建立 UUID command。回報不再反解析人類可讀 body；舊 notifier 的 article／digest
高階 convenience methods直接 fail closed。changed-feed、concurrent winner、
六種 level mapping、invalid level與五種 durable identity drift等相鄰範圍
**75 passed**；任何 key／recipient／actor／level／title 錯綁都在 provider 前
fail closed。

**狀態：`contained`**。fresh Telegram receive→process→reply、目標 Gmail
ACK／CLOSE、下一個自然 Token 08:00 fire與 24 小時通知頻率／必要性 audit 尚未完成；
這些下游 acknowledgement 缺一不可升級為
`root_cause_fixed_and_verified`。制度化規則：**通知 source marker、schedule owner
與 transport exit 0 都不是送達／頻率正確的證據；必須同時驗 identity、唯一 channel
owner、durable effect receipt 與收件端 read-back。**

---

## 2026-07-30 — Starvation lockout 先截斷、enqueue 後驗 collision，形成永久死結

**證據化症狀**：starvation lockout 曾只 offer K1730、K1731 兩席，但兩者各有
未合併 worktree；worker claim、建 worktree 後才被 `enqueue-agent` 的 task-id
collision gate 拒絕。後方 K1735／K1737 等無 worktree 的餓死任務永遠進不了
候選席，experiment lane 因此即使有工作也沒有可成功 enqueue 的工作。

**根因層級（selection／admission contract 分岔）**：starvation 只以 priority、
age 與 free-slot 數截斷；唯一知道 git commit／worktree ownership 的 collision
判定藏在 enqueue boundary。兩個 gate 各自正確，但上游 menu 不知道下游必拒條件，
把「必敗」誤當成「可派」並重複 force-feed。

**底層修復與制度化**：collision query 已移到
`volpred.ops.task_dispatch_collision`；enqueue 單筆與 starvation 批次 preflight
共用同一實作。dispatcher 在 urgent/time-critical lane ranking、preempt seating 與
slot truncation 前先掃完整 worker-claimable pool，排除 collision，保留明確
worktree／branch／commit evidence 並由後方可派 task 補席；查詢失敗則 fail closed，
不得假設無 collision。batch query 只掃一次 git log/worktree registry，避免逐 task
重跑完整 git graph。

**回歸與狀態**：K1730／K1731 blocked、K1735／K1737 backfill、urgent/preempt
collision、scan error、single/batch parity 與 merge-to-HEAD release 等相關 tests
**110 passed**；live graph
回讀亦精確定位 K1730／K1731 的 owner commits，K1735／K1737 為 clean。
此類為 **`root_cause_fixed_and_verified`**。制度化規則：**任何會縮窄候選的
selection gate，都必須在截斷前共用 downstream admission 的機械可派工判定；
不可先推薦、再讓下一層永久拒絕。**

---

## 2026-07-30 — 首頁把 115 筆 legacy memory 紀錄誤標為全部實驗

**證據化症狀**：線上首頁與 `/api/research/stats` 顯示 115；該數字精確等於
legacy `memory_entries(type=experiment)`／`storage/memory/experiments.json` 的紀錄
數，卻與可重生的 `experiments/index.json.summary.total=1388` 不符。研究資料沒有
被刪除；同一時點另有 1514 份 result artifacts，而 knowledge entries 是第三個獨立
口徑，不能拿其中任一數字冒充「實驗總數」。

**根因層級（projection semantic contract）**：首頁沿用舊 ResearchSummary，把
legacy MemorySystem 的執行紀錄長度命名為 `n_experiments`；canonical K 實驗 index
沒有正式前端 projection，Mirror 與 Supabase 路徑也都會把同一錯誤語意送到首頁。
因此部署、同步與資料庫本身即使健康，畫面仍必然退回 115。

**底層修復與制度化**：`build_experiments_index.py` 現在於同一 generation 產生
indexed experiment 與 result artifact 的 versioned projection，目標由
`config/project_targets.json.research_metrics_targets` 決定並原子 replace；
`daily_update.py` 以既有 nested-repo dirty ownership／path-scoped commit 管理它。
前端對 Supabase、Mirror 兩路 summary 都套用 schema-v1 canonical overlay，保留
legacy record、knowledge 與 result artifact 為明確不同欄位，首頁標籤改成
「已索引實驗」。索引的逐目錄 Git subprocess 同時收斂成一次 bulk history scan，
完整重建由超過兩分鐘降至 1.7 秒。safe deploy 會以 release ID 綁定本地 projection、
線上 API 與 original/v3 computed DOM，任一不一致即失敗。

**回歸與 live read-back**：主專案相關 54 tests、frontend canonical full
`npm run check`、Matt Standards／Spec review 均 PASS。Zeabur deployment
`6a6b2cfa159a57c418d426a5`、release `vnext-experience-20260730.1` 已 RUNNING；
production read-back 為 indexed experiments 1388、result artifacts 1514、
legacy records 115、knowledge items 3198，兩個首屏可見 DOM 都等於 1388，
`vnext-live` errors 為空。此類為 **`root_cause_fixed_and_verified`**。

---

## 2026-07-30 — H4-4 pregate 退役後，活規格與 observation ledger 仍宣稱 permanent shadow

**證據化症狀**：`hourly_pregate` 已從 scheduler 與 runtime schedule 移除，
但 `observation_ledger.pregate_shadow` 仍是 `permanent`；設計文件 §3.3/R3
仍要求把 heuristic demand 搬入 `DecisionInput`，active `scripts/` namespace
也仍保留可直接呼叫的 evaluator。三個 surface 與 control-gate registry 的
`last_action=retire` 相互矛盾。

**根因層級（retirement／living-spec contract）**：第一輪只切斷 runtime
caller，沒有沿 downstream authority graph 清除 ledger、interface schema 與
active executable namespace；而 task completion 在這些 read-back 前過早寫成
`root_cause_fixed_and_verified`。

**底層修復與制度化**：最終 production crosscheck 共 229 班、10 個
would-skip candidates，其中 9 班仍有可歸因的實質產出（90% false skip，
門檻 ≤10%），故不把已證偽 heuristic 搬入新 owner。已移除
`DecisionInput.pregate_mode/demand`，evaluator 移至
`scripts/_legacy/hourly_dispatch_pregate.py` 並只回報
`retired/no-decision`；共享 substantive taxonomy 抽至
`volpred.ops.dispatch_outcomes`，crosscheck 仍可重現歷史母體。
repository tests 鎖住 active script 不存在、schedule 無 pregate、ledger
shadow 已結案及 time-bound monitor 存在。

**下游 read-back 與狀態**：`pregate_shadow` 已透過 canonical
`volpred ops observation resolve` 結案，另立
`hourly_pregate_retirement_monitor`，deadline =
`2026-08-06T19:30:00+08:00`。在 7 日 post-cutover fire／provider-usage
read-back 與 rollback rehearsal receipt 完成前，本 H4-4 slice 為
**`contained`**；不得沿用先前過早的
`root_cause_fixed_and_verified` 口徑。

## 2026-07-31 — K1733 收件 freshness gate 找錯位置，會把完好的 full-production 產物判成必須重跑

**證據化症狀**：PHASE A 的 `collect_completed` followup `k1733-split-stage1-full-run`
（exit_code=0）其 `claude_followup.brief` 第 (0) 步寫著：「assert `config.quick_mode == false`
and `reproduce_spec` exists **in** `K1733_results.json` … a JSON without `reproduce_spec`
means the run crashed at the end and **must be re-run, not collected**」。
實地回讀該 artifact：`config.quick_mode` = `False`（通過），但 `reproduce_spec`
**不在** JSON 的 top-level keys 內（`k_id … code_trace`，共 20 個 key，無此欄）。
照 brief 字面執行 → 判定「run 崩了」→ 丟棄產物 + 重跑一次 heavy compute。

**根因層級（後置條件契約 vs canonical writer 實際產出）**：canonical writer
`src/volpred/research/reproduce_spec.py` 的契約是把 spec 寫成 **sibling 檔**，不是 inline 欄位 ——
模組 docstring 明寫「That writes `K1750_results.json` and `reproduce_spec.json` **side by side**」，
`SPEC_NAME = "reproduce_spec.json"`。該 worktree 內 `experiments/k1733/reproduce_spec.json`
確實存在（3,951 bytes，mtime 與 results JSON 同為 07-30 08:33），schema
`volpred.reproduce_spec.v1`，欄位齊備（entrypoint sha256／inputs 逐檔 sha256／outputs／
randomness／environment／canonical_result_identity）。
**gate 條件從一開始就對不上 writer 的產出形狀**，對任何正常完成的 run 都會誤判為崩潰。

**回歸驗證（回讀 live source，非憑印象）**：`reproduce_spec.json` 宣告的
`canonical_result_identity` = `{path: K1733_results.json, sha256: 9b4ead3349650533a5e82a06ee7ae6e7c5d37b1d8097a0e3fa0d09d809944aaf, size_bytes: 322085}`；
對該檔實際 bytes 重算 sha256 **逐位元相符**（同 hash、同 322,085 bytes）。
spec 內含 results 檔的 hash ⇒ spec 必然寫在 results 落地**之後** ⇒ finalize 步驟有跑完、
run 沒有在最後崩掉。**結論：此 artifact 可以 collect，不該 re-run。**

**狀態：`contained`（不得稱完成）**。已完成五步 gate 的 (1) 證據化症狀、(2) 根因層級、
(4) 回歸驗證；**未**完成 (3) 重構底層與 (5) 制度化寫回 —— 產生這種 brief 的 split／followup
撰寫路徑沒有被改，也沒有任何機械 gate 會擋下「後置條件斷言與 canonical writer 契約不符」
這類錯誤。同類錯誤仍可再靜默發生。

**待辦（留給後續班次，附本條為輸入）**：(a) K1733 收件仍未執行 —— brief 的 (1) README
reconciliation（`experiments/k1733/README.md` 565 行 vs 220KB JSON 逐數字核對）與 worktree
`dispatch-slot-1-9189c746-k1733`（branch `k1733-slot1-9189c746`）的正式 merge 都還沒做，
本班預算不足以完整收尾故未 claim（未留 partial）；接手時**freshness gate 請改讀 sibling
`reproduce_spec.json` 並比對 `canonical_result_identity`**，不要沿用 brief 原文那條。
(b) 根治面：讓 followup brief 的後置條件從 canonical writer 的契約推導，而非人工複述。

---

## 2026-08-01 — general draft 的 lazypack「延後」只有提醒、沒有 durable owner，會讓 draft pool 持續缺貨

**證據化症狀**：`publish_draft.py --status draft` 對 general 文章缺少懶人包時，舊流程只印出
後續 enqueue 提醒便回成功；即使沒有 `--lazypack-plan`、plan 的 evidence binding 無法解析、
publisher stdout 無法識別新 article id，或 enqueue transport 失敗，文章 task 仍可宣稱完成。
這類 draft 隨後被 release gate 擋住，形成 `draft_pool_low`／release starvation。K1325 live path
另證明舊 settlement 用 stdout 第一個 `mile_*` 猜 owner，曾把新 plan 指向無關舊文章。

**根因層級（跨階段 ownership contract）**：系統把「讀者可見前才要求懶人包」誤解成
「建立 draft 時可沒有後續執行 owner」。publish-time gate、deferred preflight 與 post-publish
settlement 各自重算 policy，且 settlement 的 receipt identity 與 failure semantics 都不是正式契約；
因此 exit 0 只證明 feed mutation 發生，不證明該文章具有可執行、可追蹤的 release 路徑。

**底層修復與制度化**：新增單一 `LazypackObligation` classification，publish gate、pre-mutation
deferred preflight 與 settlement 共用同一判定。draft/scheduled 若尚無圖組，feed mutation 前
必須攜帶 `--lazypack-plan`，並以 canonical renderer 完整驗 schema、evidence SHA 與每個 binding；
checker/boundary 無法判定時 deferred path fail closed。publish 後只接受
`action=publish_milestone` 的 structured receipt（或 publisher 自身 anchored line）作 exact article
identity；缺 id、缺 plan、enqueue nonzero 或 exception 一律回 8，不得再把 ownerless handoff
報成成功。published reader gate 原有 fail-open policy 保留，但 exception 必留下可搜尋 diagnostic。

**回歸驗證**：正向 integration 以隔離的 tmp feed／queue 跑 `main()` 到真實
`lazypack_async_render enqueue`，回讀 exact article id、durable queued receipt 與 frozen plan SHA；
另覆蓋缺 plan、binding 不存在、checker/boundary failure、malformed receipt、錯誤 id、transport
exception。相關 suite **112 passed**，Matt Standards／Spec 雙 PASS；全量 suite 的 25 個既有
control-plane/provider-policy failures 與本 slice 無關，未冒稱全綠。

**Live gate / 狀態**：K1450 article `mile_5378daa1` 由自然 Operations Core fire
`operations-core-v1:volpred-compute-worker:80e6876c837201b47ea1c828` 執行 r4，exit 0；人工回讀
4/4 PNG 已無截字／重疊，四個 content-addressed public URLs 全部 HTTP 200。canonical feed 已
replace 圖組且 `sync_article=true`；`feed-sync --dry-run` 對該 article 為 0 insert／0 update，
release preview 從 blocker 解除為 draft=6、content_gate_blocked=0、eligible=6，且下一候選精確為
`mile_5378daa1`。本 slice 五步 Gate 為 **`root_cause_fixed_and_verified`**；incident lifecycle
本身仍須 sustained-clean 才能標 resolved，這是時間窗狀態，不是再留一個人工修復步驟。

---

## 2026-08-01 — pre-write dedup 在 identity ratchet 後仍產生 title hash，令 control-gate evidence source 失明

**證據化症狀**：原 detector `audit_control_gate_lifecycle.py` 穩定回報
`publisher_arc_dedup` 的 75 筆 post-ratchet evidence 中有 60 筆
`synthetic_candidate_identity_after_ratchet`。逐筆分組後全部都是兩次正式
`warn_arc_near_miss` 呼叫：55 筆 `title:0188e324171d17f3` 與 5 筆
`title:221b4ebf6d347778`；沒有隱藏 task／event／K identity，也不是舊 row 被改寫時間戳。

**根因層級（evidence identity／PDCA outcome join）**：registry 已在 07-30 宣告 canonical
candidate identity ratchet 生效，但 `check_arc_dedup.py` 對無 K、非 event 的文章仍接受
title-only 呼叫，並由 publisher logger退回 `title:<hash>`。因此 gate action 雖可觀測，卻不能
和 canonical `storage/next_tasks.json` 的 task outcome join；policy 與 writer capability
在同一個 cutover 點分岔。

**底層修復與制度化**：pre-write CLI 新增 `--candidate-id`；Operations Core agent 預設取
`VOLPRED_PRESELECTED_TASK_ID`，互動 session 必須明示。無 K、非 event 的 identity 若缺失、
含空白、使用 `title:/decision:`，或無法在 canonical task pool 回讀，不執行模糊 dedup，改寫
durable `warn_arc_unjudged` receipt、回 `gate_error_fail_open`／exit 0，讓 source-health 保持紅燈
但絕不阻斷寫作；這同時遵守「證據不可靜默消失」與「fuzzy gate 不得製造內容黑洞」。K 與
structured event 仍分別使用既有 K+audience／event+slot 身分，禁止混入第二個 candidate id。
publishing rule 與 hourly dispatch prompt 同步機械命令；registry ratchet 校正到真正 enforcement
生效的 `2026-08-01T10:52:12+00:00`，不再對尚未具備的能力做虛假宣告。

**回歸與 live read-back**：兩輪 TDD 先固定 scheduled env identity、缺 identity、task pool
不存在三種 RED，再轉 GREEN；Matt review 發現並修正一筆舊 generic fuzzy 測試的 title-only
契約，最終擴大相鄰 suites **172 passed**。正式 canary 以
`alert_control_gate_source_health_20260801` 寫入 `warn_thin_signature` receipt，回讀 candidate id
精確等於 task SoT；原 detector 隨即回報 `healthy=true`、`unhealthy_source_count=0`。本根因切片
為 **`root_cause_fixed_and_verified`**；歷史 60 筆保留作 incident 證據，未手改或刪除 log。

---

## 2026-08-01 — 舊 dispatch generation 的 settlement receipt 無終止語意，形成每分鐘永久重試

**證據化症狀**：live supervisor 每輪都對同一批已完成、已 blocked 或已由後續 session 接管的
task settlement 重跑 CAS；`ci-red-30339013855`、`ci-red-30409803097`、
`ci-red-30433823744`、`ci-red-30494529174`、`ci-red-30507270318` 等穩定回
`claim_session_mismatch`，termination canary 另回 `workspace_not_terminal`。單輪最多 20 個 child
CLI 反覆讀寫 queue，與郵件中的 `dispatch-preassign` 30 秒逾時同時出現。歷史 receipt 與 task
狀態均保留，未以清檔止血。

**根因層級（generation／settlement state machine）**：workspace ledger 只有 pending 與 completed，
但 scheduler 僅能在舊 claim-session CAS 成功時寫 completed。任務若先被 termination path 原子
re-pend、由新 session 接手或由其他正式流程結案，舊 CAS 必然永久 mismatch；observe-only 的
`system_terminated` 路徑又刻意不做第二次 queue settlement，因此也沒有 durable terminal edge。
正確語意不是把舊 disposition 套到新任務，而是證明 canonical generation 已前進後，只封存舊
receipt 為 `superseded`。

**底層修復與制度化**：task-pool 新增 supervisor-only、read-only 的
`dispatch-generation` read-back，精確比對 task id、claim session 與 dispatch job。reconciler 只在
durable workspace receipt 已入 ledger、且 canonical read-back 回 `generation=superseded` 時，追加
`task_settlement_completed(disposition=superseded)`；不修改 task、不重放 merge／remediation effect。
task/session/job、workspace name 與 allocation receipt 必須全部綁到同一 generation；terminal
observation 採 strict tri-state，store 消失、I/O／JSON 錯誤或找不到 exact allocation 一律在副作用
前 fail closed。reconciliation 沒有 terminal receipt 時只以 `settlement_recovery`／
`superseded_generation` 進入 non-merge checkpoint/quarantine，絕不沿用原本的 success outcome 去
merge；原 generation 仍 owned、identity 不符、queue 不可讀或 completed receipt append 失敗時都
保留 pending 供下一輪重試。

**回歸與狀態**：TDD 覆蓋 owned／superseded／wrong-job、正常 disposition 後 CAS mismatch、以及
`system_terminated + empty_removed` 非終態路徑；另覆蓋 generation-advance race、舊 receipt job
正規化、missing／unreadable／corrupt／wrong-allocation 四類 strict observation 與 finalizer
fail-closed。task-pool suite **146 passed**，supervisor suite **323 passed, 1 skipped**，Matt
Standards／Spec 雙 PASS，critical Ruff、compile 與 diff gate 通過。2026-08-01 22:26:24 CST 已由
immutable release 完成 planned reload；22:26:38 與 22:28:23 兩個自然 reconciliation 週期均為
`claim_session_mismatch=0`、新 ERROR=0，pending settlement 由 26 收斂至 1。最後一筆是有 durable
workspace identity、但尚無 terminal receipt 的舊 generation，已走 `remediation_opened` 並 materialize
P2 `inc_792a94b0ecf4_e1`，沒有重放舊 task effect 或污染現行 claim。五步 Gate 已完成，狀態為
**`root_cause_fixed_and_verified`**。
### 2026-08-01 — Claude quota 後 Codex failover 仍被 production env 關閉，OAuth crash custody 未封口

**證據化症狀**：live LaunchAgent 明確載入 `VOLPRED_CODEX_FAILOVER=0`；同一時段
supervisor log 在 Claude quota 後反覆寫出 `codex failover disabled`，因此
`Claude→Codex failover 接手失敗` 並非通知誤報。canonical schedule、repo plist 與
installer validator 都仍把先前的 `disabled_until_per_fire_custody` 當現況，造成後續已完成
的 kernel custody／termination-intent 工作無法自動解除舊 disable snapshot。

**根因層級與底層修復**：這是 activation contract 加 credential lifecycle 的複合缺口。
canonical schedule、plist 與 immutable installer 現共同要求 failover=1；新 Codex OAuth
lease 在 secret 寫入前先 fsync parent/child directory 與 durable v3 intent，精確綁定
job、attempt 與 Darwin producer custody。missing／invalid／stale-attempt custody 在
materialize、provider spawn、kill 前 fail closed。所有 terminal path 都以完整 resource
coalition（含 `setsid` descendant）連續兩次 empty 才刪 synthetic auth；unknown／live
custody 不再同步無限等待唯一 slot，而是 durable `recovery_pending` 後交給 health/startup
重試。receipt state 依 durable `close_phase` 單調前進，pre-checkpoint failure 與
destination-unlinked 後 crash 都能在 restart 收斂；v1/v2 歷史 recovery 保持相容。

**live canary 揭露的相鄰根因**：一次性 launchd canary remove 後，exact saved resource
coalition 已被 kernel 移除並回 `ESRCH`；舊 observer 把它當 unknown，會讓 v3 receipt
永久 active。`_unknown_custody_members()` 現只把 exact saved-coalition enumeration 的
`ESRCH` 視為 authoritative drained；host、boot、observer-current-coalition 或 ancestor
probe 的任何 `ESRCH` 仍是 unknown／fail closed。負向測試鎖住三種不可誤放行的 probe。

**回歸、部署與回讀**：TDD 與 Matt Spec／Standards 多輪雙審最終皆 PASS；activation
scoped suite **380 passed、1 skipped**，live-follow-up 後合併 suite **402 passed、2
skipped**，F/E9 lint 與 diff check clean。commits `c25324da2`、`02ee2b8a0` 透過 immutable
installer 部署；current release=`02ee2b8a0863f7038eff0c1610d1cf3cc423279b`、SHA
`b233a8a151bf04d8ac2453cd9aebb7a6d6e6ad4376ff506aead217af38f0c4d2`，LaunchAgent
read-back 為 failover=1、fresh PID／heartbeat、0 current job、auth_blocked=false。
subscription-only canary 回讀 `codex-cli 0.145.0`、ChatGPT reachable、API-key env=false、
v3 job/attempt match、cleanup=true、synthetic auth absent；移除 canary 後的第二筆 interrupted
receipt由 ESRCH 修正成功回收（recovered=1），全目錄 nonterminal v3=0。此 bounded incident
五步完成，狀態 **`root_cause_fixed_and_verified`**；program umbrella 的 formal owner
cutover／retirement window 仍依 #9→#12 blocking edge 獨立保持 `contained`。

---

## 2026-08-02 — 新舊 supervisor 共用 provider-auth receipt namespace，測試 receipt 令 live health loop crash

**證據化症狀**：2026-08-01 23:06 CST 的通知不是 credential 或 API key 失效；舊 immutable
supervisor 在 root `~/.volpred/logs/provider-auth-reapers/*.json` 讀到 working-tree tests 寫出的
`provider-auth-lease.v3`，將未知 schema 當成 health loop exception，整個週期被記為
`loop_crash`。同批郵件另揭露 dispatch-preassign 30 秒逾時；後者已由 generation settlement
state-machine ticket 獨立收斂，本條只處理 receipt rollout／test-state isolation 根因。

**根因層級（rollout compatibility／writer capability／test isolation）**：receipt writer 沒有
版本化 live namespace，測試預設也能落到 production root；writer 只有 PID-shaped guard，沒有
證明「目前 supervisor 是哪一個 immutable release、是否已完成 startup recovery」的 capability。
健康檢查又把 receipt control-plane invalid 與 loop crash 混為一談，所以一次 schema rollout
同時造成 cross-release 誤讀、測試污染與錯誤事故分類。

**底層修復與制度化**：`provider-auth-lease.v3` 成為單一 schema constant；v3 writer 只有在
startup recovery 完成、PID 與 process-start fingerprint 精確吻合後才取得
`provider_auth_receipt_schema` capability，且 pytest context 無條件禁止寫 production root。
新 receipt 寫入版本化 `provider-auth-reapers/v3/`；reader 在 rolling window 同時讀 legacy root
與 v3 child，舊 release 則自然只看到 root v1/v2。startup relocation 僅搬移 terminal／cleaned、
destination 已消失的 root v3 receipt；每筆採 fsync、content hash、intent/completed append-only
audit，torn audit tail 可在鎖內截到最後完整行再依 target digest reconciliation。malformed 或
nonterminal receipt 不搬移並 fail closed。健康層遇到 invalid receipt 現設 `auth_blocked=true`、
持續 heartbeat，另送精確的「派工安全暫停」通知，不再誤稱 login 失敗或讓整個 health loop crash。

**回歸與 live read-back**：Issue #53／commit `ccb97792c` 經 Matt Standards／Spec 雙 PASS，
相鄰完整 suite **374 passed、1 skipped**，compile、Ruff F/E9 與 diff gate 均通過。自然 PHASE-Z
drain 後 supervisor 於 2026-08-02 00:15:52 CST planned reload 至 release commit `095a31f16`
（含上述 commit）；fresh PID 72651，兩個以上 health 週期 heartbeat 持續前進，
`provider_auth_receipt_schema=provider-auth-lease.v3`、writer start fingerprint 已寫入、
`auth_blocked=false`、current jobs／PHASE-Z 均為 0。11 筆歷史 test v3 receipts 全部搬到 v3 child，
root 只剩 1 筆 v1／2 筆 v2；22 筆 audit 精確形成 11 組 intent＋completed，逐檔 SHA-256 回讀吻合，
沒有 nonterminal／invalid v3。此 bounded 根因五步 Gate 完成，狀態為
**`root_cause_fixed_and_verified`**；Issue #9→#12 全域 legacy retirement 仍依其獨立 clean-window
與 blocking edge 判定，不由本 slice 提前結案。

---

## 2026-08-02 — compute queue 交付繞過 experiment admission，Codex failover 又缺少 PHASE A 收件

**證據化症狀**：GitHub Actions runs `30711055685`、`30713909333` 都只有
`test_knowledge_unrecorded_ratchet` 失敗：K1743 的 archived results 已進 main，但 canonical
knowledge 沒有 K1743。compute receipt `storage/ops/compute_queue/k1743-price-discovery.json`
同時仍為 `followup_dispatched=false`、`source_task_settlement.state=pending_collection`；落地
commit `3dac20c9c7ab` 只收了 results。原始 results 另含 2011-10-25 的 1.8015 與
2014-12-31 的 3.67 TWD/USD 壞 tick，造成約 -94%／-88% 的不可能 ADR premium，證明未經
正式收件與 review 的檔案不只是 metadata 不完整，也可能包含研究品質錯誤。

**根因層級（雙 admission path／followup lifecycle）**：generic `experiments/**` namespace
掃描會呼叫 `_gate_experiment_ready_for_main`，但 completed compute receipt 的 queue-output
捷徑直接把 declared paths 送進 commit，形成較弱的第二入口；另一方面 Codex failover prompt
只從 handoff Section 4 挑新工，沒有 Claude hourly flow 的 PHASE A，因此 Claude 不可用時
`pending_collection` 永遠沒有人正式收件。兩個缺口疊加後，orphan reaper 把尚未 review、spec、
knowledge closure 的 compute result 誤認為可交付成品。

**底層修復與制度化**：queue-output candidate 現在對任何 `experiments/<id>/` 路徑重用同一個
canonical experiment admission gate，並在持有 receipt／Git transaction lock 後、真正 staging 前
重新授權 exact paths；review verdict、artifact contract、reproduce spec、knowledge 或 byte binding
未齊、或 scan 後發生漂移時，只寫 `experiment_admission_blocked` evidence，保留原檔且禁止 commit。
queue lane 另遵守 `experiments/<id>/` first-child atomic unit：receipt 未宣告的 dirty companion 不得拿來
通過 gate 後只提交 results；正式收件必由 namespace／main-thread collector 原子落地整個 unit。持鎖
admission 會在 staging 後再跑一次，並逐一比對 HEAD、working-tree SHA 與 staged Git blob，連不拿
writer lock 的外部檔案寫入也不能把已審 bytes 偷換掉。experiment transaction 不再使用會重讀
working tree 的 `git commit --only`；它從隔離 index 建立 commit-tree，驗 commit 內 exact blob／
path scope 後才以 HEAD CAS 發佈，因此 staged 驗證後的檔案改寫只會留下新 dirty bytes，不會進入
已授權 commit。
Codex failover prompt 補齊 PHASE A，逐筆處理 `collect_completed`、`split_required`、
`artifact_contract_mismatch`、`triage_failed`，未 `mark-followup-dispatched` settlement 前不得挑新工。
K1743 本身改用 runtime `finalize_experiment()` 同步產 results/spec byte trace，新增 FX 合理範圍與
material-corruption fail-closed gate；兩個孤立壞 tick只記錄後剔除、不插值，重跑後維持誠實
`NULL`，並以 Codex review、PASS verdict 與 canonical MemorySystem writer 完成研究閉環。

**驗證狀態**：TDD 已鎖住「completed compute experiment 不得繞過正式 admission」及「Claude／
Codex failover prompt 必須具備相同 followup modes」；K1743 artifact gate、四項 experiment gate、
review byte binding 與 knowledge provenance 均已通過。提交後仍須由 tracked-file pytest、GitHub
Actions green 及 CI watcher read-back 完成最終持續驗證；在此以前本 incident 僅為
**`contained`**，不得提前稱 `root_cause_fixed_and_verified`。

---

## 2026-08-02 — 舊 commit-ownership Stage 2 稽核可用 sparse／stale rows 自我誤判綠燈

**證據化症狀**：原 Stage 2 assessor 把「最後一筆 shadow」當七日窗終點，只用現存 rows
當 identity 分母，且中位數排除 identity-missing 班。兩筆恰隔七日即可冒充連續觀測；過期
ledger 可把自己的七日搬到現在；`fire_ids=[null]` 與缺失／null 的
`inferred_not_declared` 亦可被當成有效 identity／零缺口。這不會直接啟動 Stage 3（另有硬鎖），
但會產生不實的歷史 PASS，讓退役決策建立在錯誤證據上。

**根因層級（measurement population／schema／superseded contract）**：舊計畫把
PostToolUse shadow rows 同時當樣本與分母，沒有與 canonical schedule、已開啟的 fire manifests
或 audit 當下時間對帳。Claude hook 又只涵蓋 Edit／Write 類工具，Bash、Codex 與其他 producer
不在宣告面；因此擴大 hook 不是修復，而是復活已被 Issue #43 producer isolation 取代的 ownership
模型。

**底層修復與制度化**：`scripts/audit_commit_ownership_shadow.py` 現嚴格讀取 git-common-dir
shadow bytes／fire manifests，並從 `config/runtime_schedules.json` 取得 canonical
`7 * * * *` cadence。評估窗以 timezone-aware audit time 錨定；freshness、窗首／窗尾與任兩筆
observation 的最大 gap、manifest expected-fire coverage、unexpected observed fire、identity
coverage及所有班次的 missing-path median 均 fail closed。present `fire_ids` 僅接受非空字串；
舊 schema 缺欄只算 identity-missing；gap 欄缺失或 null 直接 audit failed。任一班 baseline
unavailable 也不得把不可量測的 `inferred=[]` 當零缺口。CLI 對 malformed evidence 回 typed
JSON／exit 2，對任何可解析結果則因 superseded contract 固定
`manifest_cutover_eligible=false`／exit 1。正式出口明確分成 Issue #43 producer landing、
Issue #41 machine-state single writer、Issue #44 recognizer physical retirement。

**live read-back 與回歸**：2026-08-02 audit 回讀 shadow **372 rows／1,504,669 bytes／SHA-256
`79dd5326ed8e6e2b7b31b976f31425003c518f85398d5b50d9bc8991df08a29e`**。當下七日窗為
222 observations；canonical gap 3,600 秒、允許上限 7,200 秒，實際最大 gap 86,285.506 秒；
identity coverage 88.288%、280 expected manifests 中 observed 217（77.5%）、missing 63、
unexpected 1；`inferred_not_declared` 中位數 10、最大 62，baseline available 219/222。
audit 誠實回 `legacy_stage2_metrics_pass=false`、`manifest_cutover_eligible=false`、exit 1；
machine-state／non-machine missing occurrences 分別 1,271／1,508。TDD 新增 sparse endpoints、
stale ledger、expected-fire 漏失、schema、全班 baseline 缺失、全-window median與 public CLI
exit-contract regressions；PHASE-Z／supervisor 相鄰完整範圍 **630 passed、1 skipped**，新增
exact fire reconciliation 後定向 **43 passed**；Matt
Spec／Standards 最終雙 PASS。此「舊 auditor 可誤綠／Stage 3 可被錯誤證據復活」根因為
**`root_cause_fixed_and_verified`**；Issue #41／#44 umbrellas 仍須各自完成正式 cutover／physical
retirement，維持 **`contained`**，不得由本歷史 audit 提前結案。
