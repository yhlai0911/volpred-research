# K1451: HYG−LQD 信用利差代理能領先 SPY 未來波動嗎？

- **K id**: K1451
- **Status**: completed
- **Created**: 2026-06-10
- **Task source**: `research_vol_hyg_lqd_spread_spy_realized_vol_lead_lag_yfi`

## Question

這題用純 `yfinance` 可取得的信用風險代理：

- `HYG` = high yield corporate bond ETF
- `LQD` = investment grade corporate bond ETF

檢驗 `HYG/LQD` 的 22 日變化在 `t-1` 是否能預測：

- `SPY` 未來 21 日 realized volatility

也就是說，信用市場的風險偏好變化，
是否在 vol 維度上 **領先** 股市。

## Motivation

如果信用利差真是更早反應風險偏好的市場，
那麼 `HYG` 相對 `LQD` 的弱勢應該先發生，
接著才看到股市未來波動升高。

但專案既有多條線都指向同一個疑問：

- 信用利差可能只是和 `VIX` 同步惡化
- 真正增量訊號很小，甚至被 `VIX` 完全吸收

所以這題的核心不是找出任何微弱相關，
而是問：

**控制 `VIX_{t-1}` 後，信用利差代理還剩多少資訊？**

## Literature Preamble

本題對齊三個方向：

1. **Collin-Dufresne, Goldstein, and Martin (2001)**  
   信用利差會受共同風險因子主導，不只是公司基本面。

2. **Campbell and Taksler (2003)**  
   equity volatility 與 credit spread 關聯很深，但方向不必然代表信用市場先領先。

3. **專案既有 K348 / K872 / T14**
   - credit spread 方向上和 future vol 有些關聯
   - 但多次看到被 `VIX` 吸收，經濟意義偏弱

## Data

- Source: `yfinance`
- Tickers: `HYG`, `LQD`, `SPY`, `^VIX`
- Period: 2007-01-01 to 2026-06-09

## Method

### Predictor

- `signal_t = log(HYG/LQD).diff(22).shift(1)`

直觀上：

- `HYG/LQD` 下跌 = 高收益債相對投資級走弱 = 信用風險偏好轉差

另外補兩個變體：

- z-score 版本
- `wide_credit_stress` bucket（signal 落在歷史 20% 最差尾端）

### Outcome

- `SPY` forward 21d realized vol
- 由 `t+1 .. t+21` 報酬計算

### Lookahead protection

- predictor 一律 `shift(1)`
- `VIX` control 用 `vix_lag1`
- outcome 明確用 forward window，不碰 same-day return

### Inference

主檢定：

- `SPY_fwd_rv21 ~ signal`
- `SPY_fwd_rv21 ~ signal + vix_lag1`
- `SPY_fwd_rv21 ~ signal_z + vix_lag1`
- `SPY_fwd_rv21 ~ wide_credit_stress + vix_lag1`

全部用：

- **OLS + Newey-West HAC**
- `maxlags = 21`

另外補：

- lag `-5 .. +5` cross-correlation
- moving-block bootstrap 95% CI
- `seed = 42`

## Files

- `k1451.py`
- `k1451_results.json`
- `figures/lead_lag_credit_spread.png`

## Main Results

- Sample: `2008-05-12` to `2026-05-07`, `n=4,526`
- `SPY` forward 21d RV 平均：`16.20%`
- `HYG/LQD` 22d lagged change 與 `SPY` future RV 的簡單相關：`-0.235`

這個負號代表：

- `HYG/LQD` 越弱（信用風險越差）
- 往後的 `SPY` realized vol 越高

方向上合理，但問題在於它是不是 **獨立於 VIX**。

### Lead-lag cross-correlation

- lag `-1`: `-0.227`
- lag `0`: `-0.235`
- lag `+5`: `-0.289`

方向上整排都偏負，
代表信用壓力和股市後續波動確實同向惡化。
但這本身仍不能回答「誰有增量資訊」。

### HAC regressions

1. **單變量**
   - `SPY_fwd_rv21 ~ hyg_lqd_chg22_lag1`
   - `coef = -1.114`
   - HAC `p = 0.025`

2. **加上 `VIX_{t-1}`**
   - `SPY_fwd_rv21 ~ hyg_lqd_chg22_lag1 + vix_lag1`
   - `hyg_lqd_chg22_lag1 coef = -0.041`
   - HAC `p = 0.868`
   - `vix_lag1 coef = +0.883`
   - HAC `p ≈ 6.5e-25`
   - `R² = 0.462`

3. **z-score 版本**
   - `hyg_lqd_chg22_z coef ≈ 0`
   - HAC `p = 0.999`

4. **stress bucket**
   - `wide_credit_stress coef = +0.0169`
   - HAC `p = 0.305`

### Multiple testing

- 4 個 primary tests
- 最小 raw p 是單變量 `0.025`
- 但 Bonferroni 後變成 `0.102`
- **0/4 survive**

## Verdict

**NULL**

最精確的結論是：

1. `HYG/LQD` 信用利差代理和未來股市波動確實有方向一致的關聯
2. 但這個關聯 **幾乎完全被 `VIX_{t-1}` 吸收**
3. 所以它不是穩健的獨立 lead-lag vol 訊號

換句話說，信用市場不是完全沒在先反應，
而是它提供的訊息在這個日頻設定下，
大多已經體現在 `VIX` 裡。

## Reproduce

```bash
uv run python experiments/k1451/k1451.py
```

## Honest Limits

- `HYG/LQD` 是 ETF proxy，不是真正的 option-adjusted spread
- ETF 價格混合了 duration、carry、fund flow 與信用風險，不是純 spread
- 若要更強 inference，下一步應補：
  - FRED OAS 對照版
  - 與 `MOVE` / `VVIX` / `VIX9D` 做 incremental horse race
  - expanding OOS regression 而不是單次全樣本 HAC
