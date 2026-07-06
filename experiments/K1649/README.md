# K1649 — Expectile 型風險測度（EVaR / CARE）對照 quantile-VaR backtest

## 動機

Expectile 風險測度的吸引力是：它用 asymmetric least squares 估計，並在特定條件下兼具 coherent 與 elicitable 的理論特性。這個實驗不直接宣稱 expectile 一定比較好，而是問一個可檢定問題：

**在 TLT / HYG 日報酬的 VaR backtest 中，expectile-VaR 或 CARE 是否能在 OOS pinball loss 與 calibration 上，穩健打敗傳統 quantile-VaR baseline？**

這裡的 EVaR 指 expectile-based VaR，不是 entropic VaR。

## 文獻依據

- Newey & Powell (1987)：asymmetric least squares / expectile regression。
- Taylor / Kuan et al. CARE：conditional autoregressive expectile 與 expectile-based VaR。
- Bellini et al. (2014)：generalized quantiles / expectiles 作為 coherent risk measures。
- Fissler & Ziegel (2016)：elicitability 與風險測度 backtesting 脈絡。
- 2023 Basel III→IV expectile 討論：Expected Shortfall 與 expectile risk measures 的監理替代方案比較。

## 設計

| Spec | Value |
|---|---|
| Data source | Yahoo Finance adjusted close via `yfinance` |
| Data window | 2010-01-04 ~ 2026-07-02 |
| OOS window | 2015-01-01 起，common obs = 2891 / asset-alpha |
| Dependent assets | TLT, HYG |
| Targets | VaR 5%, VaR 1% |
| Refit | Quarterly expanding |
| Seed | 42 |
| Harvey threshold | `abs(t) > 3.0` |

### 模型

1. **HS250**：rolling 250-day empirical quantile。
2. **LinearQR**：`statsmodels.QuantReg`，covariates = `[rv5, abs_ret1, neg_ret1, ief_mom5, lqd_mom5, credit_chg5, vix]`。
3. **ALSExpectile-VaR**：expectile regression；每次 refit 以前的樣本用 unconditional expectile mapping 選 tau，使 in-sample violation rate 最接近 VaR alpha。
4. **CARE-SAV**：`e_t = b0 + b1 * |r_{t-1}| + b2 * e_{t-1}`，同樣用 alpha-mapped tau。

### Lookahead policy

- Covariates 明確使用 `signal = features.shift(1)`。
- HS250 明確使用 `y.shift(1).rolling(...).quantile(alpha)`。
- 所有 parametric refit 都使用 `df[df.index < ts]`，不含當天資料。
- Forecast parquet 保留 day-level `y`, `var`, `pinball_loss`, `violation`, `tau`，方便逐筆追溯。

## 成功標準

若 expectile 類模型（ALSExpectile-VaR 或 CARE-SAV）相對 LinearQR 至少在一個 asset-alpha 組合達到 Harvey `abs(t) > 3.0` 且 mean pinball loss 較低，才可宣稱 expectile 對 quantile-VaR 有實證 edge。

## 結果

### Mean pinball loss / violation rate

| Asset | Alpha | Best | HS250 | LinearQR | ALSExpectile-VaR | CARE-SAV |
|---|---:|---|---:|---:|---:|---:|
| TLT | 5% | CARE-SAV | 0.001003806 / 0.057420 | 0.000977414 / 0.051539 | 0.000972661 / 0.054998 | 0.000957958 / 0.050847 |
| TLT | 1% | LinearQR | 0.000314851 / 0.013490 | 0.000253264 / 0.012798 | 0.000267276 / 0.018679 | 0.000261034 / 0.014182 |
| HYG | 5% | LinearQR | 0.000600862 / 0.058803 | 0.000484023 / 0.039779 | 0.000488353 / 0.054306 | 0.000490961 / 0.058111 |
| HYG | 1% | CARE-SAV | 0.000219346 / 0.016257 | 0.000147909 / 0.006572 | 0.000147441 / 0.012798 | 0.000144279 / 0.009339 |

Cell format = `mean_pinball / violation_rate`。

