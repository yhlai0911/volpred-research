# K741 merge-certification re-review (round 2) — 2026-07-20

## Certification target and verdict

- Repository/branch: `k741-nfp-canonical`
- Frozen commit reviewed: `0d2835eb0fa3522f23c3cad68d03873bd353e5ce`
- Prior frozen commit/review: `4af5056bbb889a0c9f10121da445acc8a1a49df5` / `review_k741_codex_20260720.md`
- **Verdict: FAIL — not mergeable as-is.**

The new commit correctly changes the main disclosure object, README, and paper, and its new Holm calculations are exact. It nevertheless does not genuinely withdraw the two rejected claims everywhere: the live canonical generator still contains and emits both old defences in `methodology_deltas`. The paper also retains a localized mechanistic overclaim in the interpretation paragraph. These are source-generated contradictions, not harmless stale prose in an archived review.

## Blocking findings

### B1 — The rejected “a priori / not chosen for favourability” defence still survives in live source and regenerated JSON

The principal B1 surfaces were repaired correctly:

- The module docstring now says the choice was made during revision with both p-values known, explicitly withdraws “a priori,” and calls the replacement rationale weaker than pre-specification.
- `test_variant_disclosure.chosen_a_priori` is `false`; `when_chosen` truthfully records that both results were known.
- The README makes the same correction.
- The `tab:nfp` note says “settled during revision with both results known, not pre-specified.”

The replacement sensitivity facts are numerically accurate: Welch helps the overall vs-all comparison (`0.0505613 -> 0.0393514`) but removes the four-regime family’s sole Student-Holm survivor (Low: `0.0356147` under Student versus `0.1038782` under Welch). The main disclosure appropriately says this is weaker than pre-specification.

But the withdrawal is incomplete in the canonical generator:

- `k741_nfp_event_study_canonical.py:159-161` still says the headline is “fixed a priori.”
- `k741_nfp_event_study_canonical.py:655-662`, in the live `methodology_deltas` payload, still says Welch was “NOT chosen for favourability.” That is the exact categorical defence rejected in round 1. It is regenerated into `k741_nfp_event_study_canonical_results.json:1403`.

This is not merely an old historical quotation: a fresh live-FRED in-memory execution reproduced the committed JSON exactly, including this claim. The JSON therefore says both (a) the decision was made after both p-values were known and the weaker “against interest where it counts” fact is all that can be offered, and (b) it was not chosen for favourability. Those cannot coexist as a clean, honest audit record.

The phrase “both variants are reported everywhere” is also too literal. The paper reports the consequential overall vs-all sensitivity and the Student-Holm calm-regime result, while exhaustive per-test variants live in JSON; it does not print every Student/Welch result everywhere. “All consequential sensitivity results are disclosed, with full variants in JSON” would be accurate.

Required resolution: update the stale constant comment and the generated `methodology_deltas` item to the same post-hoc, weaker-than-pre-specification framing already used by `test_variant_disclosure`. Do not retain a categorical no-favourability claim.

### B2 — The rejected “the table is the family” boundary still survives in live source and regenerated JSON

The new calculations and principal paper disclosure are correct, but `k741_nfp_event_study_canonical.py:665-670` still defines the canonical multiplicity change as “Holm-Bonferroni over the four-test family” because “the table is the family.” The live generator emits that text at `k741_nfp_event_study_canonical_results.json:1408-1409`.

This directly contradicts the new `test_variant_disclosure.multiplicity` object, which correctly says the table boundary was convenient rather than principled and reports all four groupings. A canonical result artifact cannot simultaneously reject and endorse the exact family rule that determined the first FAIL.

Required resolution: rewrite the generated `methodology_deltas` item to say that four-regime Holm is retained as one reported grouping, while the two-overall, primary-plus-regimes, and all-six groupings are also computed and disclosed because no pre-specified family boundary exists.

### B3 — The interpretation paragraph still states an unestablished mechanism as fact

