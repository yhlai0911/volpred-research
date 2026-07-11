# Codex primary-path review — K1686 contemporaneous null (volatility absorption)

You are the primary-path code reviewer for an empirical finance experiment. A
`feature-dev:code-reviewer` subagent already passed it CONDITIONAL PASS, but under this
repo's K1259 rule a subagent PASS does not substitute for a Codex primary-path PASS. Your
verdict decides whether the result may be written to the canonical knowledge base.

Read these files (repo is read-only to you):

- `experiments/k1686/k1686_contemporaneous_null.py` (~1200 lines — the whole thing)
- `experiments/k1686/k1686_contemporaneous_null_results.json`
- `experiments/k1686/README.md`
- `experiments/k897/` (the predecessor whose `NULL REJECTED` verdict this experiment overturns)

## Context

Paper 8 (`paper/volatility-absorption`) claims that high ambient fear *absorbs* volatility
shocks: the shock-absorption ratio (SAR) declines across VIX regimes (calm <15 → high 25-30),
empirical decline = 0.8165. K897 simulated a GJR-GARCH null and reported `NULL REJECTED`,
i.e. GARCH mechanics cannot reproduce the decline.

K1686's charge: K897's null used a vol proxy that could not react to the *same day's* return,
whereas VIX can. Making the proxy contemporaneous is the make-or-break identification test. The
decision rule was pre-registered in commit `870af5d00` **before any simulation ran** (verify this
yourself in git history): decline outside the null's 95% CI → identification holds, paper upgrades;
inside → absorption claim downgraded, paper reframes.

Reported outcome: 0.8165 falls **inside** the contemporaneous null 95% CI [0.0824, 1.0596],
MC p = 0.41 → `IDENTIFICATION CLOSED`, verdict `ABSORPTION CLAIM NOT SUPPORTED`.

## What I need you to check (be adversarial — try to break it)

1. **Contemporaneous timing is actually implemented, and is not lookahead.** The null's proxy at
   time t must react to r_t (that is the whole point), but nothing may use information from t+1 or
   later. The code extends the GARCH recursion one step to get `h[n_obs]`. Verify that `h[t+1]`
   (a *conditional* variance known at t) is what feeds the proxy, that this is the correct analogue
   of VIX's forward-looking construction, and that the shift/index arithmetic (`abs_ret[1:]`,
   `P[:-1]`, `shock[1:]`) is off-by-one clean in every variant.

2. **Seed reproducibility and the "identical paths as K897" claim.** README asserts the same seeds
   + same params + no extra random draw ⇒ simulated return paths are pointwise identical to K897's,
   which is what licenses the "on the same seeds, the margin was a timing artifact" comparison. Check
   this is true in code (no extra `standard_t` draw, no padding, no reordering). If it is not exactly
   true, say so — the K897-overturn claim leans on it.

3. **Empirical vs simulated definitions are aligned.** The SAR, the regime cut-points (15/20/25/30),
   and the shock threshold (|Δproxy| > 2) must mean the same thing on both sides. Where they cannot
   (the null's proxy lives on a different scale than VIX — see variants F and G, the calibration
   discussion in README §6), check the code does not quietly compare unlike with unlike, and that
   any such gap is *disclosed* rather than papered over.

4. **Pre-registration integrity.** Confirm from git history that the decision rule and the empirical
   value 0.8165 were committed with **no results present**, and that the pre-registered primary
   (variant A) was not swapped, re-specified, or re-seeded after results appeared. Variants F and G
   are labelled POST-HOC — confirm that labelling is honest and that no post-hoc variant is being
   used to carry the primary verdict.

5. **Does the verdict overclaim?** The result JSON says the null comparison is *inconclusive* (A/D_up/E
   fail to reject; B/C/G reject) and rests the decisive finding instead on a null-free signed
   decomposition (fear spikes: decline −0.1226, bootstrap 95% CI [−0.7289, 0.5828], n=10 fear-spike
   days vs 24 relief days). Two things to judge: (a) is the signed decomposition itself sound, or is
   n=10 too thin to carry "decisive"? (b) is the *stated* verdict appropriately weaker than the
   evidence, or does it overclaim in either direction?

## Output format (plain markdown, no preamble)

```
## VERDICT: PASS | CONDITIONAL PASS | FAIL

### Blocking issues
(numbered; each with file:line and why it invalidates the result. "none" if none.)

### Non-blocking findings
(numbered; file:line.)

### On the K897 overturn
(does the evidence support retiring K897's NULL REJECTED verdict? yes/no + why)

### On the paper disposition
(the experiment recommends reframing Paper 8 as an FRL measurement note — signed-composition
effect, not absorption. Is that supported by what you read, or is even that too strong?)
```

Be concrete. Cite line numbers. If the code is clean, say so plainly — do not manufacture findings.
