# K570 Post-Publish Codex Review
**Article**: 財報季要降槓桿嗎？21 年 SPY 數據說：別自作聰明 (mile_9fb5d7f7)
**Published**: 2026-05-10
**Review date**: 2026-05-18
**Reviewer**: OpenAI Codex gpt-5.4 (primary path, session 019e37fd)

---

## Verdict: CONDITIONAL_PASS (with mandatory corrections)

Null result direction likely holds but evidence quality is compromised. Absolute performance numbers must be corrected before further citation.

---

## Findings

### 1. HIGH: Lookahead Bias in VT Execution
**Location**: `k570_earnings_season.py:170,200`

`weights` computed from `vix[t]` (same-day close) then applied to `ret[t]` (close-to-close return). For close-to-close returns, VIX close at day t is only known at day t close — cannot be used to set day t position.

**Correct fix**: `weights = f(vix.shift(1))` — use yesterday's VIX to set today's weight.

**Impact on conclusion**:
- Absolute performance numbers (15.1% annual return, Sharpe 1.43, MDD -14.7%) are not reliable
- `earnings_only` and `anti_earnings` have asymmetric lookahead exposure vs baseline (they use `weight=1` on certain days), making relative comparison less clean
- NULL result direction may still hold but **cannot use current backtest as evidence**

**Required action**: Rerun K570 with `vix.shift(1)` before citing numbers.

### 2. MEDIUM-HIGH: "DM Test" Terminology Incorrect
**Location**: `k570_earnings_season.py:253`

`dm_test_sharpe` computes HAC t-statistic on return differential, not a proper DM test on forecast loss differentials. Applying Harvey (2016) `|t| > 3` hurdle to this statistic is methodologically mismatched.

**Impact**: Weakens "statistically rigorous rejection" claims. Direction of null result is probably unaffected.

**Required action**: Rename to "HAC return-differential test" or implement proper loss-DM / Sharpe-difference test.

### 3. MEDIUM: Bootstrap Mis-specified
**Location**: `k570_earnings_season.py:288`

i.i.d. bootstrap ignores serial correlation and volatility clustering — CIs are likely too tight. Additionally, bootstrap uses arithmetic-mean Sharpe while main table uses geometric-annual Sharpe (inconsistent statistics).

**Required action**: Use block/moving/stationary bootstrap. Standardize Sharpe formula.

### 4. MEDIUM: "Non-overlapping OOS" Claim False
**Location**: `k570_earnings_season.py:84-88`

Test windows (2012-2017, 2016-2020, 2020-2025) overlap at 2016-2017 and 2020 boundaries. Also, no parameter is estimated from train windows — these are rolling subperiod checks, not genuine train/test OOS.

**Required action**: Change "3 non-overlapping OOS periods" to "3 overlapping subperiod robustness checks."

### 5. LOW-MEDIUM: Over-strong Inference Labels
- Plain `ttest_ind` on autocorrelated 21-day RV is not ideal (should use HAC t-test)
- "VIX remains the sufficient statistic" overstates — correct claim: "no earnings-season overlay shows robust improvement in this fixed-rule evaluation"
- Train/Test OOS framing is misleading (no parameters estimated from train window)

---

## Article Correction Plan

1. **Immediate**: Add disclaimer in article noting VIX lookahead implementation issue; flag performance numbers as preliminary pending correction
2. **Short-term**: Create K570b with `vix.shift(1)` fix + block bootstrap + corrected OOS labels
3. **Post-correction**: Update article with corrected numbers if null result confirmed; otherwise update conclusion

---

## Notes for knowledge.json
- Do NOT write a PASS knowledge entry for K570 until K570b corrected version is complete
- K570 currently has CONDITIONAL_PASS status: direction plausible but methodology needs repair
