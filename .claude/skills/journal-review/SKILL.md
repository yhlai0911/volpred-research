---
name: journal-review
description: >
  Use this skill to run a JOURNAL-SPECIFIC format + substance review on a
  submission-ready paper and to pick the right target journal. It loads the
  chosen journal's profile (scope, format limits, fees, distinctive rules,
  pre-submission checklist), runs multi-round latex-academic-reviewer +
  citation-verifier (via codex exec to save tokens), then a journal-specific
  format check, a substance/fit check, and a compliance gate (author = Yi-Hao
  Lai only; no volpred / AI / LLM mentions) before assembling the submission
  package. Trigger phrases: '投哪個期刊', 'journal review', '期刊投稿審查',
  'pick journal', 'submission package', 'format check for JBF/JFE/RFS/...'.
  Do NOT use for: writing paper body (use paper-update / finance-paper-quality),
  generic LaTeX review with no target journal (use latex-academic-reviewer),
  or citation-only checks (use citation-verifier).
---

# Journal Review

Journal-targeted gate for a **submission-ready** paper. This skill does NOT write
the paper and does NOT re-derive results — it picks the right venue, enforces that
journal's mechanical rules, pressure-tests fit, runs the compliance gate, and
assembles the submission package.

Prereq: the paper must already be `ready_for_submission` per
`paper-stage-classifier`. If it is still in `draft`/`review`, run
`paper-review-cycle` first — this skill is the LAST gate before the portal.

## Workflow

### 1. Pick the journal
- Read `references/journal-index.md` — the comparison table (tier, scope, length
  limit, abstract type, distinctive requirement, decision time) lets you match the
  paper to 1-2 candidates fast.
- Match on: (a) core contribution type — forecasting/evaluation → IJF/JoF;
  econometric-methodology → JoE; general empirical finance → JBF; top-3 economic
  mechanism → JFE/RFS; practitioner payoff → JPM/FAJ; Asia-Pacific data → PBFJ;
  short single result → FRL — and (b) data region, length, audience.
- Confirm scope fit BEFORE anything else (most journals charge a non-refundable
  submission fee forfeited on desk-reject). Hard scope gates: FRL excludes
  single-country replications; PBFJ excludes US-only data; JPM/FAJ reject
  "written for an academic audience" / highly-quantitative; JoE rejects
  applied-only (no methodology) papers.

### 2. Load the journal reference
- Read `references/<abbrev>.md` for the full profile + its extended
  pre-submission checklist. The per-journal checklist is canonical; the generic
  `templates/submission-checklist.md` is the floor every journal extends.

### 3. Multi-round latex-academic-reviewer + citation-verifier (via codex exec)
- Run review rounds with `latex-academic-reviewer` (logic/structure/equations)
  and `citation-verifier` (refs/DOIs) — see those skills; do not duplicate them
  here.
- **Token economy**: delegate each round to `codex exec` (heredoc + stdin for
  zh-Hant prompts) so the heavy read of the `.tex` + bibliography happens in the
  subprocess, not the main context. Reserve the main thread for adjudicating
  findings and writing canonical changes. See `codex-cli` skill.
- Iterate until reviewer findings converge (no new structural/citation defects).
  Reader-facing abstract/summary prose also passes `anti-ai-style`.

### 4. Journal-specific FORMAT check
Run the mechanical checklist from `references/<abbrev>.md`. The high-frequency
trip-ups (count them, don't eyeball):
- Abstract word cap (JFE/RFS = 100; JBF = 150; IJF = 100-150; FAJ ≈ 100;
  JPM ≈ 160; FRL/JoE/PBFJ = 250).
- Main-text cap (FRL = 2500 words; JPM = 4000 target / 2500-7500).
- Highlights file (JBF/FRL/IJF/PBFJ): 3-5 bullets, each ≤85 chars incl. spaces,
  filename contains "highlights".
- Anonymization for double-blind venues (JBF/JFE/RFS/IJF/PBFJ/FAJ) vs
  single-blind (JoE-uncertain/JoF) — strip metadata too.
- References style: author-date Harvard/APA/Chicago per journal (NOT numbered).
- Editable source only (Elsevier): .tex (elsarticle) or single-column .docx;
  PDF is not an acceptable source. FAJ/JPM prefer Word.
- Exhibit naming (JPM = "Exhibit N"); tables ≤8 cols & B&W-legible (FAJ).

### 5. SUBSTANCE / fit check
Run the journal's substance bullets. Cross-cutting rigor every finance/forecasting
referee polices (and our `experiments.md` enforces):
- OOS design, explicit lag (`signal.shift(1)`), forward-label `target_end <
  forecast_origin`, matched lag for baseline vs proposed.
- Forecast-eval correctness: DM / HLN small-sample correction / Giacomini-White /
  MCS; QLIKE = actual/predicted; horizon-matched inference; cluster-robust /
  date-aggregated (no asset-day iid pooling).
- Robustness battery incl. a crisis/bear subperiod; multiple-testing control
  (SPA/Reality Check/Romano-Wolf); no "only/unique" claim without re-verifying
  the current results table.
- Frame the contribution for the venue: economic mechanism (JFE/RFS),
  policy/institutional relevance (JBF), methodology (JoE), forecasting+decision
  value (IJF/JoF), implementable practitioner payoff net of costs (JPM/FAJ).

### 6. COMPLIANCE gate (hard — cross-ref paper-workflow / publishing rules)
Before packaging, enforce the submission-compliance invariants (also in
`templates/submission-checklist.md`):
- **Authorship = Yi-Hao Lai (賴奕豪) ONLY.** No co-authors, no AI/agent listed
  as author (Elsevier/JFE/RFS forbid AI authorship anyway).
- **No "volpred" / "VolPred" / "AI" / "LLM" / "Claude" / "Codex" / agent / model
  branding** anywhere in the manuscript, metadata, acknowledgements, filenames,
  or code comments shipped in the replication package. Grep the .tex + bib +
  package. A generative-AI-use declaration (required by Elsevier/IJF/PBFJ if AI
  was used) is a SEPARATE titled section before references — handle per the
  journal rule, not by silently omitting.
- **No AI-style phrasing** in reader-facing prose (abstract/intro) — `anti-ai-style`.
- **Reproduce gate green**: replication package regenerates every table/figure
  (fixed seeds, README, pinned env, data-availability statement); satisfies the
  journal's data/code policy (JBF Option C / JFE Mendeley / RFS Dataverse /
  IJF CASCaD / FRL Option C / PBFJ).
- Figures vector / high-res & B&W-legible where required; refs verified (step 3).

### 7. Submission package
Assemble exactly what the portal needs per `references/<abbrev>.md`:
anonymized manuscript + separate title page, highlights file, cover letter
(`templates/cover-letter.md`), declarations (COI / funding / CRediT / AI-use),
replication package + data-availability statement, and the submission fee
note. Then email the boss a one-paragraph summary (target journal, fee, decision
horizon, open risks) per `feedback_email_on_major_decisions`. Submission itself
(portal upload, fee payment) is a boss decision — do not submit autonomously.

## References
- `references/journal-index.md` — fast picker table (read first).
- `references/{jbf,jfe,rfs,joe,frl,ijf,jpm,faj,pbfj,jof}.md` — per-journal profile + checklist.
- `templates/cover-letter.md`, `templates/submission-checklist.md`.
- Companion skills: `latex-academic-reviewer`, `citation-verifier`,
  `paper-review-cycle`, `paper-stage-classifier`, `finance-paper-quality`,
  `anti-ai-style`, `codex-cli`. Rules: `paper-workflow.md`, `publishing.md`,
  `experiments.md`.
