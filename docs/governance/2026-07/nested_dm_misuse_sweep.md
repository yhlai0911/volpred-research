# Nested-model raw-DM misuse — full-population sweep

**Date:** 2026-07-12

**Trigger:** K1681 primary-path review

**Task:** `nested_dm_misuse_class_sweep`
**Scope:** `experiments/**/*.py` (static AST + lexical data-flow evidence)

## Why this is a distinct failure class

When a larger forecasting model nests a parsimonious baseline, the null sets the
extra population coefficients to zero but the larger model must still estimate
them. That estimation noise makes the larger model's expected MSPE worse under
the null. Consequently, a raw Diebold--Mariano statistic does not have its usual
equal-accuracy interpretation for the question “does the added variable contain
incremental predictive information?” Harvey--Leybourne--Newbold rescales a DM
statistic for finite samples; it does **not** remove the nested-model bias.

For squared-error forecasts, Clark and West's MSPE adjustment is the relevant
starting point. This does not make every old NULL a PASS:

- A significant Clark--West statistic addresses whether the larger model has
  incremental population predictive content (in the nested linear setup used
  here: whether the added population coefficients are not jointly zero).
- The sign and magnitude of the unadjusted OOS loss difference still describe
  realized finite-sample forecast performance.
- Therefore CW can reject while the larger model's realized OOS MSPE is worse.
  K1681's downside-semivariance cell is the local example.
- Clark--West (2007) is an MSPE procedure. It must **not** be mechanically pasted
  onto QLIKE or pinball loss. Those cells need a loss-appropriate encompassing,
  fixed-window conditional predictive-ability, or valid recursive-bootstrap
  design.

Primary sources: Diebold and Mariano (1995),
<https://doi.org/10.1080/07350015.1995.10524599>; Clark and West (2007),
<https://doi.org/10.1016/j.jeconom.2006.05.023>.

## Population and result

The auditor parsed every Python file without importing experiment code:

| Item | Count |
|---|---:|
| Python files parsed | 1,807 |
| Parse/read errors | 0 |
| Structurally affected paths | **220** |
| Clear raw-DM/HLN claim sink | 211 |
| Static evidence requires manual review | 9 |
| Reviewed-safe CW-primary controls | 5 |
| Affected paths with a knowledge claim | **111** |
| No downstream knowledge claim found (“diagnostic-only” cohort) | **109** |

“Affected” means the path contains strong evidence of (a) a nested baseline /
augmented pair, (b) raw DM/HLN or an equivalent HAC mean test of an unadjusted
loss difference, and (c) a claim sink or unresolved data-flow. It does **not**
mean 220 published conclusions are numerically wrong. Materiality still requires
re-running each experiment with the correct comparison and checking whether the
verdict changes.

Exposure classification uses exact `experiment_id` links in
`storage/memory/knowledge.json`, plus a targeted manual pass over the newest
K1530/K1606/K1616/K1617/K1652/K1668/K1682/K1683 cases. The targeted recent-case
search found no corresponding individual `storage/reports/*.json` article or
`paper/**/*.tex` claim. `storage/reports/feed.json` was deliberately not loaded;
individual report files were searched instead. “Diagnostic-only” here therefore
means “no downstream claim identified”, not necessarily that the experiment's
own script labels DM diagnostic.

Complete machine population and evidence can be regenerated with:

```bash
uv run python scripts/audit_nested_dm_misuse.py --json /tmp/nested-dm.json
```

The frozen path lists live in
`storage/ops/nested_dm_misuse_baseline.json`.

## High-priority exposed cases checked by hand

| Experiment | Nested comparison and claim use | Exposure / action |
|---|---|---|
| K1530 | Baseline vs retail-flow augmented RV model; raw DM/Harvey is the formal gate (`README.md:65-117`) | Knowledge claim says 0/4 specs pass Harvey. Re-run with a nested-appropriate design. |
| K1606 | HAR vs HAR + deposit-flight signal; raw DM/bootstrap drives “no incremental OOS power” (`k1606.py:525-540`) | Knowledge exposed. A block bootstrap of the raw loss difference does not itself remove nesting bias. |
| K1616 | HAR vs HAR + ECT + \|ECT\| (`README.md:51-74`); DM/HLN flags feed the verdict (`k1616_cointegration_ect_har_rv.py:276-303,419-429`) | Knowledge exposed. Re-test the “ECT redundant” claim. |
| K1617 | Clean HAR → static factor-HAR → TVL factor-HAR ladder; pooled-by-date HLN feeds verdict (`k1617.py:447-535`) | Knowledge exposed. TVL-vs-static is not nested; static-vs-HAR and TVL-vs-HAR are. Re-test pair by pair. |
| K1652 | Ridge baseline plus wrapped-token basis features; QLIKE DM/Harvey gates verdict (`k1652.py:197-211,358-369`) | Knowledge exposed. Positive findings are not automatically invalid, but QLIKE needs a loss-appropriate nested test—not MSPE-CW by relabeling. |
| K1668 | HAR vs HAR + CPU signal; raw DM drives incremental-power verdict | Knowledge exposed; re-run before reusing the claim. |
| K1681 | M2B = M1B + SMAD; raw date-aggregated DM was primary (`k1681.py:391-405`) | Knowledge wording is corrected to CW, but old result/verdict fields and an article-angle sentence still retain the Harvey rationale. Formal rerun is queued. |
| K1682 | Baseline + dispersion; QLIKE/pinball HLN-DM governs 0/8 gate, while CW is only an RV diagnostic (`k1682.py:725-761`) | Knowledge exposed. Tail-loss inference remains unresolved. |
| K1683 | Matched baseline + one crowding signal; raw HLN primary family drives NULL (`k1683.py:640-655`) | Knowledge exposed; needs nested-appropriate re-test. |

