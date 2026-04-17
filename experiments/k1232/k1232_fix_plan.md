# Paper 9 (garch-x-vix) Citation + FEZ Fix Plan

**Paper**: `paper/garch-x-vix/main.tex` — *Multiplicative GARCH-X with VIX*
**Status**: Submitted (under review at JEF / IJoF)
**Replication-package status (per K1229 + reproducibility_audit)**: NEEDS-FIX
**Plan produced**: K1232, 2026-04-17
**Authoritative input**: `paper/garch-x-vix/review_history/v1/citation_check_report.md`, `paper/garch-x-vix/reproducibility_audit/` (README + diff_report), git commit `2bf5f2f6`.

---

## Executive Summary

| Bucket | K1229 claimed | v1 check found | Already fixed (commit `2bf5f2f6`) | Still open |
|---|---|---|---|---|
| MAJOR (citation) | 1 fabricated | 1 wrong-metadata (not fabrication) | ✅ yes | 0 |
| MEDIUM (citation) | 5 | 5 missing DOI | ✅ yes (all 5) | 0 |
| MINOR (citation) | — | 4 | ✅ 2 of 4 (conrad2020, kupiec1995) | 2 optional |
| REPRO — FEZ t=3.45 | 1 no-source | 1 confirmed | ❌ no | **1 P1** |
| REPRO — STOXX50E t=3.64 | (related) | 1 OOS-mismatch | ❌ no | 1 P1 |

**Net remaining action items**: 1 P1 (FEZ/STOXX50E package — same root cause, handle together). The "citation fix plan" is essentially already executed; documenting it here for audit traceability and to close the K1229 pending-items loop.

---

## Item #1 — MAJOR (citation): `conrad2015`

### Original issue (v1 citation_check_report.md §MAJOR-1)

- **Claimed in paper (pre-fix)**: Conrad, C. and Loch, K. (2015). Anticipating long-term stock market volatility. *Journal of Business and Economic Statistics*, 33(3):338--358.
- **Actual publication**: Conrad, C., & Loch, K. (2015). Anticipating long-term stock market volatility. *Journal of Applied Econometrics*, 30(7):1090–1114. DOI: `10.1002/jae.2404`.
- **Type**: Wrong journal + wrong volume + wrong issue + wrong page range. Not a fabrication — the paper exists, its bibliographic metadata was wrong.
- **Content claim check (v1 §Content-Fidelity)**: In-text claim at lines 73, 85, 99, 808 ("forward-looking variables improve long-horizon volatility forecasts; consumer confidence and financial conditions indices") is faithful to the **real** Conrad & Loch (2015, JAE). Only the bibliographic record needed correction.

### Fix status: ✅ APPLIED in commit `2bf5f2f6` (2026-04-17)

Main.tex lines 935-939 (post-fix, confirmed by Read):

```latex
\bibitem[Conrad and Loch, 2015]{conrad2015}
Conrad, C. and Loch, K. (2015).
\newblock Anticipating long-term stock market volatility.
\newblock {\em Journal of Applied Econometrics}, 30(7):1090--1114.
\newblock \url{https://doi.org/10.1002/jae.2404}
```

No further action. Cite key `conrad2015` retained (no body-side changes needed since natbib resolves via `\bibitem[...]` label).

### Recommendation

No action. Verified correct as of 2026-04-17.

---

## Item #2 — MED-1: `bollerslev1986` — missing DOI

- **Issue**: APA 7 requires DOI when available.
- **Fix**: Add `\url{https://doi.org/10.1016/0304-4076(86)90063-1}` as a third `\newblock`.
- **Status**: ✅ APPLIED (commit `2bf5f2f6`, main.tex line 891).
- **Recommendation**: No action.

## Item #3 — MED-2: `engle1982` — missing DOI

- **Fix DOI**: `10.2307/1912773` (Econometrica, JSTOR).
- **Status**: ✅ APPLIED (main.tex line 902).
- **Recommendation**: No action.

## Item #4 — MED-3: `glosten1993` — missing DOI

- **Fix DOI**: `10.1111/j.1540-6261.1993.tb05128.x` (J. Finance via Wiley).
- **Status**: ✅ APPLIED (main.tex line 972).
- **Recommendation**: No action.

