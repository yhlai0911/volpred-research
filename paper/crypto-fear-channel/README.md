# Paper 10: The Crypto Fear Channel — Asymmetric BTC–Equity Volatility Spillover

**Target Journal**: Journal of International Financial Markets, Institutions & Money (1st) / Journal of Empirical Finance (2nd) / Finance Research Letters (backup)
**Status**: **Kickoff — intro drafted, main body pending** (2026-04-17 outline + body_v0_intro.tex; 2026-04-19 Codex P25 `task_7d2c` pre-body audit queued awaiting quota reset 2026-04-24)
**Pages**: TBD (body pending)
**Citations**: TBD

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

- **Blocked until 2026-04-24 10:27 UTC**: Codex `task_7d2cdf...` pre-body audit (queued, awaiting quota reset per `docs/error_log.md` 2026-04-19 Codex quota blocker)
- **Post-quota-resume**: Codex audit produces:
  - Experimental claim cross-check vs `K639/K746b/K1025` JSONs
  - Citation candidates (Diebold-Yilmaz 2012 / Forbes-Rigobon 2002 / Bouri et al. 2017 / Corbet et al. 2018)
  - Outline-to-body gap analysis
- **Main-thread post-audit**: Draft body sections §3 methodology + §4 results (L188 rule — `.tex` body writing stays on main thread, not Codex)
- **Reproduce.py kickoff**: Follow P5/P6 green pattern

## Cross-reference

- `research_program.md` Paper Portfolio Status entry
- `paper/garch-x-vix/README.md` — Related spillover paper (GARCH-X framework)
- `paper/vt-crowding-abm/README.md` — Related crowding dynamics paper
