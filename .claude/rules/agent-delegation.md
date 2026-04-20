---
paths:
  - ".claude/skills/**"
  - "scripts/agent_prompts/**"
  - "AGENTS.md"
  - "CLAUDE.md"
---

# Agent Delegation + Model Selection（主線程派工節奏）

**核心原則**：主線程 context 有限且昂貴；sub agent 的 context 用完即丟。把會燒 context 的工作外包給 agent team，主線程只保留 **規劃 / synthesis / 驗證 / 決策 / 記錄**。這是 session-level token 節約最大槓桿。

**詳細 playbook**（10 類任務 × skill 對照表、6 要素 brief 範本、task decomposition 範例、work_log schema、decision tree、場景例子）：`.claude/skills/autonomous-research/references/delegation-playbook.md`（skill 觸發時才載）。

## 模型選擇（合併自舊 model-selection.md）

| 任務類型 | 模型 | 原因 |
|---|---|---|
| 研究實驗（GARCH、統計檢定、策略回測） | `opus` | 精確性與專業性要求高 |
| 程式開發（前端、後端、bug 修復） | `opus` | 程式碼正確性關鍵 |
| 統計分析（DM、bootstrap、cross-OOS） | `opus` | 數學嚴謹性不可妥協 |
| 論文寫作 / 審查 | `opus` | 學術品質要求 |
| 知識合成（meta-analysis、投資指南） | `opus` | 需要深度推理 |
| 簡單搜尋（grep、檔案查找） | `Explore` subagent | 快速唯讀 |
| 簡單文章撰寫（feed 文章） | `sonnet` 可接受 | 創意寫作彈性較大 |
| 規劃與架構 | `Plan` subagent | 結構化思考 |

**規則**：不確定時預設 `opus`；研究/統計/程式/論文精確性工作絕不降級 sonnet 省 token。簡單唯讀探索才用 Explore / Plan subagent。

## Delegation Threshold（何時派 vs 自己做）

**派 agent**：多步流程（≥3 步）、需 WebSearch / 外部資料、實驗腳本 + 跑、寫文章（需 chart + content）、批次改 >5 檔、可 brief 化獨立任務、反覆試錯 debug。

**主線程自己做**：單一 grep/jq/ls、簡單 Edit（單檔、明確 old_string）、驗證 agent 回報、agent 結果 synthesis、寫 knowledge/experience/log、判斷要不要派下一個 agent。

**判斷法則**：
- 「這件事如果我做，會燒 3000+ tokens 嗎？」→ 會 → 派 agent
- 「這件事需要我的對話記憶才能做嗎？」→ 會 → 自己做
- 「成功標準能一句話寫清楚嗎？」→ 能 → 派 agent 最快

## 派工前 Checklist 三關（硬性，每次都做）

**關 1 — Mission sanity**：這輪服務 CLAUDE.md L5-24 哪條 Mission？全在 ops（補池/排程/governance）立刻警訊 — 研究與論文永遠不輸給 ops。

**關 2 — 多樣化檢查**：`jq '[.[-5:] | .[] | .task_type]' storage/work_log.json`；≥3 筆同 type 必換 type。

**關 3 — 不問選擇題**：「要不要 X？」違規。要做就做，不做就不做；疑問時不問，直接決定，決定錯了事後修。

**允許問用戶的例外**：破壞性風險、policy 決策（投稿/研究 pivot）、邏輯推不出來的歧義。

## Codex subagent 併發限制（Shared runtime）

**硬規則**：一 Claude session 一次只能派 1 個 `codex:codex-rescue` / Codex subagent。第二個會搶 runtime → stale claim（started_at=null）。派前檢 `storage/ops/tasks/*.json` 有無 `claimed_by=codex` 且 `started_at=null` >5min 的 stale；有則先 `finish-task --status failed` 清，或 bypass 改派 `general-purpose` Agent tool。詳細見 delegation-playbook.md。

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
