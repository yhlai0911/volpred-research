# Workflow Index

這份文件是 **token-aware 的快速路由索引**。先在這裡判斷 workflow 與 detail skill，
再按需讀對應 skill 全文；model／effort 由 runtime router 決定，不要一開始就把多份長
SOP 一次載入。

## Current skill workflows

下表由 `config/skill_registry.json` 投影，僅負責 workflow → skill 導航。Model／effort
一律在執行時交給 `config/models.json` 與 `scripts/model_router.py`，不得從本表或 skill
frontmatter 推導。Support／cross-cutting skill 由其 owner 載入，不另外製造平行 router。

<!-- skill-workflows:start -->
| Workflow ID | 使用時機 | Detail path |
|---|---|---|
| `ops-triage` | 後台 surface、平台操作與 ops 導航 | `.claude/skills/admin-ops/SKILL.md` |
| `agent-result-check` | agent／worktree 結果回傳後驗證 | `.claude/skills/agent-result-verification/SKILL.md` |
| `research-design` | 文獻、實驗、回測與研究續跑 | `.claude/skills/autonomous-research/SKILL.md` |
| `citation-check` | DOI、書目與 claim-level 引用驗證 | `.claude/skills/citation-verifier/SKILL.md` |
| `deploy-frontend` | active frontend 安全部署與 live readback | `.claude/skills/deploy-frontend/SKILL.md` |
| `data-source-lookup` | 外部資料源選擇與欄位陷阱 | `.claude/skills/external-data-sources/SKILL.md` |
| `feed-publish` | 撰寫或發布 reader-facing feed 文章 | `.claude/skills/feed-publisher/SKILL.md` |
| `paper-quality` | claim-evidence 與財金論文品質 | `.claude/skills/finance-paper-quality/SKILL.md` |
| `host-migration` | 使用者明確要求換機／standby／promotion | `.claude/skills/host-migration/SKILL.md` |
| `incident-response` | bug、alert、failed workflow 與結案 | `.claude/skills/incident-response/SKILL.md` |
| `latex-review` | read-only LaTeX 學術審查 | `.claude/skills/latex-academic-reviewer/SKILL.md` |
| `member-qa` | 會員問題評分、claim 與答覆生命週期 | `.claude/skills/member-questions/SKILL.md` |
| `memory-health` | 記憶索引與內容健康稽核 | `.claude/skills/memory-health/SKILL.md` |
| `paper-review-round` | 發起、收集與歸檔一輪 paper review | `.claude/skills/paper-review-cycle/SKILL.md` |
| `paper-submission` | 唯一 paper state 與 submission orchestration | `.claude/skills/paper-submission-pipeline/SKILL.md` |
| `paper-update` | 主線程修稿、編譯與平台同步 | `.claude/skills/paper-update/SKILL.md` |
| `platform-ops` | 一次性 platform triage／repair loop | `.claude/skills/platform-ops-manager/SKILL.md` |
| `skill-governance` | 新增、修改、合併、退役或稽核 skill | `.claude/skills/project-skill-governance/SKILL.md` |
| `publication-scan` | 研究／事件文章候選掃描 | `.claude/skills/publication-candidates/SKILL.md` |
| `reconcile-projections` | local canonical 對 remote/live drift | `.claude/skills/reconcile-projections/SKILL.md` |
| `reproducibility-audit` | experiment inventory、isolated rerun、identity drift | `.claude/skills/reproducibility-audit/SKILL.md` |
| `schedule-operations` | Operations Core schedule、owner、liveness | `.claude/skills/schedule-operations/SKILL.md` |
| `strategy-lifecycle` | 策略評估、registry、啟停與 rollout | `.claude/skills/strategy-lifecycle/SKILL.md` |
| `task-pool` | task create／claim／start／release／complete | `.claude/skills/task-pool-operator/SKILL.md` |
| `trending-repost` | 熱門主題的 VolPred 原創分析 | `.claude/skills/trending-repost/SKILL.md` |
| `web-ui-review` | active frontend UI/UX gate | `.claude/skills/web-ui-ux-review/SKILL.md` |
<!-- skill-workflows:end -->

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

## Historical workflow snapshot（superseded）

> **Owner directive 2026-07-05**：下表「預設 model」欄全部為 `opus`（4.8）；所有 subagent 一律用 opus，只有 `effort` 依難度變化。**effort 是 5 檔**（對齊 `claude --effort`）：`low < medium < high < xhigh < max`（`max` 是天花板；owner 更正——原本錯把 high 當頂，研究類升 `xhigh`、失敗升 `max`）。effort 現在真的透過 `--effort` 套用（worker.py / telegram_responder.sh；2026-07-05 前 inert）。canonical 來源 = `config/models.json` + `scripts/model_router.py`。`sonnet` / `haiku` 退出預設 rotation（仍是合法 alias，不自動路由）。

