# Paper stage tracker 統一分析

日期：2026-07-16

任務：`paper_stage_tracker_unification_analysis`

範圍：analysis-only；本文件不修改 stage、Supabase、前端或論文正文。

## 結論

建議保留 `storage/paper_pipeline_status.json` 的 submission pipeline 作為唯一 **decision source of truth**，但不要照原提案新增 `papers.stage`。

實際稽核推翻了「兩套 stage tracker 都已在寫資料」這個前提：

- 11-stage pipeline 是真的持久化 tracker，也是 stall detector、paper adjudication 與 website drift alert 的輸入。
- 5-stage `paper-stage-classifier` 是舊的分類規格；它要求的 `paper-upsert --stage`、`papers.stage` 與 details fallback 都沒有實作。它目前只存在於 skills / docs 的判斷與路由文字中。
- Supabase `papers.status` 不是第二套研究決策 stage，而是公開網站的 **display projection**。目前兩者分開是合理的，但 projection 規則重複、手動同步，且部分語意不完整。

因此應做的不是「合併兩個資料表」，而是：

1. 把 submission pipeline 的 enum、transition 與 display projection 收斂為一個 machine-readable owner。
2. 為 `paper_pipeline_status.json` 增加唯一、帶鎖、會驗證 transition 的 writer。
3. 把 `paper-stage-classifier` 改成 canonical pipeline 的衍生 view / 相容入口，移除獨立寫 stage 的指令。
4. Supabase 保持 display-only；核心統一不需要 schema migration。只有決定新增 `preprint` 等公開 label 時才需要前端協調。

## 1. 現況證據

### 1.1 11-stage submission pipeline：實際 decision tracker

`storage/paper_pipeline_status.json:2-20` 自稱 source of truth，列出 11 個 stage：

`draft → revision → compliance_scrub → multi_round_review → review_converged → arxiv_ready → arxiv_posted → journal_submitted → under_journal_review → accepted / rejected`

同一 state machine 也出現在 `.claude/skills/paper-submission-pipeline/SKILL.md:24-42`；其 ACT 步驟明確要求更新 tracker 的 `stage`、`stage_entered_at`、`last_advance_at` 與 `blocker`（同檔 `:94-113`）。

目前 tracker 有 13 篇：

| stage | 數量 |
|---|---:|
| `draft` | 2 |
| `revision` | 10 |
| `multi_round_review` | 1 |

實際 reader：

| Reader | 用途 | 證據 |
|---|---|---|
| `scripts/paper_pipeline_check.py` | stall / data issue 報告 | `:1-44`, `:58-117` |
| `src/volpred/ops/alerts.py::_parse_paper_website_drift_state` | 11-stage 對 public status 的 over-claim 檢查 | `:2150-2314` |
| `src/volpred/ops/alerts.py` paper adjudication gap | blocker 引用 terminal task 後的裁決義務 | `:2346` 起 |
| `.claude/rules/paper-workflow.md` | `blocked_on_tasks`、12 小時裁決義務 | `:1-20` |
| `paper/*/EXECUTION.md` 與 review history | 各 paper 的執行與審查依據 | `rg paper_pipeline_status.json paper/` |
| tests | drift、adjudication、特定治理 invariant | `tests/test_paper_adjudication_gap_alert.py`, `tests/test_k189_k1544_governance.py` |

實際 writer 現況較弱：repo 沒有 `paper_pipeline_status` transition CLI 或 writer；`rg` 只找到測試 fixture 直接 `write_text`。git history 顯示 tracker 由 paper / ops commits 直接改檔；`scripts/paper_pipeline_check.py` 也不驗證 stage 是否屬於 `_meta.state_machine`。這代表 canonical tracker 已成立，但沒有 canonical write path、transition validation、schema validation 或鎖。

### 1.2 5-stage classifier：活躍指引，非活躍資料庫 tracker

`.claude/skills/paper-stage-classifier/SKILL.md:17-23` 定義：

