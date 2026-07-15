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
- 2026-07-14 22:20 **RESOLVED** agent-job 的認證牆被歸檔成「研究失敗」：repo 有兩處 spawn `claude -p`，只有 supervisor 的 `worker.py` 分得出 auth / quota / transient，`run_agent_job.py` 只看得到 exit≠0 → K1709 rev3 重審 agent 5 秒死於 `Not logged in`（同時段 supervisor fire 認證正常＝暫時性刷新競態），queue 標 failed，followup brief 派下一班 fire「去 worktree 翻可搶救成果」— 那裡什麼都沒有，agent 從未啟動。**修**：分類邏輯抽成單一 owner `scripts/dispatch_supervisor/failure_class.py`（worker.py 改引用，行為不變）；runner 用同一份定義，auth → 有界重試（3 次 / 120s，且只在剩餘 budget 塞得下正事時），真失敗 → 一如既往不重試；`failure_class` 寫進 metadata receipt，compute_queue 據此把 auth 類 followup 改成「re-enqueue，不要 triage、不要記任何研究裁決」。Gate: `scripts/tests/test_agent_job_auth_class.py`（break-then-verify 確認會咬）。commit b4b2db64d — Q3

## B. Git owner / canonical-write / `git add -A` 中毒

**規則**：每個會寫檔的流程（排程 writer、compute job、驗證副產物、auto-commit）都必須有明確 Git owner，用 **explicit-path** commit，**禁止 `git add -A`**（會捲進他人在途檔、毀掉 before/after、洩漏未完成工作）。共用 main checkout 的 Git mutation 是一整段 transaction：ownership/HEAD recheck → stage/stash → commit/merge/ref adoption → index/stash 收尾必持同一把 common-dir lease；只鎖最後一個 `git commit` 仍是 race。「排程 writer 沒 commit」是類別漏洞，逐案補 `git commit` 不收斂 → 立 class-level gate。
**機械 owner**：`src/volpred/ops/git_writer_lock.py` + `scripts/git_writer_lock.py`（跨 process、stable inode、finite timeout、exact-path/index rollback）統一包 PHASE-Z / scheduled writers / reaper / worktree merge / Codex backfill；common-dir `reference-transaction` hook 對 main ref fail-closed（raw commit / `--no-verify` / update-ref 都須 inherited lease），pretooluse 提早擋 shared-main 裸 commit。agent compute job 強制使用 registered linked worktree，不再預設 main；push 另綁 immutable audited SHA。
**代表 incident**：
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

## C. Worktree merge / 實驗檔遺失 / 審查認證

**規則**：worktree agent 只產 `experiments/kXXX/`，禁改共享狀態；主線程用 `scripts/merge_worktree.sh` 合併，**禁 `git worktree remove --force`**（L1 hook 擋）。實驗進 main 的唯一門票 = `experiments/<kid>/review_verdict.json` 且 sha256 綁「現在這份 bytes」（PASS 後又改 code 也擋）。裁決檔一律由 `verdict-template` 產生，不手抄。
**機械 owner**：`scripts/merge_worktree.sh` → `scripts/experiment_gates.py certify`；`worktree-merge-verification` skill。
**代表 incident**：
- 2026-07-12 **3-STRIKE（K1032 class）** `.claude/worktrees/` 底下「獨立 repo」對 merge 的破壞 — Q3
- 2026-07-14 Merge 認證聲稱可用裸 `python3`，卻在解析子命令前 eager-import 專案套件 — Q3
- 2026-07-14 Review 對移動中的樹裁決：verdict 沒綁 commit SHA，一落地就過期 — Q3
- 2026-07-13 orphan branch：三個 commit 全被平行實作取代而丟棄 — Q3
- (K1032 原始教訓：merge_worktree 誤判「no commits」但 reflog 有 commit → 檔案遺失) — Q2

## D. Silent fallback / fail-open guard / exit-code masking

