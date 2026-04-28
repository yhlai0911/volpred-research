# Project Improvement Status

Last updated: **2026-04-23 (token optimization planning)**

## 2026-04-23 Token Optimization Planning

- ✅ 重寫 [Token 優化計劃（2026-04-23 修正版）](/Users/yhlai0911/Desktop/volpred-research/docs/token_optimization_plan_2026-04-23.md)：依 Claude Code 官方語義重新區分 `subagent` 與 `agent team`，補上 `skills/model/effort/context: fork` 的可用能力與限制。
- ✅ 補上既有 skills 配置矩陣：`admin-ops`、`autonomous-research`、`feed-publisher`、`paper-*`、`memory-health` 等已在計劃中對應預設 `model / effort / context: fork`，可作為下一輪實作 frontmatter 的直接依據。
- ✅ 確認現況：全域 [~/.claude/settings.json](</Users/yhlai0911/.claude/settings.json:94>) 已有 `statusLine`，且 [~/.claude/statusline-command.sh](</Users/yhlai0911/.claude/statusline-command.sh:1>) 已顯示 `context_window.used_percentage`；缺的不是顯示，而是明確行為規則。
- ✅ 專案層 `.claude/settings.json` / `.claude/settings.local.json` 已改為 `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=62`，並移除預設開啟 `agent team` 的 env。
- ✅ chatty hooks 已瘦身：保留 `Stop` / `PreCompact` state save 與針對實驗 Bash 的 `PreToolUse` guard，移除會反覆把 meta 指令塞回 context 的 `SessionStart`、`SubagentStop`、`TaskCompleted`、`Notification`、`PostCompact` hooks。
- ✅ 依官方 hooks lifecycle/cost 文檔補上 `PreToolUse` Bash optimizer：對 `pytest` / `npm test` / `go test` 等高噪音測試命令改走 compact wrapper，完整輸出寫到 `storage/logs/hooks/`，Claude 只看通過摘要或失敗片段；這是目前唯一直接作用在 agentic loop、能穩定減少 token 的 hook 週期。
- ✅ 再把 `PreToolUse` Bash optimizer 擴到高頻人工巡檢輸出：`git status`（保留 `--porcelain` / `-z` 這類機器可讀模式）與大型 log `tail` 現在也會改走 compact wrapper，完整輸出仍落到 `storage/logs/hooks/`，Claude 只看 branch / dirty counts / path preview 或最後 40 行摘要，進一步降低 dirty worktree 與 log 巡檢的固定 context 稅。
- ✅ 新增 [docs/workflow-index.md](/Users/yhlai0911/Desktop/volpred-research/docs/workflow-index.md)：把 workflow、執行模式、預設 `model / effort`、compact 邊界與 detail path 集中成輕量索引。
- ✅ `CLAUDE.md`、`docs/hardware.md`、`.claude/rules/agent-delegation.md`、`autonomous-research` delegation playbook 已同步改成「單一主 session / forked subagent 為預設，agent team 為特例」。
- ✅ 高頻 top-level skills 已補上 `model / effort`，並對 `citation-verifier`、`member-questions`、`memory-health`、`publication-candidates`、`latex-academic-reviewer` 補進 `context: fork` 路由。
- ✅ 將完成任務後的 `bash say ...` 從 `AGENTS.md` / `CLAUDE.md` 這類 always-loaded guide 移出，改成 on-demand 的 [`.claude/commands/task-done.md`](/Users/yhlai0911/Desktop/volpred-research/.claude/commands/task-done.md)：收尾時才做摘要、讀 status line context %、給 `/compact` / `/clear` 建議，最後才播報，避免每個 session 都為這條規則付固定 token 稅。
- ✅ 補上 Phase 4.1 的固定低噪音 summary CLI：`uv run volpred ops queue-summary`、`scheduler-summary`、`token-summary`、`log-summary`。它們都用現有 control-plane / schedule / token report / logs 做 compact readout，取代日常巡檢時手動拼多個較吵命令，降低 context 汙染。
- ✅ 補上 Phase 4.2 的 ID-based execution prompt：`execution_brief` 現在會帶 `workflow_id`，並把 executor / coordinator prompt 從整包 `TASK_JSON + BRIEF_JSON` 收斂成 compact task envelope / execution packet，只保留 `workflow_id`、`required_files`、`success_criteria` 等最小必要欄位，避免把 `updated_at`、`template_hash`、`source_type` 之類 metadata 一起塞進模型。
- ✅ 補上 Phase 4.3 的開工前 boundary gate：新增 [`.claude/commands/task-start.md`](/Users/yhlai0911/Desktop/volpred-research/.claude/commands/task-start.md)，讓跨 workflow 或高成本任務在載入長 skill 前先看 status line context %、決定 `直接開始 / 先 compact / 先 clear`；`/research`、`/publish`、`/deploy` 也同步加上這層 gate，避免在高 context session 直接把長 SOP 再塞進主線。
- ✅ 進一步瘦身 recurring prompt 範例：把 `autonomous-research`、`admin-ops` scheduling 參考與 `scripts/session_startup.md` 內的長 `CronCreate(prompt=\"...\")` 改成短 prompt，改用 `queue-summary`、`scheduler-summary`、`log-summary`、`token-summary` 等固定 CLI 當入口，保留行為意圖但移除冗長步驟描述，降低 session cron / skill 載入時的固定 token 稅。
- ✅ 將 publication topic selection 也收斂到固定低噪音入口：新增 `uv run volpred ops publication-candidates-summary`，把 `publication-candidates`、`feed-publisher` 與 publishing rule 從 `cat/jq storage/publication_candidates.json` 改成 compact snapshot；每週 publication 巡檢 cron 也同步改成短 prompt，降低寫作前 workflow 的固定 token 與 shell glue 噪音。
- ✅ 將平台巡檢也收斂到固定低噪音入口：新增 `uv run volpred ops platform-patrol-summary`，把原本常要交錯讀的 `platform-cycle-summary`、alert 條件、scheduler / health 關鍵欄位壓成單一 compact snapshot；session cron / admin-ops 參考改成先看 patrol summary，只有 breach / release_due / pending_questions 時才下鑽 detail CLI，確保巡檢效果不減損但日常 context 更乾淨。
- ✅ 將會員問題重排入口也改成兩層式：新增 `uv run volpred ops question-ops-summary`，先只看 pending / ranked / candidate pool / top previews；只有 `pending_questions > 0` 時才打開完整 `question-ranking-workflow` 讀 `evaluation_template`。stable insertion rerank、atomic claim 與後續研究/發文流程都不變，但 6 小時巡檢不再每次都把完整 workflow 包塞進 context。
- ✅ 將 `memory-health` 也補成 summary-first workflow：新增 `uv run volpred ops memory-health-summary`，先回報記憶檔大小 / JSON 可讀性 / knowledge duplicates / orphan worktrees；只有 `warn / danger / duplicates / orphan_count > 0` 時才展開完整維護步驟。這樣每週記憶健檢不必每次都執行長 shell/python 區塊，且原本檢查項目沒有減少。
- ✅ 將知識索引檢查也收斂成 summary-first：新增 `uv run volpred ops knowledge-index-summary`，直接回報 `fresh / stale / missing / broken`、state drift、tracked files、index entries、`recommended_action` / `recommended_command` 與 top sources；`knowledge_index_check` 的 canonical prompt、`session_startup` 與 active skills 現在都先看這個 compact gate，依建議決定 `skip / auto / build`，不再把判斷邏輯散落在文件裡。
- ✅ 再把知識索引維護下沉成單一 wrapper CLI：新增 `uv run volpred ops knowledge-index-maintain --stub-if-no-work`，由程式先看 before summary、再自動執行 `skip / auto / build`、最後做 after-check 與 state sync；session cron / active skills 不再需要在 prompt 裡描述 decision tree，no-work 路徑也能只吐極小 stub。
- ✅ 將 `platform_patrol` / `question_research` 也下沉成 wrapper gate：新增 `uv run volpred ops platform-patrol-maintain --stub-if-no-work`、`uv run volpred ops question-ops-maintain --stub-if-no-work`；當沒有 `breach / release_due / pending_questions` 或沒有待評分題目時，cron 可以直接吐 tiny stub，不必每次都把 summary 與 decision 規則載進模型。
- ✅ 將 `continue_task` 也下沉成 slot-aware wrapper gate：新增 `uv run volpred ops continue-task-maintain --stub-if-no-work`，直接根據 `scheduler_preview`、queue snapshot、busy agent count 與 `idle_policy.max_concurrent_agents` 判斷 `no_work / slot_full / blocked_queue / dispatch_candidate`；沒有 runnable work 時 cron 可直接 tiny stub，不再每次都把 queue 規則與 slot-aware 判讀寫在 prompt 裡。
- ✅ 將 `daily_planning` 也下沉成固定 planning gate：新增 `uv run volpred ops daily-planning-maintain --stub-if-no-work`，先把 queue、scheduler 與 platform gate 壓成單一 compact packet；若沒有 `queued_tasks / pending_user_tasks / scheduler_gap / platform_signal` 就直接 tiny stub，避免每日規劃 prompt 每次都重述 queue/scheduler/草稿池檢查規則。
- ✅ 收掉剩餘兩條 recurring prompt 的 decision tax：新增 `uv run volpred ops token-usage-maintain --stub-if-no-work` 與 `uv run volpred ops git-sync-maintain --stub-if-no-work`。前者會自動判斷今日日報與週五週報是否缺失，必要時直接生成後再回報 after summary；後者則把 `git status/branch ahead-behind/dirty tree` 先壓成 compact preflight，只有真的有變更或同步需求時才展開 commit/pull/push。這樣 `token_usage_daily` / `git_sync` 也和其他 recurring workflows 一樣走 wrapper-first，不再靠 prompt 內自然語言 decision tree。
- ✅ 對齊 `release_pool` fallback 的觀測面：`check_alerts.py` 內的 hourly piggy-back release 若成功，現在會同步補寫 `storage/logs/cron/release_pool.log` 與 `storage/ops/cron_last_run.json["release_pool"]`。這不改釋出邏輯，只修正「文章有發出去，但 cron/log/health 看起來像沒跑」的 observability 分叉，避免之後誤判 host cron 是否失效。
- ✅ 將 `ndc_indicator_refresh` 也改成 wrapper-first：新增 `uv run volpred ops ndc-indicator-maintain --stub-if-no-work`，先檢查 `storage/macro/tw_dgbas_bci_m.csv` 是否已達 NDC 2 個月 lag 的預期月份；平常沒缺口時直接 tiny stub，只有 canonical CSV 落後或缺檔時，才展開 `collect_ndc_bci.py` 的人工更新流程。這樣月度台灣景氣指標維護不再每次都把整段更新 SOP 載入主線。
- ✅ 收掉 token 優化計劃剩餘兩個治理尾巴：將 `.claude/skills/member-questions/SKILL.md`、`.claude/skills/taiwan-macro-data/SKILL.md` 正式標準化，並同步更新 workflow index / error log / token plan 引用；避免 provider-visible skill 命名不一致，讓後續 agent-spec render / drift 檢查與自動化治理更單純。
- ✅ 將 `config/runtime_schedules.json` 的 canonical recurring prompts 收斂到 summary-first 短版：`daily_planning`、`continue_task`、`question_research`、`platform_patrol`、`token_usage_daily`、`ndc_indicator_refresh`、`git_sync` 等現在都和 `scripts/session_startup.md` / admin-ops 參考一致，直接指向 `queue-summary`、`question-ops-summary`、`platform-patrol-summary`、`token-summary` 等 compact 入口；效果不變，但日常 recurring prompt 載荷明顯下降。
- ✅ 新增 `config/token_policy.json` 作為 token / context 邊界的 canonical source，集中管理 `auto_compact=62`、`normal/compact/clear` 邊界與 status line 顏色門檻；`task-start`、`task-done`、`research`、`publish`、`deploy`、`workflow-index`、`hardware` 改成引用這份 config，而不再各自 hardcode 一套數字。
- ✅ `scripts/check_session_health.py` 的 `cost / lifetime / cache / messages / active window` threshold 也改成讀 `config/token_policy.json > session_health`，讓 token/context 相關巡檢門檻不再散落在 repo 內腳本。
- ✅ 全域 `~/.claude/statusline-command.sh` 也改成在 repo 內優先讀 `config/token_policy.json > statusline_colors`；畫面上的 context bar 顏色門檻現在和 repo 內 workflow/commands 使用的是同一套 canonical policy。
- 🎯 修正版優先序已調整為：`先把 agent team 從預設降為特例` → `設定 auto-compact 62%` → `建立 workflow index + skills routing` → `用 skill/subagent frontmatter 正式管理 model/effort`。
- 📌 新結論：本專案最該優化的是 **workflow routing 與 context boundary**，不是單純「少用 agent」。`subagent` 應保留並精準使用；`agent team` 只留給真正需要多 session 協作的任務。

