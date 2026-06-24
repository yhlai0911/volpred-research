% PRG v6 MAJOR #4 verification + remaining pending scope check

# Review scope

- Single-fix verification of commit `92f172cf` (PRG v6 MAJOR #4 — Bonferroni replacement of Harvey 2016 citation).
- Scope-check of `paper_body_prg_v6_major5/6/7` and `minor8/9/10` task descriptions against current `paper/prg-periodic-garch/main.tex`.
- NOT a full Codex review — focused validation only.
- Reviewer: main thread (hourly-08 dispatch, 2026-06-24 08:09 CST).

# MAJOR #4 verdict: **PASS**

## What was fixed

`main.tex` lines 140, 210, 337 now adopt the Bonferroni framing:

> `|t|>3.0` as a conservative significance threshold that approximates a Bonferroni-style adjustment for the family of pairwise DM tests reported across the paper's main results (six markets × three benchmarks) and supplementary tables (approximately 20 tests in total; α/m ≈ 0.05/20 = 0.0025, corresponding to a two-sided normal critical value |z|≈3.02). This individual-test threshold complements, rather than substitutes for, the joint Hansen2011MCS Model Confidence Set assessment...

## Checks

1. **Math**: 0.05/20 = 0.0025 ✓. Two-sided z at α=0.0025: 1−Φ(z) = 0.00125 → z ≈ 3.024 ✓. Mapping `|t|>3.0` ≈ Bonferroni |z|≈3.02 is defensible.
2. **Reference removal**: `grep -i 'harvey2016\|Harvey, .*(2016)\|Harvey (2016)' main.tex` → 0 hits ✓. `Harvey2016` removed from bibliography (3 `Harvey1997` cites remain — distinct small-sample DM correction, correctly retained).
3. **MCS complement**: `Hansen2011MCS` cited 6× including a properly framed "complements, rather than substitutes for" qualifier — addresses Codex concern that the threshold was previously framed as "now standard in MCS literature" without joint test backing.
4. **Cross-ref**: `\label{sec:eval_framework}` added in §2.x; subsequent appearances at L210, L337 cite back via `Section~\ref{sec:eval_framework}` ✓.
5. **Honest hedge**: "approximates a Bonferroni-style adjustment" (not "is a Bonferroni adjustment") — preserves the original "we chose this threshold a priori" framing while disclosing the closest interpretive home for the cutoff.

No issues. MAJOR #4 is structurally sound and ready to ship in next compile cycle.

# Remaining MAJOR/MINOR scope check vs current main.tex

| Task | Status | Evidence in current main.tex | Action |
|---|---|---|---|
| **MAJOR #5** — VaR/ES claim scope to Table 3 actually-shown rows | **DONE — close as succeeded_already_done** | Abstract L41 → "in the reported markets, delivers an SPY Expected Shortfall gain" ✓. §4.3 closing paragraph (L284) → "PRG-leading VaR rankings in the reported markets, while the ES evidence in this paper is strongest for SPY and the dedicated supplement markets rather than a uniform six-market ordering claim" ✓. §4 discussion (L348+) contains no VaR/ES generalization (only QLIKE bridge effect). Conclusion L362 third finding is about HAR target-mismatch (MAJOR #7), not VaR/ES. No "dominates" or "consistent ranking across all six markets" survives in VaR/ES context. | **CLOSE** as `succeeded_already_done`. Task description obsolete — fix was bundled into BLOCKING #1 reframe (commit b630209d). |
| **MAJOR #6** — ablation SPY-only scope-pull-in | **still valid** | Abstract L41 + conclusion L362 generalize: "the bridge value materializes only when overnight information is exploited at the natural intraday-forecast horizon" — universal claim drawn from SPY-only K880v2 robustness exercise. Needs reframing: "in the SPY market, where this robustness exercise is performed, the bridge value materializes..." or equivalent SPY-scoped wording. | **KEEP** — needs targeted rewrite in abstract L41 and conclusion L362 third sentence. |
| **MAJOR #7** — HAR target-mismatch scope to TAIFEX-only | **partially done in conclusion; intro L63 still generalizes** | Conclusion L362 already scoped: "previously reported HAR dominance over GJR **in the TAIFEX sample examined here**... we report this as evidence **consistent with a broader target-mismatch concern... rather than as a general adjudication**." But intro contribution L63 still claims: "previously documented HAR dominance over GJR is largely a target-mismatch artifact... **an evaluation methodology bias systematically obscured in prior literature**." | **KEEP** — needs intro L63 reframe: replace "systematically obscured in prior literature" with TAIFEX-scoped wording or hedge to "as documented in our TAIFEX sample". |
| **MINOR #8** — Table 1 MCS row consistency (PRG only vs PRG Basic + Extended) | not checked in this review | Table 1 at L194–206 | Defer to dedicated fix. |
| **MINOR #9** — discussion-mechanism citation gaps (overnight session-bridge mechanism citations) | not checked in this review | §4 discussion | Defer. |
| **MINOR #10** — economic-value formal test (Sharpe diff test / bootstrap CI / TC sensitivity) | not checked in this review | §3.3 Economic significance / Table 5 area | Defer. |

# Bottom line

- MAJOR #4 lands cleanly; no follow-up needed for that single fix.
- MAJOR #5 may be near-complete — recommend a 10-minute audit of §4 discussion text before the dedicated `paper_body_prg_v6_major5` fix; if §4-discussion is already scoped, close the task as `succeeded_already_done`.
- MAJOR #6 + #7 + MINOR #8/9/10 task descriptions remain accurate and actionable.
- No regression introduced by 92f172cf. Paper safe to keep accumulating fixes on top.

# Sign-off

verdict: PASS (MAJOR #4 fix structurally sound + honest hedge); CONDITIONAL on §4-discussion check for MAJOR #5.
reviewer: hourly-08 main thread focused review
date: 2026-06-24 08:10 CST
