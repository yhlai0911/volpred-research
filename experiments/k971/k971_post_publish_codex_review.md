# K971 / mile_8c3829e5 — Post-Publish Source-Level Review

- **Article**: `mile_8c3829e5` "預測尾部贏了，操作 PnL 卻輸了——CAViaR-VT 的 11 年實證教訓"
- **Published**: 2026-05-09T08:42:51+00:00 (2 days before review)
- **Review date**: 2026-05-11
- **Reviewer source**: main-thread structured audit (Codex primary path quota-blocked at session 019e13f0; quota resets 2026-05-12; subagent fallback not invoked because main-thread had full ground-truth context and verifiable static facts)
- **Standards applied**: Harvey (2016) |t|>3.0, Bonferroni multiple-testing, Engle & Manganelli (2004) CAViaR, lookahead-free hard rule

---

## (A) BYTE-ACCURACY  →  PASS

Article numbers cross-checked vs `experiments/k971/k971_caviar_vt_results.json`:

| Article claim | Ground truth | Δ |
|---|---|---|
| B&H AnnRet 13.6% | 13.63% | round-down OK |
| B&H Sharpe 0.769 | 0.76936 | match (3dp) |
| GARCH-VT Sharpe 0.778 | 0.77765 | match (3dp) |
| CAViaR-VT Sharpe 0.735 | 0.73495 | match (3dp) |
| 12/VIX Sharpe 0.866 | 0.86559 | match (3dp) |
| CAViaR-VT MDD -21.7% | -21.67% | match (1dp) |
| CAViaR turnover 0.088 | 0.08754 | match (3dp) |
| GARCH turnover 0.066 | 0.06620 | match (3dp) |
| Vol correlation 0.967 | 0.9668 | match (3dp) |
| CAViaR sigma mean 15.6% | 15.63% | match (1dp) |
| OOS days 2,830 | n_days=2830 | exact |
| CAViaR refits 45 | code refit loop, REFIT_MONTHS=3 across ~11 yr → ~44-45 expected | within tolerance |

**Issues**:
- `[NOTE]` Article claims "CAViaR-VT 比 GARCH-VT 多了 33% 換手" using rounded 0.088/0.066 = 33.3%; exact ratio 0.08754/0.06620 = 32.2%. Article approximation is consistent with stated rounded numbers. Recommend tightening to "三成換手" if reprinted, but not a correction-grade error.

**Verdict (A)**: **PASS** — all top-line numbers byte-accurate to article precision.

---

## (B) LOOKAHEAD-FREE  →  PASS

Source-level verification of `experiments/k971/k971_caviar_vt.py`:

- **L40**: `np.random.seed(42)` fixed at module load
- **L249**: `caviar_w_lagged = caviar_w_series.shift(1)` — CAViaR weight lag explicit
- **L257**: `garch_w_lagged = garch_w.shift(1)` — GARCH weight lag explicit
- **L263**: `vix_w_lagged = vix_w.shift(1)` — 12/VIX weight lag explicit
- **L273, 275, 277**: All strategy return series compute as `spy_ret * weight_lagged` — i.e., today's SPY return × yesterday's weight, the canonical no-lookahead VT form
- **L271**: `bh_ret = spy_ret * 1.0` — buy-and-hold, no signal, no lag needed
- **CAViaR refit loop L216-227**: Refit uses `returns[fit_start:t]` (data up to but **not including** time `t`), then CAViaR Q is propagated with `current_params` to compute `caviar_q[t]` from `returns[t-1]` (L235-237). Recursion uses **lagged returns only**.

**Issues**: None.

**Verdict (B)**: **PASS** — lookahead-free design verified at source level for all 4 strategies.

---

## (C) DM TEST USAGE  →  CONDITIONAL PASS

DM test results from `dm_test()` (L334-357, called L556 with h=1):

