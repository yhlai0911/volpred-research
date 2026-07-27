# Task: BTC-GAS negative-result paper — markdown → LaTeX (Elsevier elsarticle / JBF-IJF style)

**Model**: opus / high (per model_router, paper_body)
**Pool task**: `BTC_GAS_tex_conversion` (source_task_id)
**Worktree cwd**: `.claude/worktrees/dispatch-slot-1-2e78555e-btcgas` (write ONLY here)

## Goal
Convert the assembled markdown draft of the BTC GAS-t negative-result paper into a compiling
LaTeX manuscript using the Elsevier `elsarticle` document class (JBF / IJF submission style),
then compile it with `xelatex` to a PDF.

## Source material (read all first, in this worktree)
- `paper/btc-gas-negative/drafts/body_v1.md` — the full assembled body (~87 KB; authoritative prose)
- `paper/btc-gas-negative/drafts/v0_outline_abstract.md` — title, abstract, JEL/keywords, 3 contributions
- `paper/btc-gas-negative/drafts/v1_section1_introduction.md` … `v1_sections7-9_discussion.md` — per-section drafts (use body_v1.md as the merge-of-record; sections are for cross-check only)
- `paper/btc-gas-negative/README.md`, `experiments.md`, `data_sources.md` — provenance, numbers, data windows
- `paper/btc-gas-negative/review_history/` — prior review notes if present

## Reference template (DO NOT copy content — copy STRUCTURE/preamble only)
`paper/leverage-direction/` is a complete elsarticle build you can mirror:
- `main.tex` / `main_v_ijf.tex` — preamble, \documentclass[review]{elsarticle}, packages, \begin{document}, \input structure
- `body.tex`, `tables_main.tex` — how body + tables are split and \input
- how figures/tables/labels/\cite are wired
Match its package set and build conventions so `xelatex` succeeds the same way.

## What to produce (all under `paper/btc-gas-negative/`)
1. `main.tex` — elsarticle wrapper: documentclass, packages, title, author, abstract, keywords, JEL, \input{body}, bibliography.
2. `body.tex` — the converted body (sections 1–9). Convert markdown → LaTeX faithfully:
   - `#`/`##`/`###` → `\section`/`\subsection`/`\subsubsection`
   - markdown tables → `booktabs` `tabular` (or a `tables_*.tex` you \input); keep EVERY number exactly as in the markdown — do NOT recompute or round differently
   - inline stats (DM-HLN t, p-values, QLIKE %, n) → proper math mode; preserve exact values
   - bullet lists → `itemize`/`enumerate`
   - keep footnotes, emphasis, cross-references
3. `references.bib` + `\cite` wiring — extract every citation referenced in the prose into a BibTeX file with best-available metadata; wire `\citep/\citet`. If a reference's full metadata is unknown, include a minimal but syntactically valid entry (author, year, title, venue) rather than dropping the cite — flag such entries in a `% TODO verify` comment.
4. Compile: run `xelatex main.tex` (twice + `bibtex`/`biber` as needed for refs) until it produces `main.pdf` with no fatal errors. Resolve undefined refs/citations. Leave the build reproducible.
5. If `paper/btc-gas-negative/reproduce_report.json` exists, read it and confirm the numbers you carried into tables match it; note any discrepancy in `README.md`. If it does not exist, do not fabricate one.

## Compliance gate (HARD — this is a submission-track artifact)
- **Author = Yi-Hao Lai (Da-Yeh University, Department of Finance) ONLY.** No co-authors.
- **Zero mentions of volpred / VolPred / AI / LLM / Claude / autonomous agents / "hourly fire"** anywhere in the .tex or .bib. Strip any such provenance lines from the markdown when converting (they belong in README, not the manuscript).
- Research-honesty: carry numbers verbatim from the markdown/results; never invent statistics. This is a NEGATIVE-result paper — keep the "parity, not superiority" framing intact; do not upgrade any claim.

## Success criteria (the collecting fire will verify)
- `paper/btc-gas-negative/main.pdf` exists and is a non-trivial compiled PDF (all 9 sections present).
- `main.tex` + `body.tex` (+ any `tables_*.tex`, `references.bib`) present and self-consistent.
- No compliance-gate violation (grep the .tex/.bib for the forbidden terms → must be empty).
- Numbers in tables match body_v1.md.

## Deliverable / result artifact
`paper/btc-gas-negative/main.pdf` (relative to worktree cwd) — its existence is the success post-condition.

Write a short `paper/btc-gas-negative/CONVERSION_NOTES.md` summarizing: files created, xelatex build command, any citations left as `% TODO verify`, any number discrepancies vs reproduce_report.json.

Do NOT touch feed.json, supabase, or anything outside this worktree. Do NOT git commit — the collecting fire merges the worktree.
