VERDICT: FAIL

## 1. Is the 2×2 real?

Yes.

- Four cells are independently executed by the nested loops at `experiments/k741/k741_nfp_event_study_canonical.py:358-362`; each calls `run_cell`, which remaps dates and re-estimates statistics.
- Independent event-day hashes were distinct:

  - proxy + archived: `3795682394011407`
  - proxy + forward: `ab4c39abb207e790`
  - official + archived: `a874c44cdec059b2`
  - official + forward: `4cccd900646f254f`

- Pairwise symmetric differences range from 10 to 77 mapped trading days. No cell is a copy or arithmetic derivation.
- `factor_decomposition.date_effect_at_archived_mapper` and `.date_effect_at_forward_mapper` compare date sources at fixed mappers; `.mapper_effect_at_official_dates` compares mappers at fixed official dates. These paths agree exactly with their source cells.
- The decomposition omits the complementary mapper effect at proxy dates, but every contrast it does report is correctly isolated.

## 2. Is the estimation window honest?

Yes.

- Returns and `VIX_prev` are constructed on the warm-up frame before slicing: `k741_nfp_event_study_canonical.py:341-350`.
- Estimation starts with `frame = full.loc[SAMPLE_START:]` at line 350. The first trading observation is 2010-01-04; its `VIX_prev` is the retained 2009-12-31 value, confirming that the lag sees warm-up data.
- Counts come from `len(nfp)` and `len(non)` at lines 173-186, not constants.
- Independent calculation on the pinned CSV reproduced 4,084 estimation rows, comprising 194 NFP and 3,890 non-NFP days.
- JSON sources: `.part_a_historical.n_nfp = 194`, `.part_a_historical.n_non_nfp = 3890`.
- Headline ratio and p-value reproduced exactly: `1.1630737841891277`, `0.050561278499795845`.

## 3. Is the forward mapper leak-free?

Yes for the headline k741 arm.

- `map_forward` only selects `trading_days >= release_date`: `k741_nfp_event_study_canonical.py:136-148`.
- `check_mapping` raises on any backward mapping: lines 151-166. It is reached from every `run_cell` call at lines 315-324.
- A synthetic backward mapping triggered the expected `RuntimeError`, so the assertion is live, not dead code.
- Independent reconstruction of all 194 mappings found:

  - minimum lag: 0 days
  - maximum lag: 3 days
  - strictly backward: 0
  - collisions: 0

- All five Good Fridays map forward to Monday.
- JSON confirmation: `.factorial_cells.official__forward_mapper.n_mapped = 194`, `.excluded_releases = []`, `.backward_mapped_lookahead_events = []`.
- k904 also maps its endpoint release, 2026-04-03, forward to 2026-04-06 and reproduces its archived JSON exactly. Its `run_cell` does not fail closed on exclusions, unlike k741, but the committed result has 195/195 mapped and zero exclusions, so this is a NOTE rather than an observed leak.

## 4. Is the calendar itself right?

The release dates and headline counts appear correct, but the report’s shift taxonomy is wrong.