## Item #5 — MED-4: `han2014` — missing DOI + narrative attribution

- **Fix DOI**: `10.1080/07350015.2014.897954` (JBES via Taylor & Francis).
- **Narrative**: v1 also flagged line 107 "Han (2014) developed asymptotic theory…" — should read "Han and Kristensen (2014)" for clarity. Commit `2bf5f2f6` commit message says this was skipped because natbib via `\citet{han2014}` already renders as "Han and Kristensen (2014)". **Verified by Grep** — no raw "Han (2014)" string in main.tex today; natbib rendering via `\bibitem[Han and Kristensen, 2014]{han2014}` is correct.
- **Status**: ✅ APPLIED (DOI at main.tex line 978; narrative handled via natbib label).
- **Recommendation**: No action.

## Item #6 — MED-5: `francq2019` — missing DOI

- **Fix DOI**: `10.1017/S0266466617000512` (Econometric Theory via Cambridge).
- **Status**: ✅ APPLIED (main.tex line 946).
- **Recommendation**: No action.

---

## Item #7 — FEZ DM t=3.45 — NO SOURCE (HIGH RISK, P1 — REAL OPEN ITEM)

### Where it appears in the paper

From `Grep "FEZ" main.tex`:

| Location | Line | Context |
|---|---|---|
| Table 6 (Cross-Asset) | 526 | `FEZ & 0.44 & 1.422 & 1.371 & 3.45 & \textbf{Yes}` |
| Table 6 footnote | 533 | "STOXX50E and FEZ use US VIX (not VSTOXX)…" |
| Conclusion §6 | 858 | "A4f with US VIX achieves Harvey significance for five of seven tested markets—SPY, QQQ, EURO STOXX 50, FEZ, and GLD" |
| (Abstract) | — | also claims five-of-seven |

Note: Main horse-race Table 3 row 8 `A4n (VIX^2, norm)` also shows t=3.45 at line 406. That number is **different** — it is the main-spec DM t against GJR, sourced from `compute_mcs_dm.py` → `mcs_dm_results.json` (fully reproducible). The FEZ t=3.45 in Table 6 is a **coincidence of the same value**; do not conflate in any fix.

### Issue (reproducibility_audit/diff_report.md §D2)

- **Claim**: FEZ DM t=3.45 under A4f spec, OOS 2019-2026, Harvey significant.
- **Problem**: No experiment produces this exact number.
  - K949 runs FEZ but uses **MF-GJR log-exp spec + OOS 2016-2025** → gives t=3.84 (not 3.45, and wrong spec + wrong period).
  - K994 does not include FEZ.
  - Audit searched all `experiments/kXXX_results.json` and found no cell matching "FEZ + 3.45".
- **Risk level**: HIGH — reviewer can directly ask "show us the FEZ script"; currently no answer.

### Context claim the FEZ t supports

The claim is: "US VIX serves as a *global* fear factor — multiplicative GARCH-X with US VIX produces Harvey-significant improvement over GJR on Eurozone equity (EURO STOXX 50 via FEZ ETF), even though VSTOXX would be the natural local implied-vol measure." This is a **substantive contribution** of the paper (not just a filler stat). Cannot simply drop the claim without weakening the five-of-seven global-factor narrative.

### Fix options (per paper-guide (a)(b)(c))