`early / draft / review / ready_for_submission / submitted`

它在 `:40-49` 要求：

- 依 pages / review report 分類。
- 執行不存在的 `volpred ops paper-upsert --stage <stage>`。
- 更新 `next_tasks.json` description。
- 把 frontend 的 display status 誤稱為同一組 stage dependency。

但同 skill `:125-135` 又明寫 DB schema 與 CLI 都是「待實作」。實際檢查也證實：

- `src/volpred/cli.py:2654-2684` 的 `paper-upsert` 只有 `--status`，沒有 `--stage`。
- `src/volpred/ops/papers.py:31-34, 103-162` 只讀寫 `status`，沒有 `stage` 或 details stage。
- `supabase/migrations/20260321142700_papers_table.sql:2-18` 與 `frontend-v2-fix/supabase/migrations/001_schema.sql:128-140` 都只有 `status`。
- repo 內只有 classifier / review-cycle 兩個 skill 提到 `paper-upsert --stage`，沒有 production caller。

因此 5-stage 的風險不是「另一份 DB 真值已漂移」，而是 agents 仍可能依舊 skill 做不同 stage 判斷、嘗試不存在的 CLI，或把公開 status 當研究決策 stage。

它的主要 consumer 都是文字路由：

- `.claude/skills/paper-review-cycle/SKILL.md` Step 4
- `.claude/skills/paper-update/SKILL.md` scope boundary
- `.claude/skills/journal-review/SKILL.md` prerequisite
- `.claude/rules/task-routing.md` 的 `paper_decision`
- `docs/workflow-index.md`、`docs/skill-registry.md`、`docs/ops_team_structure.md`
- `config/supervisor_rules.json`

沒有 runtime Python / Supabase reader 依賴 5-stage 值。

### 1.3 Supabase / frontend：display projection，不應升格成 decision SoT

`papers.status` 的 ops writer 是：

`uv run volpred ops paper-upsert --paper-id <id> --status <value>`

資料流：

`paper-upsert → src/volpred/ops/papers.py → Supabase papers.status → /api/papers → /paper + /v3/paper`

兩個前端共用 `/api/papers`，但 display vocabulary 並不完全一致：

- 原版 `frontend-v2-fix/src/app/paper/page.tsx:9-73` 支援 `working / major_revision / ready_for_submission / submitted / accepted / published`，另有 unknown fallback。
- v3 `frontend-v2-fix/src/app/v3/paper/page.tsx:39-69` 只宣告 `working / ready_for_submission / submitted / accepted / published`。
- Admin 另有直接 Supabase writer（`frontend-v2-fix/src/lib/admin-papers.ts` 與 admin papers API）；其表單 vocabulary 只有 `working / submitted / accepted / published`，漏 `ready_for_submission`。它能繞過 pipeline transition 與 projection，是 implementation phase 必須收編的 write surface。
- drift alert 的 rank 只認 `working / ready_for_submission / submitted / accepted / published`（`src/volpred/ops/alerts.py:2160-2183`）；`major_revision` 不在 rank 中，故不會被判 over-claim。
- 同一 alert mapping 已列出 pipeline `published`，但 tracker `_meta.state_machine` 沒有 `published`；目前 tracker metadata/spec 11 態、detector mapping 12 態，而且尚無 validator。

2026-07-16 live readback：Supabase production schema 有 18 欄，沒有 `stage` 或 `details`，`status` 是無 CHECK constraint 的 TEXT；沒有 papers RPC。Supabase 有 11 篇 papers row，11 篇全部是 `working`。已上站的 11 篇在現行 projection 下都應為 `working`，因此這個 snapshot 是 exact in-sync；tracker-only 的 `btc-gas-negative`、`forecast-tail-divergence` 尚未上站，projection / sync 不得因此自動建立 public row。

## 2. 語意缺口

### 2.1 `early` 不是 submission stage

