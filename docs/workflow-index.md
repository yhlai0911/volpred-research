# Workflow Index

這份文件是 **token-aware 的快速路由索引**。先在這裡判斷 workflow / 執行模式 / 預設 model，再按需讀對應 skill 全文，不要一開始就把多份長 SOP 一次載入。

## 使用順序

1. 先辨識任務屬於哪個 workflow。
2. 依「執行模式」決定留主線、fork subagent，或極少數情況才開 `agent team`。
3. 再讀對應 `detail path`。
4. Context 邊界以 `config/token_policy.json` 為準；若 `context_window.used_percentage >= compact_min_pct`，先 `/compact` 再開新 workflow。
5. 若要跨 workflow 開工，優先先跑 `/task-start <workflow-id 或任務描述>` 做 boundary gate。

## Context 邊界

Canonical source：`config/token_policy.json`

- `< normal_max_pct`：正常工作
- `normal_max_pct - compact_min_pct`：避免開新 noisy side task；優先 fork 或先收斂
- `compact_min_pct+`：優先 `/compact`
- `clear_min_pct+`：除非收尾，停止開新主題；跨 workflow 時優先新 session / `/clear`

## 開工前 Gate

- 一般跨 workflow 開工前，先用 `/task-start <workflow-id 或任務描述>`。
- `research`、`publish`、`deploy` 這類可能載入較長 skill / SOP 的 command，先做 boundary gate，再決定是否繼續。
- 原則：先判斷「要不要在這個 session 繼續」，再決定「要讀哪份 skill」。

## Workflow 路由

| Workflow ID | 何時使用 | 執行模式 | 預設 model / effort | Detail Path | Compact 提示 |
|---|---|---|---|---|---|
| `research-design` | 新實驗、回測、方法論判斷、研究方向續跑 | inline；side task 再 fork | `opus / high` | `.claude/skills/autonomous-research/SKILL.md` | 新開實驗分支前若 `62%+` 先 compact |
| `code-implement` | 程式實作、bug fix、focused code change | inline；大搜尋或大 logs 再 fork | `sonnet / medium` | `AGENTS.md` | 單檔小改留主線；跨模組再拆 |
| `code-review` | review、風險盤點、回歸與缺測檢查 | inline | `sonnet / medium` | `AGENTS.md` | findings-first；不要把 review prompt 寫成長 SOP |
| `agent-result-check` | agent / worktree 回報結果後驗數字 | inline | `sonnet / low` | `.claude/skills/agent-result-verification/SKILL.md` | 保留在主線做，不外包 |
| `ops-triage` | admin、排程、release pool、策略 metadata、平台巡檢 | inline | `sonnet / medium` | `.claude/skills/admin-ops/SKILL.md` | log / docs 大搜尋可拆 fork |
| `schedule-governance` | schedule / cron / control-plane 治理與 canonical 對齊 | inline | `sonnet / medium` | `.claude/rules/control-plane.md` | 先改 canonical config / wrapper，再談 install |
| `feed-write` | 寫 reader-facing feed 文章 | inline | `sonnet / medium` | `.claude/skills/feed-publisher/SKILL.md` | 若研究 context 已重，先把查資料部分 fork |
| `publication-scan` | 選題、補草稿池、事件候選掃描 | forked subagent | `sonnet / low` | `.claude/skills/publication-candidates/SKILL.md` | `55%+` 就優先 fork |
| `member-qa` | 會員問題評分、rerank、candidate flow | forked subagent | `sonnet / low` | `.claude/skills/member-questions/SKILL.md` | 與主線研究無關時必隔離 |
| `memory-health` | knowledge / thinking / experiment memory 健檢與去重 | forked subagent | `sonnet / medium` | `.claude/skills/memory-health/SKILL.md` | 大檔檢查優先用乾淨 context |
| `citation-check` | citation bibliographic accuracy / DOI / 引文忠實度 | forked subagent | `sonnet / medium` | `.claude/skills/citation-verifier/SKILL.md` | 長文獻核對不要塞主線 |
| `paper-quality` | claim-evidence、contribution framing、Harvey 標準 | inline | `opus / high` | `.claude/skills/finance-paper-quality/SKILL.md` | 高風險判斷，不為省 token 降級 |
| `latex-review` | LaTeX 結構、review report、長論文審查 | forked subagent | `opus / high` | `.claude/skills/latex-academic-reviewer/SKILL.md` | 長文件審查優先 fresh context |
| `paper-stage` | early/draft/review/ready/submitted 分類 | inline | `haiku / low` | `.claude/skills/paper-stage-classifier/SKILL.md` | 快速分類，不必重模型 |
| `paper-review-round` | 發起一輪 review cycle、收集 reviewer 報告 | inline | `sonnet / medium` | `.claude/skills/paper-review-cycle/SKILL.md` | 真正 reviewer 可另外 fork |
| `paper-update` | review 後修訂、compile、平台同步 | inline | `sonnet / medium` | `.claude/skills/paper-update/SKILL.md` | 與 stage / review 分開處理 |
| `strategy-lifecycle` | 策略 registry、上架 gate、metadata / rollout 檢查 | inline | `sonnet / medium` | `docs/strategy-registry.md` | 牽涉 canonical metrics 時先驗來源 |
| `data-source-lookup` | 外部資料來源操作、注意事項、選源導航 | inline | `haiku / low` | `.claude/skills/external-data-sources/SKILL.md` | 參考型工作，短查即走 |
| `tw-macro-lookup` | DGBAS / NDC 台灣總體資料抓取與欄位 | inline | `haiku / low` | `.claude/skills/taiwan-macro-data/SKILL.md` | 不要把整份資料流程帶進主線 |
| `worktree-merge-check` | merge worktree 後驗證檔案與 reflog 恢復 | inline | `sonnet / low` | `.claude/skills/worktree-merge-verification/SKILL.md` | merge 完立即做，不延後 |

## 何時才用 `agent team`

符合以下任一條才考慮：

- 子任務之間需要直接討論、交叉審查或互相挑戰假說
- 單純多個獨立 subagent 不能完成任務
- 任務本質是多 session 協作，不只是平行切片

其餘情況一律先選 `單一主 session` 或 `forked subagent`。
