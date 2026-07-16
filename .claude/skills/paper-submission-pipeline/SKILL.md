---
name: paper-submission-pipeline
description: >
  Canonical SOP for driving any paper from revision through arXiv/journal submission
  via a staged-gate state machine. Use when advancing a paper toward submission:
  picking which paper to push next, running a gate (compliance scrub / multi-round
  review / arXiv post), or when the stall detector flags a paper as stuck. Makes each
  paper's progress OBSERVABLE (stage tracker) and DRIVEN (gates + stall alert) so
  "papers stalled" surfaces automatically instead of waiting for the owner to notice.
  Trigger phrases: 'paper submission', '投稿', 'arXiv', 'submission pipeline',
  'paper stalled', '論文卡關', 'advance paper', 'compliance scrub', 'contribution gate'.
  Do NOT use for: writing/revising .tex body (use paper-update), running a single
  review round mechanically (this skill orchestrates them via codex), or feed articles.
---

# Paper-Submission Pipeline (PDCA / loop-engineering process)

**Root problem this solves**: the owner felt "papers are stalled." Diagnosis: papers
are NOT short of findings — they stall at two ungoverned gates (experiment→narrative
synthesis, and submission execution). The fix is to make each paper's progress
**observable** (stage tracker) and **driven** (gates + a stall detector that alerts
when a paper sits at one stage too long), so stalls surface automatically.

- **Tracker (source of truth)**: `storage/paper_pipeline_status.json`
- **Check / stall detector**: `scripts/paper_pipeline_check.py` (prints JSON; exit 1 = findings)
- **Dependencies (reference, do not duplicate)**: `journal-review` (per-journal
  requirements), `latex-academic-reviewer` + `citation-verifier` + `paper-review-cycle`
  (the review engines), the paper narrative state machine in `CLAUDE.md`,
  `.claude/rules/publishing.md` compliance norms.

---

## State machine (one stage per paper)

```
draft -> revision -> compliance_scrub -> multi_round_review -> review_converged
      -> arxiv_ready -> arxiv_posted -> journal_submitted -> under_journal_review
      -> accepted / rejected
```

Each paper carries: `paper`, `journal_target`, `stage`, `stage_entered_at`,
`blocker`, `last_advance_at`, `owner_decision_pending`（legacy compatibility；依
2026-07-09 standing authorization，投稿本身不得再把它設為 true）.

---

## ⚠️ TWO BOSS HARD RULES (2026-07-01) — most important, read first

### Hard rule (i) — CONTRIBUTION GATE before any review converges
期刊審查一定要看**貢獻**，不是單純計量方法的練習。Before a paper can pass
`review_converged`, the review MUST first establish a genuine novel **contribution**
with economic/theoretical significance. The reviewer answers, in one paragraph:

> "What does this paper teach the field that was not known before? Why does it matter
> economically/theoretically? Is it more than a method demonstration?"

A paper that is **only** a method exercise / incremental robustness check **FAILS this
gate and does NOT advance** — it is desk-reject bait. Contribution is checked *first*;
econometric correctness comes *after* and is necessary but not sufficient.

### Hard rule (ii) — arXiv is ONLY for ready-for-submission papers
不是每一篇都要馬上上 arXiv，是 **ready for submission** 的才可以。Post to arXiv FIRST
to claim priority — **but ONLY** for papers that have cleared `review_converged`
(contribution + reviews + compliance). **Drafts and in-revision papers MUST NOT be
posted to arXiv.** 最終版先丟 arXiv 佔位，找機會再丟目標期刊。

---

## Gates (PDCA "Check" — verifiable, between stages)

| Transition | Verifiable criteria |
|---|---|
| `-> compliance_scrub` | reproduce gate GREEN + known revision blockers resolved |
| `-> multi_round_review` | **COMPLIANCE CLEAN** (see below) — cross-ref the paper-submission-compliance audit |
| `-> review_converged` | **(a) CONTRIBUTION GATE first** (hard rule i), **then (b)** latex-academic-reviewer + citation-verifier + journal-review(target-specific) ALL pass with **0 HIGH findings**, iterated until convergence |
| `-> arxiv_ready` | only papers past `review_converged` reach here; final manuscript compiles clean; all gates green; compliance re-verified |
| `-> arxiv_posted` | post to arXiv first (hard rule ii — ready-for-submission only) |
| `-> journal_submitted` | gates 全綠後由主線程自主完成 target-journal portal submission；不逐篇再問 owner。若缺登入、付款或法律聲明等外部輸入，寫入 `blocker`，不是重開投稿決策 |

### Compliance gate (the `-> multi_round_review` bar)
Compliance prose 的唯一 owner = **`journal-review` Step 6**（authorship = Yi-Hao Lai only;
ZERO volpred / Claude / ChatGPT / GPT / LLM / "large language model" / AI-as-method / "this
platform" mentions; AI-use declaration 為期刊要求時的獨立 titled 章節，非 footnote、非默默省略;
no AI-style phrasing/symbols）+ 機械 gate **`scripts/check_paper_compliance.py`**. 清此 gate
前必跑該 compliance audit；本 skill 不重複清單。

