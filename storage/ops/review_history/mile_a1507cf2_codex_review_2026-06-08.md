# mile_a1507cf2 Codex 24h Review — 2026-06-08

**Article**: `mile_a1507cf2` 「K951：Copula-GARCH 在高相關 ETF 配對避險上全面落敗 Rolling OLS — 尾部結構缺失是根本原因」  
**Backing experiment(s)**: `K951` primary, with comparison to `K931` and `K923`  
**Reviewer**: Codex CLI  
**Verdict**: **FAIL**

## Findings

1. **The article attributes a formal “Harvey gate” that the source code does not actually implement.**  
   The published article says the DM tests “均通過 Harvey \|t\| > 3.0 門檻” and the methods table labels the test as “Diebold-Mariano（Harvey 1997 修正）；門檻 \|t\| ≥ 3.0” in [storage/reports/feed.json](/Users/yhlai0911/Desktop/volpred-research/storage/reports/feed.json:62). But `K951`’s `dm_test_hedge()` is a plain HAC-style DM t-stat on squared hedged returns, with Newey-West variance and **no Harvey-Leybourne-Newbold small-sample correction term at all**; see [experiments/k951/k951.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k951/k951.py:229). The `***` marker is then assigned by a hardcoded `abs(t_stat) > 3.0` rule in [experiments/k951/k951.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k951/k951.py:528), which is a house threshold, not a documented Harvey significance test. This is a methodological overstatement, not just wording.

2. **The article’s cross-experiment comparison misstates K931’s correlation regime, weakening the “asset type, not correlation level” claim.**  
   `K951`’s article frames `K931` as the high-correlation counterexample and says SPY-QQQ’s `0.937` is “與 K931 的 0050-TSMC 相當” in [storage/reports/feed.json](/Users/yhlai0911/Desktop/volpred-research/storage/reports/feed.json:62). But the `K931` source says Pearson `r = 0.7259`, rolling-250d mean `0.8135`, with a wide range `[0.349, 0.955]`; see [experiments/k931/README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k931/README.md:28). `K951`’s own README also incorrectly summarizes `K931` as `r>0.9` in [experiments/k951/README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k951/README.md:6). Once that premise is corrected, the article can still argue “ETF diversification may matter,” but not with the same confidence that “asset type rather than correlation level” has been isolated.

3. **The mechanism section goes beyond what K951 alone identifies.**  
   The article presents “ETF 是分散化組合，所以尾部結構被平滑掉” as the root cause and then elevates that into the general takeaway that copula works for individual stocks but not ETFs in [storage/reports/feed.json](/Users/yhlai0911/Desktop/volpred-research/storage/reports/feed.json:62). `K951` does show `nu=30` for these three ETF pairs and worse HE for copula, but causally pinning that to “asset type” requires more than three ETF pairs plus one Taiwan constituent pair. The source itself is narrower: it tests three ETF pairs and reports the pattern; stronger generalization should stay labeled as a hypothesis.

## What Holds

1. **The headline performance numbers quoted for K951 match the experiment artifact.**  
   HE values and DM t-stats for `SPY-QQQ`, `GLD-SLV`, and `SPY-EWG` match [experiments/k951/k951_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k951/k951_results.json:1): e.g. OLS-vs-Copula DM `-3.14 / -3.28 / -3.48`, and Copula HE `0.821 / 0.442 / 0.561`.

2. **No obvious lookahead bug appears in the hedge-ratio construction.**  
   OLS, rolling OLS, DCC proxy, and copula refits all use data through `t-1` for the hedge ratio applied at OOS day `t`; see [experiments/k951/k951.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k951/k951.py:309), [experiments/k951/k951.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k951/k951.py:334), and [experiments/k951/k951.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k951/k951.py:393).

3. **The descriptive `nu → 30` pattern is real in this artifact.**  
   The stored copula `nu` histories are indeed all `30.0` in [experiments/k951/k951_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k951/k951_results.json:1), so the article is not inventing that numerical pattern.

## Conclusion

This article is **not numerically fabricated**, but it fails the 24h source-integrity bar because two central claims are stronger than the source supports:

- the “Harvey gate” language implies a formal corrected significance procedure that `K951` does not implement;
- the `K931` comparison is misstated in a way that materially props up the article’s main interpretive claim.

To recover this piece, the article should be narrowed to something like:

- `K951 shows Student-t copula underperforms simpler hedge ratios on these three ETF pairs`
- `within this sample, nu saturates at 30 and copula hedge ratios appear systematically too high`
- `K931 suggests concentrated constituent pairs may behave differently, but asset-type vs correlation-level separation remains provisional`
