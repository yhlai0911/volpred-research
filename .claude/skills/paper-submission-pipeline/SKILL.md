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
synthesis, and submission decision). The fix is to make each paper's progress
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
`blocker`, `last_advance_at`, `owner_decision_pending`.

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
| `-> journal_submitted` | owner approval + target-journal portal submission (owner-timed: 找機會再丟) |

### Compliance gate (the `-> multi_round_review` bar)
- Author is solely **"Yi-Hao Lai"**.
- **ZERO** mentions of volpred / Claude / ChatGPT / GPT / LLM / "large language model" /
  AI-as-method / "this platform".
- No AI-style phrasing or symbols (em-dash tics, "delve", "it's worth noting", etc.).
- Cross-reference the paper-submission-compliance audit before clearing.

### Run reviews via codex to save tokens (boss directive 6)
All multi-round review rounds (latex-academic-reviewer, citation-verifier,
journal-review) run via **`codex exec`** (`codex:rescue` / `codex-cli`) — not in the
main thread — to save main-thread tokens. The main thread orchestrates, reads the
codex verdict, applies corrections (via `paper-update`), and advances the tracker.

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
4. `journal_submitted`: owner approval + portal submission, owner-timed.

Drafts / in-revision papers never skip ahead to arXiv. Priority claiming only protects
a manuscript that is genuinely ready.

---

## Tracker update conventions
- One stage advance = update `stage`, set `stage_entered_at` + `last_advance_at` to now
  (ISO-8601 with `+08:00`), and replace `blocker` with the next gate's blocker (or "").
- Set `owner_decision_pending: true` when the next move is owner-timed (submit decisions).
- Never hand-edit to skip a gate's CHECK criteria — that defeats the observability the
  process exists to provide. Advance only after the gate verifiably passes.
