# K1232 — Paper 9 (garch-x-vix) Citation + FEZ No-Source Fix Plan

**Type**: Planning / audit only (NOT .tex edit)
**Date**: 2026-04-17
**Seed**: 42 (not applicable — no stochastic computation)
**Sources**:
- `experiments/k1229/k1229_papers_audit.md` — Paper 9 section (action items)
- `paper/garch-x-vix/review_history/v1/citation_check_report.md` — 1 MAJOR + 5 MED + 4 MINOR detailed breakdown
- `paper/garch-x-vix/citation_check.md` — top-level summary (slightly stale; based on v0 that flagged Bayer & Hackethal; superseded by v1)
- `paper/garch-x-vix/reproducibility_audit/README.md` + `diff_report.md` — FEZ t=3.45 no-source analysis
- git commit `2bf5f2f6` — Paper 9 bib fix landing

## Purpose

Produce a main-thread execution guide that:
1. Maps every K1229-flagged Paper 9 issue (1 MAJOR fabricated/wrong-metadata citation + 5 MED citation issues + FEZ t=3.45 no-source) to a specific actionable fix.
2. Clarifies current state — most citation fixes already landed in commit `2bf5f2f6`; only FEZ/STOXX50E reproducibility remains genuinely open.
3. Gives the main thread a drop-in checklist for the Paper 9 revision response (either pre-emptive errata or a response to reviewer comments).

## Important finding (scope correction)

**The K1229 audit phrasing "1 MAJOR fabricated citation" conflates two separate check rounds.**

- **v0 citation_check.md** (paper/garch-x-vix/citation_check.md — 58 lines, dated "2026-04-10"): flagged `Bayer & Hackethal (2020)` as fabricated. But v1 (next section) found no `Bayer & Hackethal` citation anywhere in main.tex — it was already removed before v1 check. The v0 file appears to be leftover from an earlier tex version.
- **v1 citation_check_report.md** (paper/garch-x-vix/review_history/v1/ — 165 lines, dated "2026-04-13"): the authoritative one referenced by commit `2bf5f2f6`. Reports 1 MAJOR (`conrad2015` wrong journal/vol/pages — **not fabricated**, just wrong metadata) + 5 MEDIUM (missing DOIs) + 4 MINOR.

**Net effect**: There is **no currently-fabricated citation in Paper 9 main.tex**. MAJOR-1 is a metadata correction (Conrad & Loch 2015 is a real paper in *Journal of Applied Econometrics* 30(7):1090-1114; the paper incorrectly listed it as JBES 33(3)). This is serious (wrong journal = different paper entirely) but not fabrication.

## Current state of 2026-04-17 main.tex bibliography

All 6 substantive v1 findings (1 MAJOR + 5 MED) have already been applied per commit `2bf5f2f6` (2026-04-17):

- `conrad2015` — journal/volume/pages corrected + DOI added
- `bollerslev1986` — DOI added
- `engle1982` — DOI added
- `glosten1993` — DOI added
- `han2014` — DOI added
- `francq2019` — DOI added
- (bonus) `conrad2020` DOI, `kupiec1995` DOI — MINOR-1/4 also applied

No `Bayer & Hackethal` citation exists in main.tex. `wang2015` key is correctly used (no `wang2017` lingering).

## Remaining open items

1. **FEZ DM t=3.45 — NO SOURCE (HIGH RISK, reviewer-exposable)**
   - Table 6 line 526, also Abstract and Conclusion
   - No existing experiment produces t=3.45 for FEZ under A4f spec + OOS 2019-2026
   - Closest: K949 FEZ gives t=3.84 but uses MF-GJR log-exp spec + OOS 2016-2025 (wrong spec AND wrong period)
2. **STOXX50E DM t=3.64 — RELATED OOS MISMATCH (HIGH RISK)**
   - Table 6 line 525, abstract
   - Same root cause as FEZ — K949 different spec/period
3. **Main Table 4/Row 8 (A4n) t=3.45** — line 406 (`A4n (VIX^2, norm) & -8.350 & 3.45`) coincidentally same number as FEZ; this is a *different* t-stat (for main horse-race row 8, sourced from `compute_mcs_dm.py` → `mcs_dm_results.json`, **fully reproducible**). Must not conflate with FEZ.
4. Minor stylistic follow-ups (non-blocking): MINOR-2 (JBES `\&` vs "and"), MINOR-3 (`acerbi2014` URL) — skipped per commit `2bf5f2f6` note.

## Files in this experiment

- `README.md` — this file
- `k1232_fix_plan.md` — per-item execution plan with LaTeX diff suggestions, effort estimate, decision tree
- `k1232_fix_items.json` — structured per-item state (parseable by downstream tools)

## Main-thread execution sequence (summary)

1. Confirm current bib state (compile xelatex, check 27 cites with `natbib` warnings clean) — **already done in `2bf5f2f6`**.
2. **FEZ / STOXX50E fix (P1)**: Choose option (a) run dedicated A4f experiment OR (c) errata footnote. Recommendation: (a) — effort estimated 2 hours per reproducibility_audit, gives reviewer-safe response.
3. Re-run `compute_mcs_dm.py` or a new `k1232b_fez_stoxx50e.py` to produce verified t-stats; if t ≠ 3.45 / 3.64, update Table 6 and Abstract/Conclusion.
4. If (a) chosen: commit verified numbers, run `uv run volpred ops paper-update --paper-id garch-x-vix`.
5. Update `paper/garch-x-vix/reproducibility_audit/` to reflect FEZ now sourced.
6. Close Paper 9 replication-package NEEDS-FIX status.

## Do NOT

- Do NOT modify `paper/garch-x-vix/main.tex` from this worktree (CLAUDE.md rule: agent 不寫 body.tex).
- Do NOT run the FEZ experiment from this worktree (requires data access + is a new K — must be main-thread decision).
- Do NOT fabricate replacement citations. (N/A here — no fabricated citation to replace.)

## Success criteria

- [x] 7 items (1 MAJOR + 5 MED + 1 FEZ) × per-item plan entry
- [x] Scope-correction finding documented (1 MAJOR = metadata error, not fabrication; already fixed)
- [x] Action sequence with option (a)/(b)/(c) per open item
- [x] Effort estimate total
- [x] Structured JSON for downstream tooling
