# Review notes — paper2_taiwan_indiv_rolling_gamma (2026-07-13)

## Reviewer routing (and why it is not Codex)

The project's primary code-review gate is `codex exec`. **It was hijacked, twice.** Both calls were
given an explicit prompt naming the two files to review; both **ignored the prompt entirely** and went
off to review `scripts/fb_realchrome_post.py`, an unrelated FB-posting script.

**Root cause**: `AGENTS.md` — which Codex auto-loads at session start — instructs the agent to *"claim a
pending task from the task pool"*. Codex follows the repo instruction, abandons the caller's prompt, and
does dispatcher work instead. This is not specific to this experiment: **any `codex exec` code review
launched from this repo is liable to be hijacked the same way**, which means the review gate in front of
`knowledge.json` writes may have been passing without actually reviewing. Flagged to the main thread in
README §8 (`AGENTS.md` is outside a worktree agent's write scope).

Per the two-strikes rule (`feedback_gates_fix_immediately_two_strikes_switch_model`), the review was
re-routed to a fresh-context `feature-dev:code-reviewer` subagent — the fallback documented in
`.claude/rules/experiments.md`.

## Findings raised and fixed *before* the external review returned

These were caught by the repo's own gates and by self-audit, and are recorded here because the fixes
changed reported numbers.

### 1. Ablation ordering was confounded — **FIXED** (changed a reported number)

**Defect.** The 2317 data-quality sensitivity dropped the corrupted rows from the *series*, and only then
took the last 2000 observations. Because the series was 7 rows shorter, the slice reached ~7 sessions
further back — into **April 2018, right beside the 2018-Q1 volatility spike that we independently know
raises γ**. The "sensitivity" therefore confounded two changes: *removing the corrupt days* and *adding
days from a high-asymmetry period*.

**Fix.** `last_window(..., ablate=...)` now cuts the window first and ablates **inside** it, holding the
calendar span identical to the primary. Cost: n = 1993 rather than 2000, recorded in `n_obs`.

**Effect on the result.** The corrected ablation reports 2317 γ = **0.0074**; the confounded one reported
0.0085 — i.e. **the old ordering understated the contamination**. (9-stock mean 0.0309 vs 0.0310;
ratio 6.39× vs 6.37×. Conclusions unaffected either way.)

### 2. A statistical overclaim — **WITHDRAWN**

**Defect.** The first draft argued: the TWII γ spread across end dates (~0.11) is about the size of its
own standard error (~0.08), *therefore* the estimates are "imprecise rather than regime-unstable".

**Why that is invalid.** Consecutive end dates share **~97% of their observations**, so the estimates are
strongly *positively* dependent. The standard error of the **difference** between two overlapping
estimates is far smaller than √2 × SE — so two of them can be significantly different from one another
even while their individual confidence intervals overlap almost completely. Comparing a spread of
dependent point estimates against marginal standard errors is not a test of anything, and the sweep is
not a sampling distribution.

**Fix.** The claim is withdrawn in both the README (§6) and the results JSON
(`end_date_sensitivity.what_this_sweep_is_NOT`). What is now claimed is only what survives without
dependence-aware machinery: each estimate is individually imprecise (TWII t = 1.86, 95% CI contains every
other end date's estimate *and* the legacy 0.272); the number moves with the terminal date and the driver
is identifiable; therefore no end date's estimate is a sharp structural constant. The README states
explicitly that settling *real* parameter instability would require a **Nyblom/CUSUM stability test or an
overlap-respecting block bootstrap**, and that **this experiment runs neither**.

### 3. Two silent fallbacks — **FIXED** (caught by the repo's pre-commit gate)

- `fetch_snapshots.py`: a missing legacy reference returned `None`, so the **regression check against the
  old snapshot would silently not run** — a refreshed series could have reached the paper with nothing
  having verified it. Now emits `warn(...)`, records the skip in `MANIFEST.json →
  regression_check_coverage`, and reports which series were unchecked.
- `paper2_taiwan_indiv_rolling_gamma.py`: the multistart loop swallowed exceptions with a bare
  `except: continue`. Now each failure is logged, and — the substantive part — **a fit that still fails to
  converge after 50 seeded restarts now raises** instead of quietly reporting a failed optimiser's
  parameters as if they were estimates.

`scripts/audit_silent_fallbacks.py`: **no findings** for this experiment.

## Verification performed

| Check | Result |
|---|---|
| Offline reproducibility | **PROVEN at runtime** — the estimation script runs to completion with all outbound socket connections blocked. It imports no network library; the 3 mentions of yfinance are in docstrings. |
| Refresh did not alter the data | Every series' log returns reproduce the previous canonical snapshots to **< 1e-6**; re-estimating the *old* window on the *new* data reproduces the 2026-07-07 run exactly. The refresh moved the window, not the data. |
| Calendar alignment | All 12 rows share `window_end = 2026-07-09`. |
| Convergence | All fits converged (`convergence = 0`) across all variants; **zero restarts needed**. |
| Data quality | Full-population scan of all 12 series inside the estimation window for stale-price runs and \|r\| > 11% (Taiwan's ±10% limit). One genuine defect found (2317, §7 of README); the rest are ordinary microstructure zero-return days. |
| Lookahead | None by construction — γ is an in-sample descriptive MLE; no forecast, no OOS split, no signal. |

## Independent review status

A fresh-context `feature-dev:code-reviewer` subagent was dispatched with an adversarial brief covering
(a) window/slicing correctness, (b) the ablation-ordering question, (c) the dependence problem in the
end-date sweep, and (d) referee-facing embarrassments. **Its verdict had not returned when this
experiment was committed.** The three substantive issues it was asked to arbitrate were all resolved by
self-audit first (above), with the corrected numbers already in the results JSON.

**Standing instruction for the main thread**: treat this experiment as **CONDITIONAL** on that review
landing. The numbers are reproducible and the honesty defects are fixed, but per
`.claude/rules/experiments.md` a subagent-fallback PASS is **not** a substitute for a primary-path review
— and here even the fallback has not yet signed off. Do not write `knowledge.json` on the strength of
this file alone. Re-run the review once the `AGENTS.md` hijack (README §8) is fixed, since that is what
broke the primary path in the first place.
