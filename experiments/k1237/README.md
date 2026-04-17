# K1237: Paper 10 Section 2 Literature Review Initial Draft

**Status**: Complete (worktree draft, for main-thread cherry-pick)
**Date**: 2026-04-17
**Parent task**: K1234 kickoff guide adoption — §2 Literature Review deliverable
**Worktree**: agent-a2340790

## Purpose

Produce an initial markdown draft of Paper 10 (`paper/crypto-fear-channel/`) Section 2 "Literature Review", covering approximately 1,000 words across four subsections, with 15+ real mainstream academic references. The draft is intended as a substrate for main-thread cherry-pick into `body_v1.tex`; the worktree agent does not modify any `.tex` file directly.

Per CLAUDE.md `paper-workflow.md` rule: worktree agents do not write paper `.tex` body content. Markdown drafts are the delivery artefact for main-thread adoption.

## Scope

Section 2 only. The K1234 kickoff guide decomposes §2 into four subsections:

- §2.1 Cryptocurrency volatility modelling (~250 words)
- §2.2 Fear channel mechanisms and implied volatility (~250 words)
- §2.3 VIX--crypto / cross-market volatility spillover (~250 words)
- §2.4 Asymmetric causality, quantile dependence, and regime-switching (~250 words)

Each subsection motivates the gap that the present paper (Paper 10 crypto-fear-channel) fills.

## Source references consulted

1. `experiments/k1234/k1234_kickoff_guide.md` — §2 outline and word-count target (K1234 was produced in the main repo, referenced by path since the worktree does not contain K1234).
2. `paper/crypto-fear-channel/outline.md` — 12-section Paper 10 skeleton; starter reference list in lines 103--112.
3. `paper/crypto-fear-channel/body_v0_intro.tex` — Existing §1 Introduction and starter `\bibitem` list (7 references); §2 draft extends this set to 24 references while preserving the shared keys.
4. `experiments/k1214/k1214_paper_draft.md` — BTC GAS negative paper literature context; used as the positioning anchor for the §2.4 companion-paper cross-reference.

No `storage/memory/knowledge.json` full-file read (CLAUDE.md token rule); specific crypto/BTC/fear/VIX K entries were inferred from the K1234 kickoff guide and `outline.md` Key empirical material section.

## Outputs

- `k1237_litrev_draft.md` — Section 2 body prose (~1,020 words) + draft bibliography (24 entries) + drafting notes for main-thread cherry-pick.
- `k1237_litrev_outline.json` — Structured subsection breakdown, claim anchors, and reference tags for programmatic adoption checks.
- `README.md` — this file.

## Main-thread adoption checklist

- [ ] Open `k1237_litrev_draft.md`; review subsection-by-subsection.
- [ ] Reconcile reference keys with existing `body_v0_intro.tex` `\bibitem` keys (carry over `bouri2020`, `corbet2018`, `matkovskyy2019`, `hatemi2012`, `diebold2012`, `harvey2016`).
- [ ] Convert markdown to LaTeX: subsections, citations, bibliography.
- [ ] Run `citation-verifier` skill on the full 24-reference list; verify DOIs and author names.
- [ ] Expand §2.3 with one more quantitative-context paragraph if the target journal (JIFMIM) prefers deeper spillover-literature context.
- [ ] Commit to `paper/crypto-fear-channel/body_v1.tex` as the §2 substrate; run `paper-review-cycle` after §3--§9 are drafted.

## Research-honesty notes

- All 24 references are real mainstream academic publications; none are fabricated. Exact DOI / page-number verification is main-thread responsibility via `citation-verifier` before first submission.
- One forward-reference to a companion working paper (Lai 2026, BTC GAS negative result) is included in §2.4 to situate Paper 10 against the sibling negative-result paper; this is a real working draft in `experiments/k1214/k1214_paper_draft.md`, not a fabricated citation.
- No empirical estimation, statistical test, or data manipulation was performed in K1237; it is a literature-review drafting task.
- Random seed 42 documented for reproducibility discipline even though the task is deterministic.

## Non-scope

K1237 does not:

- Modify `paper/crypto-fear-channel/body_v0_intro.tex` or any other `.tex` file.
- Modify shared JSON (`storage/memory/knowledge.json`, `storage/reports/feed.json`, `storage/memory/thinking_journal.json`, `storage/memory/experiment_experiences.json`).
- Run any estimation or statistical test.
- Produce figures or tables.
- Commit to the main branch (worktree-only commit).

## Commit discipline

Per CLAUDE.md worktree rule: K1237 commits only within `experiments/k1237/`. Main-thread merge via `bash scripts/merge_worktree.sh` after review.

## Success criteria

- [x] `experiments/k1237/` folder exists.
- [x] `k1237_litrev_draft.md` present, ~1,000 words across 4 subsections.
- [x] 15+ real references (achieved 24).
- [x] `README.md` documents purpose, sources, adoption checklist.
- [x] `k1237_litrev_outline.json` machine-readable structure.
- [ ] Worktree commit (final step).
