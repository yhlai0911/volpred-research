# K1450: VNQ 在升息/降息 regime 下更像股票還是債券？

- **K id**: K1450
- **Status**: completed
- **Created**: 2026-06-10
- **Task source**: `research_reit_vnq_realized_vol_regime_reit_yfinance`

## Question

這題要回答的不是長期配置，
而是更窄的短期波動問題：

- 在 **升息** vs **降息** regime 下，
- `VNQ` 的未來 21 日 realized vol 是否有系統性差異？
- `VNQ` 與 `SPY` / `TLT` 的未來 21 日相關性是否改變？

如果 `VNQ` 在 rate-up regime 明顯更貼近 `SPY`、更遠離 `TLT`，
可以把它理解成「利率壓力下更像 equity risk sleeve」。

## Motivation

REIT 很容易被口頭上說成「半股半債」，
但這種說法需要拆開看：

1. **報酬來源** 可能帶有利率敏感度
2. **短期波動與共動** 卻未必像債券

因此這題直接看 forward RV 和 forward correlation，
避免只從總報酬敘事下結論。

## Literature Preamble

這題對齊三個方向：

1. **Ling and Naranjo (1999)**  
   REIT 與股票 / 利率因子都相關，但不是純 bond proxy。

2. **Petkova and Zhang (2005)**  
   style / macro sensitivity 會隨經濟狀態改變，意味著 REIT 的 risk loading 可能 regime-dependent。

3. **專案既有發現 K64 / K349 / reit_vol_article**
   - VNQ 與 SPY 長期相關高
   - 2022 升息期 VNQ 受壓明顯
   - 但「像股票還是像債」需要用條件相關與波動正式檢定

## Data

- Source: `yfinance`
- Tickers: `VNQ`, `SPY`, `TLT`, `^TNX`
- Period: 2005-01-01 to 2026-06-09

## Method

### Rate regime

- 訊號：`^TNX.diff(63).shift(1)`
- `rate_up`: lagged 63d 10Y yield change > 0
- `rate_down`: lagged 63d 10Y yield change <= 0

用 `shift(1)` 保證 day `t` 只使用 `t-1` 已知的利率資訊。

### Outcomes

- `VNQ` forward 21d realized vol
- `SPY` forward 21d realized vol
- `TLT` forward 21d realized vol
- `VNQ-SPY` forward 21d correlation
- `VNQ-TLT` forward 21d correlation

全部 outcomes 都用 `t+1 .. t+21` 報酬，
避免 same-day leak。

### Inference

主檢定：

- `OLS(outcome ~ rate_up_dummy)` with **HAC / Newey-West**
- `maxlags = 21`

原因：

- forward 21d RV / corr 都是重疊視窗
- 若用 iid 標準誤，顯著性容易被誇大

Multiple testing:

- 5 個 primary contrasts
- Bonferroni 與 BH 一起報告

## Files

- `k1450.py`
- `k1450_results.json`
- `figures/vnq_rate_regime_summary.png`

## Main Results

- Sample: `2005-04-06` to `2026-05-07`, `n=5,301`
- Regime counts almost perfectly balanced:
  - `rate_down`: `2,651`
  - `rate_up`: `2,650`

### Forward RV

- `VNQ` forward RV:
  - `rate_down`: `23.85%`
  - `rate_up`: `19.76%`
  - HAC `p=0.0599`

- `SPY` forward RV:
  - `rate_down`: `16.99%`
  - `rate_up`: `14.44%`
  - HAC `p=0.0355`

- `TLT` forward RV:
  - `rate_down`: `13.98%`
  - `rate_up`: `13.22%`
  - HAC `p=0.221`

解讀：
方向上是 `rate_down` regime 的 forward RV 較高，
但經多重比較後，這些 RV 差異都不夠穩健。

### Forward correlation

- `VNQ-SPY` forward correlation:
  - `rate_down`: `0.625`
  - `rate_up`: `0.628`
  - HAC `p=0.897`

- `VNQ-TLT` forward correlation:
  - `rate_down`: `-0.077`
  - `rate_up`: `+0.041`
  - HAC `p=0.0030`
  - Bonferroni-adjusted `p=0.0150`

這是本題唯一穩健結果：

- 在 `rate_down` regime，`VNQ` 對 `TLT` 還帶有些微負相關
- 在 `rate_up` regime，`VNQ-TLT` 轉成接近零到小幅正相關

### Multiple testing

- 5 個 primary contrasts
- Bonferroni / BH 後 **只有 1/5 survive**
- survive 的是：
  - `fwd_corr_vnq_tlt`

## Verdict

**CONDITIONAL_PASS**

最精確的結論不是「VNQ 在升息期更像股票」，
而是：

1. `VNQ-SPY` 相關性本來就高，而且在升降息 regime 間幾乎不變
2. 真正會變的是 `VNQ-TLT` 關係：升息 regime 下，REIT 與長債的負相關消失，甚至微幅轉正
3. 所以 `VNQ` 的短期身份更像是：
   - **本質上一直偏 equity-like**
   - 但在 rate-up regime 會 **更明顯失去 bond-like hedge 關聯**

## Reproduce

```bash
uv run python experiments/k1450/k1450.py
```

## Honest Limits

- `^TNX` 是 Yahoo 10Y yield proxy，不是完整 Fed path / futures-implied policy path
- `rate_up` / `rate_down` 只用 63d sign，屬低自由度 descriptive regime，不代表最優利率 state machine
- 這題回答的是短期波動與共動，不直接等於 REIT 長期 expected return