| Workflow ID | 何時使用 | 執行模式 | 預設 model / effort | Detail Path | Compact 提示 |
|---|---|---|---|---|---|
| `research-design` | 新實驗、回測、方法論判斷、研究方向續跑 | inline；side task 再 fork | `opus / xhigh` | `.claude/skills/autonomous-research/SKILL.md` | 新開實驗分支前若 `62%+` 先 compact |
| `code-implement` | 程式實作、bug fix、focused code change | inline；大搜尋或大 logs 再 fork | `opus / medium` | `AGENTS.md` | 單檔小改留主線；跨模組再拆 |
| `code-review` | review、風險盤點、回歸與缺測檢查 | inline | `opus / medium` | `AGENTS.md` | findings-first；不要把 review prompt 寫成長 SOP |
| `agent-result-check` | agent / worktree 回報結果後驗數字 | inline | `opus / low` | `.claude/skills/agent-result-verification/SKILL.md` | 保留在主線做，不外包 |
| `ops-triage` | admin、排程、release pool、策略 metadata、平台巡檢 | inline | `opus / medium` | `.claude/skills/admin-ops/SKILL.md` | log / docs 大搜尋可拆 fork |
| `schedule-governance` | schedule / cron / control-plane 治理與 canonical 對齊 | inline | `opus / medium` | `.claude/rules/control-plane.md` | 先改 canonical config / wrapper，再談 install |
| `feed-write` | 寫 reader-facing feed 文章 | inline | `opus / medium` | `.claude/skills/feed-publisher/SKILL.md` | 若研究 context 已重，先把查資料部分 fork |
| `publication-scan` | 選題、補草稿池、事件候選掃描 | forked subagent | `opus / low` | `.claude/skills/publication-candidates/SKILL.md` | `55%+` 就優先 fork |
| `member-qa` | 會員問題評分、rerank、candidate flow | forked subagent | `opus / low` | `.claude/skills/member-questions/SKILL.md` | 與主線研究無關時必隔離 |
| `memory-health` | knowledge / thinking / experiment memory 健檢與去重 | forked subagent | `opus / medium` | `.claude/skills/memory-health/SKILL.md` | 大檔檢查優先用乾淨 context |
| `citation-check` | citation bibliographic accuracy / DOI / 引文忠實度 | forked subagent | `opus / medium` | `.claude/skills/citation-verifier/SKILL.md` | 長文獻核對不要塞主線 |
| `paper-quality` | claim-evidence、contribution framing、Harvey 標準 | inline | `opus / xhigh` | `.claude/skills/finance-paper-quality/SKILL.md` | 高風險判斷，不為省 token 降級 |
| `latex-review` | LaTeX 結構、review report、長論文審查 | forked subagent | `opus / high` | `.claude/skills/latex-academic-reviewer/SKILL.md` | 長文件審查優先 fresh context |
| `paper-stage` | early/draft/review/ready/submitted 分類 | inline | `opus / low` | `.claude/skills/paper-stage-classifier/SKILL.md` | 快速分類，不必重模型 |
| `paper-review-round` | 發起一輪 review cycle、收集 reviewer 報告 | inline | `opus / medium` | `.claude/skills/paper-review-cycle/SKILL.md` | 真正 reviewer 可另外 fork |
| `paper-update` | review 後修訂、compile、平台同步 | inline | `opus / medium` | `.claude/skills/paper-update/SKILL.md` | 與 stage / review 分開處理 |
| `strategy-lifecycle` | 策略 registry、上架 gate、metadata / rollout 檢查 | inline | `opus / medium` | `docs/strategy-registry.md` | 牽涉 canonical metrics 時先驗來源 |
| `data-source-lookup` | 外部資料來源操作、注意事項、選源導航 | inline | `opus / low` | `.claude/skills/external-data-sources/SKILL.md` | 參考型工作，短查即走 |
| `tw-macro-lookup` | DGBAS / NDC 台灣總體資料抓取與欄位 | inline | `opus / low` | `.claude/skills/taiwan-macro-data/SKILL.md` | 不要把整份資料流程帶進主線 |
| `worktree-merge-check` | merge worktree 後驗證檔案與 reflog 恢復 | inline | `opus / low` | `.claude/skills/worktree-merge-verification/SKILL.md` | merge 完立即做，不延後 |

## 何時才用 `agent team`

符合以下任一條才考慮：

- 子任務之間需要直接討論、交叉審查或互相挑戰假說
- 單純多個獨立 subagent 不能完成任務
- 任務本質是多 session 協作，不只是平行切片

其餘情況一律先選 `單一主 session` 或 `forked subagent`。
