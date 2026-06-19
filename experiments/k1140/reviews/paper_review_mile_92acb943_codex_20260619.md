# K1140 / mile_92acb943 Codex 24h Publication Review

- Article: `mile_92acb943` - "把上一個實驗再算一次，原本的『顯著』就不見了"
- Task: `paper_review_mile_92acb943`
- Source experiment: `experiments/k1140/`
- Reviewer: Codex
- Review date: 2026-06-19
- Verdict: **PASS**

## Bottom Line

The published article is supported by the committed K1140 artifacts. The central claim is correct: K1114's original 3-of-9 BH-FDR discovery count does not survive the stricter overlap-aware retest, and the strictest block-based layer has zero BH-FDR survivors.

No public correction or results change is required.

## Claim-Evidence Match

| Article claim | Source check | Status |
|---|---:|---|
| K1114 originally had 3 significant results | `README.md` and K1140 inputs list UMC trend, MediaTek trend, and TSMC regime KS as the original K1114 BH-FDR passes | PASS |
| Rolling windows overlap heavily: 500-day window and 21-day step imply 479/500 overlap | `config.k1114_window_obs = 500`, `config.k1114_step_obs = 21`; article's 95.8% is consistent | PASS |
| HAC L=24 leaves only MediaTek trend as a BH-FDR survivor | `core_verdict.survivors_hac_L24_bh_fdr = ["MediaTek:trend"]`; L24 BH-adjusted p=0.0001356 | PASS |
| UMC is nominally significant at L=24 but not after BH-FDR | UMC L24 raw p=0.01434, BH-adjusted p=0.06451 | PASS |
| TSMC trend is not significant under HAC L=24 | TSMC L24 t=0.7563, p=0.4495, BH-adjusted p=0.8768 | PASS |
| The strictest block-based layer has zero BH-FDR survivors | `core_verdict.survivors_strictest_bh_fdr = []` | PASS |
| Strictest trend examples match the article | TSMC block p=0.4877, UMC block p=0.02120 and BH-adjusted p=0.1908, MediaTek block p=0.06059 and BH-adjusted p=0.2726 | PASS |

## Lookahead / Timing Audit

No lookahead issue was found.

K1140 is a retrospective robustness audit of K1114's stored rolling `theta2_series`; it does not create a trading signal, portfolio return, or backtest. The script only re-tests trend, Spearman association, and regime KS evidence on the existing series with HAC, block permutation, effective-n, and BH-FDR layers.

The generic `scripts/lookahead_audit.py` scan does not flag `experiments/k1140/k1140.py`.

## Statistical Claims

The article's statistical language is appropriately conservative. It distinguishes:

- HAC L=24: one surviving trend finding, MediaTek.
- Strictest block-based layer: zero surviving findings across the nine tested labels.
- The resulting interpretation: K1114 should be treated as a warning about overlapping rolling-window dependence rather than as three stable effects.

This matches `k1140_results.json` and avoids overstating the remaining MediaTek HAC result after the stricter block-based retest.

## Reproducibility / Provenance Caveat

K1140 has the required experiment triad:

- `experiments/k1140/README.md`
- `experiments/k1140/k1140.py`
- `experiments/k1140/k1140_results.json`

The script uses fixed random seed `42`, `N_PERM = 5000`, and block size `24`. I did not rerun the full script during this review because `k1140.py` rewrites result timestamps and plot files; this review verifies committed source/results/article consistency.

One terminology caveat: the source and article sometimes call the strictest trend layer "block-bootstrap" or "區塊重抽", but the implemented null test shuffles blocks without replacement and stores the p-value as `block_perm_p`. The numeric claims are still supported. Future technical documentation should call this a block-permutation or block-shuffle test unless the implementation changes to bootstrap resampling with replacement.

## Verification

- `uv run python -m py_compile experiments/k1140/k1140.py` passed.
- `uv run python scripts/lookahead_audit.py --json` reported no K1140 finding.
- Deterministic JSON checks confirmed the L24 HAC table, strictest BH-FDR table, and `k1114_3_of_9_pass_fully_collapses = true`.

## Verdict

`PASS`.

The public article can remain published. No source or content correction is required.
