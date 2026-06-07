# mile_3f18cb8e Codex 24h Review — 2026-06-08

**Article**: `mile_3f18cb8e` 「分析師跟了 64 個人的股票，和只有 3 個人跟的股票，財報對波動率的作用一模一樣」  
**Backing experiment(s)**: `K1162` primary, with context from `K1151` / `K1157`  
**Reviewer**: Codex CLI  
**Verdict**: **CONDITIONAL_PASS**

## Findings

1. **The title overstates what K1162 actually tests.**  
   The published title in [storage/reports/feed.json](/Users/yhlai0911/Desktop/volpred-research/storage/reports/feed.json:83) says analyst-followed and thinly-followed stocks are affected by earnings volatility in “exactly the same way.” But `K1162` only runs a Wald equality test on the **continuous surprise coefficient** `θ_SURP`, not on the binary-EAV coefficient. See `wald_test_theta_diff()` in [experiments/k1162/k1162.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1162/k1162.py:600) and the README statement “Wald θ_HIGH = θ_LOW” in [experiments/k1162/README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k1162/README.md:184). The same source simultaneously reports binary-EAV bootstrap `t=+2.25` for LOW and `t=+6.07` for HIGH, so “作用一模一樣” is too strong as a headline.

2. **The article’s mechanism phrasing is stronger than the proxy design supports.**  
   The article says the phenomenon is unrelated to analyst coverage and “換言之和 EPS 數字的測量精確度無關” in [storage/reports/feed.json](/Users/yhlai0911/Desktop/volpred-research/storage/reports/feed.json:85). But `K1162` uses a **current yfinance snapshot** of `numberOfAnalystOpinions`, not a historical monthly coverage series, and the source explicitly labels this as a post-hoc mechanism-isolation proxy with a stronger I/B/E/S version still needed; see [experiments/k1162/README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k1162/README.md:79). The article does mention this limitation later, but the stronger causal wording appears earlier and should be softened.

## What Holds

1. **The quoted numbers match the experiment artifact.**  
   `LOW continuous t=-0.31, p=0.733`, `HIGH continuous t=+0.34, p=0.707`, `LOW binary t=+2.25`, `HIGH binary t=+6.07`, and Wald `t=+0.39, p=0.70` all match [experiments/k1162/k1162_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k1162/k1162_results.json:1).

2. **No lookahead bug is evident in the mechanism test itself.**  
   The source openly treats analyst coverage as a current cross-sectional snapshot for mechanism isolation rather than a trading signal, and the README discloses that limitation. On that narrower claim, the design is coherent.

3. **The core null-result message is supported.**  
   `K1162` does support the statement that the continuous surprise signal is not rescued by the high-coverage subset, and that binary EAV remains the stronger specification.

## Conclusion

This article is **not a source-integrity failure**; the main issue is framing drift. The core result “high-coverage subset does not rescue continuous surprise” is supported, but the title and one mechanism paragraph should be narrowed from “一模一樣 / 無關” to wording closer to:

- “高低覆蓋組在連續 surprise 係數上看不出統計差異”
- “在目前的 coverage snapshot proxy 下，看不到 analyst coverage 改變 continuous-signal 結論”

That would align the article with what `K1162` actually identifies.