## 2026-04-20 v12 continuation session outcomes（16 commits）

### Research
- ✅ **K1259 MCS/SPA meta-analysis 3-phase 完整落地**：Phase 1 ledger 2741 DM rows/236 K/16 assets (commit def4695b) → Phase 1.5 main-thread asset backfill 38%→78% (efd370f4) → Phase 2 HLN-2011 Variant A 18/20 per-asset MCS runs (5314dbd3) + CF-Rolling absence 分析 appendix (5bbeb48e)。**Key finding**: SPY QLIKE α=0.10 88/100 survive, A4f family dominant; GLD MSE 窄 set; α=0.10=0.20 identical; CF-Rolling 真正 absent（Trinity-only evaluation，never DM-compared pairwise）。
- ✅ **K1258 forgetting-factor BMA completed** (commit b6c6225f, agent a09ba983 5.83 min)：H1 FAIL (no Harvey pass), H2 PASS (regime switching restored 10-80x), H3 PASS (optimal λ asset-specific), H4 λ=1.0 default。Structural insight: forgetting 修好 K1257 H3 concentration 但 switching 不 translate 為 predictive gain → BMA family 對 vol forecasting 結構性不足，regime gains 需 switching-model / mixture-of-experts。
- ✅ **K1258 knowledge.json done** (entry 727e23ee, 2026-04-24 main-thread fallback `codex_review.md` PASS-with-caveats)。
- ✅ **K1259 knowledge.json done** (entry c4db347a, 2026-04-28 subagent fallback `codex_review.md` PASS-with-caveats; agent a9496102fadd8a804, commit 7c0013b6)。
- ✅ **K1259 review-cycle 全結 2026-04-28**（3/3 MAJORs closed）：(1) commit `d4c2faf1` MAJOR-3 `load_ledger` docstring loss_fn filter mismatch fix；(2) commit `53c1d559` MAJOR-1 Phase 1.5 backfill scripted — `apply_phase15_backfill.py` + `phase15_asset_map.json` (105 K_ids, 67 singleton + 1023 multi)；(3) commit `aff7b4a5` MAJOR-2 generic-key false-positive sweep — `build_dm_ledger.py` 新增 `NON_DM_PATH_TOKENS = (ttest, mcnemar, wilcoxon, kstest, kruskal)` filter，11 false-positives 移除（K649×4, K706×2, K744×2, K1059×2, K789×1，全 ttest/mcnemar 假性命中 generic `t`/`stat` keys），ledger 2741 → 2730 rows，Phase 2 superior_set stability verified（only cosmetic `middle` removal in SPY/QLIKE）；(4) commit `b1f85845` knowledge `c4db347a` confidence 0.80 → 0.88 finalized；(5) commit `9b9951fd` `research_program.md` K1259 row 同步。**Audit doc**：`experiments/k1259/generic_key_audit.md` 含 methodology + 11-row false-positive table + Phase 2 stability verification。
- ⏸️ **K1258/K1259 feed publication** 推延至 Phase 3 article 階段（meta-analysis 完整 narrative 需 Phase 1+2 結果整合，非單獨 K-finding 文章）。Phase 3 K1259 article 已 dedup-clean (3-layer 2026-04-28T19:40 CST)，可隨時排入後續 slot。

