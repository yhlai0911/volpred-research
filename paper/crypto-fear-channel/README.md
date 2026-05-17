# Paper 10: The Crypto Fear Channel — Asymmetric BTC–Equity Volatility Spillover

**Target Journal**: Journal of International Financial Markets, Institutions & Money (1st) / Journal of Empirical Finance (2nd) / Finance Research Letters (backup)
**Status**: **READY FOR SUBMISSION** (2026-05-17 v4.1 hotfix; 4-round review history complete; 0 blocking issues; academic 4.70★; citation 21/22 VERIFIED; reproduce gate GREEN)
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

- **Submit to JIMF** (Journal of International Financial Markets, Institutions & Money, 1st choice). Prepare cover letter + submission package.
- **Pre-submission copy-edit** (3 MINOR deferred): (1) wrap `\texttt{statsmodels...}` overfull hbox into footnote; (2) Table 6 caption scope clarification; (3) §8.2 F/p pairing style.
- ~~**review cycle**~~ — COMPLETE (4 rounds, v1-v4; see `review_history/`; v4.1 hotfix closes last MAJOR+3MED)
- ~~**reproduce.py setup**~~ — DONE (37/37 byte-match, gate=pass)
- ~~**citation_check.md**~~ — DONE (24 citations inventoried; 21 VERIFIED, 1 NEEDS_CHECK, 0 ERROR)

## Cross-reference

- `research_program.md` Paper Portfolio Status entry
- `paper/garch-x-vix/README.md` — Related spillover paper (GARCH-X framework)
- `paper/vt-crowding-abm/README.md` — Related crowding dynamics paper
