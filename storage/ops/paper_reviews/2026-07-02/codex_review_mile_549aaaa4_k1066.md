# Codex 24h Review - mile_549aaaa4 / K1066

- **Article**: `mile_549aaaa4`
- **Task**: `paper_review_mile_549aaaa4`
- **Experiment**: `experiments/k1066/`
- **Review timestamp**: 2026-07-02 02:40 Asia/Taipei
- **Verdict**: **PASS AFTER PATCH**

## Scope

Checked the published article against:

- `storage/reports/feed.json` entry `mile_549aaaa4`
- `experiments/k1066/k1066.py`
- `experiments/k1066/k1066_results.json`
- `experiments/k1066/README.md`
- `experiments/k1066/k1066_dm_comparison.png`
- `experiments/k1066/k1066_subperiod_stability.png`

This review did not rerun yfinance downloads. It audited the committed source code, results JSON, README, and the live article entry.

## Claim-Evidence Check

| Article claim | Source evidence | Status |
|---|---|---|
| K1066 uses SPY OHLC + VIX from yfinance, 2005-01 to 2026-04, n=5,350; OOS starts 2019-01 with n=1,828. | `k1066_results.json:6-14`; data construction in `k1066.py:91-124`. | Match |
| Rolling OOS uses 2000-day estimation window, refits every 63 trading days, 30 refits, seed 42. | `k1066_results.json:11-14`; rolling refit code uses `train_start=max(0, abs_idx-WINDOW)` and `t_idx % REFIT_EVERY == 0` in `k1066.py:343-352`. | Match |
| H1: A4f_oc beats GJR_oc on r²_oc with DM t=4.04 and Harvey threshold pass. | `k1066_results.json:128-135`; `hypotheses.H1` at `k1066_results.json:313-318`. | Match |
| H2: A4f_oc does not exceed the original K988 close-to-close benchmark 4.48. | `k1066_results.json:319-324`; benchmark constant in `k1066.py:78`; H2 code is only `h1_t > benchmark` at `k1066.py:764-767`. | Match after wording patch |
| H3: A4f_oc wins 5/5 subperiods; binomial p=0.03125. | `k1066_results.json:228-310`; summary code at `k1066.py:723-744`. | Match, with caveat |
| Five subperiods include 2019 pre-COVID, COVID, post-COVID/inflation, rate-hike, and recent tech-led period. | Subperiod definitions in `k1066.py:643-648`; results in `k1066_results.json:228-303`. | Match |
| Data source / method footer lists yfinance SPY OHLC + CBOE VIX, rolling refit, 63-day frequency, seed 42. | `k1066_results.json:6-14`; `README.md:36-43`. | Match |

## Methodology Check

- **Lookahead**: PASS. Training slices stop before the OOS forecast day (`train_ret_* = ret_*[train_start:abs_idx]`, `train_vix = vix[train_start:abs_idx]`) and OOS forecasts use `vix[abs_idx - 1]` plus previous-day returns. Evidence: `k1066.py:350-352`, `k1066.py:398-450`.
- **A4f VIX lag**: PASS. The fitted A4f likelihood constructs `vix_lag[1:] = vix_vals[:-1]`; OOS forecast explicitly uses `v_lag = vix[abs_idx - 1]`. Evidence: `k1066.py:230-247`, `k1066.py:422-423`, `k1066.py:440-441`.
- **DM convention**: PASS. `run_dm()` sets `d = loss1 - loss2`, so positive DM t means the second model has lower QLIKE loss and wins. Evidence: `k1066.py:585-610`, `k1066.py:613-624`.
- **Subperiod inference**: CONDITIONAL PASS. The article's 5/5 statement is backed by a simple one-sided binomial sign test, but only one subperiod is Harvey-significant (`n_harvey_significant=1`). This supports directional stability, not "each period is independently strong."

## Finding And Patch

### Finding: H2 wording overstated the statistical implication

Original article wording said H2 had "勝幅略低，而且統計上差異有意義." K1066 does not test whether DM t=4.04 is statistically different from 4.48. It only applies the pre-set gate `4.04 > 4.48`, which fails. Evidence: `k1066.py:764-767`, `k1066_results.json:319-324`.

### Patch applied

Updated the published article through:

```bash
uv run python scripts/publish_draft.py storage/drafts/mile_549aaaa4_codex_review_fix.md \
  --update mile_549aaaa4 \
  --update-action codex_review_h2_wording_fix \
  --update-summary "Codex 24h review: H2 wording downgraded because K1066 only compares DM t=4.04 with the 4.48 benchmark and does not test the difference between the two statistics; H3 wording clarified as directional binomial evidence, not per-period Harvey significance." \
  --no-sanitize --no-lazypack-gate --no-update-description
```

Changes:

- H2 now says A4f_oc did not exceed the 4.48 benchmark and that no separate test of the 4.04-vs-4.48 difference was run.
- H3 now says the 3.1% p-value is from a simple directional binomial check and that only one subperiod passes the stricter single-period threshold.
- The interpretation section now says close-to-close is "slightly stronger in this comparison" rather than definitively claiming VIX predicts full-day volatility more accurately.

`publish_draft.py --sync-supabase` hung during full `feed-sync --apply` after the local write, so it was interrupted. The single article was then synced via `scripts.supabase_sync.sync_article()`.

Remote read-back confirmed:

- `status=published`
- old phrase `統計上差異有意義` absent
- new phrase `沒有另外檢定` present
- H3 `方向一致` caveat present

## Recommendation

Keep the article live. After patch, the article's numeric claims, lookahead handling, DM/Harvey interpretation, and subperiod stability wording are aligned with K1066's source code and results.

