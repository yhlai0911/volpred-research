# K1495 — Lagged Concentration Pulse and Forward Market Volatility

## Motivation

`K1418_concentration_dispersion_2026` 已經做過 contemporaneous 結構描述：集中度高的時代，個股 RV 可以遠高於指數 RV。但那個 evidence package 不是正式實驗，也沒有回答更嚴格的問題：

> 如果用 **可交易時點 t 已知** 的 concentration proxy（`SPY` 相對 `RSP` 的落後/領先）來看，之後 21 個交易日的市場波動是否真的更高？

本實驗把題目改寫成 **lagged regime test**，避免只停在同時點故事。

## Difference vs prior work

- `K1418`：同時點結構描述，主軸是「Top-5 vs SPY 的 RV gap」。
- `K1495`：lagged concentration proxy，主軸是「t 時點可見的 proxy 是否對 t+1..t+21 的 market vol 有條件資訊」。
- `K771` / `K809`：曾否證「高 dispersion → equal-weight 勝 SPY」的交易假說；本題不做 return timing，而做 **volatility regime**。

## Related knowledge / K

- `K1418`：集中度與個股/指數 RV 結構缺口（描述性）
- `K771`, `K809`：equal-weight / sector-dispersion 類交易假說多為 NULL 或方向相反
- `K1427`：dispersion 與 selloff 的描述性分解，提醒高 dispersion 不等於後續一定更平靜

## Literature consulted

1. *Granular Stock Market* (SSRN, 2025)  
   Rising concentration can transmit firm-level shocks into aggregate volatility.
2. *Actively Passive: The Rise of Market Volatility* (SSRN, 2026)  
   Index trading growth can structurally raise aggregate volatility.
3. *Volatility-Weighted Concentration and Effective Fragility in U.S. Equity Markets* (SSRN, 2025)  
   Equal-weight vs cap-weight divergence is a practical concentration-risk lens.
4. *The S&P Equal Weight Index Uses, Properties and Historical Experience* (S&P/SSRN, 2023)  
   Equal-weight index is a lower-concentration benchmark with different exposure profile.

## Hypothesis

- `H1`: 當 `SPY` 在過去 21 天明顯跑贏 `RSP`（cap-weight concentration pulse）時，未來 21 天 `SPY` realized volatility 較高。
- `H2`: 這個高 concentration regime 會放大 `SPY - RSP` 的未來 volatility gap。
- `H3`: 在控制當前 `SPY` 自身 21 日 vol 後，高 concentration dummy 仍保有正向增量。

## Data

- Source: `yfinance`
- Tickers: `SPY`, `RSP`
- Price field: adjusted daily close
- Sample start: `2003-05-01`（RSP 可用期）
- Sample end: script runtime cut

## Method

### Primary concentration proxy

- `conc_proxy_21d = sum_{i=t-20}^t (logret_SPY_i - logret_RSP_i)`
- 解讀：cap-weight 在近月相對 equal-weight 的 concentration pulse

### Regime rule

- `high_regime_t = 1[conc_proxy_21d >= expanding_q80_t]`
- expanding 80th percentile 只用 `t` 當下以前資料，避免 full-sample 門檻偷看未來

### Outcomes

- `fwd_rv21_spy`: `t+1..t+21` 的 `SPY` annualized realized vol
- `fwd_rv21_rsp`: `t+1..t+21` 的 `RSP` annualized realized vol
- `fwd_rv_gap = fwd_rv21_spy - fwd_rv21_rsp`
- `fwd_min_ret21_spy`: `t+1..t+21` 最差單日 log return
- `tail_event_top_decile`: `fwd_rv21_spy` 是否落在全樣本 top decile

### Inference

- Welch mean-difference test：只當輔助描述
- Stationary bootstrap：主要 CI / p-value（保留重疊視窗相依）
- HAC(21) regression：檢查 `high_regime` 在控制 `rv21_spy` 後是否仍有增量

## Anti-bug rules

- 所有 regime/proxy 都只用 `t` 以前資料
- 所有 forward outcome 從 `t+1` 開始，不含當日
- 固定 `seed=42`
- 重疊 21 日窗不用 iid bootstrap 充當正式 inference

## Success criteria

- `H1`: high regime 的 `fwd_rv21_spy` 均值 > non-high，且 bootstrap CI 不跨 0
- `H2`: `fwd_rv_gap` 高 regime 顯著更大
- `H3`: HAC regression 中 `high_regime` 係數為正且 `p < 0.05`

## Files

- `k1495.py`
- `k1495_results.json`
- `fig_concentration_proxy_and_forward_vol.png`
- `fig_high_vs_nonhigh_forward_vol_box.png`

## Results

有效樣本（扣除 rolling / expanding warmup 與 forward window）為 `2004-05-28` 到 `2026-05-13`，`n=5,524`。

### Group means

- High concentration regime:
  - future 21d `SPY` RV = `18.16%`
  - future 21d `RSP` RV = `19.45%`
  - future `SPY - RSP` vol gap = `-1.29 pp`
  - future top-decile vol event rate = `13.71%`
- Not-high concentration regime:
  - future 21d `SPY` RV = `14.41%`
  - future 21d `RSP` RV = `15.32%`
  - future `SPY - RSP` vol gap = `-0.90 pp`
  - future top-decile vol event rate = `8.50%`

### Formal tests

- `H1` PASS:
  - `SPY` future vol diff = `+3.75 pp`
  - Welch `t=9.47`, `p≈7.5e-21`
  - stationary bootstrap 95% CI = `[+0.95 pp, +7.39 pp]`
- `H2` FAIL:
  - `SPY - RSP` future vol gap 並未更寬
  - 點估計反而更負（`-0.39 pp`），bootstrap 95% CI 跨 0
- `H3` PASS:
  - HAC(21) regression: `fwd_rv21_spy ~ rv21_spy + conc_proxy_21d + high_regime`
  - `high_regime` 係數 `+2.03 pp`, `t=2.05`, `p=0.041`
  - robustness: 63d proxy high-regime 係數 `+2.63 pp`, `t=2.51`, `p=0.012`

## Verdict

`PARTIAL_PASS`

正確口徑不是「集中度升高會讓 cap-weight 指數獨有的 tail vol 裂口擴大」，而是：

1. `SPY` 相對 `RSP` 的 lagged concentration pulse，確實對 **未來整體市場波動升高** 有條件資訊。
2. 但這個效應同時也反映在 `RSP`，所以 **不是** `SPY` 對 `RSP` 的獨特 volatility widening。
3. 因此它比較像 **broad market turbulence regime descriptor**，不是乾淨的 `cap-weight tail fragility spread` 預測器。

## Codex review outcome

- Source-level review: `reviews/codex_review_20260614.md`
- Verdict: `PASS`
