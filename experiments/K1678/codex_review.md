# K1678 Codex Review

## Verdict

`PASS` — the experimental verdict `NULL_NO_ROBUST_SALIENCY_AMPLIFICATION` is supported by the stored artifacts. No blocking methodology or implementation issue remains.

Reviewer source: primary Codex session plus independent fresh-context Codex subagents, pre-run and post-run.

## Pre-run gate

The script was reviewed before the full experiment for:

- SEC Attachment-A full-population parsing and option-identifier exclusion;
- explicit event/attention `shift(1)` and exact t+1…t+H target windows;
- target-free same-ticker matching and event-buffer rules;
- within-ticker H-row event de-clustering;
- horizon-specific HAC lags;
- seed/block bootstrap implementation;
- Bonferroni and BH over exactly m=8;
- conservative verdict logic and atomic JSON replacement.

Result: `PASS`. The source parser smoke test independently recovered 439 blocks, 412 equity tickers, 1,083 date occurrences, and 1,079 unique ticker-dates with the exact expected year counts.

## Post-run artifact verification

- Primary cells: 8/8 independently refitted from `K1678_matched_events.csv.gz`.
- Maximum coefficient discrepancy: `1.07e-13`.
- Maximum HAC t-statistic discrepancy: `2.16e-15`.
- Maximum HAC p-value discrepancy: `1.67e-15`.
- Matched outcome differences recomputed from `data/analysis_panel.csv.gz`; maximum discrepancy `7.28e-12`.
- Matched saliency differences recomputed; maximum discrepancy `4.44e-16`.
- Every formation date maps to the preceding ticker trading row and an exact SEC label.
- Every control set has three rows; nearest control is 11 trading rows from any labelled event, exceeding `max(10,H)`.
- H=5 retained events are at least five ticker trading rows apart.
- H=1/H=5 coverage agrees across JSON and CSV: 525/345 matched rows, 302/242 event-date clusters, 205/204 tickers.
- Bonferroni p-values are all 1.0; minimum BH q is 0.7716; maximum absolute primary HAC t is 1.258.
- All eight 2,000-rep moving-block bootstrap 95% confidence intervals cross zero.
- Base seed 42 and derived per-cell seeds 142–145 / 542–545 are recorded; block length is 10 for both horizons.
- Artifact SHA-256 values match the result JSON.
- Repeated complete cached runs reproduce byte-identical CSV, deterministic gzip, PNG, and canonical JSON after excluding `generated_at`.
- Figure was visually inspected at original resolution; no clipping remains.

## Conclusion ceiling

The evidence supports only a narrow null: broad Wikimedia manipulation/retail-topic attention does not robustly explain cross-event variation in subsequent risk within the surviving portion of one retrospective SEC complaint.

It does **not** show that alleged manipulation dates lack crash risk. Secondary direct event-minus-control left-tail and gap estimates are positive. It also does not reject ticker-specific search/social/news attention, the JBF/JEF China quasi-experimental mechanism, or any causal manipulation channel.

## Nonblocking limitations retained in the artifacts

- Complaint allegations are neither convictions nor point-in-time labels.
- The complaint concerns one alleged trader and an odd-lot/order-book mechanism, not a social-media manipulation population.
- Current Yahoo availability loses 160 requested symbols and creates delisting/survivorship attrition.
- Wikimedia topic pageviews are market-wide, not firm-specific attention.
- A no-label matched day is not verified manipulation-free.

Final review verdict: `PASS`.
