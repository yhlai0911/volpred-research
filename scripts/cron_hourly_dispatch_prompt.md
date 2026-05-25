Hourly dispatch trigger (LaunchAgent HH:07 CST, 24 slots/day). 規則 (token-conserving split architecture):

**完整完成原則（HARD RULE）**：本次 fire 派的 task 必須**徹底完成 task goal 才能停止** — 派 agent 後 wait 完成、驗證結果、寫 knowledge.json/work_log、commit。**禁止做一半丟給下一輪**。若任務太大 50min cap 內完不成，**必須 scope 切小**到能在 50min 內收尾的單位（不要 partial 提交）。Heavy compute（GARCH MLE / Bootstrap / 全期 backtest）強制走 `scripts/compute_queue.py enqueue` 給 async worker，不要塞進 hourly fire。Cap 50min（3000s）；hang detect 由 cron script 處理，不該變成「做一半算了」的藉口。

**Routing canonical**：`.claude/rules/task-routing.md` — 12 task types × Claude/Codex/並行/skill 對照表 + email_reply 特殊兩段流程。派工前 grep `task_type` 對應行。

**統一任務池 + claim 流程（HARD RULE，2026-05-25 用戶要求）**：
1. **第一動作必讀 `storage/ops/handoff_latest.md`**（由 com.volpred.handoff-regen LaunchAgent 每小時 :50 自動生成）— 取得任務池快照 / claim 狀態 / email_reply 待處理 / dashboard 訊號。
2. **派工前先 claim**：`uv run python scripts/task_pool_claim.py claim --id <id> --owner hourly-$(date +%H)` — 拒絕 `wrong_status` / `already_claimed` 時換另一 task，禁強推。
3. 開工標 in_progress：`uv run python scripts/task_pool_claim.py start --id <id>`
4. 完工標 succeeded/failed：`uv run python scripts/task_pool_claim.py complete --id <id> --status succeeded --result "<摘要>"`
5. 雙 session 撞題保護：claim 機制已 cross-session atomic（fcntl LOCK_EX on next_tasks.json）— 互動 session 與 hourly session claim 同 id 時後者得 `already_claimed`，自動換工。

PHASE 0 — Email reply 任務（**最高優先**，超越 compute queue followup）:

**Filter 已收緊（2026-05-25）**：只處理 from owner + Re: prefix + subject 含 `[VolPred` 三條件齊全的回信。其他不會入池。

**Reply 工作流**（用戶 2026-05-25 兩次硬性要求；最新版 = ack@receive + close@completion）：

**重要轉變（11:09 update）**：
- **ACK email 已由 gmail-poll 在收信當下立即寄出**（不再由 hourly-dispatch 寄 plan email）
- 你（hourly-dispatch）只需 **執行 + 寄 close email**
- 避免重複寄信（ack + plan + close = 3 封過 noisy）



**所有寄出的 email 一律 HTML 編排**（用戶 2026-05-25 硬性要求）：
- `send-alert --body "<markdown>"` 自動 markdown→HTML + `_email_shell` 包裝
- 長 email 用 `--body-md FILE` 從 `/tmp/*.md` 讀
- 必含：`# 標題` + `## 段落` + 表格 + **bold** + 程式碼框
- Level badge 自動加（info 藍 / warn 橘 / critical 紅）

### Phase 0.A — 先處理已 in_progress 但未 close 的 email_reply
```bash
uv run python scripts/task_pool_claim.py list --status in_progress --limit 50 2>/dev/null \
  | jq '[.tasks[] | select(.task_type=="email_reply")]'
```
對每一條（讀 `result` field 看上輪 plan + linked task ids）：
- jq query linked_task_ids 的當前 status
- 若**全部 succeeded** → 寄 **CLOSE email**（`Re: <原 subj>` body=「完成項目摘要 + commit hash + 對應 task id」）→ complete --status succeeded
- 若有 failed → 寄 **close-with-failure email** 說明哪步失敗+原因 → complete --status failed
- 若仍 in_progress → 跳過本輪不動，下次 tick 再 check（避免 nagging）

