VERDICT: NEEDS_REVISION

1. HIGH — Lag / lookahead disclosure mismatch.
   Evidence: article says all SKEW/VIX signals use `t-1` values (`storage/reports/feed.json:398`), but the model features are contemporaneous levels with no `.shift(1)` on `SKEW`/`VIX` (`experiments/k447/k447_skew_index.py:133-149`). This is not obvious lookahead against future targets, but the article's stated lag convention is false and should be corrected.

2. MEDIUM — Tail-event model claim overstates inferiority of adding SKEW.
   Evidence: article says adding SKEW "讓 VIX 變得更糟" (`storage/reports/feed.json:398`) because AUC falls from 0.824 to 0.743, but Brier score improves from 0.1299 to 0.0678 (`experiments/k447/k447_skew_index_results.json:231-263`). The evidence is metric-conflicted, so the article cannot present the combined model as unambiguously worse.

3. MEDIUM — OOS tail-rate narrative is stronger than the test supports.
   Evidence: article says the high-SKEW tail-risk story was "在 OOS 階段被資料推翻" (`storage/reports/feed.json:398`), but the tercile chi-square test is not significant (`p=0.1341`) even though the monotone rates are 8.6% / 5.2% / 4.7% (`experiments/k447/k447_skew_index_results.json:291-313`). This supports "no confirming evidence," not a clean statistical refutation.
