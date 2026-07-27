# Codex primary-path review — K1715 (escalation attempt 2: BFGS min-NLL guard)

You are a rigorous quantitative-finance code reviewer. Review the experiment script at path
`.claude/worktrees/k1715-204d556b/experiments/K1715/K1715.py` (an unmerged worktree branch,
resolvable from the repo root you are in). This is escalation attempt 2 of an
already-reviewed experiment; the ONLY code change since the prior Codex verdict is the
**BFGS min-NLL guard** in `fit_model()`. Focus your review there, but flag any NEW critical
issue you see anywhere.

## Context of the fix under review
A prior Codex CRITICAL found that the fit loop unconditionally adopted the BFGS polish result
(`res_bfgs`) after Nelder-Mead. On the near-integrated ridge, BFGS line-search can fail and
return a HIGHER NLL than NM, so a strictly worse solution could be accepted. The fix (K1715.py
around lines 370-388) is:

```python
res_nm = optimize.minimize(obj, s0, method="Nelder-Mead", ...)
res_bfgs = optimize.minimize(obj, res_nm.x, method="BFGS", ...)
if np.isfinite(res_bfgs.fun) and res_bfgs.fun <= res_nm.fun:
    res = res_bfgs
else:
    res = res_nm
...
"nm_to_bfgs_improve": float(best_rec["nm_nll"] - best_nll),
```

## What to judge (be adversarial)
1. **Does the guard actually eliminate the "accept higher-NLL solution" path?** Consider NaN/inf
   handling, the `<=` tie-break, and whether `best_rec`/`best_nll` are selected consistently with
   the guard so that `nm_to_bfgs_improve` can never be negative. (Empirically all 268 fits report
   nm_to_bfgs_improve >= 0; confirm the CODE guarantees this, not just this run.)
2. **`optimizer_success` semantics honesty**: the code reports scipy's strict BFGS gtol flag as
   `optimizer_success`. When `res = res_nm` (BFGS rejected), is `best.success` semantically
   honest / clearly documented? Is there any way the reported success flag misleads about which
   optimizer's solution was actually used?
3. Any residual lookahead / lag / data-leakage issue (baselines use same one-step timing?),
   fabricated-number risk, or silent failure that would invalidate the NULL verdict.

## Output
Write a structured verdict to the output file:
- Overall: PASS / FAIL
- CRITICAL findings (must be empty for merge): list or "none"
- MAJOR / MINOR findings
- One-line bottom line on whether the BFGS guard fix is correct and safe to merge.