- **(a) Run dedicated K experiment**: Create `experiments/k1232b/` (or similar new K) with A4f spec on FEZ, OOS 2019-2026 exactly. Record `fez_dm_t` in `k1232b_results.json`. Update Table 6 with verified number (may or may not equal 3.45 — must use whatever script produces, per research-honesty rule).
- **(b) Rewrite claim**: Drop FEZ from five-of-seven narrative, re-phrase as four-of-six (removing FEZ, keeping STOXX50E only if that is independently sourced — which it is NOT; see Item #8 below, same root cause). Weakens the global-factor contribution materially.
- **(c) Errata footnote**: Add footnote to Table 6 and Conclusion: "FEZ row pending errata — reproducibility script under construction (see Replication Notes)." Acceptable as a stopgap but reviewers may still flag.

### Recommendation

**(a) + a minor-data-collection note.** Run dedicated A4f on FEZ + STOXX50E together (single K covers both — same code, two tickers). Effort per `reproducibility_audit/README.md` = 2 hours. If new numbers match 3.45 / 3.64 within rounding tolerance → paper unchanged. If materially different → update Table 6 + Abstract + Conclusion numbers (research-honesty rule).

**Fallback**: If data-access friction (yfinance rate limit, FEZ pre-2019 data gap) blocks (a), fall back to (c) with a specific commit-dated errata note, *not* (b) — rewriting the narrative should be last resort.

### LaTeX changes required (conditional on option (a) outcome)

- If verified t ≈ 3.45 (within ±0.05): **no tex change**, just commit new experiment.
- If verified t differs: update Table 6 line 526:
  ```latex
  FEZ & 0.44 & 1.422 & 1.371 & <NEW_T> & \textbf{<Yes/No>} \\
  ```
  And update Abstract + Conclusion "five of seven" language if significance status flips.

---

## Item #8 — STOXX50E DM t=3.64 — related OOS mismatch (HIGH RISK, P1)

### Where

Table 6 line 525: `STOXX50E & 0.44 & 1.565 & 1.513 & 3.64 & \textbf{Yes}`. Also Abstract, Conclusion.

### Issue (reproducibility_audit §D1)

K949 STOXX50E uses different spec (MF-GJR log-exp) and different OOS (2016-2025). Produces t≈3.842 for FEZ under that spec; K949 doesn't have a separate STOXX50E row but the K1229 audit notes STOXX50E suffers the same root-cause mismatch as FEZ.

### Recommendation

**Bundle with Item #7 fix** — single new K experiment runs A4f on both FEZ and STOXX50E over identical OOS 2019-2026 with US VIX as multiplicative. Outputs verified t-stats for both rows of Table 6.

---

## Summary Action Table

| # | Issue | Type | Current state | Fix option | Effort | Priority |
|---|---|---|---|---|---|---|
| 1 | MAJOR: conrad2015 wrong journal | Citation metadata | ✅ Fixed (commit 2bf5f2f6) | — | 0 | — |
| 2 | MED: bollerslev1986 DOI | Citation DOI | ✅ Fixed | — | 0 | — |
| 3 | MED: engle1982 DOI | Citation DOI | ✅ Fixed | — | 0 | — |
| 4 | MED: glosten1993 DOI | Citation DOI | ✅ Fixed | — | 0 | — |
| 5 | MED: han2014 DOI + narrative | Citation DOI | ✅ Fixed | — | 0 | — |
| 6 | MED: francq2019 DOI | Citation DOI | ✅ Fixed | — | 0 | — |
| 7 | FEZ t=3.45 no-source | Reproducibility | ❌ OPEN | (a) → (c) fallback | 2h | **P1** |
| 8 | STOXX50E t=3.64 OOS mismatch | Reproducibility | ❌ OPEN | Bundle with #7 | 0h (in #7) | P1 |

---

## Aggregate Fix Sequence (main thread)

1. **Confirm citations clean** — xelatex compile; should see 27 bibitems, 0 undefined-citation warnings. (Already done in commit `2bf5f2f6`; paper-update also ran successfully.)
2. **FEZ + STOXX50E package (P1, ~2 hours)**:
   - Create `experiments/k1232b_fez_stoxx50e/` with `k1232b.py`:
     - Download FEZ + `^STOXX50E` via yfinance 2005-01-01 to 2026-04-17
     - Fit A4f spec: `\sigma_t^2 = \tau_t \cdot g_t` with `\tau_t = \theta_0 + \theta_1 \mathrm{VIX}_{t-1}^2` and GJR short-run; use US VIX (^VIX) as exogenous (per paper footnote §Table 6).
     - Rolling OOS 2019-01-01 to 2026-04-17 with refit_freq matching main spec (check K988/K988b).
     - Compute DM-Harvey t-stat of A4f-QLIKE vs GJR-QLIKE, Newey-West lag = h-1.
     - Save `k1232b_fez_stoxx50e_results.json` with both tickers + both t-stats + QLIKE comparisons.
   - Codex review + cross-check against Harvey 2016 methodology.
   - **Seed = 42** for any train/test split; NO bootstrap needed for single DM t-stat.
3. **Compare numbers**:
   - If verified t(FEZ) ∈ [3.40, 3.50] **and** t(STOXX50E) ∈ [3.60, 3.70] → numbers stand; only update reproducibility_audit README to mark D1/D2 as resolved.
   - If verified t differs materially → update main.tex Table 6 rows 525-526, and Abstract/Conclusion sentences that depend on "five of seven" Harvey-significance language.
4. **LaTeX recompile + paper-update** — per paper-guide standard flow: `xelatex main.tex` → `uv run volpred ops paper-update --paper-id garch-x-vix`.
5. **Update reproducibility_audit** — README + diff_report marking D1 & D2 as RESOLVED with K1232b as source.
6. **Close loop in K1229 audit** — update `experiments/k1229/k1229_papers_audit.md` Paper 9 section from "NEEDS-FIX" to "audit-clean" once K1232b lands.

---

## Estimated Effort

| Phase | Effort |
|---|---|
| Citation items (1 MAJOR + 5 MED) | **0 h (already done)** |
| FEZ + STOXX50E K1232b experiment | 2 h (per reproducibility_audit README.md estimate) |
| Codex review | 20 min |
| Tex + paper-update (only if numbers change) | 20 min |
| Audit README update | 10 min |
| **Total remaining work** | **~3 hours** |

---

## Do / Do-Not

### Do
- Run K1232b from the main thread (has write access to `storage/` for artifacts, can call `paper-update` CLI).
- Fix `seed=42` in any stochastic path.
- Save BOTH FEZ and STOXX50E t-stats to same results JSON.
- Compare new numbers to paper's 3.45 / 3.64 before deciding tex-edit vs no-change.

### Do Not
- Do NOT modify `main.tex` from this K1232 worktree (CLAUDE.md rule).
- Do NOT fabricate citations — none of the 6 citation items needed fabrication (all were real papers with real fixes; MAJOR-1 was a metadata correction to the *correct* real journal).
- Do NOT adjust seed until t-stat matches paper (research-honesty rule — forbidden).
- Do NOT hardcode the paper's t=3.45 / 3.64 into the script's expected output.
- Do NOT skip Codex review of K1232b before landing (standard experiments-after rule).

---

## Pre-submission Gate for Paper 9 Revision

Before `paper-update` on any Paper 9 revision that claims replication-package readiness:

- [ ] 27 bib entries compile clean with xelatex (0 undefined cites, 0 orphans)
- [ ] `citation_check_report v2` re-run shows 0 MAJOR, ≤3 MED (expected: 0 MED after `2bf5f2f6`)
- [ ] `experiments/k1232b/` exists with A4f FEZ+STOXX50E results and Codex-reviewed
- [ ] `reproducibility_audit/diff_report.md` shows D1 and D2 RESOLVED
- [ ] `paper/garch-x-vix/experiments.md` registers K1232b
- [ ] `xelatex main.tex` compiles 36 pages (or matches current page count after any edits)
- [ ] `uv run volpred ops paper-update --paper-id garch-x-vix` syncs Supabase + Mirror

---

## References

- `experiments/k1229/k1229_papers_audit.md` — original Paper 9 pending-items list
- `paper/garch-x-vix/review_history/v1/citation_check_report.md` — v1 detailed citation check
- `paper/garch-x-vix/citation_check.md` — v0 top-level (stale, see scope correction in README)
- `paper/garch-x-vix/reproducibility_audit/README.md` + `diff_report.md` — FEZ/STOXX50E analysis
- `paper/garch-x-vix/main.tex` lines 525-533 (Table 6), 406 (Table 3 row 8, unrelated t=3.45 coincidence), 858 (Conclusion), 880-1020 (bibliography)
- git commits: `cb81a798` (v1 check), `2bf5f2f6` (bib fix), `4e84d37f` (repro audit), `26c7a6ed` (no-source rescan), `f96888d1` (experiments.md quick-win)
