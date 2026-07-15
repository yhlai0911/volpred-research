# K1386 methodology-repair independent review — PASS

- Reviewed at: 2026-07-15T20:57:49+08:00
- Reviewer: Codex fresh-context independent reviewer / GPT-5
- Frozen base commit: `51f0aaae0ac11b6a50a4a69943e0f4be82bf0518`
- Verdict: **PASS**
- Blocking defects: none

## Verification performed

The reviewer independently reran the repaired experiment and verified that the
core artifact hashes were stable. The review confirmed:

- canonical actual-first QLIKE and
  `volpred.stats.model_evaluation.dm_test`, with no local h=1 DM helper;
- a frozen 2026-05-19 endpoint and hash-pinned analysis slice;
- rejection of conflicting duplicate-date rows, removal only of
  value-identical duplicates, a one-to-one merge, and unique increasing dates;
- HAR fitting only on origins whose next-day target remains inside IS;
- strict forecast-origin equality, finite positive forecasts, and explicit
  origin-t versus target-t+1 scoring;
- atomic chart, NumPy loss-array, and results-JSON writes;
- README/results numerical and directional consistency;
- protocol-specific limitations and no claim against rough-volatility models
  generally;
- all four scoped experiment-integrity gates pass.

## Independently verified headline results

The cleaned frozen sample has 3,021 IS observations, 1,098 OOS forecast
origins, and 1,097 evaluated rows. Canonical QLIKE is 0.37534907 for HAR,
0.47163477 for the fGN-motivated univariate approximation, and 0.47314873 for
the multivariate approximation.

| Comparison | HAC lag | DM t | p | loss-diff ACF(1) | `|t|>3` |
|---|---:|---:|---:|---:|:---:|
| fGN-uni vs HAR | 11 | 3.437383 | 0.000609 | -0.044616 | PASS |
| fGN-multi vs HAR | 11 | 3.452342 | 0.000577 | -0.050840 | PASS |

Positive t means the fGN approximation has higher QLIKE loss. The qualitative
verdict remains `NULL_NO_FGN_IMPROVEMENT`; the correction does not establish
that rough-volatility models are generally inferior.

## Additional artifact hashes

- `k1386_loss_har.npy`:
  `1324bd08755579b968a1167d87e9d303a8c7c4ceb3948108a9f17f119924f57d`
- `k1386_loss_fgn_uni.npy`:
  `95827578b3604185006604ed71d115c6ef27826667d67aec4f1754540e88bfb8`
- `k1386_loss_fgn_multi.npy`:
  `9fe0530a7bc640a84b96045359164a72179d0039f88fe31db5436104ceffeb0c`
