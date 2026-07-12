# Review notes — paper2_taiwan_indiv_rolling_gamma (2026-07-13)

**Verdict: CONDITIONAL_PASS** — fresh-context `feature-dev:code-reviewer` subagent, adversarial brief.

> *"Mechanics are sound. The interpretation is not. … The estimates are trustworthy. The conclusions
> drawn from them are not, and the headline ratio needs an interval or a reframing before it can appear
> in a journal table."*

The reviewer independently recomputed the aggregates from the per-row γ's and reproduced them
(Σγ/9 = 0.290442/9 = 0.032271 ✓; g10 = 0.051244 ✓; 0.197519/0.032271 = 6.1206 ✓), confirmed the
persistence formula and the absence of any lookahead channel, and then took the interpretation apart.
**It was right on both ship-blockers.** Every finding below is dispositioned; nothing is deferred.

---

## Reviewer routing (and why it is not Codex)

The project's primary review gate is `codex exec`. **It was hijacked, twice.** Both calls were given an
explicit prompt naming the two files; both **ignored the prompt entirely** and went off to review
`scripts/fb_realchrome_post.py`, an unrelated FB-posting script.

**Root cause**: `AGENTS.md` — which Codex auto-loads — instructs the agent to *"claim a pending task from
the task pool"*. Codex obeys the repo instruction, abandons the caller's prompt, and does dispatcher work.
**Any `codex exec` review launched from this repo is liable to be hijacked the same way**, which means the
gate in front of `knowledge.json` writes may have been passing without reviewing anything. Per the
two-strikes rule (`feedback_gates_fix_immediately_two_strikes_switch_model`), review was re-routed to the
`code-reviewer` subagent — the fallback documented in `.claude/rules/experiments.md`.

**This must be fixed, not routed around.** See README §8.

---

## Ship-blockers — both confirmed, both now settled by computation

### SB1. "Imprecise, not regime-unstable" was **backwards** — REFUTED, and re-tested

I wrote it, then withdrew it as merely *un-rigorous*. **Both drafts erred in the same direction.** The
reviewer's point: the ~99% window overlap does not *blur* the inference, it **reverses** it.

σ ≈ 0.08 is the marginal sampling SD of *one* estimate. The spread is a dispersion of *differences between
estimates sharing most of their data*. Under a constant-parameter null:

> **SD(γ̂₁ − γ̂₂) ≈ σ·√(2(1−ρ))**

At ρ ≈ 0.99 that is **~σ/7**, not √2·σ. Scoring the movement against σ **understates** it several-fold.
The reviewer's decisive example is my own headline: the 9-stock mean γ **doubles between two windows
sharing 99% of their observations** (z ≈ 5–14 under any plausible cross-sectional correlation). And §6
was self-contradictory — "just imprecision" twenty lines above "an event-driven statistic". *Noise is not
attributable to nameable sessions.*

**Disposition — tested instead of narrated** (`inference.py` part C). Constant-γ parametric bootstrap,
B = 999: fit GJR to the full TWII sample, simulate paths with γ **constant by construction**, run the
identical 19-date sweep on each, compare the swept max−min range. Handles the overlap **and** the max−min
multiplicity exactly.

| | |
|---|---|
| Observed sweep range | **0.1099** |
| Null 95th / 99th pct | 0.0326 / 0.0413 |
| **p** | **0.0010 → reject constant γ** |

The reviewer predicted "given z ≈ 2.5 you reject, and the honest sentence becomes *stronger* than the one
you have." Correct on both counts.

### SB2. The amplification ratio is **ill-posed** — CONFIRMED, and replaced

Not one of the nine stock γ's is significant (|t| = 0.27 … 1.56; 2412's is negative — reviewer checked it
is an interior point, α + γ = 0.155 > 0, so the *t* is valid). The numerator is not significant either
(t = 1.86). **A ratio whose denominator's CI covers zero has an unbounded Fieller confidence set.**

**Disposition — moving-block bootstrap** (`inference.py` part D; B = 999, 252-session blocks, date blocks
resampled *jointly* across all ten securities so their cross-sectional dependence is preserved — a naive
√(Σσᵢ²)/9 assumes it away, as the reviewer noted):

| | Bootstrap 95% CI |
|---|---|
| Denominator γ̄_9stock | **[−0.016, 0.130] — covers zero** |
| Ratio | **[−26.2×, +33.6×]** (range −2504× … +8205×) |

Not a theoretical worry. **The ratio is deleted as a reported statistic.** Replaced with the reviewer's
(a) and (c):

