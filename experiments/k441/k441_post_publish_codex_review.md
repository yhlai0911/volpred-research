# K441 Post-Publish Codex Review

- Review date: 2026-05-27
- Article: `mile_d0d66405` / `Range-Based 估計子作為 GARCH Proxy：哪一個最準？`
- Experiment: `experiments/k441/k441_range_vol.py`
- Results: `experiments/k441/k441_range_vol_results.json`
- Verdict: `NEEDS_REVISION`

## Findings

### 1. MAJOR — Article cites HLZ/strict significance framing, but code only runs a plain DM z-test

Article lines 68-71 say the GJR advantage is confirmed by a "HLZ 2016 嚴格統計門檻". The source does not implement Harvey / HLN / HLZ style small-sample correction or thresholding. It uses a custom `dm_test()` with Newey-West variance and Gaussian tail p-values only:

- `def dm_test(...)` at [k441_range_vol.py:375](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol.py:375)-[394](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol.py:394)
- p-values computed as `2 * (1 - norm.cdf(...))` at [line 393](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol.py:393)
- article-referenced Yang-Zhang / Garman-Klass DM numbers do exist in results at [k441_range_vol_results.json:276](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol_results.json:276)-[301](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol_results.json:301)

Required fix: rewrite the article as "plain DM-style comparison in this script shows ..." or upgrade the code/results to the claimed Harvey/HLZ procedure.

### 2. MAJOR — "Yang-Zhang proxy" is a custom full-sample-centered construction, not a standard per-day YZ estimator

The article presents Yang-Zhang as a standard proxy and makes it the centerpiece of the conclusion (article lines 60-62, 97, 107-121). But the implementation is a custom per-day decomposition using full-sample means and a full-sample `k`:

- `n = len(overnight)` and `k = ...` at [k441_range_vol.py:129](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol.py:129)-[130](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol.py:130)
- `overnight_mean = np.mean(overnight)` and `oc_mean = np.mean(oc)` at [line 135](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol.py:135)-[136](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol.py:136)
- `rv_yz = (overnight - overnight_mean)^2 + k*(oc - oc_mean)^2 + (1-k)*rv_rs` at [line 138](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol.py:138)-[140](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol.py:140)

This is not documented in the article. It does not prove a trading lookahead bug, but it is a methodology mismatch: the published narrative treats the proxy as canonical Yang-Zhang, while the code uses a sample-dependent approximation. Because the headline "best proxy" result depends on this construction, the article needs a disclosure or a rerun with a standard implementation.

### 3. MEDIUM — The lookahead audit language is stronger than the source-level evidence

Article lines 35-42 state the recursion is "嚴格走 t-1 → t" and implies the OOS comparison is clean. The code is directionally consistent with a 1-step-ahead GARCH workflow:

- fit split at [k441_range_vol.py:274](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol.py:274)
- OOS forecast call at [line 279](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol.py:279) and [line 302](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol.py:302)

But the script never validates forecast-date alignment against proxy dates. It computes `oos_dates` and then ignores it, relying on positional truncation only:

- `oos_dates = dates_pd[is_oos]` at [line 306](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol.py:306)
- alignment by `min_len` / slicing at [line 307](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol.py:307)-[317](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol.py:317)

Required fix: either add an explicit date-index alignment assertion in code, or soften the article's "strictly verified" wording.

## Verified Claims

- The main QLIKE matrix in article lines 48-55 matches `oos_evaluation` in results:
  - GARCH / CC `1.3216` at [k441_range_vol_results.json:116](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol_results.json:116)
  - GJR / Parkinson `0.3820` at [line 142](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol_results.json:142)
  - GJR / Yang-Zhang `0.2828` at [line 154](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol_results.json:154)
- `ranking_consistent = true` is present at [k441_range_vol_results.json:248](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol_results.json:248), so the article's "跨 proxy 排名一致" statement is supported by the stored artifact.
- CARR vs GJR Yang-Zhang comparison in article line 83 is supported by results:
  - CARR-Weibull Yang-Zhang QLIKE `0.4215` in `carr_evaluation`
  - DM stat `-4.6633`, p `3.11e-06` in `dm_carr_vs_gjr` at [k441_range_vol_results.json:420](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol_results.json:420)
- Efficiency / annualized-vol statements around article lines 92-97 are numerically supported:
  - Parkinson annualized vol `15.34%` at [k441_range_vol_results.json:22](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol_results.json:22)
  - Yang-Zhang annualized vol `19.42%` at [line 55](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol_results.json:55)
  - Parkinson efficiency multiple `6.81x` at [line 434](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol_results.json:434)
- GJR residual diagnostic claims in article line 101 are supported by `diagnostics`:
  - lag 10 `Q=9.27, p≈0.51` at [k441_range_vol_results.json:459](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol_results.json:459)
  - lag 20 `Q=12.54, p≈0.90` at [line 463](/Users/yhlai0911/Desktop/volpred-research/experiments/k441/k441_range_vol_results.json:463)

## Bottom Line

The stored numbers broadly match the article, and I did not find a source-level same-day signal bug analogous to prior lookahead incidents. The required revisions are methodological honesty revisions: the article currently overstates the exact test being run and understates that the published "Yang-Zhang" proxy is a custom implementation.
