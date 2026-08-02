# Codex primary-path review — K1813 (frozen bytes)

You are the independent reviewer for experiment **K1813**. The experiment is FROZEN.
Read-only sandbox: do not edit, re-run, or "fix" anything. Your job is to judge.

## Where the bytes are

Worktree (frozen, already committed as `7a41cb362`):

```
/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-8af0700e-k1813/experiments/k1813/
  k1813.py                 (57,747 bytes, sha256 a9e19bc27714c0bf5b1f95c590cc5755eef7f6f849d13ac1532bb7aed68a0f0b)
  K1813_results.json       (376,182 bytes, sha256 6b29611d346afb29188a95f49789cfc4d07ea2a40b4f848e904648af82b69382)
  README.md                (sha256 667604cbc6ddea83a1324025e38c8c9f020c11a9c9efbecfdaa707b6e14715ba)
  reproduce_spec.json
  data/*.csv               (frozen yfinance pulls, hashed in reproduce_spec.json)
  figures/*.png
```

Verify the hashes yourself before you start. If a file's bytes differ from the above,
stop and report that as a blocking defect — you are not reviewing what was claimed.

## What the experiment claims

Topic: overnight vs intraday volatility-risk-premium clustering, and whether a
day-of-week overnight rule is tradable after costs. SPY/QQQ/IWM/TLT/GLD, yfinance daily
OHLC, OOS from 2015-01-01 (n=2909), seed 42, block bootstrap B=2000 block=20, BH-FDR q=0.10.

Headline verdicts in `K1813_results.json` -> `verdicts`:

- H1a ACCEPT — both segments show volatility clustering (Ljung-Box Q(10), 5/5 assets).
- H1b REJECT — the AR(5) |r| persistence gap between segments is significant in 0/5 assets.
- H2a REJECT — the tradable axis (overnight *return*) shows no weekday structure
  (0/25 cells, 0/5 joint F after FDR).
- H2b ACCEPT — the variance axis (overnight RV / VRP proxy) does, 5/5 assets.
- H2c — after controlling for how many calendar days the overnight window spans,
  only QQQ/TLT/GLD survive; SPY and IWM drop out.
- **H3 REJECT (main result)** — at 1 bp/side on `net_with_cash`, 0 of 25
  asset x calendar-rule combinations achieve delta-Sharpe > 0 with bootstrap p < 0.05;
  9 combinations significantly LOSE to buy-and-hold. Rules that "win" at 5 bp are
  claimed to be a turnover artifact (SPY 205 vs 504 sides/yr), not a calendar effect.

This is a NULL result. **A null is easy to get for the wrong reason** — an underpowered
test, a mis-specified benchmark, or a cost model that buries everything. Review it as
carefully as you would review a positive finding, in both directions: is the null real,
and is any surviving sub-claim (H2b/H2c) overstated?

## Blocking checklist

Judge each; a genuine problem in any one is a FAIL.

1. **Lookahead.** Every signal must be built from information available strictly before
   the return it multiplies. Check `signal.shift(1)` and equivalents, the expanding /
   walk-forward weekday means (around line 628-640), the ex-ante RV window (around 473-490),
   and the T-bill rate lag (line 241). Note `next_on = w_on.shift(-1)` near line 525 is used
   for *turnover accounting*, not for returns — confirm that reading, or flag it if the
   forward weight leaks into P&L.
2. **In-sample / out-of-sample separation.** Weekday selection, top-2 selection and the
   "worst weekday" screen must be fit on pre-2015 data only. Confirm the frozen selection
   never sees OOS data, and that the walk-forward variant is genuinely causal.
3. **Benchmark fairness.** Buy-and-hold, always-overnight and the calendar rules must use
   the same lag convention, the same cost model, the same interest/cash accounting, and the
   same trading days. The code claims a 100%-bills book has exactly zero excess return and
   buy-and-hold has exactly zero turnover — verify both hold in the results.