**規則**：不可用 silent fallback / try-except swallow / 靜默降級掩蓋 schema 或流程缺陷；護欄不可放在 fail-open 的 `try` 內（等於沒護欄）。hook / wrapper 不可把 shell pipeline exit code 當 tool outcome（pytest false-green）。silent fallback **當場修**，不丟下一班。
**機械 owner**：`.claude/rules/no-silent-fallback.md`（規則本體）+ pre-push silent-fallback baseline sweep + CI silent-fallback check（baseline 只准變少）。
**代表 incident**：
- 2026-06-22 ~ 06-23 silent-fallback batch fix（多筆，governance sweep）— Q2
- 2026-06-23 **3-STRIKE** 測試 hook 假報「Tests passed」（exit-code masking）— Q2
- 2026-06-20 **3-STRIKE** host_cron_fail false-critical on exit-as-findings — Q2
- 2026-07-14 05:45 護欄放在 fail-open 的 `try` 內，等於沒有護欄 — Q3
- 2026-07-14 06:20 dedup gate 說 `clean`，其實是「我沒看」（STRIKE 2）— Q3
- 2026-07-10 canonical-write：silent ignore of `sync_article()` 回傳（K1021 同根因）— Q2

## E. Dedup / narrative-arc / 重複內容 / recycling / K-id 撞號

**規則**：派寫作 agent 前主線程做 3-layer 查重；同邏輯 arc 換外殼也算重複（arc-dedup）。dedup gate 若 fail-closed default 會變 8-day 內容黑洞（要 fail-open + audit trail）。K-id 配號前 `ls experiments/` + `ls .claude/worktrees/`，禁雙 agent 同號。鬼打牆根因在**釋出端**非研究端。**實驗做完沒寫進 knowledge.json = 對 dedup 完全隱形**（查重查不到 → 系統宣稱「全飽和」還去重跑同一題）——「寫 KB」不是收尾禮儀，它是 dedup 的資料前提。
**機械 owner**：3-layer dedup（`.claude/rules/publishing.md`）+ arc-dedup gate + `.claude/rules/dedup-gate-audit.md`；release_dedup TTL 別凍死全池。**KB 覆蓋率**：`scripts/reproduce_check.py` 的 `KNOWLEDGE_UNRECORDED` issue（經 `daily_checkup.py` reproducibility 維度曝光）。
**代表 incident**：
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
- 2026-07-12 DM helper 在 h=1 退化成 iid，K565 的 Harvey PASS 被推翻 — Q3
- 2026-07-13 K1702 把 MDD/vol 比率誤當尺度不變，原 Codex gate 因此失效 — Q3
- 2026-07-11 FEVD 取錯軸：`decomp[-1]` 把「最後一個變數」當成「最後一個 horizon」（K865 作廢）— Q3
- 2026-07-13 K1701 巢狀 QLIKE 用 expanding raw DM 承載 NULL，修正後只能判 inconclusive — Q3
- 2026-06-16 K445 article OOS 用 origin-aligned forecasts（off-by-one / lookahead 風險）— Q2
- 2026-05-06 K547 lookahead audit sweep：`weights * ret` 同期 pattern 跨 11 檔 — Q2

## H. Turn final-text / notify-first / boss-facing report / alert-as-task

**規則**：互動 turn 收尾必須是**給用戶的文字**（email 不能替代 session 內回覆）；ScheduleWakeup 互動 turn 禁用。不要把修復中間狀態 / 待辦丟給老闆（alert body 寫「已自動修復」非「建議老闆行動」）；alert 預設自動變 task。回報禁列「還需要你做 X」。
**機械 owner**：`scripts/hooks/enforce_final_text.py`（Stop hook）+ `scripts/hooks/deny_wakeup_interactive.py`（互動 turn 擋 wakeup）；alert→task remediation bridge。
**代表 incident**：
- 2026-07-02 14:25 **3-STRIKE** 「turn 結尾無文字回報」同日第三波 → Stop hook 機械化 — Q3
- 2026-07-02 13:58 turn 結尾無最終文字回覆（同日復發，3-STRIKE TRIGGER）— Q3
- 2026-07-14 12:41 CI 紅燈 notify-first：把修復中間狀態丟給老闆 — Q3
- 2026-07-13 01:10 警報把工作派給老闆：24/27 個 alert body 是寫給人看的待辦清單 — Q3
- 2026-07-13 21:45 「修好 CI」宣告後老闆連環收 failure 信（修復不完整 + 未 push）— Q3

## I. Chart / CJK 豆腐字 / renderer domain model

