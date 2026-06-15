# K1345 — Pre-FOMC Implied Vol Drift Tradability (T-14 / T-7 / T-3 / T-0)

## Motivation

Recent literature (iPresage 2026; JFQA 2025-08 disagreement model) revives the hypothesis that implied vol begins to **drift up 1-2 weeks before FOMC announcements** as anticipatory hedging demand builds. This contradicts the classic "VIX is a coincident indicator" view.

**Core question**: After realistic transaction cost, is long-vol entry at T-14 / T-7 / T-3 / T-0 (relative to FOMC announcement) **tradable** in OOS?

**Why this matters now (monetization)**:
- If PASS → packageable strategy card + event-tied article (high reader interest around Fed dates).
- If NULL → honest-null knowledge entry that contradicts pop-finance narrative; protects readers.

## Relationship to Existing K-Series

| K | Finding | Relation to K1345 |
|---|---|---|
| K513 | FOMC vol footprint +28% sig | Confirms event matters; we test **drift timing** instead |
| **K514** | FOMC surprise IS t=−8.18 → OOS WORSE +3.89 | **Strong warning of data snooping** — drove Bonferroni discipline here |
| K856 | Fed rate causal NULL (4 methods); VIX anticipates not reacts | Already-established prior: VIX pre-prices FOMC — this paper tests whether anticipation is **monetizable** |
| K185 | FOMC vol effect (Gemini R8#4) | Background |

**K1345 differentiation**: Timing of pre-announcement entry (4 windows) + post-event crush risk + **net-of-cost** Sharpe, not the surprise-direction angle that already failed OOS (K514).

## Literature (motivating, not exhaustive)

- iPresage (2026) — anticipatory vol-of-vol drift in disagreement-based macro events
- JFQA (Aug 2025) — disagreement model predicts widening dispersion 5-10 trading days pre-announcement
- Lucca & Moench (JF 2015) — pre-FOMC announcement drift (equity, not vol)
- Cieslak, Morse, Vissing-Jorgensen (JF 2019) — Fed cycle in stock returns

(For 3+ references discipline. Full literature is in `research_program.md` Phase-XII FOMC notes.)

## Data

- **VIX**: `^VIX` from yfinance (2010-01-04 to 2026-06-12)
- **VIX9D**: `^VIX9D` from yfinance (2011-01-03 onward — used for IV path visualization)
- **SPY**: `^SPY` from yfinance (control / market regime baseline)
- **Tradable proxy**: `VIXY` (ProShares VIX Short-Term Futures ETF) — starts 2011-01-04.
  - **Why VIXY not VXX**: VXX yfinance series starts 2018-01-25 (post-2018 ETN relaunch). VIXY back to 2011 gives ~14 FOMC meetings/year × ~7.5 years IS.
  - VIXY tracks the same S&P 500 VIX Short-Term Futures Index as VXX (long M1+M2 VIX futures, roll daily).
- **FOMC announcement dates**: Hardcoded, manually verified from FederalReserve.gov calendar (2011-01 to 2026-06; **123 scheduled meetings only**). 2020-03-03 and 2020-03-15 emergency cuts **EXCLUDED** — those cuts were not announced ex-ante, so any T-14 / T-7 / T-3 entry on those dates would be lookahead. (Codex K1345 review caught this in v1; v2 fixed.)

## Method

1. For each FOMC announcement date `d` and entry window `w ∈ {14, 7, 3, 0}`:
   - **Entry trading day** `e = first_trading_day_on_or_after(d - w_calendar_days)`
   - **Signal lag (lookahead control)**: entry is **fully calendar-driven** from the ex-ante known scheduled FOMC list — no price-derived signal exists in the entry rule, so a `.shift(1)` on returns is not the right lookahead control (there is no price-based signal to lag). The actual lookahead control is: (a) only scheduled meetings (emergency cuts dropped), (b) entry executed at **open of e**, exit at **close of x_d**, so any same-day close-to-close info is excluded by construction.
2. For each exit horizon `x ∈ {0, 1}` (days after `d`):
   - **Exit day** `x_d = first_trading_day_on_or_after(d + x_calendar_days)` (close of that day)
   - Return = `VIXY[x_d].Close / VIXY[e].Open - 1` (enter at open of e, exit at close of x_d)
3. **Transaction cost**: 0.05% per side × 2 (round-trip) = 10 bps total. Subtracted from each trade.
4. **Stats per spec**: mean return, t-stat (HC), bootstrap p-value (1000 reps, block-bootstrap block=5 to preserve vol cluster), 95% CI, % positive trades, net Sharpe (annualized using sqrt(252/avg_holding_days)).
5. **IS/OOS split**:
   - IS: 2011-01 to 2018-12 (~64 meetings)
   - OOS: 2019-01 to 2026-06 (~62 meetings, includes COVID + 2022 hike cycle)
6. **Multiple testing**: 8 specs (4 entry × 2 exit) → Bonferroni α = 0.05/8 = 0.00625.
7. **Baseline comparators**:
   - Random-date entry (same N trades, sampled from non-FOMC days, seed=42)
   - Buy-and-hold VIXY over same period

## Lookahead Audit

- Entry is calendar-driven (FOMC dates known years in advance via Fed schedule). No price-derived signal exists.
- Trade is executed at **open of entry day** using only the calendar fact "FOMC announcement in w days". No same-day return information used.
- **v2 fix** (Codex caught in review): 2020-03-03 and 2020-03-15 emergency Fed cuts dropped from the FOMC list — those were not scheduled ex-ante, so including them with T-14/T-7/T-3 entries leaked future information.
- Trade construction in `run.py::build_trades` reads only `FOMC_DATES` (a hard-coded calendar list) and `vixy.index` (prices on or before the entry date are used for `Open[e]`; the exit reads `Close[x_d]` which is strictly after entry).

## Seed

`numpy.random.seed(42)` set at top of run.py. Block-bootstrap, random-date baseline both use this seed.

## Honest Caveats (pre-stated)

- VIXY has well-known contango drag (~5-15% annual) — long-only spec is fighting structural headwind.
- VIXY only available 2011-onwards; 2008-2010 (high-vol regime) excluded — may bias OOS optimism.
- Cost assumption (0.05% per side) is mid-range retail; actual ETF spread can spike during FOMC.
- "Drift" is a directional bet; if FOMC is largely priced in (K856), expected drift is ~zero.

## Success Criteria (pre-registered)

- **PASS**: ≥1 spec with OOS Sharpe > 0.5 **after cost** AND bootstrap p < 0.00625 (Bonferroni) AND |OOS-IS Sharpe gap| < 1.5.
- **CONDITIONAL_PASS**: ≥1 spec where the *same* spec has OOS Sharpe > 0.3 AND OOS bootstrap p < 0.05 — directional evidence but not strategy-grade. (v2 fix: same-spec requirement; v1 mixed best-Sharpe and best-p across specs.)
- **INVERSE_SIGNIFICANT** (v2 added): original long-vol hypothesis rejected, but ≥1 spec has Bonferroni-significant **negative** OOS Sharpe — the inverse (short-vol pre-FOMC) shows a real drift. Useful as honest-null + scientific finding.
- **NULL**: No spec meeting CONDITIONAL bar; no inverse-significant pattern. (Was the prior expectation given K856.)
- **FAIL**: best OOS Sharpe < 0 but no Bonferroni-significant spec.

### v2 Result (this run)

- **Verdict: INVERSE_SIGNIFICANT** — long-vol pre-FOMC is NOT tradable; instead, VIXY shows Bonferroni-significant *negative* drift T-7→T+0 (OOS Sharpe −1.58, p_boot=0.002) and T-3→T+0 (OOS Sharpe −2.99, p_boot=0.005). Consistent with K856 (VIX anticipates FOMC). The inverse trade (short VIXY pre-FOMC) is **not** automatically a free lunch — VIXY's structural contango already makes most "short VIXY" strategies look good; the question of whether the **FOMC-window short** beats a **buy-and-hold short VIXY** baseline is a separate study.
- Best OOS spec by Sharpe is T-0/T+1 = +2.03 but p=0.197 (insignificant; small N=58 + IS-OOS gap −1.47 warning).
- 0 / 8 specs satisfy strict PASS bar.

## Artifacts

- `README.md` (this file)
- `run.py` (self-contained reproducible script)
- `results.json` (machine-readable verdict + per-spec stats)
- `fig_iv_path.png` (avg VIX/VIX9D path around FOMC, IS vs OOS)
- `fig_returns_by_window.png` (Sharpe bar chart per (entry, exit) spec)