`early` 由頁數與結構完整度推導，較像 manuscript maturity assessment。submission pipeline 從 `draft` 開始是合理的。`early` 應保留為非持久化診斷，例如 `maturity=early`，不應寫入 canonical submission stage。

### 2.2 舊 `ready_for_submission` gate 太弱

5-stage classifier 只要求 reviewer 星等與 citation finding 數量；11-stage pipeline 還要求 reproduce、compliance、contribution、target-journal review 與 0 HIGH。研究誠實上必須採後者。衍生 view 只有在 canonical stage 到 `review_converged` 或 `arxiv_ready` 時才可顯示 ready。

### 2.3 `arxiv_posted` 不等於 journal `submitted`

目前 skill / alert 把 `arxiv_posted` 投影成 public `submitted`。讀者通常會把 Submitted 理解為已投期刊，這可能造成語意 over-claim。

建議：

- 最佳方案：新增 public `preprint` label。
- 在前端尚未部署 `preprint` 前：`arxiv_posted` 繼續顯示 `ready_for_submission`，另以 arXiv URL / badge 表示 preprint。
- 只有 `journal_submitted` 與 `under_journal_review` 投影成 `submitted`。

### 2.4 canonical pipeline 缺 `published`

11-stage 以 `accepted / rejected` 結束，但網站有 `published`。owner 必須二選一：

1. 建議：在 `accepted` 後加入 `published` terminal stage，形成 12-stage lifecycle。
2. 或把 publication 狀態建成與 submission stage 正交的 `publication_state`。

不要讓 `published` 只存在 Supabase；否則生命週期尾端仍有不可逆的第二真值。

### 2.5 `rejected` 應是一次投稿的 outcome，不一定是 paper 終點

若換期刊重投，需允許 `rejected → revision`，同時保存 `submission_attempts[]` 或歷史 receipt；不能覆蓋掉拒稿紀錄後假裝從未投稿。

### 2.6 `major_revision` 缺單一語意

public `major_revision` 可能指內部 major rewrite，也可能指 journal R&R。建議只在有已驗證 journal decision 時使用；內部修稿一律投影為 `working`。若保留此 display status，v3 與 drift mapping 必須一起補齊。

## 3. 建議 target architecture

```text
config/paper_pipeline_stages.json
  ├─ stages / allowed transitions / terminal flags
  ├─ public projection
  └─ gate requirements
           │
           ▼
src/volpred/ops/paper_pipeline.py
  ├─ validate_tracker()
  ├─ transition_paper()
  └─ project_public_status()
           │
           ├─ paper-stage-transition CLI（唯一 writer，flock + atomic write）
           ├─ paper_pipeline_check.py（reader + validation）
           ├─ alerts.py（共用 projection，不再複製 mapping）
           └─ paper-upsert（display sync，仍由 gate 控制）

storage/paper_pipeline_status.json = decision instances / evidence / history
                                    （只存 spec_version/spec_sha256 pointer，不複製 enum）
Supabase papers.status           = derived public display only
paper-stage-classifier skill     = compatibility alias + derived maturity view
```

為何把 enum 放 `config/`：stage vocabulary、transition 與 projection 是流程規格，不是某次 paper 的執行資料；符合專案「規格先進 canonical config」原則。`storage/paper_pipeline_status.json` 只保存 paper instance state 與 gate evidence。

## 4. Migration 計畫

### Phase 0 — owner 語意裁決

需要 owner 決定：

1. 是否採 `published` 為 canonical 第 12 stage（建議是）。
2. 是否新增 public `preprint`（建議是）；部署前 `arxiv_posted` 保守投影為 ready。
3. `major_revision` 是否只保留給 verified journal R&R（建議是）。
4. display sync 是否在 transition CLI 內自動執行；初期建議仍需 explicit `--sync-display`，避免未驗證 aspirational stage 上線。

### Phase 1 — 先加 read-only canonical spec

