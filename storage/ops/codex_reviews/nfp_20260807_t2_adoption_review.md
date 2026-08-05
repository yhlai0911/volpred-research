# nfp_20260807_t2 — adoption review

**Date**: 2026-08-05
**Dispatch**: `assign_c7ca1c01`, slot-1 / job 353fc09c8276479fb2bf5b5e25002108
**Outcome**: PASS on the frozen snapshot pinned in `review_verdict.json`

## Why not Codex

The canonical reviewer for `experiment_ready_for_main` is Codex. It was unavailable
for the whole of this fire: `scripts/codex_exec_bounded.sh --timeout 90` returned
`ERROR: You've hit your usage limit ... try again at Aug 8th, 2026 12:01 PM`, and the
queue-maintenance quota probe independently reported `unavailable; blocked=2;
reachability rc=-4`. The credit window reopens 2026-08-08, which is after the
2026-08-07 release this evidence package serves — waiting would have expired the
artifact's reason to exist.

Reviewers used instead: two independent Claude Opus 5 subagents, each given a
distinct adversarial lens and no sight of the other's findings. This is weaker than
Codex on independence — same model family as the author — and the verdict records it
plainly rather than claiming a Codex review that did not happen. The T-7 sibling
(`nfp_20260807_t7`) was certified by Codex plus subagents; this one is subagents only.

## What was reviewed

The package was orphaned and untracked for four fires. The reaper held it as
`atomic_unit_incomplete`. Running the admission gates directly showed the dispatch
brief's premise ("only gap = no README.md") was incomplete: the gate's actual failure
was `review-certification: uncertified: no review_verdict.json`. Both gaps are closed
here. `reproduce_spec`, `reproduce_commit`, entrypoint identity and artifact
generation were already clean and were not touched.

`README.md` and `render_readme.py` are new in this fire. The README is generated from
`nfp_20260807_t2_results.json`, so no number in it is hand-transcribed; `--check`
re-renders and fails on drift. The experiment code, results JSON, figure and data
snapshots were **not** modified — hashes below match the pre-existing pins.

## Lens 1 — code correctness (agent ac90fefce0ec7a7f2)

**PASS.** The reviewer reimplemented the analysis independently and matched the
archived results to ~15 significant figures: event n=191 mean=-0.17185212143133796,
control n=3597 mean=0.7181639668437, panel n=3788, and all three HAC lags
(SE 0.8207232162487592 / 0.8377046835148462 / 0.8554410990015895).

Verified: event window is literally `close[i-1]/close[i-3] - 1` (`nfp_20260807_t2.py:215`,
`PRE_LAG=3`); the control exclusion `range(release_position - 2*HORIZON, release_position - 1)`
is exactly tight against the sampled event set — zero of 3,597 controls overlap any
event window; every panel is `.sort_values("start_date")` before HAC; lag 6/22/60 are
genuinely re-fit rather than copy-pasted; Holm is a correct step-down over the 4 regime
cells; and there is no look-ahead — the script hard-fails unless the snapshot ends at
2026-08-04, the target release is not in the sample, and `forward` is NaN at the as-of
date so it cannot enter the control set as a partial window.

Non-blocking: 21 of 3,597 controls (0.58%) are under-excluded relative to the literal
control definition, from two guards at `nfp_20260807_t2.py:200-204` — six Good-Friday
releases skipped by a calendar-match guard, and one release whose exclusion loop is
short-circuited by an earlier `continue`. Direction is toward the null. Also
`n_releases_matched` labels 191 as "matched" when 192 matched and one was dropped for
insufficient history.

## Lens 2 — overclaim and number fidelity (agent ac2542a5cab1c18fb)

**FAIL on round 1**, then PASS after fixes, across four rounds. Both blocking defects
were in prose written during this fire, not in the pre-existing experiment:

1. **A stated result that was never computed.** The first README draft said both week
   halves "沒有通過 primary test". `week_decomposition.early_T7_to_T3` holds only
   descriptive fields — no p, no CI, no HAC — and the sibling tested the full week, not
   the early half. The early half is exactly where the dilution hypothesis puts the
   ramp, so this was material. Replaced with an explicit statement of absence.

2. **An uncaveated figure the README disowned in prose.** `nfp_20260807_t2_window.png`
   has a "decompose the pre-release week" panel whose tallest bar is the release day
   itself at -1.30%, the raw weekday-confounded mean, no error bar, setting the y-axis.
   The README's own text called that number unreadable as an event effect, but never
   referenced the figure. The PNG is pinned in `artifact_generation.output_identities`,
   so regenerating it would invalidate `generation_id e05354953867738d...`; the remedy
   is a README-layer correction naming the file, the scope error, the weekday-controlled
   counterpart (-0.75 pp, p=0.285) and an explicit prohibition on the finding reading.

Rounds 3 and 4 fixed a self-contradiction introduced by that very caveat (a closing
clause that asserted a significance status for the untested first bar), moved all
remaining hand-typed counts and both "CI covers 0" predicates behind derived helpers,
scoped an over-broad units line, and corrected a latent compound-numeral bug
(`cn_count(12)` → 十兩). The last fix touched `render_readme.py`, which is in the claim
surface, so it was re-reviewed rather than slipped in after the PASS; the reviewer
independently ran `--check` and confirmed the README bytes were unchanged.

## Residual risks accepted

- **Reviewer independence** is weaker than the Codex baseline (same model family).
- **Under-exclusion of 21 controls** — negligible, toward the null, recorded not fixed;
  fixing it would require a re-run and a new artifact identity.
- **Syndication risk on the frozen PNG**: the caveat lives only in the README, so if the
  figure is lifted into an article without it, the correction does not travel. The T-7
  sibling shows this pathway is live. Relevant to whatever publish step consumes this.
- **Scope-loose sentence** at README L116 ("唯一經過 HAC 推論的窗口") slightly under-counts
  the test surface — the weekday-controlled day-level regressions are also HAC.
- `cn_count(n)` for n >= 20 falls through to an Arabic numeral. Unreachable (max is 5).

## Verdict

PASS, bound to the `reviewed_sha256` map in
`experiments/nfp_20260807_t2/review_verdict.json`. Any edit to those five files
re-opens the gate, which is the intent.
