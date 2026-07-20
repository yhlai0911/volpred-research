# K741 merge-blocking Codex review — 2026-07-20

## Certification target and verdict

- Repository/branch: `k741-nfp-canonical`
- Frozen commit reviewed: `4af5056bbb889a0c9f10121da445acc8a1a49df5`
- Primary object: `k741_nfp_event_study_canonical.py`, with its committed JSON, README, `main_v3.tex` NFP passages, and `reproduce.py` T5 bindings
- **Verdict: FAIL — not mergeable as-is.**

The numerical implementation of Welch, Brown–Forsythe, and four-regime Holm is correct and reproducible. The blockers are inferential/governance claims: the choice cannot truthfully be called *a priori* at this stage, and the stated multiplicity family excludes two reported overall tests without a defensible pre-specified basis. Both choices matter exactly at the 5% boundary.

## Blocking findings

### B1 — “A priori” / “not chosen for favourability” is not supportable from this experiment history

The cited methodological rationale is correctly stated and correctly cited. Zimmerman (2004) specifically finds that variance-pretest-then-select procedures fail to protect size and recommends unconditional separate-variance testing for unequal sample sizes; Ruxton (2006) recommends the unequal-variance test as the default alternative; Delacre, Lakens, and Leys (2017) argues for Welch by default, with better Type-I-error control under unequal variance and little loss when equal variance holds. The bibliography entries are accurate.

The numerical disclosures are also correct:

- Brown–Forsythe (median-centred Levene), NFP vs all non-NFP: `p = 0.4801957964`, SD ratio `0.9376421850`. This is correctly described as *no evidence* of unequal variance; it is not evidence that variances are equal.
- Overall vs all: Student `p = 0.0505612785`; Welch `p = 0.0393514478`.
- Four-regime Student Holm: Low `0.0356147439`, Medium `0.0802572622`, Elevated `0.5069042594`, High `0.7312488924`; Low alone survives.
- Four-regime Welch Holm: Low `0.1038782453`, Medium `0.1038782453`, Elevated `0.5329009894`, High `0.7066611566`; none survives.

Those facts do **not** establish that the choice was a priori or not outcome-favourable. The archived analysis had already been run with Student, the two p-values and their crossing of 5% were known, and this round then changed the headline to Welch. A standard default selected after observing the result may be a reasonable post-hoc standardisation, especially with full sensitivity disclosure, but it is not temporally a priori. Moreover, “Welch hurts the regime family” does not negate that it changes the separately headlined overall result in the authors’ favour. The paper and JSON make the categorical claims `chosen_a_priori: true`, “not chosen for favourability,” and “It is not a choice that flatters the results”; the available audit trail cannot certify those claims.

Required resolution: retain Welch if desired, but describe it as a post-hoc methodological standardisation adopted after the omitted default/mislabelling was discovered; explicitly say the choice was made with both results known. Do not claim that an adverse result in another family proves absence of outcome-sensitive selection.

### B2 — The Holm family is defined by table location, and exclusion of the two overall tests is convenient rather than principled

The four regime tests plainly form a family, and the implemented Holm step-down calculation for that family is correct. But “the table is the family” is not a statistical principle; a family follows the set of inferential claims, not the LaTeX table boundary.

The overall vs-all and vs-Friday tests are not merely “two framings ... on one sample.” They use different control samples and answer distinct comparator questions. Dependence between them does not prevent Holm adjustment. Both are reported together in the intro and `sec:nfp`, and there is no pre-analysis designation of one as the sole confirmatory primary test with the other only a sensitivity check.

The consequential omitted calculations are:

- Holm across the two reported overall comparisons: both adjusted `p = 0.0722248191`.
- Holm across the primary vs-all test plus four regimes (five tests): smallest adjusted `p = 0.1298478067`.
- Holm across both overall comparisons plus four regimes (six tests): smallest adjusted `p = 0.1558173680`.

Thus the present family boundary preserves a nominally sub-5% overall headline that disappears even under the smallest natural overall family. The paper does call the result “borderline” and discloses Student `p = 0.051`, which is commendably cautious, but it does not disclose this directly relevant multiplicity result. The exclusion is therefore convenient, not adequately principled, as written.

Required resolution: pre-specify and justify distinct confirmatory/exploratory families independent of observed p-values, or adjust/disclose the two overall comparisons (and explain why the regime family is separate). The current claim that they are one hypothesis “on one sample” must be corrected.

## Checks that passed

### Independent rerun and exact statistics