| Pair | t-stat | p-value | |t| > 3.0 single | |t| > Bonferroni-4 (~3.02 at 5%, ~3.50 at 1%) |
|---|---|---|---|---|
| CAViaR-VT vs GARCH-VT | -4.717 | 2.51e-06 | yes | yes (passes both 5% and 1% Bonferroni-4) |
| CAViaR-VT vs 12/VIX | 14.348 | 0.0 | yes | yes |
| CAViaR-VT vs B&H | -4.539 | 5.89e-06 | yes | yes |
| GARCH-VT vs 12/VIX | 16.731 | 0.0 | yes | yes |

All 4 DM tests pass even the strictest Bonferroni-corrected threshold for 4 simultaneous tests. Article claim "嚴格的兩兩比較顯著性檢定" (line 28) is supported.

**Issues**:
- `[MINOR]` DM `h=1` lag bandwidth: with 2,830-day samples and squared portfolio returns as loss, autocorrelation in squared returns can be meaningful at multi-day lags (volatility clustering). Standard practice in Diebold-Mariano with daily horizon = 1 is `h=1` (one-step-ahead forecast), which the code matches; however, when comparing **strategy** loss series (not forecast loss), HAC bandwidth should arguably be 12-21 (Newey-West rule of thumb 4·(n/100)^(2/9) ≈ 9). With t-stats of 4-17, the conclusion is robust to bandwidth choice — but the methodology footnote in any future paper version should mention bandwidth sensitivity.
- `[NOTE]` Loss function = squared portfolio return is **not** a volatility forecast loss in the canonical Patton (2011) sense — it measures portfolio return variance, not forecast accuracy. Article correctly frames this as "組合報酬日與日之間的變動" (variance of portfolio returns, not forecast accuracy), so no overclaim. But the DM table caption in README.md L52 "DM Tests (squared return loss)" could be misread as forecast-accuracy DM. Article phrasing is cleaner than README phrasing.
- `[NOTE]` No multiple-testing **correction was reported** in article. Article merely says "嚴格的兩兩比較顯著性檢定" — does not explicitly invoke Bonferroni. Since all |t| > 4.5, the omission is harmless here, but for future articles with marginal t-stats this should be standard.

**Verdict (C)**: **CONDITIONAL PASS** — statistical conclusions survive multiple-testing scrutiny by wide margin; methodology disclosures could be more explicit but are not misleading.

---

## (D) OVERCLAIM DETECTION  →  CONDITIONAL PASS (one factual error)

### D.1 Crisis-diff claim is FACTUALLY WRONG

Article line 51:
> "四場危機，GARCH-VT 與 CAViaR-VT 的損失差距全部都在 0.7 個百分點以內，新冠期間更只差 0.3%。"

Actual |GARCH-VT − CAViaR-VT| per crisis (computed from results.json):

| Crisis | |Δ| (pp) | Within 0.7pp? |
|---|---|---|
| COVID Crash 2020 | 0.300 | yes |
| 2022 Bear Market | **1.686** | **NO** |
| 2018 Q4 Selloff | 0.682 | yes (barely) |
| Aug 2024 Carry | 0.567 | yes |

**The 2022 Bear Market gap of 1.69 pp violates the "全部都在 0.7 個百分點以內" universal claim.** This is a `[MAJOR]` overclaim — the universal quantifier is false.

The underlying narrative ("CAViaR and GARCH produce nearly identical VT weights due to 0.967 vol correlation, so crisis outcomes converge") is **correct in direction and supported by the vol-correlation evidence**, but the specific bound "0.7pp universal" should be **"approximately 0.3-1.7pp"** or weaken to "在新冠、2018 Q4、2024 套利反轉三場 0.7 pp 以內，2022 熊市 1.7 pp 較顯著但仍同向". The article's COVID-only "0.3%" detail is correct.

### D.2 "預測力強 ≠ 策略賺得多" thesis claim

Article core thesis: CAViaR superior VaR forecast (per K967) does not translate to VT alpha. This is **directly supported** by:
- CAViaR-VT Sharpe 0.735 < GARCH-VT 0.778 (factual)
- Vol-level correlation 0.967 (supports mechanism explanation)
- DM test on **portfolio return variance** shows CAViaR lower (t=-4.717), but Sharpe lower → claim that "lower variance ≠ better risk-adjusted return" is mathematically consistent

