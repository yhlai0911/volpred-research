# Paper 10: The Crypto Fear Channel — Asymmetric BTC–Equity Volatility Spillover

**Target Journal**: Journal of International Financial Markets, Institutions & Money (1st) / Journal of Empirical Finance (2nd) / Finance Research Letters (backup)
**Status**: **MAJOR REVISION** (2026-06-11 audit sync; v2 experiment rerun exists, but manuscript remains downgraded until data-pinning, FEVD-ordering robustness, and K1025b symmetric rerun are completed)
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

Underlying daily data for the currently reported estimates come from the archived `k1025_v2.py` yfinance pull (`auto_adjust=True`). A paper-local CSV snapshot exists in `data/`, but the headline results have not yet been fully rerun from that pinned file.

## Files

- `main.tex` — Active manuscript
- `reproduce.py` — Active traceable-binding gate for the current manuscript scope
- `data/spy_btc_usd_vix_2015-2026.csv` — Paper-local snapshot archive (not yet the direct input to all headline estimates)
- `review_history/audit_2026-06-10/` — Current audit findings and fix log

## Supporting Experiments

| K | Purpose | Status |
|---|---|---|
| K639 | BTC → SPY RV Granger causality | PASS (Granger p<0.001 at lag 1-10) |
| K746b | BTC → VIX asymmetric Granger | PASS (negative-BTC > positive-BTC) |
| K1025 | Full spillover framework | PASS (DY index + regime + 5 subperiods) |

## Next Actions

- Re-run `k1025_v2.py` off the pinned paper snapshot with a method-consistent data pipeline (`auto_adjust`, return definitions, rolling-window notation aligned).
- Either add ordering-robust generalized FEVD or keep the current Cholesky FEVD but document ordering sensitivity explicitly.
- Rebuild `K1025b` under the same v2 spec before restoring any cross-asset robustness claim.
- Keep the paper in `MAJOR REVISION` until the above reruns are landed and `reproduce.py` remains green against the updated body.

## Cross-reference

- `research_program.md` Paper Portfolio Status entry
- `paper/garch-x-vix/README.md` — Related spillover paper (GARCH-X framework)
- `paper/vt-crowding-abm/README.md` — Related crowding dynamics paper
