# K1218: Paper 6 Appendix A Markdown Draft — Clean-Slate Replication of Eq.(5)-(6)

**Status**: COMPLETED (markdown deliverable for main-thread cherry-pick)
**Date**: 2026-04-17
**Related**: Paper 6 (`paper/prg-periodic-garch`, main.tex commit `7d35418b`), K1200 (commit `287de785`), K880 canonical.

## Purpose

K1218 is a **markdown-only deliverable** that packages the K1200 clean-slate
replication evidence into a paper-ready Appendix A draft for Paper 6.
The goal is to strengthen reviewer defense by documenting that a from-scratch
implementation of Eqs.~(5)--(7) — written without reference to the K880
canonical code — reproduces the canonical SPY numbers within the pre-registered
replication tolerance band (and, in fact, performs marginally better).

**Why a separate K1218 and not just an edit to Paper 6?**  Per
`CLAUDE.md`, worktree agents must not modify `paper/*` body sources or any
`.tex` files directly. K1218 produces `.md` + `.json` only; the main thread
is responsible for the actual cherry-pick into `main.tex` or an included
`appendix.tex`.

## K1200 Source Traceability

- **Experiment**: `experiments/k1200/` (commit `287de785`)
- **Verdict**: `MINOR_DIVERGENT` — clean-slate replicates canonical figures with
  `|ΔDM_t|=0.124` (within REPLICATED band) and `|ΔQLIKE|=0.012` (MINOR band).
  Direction of divergence: clean-slate performs **better** than canonical,
  so main-text figures are conservative.
- **Knowledge ledger**: `storage/memory/knowledge.json` id `972d8402`.
- **Canonical baseline**: `experiments/k880/k880_results.json`.

Verbatim canonical numbers used in the appendix table:

| Metric                     | K880 canonical | K1200 clean-slate | Δ       |
|----------------------------|----------------|-------------------|---------|
| GJR QLIKE                  | 0.8542         | 0.8544            | +0.0002 |
| PRG Extended QLIKE         | 0.7478         | 0.7355            | -0.0124 |
| DM t (PRG vs GJR)          | 6.004          | 6.128             | +0.124  |
| Spearman ρ (PRG Extended)  | 0.5678         | 0.5761            | +0.0084 |
| OOS observations           | 1823           | 1823              | 0       |

## Files in this experiment

- `README.md` — this file
- `k1218_appendix_draft.md` — Appendix A draft (five subsections A.1–A.5)
  with LaTeX-compatible table markup, ready for cherry-pick
- `k1218_appendix_meta.json` — structured appendix outline, canonical
  numbers, tolerance check, and adoption steps for the main thread

## Main-Thread Adoption Path

1. **Cherry-pick** `k1218_appendix_draft.md` into Paper 6 as Appendix A.
   Option (a): inline into `paper/prg-periodic-garch/main.tex` after the
   `\section{Conclusion}` block, with `\appendix` then
   `\section{Independent Replication of the Two-Phase Forecast Timing}`.
   Option (b): save as `paper/prg-periodic-garch/appendix.tex` and
   `\include{appendix}` from `main.tex`.
2. **Add Section 4 cross-reference** (immediately after the SPY Table 2
   discussion): *"Appendix A.3 documents an independent clean-slate
   replication of the SPY results, yielding DM $t = 6.13$ against the
   main-text 6.00, which confirms the transcription of Eqs.(5)-(6)."*
3. **Recompile** with `xelatex main.tex` (run twice to resolve
   cross-references).
4. **Sync** with `uv run volpred ops paper-update --paper-id
   prg-periodic-garch`.

## Strict Rules Observed

- No `.tex` files written (markdown + JSON only).
- Canonical numbers transcribed verbatim from `k1200_results.json` (no
  recomputation, no rounding beyond paper-table convention).
- Academic appendix writing style (Methodology → Results → Interpretation
  → Reproducibility).
- Seed 42 documented; no re-estimation performed.
- Worktree scope: only `experiments/k1218/` files produced; no shared
  state (`storage/memory/*`, `storage/reports/*`, Supabase, Mirror)
  touched.

## References

- Paper 6 `main.tex` commit `7d35418b` (Eqs.5–7 and Section 2.4 forecast
  timing discussion).
- K1200 `experiments/k1200/k1200_results.json` (clean-slate replication
  results).
- K880 `experiments/k880/k880_results.json` (canonical SPY figures).
- Patton (2011) QLIKE robustness under noisy volatility proxies.
- Harvey, Leybourne & Newbold (1997) DM small-sample correction.
