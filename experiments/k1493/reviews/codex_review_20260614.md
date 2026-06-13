# Codex Review — K1493

- Date: 2026-06-14
- Reviewer: Codex
- Verdict: PASS with caveats

## Scope

Reviewed `experiments/k1493/k1493.py` and `experiments/k1493/k1493_results.json` for:

- data-source transparency
- reproducibility artifacts
- lookahead / timing interpretation
- formal comparison methods
- conclusion strength

## Findings

No high-severity implementation issue found.

Medium caveat:

- `VRP_t = VIX_t^2 - forward_RV21_t` is intentionally ex-post and not tradable. The script and README label it as a diagnostic, so this is acceptable, but any article must avoid calling the VRP proxy a trading signal.

Low caveats:

- `SVXY_actual` mixes short-vol carry, VIX futures roll, daily product rebalancing, leverage changes, and tail events. The README correctly avoids attributing the entire deterioration to pure VRP decline.
- `short_VIXY_naive` and `short_VXX_naive` ignore borrow, margin, recalls, and capital-survival constraints. The results JSON and README label them as naive proxies.
- `BIL` has mechanically high post-2018 Sharpe due tiny volatility, so it should be described as a cash hurdle, not a comparable risky allocation.

## Verification

- `uv run python experiments/k1493/k1493.py`
- `uv run python -m py_compile experiments/k1493/k1493.py`
- Results JSON parsed and matched headline README values:
  - VRP pre mean `0.00873`
  - VRP post mean `0.00711`
  - Welch p-value `0.407`
  - SVXY pre Sharpe `0.808`
  - SVXY post Sharpe `-0.249`

## Conclusion

K1493 supports a conservative conclusion: public-data VRP mean decline is not statistically established, but tradable short-vol proxy economics deteriorate sharply after 2018. The experiment is suitable for knowledge promotion after main-thread approval.
