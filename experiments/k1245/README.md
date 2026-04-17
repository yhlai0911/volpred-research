# K1245: Paper 9 R2 Table 6 Footnote LaTeX Draft

**Status**: COMPLETE — LaTeX footnote text ready for main-thread cherry-pick
**Date**: 2026-04-18
**Type**: Documentation / draft artifact (no new computation)

## Purpose

K1235b (commit `1d92d256`, DECISIVE) confirmed that Paper 9 Table 6 values for
FEZ ($t = 3.45$) and STOXX50E ($t = 3.64$) are reproducible within Harvey
(1997) $\pm 0.5$ tolerance under the A4f specification declared in Table 2 of
`paper/garch-x-vix/main.tex`. Replicated $t_{\text{Harvey}}$ are $3.11$ (FEZ,
$p = 1.87\!\times\!10^{-3}$) and $3.92$ (STOXX50E, $p = 8.75\!\times\!10^{-5}$).
Both above the $|t| > 3.0$ Harvey-significance threshold. Paper 9 R2 review
resolution: **path (b)** (spec-clarification footnote) — errata **not**
required.

K1245 produces the exact LaTeX footnote text ready for main-thread insertion
into `paper/garch-x-vix/main.tex` Table 6 area. Per CLAUDE.md rule, this agent
does **not** edit `body.tex` / `main.tex` — only drafts `.md` / `.json` with
embedded LaTeX code blocks for main-thread cherry-pick.

## Source experiments

| K      | Role                                                      | Verdict    |
|--------|-----------------------------------------------------------|------------|
| K1232  | Reproducibility audit — flagged "no-source" FEZ/STOXX50E. | Audit      |
| K1235  | log-exp K949 spec rerun.                                  | MISMATCH   |
| K1235b | A4f spec rerun (paper-declared spec).                     | **DECISIVE — BORDERLINE, within ±0.5 Harvey** |

## Deliverables

| File                     | Purpose                                                     |
|--------------------------|-------------------------------------------------------------|
| `k1245_footnote.md`      | Primary + short + `tablenotes \item` LaTeX variants + bibtex + 8-step apply sequence |
| `k1245_footnote.json`    | Structured LaTeX text + bib entry (machine-readable)        |
| `README.md`              | This file                                                   |

## Three footnote variants provided

1. **Primary (full)** — verbose `\footnote{...}`; full spec description, Harvey tolerance statement, OOS endpoint explanation, replication-package reference. Best when reviewer wants explicit methodological justification.
2. **Short** — concise `\footnote{...}`; ~3 sentences, keeps spec + replication numbers + threshold statement. Best when page budget is tight.
3. **`tablenotes \item`** — drops into the existing `\begin{tablenotes}` block at line 531 of `main.tex`; minimal diff, no new `\footnote` / `\footnotemark` pair. **Recommended** unless editor specifically wants a numbered footnote.

## Main-thread application (summary, full steps in `k1245_footnote.md`)

1. Open `paper/garch-x-vix/main.tex`, navigate to Table 6.
2. Pick variant (recommend `tablenotes \item` for minimal diff).
3. Optional: add bibtex entry to `references.bib` if citing K1235b formally.
4. Compile: `xelatex main.tex` x2.
5. Verify PDF rendering and cross-refs.
6. Sync: `uv run volpred ops paper-update --paper-id garch-x-vix`.
7. Commit: `Paper 9 R2 footnote: K1235b A4f spec replication cited for FEZ+STOXX50E`.

## Constraints honored

- [x] No `.tex` files written (only `.md` with LaTeX in fenced code blocks + `.json`).
- [x] Verbatim K1235b numbers (FEZ $t = 3.11$, $p = 1.87\!\times\!10^{-3}$; STOXX50E $t = 3.92$, $p = 8.75\!\times\!10^{-5}$).
- [x] LaTeX syntax verified (math-mode escapes, no unescaped special chars, `threeparttable` compatibility noted).
- [x] Deterministic draft (no stochastic content; seed 42 documented for downstream reference).
- [x] Files scoped to `experiments/k1245/` only.

## Decision tree reminder (from K1235b)

K1235b result per ticker:
- FEZ: $\lvert\text{diff}\rvert = 0.339$ → BORDERLINE (within $\pm 0.5$).
- STOXX50E: $\lvert\text{diff}\rvert = 0.283$ → BORDERLINE (within $\pm 0.5$).

Both → **path (b)**: spec-clarification footnote only. Errata not required.

## Next (main-thread)

- [ ] Main thread applies one of the three footnote variants (recommend `tablenotes \item`).
- [ ] Main thread compiles and syncs via `paper-update`.
- [ ] Main thread updates `storage/memory/knowledge.json` to mark Paper 9 R2 FEZ+STOXX50E concern as **resolved** via K1235b/K1245 trail.
- [ ] Main thread may optionally file a thinking-journal entry linking K1232 → K1235 → K1235b → K1245 for audit traceability.
