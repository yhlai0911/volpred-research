# Codex Review — K1631

**Review date**: 2026-07-05  
**Reviewer**: Codex  
**Verdict**: `CONDITIONAL_PASS`

## Findings

No blocking correctness issues found.

Residual limitations that must stay in the write-up:

1. **Primary all-time-high event count is small**: `today_all_time_high_cool20`, 20-day horizon has `n_event=10`. The correct conclusion is "no robust support for a top signal", not "margin highs are proven harmless."
2. **TWSE 今日餘額 may be revised**: main analysis uses `today_balance_kntwd`, while robustness uses `prev_balance_kntwd`. The robustness result keeps the same return-null direction, so this is disclosed rather than blocking.
3. **0050.TW is a proxy**: the experiment tests large-cap Taiwan equity exposure, not official TAIEX or a stock-level panel. README caveat is required and present.

## Code Checks

- 0050.TW price series is loaded from local `price_cache.db` and passed through `clean_tw50_data` before returns are computed: `k1631.py:85-100`.
- TWSE market margin balance parsing explicitly selects the market-wide `"融資金額(仟元)"` row, not the share-count row: `k1631.py:104-122`.
- Lookahead guard is explicit: forward returns and volatility use `ret_log.shift(-1)` through `ret_log.shift(-h)`, so same-day returns are excluded: `k1631.py:210-217`.
- High-event definitions compare against prior maxima only via `balance.shift(1)`, so the current day is not included in its own threshold: `k1631.py:221-233`.
- Overlapping forward-return tests use Newey-West HAC with `maxlags=horizon`: `k1631.py:248-253` and `k1631.py:291-292`.
- Bootstrap is seeded (`seed=42`) and uses moving blocks for the primary return-difference CI: `k1631.py:327-360`.

## Result Consistency

Primary 20-day all-time-high result:

- Return diff event minus other: `+2.93pp`
- HAC t: `+1.42`, p=`0.155`
- Bootstrap 95% CI: `[-1.39pp, +7.37pp]`
- Down probability: `40.0%` vs `35.5%`, Fisher p=`0.751`
- Volatility diff: `+8.21pp` annualized, HAC t=`+3.31`

This supports the README conclusion:

> 融資餘額創高不是可靠見頂訊號，但可能是「後面更容易震」的風險提示。

## Required Wording Guard

Do not publish a headline claiming "融資餘額創高後會漲". The positive return point estimate is not statistically robust and primary `n_event=10` is small.
