---
paths:
  - ".claude/skills/**"
  - "scripts/agent_prompts/**"
  - "config/agent_prompts/**"
  - "config/brief_templates/**"
  - "config/models.json"
  - "scripts/model_router.py"
  - "docs/workflow-index.md"
  - "storage/next_tasks.json"
  - "AGENTS.md"
  - "CLAUDE.md"
---

# Agent Delegation + Model Selection（主線程派工節奏）

**核心原則**：主線程 context 有限且昂貴；能在主線程完成的小事就別派，會污染主線但可 self-contained 的 side task 才 fork subagent。`agent team` 只留給真的需要多 session 協作、互相討論或交叉挑戰假說的任務，不作日常預設。

**詳細 playbook**（workflow × skill 對照、6 要素 brief 範本、task decomposition 範例、work_log schema、decision tree、場景例子）：`.claude/skills/autonomous-research/references/delegation-playbook.md`（skill 觸發時才載）。task type 的即時 capability / topology 仍以 `.claude/rules/task-routing.md` + `scripts/model_router.py` 為準。

**快速路由入口**：先看 `docs/workflow-index.md` 決定 workflow / 執行模式 / 預設 model，再按需讀對應 skill。

## 模型選擇（合併自舊 model-selection.md）

**Single source of truth = `config/models.json`**（roster、版本、subagent policy、drift-check 全在那）。下表是摘要，派工前以 config 為準。

**Owner directive 2026-07-05（取代 2026-07-01 二選一）**：**主線 = `opus`（固定）；所有 subagent 也一律用 `opus`（4.8）**。不再有 sonnet↔opus 選擇——每個 subagent 都是 opus，只有 `effort` 依任務難度變化。**effort 是 5 檔**（對齊 `claude --effort` 旗標）：`low < medium < high < xhigh < max`（`max` 是天花板；owner 2026-07-05 更正——原本錯把 high 當頂）。opus/low 跑 checklist 仍比 opus/max 便宜。**`sonnet` / `haiku` 退出預設 rotation（仍是合法 alias，不自動路由）；`fable` unavailable，重開再評估。**

**effort 現在真的生效（wired 2026-07-05）**：透過 spawn `claude -p` 的 `--effort` 旗標套用（`dispatch_supervisor/worker.py` `DISPATCH_EFFORT` 預設 high + `telegram_responder.sh` 預設 high + legacy cron）。**2026-07-05 前 effort 只被 model_router 算出來、寫進 brief 當參考文字，從沒傳給任何 dispatch（inert）。** 缺口：Agent/Task tool 無 effort 旋鈕 → 研究 subagent 若要真吃到 xhigh/max，orchestrator 需改用 `claude -p --effort` spawn。

| 對象 / 難度 | 模型 | effort | 原因 |
|---|---|---|---|
| 主線程（互動 session） | `opus`（固定） | — | owner directive；不能中途 hot-swap |
| subagent — **研究/高風險**：實驗設計/方法論/高風險論文判斷/策略 gate | `opus` | **xhigh**（失敗升 max） | 研究品質為先、成本不設限 |
| subagent — **paper body**：.tex rewrite（主線程才能跑） | `opus` | high | 論文寫作高風險 |
| subagent — **寫作**：文章/digest/paper_review/member_qa/email_reply | `opus` | medium | 品質優先（2026-07-05 起全 opus） |
| subagent — **ops/驗證/governance/lookup**：平台 ops/瀏覽器自動化/merge/scan/大搜尋 | `opus` | low | 流程明確、effort 低即可，但模型仍 opus |
| `sonnet` / `haiku` | 退出預設 rotation | — | owner 2026-07-05 指定全 subagent 用 opus |
| `fable` | **unavailable** — 開放後再評估為長時程自主頂層 | — | Desktop 選單 Currently unavailable |

**規則**：先尊重 skill frontmatter；只有 skill 沒定義或任務明顯升級時才手動覆寫 effort（模型固定 opus）。**程序型 side task（瀏覽器自動化、scan、大搜尋）仍要 fork subagent（不 inline 在主線）→ 現在 fork `opus / low`，不再是 sonnet**（2026-07-01 教訓：FB 發文整段 inline 在主線）。

