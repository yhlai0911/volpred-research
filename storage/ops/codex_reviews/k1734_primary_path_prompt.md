# K1734 — primary-path certification review (Codex, read-only)

You are the **primary-path reviewer** for experiment K1734. This review exists because the
certification gate refuses to close on a fallback reviewer: the two existing PASSes came from
`gemini-agy (codex-fallback)` and a `claude-subagent` adversarial cross-check, routed only because
Codex hit a usage limit. **Your verdict is the gate.** Do not defer to the existing reviews — read
the code and the numbers yourself and reach your own conclusion.

## Scope — READ ONLY

Review root: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-1e5922b4-k1734/experiments/K1734/`

Files:
- `k1734.py` (44,339 bytes, sha256 `cc8045ac3f33ce38265f351310ddbd84c9588af653afeda8cad76e15b37c635f`)
- `K1734_results.json` — canonical numbers
- `README.md` — the claims made to readers
- `reproduce_spec.json`
- `review_verdict.json` — prior reviews (context only; do NOT treat as evidence)

**Do not modify any file. Do not run the experiment. Do not merge anything.** Your only output is
the verdict file described at the bottom.

## What the experiment claims

EM carry unwind crash-risk asymmetry, three falsifiable hypotheses, overall verdict
`LEFT_TAIL_ASYMMETRY_CONFIRMED_PLUS_SMALL_OOS_LEAD_YEN_TRIGGER_REJECTED`:

- **H1 (accept)** — EM carry proxy (CEW/EMLC) left tail significantly fatter than right, amplifying in stress.
- **H2 (reject)** — yen-funding (FXY) / risk-off as trigger: rejected; README notes the contemporaneous
  FXY-carry correlation is significant but its **sign contradicts** the yen-funding direction.
- **H3 (accept, main result)** — carry unwind signal at **t−1** leads next-day EEM realized vol with
  incremental OOS skill over a HAR baseline (Clark-West), qualified as small and estimator-dependent.

## Audit dimensions — each needs an explicit finding

1. **Lookahead / lag correctness (highest risk).** Verify in the *code*, not the prose, that the H3
   signal is genuinely lagged (`shift(1)` or equivalent) and that no same-day signal multiplies a
   same-day return. Confirm the HAR baseline uses the **same** lag convention as the new signal —
   an asymmetric lag would manufacture the incremental skill. Check `lookahead_policy` against what
   the code actually does.
2. **Leakage in the OOS design.** Inspect `oos_split`: are estimation windows strictly causal? Any
   full-sample statistic (scaling, standardisation, threshold, VIX stress cut, tail cutoff) fitted on
   data that includes the test period? `vix_stress_threshold` and any tail-quantile definition are
   prime suspects.
3. **Statistics.** Clark-West applied and interpreted correctly (it is a one-sided test of nested
   models). BH-FDR family construction across the 8 primary tests. The README flags that the family
   mixes one-tailed (CW) and two-tailed p-values and reports a conservative doubling
   (`bh_fdr.conservative_two_sided_cw`, H3 adjusted p = 0.0401). Judge whether that treatment is
   adequate or whether the mixed family invalidates the FDR claim. Check overlapping-observation /
   autocorrelation handling in any daily-overlap test.
4. **Honesty.** `positioning_disclosure` states real leveraged positioning is unavailable on free
   data and everything is a proxy. Verify no conclusion anywhere in README or results silently
   exceeds what a proxy can support. Verify the H2 sign caveat is stated where the result is stated,
   not only in a footnote.
5. **verdict_supported.** Does each of `verdicts.H1_accept` / `H2_accept` / `H3_accept` and the
   `overall` string actually follow from the computed statistics at the stated thresholds? Recompute
   or spot-check the decisive numbers from `K1734_results.json`. Flag any number in README that does
   not match its cited JSON path.

Also confirm the seed is fixed and the reported sample counts in README match `coverage`.

## Output contract

Write your verdict to `storage/ops/codex_reviews/k1734_primary_path_verdict.md`.

**The first non-empty line must be exactly one of:**

```
VERDICT: PASS
VERDICT: FAIL
```

`PASS` means: certifiable as-is — no lookahead, no leakage, statistics sound, claims within evidence.
`FAIL` means: at least one blocking defect. Use FAIL for anything that changes a verdict or inflates
a result; a non-blocking nit is not a FAIL, but list it.

After that line provide, per dimension above:
- the finding (with file:line for code issues and the JSON path for numeric issues),
- severity `BLOCKING` / `NON_BLOCKING`,
- for BLOCKING items, what specifically must change.

Be adversarial. A `PASS` here merges the experiment into main and writes it into the permanent
knowledge base — if you are not convinced, say FAIL and say why.
