# `.claude/` Skill Registry

## Current architecture projection

`config/skill_registry.json` 是 skill metadata、角色、route、workflow usage、
supervisor dispatch expectation 與 architecture contract 的機械唯一來源；下表是人類
可讀 projection。Skill 的程序本體仍只存在
`.claude/skills/<name>/SKILL.md`。下方 2026-07-14 surface 稽核保留作歷史背景，不可用來
推導目前 skill inventory 或 runtime mode。

<!-- skill-registry:start -->
| Skill | Role | Domain | Route |
|---|---|---|---|
| `admin-ops` | orchestrator | ops | `ops-triage` |
| `agent-result-verification` | cross-cutting | research | `agent-result-check` |
| `anti-ai-style` | cross-cutting | publishing | support |
| `autonomous-research` | orchestrator | research | `research-design` |
| `citation-verifier` | cross-cutting | paper | `citation-check` |
| `data-collection-ops` | leaf | ops | support |
| `deploy-frontend` | leaf | frontend | `deploy-frontend` |
| `external-data-sources` | leaf | research | `data-source-lookup` |
| `fb-publishing` | leaf | publishing | support |
| `feed-publisher` | orchestrator | publishing | `feed-publish` |
| `finance-paper-quality` | cross-cutting | paper | `paper-quality` |
| `host-migration` | leaf | ops | `host-migration` |
| `incident-response` | cross-cutting | ops | `incident-response` |
| `journal-review` | leaf | paper | support |
| `latex-academic-reviewer` | leaf | paper | `latex-review` |
| `lazypack-infographic` | cross-cutting | publishing | support |
| `member-questions` | leaf | member | `member-qa` |
| `memory-health` | leaf | memory | `memory-health` |
| `owner-first` | cross-cutting | ops | support |
| `paper-review-cycle` | leaf | paper | `paper-review-round` |
| `paper-stage-classifier` | compatibility | paper | support |
| `paper-submission-pipeline` | orchestrator | paper | `paper-submission` |
| `paper-update` | leaf | paper | `paper-update` |
| `pdca-operations` | leaf | ops | support |
| `platform-ops-manager` | orchestrator | ops | `platform-ops` |
| `project-skill-governance` | orchestrator | governance | `skill-governance` |
| `promote-knowledge` | leaf | memory | support |
| `publication-candidates` | leaf | publishing | `publication-scan` |
| `reconcile-projections` | leaf | ops | `reconcile-projections` |
| `reproducibility-audit` | cross-cutting | research | `reproducibility-audit` |
| `research-topic-discovery` | leaf | research | support |
| `schedule-operations` | leaf | ops | `schedule-operations` |
| `strategy-lifecycle` | leaf | strategy | `strategy-lifecycle` |
| `task-pool-operator` | cross-cutting | ops | `task-pool` |
| `trending-repost` | leaf | publishing | `trending-repost` |
| `web-ui-ux-review` | leaf | frontend | `web-ui-review` |
| `worktree-merge-verification` | compatibility | research | support |
<!-- skill-registry:end -->

## Canonical source（2026-07-14 定案，唯一）

**`.claude/` 是唯一的 agent surface。沒有 render step，所以沒有 drift 可言。**

- Canonical：`.claude/skills/`、`.claude/rules/`、`.claude/agents/`、`CLAUDE.md`（Claude Code 直接讀）
- **已廢止**：`agent-specs/`（render 母本）、`.agents/skills/`（Codex render 複本）、
  `src/volpred/ops/agent_spec.py` + `ops agent-spec import|render|check|sync` CLI
- Enforcement owner（唯一，勿加第二層）：`tests/test_skill_surface_single_source.py`
  —— CI (`pytest.yml`) 與 pre-push hook 都會跑整個 `tests/`。第二個 skill surface 一旦
  復活（含 `.gitignore` 偷偷藏起來），測試直接 fail。

### 為什麼是「刪掉」而不是「補 render + 加 gate」

`agent-specs/` canonical 早在 2026-04-18（commit `e64a19072`，用戶確認不再用 Codex 終端機版）
就被刪掉，但 render 機械沒有一起退場，於是留下三個孤兒：

1. `ops agent-spec render` 是一把上膛的槍 —— 它會先 `rmtree('.claude/skills')` 再從一個
   **不存在**的 canonical 重建。`ops session-bootstrap` 也曾因為找不到 `agent-specs/guide.md`
   而炸掉（見 `paper/prg-periodic-garch/review_history/pre_submission_audit_v1/`）。
2. `.agents/skills/` 變成 gitignored 的 untracked 複本：**沒有任何 clone / worktree 有它**，
   也不會出現在任何 diff。三個月內 26 個共用 skill 有 18 個內容已與 `.claude/skills/` 分岔。