### Platform / Infrastructure
- ✅ **event_jobs full pipeline wired**（round 6 發現 empty → round 13 populate FOMC T-2/T+0 commit aebaeab4 → round 14 root-fix run_due_jobs piggy-back expand_due_event_jobs commit cac18c1a → round 15 standard pattern doc commit 4d7d787c）。完整鏈：host cron `0 * * * *` → check_alerts → run_due_jobs → expand_due_event_jobs → materialize task → 下輪 claim-next。scheduler_tick.log 自 2026-04-19 size=0 的 dead scheduler 被 piggy-back 接管。
- ✅ **Supabase `content_release_settings` PATCH 400 root fix** (commit 8ef0d67b)：`_update_content_release_settings` 拆 local_payload (8 fields 保 shape) vs remote_payload (delta fields only)；schema-mismatch 面積 8→2 fields。3/3 test_content_release_pool PASS。
- ✅ **P8 volatility-absorption reproduce re-verified** (commit 82f9c449)：46 MATCH / 12 MISMATCH / 17 UNTRACE / 75 total = 61.3% consistent since 2026-04-19 errata；no drift。Still awaiting user Path A/B/C decision.
- ✅ **活文件更新**: `.claude/rules/control-plane.md` universal piggy-back §step 6 + event_jobs populate 規範 + standard event pattern (CPI/NFP/FOMC/Earnings T-series); `docs/error_log.md` scheduler_tick dead incident + Supabase PATCH delta-payload root-fix entries。
- ✅ **`storage/next_tasks.json` legacy list GC** (commit e3732d3e)：106→82 entries, -298 行，24 completed/done 清除，canonical queue 不動。
- ✅ **feed INDEX refresh** (commit ce9a6a78)：944→949 articles, draft 5→8。

### Content
- ✅ **K1257 BMA draft mile_5173955c queued** (audience=research, 11415 chars, 2107 CJK)。
- ✅ **FOMC T-2 dispatch memo** (commit 15b6c27c)：`storage/next_draft_candidate_fomc_t2.md` 含 scenario-conditional number grid 主題軸 + 3-layer dedup checklist；wired to event_jobs entry fomc-2026-04-29-t2 (2026-04-26 00:00 CST not_before)。
- ✅ **FOMC T+0 event_job entry**（fomc-2026-04-29-t0, 2026-04-29 21:00 CST post-announce, requires_websearch）。

### Meta / Governance
- ✅ **Standard event pattern** 寫入 .claude/rules/control-plane.md — 6 種 event-type (FOMC/CPI/NFP/Earnings/央行/Geo) 檢查清單 + T-series slot 表 + 配額 cap + 6-step populate workflow + ROI 排序。未來任何新事件 populate 只查此段 + copy template。
- ✅ **Rule path-trigger timing principle** (pre-session commit a5573c81) — 寫規則時必檢查 paths 是否 cover planning/selection phase 而不只 execution。

---

## v12 Transition Status (2026-04-19 update)

> **v11 → v12**: 原 v11 3-terminal 架構（Claude supervisor + worker + Codex worker）已 retired (session cron decommissioned as execution clock)，**v12 模式**為 single main-thread Claude + ephemeral subagent dispatch（claude general-purpose / codex-rescue）。canonical source of truth = `storage/ops/` control plane + `config/runtime_schedules.json` + `event_jobs`。

### 2026-04-19 v12 session outcomes
- ✅ **5 Codex ops victories**（task_4e75 snapshot infra / task_fdf8 release-pool fix / task_361a P6 audit / task_9b07 session-bootstrap v11 cleanup / task_6e7c claim-next parent guard）
- ✅ **4 papers GREEN**（P4 vix-sufficiency 98% / P4ins vt-insurance-cost 100% / P5 vt-crowding-abm 100% / P6 prg-periodic-garch 100%）— 首次四篇 submission-ready
- ✅ **6 papers 0 MISMATCH**（+P1 / P2 / P3 cross-source NOTE reclass clean）
- ✅ **Host cron selectivity bug workaround**: `scripts/check_alerts.py` `_auto_trigger_release_pool_if_due()` piggy-back（解 `3 */2` cron silent skip issue）
- ✅ **Session cleanup**（0 stale claims / 0 orphan worktrees / 0 orphan worktree-* branches）
- ⏸️ **Codex quota 耗盡** until 2026-04-24 10:27 UTC；wake-up cron + canonical schedule entry 已建（one-shot durable）
- 📝 **3 reusable next-draft memos** (K957 / K1091 / K1092) for future pool-breach remediation
- 📝 **2 errata_pending.md** (P8 CRITICAL / P9 shelf-ready)
- 📝 **Release cadence** unified to 120 min interval + 2h cron

### 2026-04-19 18:00+ UTC post-compact saturation-round work (Codex-blocked observation mode)

- ✅ **K1174 memo written + DOWNGRADED**（score 10 但 `mile_45060685` 已以 footer 吸收 — pivot-angle 用）
- ✅ **publication_candidates.json rebuild** (stale 3h → fresh 18:35)；uncovered 225→215；真正 uncovered K1100-K1224 僅 K1106 + K1115（大部分已被 content/title-matching 覆蓋）
- ✅ **alerts.py `release_pool_gap` false-positive fix**：`_parse_release_pool_state` 補 `.release_settings.json.last_released_at` 作 alternative truth source — 前 24h dedup-壓著的每小時 false-positive 鏈結束（驗證 `check-alerts` → `breached=false gap=0.78h`）
- ✅ **experiments/INDEX.md rebuild**（5h30m stale → fresh；1011→1012 K，uncovered 736→735）
- ✅ **docs/strategy-registry.md drift fix**（header 14/10 active → 實 14/11 active，附 verified timestamp + code line ref）
- ✅ **Question archive**: 2026-03-20 keyboard-mash garbage question `54ba8732` (testtewtrwqetwqtewqtqwet) archived — 清 member_qa ranking 污染
- ✅ **K957 knowledge.json metadata fix**（title 37→40 Experiments / 第一句 4 缺 K→K555 唯一缺 / 研究效率觀察 37→40 + 5.4→5.0%）
- 📝 **error_log 3 新 section**: P1/P2/P3 reproduce_report stale / alerts piggy-back 失明 / K957 KB-article drift map
- 📝 **Piggy-back production-validated** (18:00 UTC 純自動 trigger mile_1beaaa3f released — 第一次 auto-release 不靠主線程 intervention)

### Historical v11 context 保留於下方（不刪除，作為 architecture evolution reference）

---

## VolPred 雙 Agent 最終優化方案 v11

### Summary

