# K1301 — HAR-RS (BNKS Realized Semivariance) vs HAR-RV on TAIFEX TX1 + SPY

**Date**: 2026-05-11
**Author**: Claude (main thread, autonomous)
**Verdict**: **NULL** — BNKS upside/downside semivariance decomposition does not
significantly improve daily RV forecasting over standard HAR-RV on TX1 day
session (the only trustworthy sample in this run).

---

## Motivation

`research_program.md` open TODO: test the Barndorff-Nielsen, Kinnebrock,
Shephard (2008) decomposition of realized variance into signed semivariances:

```
RV_t       = sum_k r_{t,k}^2
RS+_t      = sum_k r_{t,k}^2 * 1(r_{t,k} > 0)
RS-_t      = sum_k r_{t,k}^2 * 1(r_{t,k} < 0)
=> RV_t    = RS+_t + RS-_t   (by construction, ignoring zero-return ticks)
```

HAR-RS replaces the three HAR-RV aggregates with six (daily/weekly/monthly
×{RS+, RS-}) and tests whether sign-asymmetric semivariance carries
incremental predictive content beyond the symmetric HAR-RV.

This is a **different cut** from:
- K863 (physics phase-transition indicators) — different feature family.
- K868 (HAR day/night session decomposition) — by-session cut, not by-sign.
  Hypothesis: BNKS by-sign carries info K868 missed.

## Data

| Asset | Period | Source | Day session window |
|-------|--------|--------|--------------------|
| TAIFEX TX1 | 2017-05-16 → 2026-05-08 | tick CSV (`~/Dropbox/TAIFEXDATA/TAIFEXDATA/python/Daily_*TX1.csv`), big5/cp950/utf-8 fallback | 08:45–13:45 (~60×5-min bars/day) |
| SPY | last 30 trading days (60d yfinance cap) | yfinance `interval=5m` | 09:30–16:00 ET |

Loader logic ports K1100h-v2's 13:45 endpoint fix (collapse `bar_start≥13:45`
back to `13:40` so the closing tick belongs to the `(13:40, 13:45]` bar, not a
phantom 61st bar).

## Methodology

**Target**: `Y_t = log(RV_{t+1})` (placed on row t, via `.shift(-1)` on the
RV column then `dropna`).

**HAR-RV (3 features)**:
- `log RV_{t-1}` (daily)
- `log mean(RV_{[t-5..t-1]})` (weekly)
- `log mean(RV_{[t-22..t-1]})` (monthly)

**HAR-RS (6 features)** — same 3 lag aggregates on RS+ and RS-:
- `log RS+_{t-1}`, `log mean RS+_{[t-5..t-1]}`, `log mean RS+_{[t-22..t-1]}`
- `log RS-_{t-1}`, `log mean RS-_{[t-5..t-1]}`, `log mean RS-_{[t-22..t-1]}`

**Lookahead guard**: features built strictly from `.shift(1)` then
`.rolling(window=5 or 22, min_periods=5 or 22).mean()`. Target via
`.shift(-1)`. After warm-up dropna, row t carries `X_{[t-22..t-1]}` and
`Y_{t+1}` — independently verified by reviewer.

**Estimation**: closed-form OLS, both models on the same chronological 70/30
split (`np.arange(n_train)` then `np.arange(n_train, T)`, no shuffle), with
HAR-RV and HAR-RS fit on identical training rows so DM is paired.

**Test**: Diebold-Mariano on squared OOS errors with Harvey-Leybourne-Newbold
(1997) small-sample correction at h=1:
```
HLN = DM × sqrt((T+1−2h+h(h−1)/T)/T),   df = T−1
```
Sign convention: `positive DM_HLN_t ⇒ HAR-RS preferred` (HAR-RV loss > HAR-RS loss).

**Pass rule**: `|DM_HLN_t| > 3` AND `MSE_RS < MSE_RV` per Harvey's 3σ standard.

**Sample trust flag** (Gemini reviewer 2026-05-11 recommendation):
- `n_test ≥ 100` → `OK`
- `30 ≤ n_test < 100` → `LIMITED_SAMPLE`
- `n_test < 30` → `UNTRUSTWORTHY_SMALL_SAMPLE` (excluded from `overall_verdict`)