3. `.claude/**` 有 26 個檔案還掛著 `AUTO-GENERATED FROM agent-specs/. Edit canonical sources
   instead.` 的 header —— 叫下一個 agent 去改一個 2026-04-18 起就不存在的目錄。

關鍵事實（2026-07-14 實測，非推測）：**`.agents/skills/` 沒有任何 consumer**。
Codex CLI 0.144.1 只透過 plugin marketplace 發現 skill
（`<home>/.agents/plugins/marketplace.json` → `plugins/<name>/skills/`）；其 binary 對字串
`agents/skills` 命中 **0** 次，本 repo 也沒有 `.agents/plugins/marketplace.json`。
Claude Code 讀 `.claude/skills/`。`scripts/check_skills_complete.sh` 更早就把 SKILL.md 裡的
`.agents/` 路徑當成 legacy typo 自動翻譯成 `.claude/`。

一個零 consumer 的 surface 不需要 render pipeline，也不需要 drift gate —— 需要的是**消失**。
再幫它蓋一層 render + 一層 watchdog 就是 CLAUDE.md 明文禁止的疊床架屋。

### `.gitignore` 的處置

`.agents/skills/` 的 ignore rule **已移除**（不是改成 tracked）。理由：ignore 正是它能隱形
分岔三個月的原因 —— untracked ⇒ 不進 clone、不進 worktree、不進 diff。現在它既不 tracked
也不 ignored，任何人重新造出這個目錄都會被 `git status` 和上述測試同時抓到。

（`.agents/skills/` 內唯一 `.claude/skills/` 沒有的 entry 是 `source-command-deploy`，
內容是 `.claude/commands/deploy.md` 的 wrapper render —— 零獨有內容，刪除無損失。）

---

本表的目的不是重述每個 skill 全文，而是回答四件事：

1. 什麼任務應該觸發哪個 skill
2. 哪些事情不該交給它
3. 需要轉交給哪個 skill
4. 它承接 `CLAUDE.md` 的哪一段治理或操作規則

快速路由請先看 [`docs/workflow-index.md`](/Users/yhlai0911/volpred-research/docs/workflow-index.md)；本表保留較完整的 scope / handoff 對照。

## Top-Level Skills