### Run reviews via codex to save tokens (boss directive 6)
Review-round 編排（透過 `codex exec` (`codex:rescue` / `codex-cli`) 跑 latex-academic-reviewer
+ citation-verifier + journal-review、不在主線燒 token、迭代到收斂、主線程只 orchestrate +
adjudicate verdict + apply corrections via `paper-update`）的 owner = **`paper-review-cycle`
Step 1**. 本 pipeline 只 orchestrate gate，讀 codex verdict 後 advance tracker；不重複編排細節。

---

## PDCA loop (per tick / session — drive ONE paper, ONE gate)

1. **PLAN** — Run `scripts/paper_pipeline_check.py` to see every paper's stage,
   days-in-stage, and stall flags. Pick the paper **closest to its next gate** (or
   the highest-value next move). Stalled papers (>7d in stage) take priority.
2. **DO** — Drive that one gate: scrub compliance / dispatch a codex review round /
   apply corrections via `paper-update` / post to arXiv (ready-for-submission only).
3. **CHECK** — Verify the gate's criteria are actually met: compliance clean /
   0 HIGH findings / reproduce green / contribution paragraph written and passing.
   Do NOT advance on assumption — verify.
4. **ACT** — Advance the stage in `storage/paper_pipeline_status.json` (update
   `stage`, `stage_entered_at`, `last_advance_at`; clear/replace `blocker`). If a
   recurring blocker pattern appears, codify the lesson (`docs/error_log.md` / a skill).
   - **Sync the public website whenever `stage` or `journal_target` changes AND the
     paper is already live on the site** (Supabase `papers` row exists). The pipeline
     tracker is the DECISION truth; the Supabase `papers` table is the DISPLAY truth —
     they do not reconcile automatically. Use the canonical CLI (never hand-edit the DB):
     `uv run volpred ops paper-upsert --paper-id <id> --status <working|ready_for_submission|submitted|accepted|published> [--target-journal <name>]`.
     Map `stage → website status` honestly: `draft/revision/compliance_scrub/multi_round_review → working`;
     `review_converged/arxiv_ready → ready_for_submission`; `arxiv_posted/journal_submitted/under_journal_review → submitted`.
     **Never let the website status be HIGHER than the stage warrants** (over-claim =
     research-honesty breach). Both frontends (`/paper` + `/v3/paper`) read the same
     `/api/papers` → one upsert syncs both. (2026-07-01 incident: leverage-direction
     JBF→IJF + downgrade to revision, but the site sat on `ready_for_submission` +
     JBF until the owner caught it — the drift alert below now auto-surfaces this.)

### Stall detection (loop-engineering)
If a paper sits at one stage **> STALL_DAYS (default 7)**, `paper_pipeline_check.py`
flags it and (with `--alert`) fires a **warn** alert via `volpred.ops.alerts.send_alert`
listing the stalled papers — so "papers stalled" is an auto-surfaced signal, not an
owner discovery. The check exits 1 under FINDINGS semantics; if ever put on host cron,
its `runtime_schedules.json` entry MUST carry `exit_semantics: "findings"` (2026-06-30
host_cron_fail lesson).

### Website over-claim detection (loop-engineering, 2026-07-01)
`volpred.ops.alerts._parse_paper_website_drift_state` (condition `paper_website_drift`,
wired into the hourly `check-alerts` pipeline) compares each paper's pipeline `stage`
against its Supabase `papers.status`. If the public website status is **higher** than the
stage warrants (over-claim), it fires a **warn** alert listing the drifted papers + the
`paper-upsert` fix command. Under-claim (website more conservative than the stage) is NOT a
breach — this deliberately protects papers whose pipeline stage is aspirational-but-unverified
(e.g. `under_journal_review` while the site conservatively shows `working`). Journal
name mismatch (abbreviation vs full name) is a body annotation only, never a breach.
This makes "decision changed but website not synced" an auto-surfaced signal.

---

## arXiv-first-then-journal sequencing (recap)
1. Paper clears `review_converged` (contribution + reviews + compliance).
2. `arxiv_ready`: final manuscript compiles clean, compliance re-verified.
3. `arxiv_posted`: post to arXiv to claim priority — **ready-for-submission papers only**.
4. `journal_submitted`: gates 全綠後自主 portal submission；7/9 standing authorization
   已取代逐篇 owner approval。只有客觀外部輸入缺口才 block。

Drafts / in-revision papers never skip ahead to arXiv. Priority claiming only protects
a manuscript that is genuinely ready.

---

## Tracker update conventions
- One stage advance = update `stage`, set `stage_entered_at` + `last_advance_at` to now
  (ISO-8601 with `+08:00`), and replace `blocker` with the next gate's blocker (or "").
- `owner_decision_pending` 為 legacy 欄位，投稿決策一律維持 `false`。缺 portal credential、
  payment 或法律聲明時，精確寫 `blocker`；不得用此欄把已授權的投稿工作退回 owner。
- Never hand-edit to skip a gate's CHECK criteria — that defeats the observability the
  process exists to provide. Advance only after the gate verifiably passes.
