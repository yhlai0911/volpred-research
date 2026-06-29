# Codex 24h Review - mile_7b95b816 / K1580

- **Article**: `mile_7b95b816`
- **Task**: `paper_review_mile_7b95b816`
- **Experiment**: `experiments/K1580/`
- **Review timestamp**: 2026-06-30 03:55 Asia/Taipei
- **Verdict**: **PASS AFTER PATCH**

## Scope

Checked the published feed entry against:

- `storage/reports/feed.json` entry `mile_7b95b816`
- `experiments/K1580/k1580.py`
- `experiments/K1580/k1580_results.json`
- `experiments/K1580/README.md`
- `experiments/K1580/generate_charts.py`
- `experiments/K1580/fig_b_fullperiod_bar.png`
- `experiments/K1580/codex_review.md`

## Finding

| Finding | Evidence | Action | Status |
|---|---|---|---|
| Figure B title said `7 籃子` even though K1580 has 6 baskets. This was a presentation inconsistency in the image, not a computation or article-conclusion error. | `experiments/K1580/generate_charts.py` hard-coded `7 籃子`; `k1580_results.json` has 6 result baskets; the published article body/footer/caption says six. | Changed the title to use `{len(baskets)}`, regenerated `fig_b_fullperiod_bar.png`, and upserted the same public Supabase object URL: `https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/fig_b_fullperiod_bar.png`. | Fixed |

## Claim-Evidence Check

| Article claim | Source evidence | Status |
|---|---|---|
| Six baskets, three legs, 1993-2024 maximum history, costs included. | `K1580/README.md`; `k1580_results.json` has 6 baskets and 3 cost settings; default costs are TW 30 bps and US 10 bps. | Match |
| 0050 yfinance phantom split was cleaned. | `k1580.py:301-306` applies `clean_tw50_data()` only when `benchmark == "0050.TW"`. | Match |
| US large-cap long-run result: rebal 15.94% vs BH 15.89%. | `US_large_caps` default-cost metrics: 15.9364% vs 15.8917%. | Match |
| All rebal - BH differences are statistically insignificant. | All 6 default-cost bootstrap CI95 intervals include zero. | Match |
| 5/6 baskets have rebal CAGR flat or slightly higher; TW 0050 basket is lower. | Default-cost CAGRs: TW0050 -1.17 pp, TWII +1.50 pp, US large +0.04 pp, sectors +0.72 pp, multi-asset +0.04 pp, global +0.47 pp. | Match |
| Risk story: rebal generally has lower or comparable risk, especially US large-cap MDD -37.6% vs -46.2%. | `US_large_caps` default-cost MDD -37.6466% vs -46.2012%; vol 17.42% vs 19.33%; Sharpe 0.937 vs 0.861. | Match |
| Regime story: crisis/rotation years help, one-way mega-cap years hurt. | Subperiod table: US large 2022 +21.66 pp/yr; US 2020-21 -17.31 pp/yr; TW0050 2023-24 -14.14 pp/yr. | Match |
| Execution assumption is idealized same-day MOC, not lookahead alpha. | `execution_assumption` in results; `k1580.py:169-181` computes value at close then changes shares; new weights are not multiplied by same-day returns. | Match |

## Methodology Check

- `_basket_window` uses the max first valid date across all basket members plus benchmark, then intersects indexes; no off-by-one issue found.
- `_metrics` uses `INITIAL` as denominator, so entry cost affects total return and CAGR consistently across rebal, BH, and benchmark.
- `_simulate` uses fixed-point self-financing cost adjustment at annual rebalances; no convergence or accounting bug found for this scope.
- `_annual_returns` prepends the initial value anchor before year-end `pct_change`, so the first year is included once.
- `_subperiod_breakdown` rebases each strategy to 1.0 within each regime, which is the fair comparison for within-period performance. Short-window bootstrap is explicitly marked low power.

## Recommendation

Keep the article live. The only true issue found was the Figure B basket-count typo, and it has been fixed in source, regenerated locally, and re-uploaded to the existing public image URL.