I loaded `FRED_API_KEY` from the repository `.env`, reran the frozen script once with `OUT` redirected to `/tmp`, and used the live FRED endpoint. The generated JSON was byte-for-byte identical to the committed canonical JSON. The final console-only `relative_to(REPO)` print raised because the temporary output was outside the repo, after all calculation and output writing; this did not affect the comparison.

I independently recalculated Holm rather than relying on the script helper. It reproduced every committed adjusted value above. `HEADLINE_EQUAL_VAR = False`, and every `scipy.stats.ttest_ind` call is centralized in `both_variants`, where both `equal_var=True` and `equal_var=False` are explicit. No call site relies on SciPy’s default.

### Number-for-number consistency

The committed JSON, `tab:nfp`, both new tablenotes, `sec:nfp`, the introduction, and T5 bindings agree at their stated rounding precision:

- Overall ratios/p: `1.1630738 / 0.0393514` vs all and `1.1870627 / 0.0361124` vs Fridays → `1.16/0.039`, `1.19/0.036`.
- Regimes: counts `63/76/27/28`; means `0.527/0.788/1.046/1.417`; ratios `1.31/1.23/1.19/0.94`; Welch t statistics `2.28/2.23/1.13/-0.38`; raw p `0.026/0.029/0.266/0.707`; Holm p `0.104/0.104/0.533/0.707`.
- Total: 194 NFP + 3,890 non-NFP = 4,084 days.
- Brown–Forsythe `0.48`, Student alternative `0.051`, regime contrast `+0.37`, CI `[-0.10, 0.79]`, and bootstrap `p = 0.115` all agree.
- Factorial footnote values `1.149 → 1.151` agree with `1.1487091 → 1.1509593`.

`reproduce.py` completed successfully at `130/130`, green/pass. I restored `paper/volatility-absorption/reproduce_report.json` immediately afterward and verified its blob hash was unchanged.

### Calendar, window, lookahead, seed, and guards

- The 2×2 remains intact: proxy/official crossed with archived/forward mapper.
- The official-forward headline maps all 194 releases, with zero exclusions and zero backward mappings. The official-archived cell still exposes the five backward Good-Friday mappings; they are not silently removed.
- The 2009-12 warm-up is used only to create lagged `VIX_prev`; estimation is sliced from 2010-01-01 (first observed trading row 2010-01-04), so the prior 21-control-day leak remains fixed.
- `VIX_prev = VIX.shift(1)` is explicit. Event-day return is same-day because NFP is released before the market open; holiday releases are mapped forward, never backward.
- The moving-block bootstrap uses fixed seed `20260719`.
- Direct adversarial probes confirmed that backward mapping, duplicate mapped observation days, and forward-mapper exclusions raise `RuntimeError`. The headline committed cell also binds mapped count, exclusions, and backward-event count in `reproduce.py`.
- There are no `try/except` blocks that swallow failures. Global `warnings.filterwarnings("ignore")` does suppress all warnings; no warning occurred in the rerun, but this broad suppression is undesirable for a research script.
- Both archived source/result files have hashes identical to the frozen commit and are unmodified.

## Narrative assessment and non-blocking drift

The paper’s main NFP narrative is otherwise appropriately cautious: “borderline,” “descriptive,” no regime surviving Holm, direct regime contrast not established, low power acknowledged, and NFP not used as the basis of the paper’s inference. The prose matches the reported numbers. The categorical sentence “When VIX exceeds 25, the NFP effect vanishes” is stronger than the evidence—the estimate is imprecise and compatible with effects in either direction—but the adjacent `p = 0.707`, small-cell disclosure, and later caveats substantially qualify it.

The script stores a one-sided Mann–Whitney result vs all (`p = 0.0006388451`) but the paper does not use it. This omission is conservative and is not a concealment that inflates the claim; it tests a different distributional/rank estimand and direction.

Two documentation drifts should be cleaned up but did not determine the FAIL:

1. `README.md` still says the reproduction gate is `112/112`; the frozen gate now reports `130/130`.
2. The module docstring says `archived_reproduction` demonstrates reproduction of the archived JSON “before any fix.” Under the global Welch headline it reports `p = 0.0699472`, not archived Student `p = 0.0813807`; its stored Student alternative (`0.0810578`) nearly reproduces the archived value, with the residual attributable to the pinned-vs-live price snapshot. The cell should be labelled approximate/component fidelity, not exact pre-fix reproduction.

## Scope not checked

I did not rerun archived Parts C/D, recompile the PDF, inspect unrelated paper tables, or audit the upstream FRED client beyond the returned 194-date calendar. I did verify the requested T5 reproduction gate and all claim-surface files. The worktree’s pre-existing untracked `experiments/k741/review_verdict.json` and `experiments/k904/review_verdict.json` were left untouched.
