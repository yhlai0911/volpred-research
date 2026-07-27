# BTC-GAS Negative-Result Paper — Markdown → LaTeX Conversion Notes

**Date**: 2026-07-27
**Task**: `BTC_GAS_tex_conversion` — convert assembled markdown draft to a compiling
Elsevier `elsarticle` (JBF/IJF) manuscript.

## Files created (all under `paper/btc-gas-negative/`)

| File | Role |
|------|------|
| `main.tex` | `elsarticle` wrapper: `\documentclass[review,authoryear,12pt]{elsarticle}`, title, single author (Yi-Hao Lai), abstract, keywords + JEL, `\input{body}`, BibTeX bibliography. |
| `body.tex` | Full Sections 1–9, converted from `drafts/body_v1.md` (merge-of-record). Inputs `tables_main.tex` inside Section 4. |
| `tables_main.tex` | Formal Table (Cross-Period DM-HLN) in `booktabs`/`threeparttable`. |
| `references.bib` | 24 BibTeX entries, all cited; author-date via `apalike`. |
| `figures/fig1_qlike_by_period.png` | copied from `experiments/k1133b/k1133b_qlike_5model.png` |
| `figures/fig2_dm_heatmap.png` | copied from `experiments/k1133b/k1133b_dm_heatmap.png` |
| `figures/fig3_ms_state_prob.png` | copied from `experiments/k1133b/k1133b_ms_state_prob.png` |
| `main.pdf` | Compiled output — **46 pages**, all 9 sections, 2 tables, 3 figures, 24 references. |

## Build command (reproducible)

```bash
export PATH="/Library/TeX/texbin:$PATH"   # TeX Live 2026; xelatex not on non-interactive PATH by default
cd paper/btc-gas-negative
xelatex -interaction=nonstopmode main.tex
bibtex  main
xelatex -interaction=nonstopmode main.tex
xelatex -interaction=nonstopmode main.tex
```

Final pass: `rc=0`, no undefined references, no undefined citations. bibtex emitted one
benign warning (`blasques2014`: "number but no volume" — it is a discussion-paper entry).

## Table numbering note

LaTeX auto-numbers two tables: **Table 1** = the five-model specification grid (inline in
Section 3.3); **Table 2** = the headline Cross-Period DM-HLN table (`tables_main.tex`,
`\label{tab:dmhln}`). Body cross-references resolve correctly to these numbers. The source
markdown called the DM-HLN table "Table 1"; the shift to Table 2 is purely cosmetic
auto-numbering, no content change.

## Compliance gate (verified CLEAN)

`grep -rniE "volpred|claude|codex|autonomous agent|hourly fire|LLM|\bAI\b|anthropic|gpt|gemini|main thread"`
over `main.tex body.tex tables_main.tex references.bib` → **empty**.

Provenance stripped during conversion (belongs in README, not the manuscript):
- All "Codex" review mentions → neutral phrasing ("an independent code review").
  Affected: §3.5 lookahead audit, §8 implemented safeguards.
- Internal repo path `experiments/k1133b/README.md` (§3.4) → "the archived implementation notes".
- Internal log reference `(ms_fit_log, K1133b)` (§6) → "the archived MLE refit log".
- Internal experiment codenames (K1129/K1133b/K1213 methodology rule) → generic phrasing
  ("our companion cross-asset experiment", "a standing methodological rule", "a pre-registered
  methodology note dated 2026-04-15"). No numeric or claim content changed.
- The v0-outline metadata header of `body_v1.md` (author/status/"hourly-08 fire"/next-subtasks)
  was **not** carried into the manuscript; only the prose Sections 1–9 were converted.
- Author = **Yi-Hao Lai (Da-Yeh University, Department of Finance) only**. No co-authors.

## Research-honesty / framing preserved

- All numbers carried **verbatim** from `drafts/body_v1.md` / the Key Numbers table
  (single source of truth). Spot-checked in the compiled PDF: QLIKE 2.1904 / 1.9926 / 2.0402,
  DM-HLN −4.67 / −3.36 / −1.90 / −0.06 / +2.67 / +5.97 / +0.28, 9.92%, n=1,441/345/100,
  p=0.058/0.008.
- "Parity, not superiority" framing kept intact; no claim upgraded. §8 keeps the explicit
  distinction between **implemented (archived) safeguards** and **planned (not-yet-run)** robustness.
- §7.1 keeps the honest caveat that period-specific kurtosis estimates are not yet landed in a
  results artifact; §3.1 keeps the pending-snapshot-CSV caveat.

## Citations left as `% TODO verify`

Best-available metadata used; flagged in `references.bib` for pre-submission verification:
- `blasques2014` — Tinbergen Institute discussion-paper number; volume/pages not confirmed.
- `blasques2018` — text cites "Blasques et al. (2018)"; the closest located reference is the
  2016 IJF paper. Exact intended 2018 reference to be confirmed.
- `catania2017` — SSRN working paper; DOI/number to be confirmed.
- `hansen2003` — venue (Oxford Bulletin of Economics and Statistics) and volume/pages to be confirmed.

All other entries carry DOIs and standard bibliographic fields.

## reproduce_report.json

**Does not exist** in `paper/btc-gas-negative/` (checked). Not fabricated. Per README, a
paper-local pinned snapshot CSV + `reproduce.py` + reproduce gate are still pending; the numbers
in the tables trace to `experiments/k1133b/k1133b_results.json` and the Key Numbers table in
`drafts/v0_outline_abstract.md`. No discrepancy could be checked against a reproduce report
because none exists yet. This remains a pre-submission blocker recorded in README.

## Unresolved / handed to downstream

- Snapshot CSV + `reproduce.py` + green reproduce gate (submission hard requirement) — not part
  of this conversion task.
- Planned robustness battery (§8 items i–v) not yet run.
- Appendix A (alternative innovation distributions) and Appendix B (ETH/BNB replication) are
  referenced in prose but the appendices themselves are not written (consistent with §8 marking
  ETH/BNB as planned). Kept as literal text mentions, not `\ref`, so no undefined references.
- The 4 `% TODO verify` citations above.