- 本方案只在**目前 `volpred-research` 專案基礎上增量調整**，不重做網站、不替換 `storage/` / `ops` / `frontend-v2-fix/` / Supabase / Mirror / Admin 主架構。
- 優先序正式鎖定為：**正確性 > 穩定性 > token 效率 > 吞吐量**。
- 運作模式鎖定為：**Claude Code = 協調者 / 規則主導者 / brief builder；Claude 與 Codex = 執行者；control plane = 唯一狀態來源。** repo 目前仍保留 `shared scheduler` 這條 `cron-driven` 過渡路徑，但校正後的目標 runtime 是 VS Code supervisor / worker sessions。
- `2026-04-18` 依 user story 校正後，**正式操作故事應是 VS Code 三終端機模式**：1 個 Claude supervisor 管理排程 / brief / 狀態，1 個 Claude worker + 1 個 Codex worker 在已登入 OAuth 的互動 session 內認領並完成任務。
- shared scheduler 跑在 **macOS `crontab`**；Claude 既有 session cron **退役為非執行時鐘**，只保留提醒與 monitor；`idle_policy` 僅作為 slot-aware continuation / selection policy，不是另一個主時鐘。
- shared scheduler 對 live manual agent session 採保守策略：若偵測到非 scheduler 擁有的 Claude/Codex session 仍在線，則不會搶同一個 agent。
- 目前 repo 仍殘留 `scheduler -> subprocess.run(["claude", "-p", ...]) / subprocess.run(["codex", "exec", ...])` 的 headless 路徑；這是**偏離 user story 的過渡期實作**，不應視為最終 runtime contract。
- Claude 與 Codex **都可以提出 cron / schedule 需求**，但只有 **Claude coordinator** 可以把需求落成正式 canonical schedule、調整排程策略、安裝或移除 cron。
- 每輪任務都必須符合 **codebase grounding contract**：在 repo root 啟動、先讀必要背景、用結構化 brief 控制上下文；拿不到足夠背景就 fail closed。
- 一次性任務與事件前後任務正式納入 canonical schedule，新增 `event_jobs`；不再只靠 prompt 或自由文字文件記憶。
- **Brief 生成策略固定為 `C`：模板優先，Claude 協調輪只處理例外。**
- brief 模板固定放在 **`config/brief_templates/<task_family>.yaml`**。
- Claude coordinator 的 JSON brief 固定採 **pydantic 驗證 + fenced JSON 抽取 + 最多 2 次重試**；第 3 次失敗即標記 `brief_status=needs_manual_review`。
- brief 過期規則固定為：**`task.updated_at > brief_payload.generated_at` 或 template hash 改變**。
- scheduler cron 安裝與移除腳本化處理：**`scripts/install_scheduler_cron.sh`**、**`scripts/uninstall_scheduler_cron.sh`**。
- v1 **不做 task dependency graph**；事件鏈先靠 `not_before/deadline` + preconditions + fail-closed preflight 控制。
- **存檔目標**鎖定為 `docs/project_improvement_status.md`；本檔即為最終規格版本。

### Implementation Status

- 已完成：
  - Phase 6 provider skills render 修正
  - Phase 3 最小 schema 擴充
  - Phase 1 session lifecycle wrappers
  - Phase 2 auto routing
  - Phase 4 `experiment_id` 並發防撞
  - Phase 5 `agent-spec sync` alias
  - Phase 5b `event_jobs` / event ledger / preview / GC
  - Phase 7a shared scheduler tick、self-lock、scheduler state、cron wrapper scripts
  - Phase 7b execution brief、template-first policy、prior findings、fail-closed preflight
  - Phase 7c 基礎 observability：CLI、health snapshot、control-plane summary、admin ops/health 指標
  - scheduler 與 live manual Claude/Codex session 共存護欄：目標 agent 已被真人 session 佔用時，tick 會跳過並回報 `no_runnable_work`
  - `preconditions` 已落地為實際派工護欄：scheduler 會跳過未滿足前置條件的 task，executor preflight 也會把手動 claim 的 task 重新排回 queue
  - schedule governance contract 已落地：`payload.governance_area=schedule` / `payload.schedule_proposal` 會被系統辨識，並強制收斂到 Claude 作為治理 owner
  - schedule proposal 任務已有專用 brief template，`/admin/ops` 也能直接看到 `governance schedule` badge
  - `uv run volpred ops propose-schedule ...` 已提供正式 CLI 提案入口，Claude/Codex 都可用同一個 contract 建立 schedule proposal task
  - `/admin/ops` 建立本機 task 表單已補齊 `member` / `strategy` family、`public_effect` 欄位與「Schedule Proposal 範本」快捷按鈕
  - `storage/next_tasks.json` 的定位已正式收斂為 **legacy planning / working list**；canonical orchestration 仍以 `storage/ops/` control plane、`config/runtime_schedules.json`、`event_jobs` / `event_ledger` 為準
  - session worker flow 已補強：`next-task --emit-brief` 現在只會返回可執行 task，會跳過尚未被 supervisor brief 化或 preconditions 未滿足的 queued task
  - supervisor 已可用 `uv run volpred ops brief-show` / `brief-set` 正式查看與寫入 manual brief，不必手改 `storage/ops/tasks/*.json`
  - canonical `system_crontab` spec 已補上 `shared_scheduler_tick`，並把既有 `market_calendar sync` 納回 canonical，避免 install script、live crontab 與 `/admin/schedules` 的 source of truth 分裂
  - shared scheduler 已實際安裝進本機 `crontab`，目前 canonical system tasks 與 live crontab 對齊（`schedule-report` = `6/6` matched）
  - `/admin/schedules` 的心智模型已更新：shared scheduler / system crontab 為正式時鐘，session cron 僅保留為 legacy session convenience
  - coordinator / executor subprocess 已補 timeout fail-closed 護欄，避免 `claude -p` / `codex exec` 卡住時長時間占住 scheduler self-lock
  - 已新增 `uv run volpred ops scheduler-smoke` 隔離 smoke helper：自備最小 prompt / brief template，mock 掉真實 `claude -p` / `codex exec`，可在不碰 live queue 的前提下驗證 coordinator 與 executor 鏈路
  - 已新增 `uv run volpred ops scheduler-live-smoke`：用隔離 storage 真正呼叫本機 Claude/Codex CLI 做最終 smoke；Claude 走 no-persistence + no-tools，Codex 走 read-only sandbox + ephemeral，避免碰 live queue 與 repo 內容
  - 已補 execution brief CLI 相容性修正：Claude `-p --output-format json` result envelope / 純文字錯誤可正確解包；Codex output schema 已符合新版 `additionalProperties=false` 與 full required set 規則
  - 已新增 agent CLI readiness snapshot：`scheduler-live-smoke` 會把 Claude/Codex live path 分類成 `ready / auth_required / free_text_response / schema_mismatch / timeout` 等狀態，寫入 `storage/ops/agent_cli_health.json`，`ops health` / `/admin/health` 可直接觀察
- 已驗證：
  - `uv run pytest tests/test_shared_lock.py tests/test_execution_brief.py tests/test_scheduler.py tests/test_agent_spec.py tests/test_local_control_plane.py tests/test_stale_reclaim.py tests/test_session_ops.py tests/test_event_jobs.py tests/test_runtime_schedules.py`
  - `uv run python -m volpred.cli ops scheduler-preview`
  - `uv run python -m volpred.cli ops event-preview`
  - `uv run python -m volpred.cli ops scheduler-tick`
  - `uv run python -m volpred.cli ops control-plane-summary`
  - `uv run python -m volpred.cli ops health`
  - `uv run python -m volpred.cli ops schedule-report`
  - `bash scripts/install_scheduler_cron.sh`
  - `bash scripts/run_scheduler_tick.sh`
  - `cd frontend-v2-fix && npm run typecheck`
  - `uv run pytest tests/test_execution_brief.py tests/test_scheduler.py`
  - `uv run python -m volpred.cli ops agent-spec check --target all`
  - `uv run python -m volpred.cli ops propose-schedule --title ... --description ... --proposal-json ... --storage-dir /tmp/...`
  - `uv run python -m volpred.cli ops task-show <task_id> --storage-dir /tmp/...`
  - `uv run python -m volpred.cli ops scheduler-smoke --mode both --cleanup`
  - `uv run python -m volpred.cli ops scheduler-live-smoke --mode all --cleanup`
  - `2026-04-18` live smoke 實測：Codex executor path 已通過（read-only sandbox、`files_touched=[]`）；Claude coordinator / executor 目前仍會輸出自由文字而非 schema-valid JSON，因此 helper 已能穩定暴露這個剩餘 gap
  - `cd frontend-v2-fix && npm run typecheck`
- 尚未執行：
  - 將正式執行路徑從 headless scheduler subprocess 收斂回 VS Code supervisor / worker session 模式，並退役或降級 `claude -p` / `codex exec` 直跑 task 的舊路徑
  - Claude live structured-output compatibility remediation（`scheduler-live-smoke` 已確認 gap，可作為後續修正入口）
  - 最終 commit / deploy

### User Stories