- 新增 `config/paper_pipeline_stages.json`。
- 新增 `paper_pipeline.py` 讀取 spec，提供 enum validation 與 projection。
- Phase 1 不改 tracker bytes：helper 暫時接受 legacy `_meta.state_machine`，但只把它當待遷移副本，validator 必須驗證它與 config byte-equivalent；不一致就 fail loud，且任何流程都不得再把它當可編輯 owner。
- submission pipeline skill 與其他 active skills 只連到 config / helper，不再手列 stage enum 或 projection mapping。
- `paper_pipeline_check.py` 驗證 tracker 的 stage、必要欄位與 unknown stage；仍不改任何資料。
- `alerts.py` 改呼叫同一 projection helper，移除本地 `_PIPELINE_STAGE_MAX_WEBSITE_RANK` 副本。
- unknown stage 在 check / drift detector 都要 fail loud 或 degraded breach，不能像現在 `max_rank=None` 一樣靜默跳過。

Rollback：移除 helper 使用、回到現有 hard-coded mapping；tracker bytes 不變。

### Phase 2 — 建唯一 transition writer

新增：

```bash
uv run volpred ops paper-stage-transition \
  --paper-id <id> \
  --to-stage <stage> \
  --evidence <path-or-task-id> \
  --blocker '<next gate>' \
  [--sync-display]
```

Writer 必須：

- writer 上線時以同一把 sidecar lock 執行一次 metadata migration：移除 legacy `_meta.state_machine`，改存 `spec_version` / `spec_sha256`，並在 receipt 保存 migration 前後 SHA。
- 鎖定穩定的 sidecar lease（例如 `storage/.paper_pipeline_status.lock`），不可鎖 target JSON inode；從 read → validate → temp write/fsync → `os.replace` → parent directory fsync 的完整 transaction 都持有 `fcntl.LOCK_EX`。
- 驗證 allowed transition，禁止無證據跳 gate。
- 同時更新 `stage_entered_at`、`last_advance_at`、`blocker`。
- 保存 transition history / evidence，不覆蓋 rejection / submission receipt。
- 走 explicit-path git writer；禁止多 agent 手改同一 tracker。
- `--sync-display` 先計算 projection，若會 over-claim 則 fail closed。local decision commit 與 Supabase remote write 不宣稱原子化：receipt 分別記錄 `decision_committed` 與 `display_sync=pending|succeeded|failed`，配合 idempotency key / outbox 重試；remote 失敗不得重跑或回滾已完成的 decision transition。

Rollback：writer 上線前保留 tracker backup hash；writer 每次 transition 可由 history 反向產生 compensating transition，不用 `git reset` 或手改 JSON。

### Phase 3 — 退休獨立 5-stage 指令

- 保留 skill 名 `paper-stage-classifier` 作相容 alias，避免一次打斷所有路由。
- 刪除不存在的 `paper-upsert --stage`、`papers.stage` / tags fallback 與「更新 next_tasks 等於 stage persistence」文字。
- stage 判定改讀 canonical tracker；pages / structure 只輸出非持久化 `maturity`。
- `paper-review-cycle`、`paper-update`、`journal-review`、task routing、workflow index、skill registry、ops team docs 全改 pointer 到 canonical pipeline。
- `next_tasks` 只保留執行任務，不保存另一份 paper stage。

### Phase 4 — public display 收斂

- 若 owner 核准 `preprint` / R&R-only `major_revision`，先同步修改 `/paper` 與 `/v3/paper`，再允許 writer 投影新值。
- 兩前端共用一個 status type / label module，避免 union 再漂移。
- Admin status picker 不再直接發明 display 狀態：要嘛改成 read-only，要嘛只呼叫 canonical transition / projection API；至少必補 `ready_for_submission` round-trip。
- Supabase `status` 現為 TEXT，不需要為核心統一新增 `stage` column；可另加 CHECK constraint，但必先清點 production distinct values。
- deployment 後用 `/api/papers`、`/paper`、`/v3/paper` 三面驗證。