### Phase 0.B — 新 pending email_reply 入單
```bash
uv run python scripts/task_pool_claim.py list --status pending --limit 50 2>/dev/null \
  | jq '[.tasks[] | select(.task_type=="email_reply")][0]'
```
若有最舊一條 → 走 5 步：

1. **CLAIM**: `uv run python scripts/task_pool_claim.py claim --id <id> --owner hourly-$(date +%H)` → `start`
2. **ANALYZE**: 讀 description 內「用戶回信內容」+「原始助理寄出內容」→ 分類 (question / command / dispatch / observation / urgent)
3. **PLAN**: 寫 1-5 個 bullet 計畫 — 每 bullet 含「動作 / 預期產出 / ETA」。對需要 sub-task 的動作，下 `task_pool_claim.py claim` 建 linked sub-task（task_type 對應；description 含 parent_email_task_id 反向追蹤）
4. **(SKIP — ack 已由 gmail-poll 寄)** ❌ 不要再寄 plan email。用戶在收信當下已收到 ack（含 task_id / type / priority / ETA / 完成 email 承諾）— 你只負責執行 + close。
5. **記 plan 到 task.result** (jq edit next_tasks.json 補欄位)：
   ```bash
   jq --arg id <task_id> --arg plan '<plan text>' --argjson subs '["sub_id_1","sub_id_2"]' \
     '(.[] | select(.id==$id)) |= (.plan = $plan | .linked_task_ids = $subs | .needs_close_reply = true)' \
     storage/next_tasks.json > /tmp/nt && mv /tmp/nt storage/next_tasks.json
   ```
6. **EXECUTE**：當下 tick 能完成的立即做（小型 question 直接答完；指令直接 commit）；大型任務派 agent / 進 compute queue / 留 sub-task 給未來 tick 接。
7. **本 tick close 判定**：若所有 linked sub-tasks 都已 succeeded（或本就無 sub-task 因為 question 直接回答完）→ 寄 close email + complete --status succeeded。否則**留 in_progress**，下次 tick Phase 0.A 接手。

**重要**：plan email 是「**對用戶承諾**」，寄出後沒做完不算結案。stale cleanup 2h 會把卡住的 email_reply auto-release 給下一輪重做（但 plan email 已寄，用戶會看到 retry log），盡量在 2 tick 內收尾。

### Phase 0.C — 都沒事 → 進 PHASE A
若 0.A 全 close 完、0.B 無新單 → PHASE A。

PHASE A — 檢查 compute queue 有無 completed 待 followup:
1. 跑 `uv run python scripts/compute_queue.py list --completed-pending-followup --json`
2. 若有 entries → 優先處理: 對最舊一條讀 result_artifact 路徑 + agent claude_followup.brief 文字，派 Claude interpretation agent 解讀（~25K tokens, light），不再做 compute。派完跑 `uv run python scripts/compute_queue.py mark-followup-dispatched --id <id> --next-task-id <task_id>` 防重派。本小時派工結束。
3. 若無待 followup → 進 PHASE B。

PHASE B — 派新工:

1. 跑 `uv run python scripts/continue_task_dispatch.py --report` 看 dispatch state + agentable candidates。
2. 多樣性檢查: `jq '[.[-5:] | .[] | .task_type]' storage/work_log.json` — 從 11 type 池選不在 last-3 的 type（experiment / paper_decision / paper_body / paper_review / event_article / daily_article / member_qa / strategy_lifecycle / platform_ops / governance / **trending_repost**）。

   **trending_repost daily cap = 2/day**（per `.claude/skills/trending-repost/SKILL.md`）：
   ```bash
   jq --arg today "$(date '+%Y-%m-%d')" \
      '[.[] | select(.task_type == "trending_repost" and (.timestamp // "")[0:10] == $today)] | length' \
      storage/work_log.json
   ```
   結果 ≥ 2 → 禁挑 trending_repost，rotate 其他 type。
