# K1445 — URA / KRBN Alternative-Asset Volatility Clustering & Cross-Asset Correlation

**Status**: PASS (PoC)
**Run date**: 2026-06-10
**Author**: K1445 (worktree agent, hourly-07)
**Codex review**: PENDING (main thread will dispatch after merge)

## Motivation

Article pool exhausted on traditional VIX / vol-forecast / 台股 topics. To diversify
content, this PoC quantifies the volatility dynamics of two non-traditional asset
proxies versus the equity (SPY) and long-bond (TLT) benchmarks:

- **URA** — Global X Uranium ETF (uranium miners + nuclear fuel cycle exposure;
  inception 2010-11; driven by nuclear policy, restart announcements, supply
  concentration in Kazakhstan / Canada / Australia)
- **KRBN** — KraneShares Global Carbon Strategy ETF (basket of EU ETS, California
  Cap-and-Trade, RGGI carbon futures; inception 2020-08; driven by carbon policy
  and compliance demand)

Question: do these alt-assets behave as **vol diversifiers** (low equity beta,
independent vol cycle) or as **high-beta amplifiers** (equity correlation +
explosive vol)?

## Related K

No prior K explicitly on URA or KRBN found in `storage/memory/knowledge.json`
(keyword grep: URA / KRBN / uranium / carbon credit returned no asset-specific
priors). General vol-clustering methodology priors (GARCH on liquid ETFs) are
abundant but not asset-specific.

## Positioning vs literature (PoC, no deep search)

- Uranium price dynamics literature has documented post-Fukushima (2011-03)
  structural break and strong supply-side concentration effects.
- Carbon credit (EU ETS) studies note Phase III / Phase IV regulatory regime
  shifts dominating short-run price dynamics; KRBN exposure inherits these.
- Alt-asset diversification literature (commodity ETF, gold, REITs) generally
  finds regime-dependent equity correlation — diversifier in calm regimes,
  amplifier in crisis. URA/KRBN as a sharper test of this hypothesis given
  their thinner liquidity and policy-driven cash flows.

(Positioning sentences only; not a literature review. Cite-by-name omitted to
avoid fabrication; a follow-up K should do a proper literature search.)

## Method

- Data: yfinance daily adjusted close, each asset's inception → 2026-06-09
  - URA: 2010-11-09 → 2026-06-09, n=3919
  - KRBN: 2020-08-03 → 2026-06-09, n=1470
  - SPY: 2010-01-05 → 2026-06-09, n=4132
  - TLT: 2010-01-05 → 2026-06-09, n=4132
- Log returns; drop first NaN.
- Descriptive stats: mean / std / skew / excess kurtosis / annualized vol / MDD.
- Vol clustering: Ljung-Box (lag=10) on squared returns + Engle ARCH-LM (nlags=10).
- GARCH(1,1) constant-mean normal innovations via `arch` package; report ω, α, β,
  persistence (α+β), AIC, log-likelihood.
- Static correlation matrix: full sample (intersection = 1470 obs, gated by KRBN
  inception) and 2024-onwards subsample (n=611).
- Rolling 60-day Pearson correlation for 5 pairs: URA-SPY, URA-TLT, KRBN-SPY,
  KRBN-TLT, URA-KRBN; summary stats (mean / std / min / max / latest).

**Lookahead control**: PoC is descriptive — no predictive setup. Rolling stats
use `min_periods=window` (no partial-window peek). Seed=42 fixed.

## Key findings

### Vol clustering (all assets — strong evidence)

| Asset | LB(10) p | ARCH-LM(10) p | GARCH α+β |
|-------|----------|---------------|-----------|
| URA   | 9.1e-91  | 4.2e-50       | 0.9886    |
| KRBN  | 7.8e-79  | 4.5e-44       | 0.9900    |
| SPY   | ~0       | 8.7e-250      | 0.9659    |
| TLT   | ~0       | 1.5e-210      | 0.9837    |

KRBN has the highest GARCH persistence (0.9900) — slightly above URA and SPY.
This is unusual: a young (n=1470) policy-driven asset showing persistence at
the top of the liquid-ETF range. Suggests carbon credit vol shocks decay slowly
once initiated — consistent with multi-week EU ETS policy news windows.

### Descriptive

| Asset | Ann ret % | Ann vol % | MDD %  | Skew  | Excess kurt |
|-------|-----------|-----------|--------|-------|-------------|
| URA   | -2.7      | 36.6      | -93.5  |  0.01 |  4.0        |
| KRBN  | 14.3      | 28.7      | -36.4  | -0.58 |  6.3        |
| SPY   | 13.2      | 17.2      | -33.7  | -0.56 | 12.4        |
| TLT   |  2.6      | 15.0      | -48.4  | -0.03 |  3.5        |

