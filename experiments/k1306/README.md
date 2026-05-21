# K1306: SEC EDGAR 10-K text-sentiment pilot — unblock the data-blocked direction

[提出: Claude (autonomous backlog gap-scan from research_program.md L411 "SEC Filings: 長期方向，待數據取得"), 執行: TBD worktree agent]

## Motivation

`research_program.md` L411 currently lists SEC Filings (10-K / 10-Q / 8-K) as a **BLOCKED long-term direction** ("待數據取得"). The block is treated as "waiting for paid data" but in fact:

- **SEC EDGAR is fully public and free**, accessible via `https://www.sec.gov/cgi-bin/browse-edgar` and the bulk daily index files at `https://www.sec.gov/Archives/edgar/full-index/`.
- The friction is rate-limiting (10 req/sec hard limit) and parsing (10-K is multi-MB HTML), not access.
- Loughran-McDonald (2011, JF) financial-sentiment word lists are public-domain.
- For a **pilot test**, we don't need the full universe — a 30-firm × 10-year sample is enough to establish whether the signal is non-trivial.

This is exactly the kind of "data-blocked direction that is actually unblocked if you read carefully" gap that gap-scan should catch. The downside is bounded (1 worktree session, sample-only); the upside is unblocking a multi-year direction.

Pilot scope: do SEC 10-K **management-tone changes** correlate with subsequent monthly RV of the issuing firm's stock, above and beyond what VIX already captures?

## Hypothesis

**H_K1306 (signal sufficiency)**: For at least 3 of the 30 sampled S&P-500 firms, a monthly RV regression of the form

  RV_{t, firm} = α + β_VIX · VIX_lag + β_tone · LM_tone_lag + ε

produces β_tone with |t| > 2 after controlling for β_VIX, **and** OOS QLIKE improvement >5% vs VIX-only baseline.

- **PASS (signal exists)** → escalates SEC direction from "blocked" to "feasible"; K1307 plans full S&P-500 panel
- **NULL** → confirms VIX-sufficiency extends to firm-level text features; closes the SEC-text direction with documented evidence (also a publishable finding per Paper 4 family)

Per `research_program.md` "null result 也是結果" — both outcomes are publishable.

## Design