3. 優先序（CLAUDE.md 關 2 diversity 為硬規）:
   a. 若 last-3 work_log 已有 ≥2 paper_review/paper_body/paper_decision → 禁挑 paper_*，必 rotate 到其他 type。違反 = 整盤 diversity 崩。
   b. 否則考量 paper R1 backlog (Paper 2 還剩 3 SEVERE) + M3 monetization weight。
   c. 每天至少 1 次 experiment 類（生新 research direction），避免長期 maintenance 化 + 30 天無新發現累積。新 experiment 必 grounded in research_program.md Open Question OR 文獻 last 7 天 + monetization angle。
   d. 從 10 type 池選不在 last-3 的 type — 嚴格 enforce，不再 audit 鎖死 paper R1。
4. Override: reactive K-experiment autogen brief（K1310-K1330 GARCH-Neural / HAR-GNN / Transformer / KAN / Conformal 等 ML novel-method NULL 4 連後 diversity decline）→ skip 改派非 ML K 或 paper_review。
4.5. **模型分流（2026-05-25 強制）**：派 subagent 前 query router 取 task-type-specific model：
   ```bash
   MODEL_INFO=$(uv run python scripts/model_router.py --task-type <task_type>)
   MODEL=$(echo "$MODEL_INFO" | jq -r .agent_short)  # opus / sonnet / haiku
   EFFORT=$(echo "$MODEL_INFO" | jq -r .effort)      # high / medium / low
   ```
   分流原則（per `.claude/rules/agent-delegation.md` 模型選擇表）：
   - **experiment / paper_decision / paper_body / strategy_lifecycle** → `opus`（研究與 narrative 必 opus）
   - **paper_review / event_article / daily_article / trending_repost / member_qa / email_reply** → `sonnet medium`（程序型）
   - **platform_ops / governance** → `sonnet low`（短流程 + checklist）
   - **lookup / verify / classification** → `haiku low`（便宜快速）
   - 派 Agent tool 時 `model: "<opus|sonnet|haiku>"`；派 `claude -p` 時 `--model <cli_flag>`（cli_flag 從 router output 取）
   - Brief 必含一行 `**Model**: <picked> (per task_type routing)`，便於 audit
   - 違反（例：experiment 派 sonnet）= 違反 CLAUDE.md 紀律，下次 boss_report 會抓

5. 分流決策（token 節省）:
   - heavy compute (GARCH MLE / Bootstrap / data fetch / 全期 backtest / pooled-MLE multistart) → 改 `uv run python scripts/compute_queue.py enqueue --script <path> --title <T> --result-artifact <path> --followup-brief 'brief' --followup-task-type paper_review --timeout 3600`。Compute worker cron */15 min 接手；下次 hourly 自動派 interpretation agent（省 60-70% tokens）。注意: 腳本必須完整已寫才能 enqueue。
   - decision / writing / narrative → 派 Claude agent 正常流程（worktree for experiments；main repo for articles/paper body）。
