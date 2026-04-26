---
paths:
  - ".claude/skills/**"
  - "scripts/agent_prompts/**"
  - "AGENTS.md"
  - "CLAUDE.md"
---

# Agent Delegation + Model Selection（主線程派工節奏）

**核心原則**：主線程 context 有限且昂貴；能在主線程完成的小事就別派，會污染主線但可 self-contained 的 side task 才 fork subagent。`agent team` 只留給真的需要多 session 協作、互相討論或交叉挑戰假說的任務，不作日常預設。

**詳細 playbook**（10 類任務 × skill 對照表、6 要素 brief 範本、task decomposition 範例、work_log schema、decision tree、場景例子）：`.claude/skills/autonomous-research/references/delegation-playbook.md`（skill 觸發時才載）。

**快速路由入口**：先看 `docs/workflow-index.md` 決定 workflow / 執行模式 / 預設 model，再按需讀對應 skill。

## 模型選擇（合併自舊 model-selection.md）

| 任務類型 | 預設模型 / effort | 原因 |
|---|---|---|
| 研究實驗 / 方法論 / 高風險論文判斷 | `opus / high` | 精確性與專業性要求高 |
| 平台 ops / 發文 / paper-update 類程序型工作 | `sonnet / medium` | 結構化流程明確，不必全程重模型 |
| 驗證 / merge safety / publication scan 類短流程 | `sonnet / low` | 核心是精準比對與 checklist |
| lookup / classification / data-source 查詢 | `haiku / low` | 參考型工作，應優先便宜快速 |
| 需要讀很多背景但與主線脈絡可分離的任務 | `context: fork` + 對應 skill 預設 | 降低主線 context 汙染 |

**規則**：先尊重 skill frontmatter；只有在 skill 沒定義或任務明顯升級時才手動覆寫。高風險研究/統計/論文判斷不可為省 token 降到 Sonnet 以下。

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
