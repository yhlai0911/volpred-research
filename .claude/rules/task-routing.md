---
paths:
  - "storage/next_tasks.json"
  - "scripts/task_pool_claim.py"
  - "scripts/continue_task_dispatch.py"
  - "scripts/cron_hourly_dispatch_prompt.md"
  - "AGENTS.md"
  - ".claude/skills/autonomous-research/references/delegation-playbook.md"
---

# Task Pool — Routing & Capability Matrix

Canonical mapping of `task_type` → who can claim, concurrency rules, special constraints.
**Updated 2026-05-25**: backfill applied (0 null types remaining); experiment_review collapsed into paper_review; email_reply added.

## 12 canonical task types

| task_type | Claude | Codex | 並行 | Skill / Workflow canonical | 特殊規則 |
|---|---|---|---|---|---|
| **experiment** | ✅ | ✅ | up to 4 | `autonomous-research` | worktree only; Codex review before knowledge.json write (K1259 gate) |
| **paper_review** | ✅ | ✅ (small text fix) | serialize per paper | `paper-review-cycle` | latex-academic-reviewer + citation-verifier 並行 |
| **paper_body** | ✅ only | ❌ | serialize per paper | `paper-update` | **禁止 background agent 寫 .tex** (CLAUDE.md hard rule); main thread only |
| **paper_decision** | ✅ only | ❌ | one at a time | `paper-stage-classifier` | 需 ≥3 互補實驗 + user confirm 才進 `decision_made_awaiting_body_rewrite` |
| **daily_article** | ✅ | ✅ | up to 2 | `feed-publisher` + `anti-ai-style` | reader-facing 3-canonical 必讀；publication-candidates 選題；3-layer dedup |
| **event_article** | ✅ only | ❌ | one at a time | `feed-publisher` + event templates | 即時性需要主線程判斷；直接 `published` 不入 draft pool；**FB 雙發佈強制**（2026-05-25 起；共用 trending-repost FB SOP，不算 trending daily cap） |
| **member_qa** | ✅ only | ❌ | one at a time | `member-questions` | 4 維度評分 → question-rerank → research → publish；每 6h cron |
| **trending_repost** | ✅ only | ❌ | **daily cap = 2/day** | `trending-repost` | VolPred angle 改寫 + 無 source citation；雙發佈 feed + Ivan Lai FB（**同 event_article 共用 FB SOP**） |
| **strategy_lifecycle** | ✅ only | ⚠️ (review 子任務) | one at a time | strategy-registry + `scripts/evaluate_new_strategy.py` | 同期間比較 + cross-OOS + Codex review + sensitivity + MDD gate |
| **platform_ops** | ✅ | ✅ | up to 4 | (varies — admin-ops / specific script) | bug fix / refactor / cron 維修 / data pipeline 修補 |
| **governance** | ✅ | ✅ (skill/rule 修整) | serialize | (depends on target — rules/skills/docs) | 改 governance 檔前先 commit snapshot；snapshot: prefix |
| **email_reply** | ✅ only | ❌ (但**接 linked sub-tasks**) | one at a time | `cron_hourly_dispatch_prompt.md` PHASE 0 | filter: from owner + Re: + 含 `[VolPred`；兩段式 plan email + close email |

## Routing decision tree（dispatcher 用）

```
任務 in pending:
  ├─ task_type == "email_reply"
  │     └─ Claude PHASE 0 only（最高優先；Codex skip）
  │
  ├─ task_type in {paper_body, paper_decision, event_article, member_qa, trending_repost, strategy_lifecycle}
  │     └─ Claude only（主線程紀律 / API 一致性需求）
  │
  ├─ task_type == "paper_review"
  │     ├─ description 含 errata / footnote / typo / table-fix → Codex 可接
  │     └─ 含 structural / new section / methodology change → Claude only
  │
  └─ task_type in {experiment, daily_article, platform_ops, governance}
        └─ Claude OR Codex — claim 機制決定 (fcntl atomic, 先到先得)
```

## 並行上限（M1 Max 10 核）

- **Total slot cap = 4**（hardware 容量）
- **Per task_type sub-cap**：
  - experiment: 4（最大耗算力但 worktree 隔離）
  - daily_article: 2（避免同時撞文章池釋出節奏）
  - paper_*: serialize per paper（同篇論文同時只一個 agent 動）
  - trending_repost: 2/day（daily cap，per `.claude/skills/trending-repost/SKILL.md`）

## Email reply 的特殊兩段流程

`email_reply` 是唯一 lifecycle 跨 multiple ticks 的類型：

```
Tick N: Phase 0.B claim → ANALYZE → PLAN → send PLAN email → execute / 派 sub-tasks → 
        write plan + linked_task_ids + needs_close_reply=true → 留 in_progress
Tick N+1..M: Phase 0.A check linked_task_ids 全完成？→ send CLOSE email → complete
```

Linked sub-tasks 用一般 task_type（描述含 `parent_email_task_id` 反向追蹤）— Codex 可接這些 sub-tasks，主線程負責收尾 close email。

## 維護紀錄

| Date | Change |
|---|---|
| 2026-05-25 | 初版 — backfill 60 個 null/experiment_review tasks；email_reply 加入；本表落地 |