- JSON supports 195 proxy dates, 194 official dates, 161 exact matches, 33 shifted months, and one phantom month at `.provenance`.
- Official BLS spot-checks confirm:

  - 2010-01-08 was an Employment Situation release.
  - 2012-03-09 is correct even though March 1, 2012 was Thursday. [BLS archive](https://www.bls.gov/news.release/archives/empsit_03092012.pdf)
  - 2013-10-22 was the shutdown-delayed release. [BLS release](https://www.bls.gov/news.release/archives/empsit_10222013.pdf)
  - 2025-11-20 was the delayed September 2025 release. [BLS release](https://www.bls.gov/news.release/archives/empsit_11202025.pdf)
  - 2026-02-11 was the January 2026 release. [BLS release](https://www.bls.gov/news.release/archives/empsit_02112026.htm)

- BLS also confirms that the October 2025 Employment Situation was not published. [BLS archive](https://www.bls.gov/bls/news-release/empsit.htm)

However:

- `nfp_canonical_vs_proxy_comparison.md:69` reports 26 `+7d` shifts. The JSON contains only 25: `.provenance.months_shifted[shift_days == 7]`.
- Only 16 of those 25 months began on Friday. Nine counterexamples begin Wednesday or Thursday, including 2012-03, 2014-01, 2017-03, and 2025-01.
- Therefore the blanket cause at report line 69 is false. The official dates are not wrong; the report’s explanatory classification is.

## 5. Does the paper match the JSON?

Yes numerically.

- Every table entry at `main_v3.tex:382-386` matches `.part_b_vix_regimes.<regime>.{n,mean_abs_return_pct,ratio,t_stat,p_value}` under normal printed rounding.
- Overall and Friday statistics in the introduction and §sec:nfp match `.part_a_historical`.
- The 1.149→1.151 footnote contrast matches `.factor_decomposition.date_effect_at_archived_mapper`.
- The direct contrast, CI, p-value, observed rho, bootstrap mean and trend CI match `.regime_difference_test`.
- Counts 33, 194, 3,890, 4,084, five Good Fridays, and the October-2025 phantom all trace to `.provenance` or the headline factorial-cell arrays.
- A no-write execution of `reproduce.py` returned `123/123`, gate `pass`, exit 0.

NOTE: T5 binds the main table, date-effect footnote, contrast, observed rho and bootstrap mean at `reproduce.py:151-191`, but does not bind the printed trend CI `[-1.00, 0.40]` or several provenance counts. Those numbers do have JSON sources, but future drift would not necessarily trip T5.

## 6. Is the weakened claim weak enough?

No. The difference-in-significance correction is stated correctly later, but not applied everywhere.

- `main_v3.tex:72` says, “When VIX exceeds 25, the NFP effect vanishes.” A ratio of 0.94 with `p = 0.731` does not establish disappearance or equivalence.
- `main_v3.tex:396` states that in high VIX “its marginal contribution to volatility is absorbed” as a mechanism-level fact before admitting that the direct contrast is not established.
- The abstract’s “directionally consistent” wording is appropriately weak.
- The later portion of line 396 correctly explains that significance versus non-significance is not a significant difference and rests inference on SAR, but that qualification does not cure the preceding categorical statements.
- The report repeats the same overclaim at `nfp_canonical_vs_proxy_comparison.md:264`, saying the “effect vanishes” claim “survives and strengthens.” The 0.936 point estimate moved directionally, but `p = 0.731` does not establish vanishing.

This is the primary merge-blocking defect.

## 7. Bootstrap validity

The implementation is reproducible and defensible, with a fixed-calendar caveat.

- Parameters are real: `n_boot=10000`, `block=20`, `seed=20260719` at `k741_nfp_event_study_canonical.py:233`; RNG initialization is at line 250.
- It resamples the full ordered daily tuple in circular 20-day blocks at lines 270-277, preserving local dependence between returns, lagged VIX, regime state, and the NFP indicator. It does not bootstrap only the sparse NFP subset.
- Each replicate recomputes all event/control regime ratios through `ratios(w.iloc[idx])` at lines 254-261 and 277-286. Thus “ratios re-derived per replicate” is accurate.
- Exact re-execution reproduced the archived result byte-for-value: difference `0.369085`, CI `[-0.097157, 0.786302]`, p `0.115`, and zero degenerate replicates.
- Caveat: this is a joint pairs moving-block bootstrap, so it treats the deterministic release indicator as part of the resampled process and lets event counts/spacing vary. A fixed-calendar residual bootstrap would answer a slightly different conditional-inference question. Given the explicitly descriptive, non-rejection conclusion, this caveat does not itself invalidate the weakened claim or introduce lookahead.

## Required fixes

1. `paper/volatility-absorption/main_v3.tex:72,396` — remove the categorical claims that the high-VIX NFP effect “vanishes” and “is absorbed”; the direct bootstrap contrast includes zero and no equivalence test establishes disappearance.

2. `experiments/k741/nfp_canonical_vs_proxy_comparison.md:264` — remove the statement that the “effect vanishes” claim “survives and strengthens”; only the point estimate moved further below one.

3. `experiments/k741/nfp_canonical_vs_proxy_comparison.md:69` — correct `+7d` from 26 to 25 and stop assigning all 25 to the “1st falls on Friday” cause; nine listed months do not satisfy that condition.

4. `experiments/k741/nfp_canonical_vs_proxy_comparison.md:228,300` — correct the stale gate totals (`112/112` and “currently 122/122”); the committed `reproduce_report.json` and no-write execution both report 123/123.
