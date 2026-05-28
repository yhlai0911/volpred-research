VERDICT: NEEDS_REVISION

1. HIGH — article date is wrong on its face.
   Evidence: the article says `2026-06-13` CPI release at 8:30 ET (`storage/event_articles/us_cpi_2026_06_13_t7/article.md:3`), but `2026-06-13` is a Saturday, and the same article later says the T-2 preview is expected on `2026-06-11` (`article.md:101`). The evidence package only analyzes historical releases through `2026-05-13` (`analysis.py:39-53`), so the lead date needs correction before publication can be trusted.

2. HIGH — unsupported “CPI surprise vs VIX reaction” claim.
   Evidence: the article states “CPI surprise 方向 vs VIX 反應方向的關聯，在過去一年幾乎為零” (`article.md:91`), but `storage/event_articles/us_cpi_2026_06_13_t7/analysis.py` computes VIX day changes, VIX9D/VIX ratios, and post-CPI VIX paths only (`analysis.py:87-198`). There is no CPI-surprise series, no sign-concordance test, and no regression/correlation output supporting that sentence.

3. MEDIUM — “抽籤 / 方向完全不可預測” is stronger than the evidence supports.
   Evidence: the historical sample is only `N=13` (`article.md:31`; `evidence.json`), and the script reports descriptive moments plus a t-test for the VIX9D/VIX ratio (`analysis.py:134-140`) but no formal sign/binomial test for “7 up, 6 down” (`article.md:35`) and no predictive model. The data support “small-sample, noisy, no clear edge,” not a definitive statement that CPI-day VIX direction is unforecastable.
