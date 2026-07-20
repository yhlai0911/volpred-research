# K741 merge-certification re-review (round 3) — 2026-07-20

## Certification target and verdict

- Repository/branch: `k741-nfp-canonical`
- Frozen commit reviewed: `97a89ba974684b8cc96903c005f08d8cbc5296b8`
- Prior review: round 2 at `0d2835eb0fa3522f23c3cad68d03873bd353e5ce`
- **Verdict: PASS — no remaining merge blocker found in this narrow re-check.**

## Resolution of round-2 blockers

### B1/B2 — resolved

The `HEADLINE_EQUAL_VAR` comment now says explicitly that Welch was settled during revision with both p-values known and was not pre-specified. In both the live generator's `methodology_deltas` and the committed regenerated JSON, the old “a priori” wording survives only as an explicitly withdrawn claim. The categorical “not chosen for favourability” defence is gone.

The old “the table is the family” wording also survives only as a description of the rejected interim rule. The generator and JSON instead report all four plausible Holm groupings and state that none clears 5%. Their `methodology_deltas` text is consistent, and the JSON parses cleanly. I found no surviving affirmative use of either withdrawn defence on a regenerating surface.

### B3 — resolved

The NFP interpretation paragraph now introduces absorption as “one interpretation” and immediately states that the data do not establish the mechanism. It identifies both missing supports: the regime contrast is not distinguishable from zero and the binary-event design has no surprise controls. The remainder of the NFP section continues to call the pattern descriptive/directionally consistent and states that the NFP evidence cannot carry the absorption claim on its own. I found no residual declarative causal mechanism claim in that section.

## Regression and merge check

`paper/volatility-absorption/reproduce.py` completed once at **135/135, 100%, green, gate=pass** with exit status 0. I then restored `paper/volatility-absorption/reproduce_report.json`. Its post-run blob hash equals the frozen HEAD blob (`5b9baa748084ac3acbaee8fcb336a68b67d01adb`); the canonical results JSON and `main_v3.tex` hashes were also unchanged across the run. `git diff --check HEAD^ HEAD` is clean. No additional merge blocker was found.

## Scope intentionally not repeated

Per the narrow-review instruction, I did not recompute the four Holm families, rerun the live-FRED canonical experiment, re-audit the boolean gates, recheck the already-fixed round-1 documentation drifts, recompile the PDF, rerun archived Parts C/D, or inspect unrelated paper sections. Those checks passed in round 2; this commit's relevant source changes are confined to the reviewed disclosure strings and NFP interpretation, with matching regenerated JSON changes.

Pre-existing untracked round-2/verdict artifacts were left untouched. Only this round-3 review file was added.
