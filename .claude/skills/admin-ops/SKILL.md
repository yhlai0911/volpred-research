---
name: admin-ops
description: >
  Use this skill when the task is about platform operations rather than core research:
  admin pages, content publishing workflows, article pool / scheduling, strategy management,
  question ranking and candidate handling, paper metadata / PDF delivery, admin users/roles,
  ops jobs, site health, or analytics/reader feedback. Trigger phrases: '後台', '管理區', '平台操作',
  'admin', '內容管理', '策略管理', '問答管理', 'ops', 'analytics', '會員中心',
  '文章池', '排程發布', '節奏發布', '寄信通知', '每日摘要', '管理通知', '論文管理',
  'paper-upsert', 'paper-upload-pdf', 'paper-migrate-storage'.
  Do not use for core experiments, paper writing, or deep research analysis unless the task
  clearly crosses into platform execution.
model: sonnet
effort: medium
user-invocable: true
---

# Admin Ops

Use this skill for **platform-layer work**. Treat it as the operating manual for:

- `/admin/*`
- `/api/admin/*`
- `uv run python -m volpred.cli ops ...`

## Scope Boundary

Use this skill when the job is about：

- 平台 surfaces 與 ops CLI
- 文章池、排程、節奏釋出、通知
- 策略 metadata / 問答營運 / paper metadata
- session cron、monitor、platform-cycle 類型工作流

Do **not** use this skill for：

- 核心研究設計與實驗判斷 → `autonomous-research`
- 文章內容撰寫 → `feed-publisher`
- 論文內容品質或 citation 驗證 → `finance-paper-quality` / `citation-verifier`

Do **not** use this skill as the main research workflow. When the task is primarily about:

- model experiments
- volatility forecasting research
- literature review
- paper writing
- knowledge/thinking accumulation

switch to `autonomous-research` first, and only return here when the work needs platform execution.

## Use This Skill When

Use this skill when the task involves any of the following:

- publishing, unpublishing, cleaning up, or pacing content
- article pool, scheduled posts, or cadence release
- admin notification email or daily digest
- admin dashboard operations
- strategy metadata / activation state
- member question ranking, candidate pool, or admin question workflow
- paper metadata management or PDF delivery
- admin user/role management
- ops jobs, audits, refresh, cache, or site health
- reading platform analytics to guide future actions

## Do Not Use This Skill When

Do not use this skill for:

- pure research analysis
- paper review / academic revision
- citation verification
- raw DB patching as a normal workflow

If there is already a platform surface for the task, use it instead of inventing a private path.

## Core Rules

Follow these rules in order:

1. **Prefer existing control-plane surfaces**
   - First check `/admin/*`
   - Then `/api/admin/*`
   - Then `uv run python -m volpred.cli ops ...`

2. **Prefer CLI/API before adding UI**
   - If a capability is missing, add the smallest shared surface first
   - Avoid building a UI-only form for a capability Claude also needs

3. **Do not make direct DB edits the normal path**
   - Use DB patches only for exceptional repair work
   - Normal operating flows should go through platform surfaces

4. **Keep platform work separate from research work**
   - Research creates findings
   - Platform operations publish, schedule, rank, release, manage, and observe

5. **Respect governance boundaries**
   - Adding new governance/supporting content is usually okay
   - Deleting or rewriting existing governance rules requires user approval first

## Operating Sequence

For any platform task, follow this sequence:

1. Identify the domain:
   - content
   - strategies
   - questions
   - users/access
   - ops/jobs
   - analytics

2. Load only the references you need:
   - `references/surfaces.md` for current pages / APIs / CLI
   - `references/platform-api-manual.md` for concrete workflows and payloads

3. Choose the narrowest stable surface:
   - human/manual view → `/admin/*`
   - Claude local operation → `uv run python -m volpred.cli ops ...`
   - structured read/write integration → `/api/admin/*`

4. If missing, extend the platform in this order:
   - shared logic
   - CLI/API
   - UI

## Default Patterns

Use these defaults unless there is a strong reason not to:

- **Publishing**
  - Prefer `draft` or `scheduled` over immediate release
  - Use cadence release when the task is about platform rhythm, not urgent publication
  - Treat article email as a platform notification, not a second article reader
  - If `sent=false`, interpret it as "notification prepared but not actually delivered"

- **Question ranking**
  - Read summary first
  - Evaluate pending questions
  - Rerank with stable insertion
  - Keep old ranked order stable

- **Analytics**
  - Prefer summary-first views
  - Use analytics as decision support, not vanity reporting

- **Users/Admin**
  - Prefer admin UI or admin API
  - Treat bootstrap admin email and DB role as separate concepts

- **Papers**
  - Paper writing and academic revision stay in the research layer
  - But paper metadata updates, PDF upload, and paper-page delivery belong to platform operations
  - Prefer DB row + Storage upload over static `public/paper/*.pdf` replacement

## Load References Progressively

Load these references only when relevant:

- `references/surfaces.md`
  - use when you need to know what currently exists

- `references/platform-api-manual.md`
  - use when you need exact CLI/API workflows and payload shapes

- `references/deploy-and-runtime.md`
  - use when the task is about Zeabur redeploy, runtime verification, worker/jobs, or session startup operations

- `references/session-cron-workflows.md`
  - use when the task is about packaging platform operations into Claude session cron routines

- `references/governance.md`
  - use when diagnosing errors or deciding whether to manually fix data vs fix the process
  - core principle: 永遠修流程，不修資料

- `references/architecture.md`
  - use when you need current platform topology, source-of-truth ownership, or deploy surface boundaries

- `references/data-flow.md`
  - use when the task touches `storage/` source-of-truth, `supabase_sync.py`, `daily_update.py`, `paper_trading.json` structure, or Mirror 雙寫

- `references/strategy-lifecycle.md`
  - use when adding / deactivating / recalculating a strategy; includes STRATEGY_REGISTRY 3-step SOP and upsert/activation CLI

- `references/monitor-usage.md`
  - use when deciding between Monitor / Bash(run_in_background) / CronCreate, or setting up session-level persistent monitors

**⚠️ 系統出錯時第一步：查 `docs/error_log.md`。** 不只研究錯誤，所有平台/sync/deploy/merge 錯誤都記錄在此。先查再修，避免重蹈覆轍。

Do not paste or re-explain all references by default. Load the minimal needed section and move.
