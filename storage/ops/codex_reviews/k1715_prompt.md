# Codex primary-path review — K1715 (score-driven GAS/DCS for joint VaR+ES)

You are the primary-path reviewer. This experiment lives in a worktree and is FROZEN
at its current committed bytes. Review only; the sandbox is read-only. Your verdict
becomes the merge ticket, so a PASS must be defensible against a skeptic.

## Claim surface (review exactly these; README overclaims reach humans → treat as blocking)
- `.claude/worktrees/k1715-204d556b/experiments/K1715/K1715.py`
- `.claude/worktrees/k1715-204d556b/experiments/K1715/README.md`
- `.claude/worktrees/k1715-204d556b/experiments/K1715/K1715_results.json`

## What this is
First score-driven / DCS volatility implementation on the platform: symmetric and
leveraged Beta-t-EGARCH (GAS-t, GAS-t-lev) estimated by scipy Student-t MLE, tested for
direct joint VaR+ES against GARCH-t / GJR-t baselines on SPY daily returns. OOS 2010-2026
(~4,164 obs), expanding-window refit every 63 days. Reported outcome is a **clean NULL**
(score-driven does not beat GARCH-family). A NULL is a valid PASS-able outcome — do NOT
demand a positive result; judge whether the NULL is *earned* (correct method, no leakage,
honest reporting).

## Verify (be adversarial)
1. **Lookahead**: confirm state_pred[t] is F_{t-1}-measurable — params estimated on data
   strictly before each block; the filter assigns state[t] BEFORE consuming y[t]; GARCH
   init uses model-implied unconditional variance, not the realized array. Cite line numbers.
2. **Numbers match**: every headline number in README must match K1715_results.json
   (violation rates, Kupiec/Christoffersen p-values, DM t-stats, FZ0/pinball losses).
   Any mismatch → blocking.
3. **Convergence honesty**: optimizer_success_rate is 0 (strict BFGS gtol on a
   near-integrated ridge). Is the JSON's framing honest — i.e. is the real evidence
   (boundary_rate~0, persistence~0.98, arch cross-validation matching to 3-4 sig figs)
   actually present and sufficient, or is it hand-waving over a genuine fit failure?
4. **Baselines real**: GARCH-t / GJR-t genuinely estimated and run through the SAME
   Kupiec + Christoffersen + McNeil-Frey + Acerbi-Szekely + canonical HAC-DM battery.
5. **README honesty**: the README was just corrected to remove a false "4,000,000-run
   Monte-Carlo verification of the closed-form VaR/ES" claim. Confirm no residual overclaim
   remains (the closed forms are the standard McNeil-Frey-Embrechts analytic solutions; the
   only MC in the code is the 10,000-rep Acerbi-Szekely null, which is a backtest not a
   closed-form check).

## Output (plain text, last thing you write)
```
VERDICT: <PASS | CONDITIONAL_PASS | FAIL>
REVIEWED_COMMIT: <the worktree HEAD short sha you reviewed, from git log if visible>
BLOCKING_DEFECTS: <none, or a numbered list — each with file:line and why it blocks>
NON_BLOCKING_NOTES: <optional>
ONE_LINE: <one-sentence justification of the verdict>
```
Bar: CONDITIONAL_PASS or above is mergeable. A clean, leak-free, honestly-reported NULL
should be PASS. Only FAIL on a real defect (leakage, number mismatch, fabricated claim).