| Skill | Trigger Phrases | 使用範圍 | 不該處理的內容 | Handoff | 對應 `CLAUDE.md` 段落 |
|------|------|------|------|------|------|
| `autonomous-research` | `開始研究`, `繼續研究`, `run experiment`, `跑實驗`, `研究波動率`, VT / vol forecast 相關請求 | 研究主流程、文獻搜尋、實驗設計、實驗執行、knowledge / experience 記錄、研究多元化 | 平台 ops、文章池節奏、feed 發文排程、paper review orchestration、citation-only 任務 | `feed-publisher`, `admin-ops`, `agent-result-verification`, `worktree-merge-verification` | `自主研究模式`, `實驗前必做`, `實驗完整流程`, `研究多元化`, `AI 協作模式`, `Agent Prompt 必備內容`, `排程核心原則` |
| `feed-publisher` | `發文`, `發佈`, `publish`, `post to feed`, `發佈到網站` | 文章內容規格、圖表要求、資料來源標注、主題查重、事件文章內容時效規則 | 文章池釋出、通知寄送、平台 cadence、研究設計本身、paper 寫作、選題本身 | `admin-ops`, `autonomous-research`, `publication-candidates` | `每日文章產出要求`, `署名與歸屬` |
| `publication-candidates` | `選題`, `寫什麼文章`, `publication candidates`, `文章候選`, `補草稿池`, `時事文章`, `事件文章` | 雙軌選題：研究驅動（K PASS 無文章覆蓋 + missing audience）+ 事件驅動（時事/macro 公佈/財報）候選擷取 | 實際寫作、平台 publish、研究實驗本身 | `feed-publisher`, `admin-ops` | `每日文章產出要求`（主題來源）, `署名與歸屬` |
| `admin-ops` | `admin`, `後台`, `平台操作`, `文章池`, `排程發布`, `ops`, `analytics`, `策略管理`, `問答管理` | 平台 surfaces、ops CLI、文章池、排程、通知、策略 metadata、問答營運、session cron / monitor 操作 | 核心研究判斷、論文寫作、citation 驗證 | `autonomous-research`, `member-questions`, `paper-update` | `思維模式：永遠修流程，不修資料`, `自動化：cron + Monitor`, `排程核心原則`, `Agent-first Ops Layer` |
| `member-questions` | `會員問題研究`, `member questions`, `提問排名`, `評估會員問題` | 會員問題評分、stable insertion rerank、atomic claim、candidate lifecycle、`question-answer` 綁定 | 核心研究分析本身、文章實際撰寫、平台 cadence | `autonomous-research`, `feed-publisher`, `admin-ops` | `研究主題來源`, `每日文章產出要求`（member QA 文章邏輯）, `快速指令` 的 question CLI |
| `finance-paper-quality` | `寫論文`, `revise paper`, `check paper quality`, `submission checklist` | 論文內容品質、claim-evidence matching、contribution hygiene、Harvey (2016) rigor | citation-only、LaTeX 結構審查、平台同步 | `citation-verifier`, `latex-academic-reviewer`, `paper-update` | `論文`, `研究誠實原則` 中的局限/不過度宣稱/統計嚴謹 |
| `latex-academic-reviewer` | `審查論文`, `LaTeX review`, `review paper`, `學術審查` | LaTeX 結構、論述邏輯、符號一致性、review report workflow | 純 citation 驗證、內容貢獻強度判斷、平台同步 | `citation-verifier`, `finance-paper-quality`, `paper-review-cycle` | `論文`, `Agent Prompt 必備內容` |
| `citation-verifier` | `verify citations`, `驗證引用`, `check references`, `檢查參考文獻` | citation bibliographic accuracy、DOI、內容是否忠於原文 | 一般 paper quality、LaTeX 結構審查、研究實驗 | `finance-paper-quality`, `latex-academic-reviewer`, `paper-review-cycle` | `論文`, `研究誠實原則` 的引用與可追溯要求 |
| `paper-stage-classifier` | `paper stage`, `論文 stage`, `ready_for_submission`, `submitted` | paper stage 判定、continuous review loop 入口條件 | 實際跑 review、實際修稿與同步 | `paper-review-cycle`, `paper-update` | `論文` |
| `paper-review-cycle` | `review cycle`, `跑論文審查`, `review_history` | review orchestration、雙 reviewer 併行、review_history 歸檔 | stage 判定、修稿、平台同步 | `paper-stage-classifier`, `paper-update` | `論文` |
| `paper-update` | `paper-update`, `更新論文`, `同步論文平台` | 修稿後的 compile、平台同步、版本化 | stage 判定、review orchestration、citation 審查 | `paper-review-cycle`, `paper-stage-classifier` | `論文` |
| `agent-result-verification` | agent 實驗結果返回、worktree/background 統計摘要 | 以 results JSON 驗證 agent 回報數字、檢查方向與號誌是否合理 | 研究設計、文章撰寫、平台發布 | `autonomous-research`, `worktree-merge-verification` | `實驗完整流程`, `Agent Prompt 必備內容` |
| `worktree-merge-verification` | worktree agent 返回、merge 後驗證 | merge、reflog 恢復、確認實驗檔案落地、主線程記錄前檢查 | 研究設計本身、平台操作 | `autonomous-research`, `agent-result-verification` | `研究誠實原則` 的 worktree 規範, `Agent Prompt 必備內容`, `排程核心原則` |
| `memory-health` | `memory health`, `記憶健康`, `knowledge 膨脹`, `thinking_journal` | knowledge / thinking / experiment memory 的健康檢查與維護 | 研究本身、一般發文、paper workflow | `admin-ops`, `autonomous-research` | `活文件原則`, `Error Log`, token 節約與記憶治理 |
| `external-data-sources` | `數據來源`, `data source`, `FRED`, `yfinance`, `TAIFEX`, `外部資料` | 外部資料來源用法、資料陷阱、選源導航 | 研究結論、平台 ops、文章內容規劃 | `taiwan-macro-data`, `autonomous-research` | `注意事項` 的外部數據來源段 |
| `taiwan-macro-data` | `台灣經濟數據`, `DGBAS`, `主計總處`, `Taiwan macro data` | DGBAS / NDC 台灣總體數據抓取與欄位說明 | 一般外部資料總覽、研究判斷、平台 ops | `external-data-sources`, `autonomous-research` | `注意事項` 的 DGBAS / 景氣指標段 |

## Support Bundle

| Bundle | 性質 | 用途 | 備註 |
|------|------|------|------|
| `academic-finance-reviewer/` | reference bundle | 提供 `finance-paper-quality` 使用的資產、模板與寫作品質參考 | 不是獨立 top-level skill，不單獨觸發 |

## Maintenance Rules

- 新增 skill 前，先確認不能用現有 skill + reference bundle 解決。
- 新增/刪除/改名/合併 top-level skill 時，必須同步更新本表；若影響 CLAUDE 導覽或流程入口，也要同步更新 `CLAUDE.md`。
- 若 skill 變更會影響固定路徑、hooks、session 啟動 prompt 或 cron 工作流，必須連帶檢查 `.claude/settings.json`、`scripts/session_startup.md`、`.claude/commands/` 與相關 references。
- 若內容是高頻重複流程但不值得獨立觸發，優先放到現有 skill 的 `references/`。
- 若內容是全域治理原則，優先留在 `CLAUDE.md`，不要硬拆成 skill。
- 若 skill 名稱改動會影響既有觸發，優先保留舊名並在內文修邊界。
