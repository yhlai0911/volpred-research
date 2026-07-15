# K1378 post-run independent review — PASS

- Reviewed at: 2026-07-15T18:55:49+08:00
- Reviewer: Codex fresh-context independent reviewer / GPT-5
- Frozen base commit: `811a6283cb4c8263d4452f52b7fbcd1e8872981a`
- Verdict: **PASS**
- Blocking defects: none

## Verification performed

The reviewer independently reconstructed the fixed OOS date index and recomputed
all five period results from the four saved arrays. QLIKE means, Bartlett-HAC DM
statistics and p-values, ACF(1–5), every lag-sensitivity cell, and HLN diagnostics
matched `k1378_results.json`. A deterministic in-memory replay reproduced both
loss arrays exactly, with 30/30 successful refits and 1,854/1,854 positive finite
forecasts.

The review also verified:

- actual-first QLIKE and shared scoring mask;
- day-t forecasts use only day-t−1 return and VIX;
- identical A4f `tau_t(VIX_{t-1})` normalization in fit, refit-state rebuild,
  and OOS recursion;
- optimizer rejection of unsuccessful, non-finite, penalized, or infeasible
  A4f candidates, with all-start failure terminating the run;
- hash-pinned unique-date input, fixed analysis endpoint, and exact period
  partitions;
- atomic arrays, results JSON, and chart writes;
- README/results/chart numerical and directional consistency;
- no import or numeric transplant from K1393; K1378's broad window remains
  distinct from Paper 9's narrow K1393 window;
- all four scoped experiment integrity gates pass.

## Independently reconstructed headline cells

| Period | n | A4f / GJR QLIKE | HAC lag | DM t | p |
|---|---:|---:|---:|---:|---:|
| Full | 1,852 | 1.399812 / 1.479503 | 13 | −4.370344 | 1.3093e−05 |
| Pre-COVID | 292 | 1.507945 / 1.576680 | 7 | −2.640236 | 0.008732 |
| COVID | 337 | 1.361748 / 1.473725 | 7 | −1.344156 | 0.179805 |
| Post-COVID | 1,223 | 1.384483 / 1.457894 | 11 | −4.921907 | 9.7424e−07 |
| No-COVID | 1,515 | 1.408279 / 1.480788 | 12 | −5.603420 | 2.4928e−08 |

## Additional artifact hashes

- `k1378_losses_a4f.npy`: `fb3cc5c3c84558e80da4491b0e87c03245b8fe07fd91106be62bca4577ab43e1`
- `k1378_losses_gjr.npy`: `3b69a6100aace1b96c83ab762c5818ea22e0cf0d95467830deaccf05e8dd868c`
- `k1378_valid_mask.npy`: `c77fef52457a4a360a75b0f91074f17e45aa9c396fa8c02dae028356d8a8215c`
- `k1378_no_covid_mask.npy`: `a7e5d3557dae5827296760a987d8cb5838448a8fa6a775103cd49d29c80dfd9a`
- `storage/drafts/assets/k1378_loss_gap_rolling.png`:
  `5617beb54072bb613d0ad45b5f93b002ed188f3786a0e4be1c769ccf6ce91db9`
- `storage/drafts/assets/k1378_period_gap_bars.png`:
  `20a4c6ac7bb23c295937af530b11f385a4a470ed3101a2b39b53a4fbf6721e07`

The README-only follow-up that listed the two article asset paths was hash
re-verified separately. Current README SHA-256 is
`52225eea354f0a2a74ded531ef0e7c9469300304f9b077de2f5a77a585d3b908`.
