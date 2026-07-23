# K904 merge-blocking Codex review — 2026-07-20

## Certification target and verdict

- Repository/branch: `k741-nfp-canonical`
- Frozen commit: `97a89ba974684b8cc96903c005f08d8cbc5296b8`
- Primary object: `k904_task_s4_nfp_canonical.py`
- Claim surface: the k904 README, canonical script/result, archived script/result, and three reader-facing PNGs listed in the review request
- **Verdict: FAIL — not mergeable as-is.**

The numerical 2x2 calculation and the Good-Friday endpoint repair reproduce. The merge is blocked by a non-fail-closed canonical mapper path, two false reproduction/sample statements in the README, and a stale reader-facing NFP figure that presents the archived proxy result as the current K904 result and states an unestablished absorption conclusion.

## Blocking defects

### B1 — Forward-mapper exclusions do not fail closed

`map_forward` correctly maps a release to itself when it is a trading day and otherwise searches only `trading_days >= release`; it therefore cannot map backward. `check_mapping` also raises on a backward map in a forward cell and on mapped-day collisions.

However, the other critical guard does not fail closed. `map_forward` appends an unmappable release to `excluded`, and `run_cell` records that list but proceeds to `estimate` without asserting `len(mapped) == len(dates)` or raising on exclusions (`k904_task_s4_nfp_canonical.py:107-119,177-185`). An adversarial probe with the 2026-04-03 release and a price index ending at 2026-04-02 returned an exclusion and `run_cell` did **not** raise. This is the exact silent sample-loss class that the endpoint correction is meant to prevent: the omission is disclosed inside the generated JSON only if a reader inspects it, while headline statistics are still generated and printed from the reduced sample.

Required resolution: forward/canonical cells must raise when any release is excluded (and ideally assert mapped count equals input count). If archived-factor cells are intentionally allowed to exclude, that exception should be explicit and must not apply to the headline.

### B2 — README sample-completeness and reproduction claims are false

The endpoint itself is repaired correctly. Live FRED release id 50 contains 2026-04-03; the pinned price file contains 2026-04-06; both official cells map 195/195, with the archived mapper mapping 04-03 backward to 04-02 and the forward mapper mapping it to 04-06.

But `README.md:19` says “兩臂都是 195/195 完整對應.” The committed JSON and independent rerun show:

- proxy + archived mapper: 196/196
- proxy + forward mapper: 196/196
- official + archived mapper: 195/195
- official + forward mapper: 195/195

The extra proxy observation is transparently identified in JSON as the phantom 2025-10-03 proxy month, but this makes the README's two-arm count objectively wrong.

`README.md:20` also calls `1.142670` versus archived `1.142569` a digit/bit-level reproduction. The full values are `1.1426730810172516` and `1.142568825381655`, an absolute difference of `0.0001042556` (relative difference about `9.12e-5`). No tolerance is stated in the README or canonical payload, the numbers even differ when rounded to four decimals (`1.1427` versus `1.1426`), and this is not bit-exact or digit-exact reproduction. The canonical JSON does honestly identify the likely source—archived live yfinance versus the pinned snapshot—but the README overstates that approximate fidelity.

Required resolution: say that only the official arms are 195/195 and that the proxy arms are 196/196 because the proxy includes a phantom month; describe the archived comparison as approximate snapshot-consistent reproduction, with a stated tolerance, rather than “逐位”/bit-level reproduction.

### B3 — The reader-facing NFP figure is stale and overclaims the evidence

`k904_chart3_nfp_by_vix.png` is not a canonical-result figure. Its blue values (`1.23`, `1.17`, `1.15`, `0.98`) match the archived first-Friday/proxy JSON, not the canonical official-forward values (`1.305`, `1.230`, `1.165`, `0.935`). The legend merely calls them “K904 重做比率,” so a reader is not told that they are archived/proxy values. This directly conflicts with the corrected README and canonical result on the same claim surface.

The title additionally says the NFP shock “隨 VIX 升高被吸收” and “高恐慌時消失.” K904's canonical script computes four separate raw Welch tests but no cross-regime interaction test and no multiplicity adjustment. The archived interaction test, which the plotted values accompany, reports one-tailed bootstrap `p = 0.127` and a 95% interval `[-0.181, 0.647]`, so the categorical absorption title is not established by that source either.

