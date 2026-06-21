# Paper (new): Forecast-Accuracy vs Tail-Coverage Divergence — When a Volatility Model Wins QLIKE but Fails VaR

**Status**: `OUTLINE` (2026-06-21, autonomous decision per boss email-11862 "你應該自主決定")
**Target Journal**: International Journal of Forecasting (IJF) / Journal of Forecasting — methodology venue
**Mined from**: experiment corpus (research_program.md「候選新論文方向」方向 B)
**Source experiments (verified)**: k850 (TAIFEX QLIKE↔VaR paradox), k854 (7-model unified common-sample OOS + VaR), k824 (quantile-method VaR), k799/k800 (GJR QLIKE-vs-VaR conflict)

---

## 1. Thesis (one sentence)

Center-of-distribution forecast skill and tail-risk adequacy are **orthogonal**: a model can decisively win point-forecast accuracy (QLIKE) yet systematically fail 1% Value-at-Risk backtests — so a single loss function cannot rank volatility models for risk-management use, and the common "best QLIKE → use for VaR" shortcut is unsafe.

## 2. The contribution (why it's a paper, not a note)

1. **A clean, replicated demonstration** of the divergence on the SAME common sample (not cherry-picked): HAR-RV wins QLIKE by a wide margin (DM t = **−5.60**, k850) yet its 1% VaR over-violates (HAR+CF **17/450 = 3.78%**, expected 1% → RED), while the GARCH specification that *loses* QLIKE is tail-adequate (GJR+CF **2/450 = 0.42%**, Kupiec+Christoffersen+DQ trinity PASS).
2. **Mechanism**: QLIKE rewards conditional-mean-of-variance calibration; VaR adequacy depends on the *left-tail quantile* of the standardized innovation. A model can nail the former while the tail-shaping component (distributional assumption / Cornish-Fisher / conformal) is mis-specified.
3. **What does and doesn't fix it**: Cornish-Fisher and conformal calibration patches partially close the gap on the GARCH side (GJR+Normal trinity FAIL → GJR+CF trinity PASS, k854) but do **not** rescue HAR's tail (HAR+CF still 3.78% violations) — the patch interacts with the base conditional-variance process.
4. **Practical rule**: report BOTH a point-forecast loss (QLIKE/MSE) AND a tail-coverage gate (Kupiec/Christoffersen/DQ trinity + Acerbi–Szekely ES) when selecting a volatility model; ranking on one alone is a category error.

## 3. Distinct from existing VolPred papers

- **NOT** garch-x-vix / vix-sufficiency (those are forecast horse-races / VIX informativeness). Here the *result is the ranking reversal under a different loss*, a forecast-evaluation methodology point.
- **NOT** leverage-direction (GARCH selection by gamma sign). Here selection criterion = loss-function dependence itself.

## 4. Data & methods (already run — honest provenance)

- **Markets**: TAIFEX (k850, Taiwan index) + US common-sample 7-model panel (k854). Cross-market replication strengthens generality.
- **Models**: GJR-GARCH and HAR-RV families × tail treatments {Normal, Student-t, Skewed-t, Cornish-Fisher, HistSim, Conformal}.
- **Forecast eval**: QLIKE with Diebold-Mariano (HLN small-sample correction) — DM t = −5.60 (k850).
- **VaR eval**: 1% one-day VaR, Kupiec (unconditional), Christoffersen (independence), DQ (dynamic quantile) "trinity" + Basel traffic-light; ES via Acerbi–Szekely.
- **Lookahead control**: signal.shift(1), expanding/rolling refit with target_end < forecast_origin (per .claude/rules/experiments.md).

## 5. Section skeleton

1. Introduction — the "best QLIKE wins" folk theorem and why it's unsafe for risk use.
2. Setup — loss functions (QLIKE) vs coverage tests (Kupiec/Christoffersen/DQ/ES); orthogonality argument.
3. Data & models.
4. **Main result** — the divergence table (QLIKE rank vs VaR-trinity pass/fail), cross-market.
5. Mechanism — decomposition: conditional-variance accuracy vs standardized-innovation tail.
6. What patches do (CF / conformal) and their limits.
7. Practical guidance + robustness (horizons, 5% VaR, alt samples).
8. Conclusion.

## 6. Headline results table (real numbers, to be finalized)

| Model | QLIKE rank | 1% VaR viol. rate | Trinity | Verdict |
|---|---|---|---|---|
| HAR-RV (+CF) | **best** (DM t=−5.60) | 3.78% (17/450) | FAIL | wins accuracy, fails tail |
| HAR-RV (+Normal) | best | 3.33% (15/450) | FAIL | — |
| GJR (+CF) | worse | 0.42% (2/450) | **PASS** | loses accuracy, tail-safe |
| GJR (+Normal) | worse | 1.87–2.22% | FAIL (Kupiec) | — |

*(k850 TAIFEX + k854 common-sample; exact cells to be locked from the two results JSONs in the write-up.)*

## 7. Readiness / what's left to full draft

- **Draftable now**: core result + mechanism are backed by k850/k854 reviewed experiments.
- **To strengthen before submission**:
  1. One more market (e.g. SPY long sample) to make it 3-market, not 2.
  2. 5% VaR + 10-day horizon robustness (confirm divergence isn't a 1%-only artifact).
  3. Formal ES (Acerbi–Szekely) table alongside VaR trinity.
  4. Codex review of the unified-sample reproduce script.
- **No new modeling needed** — this is a synthesis + 1–2 robustness runs, not fresh method development.

## 8. Next actions (main thread)

1. Lock exact table cells from k850/k854 results JSONs.
2. Run the SPY-sample robustness (compute_queue if heavy).
3. Promote outline → body.md → body.tex once 3-market + robustness are in (per CLAUDE.md: .tex in main thread, no background agent).
