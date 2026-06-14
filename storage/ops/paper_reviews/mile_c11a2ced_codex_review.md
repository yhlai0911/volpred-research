# Paper review (Codex 24h-rule): `mile_c11a2ced` / `K1095`

- **Article**: 把兩個工具換著用，反而更差？台股波動率策略的一場假設破功
- **K-id**: K1095
- **Reviewer**: Codex desktop
- **Review date**: 2026-06-14
- **VERDICT**: FAIL

## Critical findings

1. **Pre-event branch uses ex-post announcement dates, so the `[-5,+5]` switch is not a verified tradable signal**  
   Source code loads only realized `announce_date` from `財報公告日.txt`, stores no publication timestamp or schedule provenance, then marks every day in `[T-5, T+5]` as an event day and switches the strategy on that mask: [`experiments/k1095/k1095.py:124`](experiments/k1095/k1095.py), [`experiments/k1095/k1095.py:208`](experiments/k1095/k1095.py), [`experiments/k1095/k1095.py:392`](experiments/k1095/k1095.py).  
   The article then treats this as a legitimate forward-looking event overlay: [`storage/reports/feed.json:10758`](storage/reports/feed.json).  
   This is not research-honest unless you can prove the exact earnings date was known at least five trading days in advance. With the current artifact, the pre-event window can only be constructed ex post. That makes the core “switch before/around earnings” backtest vulnerable to lookahead bias.

2. **The reported “Diebold-Mariano” test is actually a HAC t-test on return differences, not a DM/HLN forecast-comparison test**  
   The function named `dm_test()` computes the mean of daily return differences and a Newey-West style standard error on that difference series: [`experiments/k1095/k1095.py:541`](experiments/k1095/k1095.py). It does not compare forecast loss differentials, does not implement Harvey-Leybourne-Newbold correction, and does not match the project’s usual “DM/Harvey gate” standard.  
   README Table 2 still labels this as “DM tests”: [`experiments/k1095/README.md:85`](experiments/k1095/README.md), and the published article says “用嚴格的統計檢定（Diebold-Mariano）確認”: [`storage/reports/feed.json:10758`](storage/reports/feed.json).  
   The qualitative ranking may still be directionally right, but the article currently overstates the formality of the inference.

## Major findings

3. **Announcement-day mapping is internally ambiguous and likely off by one trading day for after-close releases**  
   The in-code comment says Taiwan earnings are typically announced after close and even raises `N+1` as the natural mapping, but the implementation maps to the first trading day `>= announce_date`, not the next trading day: [`experiments/k1095/k1095.py:188`](experiments/k1095/k1095.py).  
   Because weights are shifted again afterward, this ambiguity propagates into which days count as event, non-event, and boundary-switch days. It does not necessarily reverse the null result, but it does weaken the precision of the event-window interpretation.

4. **The article’s causal mechanism claim is stronger than what K1095 directly measures**  
   The article says A4f’s edge comes from “整體預測準確度” and that the switch “截掉了它真正拉開差距的地方”: [`storage/reports/feed.json:10758`](storage/reports/feed.json).  
   K1095 itself measures strategy returns, event/non-event Sharpe splits, turnover, and the mislabeled `DM` return-difference test. It does not decompose forecast-accuracy contributions by event status inside this experiment. That mechanism may be plausible from earlier Ks, but this article presents it as if K1095 alone established it.

## Minor findings

- README Table 2 says “Mean diff (daily)” but reports values in `bp/y`, which is a unit mismatch: [`experiments/k1095/README.md:87`](experiments/k1095/README.md).
- The article body omits the experiment reference in the structured top-level fields (`experiment_refs` is only inside `details`), which makes downstream provenance weaker than usual: [`storage/reports/feed.json:10755`](storage/reports/feed.json).

## What survives

- The main descriptive ranking in the current artifacts is internally consistent: `switch_net` Sharpe `0.777` < `pure_vix_net` `0.929` < `pure_a4f_net` `0.966`, matching the article headline and README tables.
- The lag on VIX and A4f forecast inputs is explicit at the weight-construction level: [`experiments/k1095/k1095.py:378`](experiments/k1095/k1095.py), [`experiments/k1095/k1095.py:409`](experiments/k1095/k1095.py).
- The null-result direction is plausible, but it is not publish-safe in its current form because the inferential and timing claims are overstated.

## Required follow-up

1. Rebuild the event overlay with a **known-in-advance schedule source** or reframe the study as a descriptive ex-post regime partition, not a tradable switching strategy.
2. Rename the current test to what it is (`HAC test on return differences`) or implement the proper project-approved comparison method and then update README/article wording.
3. Resolve the after-close event-day mapping rule and rerun the experiment.
4. Revise the article before keeping it published; current wording should not stay as-is under the project’s research-honesty standard.
