# K1305: Paper 4 vix-sufficiency post-K1116d vintage retest — boundary case generalization

[提出: Claude (autonomous backlog gap-scan from research_program.md L451 + memory `feedback_paper_cross_paper_meta_eval`), 執行: TBD worktree agent]

## Motivation

Paper 4 (vix-sufficiency) currently READY 98% with the universal-NULL claim:

> Across SPY/GLD/TLT/BTC × {EPU, NFCI/ANFCI, STLFSI, UMCSENT, INDPRO, CFNAI} × {weekly K1116, monthly K1117b, daily K1121, jump-day K1117} = **93 specs all NULL** (alt-data adds zero increment over native IV).

K1116c established that the NULL is **robust to publication-delay and PIT alignment** (revision-corrected upper-bound) but explicitly leaves open:

> Derived K1116d (true ALFRED vintage once FRED_API_KEY 可得), K1116f (PIT alignment 套用 GLD/TLT/BTC cross-asset), K1116e (intraday release-time alignment)

K1116d / K1116f never landed because:
- FRED_API_KEY was unavailable at the time (Akamai timeout + missing key)
- The "weekly upsample artifact" loophole was closed K1117b → urgency dropped

But Paper 4's R1 / desk-review risk profile is non-trivial: a reviewer can ask "did you test the **boundary** — does the universal NULL hold when alt-data has the **best-possible** vintage AND the **non-SPY** asset class?" Without K1305 (= true vintage × GLD/TLT/BTC), the answer is "we tested vintage on SPY only and PIT on GLD/TLT/BTC only — we never crossed the two."

This is exactly the "cross-paper meta-eval" failure mode memory `feedback_paper_cross_paper_meta_eval` warns about: single-axis robustness chains don't catch boundary-cell gaps.

## Hypothesis

**H_K1305 (boundary closure)**: ALFRED vintage-aligned alt-data on GLD / TLT / BTC weekly RV produces 0 cells with DM-Harvey |t| > 3 favoring alt-data over native IV (^GVZ / TYVIX / DVOL).

- **Universal-NULL UPHELD** iff condition holds → Paper 4 R1 risk drops materially
- **BOUNDARY-LEAK** iff any single asset × spec cell crosses threshold → Paper 4 narrative needs amendment (currently 93 specs, K1305 adds ~12-18 specs; even 1 PASS would require honest reporting)

## Design

| Item | Setting |
| --- | --- |
| Assets | GLD (proxy ^GVZ), TLT (proxy TYVIX), BTC (proxy DVOL from Deribit, K1119 precedent) |
| Alt-data | NFCI, ANFCI, STLFSI4, USEPU, WLEMU (5 series via ALFRED endpoint `https://api.stlouisfed.org/fred/series/observations` with `realtime_start`/`realtime_end`) |
| Vintage method | True point-in-time: for each forecast day t, use the alt-data value as it appeared on (or before) t — no future revisions leak in |
| RV definition | Weekly realized variance (Friday-to-Friday close) per K1116/K1116b/K1116c |
| Period | 2020-01-01 → 2026-04-30 (overlaps with K1116b/K1116c) |
| Baseline | M1 (GARCH-N) + M2 (GARCH + native IV) — K1116 canonical |
| Challengers | M3 (M2 + alt-data PIT vintage), M4 (M2 + best FinStress vintage), M5 (M2 + all alt-data) |
| DM test | Harvey-Leybourne-Newbold |
| Seed | 42 |
| Codex review | Required; if Codex blocked, `feature-dev:code-reviewer` subagent per `.claude/rules/experiments.md` |

## Lookahead discipline

- ALFRED `realtime_end` set to forecast-week Friday close — strictly no future-vintage data
- Native IV (^GVZ / TYVIX / DVOL) lagged 1 day per K1116 convention
- All rolling stats `.shift(1)` explicit
- Seed = 42

## Differentiation vs prior K

- **K1116** SPY weekly: PIT (calendar shift) only, no true vintage — NULL
- **K1116b** SPY weekly: publication-delay shift(2) wk — NULL strengthened
- **K1116c** SPY weekly: 6 lag variants × 5 specs PIT — NULL robust
- **K1116d** SPY: planned true ALFRED vintage but **never executed** (FRED_API_KEY unavailable at the time, Akamai timeout)
- **K1118 / K1121 / K1117b / K1117**: GLD/TLT/BTC + cross-frequency but **no true vintage**
- **K1305 = K1116d × {GLD, TLT, BTC}** — the unfilled boundary cell

## Success criterion

- API key + ALFRED endpoint reachable (else FAIL_NO_DATA, escalate to K1268-style data-blocker resolution)
- 3 assets × 5 alt-data series × 3 challenger specs ≈ 45 cells with valid PIT-vintage values
- ≥80% cells have ≥104 OOS weeks (2 years) for DM power
- 0 cells with Harvey |t| > 3 favoring alt-data → H_K1305 UPHELD; Paper 4 NULL universally robust to vintage × cross-asset
- ≥1 PASS cell → boundary-leak honestly reported; Paper 4 §5 needs revision section
- Codex PASS before knowledge entry

## Mission 5 sanity

Primary beneficiary: **Mission 3 (Paper 4 R1 risk reduction)**. Paper 4 is READY 98% but cross-paper meta-eval would catch this gap; pre-empting R1 here is ~5% submission-success buffer. Secondary: Mission 2 (closes a documented backlog entry from K1116c knowledge).

## References

- knowledge entries K1116 / K1116b / K1116c / K1117 / K1117b / K1118 / K1119 / K1121
- research_program.md L451 Paper 4 status
- memory `feedback_paper_cross_paper_meta_eval`
- ALFRED docs https://alfred.stlouisfed.org/help/api
- Deribit DVOL data path: `data/btc/deribit_dvol.csv` (K1119 precedent)