Most of the NFP narrative has followed the statistics down: the intro and `sec:nfp` explicitly deny significance, show the `0.072` overall-pair adjustment, call the pattern descriptive, and rest inference on SAR. The high-VIX point estimate is now correctly described as imprecise and compatible with either direction.

However, `main_v3.tex:398` retains the old declarative mechanism language: low-VIX NFP releases are said to represent a larger share of uncertainty, “producing measurably higher volatility,” while at high VIX their marginal contribution “is absorbed.” Neither the regime contrast (`p = 0.115`, interval including zero) nor this binary-event design establishes that causal mechanism; `main_v3.tex:400` then expressly concedes that without surprise controls the design cannot distinguish absorption from different surprise magnitudes. The strong opening sentences conflict with the appropriately weak remainder of the paragraph.

Required resolution: frame those sentences as a possible absorption interpretation (“one interpretation is …”), not as an observed mechanism.

## Independent multiplicity check

I independently recomputed Holm step-down values from the six raw Welch p-values rather than using the script helper. Every committed adjusted value matched exactly (`max |delta| = 0`):

| Family | Independently recomputed minimum adjusted p | Clears 5%? |
|---|---:|:---:|
| Two overall comparisons | `0.0722248191` | No |
| Four regimes | `0.1038782453` | No |
| Primary overall + four regimes | `0.1298478067` | No |
| All six | `0.1558173680` | No |

Thus “nothing clears 5% under any reported family” is true. The full family maps in JSON are correct, not merely their minima.

The paper now discloses the overall-pair adjustment prominently rather than burying it:

- Introduction (`main_v3.tex:72`): both unadjusted p-values are labelled unadjusted, significance is expressly disclaimed, and both adjust to `0.072`.
- `sec:nfp` (`:371`): the two-comparison family and `0.072` are in the main prose.
- Table note (`:393`): all four family minima are reported and the no-5% conclusion is bolded.
- Interpretation (`:398`): the earlier overall/regime significance is expressly withdrawn.

There is no opposite failure of burying the multiplicity result. The only narrative defect is the causal/mechanistic phrasing identified in B3.

## Reproduction bindings and number consistency

`paper/volatility-absorption/reproduce.py` completed at **135/135, 100%, green, gate=pass**. I restored `reproduce_report.json` immediately after the run and verified its working-tree blob equals the frozen commit blob (`9585afa0b915877c742bfde2cd6ee8b6dc1c47e6`).

The new bindings are correctly wired:

- Each of the four reported family minima is bound to the matching `min_adjusted_p_by_family` key.
- `anything_clears_5pct` is computed from all four family maps. Binding `float(False)` to paper value `0.0` with zero tolerance fails if it flips to `True`.
- `chosen_a_priori` is likewise bound as `float(False)` to `0.0` with zero tolerance, so changing it to `true` fails the gate.
- Missing or non-boolean-like values would error rather than silently pass.

These gates constrain the two booleans they claim to constrain. They do not inspect contradictory free-text fields such as `methodology_deltas`, which is why the 135/135 pass does not cure B1/B2.

I also ran the canonical experiment against live FRED with an in-memory output sink, so no repository file was rewritten. The regenerated 52,358-byte JSON was text-for-text identical to the committed result. The paper values covered by the gate and the additional sensitivity values in the notes agree with that regeneration at their stated precision; I found no numerical drift.

## Non-blocking documentation drift from round 1

Both prior drifts are fixed:

1. The README now states `135/135`; an actual run confirms that is the current count.
2. `archived_reproduction` is now explicitly labelled approximate/component fidelity, with archived versus pinned values and the Student/Welch distinction stated. It is no longer presented as an exact reproduction of the archived JSON.

## Scope not checked

I did not recompile `main_v3.pdf`, rerun archived Parts C/D, inspect unrelated paper sections/tables number-for-number, or re-audit the FRED client implementation beyond the successful 194-date live retrieval. I did inspect every claim surface requested here, independently recompute all four Holm families, run the full 135-check paper gate, and perform the live-FRED canonical regeneration without filesystem output.

The pre-existing untracked `experiments/k741/review_verdict.json` and `experiments/k904/review_verdict.json` were left untouched.