### Expectile vs LinearQR DM tests

| Asset | Alpha | Pair | DM t | p | dbar | Harvey pass |
|---|---:|---|---:|---:|---:|---|
| TLT | 5% | ALSExpectile-VaR vs LinearQR | -0.865496 | 0.386838 | -0.000004752 | false |
| TLT | 5% | CARE-SAV vs LinearQR | -1.485225 | 0.137593 | -0.000019456 | false |
| TLT | 1% | ALSExpectile-VaR vs LinearQR | 1.910767 | 0.056133 | 0.000014012 | false |
| TLT | 1% | CARE-SAV vs LinearQR | 1.111046 | 0.266641 | 0.000007770 | false |
| HYG | 5% | ALSExpectile-VaR vs LinearQR | 0.539051 | 0.589893 | 0.000004330 | false |
| HYG | 5% | CARE-SAV vs LinearQR | 0.858231 | 0.390836 | 0.000006939 | false |
| HYG | 1% | ALSExpectile-VaR vs LinearQR | -0.097430 | 0.922391 | -0.000000467 | false |
| HYG | 1% | CARE-SAV vs LinearQR | -0.436337 | 0.662625 | -0.000003629 | false |

Negative dbar means the first model has lower loss. None passes the Harvey `abs(t) > 3.0` threshold.

### HS250 comparison context

HYG 5% 與 HYG 1% 顯示所有 covariate-aware / expectile-aware 模型都明顯優於 HS250 的方向：

- HYG 5%：ALSExpectile-VaR vs HS250 `t=-2.401131, p=0.016407`；CARE-SAV vs HS250 `t=-2.269933, p=0.023285`；LinearQR vs HS250 `t=-2.269704, p=0.023299`。
- HYG 1%：CARE-SAV vs HS250 `t=-2.161456, p=0.030742`；LinearQR vs HS250 `t=-1.777542, p=0.075584`。

但這不是本實驗的主要成功標準，因為公平 baseline 是 LinearQR，不是 HS-only。

## Verdict

`NULL_NO_EXPECTILE_EDGE_VS_LINEARQR`

Expectile / CARE 有時在 mean pinball loss 上略勝 LinearQR（TLT 5%、HYG 1%），也能改善 HS250；但 4 個 asset-alpha 中沒有任何 expectile-vs-LinearQR DM test 達到 Harvey `abs(t) > 3.0`。因此本實驗只能說 expectile 提供了有理論吸引力、calibration 可控的替代估計法，不能宣稱它在這個資料集上穩健打敗 quantile-VaR。

## 輸出

- `K1649.py` — reproducible script。
- `K1649_results.json` — authoritative results。
- `K1649_forecasts.parquet` — day-level forecasts and losses。
- `K1649_ohlc_cache.parquet` — yfinance adjusted close cache。
- `fig_k1649_mean_pinball.png` — mean pinball loss comparison。
- `fig_k1649_coverage.png` — violation rate vs target。

## References

- Newey, W. K., & Powell, J. L. (1987). Asymmetric Least Squares Estimation and Testing. https://www.jstor.org/stable/1911031
- Kuan, C.-M., Yeh, J.-H., & Hsu, Y.-C. Assessing Value at Risk with CARE, the Conditional Autoregressive Expectile Models. https://www.sciencedirect.com/science/article/abs/pii/S0304407608002236
- Bellini, F., Klar, B., Müller, A., & Rosazza Gianin, E. (2014). Generalized quantiles as risk measures. https://www.sciencedirect.com/science/article/abs/pii/S0167668713001698
- Fissler, T., & Ziegel, J. F. (2016). Higher order elicitability and Osband's principle. https://projecteuclid.org/journals/annals-of-statistics/volume-44/issue-4/Higher-order-elicitability-and-Osbands-principle/10.1214/16-AOS1439.short
- Zaevski, T. S., & Nedeltchev, D. C. (2023). From BASEL III to BASEL IV and beyond: Expected shortfall and expectile risk measures. https://ideas.repec.org/a/eee/finana/v87y2023ics1057521923001618.html