**規則**：每篇 reader-facing 文章要有真圖表，不可用 ASCII / 文字框冒充；中文圖必設 CJK 字型（有 helper 還要有 enforcement，否則復發）。懶人包 renderer 是 data-bound plan.json 渲染，LLM 只草擬文案 / 選 evidence path，**絕不重寫渲染 code**（每篇都讓 LLM 重寫 = domain model 錯誤）。
**機械 owner**：`scripts/lazypack_render.py`（strict data-bound）+ font enforcement + `lazypack-infographic` skill。
**代表 incident**：
- 2026-07-14 09:07 **3-STRIKE** 豆腐字圖表第三次上線 + CI 時間炸彈測試 — Q3
- 2026-07-13 22:48 CJK 圖表豆腐字第二次復發：有 helper、沒有 enforcement — Q3
- 2026-07-13 19:26 **3-STRIKE** 每篇懶人包都讓 LLM 重寫 renderer（domain model 錯誤）— Q3

## J. Alert / dreaming / detector false-positive / 轟炸

**規則**：detector 的 dedup key 必須是 root-cause identity（不是 umbrella / 帶 {hhmm} 的 title，否則 24h dedup 永不命中 → 轟炸老闆）。detector 要看得見自己派的補救任務（否則假 critical）。「N findings 全 severity=critical」是 detector 設計缺陷。無界重試 + snapshot 消耗時機錯 = 每 64 秒連發。
**機械 owner**：`src/volpred/ops/alerts.py`（check_alerts 每小時，condition-based）+ dreaming detector（dedup key = root-cause identity）。
**代表 incident**：
- 2026-07-01 **3-STRIKE** dreaming-run 7 findings 全 severity=critical + occurrence 灌水 — Q3
- 2026-07-13 21:55 PHASE-Z「沒有 fire 起始基線」warn 每 64 秒轟炸（snapshot 時機 + 無界重試）— Q3
- 2026-07-13 22:10 PHASE-Z title 帶 {hhmm} 使 24h dedup 永不命中 — Q3
- 2026-07-14 01:40 dreaming 把 umbrella alert dedup key 當成 root-cause identity — Q3
- 2026-07-14 09:56 dreaming missing_retry_strategy 假 critical：detector 看不見自己派的補救任務 — Q3

## K. Pool / release cadence / starvation / 池枯竭

**規則**：draft 池不可空、release 節奏不可斷；pool < 4 一次補滿（非一次一個），補池前查 `current_job`、寫入走 flock。pool-empty critical 反覆觸發 = 根因雙修（供給 + 消耗對齊），不是重試。
**機械 owner**：`refill_reader_facing_pool` + release cadence + journal-discovery 冷卻對齊。
**代表 incident**：
- 2026-06-14 **Three-Strike** pool-empty critical 反覆觸發 → 根因雙修 — Q2
- 2026-06-14 pool warn 反覆復現 → journal-discovery 冷卻對齊消耗 — Q2
- 2026-06-19 三根因：release pool 枯竭 / member_qa dispatch 誤分類 / M2 供給斷 — Q2
- 2026-07-13 **3-STRIKE RESOLVED**（dreaming persistent_alert e1aa596aac4a2172，連 9 次 5.8d）「發文脫班補救失敗：force-release/refill 皆為 0」— 根因不是補救失效，是**refill 把一整個連載 cluster 塞爆 → 池裡有稿但全不可釋出（同 cluster 節奏鎖）→ force-release 見無 releasable=0、refill added>0 但淨釋出=0**，dead-man 判為雙 0 升 critical。修：`refill_task_pool.py` 加 per-cluster budget，補池「看得見釋出閘門」不再自製單一 cluster 死鎖 + 回歸測試 `test_refill_cluster_budget.py`（commit e96554041，另動 `src/volpred/ops/content.py`）。alert 07-10 已停火、48h 自清；驗證 `remediate_publish_drought.py --dry-run` = no drought — Q3

## L. Paper narrative / 裁決 / review-cert SHA-pin / 規格漂移