6. Brief 含 task title/description + skill 規範 + lookahead + Codex 審核要求 + Mission sanity check。

   **Reader-facing 寫文章類任務硬規則**（feed-publisher / trending-repost / daily_article / event_article / member_qa 答覆 / FB hook，per memory `feedback_reader_facing_3canon` + `feedback_use_anti_ai_style`）：

   (a) Brief **必含 3 canonical paths**，agent 開工前先讀完：
       - `.claude/skills/trending-repost/SKILL.md`（即便非 trending_repost type，dual-publish + style 規範通用）
       - `.claude/skills/anti-ai-style/SKILL.md`
       - `.claude/rules/publishing.md`
   (b) **Evidence package 先於 prose** — 任何句子之前先組好：≥3 個可驗證數字（primary source）+ ≥1 表 + ≥1 圖 + ≥1 層量化分析（descriptive stats / before-after / cross-section / rolling / event-window / vol change）+ 最好有統計檢定或比較框架。不滿足 → 換題目或換 task type，禁強推。
   (c) **trending_repost 特別**：正式 task type 非摘要 / 翻譯；風格可參 havingchien Substack/commentary tone 但不引用不貼近改寫；先選題掃描 + 30 日查重 + VolPred angle 確認；**VolPred 直接 published 不進 draft pool**；daily cap = 2/day；雙發佈 feed + Ivan Lai FB。

   (c2) **event_article 特別（2026-05-25 新增 FB 強制）**：CPI/NFP/FOMC/財報/地緣政治 → **VolPred 直接 published 不進 draft pool** + **FB 雙發佈強制**（與 trending_repost 共用 `.claude/skills/trending-repost/references/fb-ivanlai-tone.md` SOP；但**不算入** trending daily cap=2/day）。語氣可更貼「即時市場觀察」非「專欄式 commentary」。FB 失敗不阻塞 feed publish 但**必留 retry log + work_log entry `fb_post_failed`**。

   ⚠️ **K1401 retroactive**：2026-05-25 11:16 publish 的 K1401 GDP event article (`mile_daaff779`) 因規則 2026-05-25 11:23 才更新，**未跑 FB 步驟**。下次有 idle slot 時補 FB 發佈一次（manual catch-up；之後新 event_article 自動走新規則）。
   (d) **寫前**讀 anti-ai-style/references/prompt-templates.md，5 原則套 prompt header（年齡降級 / 長文裁切 / 資訊密度 / 負向約束 / 蘇格拉底對槓）。
   (e) **寫後**跑 anti-ai-style/references/editor-sop.md 3 階段 9-checklist；任一 fail 不 publish。**只要還有 AI 味、翻譯腔、模板腔、空泛評論 → 不得發布**（無 partial pass；3 輪改寫仍 fail → 該主題 abandon）。

   (e2) **PROGRAMMATIC GATE（2026-05-25 強制；HARD RULE）**：FB / feed 任何讀者向文字 publish 前 **必跑** `uv run python scripts/anti_ai_gate.py --file /tmp/<draft>.md`（FB mode default ON），exit code 0 才能 publish。MUST level hit 任一條 = 整篇 reject 改寫到 PASS。WARN ≥3 累計也 reject。Gate fail 不准用 `--force` 等繞過 — 改文字到 PASS 才寄。此 gate 補 9-checklist 自律不足 — 2026-05-25 K1401 FB catch-up 第一版未走 gate 就 publish，用戶兩輪 feedback 才修正（套路 hook + AI bridge phrase + 段落過長）。
   (f) **3-model gate** 之 Gemini 一審 prompt 加問「是否仍有 AI 味？指出最像 AI 的 3 句並建議改寫」。
   (g) **FB 貼文規則**（trending_repost / 同步發 Ivan Lai FB，完整 SOP `.claude/skills/trending-repost/references/fb-ivanlai-tone.md`）：FB 文案是改寫版（不貼 VolPred 內文，重組 200-400 字）；主貼文**不放連結**；VolPred 連結放**第一則留言**；Ivan Lai 口吻（先個人觀察 → 短句短段 → 留白 → 不講滿）；額外禁「綜上所述/值得關注/在 AI 時代/根據資料顯示」；claude-in-chrome 輸入中文**整段貼上**不要逐字 type，貼後 screenshot 檢查再送出；失敗 retry max 3。
7. 派完 end summary 格式（per memory feedback_task_end_summary_format）: 結束時間 / 總時間 / 本次 token / 完成項目 / 本週 Max 20x quota % (`uv run python scripts/weekly_quota_estimate.py`) / 下次任務時間。
8. 若 last-3 涵蓋所有 candidates 的 type → 派沒做過的 type，必要時主動生 brief / 文章 / compute job。沒事做永不可接受。
9. 嚴禁: force push, --no-verify, 寫 knowledge.json from agent (K1259), 假數字。研究誠實 > 一切。
10. **完整完成 gate**：本 fire 結束前驗證 — (a) agent 跑完 + 結果 verify、(b) knowledge.json 或 work_log 已寫、(c) commit 已 push 主線 OR worktree merged、(d) 派出的 task next_tasks status 已標 succeeded/failed（不留 in_progress 殘留）。任一未完成 = 本 fire 未真正結束，繼續做完。下一輪 4h 後才開始下個新任務。
