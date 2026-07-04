# K1636 Codex Source Review

**verdict**: CONDITIONAL_PASS

## PASS / ISSUE

1. **Lookahead / lag**
   - PASS. Volume thresholds use prior rolling windows via `shift(1)`. Event date `t` is aligned to `next_ret = ret.shift(-1)`, and forward RV uses only returns `t+1..t+5`.
   - PASS. Same-day return is only an event condition / descriptive statistic, not prediction evidence.

2. **Statistical tests**
   - PASS. Event vs non-event uses Welch t-test, two-proportion z-test, Fisher exact p-value, and fixed-seed bootstrap.
   - PASS. Primary next-day tests are BH-FDR adjusted across 12 mean/proportion tests.
   - NOTE. The 5-day RV tests are secondary because the windows overlap; they support risk-conditioning language, not a direction/trading verdict.

3. **Event design**
   - PASS. High-volume events are rolling-percentile based; 2x-volume events are secondary robustness.
   - NOTE. `0050.TW` is an ETF proxy for Taiwan broad-market volume because `^TWII` index volume is not a clean traded volume series.

4. **Verdict honesty**
   - PASS. The result does not overclaim: next-day direction is null after FDR; volatility amplification is reported separately.
   - NOTE. 2330 high-volume raw p-values are opposite to the downside myth and do not survive BH-FDR, so they must not be promoted as a robust reversal strategy either.

## Blockers

None.

## Nice-to-have

- Add a future cross-sectional single-stock Taiwan panel if reliable TWSE volume data become available.
- If converting this into a strategy article, add open-to-close tradability robustness because full-day volume is only known after the close.