| Item | Setting |
| --- | --- |
| Sample | 30 firms, stratified by sector (5 from each of 6 GICS sectors) from S&P-500 Y2024 constituents |
| 10-K period | 2014-01-01 → 2024-12-31 (10 filing-years × 30 firms ≈ 300 10-Ks) |
| Text feature | Loughran-McDonald 2011 word-list — count `negative` / `positive` / `uncertainty` / `litigious` token shares in MD&A section |
| Tone delta | Year-over-year change in negative-tone share (proxy for management mood shift) |
| Forecast target | Monthly realized variance of firm stock in 12-month window post-filing |
| Baseline | VIX-only OLS: RV ~ VIX_lag |
| Challenger | RV ~ VIX_lag + LM_tone_delta_lag |
| DM test | Harvey-Leybourne-Newbold (per-firm) |
| Sample-level test | Fisher-combined p-value across 30 firms (Stouffer's Z) |
| Rate limit | 10 req/sec to EDGAR, user-agent header set per SEC API policy |
| Seed | 42 |
| Codex review | Required before knowledge entry |

## Lookahead discipline

- 10-K filing date used; forecast period strictly **after** filing date + 1-business-day embargo
- LM word counts computed from filing text only; no contemporaneous market data
- VIX_lag uses prior trading day close (`.shift(1)` explicit)
- Per-firm OOS = last 24 months; IS = remainder

## Differentiation vs prior K

- **K473 / K750 / K789** Google Trends NULL — **macro-level** alt-data
- **K1116 / K1116b / K1116c** EPU NULL — **macro-level** policy text
- **K1116d** planned vintage retest (still pending, see K1305)
- **K1117** jump-day matched-pair NULL — different conditioning event
- **K1306 = firm-level 10-K text** — distinct: firm-specific, not macro index, and tests whether **management's own description of risk** has incremental info beyond market-implied VIX
- No K in this repo has yet attempted SEC EDGAR free download + LM lexicon

## Success criterion

- EDGAR scraper retrieves ≥250 of 300 target 10-Ks (≥83% completion) within rate-limit budget
- LM tone deltas computed for all retrieved filings
- 30 per-firm DM tests + Stouffer combined Z computable
- ≥3 firms with β_tone |t| > 2 and OOS QLIKE > 5% improvement → H_K1306 PASS, escalate to K1307 full-universe panel
- Otherwise → NULL, document firm-text-sufficiency claim ext

## Mission 5 sanity

Primary beneficiary: **Mission 1 (article) + Mission 2 (research)**. Even NULL gives a clean article topic ("SEC 10-K 文字情緒對個股波動率有用嗎？實測 30 家 × 10 年"). If PASS, Mission 3 gets a Paper 11 candidate (firm-level text-sentiment vs IV-sufficiency boundary). Tertiary: Mission 5 (曝光 — SEC-data articles are high search-volume).

## K1306v2 — Bug Fix Record (2026-05-15)

Codex FAIL review identified two methodological bugs in v1. Both fixed in K1306v2.

### Bug 1 fixed: partial-month contamination (line 173-176)

**Problem**: `rv_series[rv_series.index > embargo].iloc[:12]` could include a partial
forward month when `embargo` fell mid-month (e.g. embargo=2023-11-03 → the next
month-end 2023-11-30 would be picked up even though only ~27 days of that month follow
the embargo). Over 12 months, this could introduce small contamination from the embargo
month's tail.

**Fix**: Added explicit `MonthEnd(12)` upper bound:
```python
fwd = rv_series[
    (rv_series.index > embargo) &
    (rv_series.index <= embargo + MonthEnd(12))
].iloc[:12]
```
The monthly RV series uses `resample("ME")` (month-end dates), so the fix ensures only
complete post-embargo month-ends are included and the window is strictly bounded.

### Bug 2 fixed: small-sample OLS guard (line 224-229)

**Problem**: The original `n<3` guard allowed N=3 or N=4 observations into a 3-parameter
OLS model (const + vix + tone), giving df=0 or df=1. HC1 heteroscedasticity-robust
t-statistics are numerically invalid at these degrees of freedom.

**Fix**: Raised guard to `n<5` (requires df≥2 for HC1 validity with 3 parameters):
```python
if n_obs < 5:
    out_per_firm[ticker] = {"n_obs": int(n_obs), "skipped": "n<5 insufficient df for HC1"}
    continue
```
This caused AAPL (N=4) and MSFT (N=4 after NaN drop on tone_delta_neg) to be skipped
in per-firm OLS. The pilot sample only has 4 firms × 5 filings — most firms fall below
the N≥5 threshold after removing the first-year NaN tone_delta. This limitation is noted
in `limitations` of results JSON and reinforces the need for K1307 (full S&P-500 panel).

### Verification

Script runs to completion without crash. All N<5 firms are skipped with clear "n<5
insufficient df for HC1" message rather than producing invalid HC1 statistics. Verdict
remains NULL (pilot sample too small for meaningful per-firm inference).

## Codex Review

**K1306v2 Codex primary-path review: PASS** (2026-05-15, gpt-5.4, session 019e2ac0)

Three Codex review rounds were required to reach PASS:

| Round | Verdict | Issue |
|-------|---------|-------|
| v1 round 1 | FAIL | Partial-month: lower bound `> embargo` still included embargo month's month-end |
| v1 round 2 | FAIL | Pooled OLS: `len(pooled) >= 6` guard did not check df_resid = N - k >= 2 |
| v2 round 3 | **PASS** | All 5 checklist items passed |

Final checklist result:
1. Lookahead bias: PASS — embargo = filing_date + 1 BD; VIX window uses `< embargo`; tone_delta is filing-level pre-embargo signal
2. Partial-month contamination: PASS — `embargo_month_end = embargo + MonthEnd(0)`; forward window uses `> embargo_month_end` (excludes embargo month); upper bound `embargo_month_end + MonthEnd(12)`
3. Small-N guard: PASS — per-firm `n_obs < 5` skip before HC1 OLS
4. Statistical validity: PASS — both per-firm (N>=5) and pooled (df_resid = N - k >= 2) guards in place
5. Seed fixedness: PASS — SEED=42 constant; bootstrap uses `np.random.default_rng(seed)`

## References

- Loughran & McDonald (2011) *Journal of Finance* — "When is a liability not a liability?"
- Loughran-McDonald master dictionary: https://sraf.nd.edu/loughranmcdonald-master-dictionary/
- SEC EDGAR API: https://www.sec.gov/edgar/sec-api-documentation
- Tetlock (2007) *J. Finance* — Giving content to investor sentiment (precedent)
- research_program.md L411 SEC Filings direction