- 作為專案 owner，我希望打開 VS Code 後能建立 3 個終端機：1 個 Claude supervisor、1 個 Claude worker、1 個 Codex worker；全部都用 OAuth 訂閱登入的互動 session，而不是背景另外開 headless process。
- 作為專案 owner，我希望平台能在**不犧牲正確性與穩定性**的前提下持續推進任務，而不是為了並行而增加錯誤與重工。
- 作為專案 owner，我希望 **Claude 負責協調與規則判斷**，而 Claude 或 Codex 都可以根據任務類型成為執行者。
- 作為專案 owner，我希望每輪任務都能讀到**剛好夠用的 codebase 背景**，而不是每次都重掃整個 repo 浪費 token。
- 作為專案 owner，我希望 recurring 任務、一次性任務、事件前後任務都能由同一套 canonical schedule 管理，不再分散在 session cron、prompt 與活文件裡。
- 作為專案 owner，我希望 Codex 持續參與系統，但主要聚焦在 **code/review/ops/bug rescue**，而不是一開始就和 Claude 完全對等搶任務。
- 作為專案 owner，我希望所有 mutating 任務都能追溯到 session、rollback point、brief、execution receipt，失敗時可以完整恢復。
- 作為專案 owner，我希望導入新 orchestration 後，網站上的文章、策略績效、會員問答、工具頁仍照常運作。
- 作為專案 owner，我希望從 `/admin/ops`、`/admin/health`、CLI 看到 scheduler、event materialization、agent session、approval、rollback、brief 狀態的實際情況。
- 作為 Claude 協調者，我希望能用最少 token 先把任務變成低歧義、可執行、可驗證的 brief，再決定交給 Claude 或 Codex。
- 作為 Claude supervisor，我希望能在互動 session 中查看 task、補 manual brief、調整 queue，然後由 worker terminals 去 claim 與完成任務。
- 作為 Codex 執行者，我希望接到的是已經定義好目標、必讀檔案、成功標準、禁止整檔讀取清單的任務，而不是模糊探索題。
- 作為平台維運者，我希望 scheduler 空轉時幾乎不耗 token，只有真的有可做任務時才喚起 LLM。
- 作為事件任務管理者，我希望 CPI / NFP / FOMC / TSMC 財報前後任務能被正式展開、去重、觀測，而不是靠記憶與臨場判斷。

### Key Scenarios

#### 1. 每日自動運作

- `crontab` 定時執行 `scripts/run_scheduler_tick.sh`。
- wrapper 腳本負責切到 repo root、載入 `.env.local`、補 PATH、執行 `uv run volpred ops scheduler-tick`。
- `scheduler-tick` 一開始先取 **`shared_state_lock("scheduler_tick")` 非阻塞鎖**；拿不到就直接退出 0，代表上一輪還在跑。
- 若目標 agent 已被 live manual session 佔用，該輪視為 `no_runnable_work`，不強行覆蓋 agent session。
- 若 task 的 `preconditions` 尚未成立，該輪也視為不可執行，不會進入 coordinator/executor。
- scheduler 再做 queue、stale reclaim、event expander、approval backlog、slot 檢查。
- 沒有可做任務就直接退出；有任務才喚起 Claude 或 Codex。

#### 2. recurring 任務

- 例子：平台巡檢、會員問題、知識索引檢查、token 日報。
- scheduler 依 recurring 規則找到 task family，直接載入 `config/brief_templates/<task_family>.yaml`。
- 模板足夠時不跑 Claude 協調輪。
- 模板 preflight 不成立時直接 fail-closed，不用 LLM 補猜。

#### 3. 一次性任務

- `event_jobs.trigger_mode=one_shot` 定義只跑一次的任務。
- scheduler 到時間後 materialize 成正式 task。
- `dedupe_key` 保證同一任務只建立一次。
- materialize 同時寫入 event ledger，避免下一輪 tick 重建。

#### 4. 事件前後任務

- 例子：CPI / NFP / FOMC / TSMC 財報前後的資料抓取、分析、文章、會員問答。
- `event_jobs.trigger_mode=relative_to_event` 用 `not_before` / `deadline` 控制窗口。
- `event_key` 固定為 `{type}_{yyyymmdd}_{variant?}`。
- `dedupe_key` 固定為 `{event_key}:{task_family}`。
- v1 不做 `depends_on_task_ids`；改用時間窗錯開與 preconditions 檢查產物是否存在。

#### 5. 模糊或跨領域任務

- 模板不足、brief 缺失、brief 過期、事件複雜、跨模組、研究 discovery、高風險任務，先喚起 Claude 協調輪。
- 協調輪輸出 schema-valid JSON brief。
- 若重試 2 次仍不合法，task 轉 `brief_status=needs_manual_review` 與 `status=blocked`。

#### 6. Code Review / Bug Rescue

- 若任務明確屬於 code/review/ops，且 brief 已就緒，直接派給 Codex。
- 若背景不清楚、跨多模組、或 risk 高，先由 Claude 補 brief，再交 Codex。
- Codex 不需要重掃整個 repo，只讀 `required_files` 與少量 `recommended_files`。

#### 7. 任務中斷與恢復

- 某個 agent session 中斷或超過 stale threshold。
- 後續 tick 執行 stale reclaim，把 task 釋回 queue。
- scheduler 下一輪重新分派，不讓任務永久卡死。

#### 8. 高風險公開行為

- 正式發文、會員可見回答、策略 runtime 變更等高影響任務進入 approval gate。
- 先建立 rollback、生成 brief、跑 preflight、等 approval。
- 通過後才對外落地。

### Final Architecture

#### Scheduler

- 唯一 clock，透過 `crontab` 執行 `scripts/run_scheduler_tick.sh`。
- 僅負責機械節奏、event expander、cheap preflight、派工判斷。
- `scheduler-tick` 使用專用 self-lock，避免雙 tick 併發。
- scheduler 是 **中立執行層**，不是 Claude/Codex 任一方私有的時鐘；但排程治理權歸 Claude coordinator。

#### Coordinator

- 預設由 Claude fresh-context 執行。
- 僅在模板不足、brief 缺失/過期、事件複雜、任務模糊或高風險時啟動。
- 輸出必須是**可驗證的 JSON brief**。
- Claude 也是 **schedule governance owner**：
  - 接收 Claude/Codex 提出的 cron 需求
  - 決定是否納入 `config/runtime_schedules.json`
  - 決定 `event_jobs` / recurring 規則 / cadence 調整
  - 決定是否執行 `install_scheduler_cron.sh` / `uninstall_scheduler_cron.sh`

#### Executors

- Claude：研究、內容、會員、模糊或高判斷任務。
- Codex：code、review、ops、bug rescue、明確結構化任務。
- Codex 不做開放式 discovery，只接已 brief 化任務。
- 因此「排程由 Claude 治理」**不等於**「所有 cron-triggered 任務都只能由 Claude 實作」；若任務 brief 清楚，仍可由 Codex 作為 executor。

#### Control Plane

- 任務、session、approval、rollback、execution receipt 的唯一協調層。
- scheduler、Claude、Codex 都只能透過 ops layer 改共享狀態。

#### Grounding

- brief 是 worker 的正式執行入口。
- executor 必須先讀 `required_files`。
- `forbidden_large_files` 是 prompt 級禁止整檔讀取清單。
- 必要背景不足時不得硬做。

### Public Interfaces / Data Contracts

#### New CLI

- `uv run volpred ops session-bootstrap --agent claude|codex`
- `uv run volpred ops next-task --agent claude|codex [--emit-brief]`
- `uv run volpred ops finish-task --agent claude|codex --task-id ...`
- `uv run volpred ops session-shutdown --agent claude|codex`
- `uv run volpred ops brief-show <task_id>`
- `uv run volpred ops brief-set <task_id> --brief-json ... --actor ...`
- `uv run volpred ops requeue-task --task-id ... --actor ... --reason ...`
- `uv run volpred ops agent-spec sync --from claude|codex`
- `uv run volpred ops scheduler-tick`
- `uv run volpred ops scheduler-preview`
- `uv run volpred ops scheduler-smoke [--mode coordinator|executor|both] [--cleanup]`
- `uv run volpred ops scheduler-live-smoke [--mode coordinator|claude-executor|codex-executor|all] [--cleanup]`
- `uv run volpred ops event-preview`

#### New Scripts

- `scripts/run_scheduler_tick.sh`
- `scripts/install_scheduler_cron.sh`
- `scripts/uninstall_scheduler_cron.sh`