4. **Cost and interest accounting.** actual/360 on calendar days, the whole daily accrual
   assigned to the overnight window, cash credited as `(1 - w_on) * rf`. Check this does not
   quietly advantage or penalise the overnight books relative to buy-and-hold, and that
   `net_with_cash` is the right scoring series for the claim being made.
5. **Inference.** Block bootstrap with seed 42, block length 20 on ~2909 daily obs;
   HAC/Newey-West lag choice; BH-FDR family definitions (are the families the pre-declared
   ones, or chosen after seeing results?); the joint-F tests. Is multiplicity handled for the
   H3 grid of 25 combinations, or is the REJECT resting on unadjusted p-values? A REJECT is
   conservative under multiplicity, but say so explicitly if it is not adjusted.
6. **Power / honesty of the null.** With n=2909 OOS days and bootstrap SE ~0.23-0.29 on
   delta-Sharpe, what effect size could this design actually detect? If the README claims
   more than "failed to reject", flag it.
7. **README vs results.** Every number in `README.md` must be reproducible from
   `K1813_results.json`. Spot-check at least 10, including the H2c q-values, the SPY/TLT
   significant losses, the IWM +0.038 (p=0.88), the turnover figures, and the TLT Thursday
   in-sample mean. Also check the figures do not assert something the numbers do not support.
8. **Degenerate-rule disclosure.** For SPY/QQQ/IWM/GLD all five weekdays have positive
   in-sample overnight means, so the sign-screen rules collapse into `always_overnight`
   (delta-Sharpe exactly 0.000, p=1.000). Confirm this is disclosed rather than presented
   as five independent tests.
9. **reproduce_spec integrity.** `entrypoint.sha256` and `size_bytes` must describe the
   script that actually produced the results (this is the K1708 failure mode), and
   `canonical_result_identity` must match the results file on disk.

## Output — stdout only

Your sandbox is **read-only**: you cannot write files, and you should not try. Everything
you emit on stdout is captured verbatim into
`storage/ops/codex_reviews/k1813_verdict.md`, and the main thread lands it from there.

Emit, in this order:

**(1)** The full review in Markdown: your findings per checklist item, with file:line
evidence for anything you flag. Separate **blocking defects** from **non-blocking
observations**.

**(2)** As the LAST thing in your output, a single fenced ```json block containing exactly
this shape, hashes copied verbatim from the list above (the main thread parses the last
fenced json block and writes it to `experiments/k1813/review_verdict.json`):

```json
{
  "kid": "k1813",
  "verdict": "PASS or FAIL",
  "reviewer": "codex/<model> (<effort>)",
  "reviewed_at": "<ISO8601 UTC>",
  "reviewed_commit": "7a41cb362",
  "review_artifact": "experiments/k1813/codex_review.md",
  "blocking_defects": [],
  "reviewed_sha256": {
    "K1813_results.json": "6b29611d346afb29188a95f49789cfc4d07ea2a40b4f848e904648af82b69382",
    "README.md": "667604cbc6ddea83a1324025e38c8c9f020c11a9c9efbecfdaa707b6e14715ba",
    "figures/fig_acf_segments.png": "c54a6ba7bf907bae5e23cc25507ba75e06fe016d8462e985342e35ad9534218a",
    "figures/fig_cost_sensitivity.png": "9b45ab69f0a1b9963d725718af30b71d6c06a450b6c1074f56015b077ce67769",
    "figures/fig_equity_curves.png": "55d602315636457c0b33f830a3a4d0d929b0d7952e31d2a5ae74a54f32bf9de8",
    "figures/fig_weekday_bars.png": "08abc5e7bf634f4398a08f042095f27cdf32904b1b63ad7d17af3febf70b1f08",
    "k1813.py": "a9e19bc27714c0bf5b1f95c590cc5755eef7f6f849d13ac1532bb7aed68a0f0b"
  }
}
```

`verdict` must be `FAIL` if any blocking defect exists, and `blocking_defects` must then be
non-empty. Do not soften a real defect to let the merge through, and do not invent one to
look thorough. If the work is sound, say PASS with an empty defect list.