Two additional contained controls show why the audit cannot use “file contains
Clark-West” as a safe rule:

- `K1679-rev` runs CW only on selected cells, but `summarise()` still derives
  `verdict_standard_dm` solely from raw DM/HLN. It remains affected.
- `K1679-rev2` runs CW on every primary cell and actually wires sign, CW,
  Bonferroni, and DM harm evidence into the verdict. It is a reviewed-safe
  control. `k1116g` and K1680 likewise label raw DM directional/descriptive and
  make CW govern the nested claim.

K1655's addendum is also methodologically useful: its VIX-vs-VIX+NFCI nested DM
is explicitly diagnostic and fixed-window CQFE is primary. A residual caveat
remains for its pinball comparison of a conditional quantile forecast against an
unconditional empirical quantile; MSPE-CW is not the answer for that cell.

## How the auditor works

The static detector requires three channels at the same path:

1. **Nesting evidence:** explicit nested-model language, an augmented feature
   set built from a baseline (`aug_cols = base_cols + [...]`, `.assign(...)`,
   starred-base lists), or paired baseline/augmented prediction/loss names.
2. **Raw comparison evidence:** canonical or local `dm_test`/`dm_hln`/HLN calls,
   plus generic HAC/intercept/one-sample tests when the input or target is an
   unadjusted loss differential. Delegating to the canonical helper is not safe:
   it fixes HAC bandwidth, not the nested-null distribution.
3. **Claim evidence:** verdict/conclusion/summary/evidence/pass/significance
   assignments, branches, or classifier functions tainted by the DM metric.

Path keys are intentional. In K1518, `fit_one()` proves
`base_cols ⊂ aug_cols` and computes canonical DM, while `evaluate()` turns the
stored statistic into PASS/NULL. A `file::function` key would miss that flow.

## Blind spots and false-positive controls

- Static analysis cannot prove arbitrary feature-set containment, especially
  when specifications are generated dynamically or loaded from JSON. The nine
  `review_required` paths are frozen rather than silently discarded.
- A single file can contain nested and non-nested pairs. The path-level ratchet
  is conservative; remediation must adjudicate pair by pair.
- Generic names can hide raw DM (`hac_t_p(loss_diff)` in K1343 and
  `hac_mean_test` in K1344). Conversely, plot/result-reader calls such as
  `fig_dm()` and `get_dm_stat()` are explicitly excluded.
- A Clark-West keyword or sensitivity cell is not a waiver. Safe classification
  requires explicit evidence that CW covers every primary nested comparison or
  that DM is non-governing. K1679-rev vs K1679-rev2 is the regression pair.
- Downstream exposure lookup is strongest for records with exact
  `experiment_id`. Legacy knowledge without that field, title-only article
  references, and prose that omits a K ID remain potential false negatives.
- The scanner finds structural misuse risk, not economic materiality. Only a
  rerun can establish whether a coefficient/content conclusion or a finite-sample
  forecast-ranking conclusion changes.

## Mechanical enforcement (single owner)

| Layer | Artifact |
|---|---|
| Auditor | `scripts/audit_nested_dm_misuse.py` |
| Enforcement owner | `scripts/tests/test_nested_dm_misuse_ratchet.py` |
| Frozen population | `storage/ops/nested_dm_misuse_baseline.json` |

The ratchet enforces:

- no new affected path outside the frozen baseline;
- repaired paths must be removed immediately (no stale baseline padding);
- retired paths cannot resurrect;
- exposed / diagnostic-only cohorts are sorted, unique, disjoint, and counted;
- any unreadable or unparsable Python file fails instead of silently shrinking
  the population;
- regression anchors cover canonical `dm_test`, generic HAC loss tests,
  partial-CW false safety, full-primary CW controls, and synthetic nested /
  non-nested cases.

The active union may only shrink. Moving an exposed site to diagnostic-only does
not count as remediation; the raw-DM claim path must be corrected or retired.
