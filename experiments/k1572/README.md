# K1572 — DNN Quantile VaR vs K1571 Baseline Plateau

## 動機

K1571 Stage 1 已建立公平 baseline plateau：在 TLT / HYG、OOS 2015-01-01 到 2026-06-26、monthly expanding refit、同一 lagged covariate set 下，LinearQR / HARQ / CAViaR-SAV 彼此 statistically indistinguishable。K1572 的問題是：加入 DNN quantile regression 後，是否能在**相同 information set**下打敗這個 plateau？

本實驗只測「非線性函數形式是否有增量價值」，不讓 DNN 吃到額外特徵。

## 設計

| Spec | Value |
|------|-------|
| Parent | K1571 Stage 1 |
| Dependent assets | TLT, HYG |
| Data | yfinance adjusted close cache via `experiments/k1571/data_cache.parquet` |
| Data period | 2010-01-04 to 2026-06-26 |
| OOS window | 2015-01-01 to 2026-06-26 |
| OOS obs | 2,887 per asset-alpha |
| Targets | VaR(5%), VaR(1%) |
| Refit | Monthly expanding |
| Seed | 1571 |
| DNN features | `[rv5, ief_mom, lqd_mom, credit_chg, vix]` |
| Lag rule | K1571 `build_panel()` applies `.shift(1)` to every feature |
| DNN model | 5-input feed-forward quantile net, hidden sizes 16 and 8, ReLU, pinball loss |
| Training budget | 120 epochs per monthly refit, AdamW lr=0.01, weight_decay=1e-4 |

Baselines are HS250, LinearQR, HARQ, and CAViaR-SAV. The main plateau benchmark is `PlateauMedianLoss`: the pointwise median pinball loss across LinearQR, HARQ, and CAViaR-SAV.

## Baseline Validation

K1572 reuses K1571's panel construction, HS, QuantReg, DM, Kupiec, and Christoffersen helpers. For tractability, CAViaR-SAV keeps the same recurrence and monthly expanding refit but warm-starts monthly optimization from the prior month's parameters. Validation against K1571 mean pinball:

| Asset-alpha | HS250 | LinearQR | HARQ | CAViaR-SAV |
|-------------|------:|---------:|-----:|-----------:|
| TLT_05 | 0.000% | 0.000% | 0.000% | +0.005% |
| TLT_01 | 0.000% | 0.000% | 0.000% | -1.504% |
| HYG_05 | 0.000% | 0.000% | 0.000% | -0.033% |
| HYG_01 | 0.000% | 0.000% | 0.000% | +0.079% |

CAViaR warm-start had 138 refits per asset-alpha and zero non-success refits.

## Results

Negative edge means DNN has lower mean pinball loss. Positive edge means DNN is worse.

| Asset-alpha | DNN mean pinball | Plateau mean | DNN vs plateau | DM t | DM p | DNN vs HS250 | DM p vs HS250 |
|-------------|-----------------:|-------------:|----------------:|-----:|-----:|-------------:|--------------:|
| TLT_05 | 0.00098793 | 0.00096115 | +2.79% | +1.128 | 0.259 | -1.60% | 0.700 |
| TLT_01 | 0.00027314 | 0.00026076 | +4.75% | +1.147 | 0.251 | -13.34% | 0.302 |
| HYG_05 | 0.00051282 | 0.00048397 | +5.96% | +2.535 | 0.011 | -14.63% | 0.033 |
| HYG_01 | 0.00015667 | 0.00014659 | +6.87% | +0.754 | 0.451 | -28.65% | 0.016 |

Aggregate verdict: `NULL_OR_WORSE_VS_PLATEAU`.

## Interpretation

DNN-QR beats HS250 on all four mean pinball comparisons, but that is the wrong claim target: K1571 already showed HS250 is an easy and sometimes mis-calibrated baseline. Against the fair covariate-aware plateau, DNN-QR is worse in all four asset-alpha cells. The strongest result is HYG VaR(5%), where DNN is 5.96% worse than plateau median and the DM test rejects equality in the wrong direction (p=0.011).

This supports the K1571 null claim: in this setup, the literature-style "DNN beats historical simulation" result can be a weak baseline artifact. With the same lagged covariates and same monthly expanding information set, this small DNN does not show real nonlinear information gain.

## Limitations

- This is a constrained feed-forward DNN, not a full RNN/CAR-CARNN architecture.
- CAViaR in K1572 is warm-started for runtime, not byte-identical to K1571's six-start-per-month optimizer; the validation table quantifies the resulting mean-pinball drift.
- Only TLT and HYG are tested, matching K1571. The conclusion should not be generalized to equities, intraday data, or option-implied features.
- The evaluation is VaR pinball loss and VaR calibration. ES/Fissler-Ziegel joint scoring is not added here.

## Outputs

- `k1572.py` — reproducible script
- `k1572_results.json` — formal results and validation metadata
- `fig_k1572_cumulative_pinball.png` — cumulative pinball loss by asset-alpha
- `fig_k1572_dnn_edges.png` — DNN mean pinball edge vs plateau and HS250

## References

- Taylor (2000), quantile regression neural networks for conditional return distributions: https://doi.org/10.1002/1099-131X(200007)19:4%3C299::AID-FOR775%3E3.0.CO;2-V
- Engle and Manganelli (2004), CAViaR: https://doi.org/10.1198/073500104000000370
- Diebold and Mariano (1995), predictive accuracy tests: https://doi.org/10.1080/07474939508800353
- Harvey, Leybourne and Newbold (1997), small-sample forecast accuracy correction: https://doi.org/10.1016/S0169-2070(96)00719-4
