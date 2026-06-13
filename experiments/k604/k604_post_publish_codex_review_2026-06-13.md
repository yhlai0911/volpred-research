# K604 / mile_651c242d — Post-Publish Source-Level Review

- **Article**: `mile_651c242d` "好策略被成本吃掉 27%：11 個 VT 策略的實施費用拆解"
- **Published**: 2026-06-12T16:01:01.081301+00:00
- **Review date**: 2026-06-13
- **Reviewer**: Codex desktop
- **Task**: `paper_review_mile_651c242d`
- **Linked K**: `K604`

## (A) 表格數字一致性 → PASS

Cross-check against [`experiments/k604/k604_implementation_costs_results.json`](/Users/yhlai0911/Desktop/volpred-research/experiments/k604/k604_implementation_costs_results.json):

| 文章宣稱 | Ground truth | Verdict |
|---|---|---|
| 11 策略平均風報比損耗 27.2% | `summary.avg_sharpe_reduction_pct = 27.2` | ✅ |
| Adaptive Tier VT 2.932 → 2.095，損耗 28.5% | `adaptive_tier.net_sharpe` | ✅ |
| Piecewise Conservative 2.554 → 1.776 | `piecewise_conservative.net_sharpe` | ✅ |
| 12/VIX 0.683 → 0.424，損耗 37.9% | `simple_12vix.net_sharpe` | ✅ |
| 台股平均交易成本 4.34%/年，美股 0.34%/年 | `summary.key_findings` 明示同值 | ✅ |
| 12/VIX 交易成本 0.09%/年 | `simple_12vix.operational_cost_pct = 0.0879%` | ✅（四捨五入） |
| Adaptive Tier 稅負 6.72%/年 | `adaptive_tier.cost_breakdown.us_tax_drag_pct = 6.72` | ✅ |

Top-line table values and ranking claims are consistent with the current results artifact.

## (B) Lookahead / 方法檢查 → PASS

- This experiment is an implementation-cost analysis driven by `paper_trading.json` weight histories, not a predictive backtest article.
- No new trading signal is generated inside [`experiments/k604/k604_implementation_costs.py`](/Users/yhlai0911/Desktop/volpred-research/experiments/k604/k604_implementation_costs.py); the script aggregates realized weights, turnover, spreads, commissions, taxes, and margin costs.
- Therefore the main review focus is source-to-prose fidelity rather than lookahead bias. No lookahead-specific issue is implicated here.

## (C) Major content-vs-source mismatch → FAIL

### C.1 Taiwan VT "minimum capital threshold" is misinterpreted in the article

Article text says:

> 台股 VT 策略的最低進場資本門檻是 977,005 美元。低於這個門檻，佣金比例失控，策略從賺錢變賠錢。

But the source code defines this threshold differently:

- [`experiments/k604/k604_implementation_costs.py:519`](/Users/yhlai0911/Desktop/volpred-research/experiments/k604/k604_implementation_costs.py:519) computes `min_for_commission = int(annual_commission / 0.005)`.
- The docstring in [`experiments/k604/k604_implementation_costs.py:504`](/Users/yhlai0911/Desktop/volpred-research/experiments/k604/k604_implementation_costs.py:504) states the criterion is:
  `Commission costs < 0.5% of portfolio per year`.
- In results, `taiwan_8.63vix.minimum_portfolio.reason = "commission threshold"` and `minimum_portfolio_usd = 977005`.

So `977,005` is a **practical commission-ratio threshold**, not a proven **profitability breakeven**.

The article's sentence "低於這個門檻，策略從賺錢變賠錢" is unsupported by the source artifact. The code never solves for net return crossing zero, and the result file never labels this threshold as breakeven.

This is a **material prose overclaim**, because it changes the meaning from:

- "below this size, commissions exceed 0.5%/yr"

to:

- "below this size, the strategy becomes loss-making"

Those are not equivalent claims.

## (D) Secondary research hygiene issue → CONDITIONAL

- [`experiments/k604/README.md`](/Users/yhlai0911/Desktop/volpred-research/experiments/k604/README.md) is still a planning placeholder, which violates the experiment three-piece documentation standard.
- This is not the article's main factual failure, but it weakens auditability.

## Overall verdict

**FAIL**

Reasons:

1. Core table numbers are accurate.
2. However, the Taiwan VT "minimum capital threshold" paragraph overstates what the experiment actually computes.
3. README is also incomplete, adding an avoidable audit-trail weakness.

## Required correction

The offending sentence should be weakened to reflect the real meaning of the metric, e.g.:

- "這個數字代表的是 practical commission threshold：低於約 97.7 萬美元時，固定佣金會超過每年資產的 0.5%，實施摩擦明顯升高。"

Do **not** describe it as a profitability breakeven unless K604 is extended to compute an actual net-return crossing point.