**Drift-check（roster 變動偵測）**：**可用性真相來源 = Claude Desktop 右下角模型選單**（老闆可截圖，含展開「More models ›」）。Agent/Workflow tool 的 `model` enum 只列「可派別名」，**不反映當下可用性**（如 fable 是合法別名卻 Currently unavailable）。主線程 computer-use 是 Chrome-scoped，**碰不到 native desktop UI → 此 reconcile 需老闆截圖或未來 OS-level computer-use**。無 cron 自動偵測（無 `ANTHROPIC_API_KEY`）；`scripts/check_model_roster.py` 在 `config/models.json` 過期時提醒。**新 model 先查定位再指派 tier（不猜）；available=false 的 model 一律走 fallback。**

## Delegation Threshold（何時派 vs 自己做）

**派 subagent**：大量搜尋 / log / docs、需 WebSearch / 外部資料、實驗腳本 + 跑、寫文章（需 chart + content）、批次改 >5 檔、可 brief 化獨立任務、反覆試錯 debug。

**派 agent team**：只有子任務彼此需要互相溝通、交叉審查、共同形成共識，且單純多個獨立 subagent 不夠時才用。

**主線程自己做**：單一 grep/jq/ls、簡單 Edit（單檔、明確 old_string）、驗證 agent 回報、agent 結果 synthesis、寫 knowledge/experience/log、判斷要不要派下一個 agent。

**判斷法則**：
- 「這件事會污染主線 context，但結果可以摘要回來嗎？」→ 會 → 派 subagent
- 「這件事需要我的對話記憶才能做嗎？」→ 會 → 自己做
- 「成功標準能一句話寫清楚，而且子任務彼此不必互聊嗎？」→ 能 → 不必開 team，subagent 即可

## 派工前 Checklist 三關（硬性，每次都做）

**關 1 — Mission sanity**：這輪服務 CLAUDE.md L5-24 哪條 Mission？全在 ops（補池/排程/governance）立刻警訊 — 研究與論文永遠不輸給 ops。

**關 2 — 多樣化檢查**：`jq '[.[-5:] | .[] | .task_type]' storage/work_log.json`；≥3 筆同 type 必換 type。

**關 3 — 不問選擇題**：「要不要 X？」違規。要做就做，不做就不做；疑問時不問，直接決定，決定錯了事後修。

**允許問用戶的例外**：破壞性風險、policy 決策（投稿/研究 pivot）、邏輯推不出來的歧義。

## Codex subagent 併發限制（Shared runtime）

**本專案預設**：`codex:codex-rescue` 預設一次派 1 個。若任務完全獨立、寫入範圍不重疊、且不共享同一續跑 thread，可放寬到同一 session **最多 3 個**。**不要設成不限制**。

補充：
- Codex plugin 有 background job queue，工具層不是絕對單工；但續跑 thread、claim state、shared 檔案寫入仍可能互相干擾。
- 只要看到 `started_at=null`、stale claim、或兩個 Codex 任務開始碰同一檔，就立刻降回 serialize。
- 派前檢 `storage/ops/tasks/*.json` 有無 `claimed_by=codex` 且 `started_at=null` >5min 的 stale；有則先 `finish-task --status failed` 清，或 bypass 改派 `general-purpose` Agent tool。

## Sub Agent self-contained brief 必備 6 要素

1. **任務（WHAT）**：產出物、資料、模型、指標
2. **動機（WHY）**：相關 K、正負面意義
3. **Context 指引**：明指要讀哪些檔（`experiments/kXXX/README.md`、`docs/error_log.md`、相關 skill）
4. **規範引用 + skill 路徑**：一律指 `.claude/skills/<name>/SKILL.md` + 對應 `references/*.md`（Codex subagent 透過 `codex:codex-rescue` 派工時 prompt 裡也寫這個路徑，`codex-companion` runtime 能讀專案內任何檔）
5. **成功標準**：可驗證 checklist（檔案/數值/test/CLI return）
6. **Scope 限制**：不可擴散/不可改/遇錯如何回報

範本：`.claude/skills/autonomous-research/references/agent-brief-template.md`。

## Anti-patterns（禁止）

- ✗ 自己扛該派的大任務（audit 全 feed、批次 cleanup 多 draft、查文獻寫實驗設計）— 主線程 token 速耗盡
- ✗ 派 agent 但 prompt 太短 → agent 瞎猜 → 結果不可用，還要花 token 重派
- ✗ 派 agent 做主線程才能做的事（決定研究方向、判斷文章該不該發、整合多 agent 結論）— 需跨對話記憶
- ✗ 派完不驗證 — 必跑 `agent-result-verification` skill，不照抄數字
- ✗ 收大 task 直接派 1 agent 扛全部（子步驟耦合，跑不動全掛）→ 必先規劃子任務結構
- ✗ 低成本 1-行 edit 也派 agent → 主線程 setup 成本反而更高
