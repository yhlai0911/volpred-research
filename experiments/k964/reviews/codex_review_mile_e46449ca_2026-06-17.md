# Codex 24h-rule review — K964 / mile_e46449ca

- Reviewer: Codex CLI (codex exec, gpt-5.4 medium)
- Review date: 2026-06-17 19:14 台灣時間
- Article: 「財報季來了，股市真的比較動盪？20年數據說：沒這回事」(daily_article, published 2026-06-17 09:01)
- Source file audited: `experiments/K964/k964_earnings_vol.py` (432 lines)
- Results JSON: `experiments/K964/k964_earnings_vol_results.json`
- Tokens used: 118,892

## VERDICT: CONDITIONAL_PASS — keep live with wording softening

## Findings

1. **No fatal lookahead in main OLS.** `vix_lag1 = df['vix'].shift(1)` before regression (line 183). RV20 `rolling(20).mean()` of squared returns includes t and prior, not future (line 62-63). Caveat: high/low VIX *conditional buckets* use same-day VIX to classify same-day |abs_return| (line 231-234) — keep descriptive only, not tradable.

2. **Headline stats match code/results.** Welch |ret| p=0.5777 / RV20 p=0.7633 match JSON (line 84-92). OLS beta=0.002798, t=1.795, p=0.0726 matches (line 113-117). No abs-vs-squared swap.

3. **Units labelling caveat.** RV20 = `mean(sq_return) × 252` = annualized realized **variance** (no √). Article/figures should not describe RV20 as annualized volatility without clarifying.

4. **VIX control is dimensionally weak.** Regressing annualized variance on VIX level (line 188-190) works as rough control but better: `(VIX/100)²`, `log(RV) ~ log(VIX)`, HAC/Newey-West SE (RV20 overlaps heavily; HC1 only handles heteroskedasticity not serial correlation).

5. **Quarter story = exploratory, not proven cancellation.** Q4/Q1 strong, Q3 t=2.765 < Harvey |t|>3 (Bonferroni 5% survives). "Calendar seasonality cancellation" needs month fixed effects or actual earnings-date intensity — sign interpretation alone is over-reading.

6. **Earnings window proxy broad & contaminated.** Fixed Jan10-Feb15 etc. = 2,079 days = 41% of sample. Plausible for broad "season" coverage, weak as actual S&P 500 reporting-cluster treatment. Late reporters, preannouncements, post-window effects contaminate controls.

## Article-Level Corrections Needed

- Replace "VIX sufficiency confirmed" → "under this broad fixed-calendar earnings-season proxy, K964 finds no robust incremental SPY-level effect after lagged VIX control."
- Clarify RV20 is realized variance (not vol).
- Label per-quarter results as exploratory.

## Specific Lookahead / Methodology Concerns

No fatal forward-looking RV window. Main VIX control is lagged. Same-day VIX regime split and overlapping RV20 + HAC omission are the main methodology caveats.

## Approve Keeping Live?

**Y, with caveats.** Core NULL result is numerically supported. Article should soften "VIX sufficiency" and "calendar cancellation" claims.

## Follow-up

- Patch article wording (2 places — "VIX sufficiency" + "calendar cancellation"). Done by hourly-19 in same tick.
- Knowledge entry: K964 CONDITIONAL_PASS, reviewer=Codex 24h-rule.
- No script-level patch required (NULL result robust to caveats; HAC/Newey-West would refine SE but not flip conclusion).