Rollback：先部署能讀新舊 status 的 frontend，再啟用新 projection；保留上一版 bundle 與可逆的 CHECK-constraint drop migration。readback 失敗時把 public projection 回復舊值，但不回退研究 decision stage。

### Phase 5 — 移除相容層

連續至少兩個 review / submission transition 都只走新 writer，且 audit 無舊 `--stage` caller 後，才考慮把 classifier skill 改名或移除。不要在同一 commit 同時改 enum、writer、skills、frontends 與 production data。

## 5. Acceptance gates

### Static / unit

- spec 中每個 stage 都有 terminal flag、allowed transitions 與 public projection。
- active repo 只有 `config/paper_pipeline_stages.json` 一份 authoritative enum / transition / projection mapping；tracker 只存可驗證的 spec pointer，skills 只存連結。
- exhaustive test 覆蓋全部 stage；unknown stage fail loud。
- `review_converged` 以前不可投影 ready；`journal_submitted` 以前不可投影 submitted。
- `arxiv_posted` 不可投影 journal submitted。
- illegal skip（例如 `revision → arxiv_ready`）失敗。
- `rejected → revision` 必保存舊 attempt evidence。
- `rg 'paper-upsert .*--stage|papers.stage'` 在 active rules / skills / code 為零。

### Tracker

- 全部 paper id 唯一。
- 每筆 current stage 在 canonical spec。
- `stage_entered_at`、`last_advance_at` 可解析且 transition history 單調。
- blocker 引用的 task terminal 後，adjudication gap gate仍有效。
- writer concurrency test 證明兩個 process 不會 lost update。
- concurrency test 必須涵蓋 `os.replace` 後第二個 process 開啟新 target inode 的情境，證明 sidecar lock 仍序列化整個 transaction。
- display sync failure receipt 必須保留已完成 decision、標記 outbox pending/failed，且 idempotent retry 不會重跑 transition。

### Display / deployment

- production `/api/papers` distinct status 全在兩前端共同 type / config。
- Admin 能 round-trip `ready_for_submission`，且不能繞過 canonical transition 製造 over-claim。
- tracker → public projection 不存在 over-claim。
- `/paper` 與 `/v3/paper` 都能 render 每個 status；unknown status 仍有 defensive fallback。
- 若新增 `preprint`，頁面文字不能暗示已投 journal。
- curl + browser 驗證兩版；部署失敗不修改 production projection。

### Operational

- `paper_pipeline_check.py` 的原有 stall semantics 不變。
- `paper_website_drift`、`paper_adjudication_gap` tests 全綠。
- 至少一次真實 transition 產生 transition receipt、tracker commit 與（若選）display sync readback。
- tracker-only paper 不會因 projection 被自動建立成 public paper。

## 6. 影響面與不做事項

本次分析建議未來會改：

- `config/`：新增 canonical stage spec。
- `src/volpred/ops/` + CLI：validator、projection、writer。
- `scripts/paper_pipeline_check.py`、`src/volpred/ops/alerts.py`。
- paper workflow skills / routing docs。
- 可選：active frontend 兩個 paper route 的 shared display status module。

本次不建議：

- 不新增 `papers.stage`。
- 不把 11-stage 值直接送到 frontend。
- 不用 tags/details 偷存 stage。
- 不手改 production Supabase 或 tracker 來「先對齊」。
- 不在 owner 語意裁決前實作 `published` / `preprint` / `major_revision` 規則。

## 7. 最終建議

批准方向應是「11-stage submission pipeline（補齊 published 語意）為唯一決策生命週期；public status 是單向衍生投影；5-stage classifier 退為相容入口與 maturity view」。

這個方案消除的是實際存在的三個風險：舊 skill 會下不存在的命令、tracker 沒有 canonical writer、projection 分散且可能把 arXiv 誤稱 journal submitted。它不會為了解決一個未實作的 `papers.stage` 而新增第三份資料。