URA's -93.5% MDD reflects the Fukushima (2011-03) → 2016 trough collapse plus
secondary drawdowns; sample-mean return is negative — uranium ETF has been a
long-run wealth destroyer at 2× equity vol. KRBN over its short life has out-
returned SPY but with materially higher vol (28.7% vs 17.2%).

### Cross-asset correlation

**Static full-sample** (intersection n=1470, 2020-08 → 2026-06):

| Pair       | ρ      |
|------------|--------|
| SPY-URA    | +0.516 |
| KRBN-SPY   | +0.230 |
| KRBN-URA   | +0.166 |
| SPY-TLT    | +0.059 |
| KRBN-TLT   | -0.047 |
| TLT-URA    | -0.043 |

URA is **highly correlated with SPY** (ρ=0.52) — behaves as equity-risk-on
proxy, NOT a diversifier. KRBN is **weakly correlated with SPY** (ρ=0.23) and
near-zero with TLT — closer to a genuine diversifier candidate.

**Rolling 60-day correlation summary**:

| Pair      | Mean   | Std   | Min    | Max   | Latest |
|-----------|--------|-------|--------|-------|--------|
| URA-SPY   | +0.531 | 0.173 | -0.108 | +0.918 | +0.765 |
| URA-TLT   | -0.171 | 0.211 | -0.780 | +0.413 | +0.371 |
| KRBN-SPY  | +0.213 | 0.150 | -0.156 | +0.599 | +0.325 |
| KRBN-TLT  | -0.028 | 0.146 | -0.420 | +0.308 | +0.014 |
| URA-KRBN  | +0.177 | 0.123 | -0.144 | +0.521 | +0.352 |

URA-SPY correlation **swings from -0.11 to +0.92** — heavily regime-dependent.
Latest 0.77 indicates current high-beta regime. KRBN-SPY range (-0.16 → +0.60)
is wider than the mean would suggest — carbon credit diversification benefit is
not stable.

## Verdict: PASS

Criteria met:
1. Strong vol clustering in both URA and KRBN (LB / ARCH-LM p < 0.01, GARCH
   persistence > 0.85).
2. Meaningful cross-asset structure: URA-SPY ρ=0.52 (high), KRBN-SPY ρ=0.23
   (moderate), AND rolling correlation range >0.5 for URA-SPY (regime shift
   evidence).

## Caveats

- KRBN sample is short (n=1470, 5.8 years); GARCH persistence at 0.99 may be a
  small-sample artifact. Robustness check on rolling-window GARCH refit would
  help.
- URA full sample spans uranium's secular bear (2011-2020) + recent bull
  (2021-2026). Sub-period stats (pre/post 2021) would be informative.
- yfinance dividend / split adjustment is auto_adjust=True; no manual audit
  done. Cross-check vs CRSP recommended before production claims.
- Static correlation matrix is gated by KRBN inception (1470 obs). The longer
  URA-SPY history (3900+ obs back to 2010) is not represented here — a separate
  full-URA-vs-SPY block would show post-Fukushima regime more clearly.

## Reproduction

```bash
uv run python experiments/k1445/k1445.py
```

Produces:
- `k1445_results.json` — all numbers (structured)
- `fig1_cumulative_returns.png` — log-scale cumulative log-returns
- `fig2_rolling_vol.png` — 60-day annualized realized vol
- `fig3_rolling_corr.png` — 60-day rolling correlation
- `fig4_garch_condvol.png` — GARCH(1,1) conditional vol (URA + KRBN)

Seed=42, end_date=2026-06-10, tickers=[URA, KRBN, SPY, TLT].

## Follow-up K candidates

- **K1446** — Pre/post Fukushima URA regime test (structural break diagnostics,
  rolling GARCH).
- **K1447** — KRBN sub-period stability (Phase III vs Phase IV EU ETS regime;
  rolling-window GARCH refit).
- **K1448** — DCC-GARCH on URA/KRBN/SPY/TLT — does conditional correlation
  spike during equity drawdowns (test diversifier-in-calm / amplifier-in-crisis)?
- **K1449** — Vol-targeting trading strategy backtest using GARCH conditional
  vol on URA and KRBN — does the high persistence translate to ex-ante vol
  forecast accuracy (QLIKE / DM test vs HAR-RV)?