Required resolution: regenerate or relabel chart 3 from the canonical official-forward cell and frame the regime path as descriptive/corroborative unless a valid interaction analysis supports a stronger statement. The chart must not present the archived proxy arm as the current K904 result.

## Checks that passed

### 2x2 factorial and attribution

All four cells are actually computed from the cross of `{proxy, official}` and `{archived_mapper, forward_mapper}` on one pinned price snapshot. `official__forward_mapper` is correctly selected as the headline. The stored contrasts hold the other factor fixed:

- date effect at archived mapper: `1.1426731 -> 1.1448835`
- date effect at forward mapper: `1.1745807 -> 1.1598344`
- mapper effect at official dates: `1.1448835 -> 1.1598344`

The README's statement that the small `1.1427 -> 1.1449` change is the pure date-source effect at the archived mapper is correct. The complete cells also expose the interaction. The decomposition omits the explicit mapper contrast at proxy dates (`1.1426731 -> 1.1745807`), but it is directly recoverable from the stored cells and the omission does not itself invalidate the reported contrasts.

### Endpoint, lookahead, lagging, and exceptions

- Official 2026-04-03 maps forward to 2026-04-06; the endpoint extension is real.
- Forward cells contain zero backward mappings; archived cells expose the backward holiday mappings rather than hiding them.
- Event returns use the reaction trading day. Same-day return is appropriate for a pre-open NFP release; holiday releases use the next trading day.
- `VIX_prev = VIX.shift(1)` is constructed before slicing, so regime assignment uses information available before the reaction day and the first estimation row has a valid lag.
- The estimation window and counts reconcile: headline 195 NFP plus 3,893 controls equals 4,088 trading days, and regime counts sum to those totals.
- Every S4 `ttest_ind` call in both the archived and canonical K904 scripts explicitly passes `equal_var=False`. The README's “K904 always used Welch” statement is true. Frozen-commit K741 has `HEADLINE_EQUAL_VAR = False` and explicit Student/Welch variants, so the statement that K741's headline was unified to Welch is also true.
- The canonical path contains no stochastic procedure, so it needs no seed. The archived bootstraps have fixed seeds. There is no swallowed `try/except`; broad warning suppression remains undesirable but did not alter the rerun.

### Reproduction and archive integrity

I loaded `FRED_API_KEY` from `/Users/yhlai0911/volpred-research/.env` and reran the canonical script with output redirected to `/tmp`. The live-FRED result differed from the committed JSON only in the generated top-level date (`2026-07-20` versus `2026-07-19`); all computed content matched. The final console-only `OUT.relative_to(REPO)` print raised because the temporary output was outside the repository, after calculation and writing, and did not affect the comparison.

The archived Python file has no changes after its migration commit and is clean at the frozen commit. The archived result and PNGs were left untouched during this review. No repository file other than this review artifact was modified.

## Multiple-comparison assessment

K904 exposes four raw regime p-values, including Low `p = 0.02597` and Medium `p = 0.02851`, without Holm adjustment. The README itself reports only ratios and makes no explicit standalone regime-level significance claim; the canonical JSON is likewise a data record rather than a textual significance conclusion. Therefore the mere absence of Holm in those two surfaces is not an additional blocker at K904's stated corroborative strength.

The figure's categorical “absorbed/disappears” wording is different: it is a reader-facing substantive conclusion unsupported by an interaction test, and is blocked under B3. If the revised figure or README claims that any individual regime is significant, the same four-test Holm disclosure required for K741 is necessary. From the committed raw p-values, Holm over the four regimes would adjust the two smallest p-values to approximately `0.104`, so neither survives 5%.

## Scope and skipped checks

I did not rerun the archived yfinance-dependent full Parts A-G pipeline, regenerate the PNGs, or audit paper text because the request identifies K741—not K904—as the paper table source. I visually inspected all three PNGs and checked their displayed values against the archived and canonical JSONs. The worktree's pre-existing untracked `experiments/k904/review_verdict.json` is a placeholder and was not modified, per the hard constraint.

VERDICT: FAIL
BLOCKING: Forward/canonical exclusions are recorded but do not raise, so headline event loss is not fail-closed.
BLOCKING: README falsely says both arms are 195/195 and falsely labels a 1.04e-4 ratio mismatch as digit/bit-level reproduction without a tolerance.
BLOCKING: Chart 3 presents archived proxy ratios as current K904 and states an unsupported absorption/disappearance conclusion.
