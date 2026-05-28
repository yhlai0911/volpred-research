# K1321: VIXTWN Ratio Stability Checkpoint Before 252 Days

**Date:** 2026-05-26  
**Status:** COMPLETE  
**Research Question:** Q6 — 在官方 `VIXTWN` 累積到 252 個交易日前，`VIXTWN/VIX` ratio 是否仍可視為穩定常數？

## Motivation

`K1181` 用較早的官方樣本（Dec 2025–Apr 2026）得到：

- mean ratio = `1.3906`
- CV = `0.098`

之後 `K1308` 用較新的本地資料做中間更新，結論改為 ratio 顯著上升且不穩定。
但重新檢查本地檔案後發現：

1. `data/vixtwn/vixtwn_daily.csv` 含重複日期
2. `paper/taiwan-vt/data/...vix_2008-2026.csv` 的 `vix_close` 也含重複日期

如果不先去重，樣本數與均值都可能被虛增。`K1321` 的目的不是硬做出 252 天結論，
而是做一個更嚴格的 checkpoint：

- 明確去重規則
- 用目前本地可得資料重算
- 判斷距離「252 天正式驗證」還差多少

## Data

### Primary series

- `data/vixtwn/vixtwn_daily.csv`
  - official TAIFEX VIXTWN local store
  - raw rows = `117`
  - unique trading dates after de-dup = `112`
  - date range = `2025-12-01` to `2026-05-22`

- `paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv`
  - local VIX source via `vix_close`
  - contains duplicate dates in the late-May 2026 tail

### Cleaning rule

- parse `date`
- sort by `date`
- drop duplicated dates with `keep="first"`
- align on the intersection of trading dates

This rule is deterministic and documented. No manual data edits are applied.

## Method

1. Load VIXTWN and VIX from the two local files above
2. De-duplicate both series by date (`keep="first"`)
3. Compute `ratio_t = VIXTWN_t / VIX_t`
4. Report:
   - sample size
   - mean / median / std / CV / min / max
   - first-half vs second-half mean
   - OLS linear trend on trading-day index
   - one-sample t-test against `K1181` baseline mean `1.3906`
5. Compare with:
   - `K1181` baseline
   - `K1308` checkpoint narrative
6. Check whether the 252-day target has been reached

## Lookahead / Seed

- **Lookahead:** not applicable; this is a descriptive data audit, not a forecast
- **Seed:** `42` fixed for reproducibility policy consistency, though no stochastic procedure is used

## Success Criteria

For ratio to be considered provisionally stable before 252 days, all of the following would need to hold:

- mean remains close to `K1181` baseline `1.3906`
- CV stays low (roughly `<= 0.15`)
- no significant positive time trend

## Main Result

Using the cleaned local data as of `2026-05-22`:

- unique overlap `n = 111`
- mean ratio = `1.5326`
- median ratio = `1.4502`
- CV = `0.1896`
- first-half mean = `1.3787`
- second-half mean = `1.6837`
- OLS slope = `0.00662` per trading day, `p = 5.14e-20`
- one-sample t-test vs `1.3906`: `t = 5.14`, `p = 1.34e-06`

## Interpretation

The ratio is **not stable** under the currently available local sample:

1. the mean is materially above the earlier `K1181` estimate
2. dispersion rose from about `0.10` to about `0.19`
3. the second half is much higher than the first half
4. the time trend is strongly positive

At the same time, the **252-day target has not been reached**:

- current unique VIXTWN days = `112`
- progress = `44.4%`
- remaining days to 252 = `140`

So `K1321` should be read as a **checkpoint that rejects early stability**, not as the final one-year verification.

## Relation To Earlier Ks

- `K1181`: early official sample supported `1.3906`
- `K1308`: already suspected instability
- `K1321`: confirms that instability remains after stricter de-duplication, and shows that raw duplicate handling can overstate both `n` and mean

## Files

- `k1321.py` — main script
- `k1321_results.json` — machine-readable results
