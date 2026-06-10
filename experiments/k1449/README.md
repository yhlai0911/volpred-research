# K1449: CPER 銅波動率是否領先 SPY 未來波動？

- **K id**: K1449
- **Status**: completed
- **Created**: 2026-06-10
- **Task source**: `research_vol_cper_vol_vol_lead_lag_vol_yfinance_lag`

## Question

`CPER` 可視為零售可得的銅價格 proxy。
這題檢驗的是：

- `CPER` 自身的 **trailing 21d realized vol**
- 是否對 `SPY` **未來 21d realized vol**

存在乾淨、可重現的 **lead-lag** 關係。

更具體地說：

1. 銅波動升高後，股市未來波動會跟著升高嗎？
2. 還是這只是與 VIX 同步的風險狀態，沒有增量資訊？
3. 若有訊號，方向是 risk-on cyclicality 還是 contrarian mean reversion？

## Motivation

「Dr. Copper」通常是景氣方向的敘事，
但這題問的是更窄的版本：

**銅的波動率本身，是否能領先股市波動率？**

這和價格方向不同。
如果銅波動只是和整體風險狀態同時反應，
那麼加上 `VIX_{t-1}` 後，訊號應該會消失。

## Literature Preamble

本題對齊的文獻 / 理論背景：

1. **Kilian (2009)**  
   commodity shocks 需區分需求面與供給面；銅並不是單純的 growth proxy。

2. **Corsi (2009)**  
   realized volatility 有明顯持續性，因此 lead-lag 題若用重疊視窗，必須小心自相關。

3. **Patton (2011)**  
   波動比較必須重視 loss / inference 規格；這裡因此主檢定採 HAC，而不是 naive t-test。

另外，專案既有發現 **K422** 已指出：
銅期貨波動對未來 equity vol 的關係偏向 **負向 / contrarian**，
所以 K1449 是用 `CPER` ETF proxy 做更乾淨的 lagged 驗證。

## Data

- Source: `yfinance`
- Tickers: `CPER`, `SPY`, `^VIX`
- Period: 2010-01-01 to 2026-06-09

## Method

### Predictor

- `CPER` trailing 21d realized volatility
- 正式進模型用 `t-1`：
  - `cper_rv_lag1`
  - `cper_rv_z_lag1`

### Outcome

- `SPY` **forward 21d realized volatility**
- 由 `t+1 .. t+21` 的報酬計算

### Lookahead protection

- predictor 一律 `.shift(1)`
- control 變數 `VIX` 也用 `vix_lag1`
- outcome 明確使用未來報酬窗，不碰 same-day return

### Inference

主檢定：

- `SPY_fwd_rv21 ~ cper_rv_lag1`
- `SPY_fwd_rv21 ~ cper_rv_lag1 + vix_lag1`
- `SPY_fwd_rv21 ~ cper_rv_z_lag1 + vix_lag1`
- `SPY_fwd_rv21 ~ high_cper_vol + vix_lag1`

全部都用：

- **OLS + Newey-West HAC**
- `maxlags = 21`

原因：

- forward 21d RV 是重疊 outcome
- 若用 iid 標準誤，顯著性很容易被誇大

另外補：

- lag `-5 .. +5` 的 cross-correlation
- moving-block bootstrap 95% CI
- `seed = 42`

## Files

- `k1449.py`
- `k1449_results.json`
- `figures/lead_lag_and_timeseries.png`

## Main Results

- Sample: `2012-12-18` to `2026-05-07`, `n=3,366`
- `CPER` trailing RV 平均 `24.35%`
- `SPY` forward 21d RV 平均 `14.24%`
- `CPER RV_{t-1}` 與 `SPY forward RV_t` 的簡單相關只有 `0.057`

### Lead-lag cross-correlation

- `lag = -1`（CPER 領先 1 天）相關 `0.057`
- moving-block bootstrap 95% CI: `[0.003, 0.162]`

這表示方向上不是完全 0，
但效果量非常小，而且單靠 cross-correlation 不能當正式證據。

### HAC regressions

1. **單變量**
   - `SPY_fwd_rv21 ~ cper_rv_lag1`
   - `coef = +0.0252`, HAC `p = 0.123`

2. **加上 `VIX_{t-1}` 控制**
   - `SPY_fwd_rv21 ~ cper_rv_lag1 + vix_lag1`
   - `cper_rv_lag1 coef = -0.0034`, HAC `p = 0.788`
   - `vix_lag1 coef = +0.7748`, HAC `p ≈ 9.2e-15`
   - `R² = 0.318`

3. **z-score 版本**
   - `cper_rv_z_lag1 coef = +0.0032`, HAC `p = 0.331`

4. **高銅波動 bucket**
   - `high_cper_vol (z>1.5)` coef `= +0.0084`, HAC `p = 0.651`

### Multiple testing

- 4 個 primary tests
- Bonferroni / BH 後 **0/4 survive**
- 最小 raw p 也只有 `0.123`

## Verdict

**NULL**

結論很直接：

1. `CPER` 波動對 `SPY` 未來波動的 lead-lag 效果量很小
2. 一旦控制 `VIX_{t-1}`，`CPER` 訊號幾乎完全消失
3. 所以「Dr. Copper 在 vol 維度領先股市」這個說法，在日頻 `CPER` proxy 上 **不成立**

較合理的解讀是：

- 銅波動頂多是弱的同步 risk-state proxy
- 真正穩健的短期股市波動訊號仍是 `VIX`

## Reproduce

```bash
uv run python experiments/k1449/k1449.py
```

## Honest Limits

- `CPER` 是 ETF proxy，不是 LME / COMEX 現貨與期貨完整結構
- 日頻資料無法辨識「美股收盤後、亞洲開盤前」這種更細的訊息傳遞
- 若要做更強的結論，下一步應補：
  - `HG=F` futures robustness
  - 與 `HYG-LQD` / `MOVE` / `VVIX` 的 head-to-head incremental race
  - rolling OOS window，看訊號是否只存在於單一危機期
