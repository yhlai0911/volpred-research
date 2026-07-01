# Knowledge Handoff - K1599

Do not write this directly into `storage/memory/knowledge.json` without the main-thread K1259 writer gate.

## Proposed Entry

- id: `K1599`
- title: `Daily cross-ETF co-jump proxy improves HAR-style volatility forecasts`
- status: `supported_daily_proxy`
- source_experiment: `experiments/k1599`
- data: 12 ETF adjusted closes from `experiments/k1552/data/prices.parquet`, OOS from 2016
- primary_result: Lagged daily co-jump proxy features improve next-day squared-return QLIKE forecasts versus HAR and own-jump HAR baselines.

## Evidence

- Jump detection: daily BNS-style lagged bipower scale, threshold 2.5.
- Co-jump events: 236 days with at least 3 ETF jumps; 118 days with at least 6 ETF jumps.
- Mean QLIKE: HAR_CJ_proxy 2.2489, HAR_J_proxy 2.2638, HAR_daily 2.2915.
- HAR_CJ_proxy is best by mean QLIKE for all 12 ETF assets.
- Strict wins: 18 after Harvey |t| > 3 plus Holm 5pct; strict losses: 0.
- Event diagnostic: high co-jump days are followed by higher next-day market r2 (t=3.07, p=0.00239) and absolute return (t=4.60, p=6.68e-6).

## Safe Claim

Daily cross-ETF co-jump counts are an informative stress-state feature for next-day volatility forecasts in this ETF panel.

## Caveat

This is not high-frequency HAR-CJ replication. A paper-level claim needs synchronized 5-minute cross-ETF RV/BPV, formal BNS or Lee-Mykland co-jump flags, threshold sensitivity, and a full continuous-vs-jump decomposition.