#### New Config / Template Paths

- `config/runtime_schedules.json`
  - 新增 optional section：`event_jobs`
- `config/brief_templates/<task_family>.yaml`
- `config/agent_prompts/claude_coordinator.txt`
- `config/agent_prompts/claude_executor.txt`
- `config/agent_prompts/codex_executor.txt`

#### TaskRecord 新欄位

- `session_id: Optional[str]`
- `rollback_point_id: Optional[str]`
- `public_effect: Optional[str]`
- `brief_status: Optional[str]`
- `brief_payload: Optional[dict]`

#### AgentSession 新欄位

- `session_rollback_point_id: Optional[str]`

#### ExecutionReceipt 新欄位

- `session_id: Optional[str]`
- `rollback_point_id: Optional[str]`

#### `brief_status` 列舉

- `pending`
- `ready`
- `stale`
- `needs_manual_review`

#### `brief_payload` 固定欄位

- `generated_at`
- `source_type`: `template | coordinator`
- `template_id`
- `template_hash`
- `coordinator_run_id`
- `task_summary`
- `goal`
- `success_criteria`
- `repo_root`
- `required_files`
- `recommended_files`
- `forbidden_large_files`
- `relevant_commands`
- `prior_findings`
- `rollback_point_id`
- `why_this_agent`

#### `event_jobs` 固定欄位

- `id`
- `event_key`
- `trigger_mode`: `one_shot | relative_to_event`
- `not_before`
- `deadline`
- `dedupe_key`
- `preferred_agent`
- `public_effect`
- `task_template`

#### `task_template` 固定欄位

- `title`
- `description`
- `task_family`
- `priority`
- `preferred_agent`
- `approval_mode`
- `risk_level`
- `payload_patch`
- `brief_template`
- `preconditions`

#### Event Ledger

- materialize 後必寫到 `storage/ops/event_ledger/`
- 為避免 path 字元問題，檔名用 `sha256(dedupe_key).json`
- ledger 內容至少包含：
  - `dedupe_key`
  - `event_key`
  - `task_family`
  - `task_id`
  - `materialized_at`
  - `deadline`
  - `gc_after`
- `gc_after` 固定為 `deadline + 7 days`
- expander 以 ledger 作為是否已 materialize 的唯一判斷來源
- scheduler 每次 tick 只做便宜 GC；刪除已過 `gc_after` 的 ledger

#### Compatibility Rules

- 所有新欄位都必須向後相容：`Optional[...] = None`
- 所有舊 JSON 讀取時一律 `.get(...)`
- 不做 migration
- `payload` 本 phase 只認 `payload["experiment_id"]` 單數字串

### Brief Generation Policy

- 策略固定為：**模板優先，Claude 協調輪只處理例外**
- recurring、明確、低歧義 task family：使用 `config/brief_templates/<task_family>.yaml`
- schedule governance 任務：優先使用 `config/brief_templates/schedule-governance.yaml`，且 scheduler 先走 Claude 協調輪
- 事件任務：先試事件模板；模板不足才跑 Claude 協調輪
- 研究 discovery、跨模組、模糊或高風險任務：跑 Claude 協調輪
- JSON 保證機制：
  - 抽取 fenced JSON 或第一個合法 JSON object
  - 用 pydantic schema 驗證
  - 最多重試 2 次
  - 第 3 次失敗：`brief_status=needs_manual_review`
- brief 過期規則：
  - `task.updated_at > brief_payload.generated_at`
  - 或 `brief_payload.template_hash != current_template_hash`
  - 任一成立即把 `brief_status` 轉為 `stale`
- `prior_findings` 自動填入規則：
  - `--emit-brief` 時自動讀取該 `task_id` 最近 3 筆 `ExecutionReceipt`
  - 收集非空 `summary` 與關鍵 `error`
  - 組成 `prior_findings` list
  - coordinator 如有更精確內容，可覆蓋或追加
- executor prompt 預設採**self-contained 模式**
  - 即使 `claude -p` 會載入 skills，也不把 auto-loaded skills 當正確性前提
  - Phase 0 會 smoke test `claude -p` 的 skills 可用性，但 Phase 7b 的執行面仍以 self-contained brief 為準
  - skill 名稱可作為提示，不作必要依賴

### Cron Governance Policy

- Claude 與 Codex 都可以提出：
  - 新 recurring 任務需求
  - 新 `event_jobs` 需求
  - cadence / interval 調整建議
  - 停用、延後、加嚴 preconditions 的建議
- 但正式落地只走 Claude coordinator：
  - 修改 `config/runtime_schedules.json`
  - 修改 `scripts/run_scheduler_tick.sh`
  - 執行 `scripts/install_scheduler_cron.sh`
  - 執行 `scripts/uninstall_scheduler_cron.sh`
  - 調整 shared scheduler 的 routing / policy
- Codex 不直接擁有 cron 安裝權，也不直接成為 canonical schedule 的最終作者。
- 若 Codex 發現需要排程變更，應產出：
  - task / brief / code review finding / schedule proposal
  - 再由 Claude coordinator 審核後納入 canonical
- schedule proposal 的 payload contract：
  - `governance_area: "schedule"`
  - `schedule_proposal: {...}`
- 一旦符合上述 contract，即使建立 task 的人是 Codex，control plane 也會把正式治理任務收斂到 Claude
- v1 的保守預設：
  - schedule discovery 可以來自兩邊
  - schedule governance 只由 Claude
  - schedule-triggered 任務若模板足夠，可直接派給 Codex executor
  - 但任何 schedule 規則變動仍需 Claude 寫回 canonical

### Fail-Closed Policy

#### Global Tick Failure

- `scheduler-tick` 在 claim 前若發現 repo root 錯誤、runtime config 無法讀取、scheduler self-lock 未取得：
  - 直接退出
  - 不變更任何 task 狀態
  - 寫 scheduler log

#### Task-Scoped Preflight Failure

- repo root mismatch / agent-spec drift / skills render 壞：
  - task 轉 `blocked`
  - `last_error` 記錄原因
  - 清掉 claim
  - 寫 execution receipt，`result_status=blocked_preflight`
- brief missing / stale：
  - `brief_status=stale`
  - 若 task 已被 claim，釋放 claim 並回 `queued`
  - 下輪 scheduler 重新生成 brief
- `required_files` 不存在：
  - task 轉 `failed`
  - `last_error` 記錄缺檔
  - 清掉 claim
- coordinator 3 次 retry 全失敗：
  - `brief_status=needs_manual_review`
  - task 轉 `blocked`
  - 清掉 claim
- `blocked` 不是 terminal，但 scheduler 不會自動重跑 blocked task
- blocked task 修復後，需透過 `ops requeue-task` 明確回到 `queued`

### Event Layer Policy

- `event_key` 固定格式：`{type}_{yyyymmdd}_{variant?}`
- `dedupe_key` 固定格式：`{event_key}:{task_family}`
- v1 不做 `depends_on_task_ids`
- 替代方案：
  - 事件任務用 `not_before/deadline` 錯開
  - `task_template.preconditions` 檢查必要檔案 / 產物 / 狀態
  - preconditions 不成立時不派工或 fail-closed
- 若未來實務上真的出現 race，再升級到 dependency graph

### Implementation Plan

#### Phase 0: Baseline 與回滾起點

- 建立 named rollback baseline
- 記錄：
  - `uv run volpred ops agent-spec check --target all`
  - `uv run volpred ops control-plane-summary`
  - `uv run volpred ops health`
  - Claude/Codex CLI skills warnings
  - `claude -p "list skills you have access to in this repo"` smoke 結果
- 每 phase 結束固定執行：
  - `pytest`
  - `uv run volpred ops agent-spec check --target all`
  - `uv run volpred ops health`
  - git commit

#### Phase 6: Provider Skills Render 修正