**規則**：單一實驗不直接改 `paper/*/body.tex`（只更新 research_program + knowledge）；≥3 互補實驗 + 用戶 confirm 才進 body rewrite。gating 實驗完成必須機械地產生**裁決義務**；handoff 隊列項禁止複製裁定內容（只放 pointer，否則變第二個會漂移的 SoT）。表面 gate 過 ≠ 語義無漂移。
**機械 owner**：`scripts/experiment_gates.py certify` + `review_verdict.json` sha-pin + `paper_adjudication_gap` alert（`src/volpred/ops/alerts.py`）。
**代表 incident**：
- 2026-07-14 Gating 實驗完成後無人裁決 + handoff 抄到已撤回裁定（差點錯殺一篇 JBF 論文）— Q3
- 2026-07-12 K1025_v3 初稿通過表面 gate，語義審查仍抓出四類規格漂移 — Q3
- 2026-07-14 paper snapshot pin 的 auto_adjust 硬規則張力（prg v7 重寫時發現）— Q3
- 2026-05-22 **3-STRIKE** K1380 SPA/RC Test — valid_all joint-mask n_valid=0 結構 — Q2

## M. Source-of-truth drift / registry / supabase / 系列身分

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
**機械 owner**：FB idempotency guard + `fb-publishing` skill（CDP-attach 持久 profile Chrome）。
**代表 incident**：
- 2026-07-08 fb_realchrome_post 附圖偵測器連 4 次假 ABORT（縮圖 count mismatch + 跨 dialog 洩漏）— Q3
- 2026-07-07 FB real-Chrome CDP-attach 接的其實是假 profile — Q3
- 2026-07-07 FB 完稿未持久化到 canonical draft 位置（text-only-in-tmp）— Q3
- 2026-06-03 FB pipeline 4 天 100% 失敗根因 — Q2

## O. Data freshness / 交易日曆 / RV 隔夜跳空 / 交易成本

**規則**：freshness 判斷用**交易日曆**不是日曆天（否則同時誤報與漏報）。日內 RV 不可把隔夜跳空混入日內第一筆報酬。交易成本計算要對市場正確（台股 vs 美股）。資料落後追到產生它的 job，不手補資料。
**機械 owner**：`data-collection-ops` skill（新鮮度判準 + recovery）+ market calendar。
**規則 2 — 等值檢查不是 freshness 檢查**：發布 gate 對抗「上游資料倒退」必須用**單調規則**（資料日期只准前進），`==` 只擋 rerun 擋不住 stale 回應；被 dup_waiver 豁免其他 gate 的內容，僅存 gate 必須獨自扛住所有失效模式。owner：`scripts/daily_update.py::daily_publish_decision` + `tests/test_daily_publish_decision.py`。
**代表 incident**：
- 2026-07-15 15:10 每日更新一天雙發：yfinance 回傳倒退資料（7/13）繞過等值 guard，還誤刪早班正確文（owner 抓包；stale 對 unpublish + 誤刪文 git 還原 + guard 改單調）— Q3
- 2026-07-14 10:15 live_freshness 拿日曆天當交易日曆，同時誤報與漏報 — Q3
- 2026-07-11 0050 五分鐘 RV 把隔夜跳空混入日內第一筆報酬 — Q3
- 2026-03-28 台股交易成本計算錯誤 — Q1

## P. Test / CI / guard leakage / hermetic

**規則**：測試與原始碼要一起上（測試先上、code 沒跟 → main 紅）。pytest guard 要覆蓋 worktree（不能只在被忽略的 root conftest）；collection 不可讀 production `.env.local`。驅動 git 的測試須隔離（臨時 repo，不碰真庫）。「測試寫 canonical state」整個 class 由 CI tree-clean owner 擋。機器要訂閱自己的 CI 狀態（別紅 12 小時沒人看見）。
**機械 owner**：CI pytest（零憑證必全綠）+ pytest.yml tree-clean step（唯一 owner）+ hermetic-git 測試規則 + cron wrapper manifest。
**代表 incident**：
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
- 依 class（明確標記為主）：**§A 並發/dispatch** 最密集（2026-06-23 META、07-12 ×2、07-01 hourly-auth 等）；**§B git-owner/canonical-write**（07-10 ×2）；**§D silent-fallback**（06-20、06-23 test-hook）；**§E dedup/K-id**（06-10、06-23）；**§H final-text**（07-02 ×2）；**§I chart**（07-14、07-13）；**§J dreaming**（07-01）；**§K pool**（06-14）；**§L paper**（05-22）；**§M series**（07-06）；**§C worktree**（07-12 K1032）。
- 查全部：`grep -rn '3-STRIKE' docs/error_log_archive/`。
