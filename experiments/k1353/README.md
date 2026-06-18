# K1353: 軟體/科技集中型私募信貸壓力外溢（duplicate closure）

## 問題

原任務：

> 軟體/科技集中型私募信貸壓力的板塊外溢 — BDC 籃 vs IGV/HYG RV，檢定產業曝險贖回是否在板塊 vol 留足跡（來源：MS/Lexology 2026 私募信貸軟體集中度）

## 判定

**VERDICT = SUPERSEDED_BY_K1344_NULL**

K1353 是 `research_program.md` 同一題再次 auto-generated 出來的重複任務。它已由 `experiments/K1344_private_credit_software_spillover/` 完整覆蓋。

## Canonical Coverage

K1344 已直接測試：

- BDC proxy：`BIZD`, `ARCC`, `BXSL`, `OBDC`, `FSK`
- Targets：`IGV`, `HYG`
- Controls：`SPY`, `QQQ`
- Horizons：5 與 21 trading days
- OOS：2021-01-04 後，`n_oos=1367`
- 推論：Newey-West HAC、moving-block bootstrap 1000 reps、Bonferroni alpha 0.0125
- Lookahead：所有 forecast features 明確 `.shift(1)`；event-study `signal = panel["bdc_pressure"].shift(1)`

## Canonical Result

K1344 verdict：`NULL`。

Primary OOS forecast cells:

| Target | Horizon | QLIKE improvement | DM t | p-value | Bonferroni pass |
|---|---:|---:|---:|---:|---|
| IGV | 5 | +1.91% | 0.47 | 0.635 | no |
| IGV | 21 | +7.19% | 1.35 | 0.178 | no |
| HYG | 5 | +2.98% | 0.74 | 0.462 | no |
| HYG | 21 | +5.44% | 0.86 | 0.388 | no |

The descriptive event study shows higher future variance after sparse BDC-stress events, but K1344 correctly treats it as diagnostic only. It is not enough to override the primary OOS forecast tests.

## Literature / Source Check

This duplicate closure reuses K1344's source framing and verifies that the source motivation exists:

- Financial Stability Board, "FSB warns on private credit vulnerabilities" (2026-05-06): private credit vulnerabilities include sector concentration, leverage, valuation opacity, liquidity, and data gaps.
  - https://www.fsb.org/2026/05/fsb-warns-on-private-credit-vulnerabilities/
- Morgan Stanley, "The Risks of Private Credit's Software Exposure" (2026-03-02): software exposure is large in opaque credit channels, with BDC portfolio software exposure discussed directly.
  - https://www.morganstanley.com/insights/podcasts/thoughts-on-the-market/private-credit-software-ai-disruption-vishy-tirupattur-vishwas-patkar
- J.P. Morgan Asset Management, "Tech, Software, and BDCs" (2026): BDC portfolios have material software/SaaS exposure and market implications.
  - https://am.jpmorgan.com/us/en/asset-management/institutional/insights/portfolio-insights/fixed-income/fixed-income-perspectives/tech-software-and-bdcs-navigating-volatility-and-ai-disruption-in-investment-grade-credit/
- MSCI Private Capital in Focus (2026): listed BDC performance diverged along software exposure lines.
  - https://www.msci.com/downloads/web/msci-com/discover-msci/events/event-assets/2026/may/Presentation_%20Private%20Capital%20in%20Focus_USEurope_May132026.pdf

## Conclusion

K1353 should not be rerun as a new empirical experiment. The correct action is to close the duplicate, update `research_program.md`, and preserve K1344 as the canonical artifact.

No `knowledge.json` write is appropriate because this is a duplicate closure over an existing NULL result.

## Files

- `K1353.py`
- `K1353_results.json`