- 修 `src/volpred/ops/agent_spec.py` 的 header 注入點
- 所有 provider-rendered `SKILL.md` 第一行都必須是 `---`
- `.claude/skills/**` 與 `.agents/skills/**` 一起修
- provider-visible `skill.md` 一律 render 成 `SKILL.md`
- 驗證時本機同時檢查 `.claude/skills/**` 與 `.agents/skills/**` 第一行
- 注意 `.agents/skills/**` 為本機 render 產物，PR 主要只會看到 `.claude/` diff

#### Phase 3: 最小 Schema 擴充

- `TaskRecord` 增加 `session_id`, `rollback_point_id`, `public_effect`, `brief_status`, `brief_payload`
- `AgentSession` 增加 `session_rollback_point_id`
- `ExecutionReceipt` 增加 `session_id`, `rollback_point_id`
- `public_effect` 固定枚舉：
  - `none`
  - `draft_only`
  - `published`
  - `member_visible`
  - `prod_runtime`

#### Phase 1: Session Lifecycle Wrappers

- `session-bootstrap`
  - 驗證 `VOLPRED_ACTOR == args.agent`
  - 建立 session rollback point
  - 執行 `agent-spec check`
  - 寫入 heartbeat / session metadata
- `next-task`
  - heartbeat
  - claim-next
  - 繼承 `session_id` / `session_rollback_point_id`
  - 需要時輸出 execution brief
- `finish-task`
  - 成功與失敗都寫 execution receipt
- `session-shutdown`
  - 標 offline，必要時釋放 claim
- `requeue-task`
  - 僅允許 `blocked` task 回到 `queued`
  - 記錄 actor 與 reason

#### Phase 2: Auto Routing

- 保留現有 `task_family`
- `preferred_agent=auto` 時映射：
  - `research/content/member -> claude`
  - `code/review/ops/strategy -> codex`
- scheduler 先看 `brief_status`
  - 未 brief / stale / 模糊 / 事件任務：先交 Claude 協調
  - 已 brief 且 `preferred_agent=codex`：可直接交 Codex

#### Phase 4: `experiment_id` 並發防撞

- claim 流程新增 guard：
  - 若 queued task 的 `payload.experiment_id` 已被另一個非 terminal task 佔用，則本輪跳過

#### Phase 5: `agent-spec sync` Alias 正式化

- 新增 `ops agent-spec sync --from claude|codex`
- 內部等價於：
  - `import --from <provider>`
  - `render --target all`
  - `check --target all`

#### Phase 5b: Event Layer

- 在 `config/runtime_schedules.json` 增加 `event_jobs`
- 新增 event expander
  - 讀 `event_jobs`
  - 判斷 `not_before` / `deadline`
  - 用 `dedupe_key` 與 ledger 防重複 materialize
  - 依 `task_template` 建立 control-plane tasks
- 新增 `storage/ops/event_ledger/`
- scheduler 每 tick 執行 event ledger 輕量 GC
- `research_program.md` 保留事件敘事，但不再作為 scheduler 唯一事件來源

#### Phase 7a: Shared Scheduler Tick

- 新增 `src/volpred/ops/scheduler.py`
- `scheduler-tick`
  - 非阻塞取得 `shared_state_lock("scheduler_tick")`
  - 讀 `runtime_schedules.json`
  - stale reclaim
  - event expander
  - cheap preflight：queue / approvals / discovery / slots
  - 無可做任務時直接退出
  - 有任務時決定本輪走 coordinator 或 executor
- `scheduler-preview`
  - 回報本輪會做什麼，不執行
- scheduler 部署層固定為 **macOS `crontab`**
- system crontab 既有永久任務保留，只新增 orchestration tick
- scheduler 自身 logging 改用 `RotatingFileHandler(10MB, backupCount=5)`

#### Phase 7b: Execution Brief 與 Grounding Contract

- 新增 `src/volpred/ops/execution_brief.py`
- recurring task family 先查 `config/brief_templates/`
- 例外 task 再跑 Claude coordinator
- `forbidden_large_files` 在 executor prompt 中轉成 `DO NOT read these files in full`
- `required_files` 必須足以完成任務；若不足則回 `needs_manual_review`
- 大檔沿用既有 token discipline，禁止整檔讀

#### Phase 7c: Observability 與 Cron 退役整理

- `/admin/ops` 與 `/admin/health` 增加：
  - active agents
  - approval backlog
  - latest rollback point
  - recent execution receipts
  - agent-spec drift
  - scheduler heartbeat / last tick
  - event materialization 狀態
  - brief_status 分布
- Claude session cron 退役為非執行時鐘
- `scripts/setup_session_crons.sh` 與 `scripts/session_startup.md` 改寫為：
  - shared scheduler 是正式時鐘
  - session cron 只剩 monitor / 提醒
- 新增：
  - `scripts/install_scheduler_cron.sh`
  - `scripts/uninstall_scheduler_cron.sh`
- cron 安裝必須 idempotent，可重跑、不重複插入
- install script 用固定 tag comment，例如 `# volpred-scheduler-tick`
- uninstall script 依 tag comment 清除

### Runtime Behavior After Completion

- `crontab` 定時執行 `scripts/run_scheduler_tick.sh`
- `run_scheduler_tick.sh` 固定內容：
  - `cd /Users/yhlai0911/Desktop/volpred-research`
  - `set -a; source .env.local 2>/dev/null || true; set +a`
  - `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"`
  - `exec uv run volpred ops scheduler-tick`
- 正式派工由 `crontab -> shared scheduler tick` 驅動；`idle_policy` 只決定 slot 空出時如何挑 user / scheduled / discovery 任務，不是獨立自動觸發器
- 建議 cron line：
  - `*/10 * * * * /Users/yhlai0911/Desktop/volpred-research/scripts/run_scheduler_tick.sh # volpred-scheduler-tick`
- scheduler 先做便宜檢查與 event 展開
- recurring/固定模式任務先查模板；模板足夠就直接派工
- 模糊、事件複雜、研究 discovery 任務才喚起 Claude 協調輪生成 brief
- Claude 是協調者，不是每輪都必經的人肉轉接站
- Codex 主要處理被明確 brief 化的任務
- 系統在**機器開著且 `crontab` 生效**時可穩定持續推進；睡眠期間 tick 會跳過，醒來後從下一輪恢復

### Delivery Plan

#### Work Session 1（約 4 小時）

- Phase 0 / 6 / 3 / 1 / 2
- 目標：skills render 修正、schema optional fields、session wrappers、auto routing 都可用
- 結束標準：turn-based 雙 session 流程已穩，無 scheduler 也能手動跑完一輪

#### Work Session 2（約 4 小時）

- Phase 4 / 5 / 5b
- 目標：experiment guard、agent-spec sync alias、event layer 上線
- 結束標準：once-only / event-relative 任務可 materialize 成 control-plane tasks

#### Work Session 3（約 10 小時）

- Phase 7a / 7b / 7c
- 目標：shared scheduler、brief system、grounding enforcement、observability、session cron 退役整理
- 結束標準：shared scheduler 可持續推進 Claude/Codex 工作，且不依賴舊 session cron

### Test Plan

- 結構測試
  - `.claude/skills/**/SKILL.md` 與 `.agents/skills/**/SKILL.md` 第一行都是 `---`
  - render outputs 不再出現小寫 `skill.md`
- Schema 相容測試
  - 舊 task / agent / execution JSON 沒有新欄位時仍能讀取
- Session 測試
  - `VOLPRED_ACTOR` 不符時 `session-bootstrap` fail fast
  - 同一 session 多個 mutating task 預設繼承同一 rollback point
- Routing 測試
  - `preferred_agent=auto` 依 `task_family` 正確分派
  - `brief_status` 未完成時不直接把模糊任務丟給 Codex
- Event 測試
  - one-shot 任務只 materialize 一次
  - relative-to-event 任務在 `not_before` 前不展開、超過 `deadline` 不再展開
  - `dedupe_key` 可防雙重建立
  - event ledger 會正確寫入與 GC
- Scheduler 測試
  - queue 空時不呼叫 LLM
  - `scheduler-preview` 能準確顯示本輪決策
  - cron wrapper 能正確載入 repo root、env、PATH
  - self-lock 能避免雙 tick 併發
