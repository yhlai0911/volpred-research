# K1229: Papers 5/7/8/9/10 + vt-crowding-abm Current-State Audit

**Date**: 2026-04-17
**Type**: Read-only audit (no new code executed, no recomputation)
**Seed**: 42 (N/A; recorded per project rule)
**Scope**: 5 paper folders that were NOT the session's primary focus on 2026-04-17.

## Motivation

Session 2026-04-17 focused on Papers 1/2/3/4/6 + new BTC GAS paper (K1214/K1228). The remaining paper folders — `volatility-absorption` (Paper 8), `vt-crowding-abm` (Paper 5), `vt-insurance-cost` (Paper 7), `garch-x-vix` (Paper 9), and `crypto-fear-channel` (Paper 10) — did not receive explicit main-thread attention. Main thread needs a current-state snapshot before planning next-session priorities: is each submission-ready? does any have pending action items from earlier in the day?

## Output files

- `k1229_papers_audit.md` — 5 per-paper brief sections, summary table, cross-cutting observations, prioritised main-thread action list.
- `k1229_paper_audit.json` — Structured metadata (5 papers × folder / readiness / experiments / pending actions / priority).

## Cross-reference

| Paper | Folder | Priority | Readiness | Top action |
|-------|--------|----------|-----------|-----------|
| 5 | vt-crowding-abm | P4 | ready | DIV-2 threshold label cleanup |
| 7 | vt-insurance-cost | P3 | ready | 3 tex fixes + K860 decision |
| 8 | volatility-absorption | **P2** | draft | Reconstruct K716–K722 .py or paper-guide (a)/(b)/(c) |
| 9 | garch-x-vix | P3 | submitted | Citations 1 MAJOR + 5 MED + 2 MINOR; FEZ no-source |
| 10 | crypto-fear-channel | P4 | kickoff | Draft §2–§9; build self-contained package |

## Method

1. Read each folder's directory listing via `ls`.
2. Read each `README.md` (paper folder) and `reproducibility_audit/README.md` (when present).
3. Read each `main.tex` / `body_v0_intro.tex` first 50 lines for title + abstract.
4. `git log --oneline` scoped to each paper folder for recent commit history.
5. Cross-checked `research_program.md` for references to any of the five papers.
6. `grep` for `multistart` / `K1216c` references (none found; confirmed N/A for these 5 papers except spot-check recommendation for Paper 9).

## Adoption

Main thread should:

1. Review `k1229_papers_audit.md` top-to-bottom.
2. Decide P2 Paper 8 rescue path: (a) reconstruct scripts / (b) revise body / (c) document errata.
3. Slot P3 items (Paper 7 polish + Paper 9 revision prep) into near-term task queue.
4. Queue P4 items (Paper 5 DIV-2 label, Paper 10 body drafting) for later sessions.
5. Housekeeping: align numbering across audit READMEs.

## Related experiments / prior audits

- Paper 5: `k827v3_abm_fixed_liquidity.py` + audit in `paper/vt-crowding-abm/reproducibility_audit/` (97.5% match, 2026-04-17).
- Paper 7: K811v2 + audit in `paper/vt-insurance-cost/reproducibility_audit/` (96% match, 2026-04-17).
- Paper 8: K716–K722 (scripts missing), K741, K897, K903, K904; older `reproduce_report.json` at 50.7%.
- Paper 9: K889/K988/K989/K1023/K1045 + full audit in `paper/garch-x-vix/reproducibility_audit/` (85% match, 2026-04-17).
- Paper 10: K639, K746b, K1025 — numbers to migrate into body once drafting resumes.

## Limits

- No compile attempts; no new code runs; no recomputation of paper numbers.
- Git log scope limited to the 5 target folders.
- Paper 10 PDF not yet compiled.

## Success criteria (met)

- 5 papers × brief audit section each: ✅
- Summary table: ✅
- Cross-cutting observations: ✅
- Main-thread action list prioritised: ✅