**Seed**: 42 for the bootstrap MSE 95% CI; OLS is deterministic.

## Results

| Asset | n_train | n_test | trust | MSE HAR-RV | MSE HAR-RS | OOS R² RV | OOS R² RS | DM-HLN t | p | Pass 3σ |
|-------|---------|--------|-------|------------|------------|-----------|-----------|----------|---|---------|
| TX1 | 1514 | 649 | OK | 1.4709 | 1.4503 | 0.0432 | 0.0567 | **1.290** | 0.197 | False |
| SPY | 5 | 2 | **UNTRUSTWORTHY** | 8.58 | 4.08 | — | — | 0.760 | 0.527 | False |

`overall_verdict = NULL`. Trustworthy assets considered: `["TX1"]`.

### Diagnostics
- TX1: `n_clip_target_at_eps=0`, `n_clip_feat_at_eps=0` (no zero-RV days
  needing the 1e-12 floor → the `.clip()` is not masking data-quality
  problems on the production sample).
- TX1 OOS R²: HAR-RS marginally better than HAR-RV (+1.34 pp), consistent with
  the MSE direction but the gain is not significant at any reasonable
  threshold (DM-HLN p=0.197, |t|=1.29 ≪ 3).

## Interpretation

The MSE direction (`HAR-RS < HAR-RV` on both samples) suggests BNKS carries
*some* asymmetric information, but on the only trustworthy sample (TX1, n_test
= 649 days) the gain is well below Harvey's 3σ bar. Combined with the K868
NULL (day/night decomposition already captured by total RV), this points to:

> For TAIFEX TX1 day session, daily RV is a near-sufficient statistic for
> next-day vol forecasting; finer decompositions (by sign, by session)
> contribute only marginal improvement that does not survive a strict
> small-sample-corrected DM test.

This does **not** rule out HAR-RS being useful on:
- Longer-horizon forecasts (h>1)
- Risk-management losses (asymmetric loss functions, VaR/ES rather than MSE)
- Crisis-period subsamples (where downside semivariance may dominate)

These are open follow-ups.

## Code review

- **Primary path (Codex CLI)** — BLOCKED. `codex exec` returned
  `ERROR: You've hit your usage limit ... try again at 7:46 PM` (2026-05-13
  reset per task brief). Diagnostic order per `docs/error_log.md` 2026-04-28
  RESOLVED entry confirmed CLI binary `codex-cli 0.121.0`, ChatGPT login OK,
  default model `gpt-5.4` — quota-only blocker.
- **Fallback path (Gemini CLI fresh-context review)** — **CONDITIONAL PASS**.
  Two non-blocking findings, both implemented:
  1. SPY n_har_rows=7 (n_test=2) is untrustworthy → added `sample_trust_flag`
     and excluded UNTRUSTWORTHY samples from `overall_verdict`.
  2. Record `n_clip_*_at_eps` so future zero-RV data issues surface.
- Re-ran end-to-end after fixes. Final TX1 numbers identical (verifying
  reviewer fixes are flag/metadata only, not affecting estimation).

Per `.claude/rules/experiments.md` 2026-04-29 K1259 lesson: this knowledge
entry will note **reviewer source = "Gemini fallback (Codex quota blocked)"**
and **MUST be re-verified by primary-path Codex on 2026-05-13+** before
closure can be considered final.

## Files

- `k1301_har_rs.py` — main script (data loader + HAR estimation + DM-HLN +
  bootstrap + JSON dump)
- `k1301_results.json` — full numeric results
- `data/_tx1_5min_2017-2026.parquet` — (not populated; loader writes daily
  features directly; left for future intraday robustness work)
- `data/_tx1_daily_rs_2017-2026.parquet` — 2186 daily rows (date, rv, rs+,
  rs−, ret, n_bars)
- `data/_spy_daily_rs_recent.parquet` — last 30 SPY trading days

## Reproduce

```bash
uv run python experiments/k1301/k1301_har_rs.py
```
Re-running after the cached parquets exist skips the 3-minute tick rebuild
and finishes in <5 s.
