# Paper 10: The Crypto Fear Channel — Asymmetric BTC–Equity Volatility Spillover

**Target Journal**: Journal of International Financial Markets, Institutions & Money (1st) / Journal of Empirical Finance (2nd) / Finance Research Letters (backup)
**Status**: **Body drafted v5 — pre-review** (2026-04-28 main.tex compiled to main.pdf; full body in main.tex 543 LoC, body_v5.tex 494 LoC; 14 `% source:` inline bindings to K639/K746b/K1025; sections Intro/LitReview/Data/Methodology/Results/Robustness drafted)
**Pages**: ~30 (target met)
**Citations**: TBD (citation_check.md pending)

## Central claim

The crypto fear channel is **asymmetric, tail-concentrated, and regime-dependent**:
- Negative BTC returns drive upward VIX shifts more strongly than positive BTC returns attenuate VIX
- Spillover concentrated in tail events (95%/99% quantile regressions)
- High-VIX regime activates a stronger BTC → equity feedback loop

## Data Sources

All from VolPred experiments (2015-02 – 2026-04, N=2,812 daily obs):

- **K639** — Confirmed BTC → SPY RV Granger causality at lag 1-10
- **K746b** — BTC volatility asymmetrically Granger-causes VIX (negative-BTC branch dominates)
- **K1025** — Full spillover framework: asymmetric Granger + quantile regression + rolling Diebold-Yilmaz spillover index + EWMA correlation by VIX regime + 5-subperiod structural change

Underlying daily data: BTC-USD / SPY / VIX from yfinance (`auto_adjust=False` per replication package rule).

## Files

- `outline.md` — Detailed paper outline (kickoff 2026-04-17)
- `body_v0_intro.tex` — Introduction draft (v0)
- `reproducibility_audit/` — Pre-body audit placeholder
- (pending) `main.tex`, `body.tex`, `reproduce.py`, `data/`, `figures/`, `citation_check.md`

## Supporting Experiments

| K | Purpose | Status |
|---|---|---|
| K639 | BTC → SPY RV Granger causality | PASS (Granger p<0.001 at lag 1-10) |
| K746b | BTC → VIX asymmetric Granger | PASS (negative-BTC > positive-BTC) |
| K1025 | Full spillover framework | PASS (DY index + regime + 5 subperiods) |

## Next Actions

- **Codex review** of main.tex v5 body (paper-review-cycle skill — `latex-academic-reviewer` + `citation-verifier`; Codex CLI primary-path verified working since 2026-04-28). Bar: CONDITIONAL PASS minimum before submission prep.
- **reproduce.py setup**: scaffold per `paper-workflow.md` rule 2 — must exist, exit 0, ≥95% match_rate, alert_level=green BEFORE submission. Self-contained replication package (data/ + scripts/ + results/ + experiments.md + README.md). Use K1268d-style structure as template.
- **citation_check.md**: populate after Codex first pass (Diebold-Yilmaz 2012 / Forbes-Rigobon 2002 / Bouri 2017 / Corbet 2018 / Hatemi-J 2012 / Patton 2011 likely candidates).
- **data_sources.md**: already exists — verify covers BTC-USD / SPY / VIX yfinance with `auto_adjust=False` (paper-workflow.md rule 1 data snapshot pinning).
- **3-spec footnote disambiguation** if quote-numbers diverge across body sections (per user 2026-04-29 K1256 lesson).

## Cross-reference

- `research_program.md` Paper Portfolio Status entry
- `paper/garch-x-vix/README.md` — Related spillover paper (GARCH-X framework)
- `paper/vt-crowding-abm/README.md` — Related crowding dynamics paper
