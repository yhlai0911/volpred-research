# Codex 24h Review - mile_d1a83b4f / K1627

- **Article**: `mile_d1a83b4f` - 美股大跌，台股隔天真的會補跌嗎？我查了兩千六百多天的數據
- **Task**: `paper_review_mile_d1a83b4f`
- **Experiment**: `experiments/k1627/`
- **Review timestamp**: 2026-07-07 00:27 Asia/Taipei
- **Verdict**: **PASS WITH NON-BLOCKING NOTE**

## Scope

Checked the published article and source experiment against:

- `storage/reports/feed.json` entry `mile_d1a83b4f`
- `storage/drafts/k1627_general_draft.md`
- `experiments/k1627/k1627.py`
- `experiments/k1627/k1627_results.json`
- `experiments/k1627/README.md`
- `experiments/k1627/codex_review.md`
- `experiments/k1627/fig_conditional_prob.png`
- `experiments/k1627/fig_transmission_scatter.png`
- `experiments/k1627/lazypack/*.png`

This review audited the committed source, results JSON, README, draft/article text, and rendered PNGs. It did not rerun the price-cache experiment, to avoid moving the public article's basis through any later cache refresh.

## Claim-Evidence Check

| Article claim | Source evidence | Status |
|---|---|---|
| SPY represents US stocks, `0050.TW` represents Taiwan market proxy, effective pairs `N=2,638`, sample starts in 2016. | Results data block lists SPY, `0050.TW`, source `data/cache/price_cache.db`, analysis start `2016-01-04`, `n_pairs=2638`, and `n_tw_unique_targets=2466` (`k1627_results.json:6-24`). README reports the same source, period, and proxy caveat (`README.md:24-32`). | PASS |
| Timing is US close day `D` to next Taiwan trading day `T`, with no future Taiwan information in the signal. | `build_pairs()` maps each US date to `np.searchsorted(tw_dates, d, side="right")`, i.e. the first TW trading date strictly greater than the US date (`k1627.py:143-169`). Results repeat the rule and no-lookahead reason (`k1627_results.json:25-34`). README explains the session timing (`README.md:34-47`). | PASS |
| Base Taiwan next-day down rate is about `43.7%` over `2,466` unique TW target days; stronger `TW<-1%` base is `13.3%`. | Results base-rate block has `P_tw_down_main_unique_twdays=0.4367396594`, `P_tw_down_strong_unique_twdays=0.1330089213`, `n_unique_tw_days=2466` (`k1627_results.json:35-42`). | PASS |
| Conditional probabilities are `29.5%`, `60.8%`, `74.5%`, `81.5%`, and `81.8%` for the article's rows. | Results have control `0.294959` (`k1627_results.json:43-48`) and threshold probabilities `0.607692`, `0.744828`, `0.815217`, `0.818182` with event counts `1170`, `290`, `92`, `33` (`k1627_results.json:49-229`). | PASS |
| "US red vs not red" difference is `31.3pp`, `z=16.1`, odds ratio `3.70`, p-value near zero. | Results show `diff=0.312733`, `z=16.10197`, chi-square p `2.47e-58`, and Fisher odds ratio `3.70262` (`k1627_results.json:66-92`). | PASS |
| Transmission regression is beta `0.485`, HAC t `7.95`, R2 `15.2%`, with US -1% implying TW about -0.485%. | Results regression block has beta `0.4845018`, HAC t `7.9524`, p `1.83e-15`, R2 `0.151909`, and the same sign interpretation (`k1627_results.json:231-245`). | PASS |
| `US<-2%` bootstrap upper CI is `88.6%`; seed and bootstrap repetitions are reported. | Results have point `0.815217`, CI `[0.738608, 0.885736]`, `n_boot_effective=2000`, threshold `-0.02`, and global seed `42` (`k1627_results.json:5`, `k1627_results.json:246-255`). | PASS |
| Dedup robustness gives `61.4%`, `76.0%`, `82.1%`, `82.8%`. | Results dedup block gives `0.614115`, `0.760300`, `0.821429`, `0.827586` (`k1627_results.json:256-277`). | PASS |

## Methodology Check

1. **Lookahead / timing: PASS.**
   - The signal is realized SPY close-to-close return on US day `D`; the response is `0050.TW` return on the first TW trading day strictly after `D`.
   - The implementation uses `searchsorted(..., side="right")`, not same-calendar-date matching (`k1627.py:156-165`).
   - There is no forecast model comparison, trading strategy backtest, or same-day TW response being predicted from information unavailable before the TW session. The many-to-one holiday case is diagnosed and handled with a dedup robustness check (`k1627_results.json:28-33`, `k1627_results.json:256-277`).

2. **Statistical overclaim: PASS.**
   - The article's strong claim is limited to a probabilistic statement: US down days materially raise next-TW-day down probability, but do not make a decline certain.
   - The "not coincidence" language is backed for the association tests and HAC regression: p-values are extremely small for the main conditional comparison and beta (`k1627_results.json:66-92`, `k1627_results.json:231-245`).
   - There are no Diebold-Mariano, Harvey, Granger, or Diebold-Yilmaz claims. The article does not claim out-of-sample forecasting superiority or a tradable alpha model.

3. **Data honesty: PASS.**
   - The article discloses `SPY / 0050.TW`, `N=2,638`, 2016+ sample, seed-fixed bootstrap, and the next-session alignment. These match the README and results metadata (`storage/drafts/k1627_general_draft.md:12-14`, `storage/drafts/k1627_general_draft.md:66-68`, `k1627_results.json:6-24`).
   - The proxy caveat is present in the README and results; the article says `0050.TW` is used to represent the Taiwan market, not that it is the official TAIEX index.

4. **Article vs experiment consistency: PASS.**
   - All public numeric claims checked above trace to `k1627_results.json`.
   - The figure files are present and nonblank. Inspected dimensions/stddev: `fig_conditional_prob.png` 1410x826, `fig_transmission_scatter.png` 1260x915, lazypack panels 1600x1000.

## Non-Blocking Note

The article mixes two base-rate denominators in a way that is transparent but could be cleaner:

- The prose reports the unconditional base rate as `43.7%` over `2,466` unique TW trading days, which matches `P_tw_down_main_unique_twdays`.
- The condition table is US-event based (`N=2,638`), and the event-universe base rate is `43.4%` (`k1627_results.json:35-42`). The README table uses this `43.4%` denominator (`README.md:70-79`).

This does not change the article conclusion, because the difference is only `0.3pp` and both denominators are explicitly present in the results. Future general-reader drafts should label the base-rate denominator consistently when the adjacent conditional table uses event-level rows.

## Recommendation

Keep the article live. No public correction is required. The supported conclusion is narrow and defensible: US market declines are a significant next-session Taiwan-market risk signal in this proxy sample, but they are neither deterministic nor a standalone trading rule.