- Brief 測試
  - 模板任務不需要跑 Claude 協調輪
  - 例外任務會得到 schema-valid 的 Claude JSON brief
  - `forbidden_large_files` 真的進入 executor prompt
  - `task.updated_at > brief_payload.generated_at` 時 brief 轉 stale
  - 模板 hash 改變時 brief 轉 stale
  - coordinator 最多重試 2 次，第 3 次轉 `needs_manual_review`
  - `prior_findings` 會自動帶入最近 3 筆 receipt 摘要
- Fail-Closed 測試
  - preflight fail 會轉 `blocked`
  - brief stale 會釋放 claim 並回 `queued`
  - 缺檔會轉 `failed`
  - blocked task 可由 `requeue-task` 回復
- Grounding 測試
  - repo root 錯誤、brief 缺失、必要檔缺失、agent-spec drift 時必須拒絕執行
  - brief 的 `required_files` 足以完成任務，且不要求 broad scan
- 回歸測試
  - `pytest`
  - `uv run volpred ops agent-spec check --target all`
  - `uv run volpred ops health`
  - `daily_update`
  - `recalc_metrics`
  - `release-pool-by-settings`
  - `question-ranking-workflow`
  - 前端 regression verifier

### Assumptions / Defaults

- 優先目標是**正確、穩定、token 效率**，不是最大吞吐量
- v1 架構採 **Claude 協調、Claude/Codex 執行**，不採雙主並行自治
- shared scheduler 層固定選 **macOS `crontab`**
- 目前系統是 **`cron-driven shared scheduler + slot-aware idle policy`**，不是純 idle-driven runtime
- Claude session cron 正式退役為非執行時鐘
- Brief 生成策略固定為 **模板優先，Claude 協調輪只處理例外**
- brief 模板固定放在 **`config/brief_templates/*.yaml`**
- Claude coordinator JSON 驗證固定採 **pydantic + fenced JSON 抽取 + 最多 2 次重試**
- brief 過期規則固定為 **`task.updated_at > brief_payload.generated_at` 或 template hash 改變**
- 所有新欄位 optional，讀取用 `.get(...)`，不做 migration
- `rollback_point_id` 預設由 session rollback 繼承，只有高價值或 destructive task 才另建
- `config/runtime_schedules.json` 繼續是唯一排程母本，並新增 `event_jobs`
- v1 **不做 task dependency graph**；事件鏈依賴先靠時間窗與 preconditions
- `claude -p` 是否自動載入 skills 會在 Phase 0 smoke 測試，但執行面不依賴它作為正確性前提
- 正式落檔目標是 `docs/project_improvement_status.md`
- 技術前提仍對齊最新官方能力：Claude 有 hooks / IDE integration；Codex CLI/IDE 目前無官方明確等價的 session cron，因此持續運作依賴 shared scheduler  
  https://code.claude.com/docs/en/vs-code  
  https://code.claude.com/docs/en/settings  
  https://code.claude.com/docs/en/sub-agents  
  https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan/  
  https://github.com/openai/codex


---

## 2026-04-18 Supervisor TODO — Paper 4 (vix-sufficiency) main_v2.tex patches

**Source**: Paper 4 reproducibility audit (task_a2ad5cff36e9, codex-worker) → `paper/vix-sufficiency/reproduce_report_2026-04-18.md`. Audit confidence: strong + codex_reviewed.

**規則**: 論文 .tex 寫作只能 supervisor 親自做 (CLAUDE.md §論文 .tex 寫作). 以下三條屬 supervisor 不可派工 backlog, 必須等 supervisor 有 narrative patch window 時執行 (非自動 tick 派工). 相關 knowledge: `PAPER4_AUDIT` item_id=2baed83f. Relevant experiences: E076, E077.

### TODO-P4-PATCH-1: K745 `41.8% QLIKE improvement` 方向反轉 (推薦 (a) 直接改 tex)
- **Location**: `paper/vix-sufficiency/main_v2.tex:98, 703, 813`
- **事實**: K745 `key_comparison.improvement_pct = -41.8` 意味 **daily HAR-ABS 勝 5-min HAR-RV 41.8%**, 不是反過來.
- **修法**: 改三處敘述為 "5-min HAR-RV underperforms best daily model by 41.8%" 或等義表達; 確保 L98 claim、L703、L813 一致.
- **相關檔**: `paper/vix-sufficiency/experiments/k745_pilot_har_rv_results.json` (n_oos=37)

### TODO-P4-PATCH-2: Table 6 era-cells 數量級錯誤 + "Harvey Pass? 0/5" 錯判 (推薦 (a))
- **Location**: `paper/vix-sufficiency/main_v2.tex:583-590`
- **Canonical source**: `paper/vix-sufficiency/experiments/k752_vix_sufficiency_eras_results.json -> part_d_competing_signals_by_era`
- **Divergent cells**: Overnight VIX Era3 (0.0004→0.0039), Era5 (0.0003→0.0032); VRP proxy Era3 (0.0008→0.0160); Vol mom 20/60 Era3 (0.0006→0.0216), Era5 (0.0002→0.0372).
- **Harvey Pass 正解**: **4 pass** (Era3: Overnight VIX t=-3.15, VRP t=-6.51, Vol mom t=+7.60; Era5: Vol mom t=+9.30), 不是 0/5.
- **修法**: 重寫 Table 6 + header claim + narrative 討論 era 5 VRP failure mechanism (現有文字仍保留但把 "0/5" 改 "4/10 pass Harvey t>3.0 threshold").

### TODO-P4-PATCH-3: Table 3 mixed-sample-window Sharpe ranking 方法論不公 (推薦 (b) 重寫)
- **Location**: `paper/vix-sufficiency/main_v2.tex:470-471, 493`
- **問題**: BH 50/50 Sharpe 0.947 來自 K507 (2005-01-03 – 2026-03-26, n=5339); 12/VIX Sharpe 0.870 來自 K731 不同 sample 窗. L493 ranking claim 混期間.
- **修法**: 選 canonical — 要嘛把 BH 50/50 改用 K731 同窗, 要嘛在 K507 同窗加跑 12/VIX (需新 code task), 要嘛 Table 3 加註 sample-window caveat 並撤回 ranking claim. 決策前不要改 tex.
- **實驗側配合**: 若走 K507 窗統一跑, 可能需派 code task 在 K731 script 加 K507 matching period.

### TODO-P4-PATCH-4: Table 10 SPY/GLD label 與 K738 cross-asset 輸出不符 (推薦 (c) 產 canonical 或 relabel)
- **Location**: `paper/vix-sufficiency/main_v2.tex:772-775`
- **問題**: Table 10 row label 寫 "SPY/GLD", 但 `3.49%/yr` / `2.12%/yr` 取自 K738 `cross_asset_summary.avg_return_drag_{12vix,ewma}` (跨所有 asset 平均); 而 K738 per-asset output 的 mdd_reduction_pp SPY=20.28, GLD=9.42 不是 paper 寫的 -8.2pp.
- **修法選項**: (i) 在 experiments/k738/ 開 subtask 算 SPY/GLD two-asset 專屬 insurance cost output + 存 JSON, 然後 supervisor 改 tex 用該 output; 或 (ii) supervisor 直接 relabel Table 10 為 "Cross-asset summary (6-asset)" 去掉 SPY/GLD 特稱.
- **建議先等 supervisor 決定走 (i) 或 (ii) 再派 code task**.

### 不派 worker 的理由
- P4-PATCH-1/2: 純論文文字修訂 → supervisor 專屬.
- P4-PATCH-3: 需 narrative 決策 (選哪個 canonical window) → supervisor 判斷.
- P4-PATCH-4: 需先走 narrative 決策 (relabel vs rerun) → supervisor 判斷後才能 spawn code task.
- **已派 worker 的部分**: `task_a683510edfc3` (codex-worker, code) — expose Table 2 behavioral sentiment (K732) + calendar anomaly OOS (K736) intermediate outputs, 讓 Table 2 也能 reproduce.

_Created 2026-04-18 06:09 UTC by claude-supervisor from audit task_a2ad5cff36e9._