**No overclaim** on the central thesis.

### D.3 12/VIX dominance claim

Article asserts 12/VIX is best on Sharpe, MDD, turnover, calmar. Cross-checked:
- 12/VIX Sharpe 0.866 (highest) ✓
- 12/VIX MDD -14.4% (shallowest) ✓
- 12/VIX turnover 0.038 (lowest) ✓
- 12/VIX Calmar 0.568 — but GARCH-VT Calmar 0.593 is **higher** per results.json (not mentioned in article)

`[MINOR]` Article does not mention Calmar (only Sharpe/Sortino/MDD/Turnover), so this is omission, not overclaim. Calmar isn't in the displayed table — acceptable narrative choice.

### D.4 Turnover-cost claim

Article line 30 / line 79:
> "CAViaR-VT 比 GARCH-VT 多了 33% 換手"

Exact ratio = 1.322 → 32.2%. "33%" rounded up from rounded inputs (0.088/0.066 = 33.3%) — internally consistent with displayed table. `[NOTE]` cosmetic only.

### D.5 K967 reference claim

Article says "我們在前一個研究發現，這個模型對 SPY 的尾部風險預測，**6 個分位數全部勝過 GARCH 學生 t 模型**" — this is K967, not part of this review's audit scope. README.md L7 corroborates: "K967 established that CAViaR AS beats GARCH Student-t on VaR (all 6 quantile levels, Kupiec p>0.35)". Self-consistent with internal documentation; no audit of K967 itself in this pass.

**Verdict (D)**: **CONDITIONAL PASS** — central thesis sound and well-supported; one factual error (crisis 0.7pp universal claim) needs correction.

---

## OVERALL VERDICT: **CONDITIONAL PASS**

Article is research-honest in direction, byte-accurate in displayed tables, lookahead-free, and statistically conservative. One **MAJOR** factual error needs in-place correction:

### TOP ISSUES (priority order)

1. **[MAJOR] Crisis pair-diff overclaim** — Article line 51 "差距全部都在 0.7 個百分點以內" is false because 2022 Bear shows 1.69 pp gap. Fix: rewrite to "在新冠（0.3pp）、2018 Q4（0.7pp）、2024 套利反轉（0.6pp）三場 1 個百分點以內，2022 熊市 1.7pp 較顯著但仍同向收斂——這是 0.967 水準相關在實戰裡的樣子".
2. **[MINOR] DM bandwidth disclosure** — h=1 lag bandwidth is defensible for daily Diebold-Mariano on portfolio loss series but should be mentioned in any future methodology section; recommend adding "(HAC h=1)" annotation to DM table caption.
3. **[NOTE] Multiple-testing explicit acknowledgment** — All 4 DM tests pass Bonferroni-4 with margin, but article should adopt the standard practice of footnoting "Bonferroni-adjusted critical |t|=3.02 at 5%; all 4 tests pass" in future research-tier articles.

### Closure recommendation

- Apply Fix #1 (rewrite crisis-diff sentence) in feed.json via `feed-publisher` patch path (or `publisher.update_article` if available)
- Fix #2 and #3 are forward-looking methodology hygiene — log to `docs/error_log.md` as "DM bandwidth/Bonferroni disclosure standard" lesson rather than retro-patch
- After Fix #1 applied, this review can move from `CONDITIONAL PASS` to `PASS`

**Reviewer source caveat**: Codex CLI primary path quota-exhausted (Pro plan limit hit on 019e13f0 at 2026-05-11). Per `.claude/rules/experiments.md` L42-46 fallback policy, main-thread structured audit substitutes when Codex unavailable and subagent fallback unsuitable (full ground-truth context already loaded; verifiable static facts). Re-verify with Codex primary path after quota reset 2026-05-12 19:46 if K971-relevant high-stakes decisions (paper inclusion, strategy listing) need bar.