| | Value | Inference |
|---|---|---|
| **Difference** γ_TWII − γ̄_9stock | **0.184** | 95% CI **[0.072, 0.298]**, P(D ≤ 0) = **0.0000** |
| **Ordering** (index γ > every stock's) | **9 / 9** | sign test **p = 0.0020**, Wilcoxon **p = 0.0020** |

**The paper's diversification-amplification thesis survives; its quantification does not.**

---

## Findings I had already self-caught (reviewer confirmed)

- **Ablation ordering** — reviewer **CONFIRMED** drop-after-slice is the defensible choice, and added a
  reason I had missed: the ablated sample becomes a strict **subset** of the primary, making it the unique
  ceteris-paribus contrast; drop-before-slice leaves them merely *overlapping*. Also noted preserving
  n = 2000 has no inferential value here (1993 vs 2000 moves the SE ~0.2%): **composition dominates size**.
- **Two silent fallbacks** (caught by the repo's pre-commit gate): the regression check silently not
  running on a missing legacy reference, and a bare `except: continue` in the multistart. Both now `warn`,
  and a fit that fails after 50 restarts now **raises** rather than reporting a failed optimiser's
  parameters as estimates.

## Findings I had **missed** — all fixed

| # | Finding | Fix |
|---|---|---|
| **P2b** | I fixed the ablation ordering for 2317 but **left the identical 0050 split-date bug in place** — and my comment claimed it was written that way *for* correctness under a moved-back window, which is **exactly backwards**. | All exclusions now route through `last_window(ablate=...)`. Re-run: **numbers identical** → it was latent, not active. Comment corrected. |
| **I1** | The multistart seeded `best` with the **non-converged** incumbent. A failed optimiser that stopped at `maxiter` while still climbing can carry a *higher* LL than a legitimate optimum → every good restart rejected → falls through to the `raise`. Docstring said "keep the best" but the code `break`s on first improvement. | `best = None`; compare converged candidates only; no early `break`. |
| **I2** | The honesty ledger's "all fits converged first try" was **unverified for ~230 of the fits** — `convergence_all_zero` was computed per variant but discarded by the sweep. | `fit_diagnostics` now counts **all 276 fits**: `max_restarts = 0`, `nonzero_convergence = 0`. Claim is now backed by a counter. |
| **I3** | Calendar alignment was *recorded* but never *asserted*, and the sweep dropped the field. The 12 series genuinely differ in trading calendar (stocks start 2018-04-18, index/ETF 2018-04-19), so a cutoff **could** silently misalign one class. | `run_variant()` now **raises** unless all 12 rows share one `window_end`; the sweep carries it. Held across all 23 runs. |
| **I4** | My §4 "the paper's 2886 self-accusation was wrong because 0.170 ≈ 0.179" was **motivated reasoning** — §6 shows 2886's γ is end-date dependent, so an agreement reachable by moving the terminal date proves nothing. | Rewritten: drop the "3× off" claim as unfounded, **but N121 remains untraceable and that is not retired**. |
| **I5** | `event_attribution()` asserted causality from two-ended window comparisons, which cannot attribute a change to the entering segment. | **Ablation-identified** (`inference.py` part B). Result is stronger than the assertion: removing **3 sessions** of 2000 drops the 9-stock mean γ **0.0323 → 0.0134 (−58%)**; removing **one** session (2018-02-06) moves TWII γ by **−0.034**. |
| **I6** | Artifact staleness. | Already resolved by a re-run before the review landed (JSON `excl_2317_gamma` = 0.0074, README "0.020 → 0.007"). The reviewer had read a pre-re-run state. |
| **m1** | Regression gate was `< 1e-4` while every artifact **claimed** `< 1e-6`. "A gate looser than the claim is a claim that nothing verifies." | Tolerance is now `TOL = 1e-6`, enforced, and **raises** on failure. |
| **m2** | Convention string said `Adj Close` is "split adjusted" — contradicted by the manifest's own **−1.389** log return on 0050's 2014 split date. | Reworded: dividend-adjusted; split adjustment **unreliable**. |
| **m3** | `event_attribution()` hardcoded aggregates in prose → would go stale on the next pull. | Now reads them from the sweep and f-strings them. |
| **m4** | `np.median` over a list that could contain `None`; `date_range + [last]` could duplicate a month-end. | `nanmedian`; `sorted({...})`. |
| **m5** | "^TWII posts one session behind" asserted as structural. | Reworded as a fetch-time observation. |

## Verification

| Check | Result |
|---|---|
| Offline reproducibility | **Proven at runtime** — estimation script completes with all outbound sockets blocked |
| Refresh altered data? | No — returns reproduce old snapshots to **< 1e-6** (now an enforced gate); old window on new data reproduces the prior run |
| Calendar alignment | **Asserted invariant**, held across all 23 runs |
| Convergence | 276/276 fits converged, 0 restarts |
| Silent fallbacks | `scripts/audit_silent_fallbacks.py`: **no findings** |
| Lookahead | None by construction (in-sample descriptive MLE) |

## Standing instruction for the main thread

The review is a **fallback-path** verdict. Per `.claude/rules/experiments.md`, a `code-reviewer` subagent
PASS is **not** a substitute for primary-path Codex once Codex is recoverable — and here the primary path
is *broken*, not merely unavailable (`AGENTS.md` hijack, README §8).

1. **Fix the `AGENTS.md` hijack first** — it is the gate in front of every `knowledge.json` write, and it
   is currently passing without reviewing.
2. **Then re-run this review on the primary path**, and note the reviewer source in any knowledge entry.
3. **Do not report an amplification ratio anywhere** — Table 2's footnote currently carries 5.0×/4.5×.
   Replace with the difference (0.184 [0.072, 0.298]) and the ordering sign test (9/9, p = 0.002).
