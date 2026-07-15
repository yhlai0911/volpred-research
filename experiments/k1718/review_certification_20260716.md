# K1718 Codex review certification

Verdict: **PASS** for the bounded scientific claim that lagged US VIX does not pass the pre-registered robust incremental-forecast gate. This is not a strategy-deployment approval.

## Review scope

- Verified the information set: every VIX source date is strictly earlier than the Japanese target date; HAR-style local features end at `r2.shift(1)`; annual expanding fits train only through the prior calendar year.
- Verified the comparison contract: all six forecasts share one positive evaluation mask per asset, Patton QLIKE is the ranking loss, Clark-West is the primary nested-model test, and Holm correction covers all six cells. Canonical QLIKE DM output is labelled diagnostic and is not used for the verdict.
- Verified data handling: `auto_adjust=True` is explicit. The 1306.T repair is isolated, records before/after values, drops the unverified pre-2015 unit regime, and is supported by JPX and NEXT FUNDS primary-source disclosures for the 2026-04-01 1:10 split and 2026-03-30 trading adjustment.
- Re-ran the full experiment. The repaired TOPIX track has 19.80% annualized close-to-close volatility rather than the stale 99.79% vendor-break artifact; the final gate remains NULL at 0/6 passing cells.

## Defect found and resolved

The first full rerun exposed a blocking serialization defect: TOPIX repair diagnostics stored a `pandas.DatetimeIndex`, while `_json_safe` handled NumPy arrays but not pandas indexes. The results writer therefore failed after estimation. The serializer now covers `pd.Index`, and the regression test serializes the complete repair diagnostics including both rescaled dates.

## Verification

- `uv run pytest experiments/k1718/test_k1718.py -q` -> 3 passed.
- `uv run python experiments/k1718/k1718.py` -> `verdict=NULL, cells=0/6`.
- `uv run python scripts/experiment_gates.py run --path experiments/k1718` -> PASS across four integrity gates.
- Results/README agree on the 2015-01-05 common start, 2020/2022 stress coverage, 0/6 familywise result, and exploratory-only VT scope.

## Remaining bounded limitations

Daily squared returns remain noisy, the HAR-style model is not HAR-RV, the vendor normalization is snapshot-specific, and the exploratory open-to-next-open VT ledger does not match the close-to-close forecast target. These limits are disclosed and do not overturn the NULL conclusion.
