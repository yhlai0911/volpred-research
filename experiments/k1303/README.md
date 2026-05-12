# K1303: HAR-CJ — Adding Realized Jumps on top of K1301 Semivariance

[提出: Claude (autonomous backlog gap-scan, extends K1301 intraday-seasonality / semivar pilot), 執行: TBD worktree agent]

## Motivation

K1255 ran intraday seasonality pilot; K1301 (currently empty stub) was scoped for intraday semivariance. Both stop short of the **jump component**, which Barndorff-Nielsen & Shephard (2004, JBES; 2006, JFEC) and Andersen-Bollerslev-Diebold (2007, RFS) showed delivers persistent forecast gain over plain HAR-RV on SPX-like indices — but the gain has never been replicated in this repo on our 5-min cumulating dataset, nor on Taiwan futures.

The continuous-jump decomposition splits realized variance into:

  RV_t = CV_t + J_t,  J_t = max(RV_t – BPV_t, 0)

where BPV_t is Barndorff-Nielsen bipower variation (jump-robust). HAR-CJ regresses next-day RV on lagged (CV, J) at daily / weekly / monthly horizons rather than the pooled RV used by vanilla HAR.

Connection to K1301: K1301's semivariance decomposition (RV+ / RV-) is **signed** but jump-agnostic; K1303 adds the **orthogonal** decomposition (CV / J). Together they form the 4-component HAR-CSJ family, but K1303 isolates the jump term first to avoid one-shot 4-way confound (per K1216b/K1216c symmetric-refinement lesson).

## Hypothesis

**H1 (jump-component gain)**: HAR-CJ delivers OOS QLIKE strictly below HAR-RV on SPY 5-min RV with DM-Harvey corrected |t| > 3 (Harvey 2016 threshold).

**H2 (universality)**: H1 extends to ≥2 of {QQQ, GLD, TX-front-month TAIFEX} — if only SPY passes, jump premium is index-specific (consistent with prior ABD 2007 SPX-only finding).

**H3 (regime asymmetry, exploratory)**: Jump frequency in crisis windows (2020Q1, 2022 selloff) is ≥2x calm windows AND Jump-Premium contribution to forecast improvement is concentrated in crisis subsamples.

## Design

| Item | Setting |
| --- | --- |
| Assets | SPY, QQQ, GLD (USD 5-min via yfinance / cached), TX (TAIFEX 5-min ticks) |
| Data span | SPY/QQQ/GLD: 2022-01-01 → 2026-04-30 (5-min cumulating window per K1255). TX: 2020-01-01 → 2026-04-30 (already ETA 2026 Q2 ready per `research_program.md` §"需 5-min 數據") |
| RV definition | 5-min log-return²-sum, exclude overnight |
| BPV definition | (π/2) × Σ \|r_t\|·\|r_{t-1}\| (Barndorff-Nielsen-Shephard) |
| Jump test | Bilateral z-test (Huang-Tauchen 2005), 0.99 significance threshold |
| Baseline | HAR-RV (Corsi 2009): daily/weekly/monthly RV lags |
| Challenger | HAR-CJ: daily/weekly/monthly (CV_lag, J_lag) — 6 regressors vs 3 |
| IS / OOS | Rolling 504-day IS, OOS 2024-01-01 → 2026-04-30 |
| DM test | Harvey-Leybourne-Newbold small-sample correction |
| Seed | 42 |

## Lookahead discipline

- Forecast at t uses (CV_{t-1}, J_{t-1}, weekly_avg over [t-5, t-1], monthly_avg over [t-22, t-1])
- BPV / J computed from intraday returns of day t-1 only; **no contemporaneous day-t intraday data leaks** into the day-t forecast
- All rolling moments use `.shift(1)` explicit
- Seed = 42 fixed for any optimization

## Differentiation vs prior K

- **K1255**: intraday seasonality pilot — descriptive, no model fit
- **K1301**: semivariance pilot (signed decomposition) — empty stub, but scope is orthogonal direction
- **K785 MF2-GARCH**: NULL on long-term-component MF₂ — K1303's jump component is event-driven not low-frequency-trend
- **K783b**: window sensitivity established w=504 as cross-asset compromise — K1303 uses same window
- **No K has done BPV / jump-decomposition** in this repo — fresh ground

## Success criterion

- HAR-CJ vs HAR-RV DM-Harvey |t| > 3 on **at least SPY** for H1 PASS (matching K1259 audit ledger SPY α=0.10 superior-set bar)
- Codex review PASS (zero CRIT, ≤1 MAJOR addressable)
- If H1 PASS + H2 PASS (≥2 of 3 non-SPY assets) → Tier-A finding, escalate to Paper 11 candidate (jump-channel sufficiency)
- If H1 FAIL → likely closes jump-premium direction for our 5-min dataset (`research_program.md` "需 5-min 數據" backlog can mark H1-NULL)

## Mission 5 sanity

Primary beneficiary: **Mission 2 (research)**. First foray into Barndorff-Nielsen jump literature for this repo; SPY/QQQ/GLD/TX intra-day infrastructure (K1255) now ETA-ready makes this experimentally cheap. Secondary: Mission 3 (Paper 11 candidate if PASS).

## References

- Barndorff-Nielsen & Shephard (2004) JBES — Power and bipower variation
- Andersen, Bollerslev & Diebold (2007) RFS — Roughing it up
- Huang & Tauchen (2005) J. Financial Econometrics — Jump test
- Corsi (2009) JFEC — HAR-RV baseline
- K1255 (this repo) — intraday seasonality pilot, data infrastructure
