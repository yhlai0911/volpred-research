# Codex 24h Review - mile_68285aa0 / K1576

- **Article**: `mile_68285aa0`
- **Task**: `paper_review_mile_68285aa0`
- **Experiment**: `experiments/K1576/`
- **Review timestamp**: 2026-07-01 07:47 Asia/Taipei
- **Verdict**: **PASS**

## Scope

Checked the published feed entry and article claims against:

- `storage/reports/feed.json` entry `mile_68285aa0`
- `experiments/K1576/k1576.py`
- `experiments/K1576/k1576_results.json`
- `experiments/K1576/event_ticker_metric_results.csv`
- `experiments/K1576/events.csv`
- `experiments/K1576/README.md`
- `experiments/K1576/codex_review.md`
- `experiments/K1576/fig_a.png`
- `experiments/K1576/fig_c.png`

This review did not rerun the yfinance download path, to avoid moving the public article's basis through data-vendor revisions. It instead audited the committed script, cached detail CSV, results JSON, and article text.

## Claim-Evidence Check

| Article claim | Source evidence | Status |
|---|---|---|
| The article is based on K1576 and references 9 defense-spending announcement dates. | Feed details reference `K1576`; `events.csv` has 9 source-linked NATO / UK / Germany / EU events; `README.md:7-17` and `README.md:33-45` match the article's event set. | Match |
| The ETF universe is 10 tickers split into defense, industrial / transport, rates, dollar, and benchmark channels. | `k1576.py:47-61` defines ITA/PPA/XAR, XLI/IYT, TLT/IEF, UUP, SPY/QQQ; `README.md:47-57` reports the same universe. | Match |
| Sample period is 2014-01-28 to 2026-01-31 using yfinance adjusted close. | `k1576_results.json::data.sample_start/sample_end/price_source`; `README.md:47-50`; `k1576.py:79-117` downloads `auto_adjust=True`. | Match |
| Event windows exclude announcement day: RV post starts T+1; pre baseline is T-30..T-6; beta post is T+1..T+63 versus T-90..T-6. | `k1576.py:34-38`, `k1576.py:137-166`, `k1576.py:213-242`; `README.md:59-84`. Mechanical CSV check confirmed `post_start > anchor_date` and `pre_end < anchor_date` for all 315 rows. | Match |
| The article's summary table reports 90/90/90/45 rows with mean, median, and fraction above baseline. | Recomputed from `event_ticker_metric_results.csv`: `t1_r2` 90, mean 1.154841, median 0.527172, frac 0.288889; `rv5` 90, 1.299284, 0.892459, 0.477778; `rv22` 90, 1.824508, 1.167999, 0.600000; `beta63_delta` 45, -0.041189, -0.030377, 0.422222. | Match |
| There are 315 p-values and 0 Bonferroni-significant tests. | Detail CSV has 315 rows and 315 non-null bootstrap p-values; Bonferroni alpha is 0.000158730159; zero rows satisfy `boot_p_value < alpha`. `k1576_results.json::multiple_testing` matches. | Match |
| Defense-specific RV and beta evidence is not stronger than benchmark / industrial comparisons. | `README.md:99-109` and `k1576_results.json::contrast_summary`: `rv5` defense-minus-benchmark mean -0.387, `rv22` defense-minus-benchmark mean -0.434, beta defense-minus-industrial mean -0.042. | Match |
| 2025 Hague opening example says ITA RV rose, SPY did little, and defense beta fell about 0.05. | Hague rows show ITA `rv5=1.747`, SPY `rv5=0.262`, and the three defense ETFs' average `beta63_delta=-0.0537`. | Match, with a wording note below |
| Figures support the article's takeaways. | `fig_a.png` is the 5-day RV distribution by channel from `k1576.py:533-550`; `fig_c.png` is the mean RV ratio heatmap from `k1576.py:568-585`. File inspection confirms nonempty PNGs with expected dimensions. | Match |

## Methodology Check

- Lookahead: no same-day return is used in the event response. `trading_day_offset()` maps T=0 to the first trading day at or after the announcement date, then RV and beta post windows start at `POST_START_REL = 1`.
- Multiple testing: the article correctly treats unadjusted positives as non-actionable. K1576 uses one Bonferroni family across all 315 bootstrap p-values.
- Bootstrap: random anchors are same-ticker and seed-fixed (`SEED = 42`). The bootstrap is one-sided for RV increases and beta increases, which matches the article's question.
- Sign tests: article prose is consistent with the direction of the pooled sign tests and does not turn `rv22`'s descriptive elevation into a trading signal.
- Identification limits: the article states the key weaknesses: only 9 events, daily data, US-listed ETF proxy limitations, anticipation, and macro-event confounding.

## Non-Blocking Note

The opening paragraph says "這檔國防 ETF ... 連動度 ... 降了 0.05" after naming ITA. The -0.05 number is the average across ITA/PPA/XAR for the 2025 Hague event (`-0.0537`), while ITA alone is `-0.1403`. Because the later body explicitly reports "國防三檔（ITA/PPA/XAR）平均 -0.058", this is a wording ambiguity rather than a numeric contradiction. No public correction is required, but future edits could change "這檔" to "三檔國防 ETF 平均" for precision.

## Recommendation

Keep the article live. The public conclusion is appropriately narrow: defense-spending announcements are visible headlines, but K1576 does not find robust defense-specific daily ETF RV or beta effects after multiple-testing correction and benchmark contrasts.
