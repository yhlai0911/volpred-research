# LaTeX Academic Review — vt-insurance-cost (v2, first full formal round)

**Manuscript**: `paper/vt-insurance-cost/main.tex` (mtime 2026-07-01 18:37; 279 lines)
**Date**: 2026-07-06
**Reviewer source**: `codex exec` (GPT-5.4, ChatGPT auth) independent deep review, orchestrated + code-verified by main thread (Claude opus)
**Scope**: logic structure / argument quality / model spec / equation consistency / symbol consistency / methodology rigor. Citation bibliographic accuracy handled in `citation_check_report.md`.

> **Note on this round**: This is the **first full formal review round**. `review_history/v1/` contained only a citation-only diagnostic (2026-07-05). `audit_2026-06-10/` and `diagnosis_v1/` were targeted audits (footnote/spec fixes + reproduce divergence), not full structural reviews.

---

## Overall Assessment

| Item | Verdict |
|---|---|
| **Overall verdict** | **需大改 (Major revision)** |
| **Academic score** | **2.5 / 5 ★** |
| **Suggested journal tier** | FRL / IJF / JPM (practitioner) after major revision. **Not** JFE/RFS/JoE at current state; JBF only after stronger identification, complete OOS, and a clean benchmark. |
| **Blocking issues** | 3 SEVERE |

The core decomposition **concept** is sound and Table 2's decomposition numbers are traceable and honestly reported. The blocking problems are **not prose** — they are (1) a code-vs-paper drift in the 50/50 benchmark implementation, (2) weak cross-OOS evidence for the S2 trading-rule framing, and (3) a code-vs-paper drift in the S3 formula. The paper's self-disclosures (apples-to-apples caveat, incomplete OOS windows, 54 vs 63 bps convention) are commendably honest but cannot fully rescue the drift issues.

**Severity tally: 3 SEVERE / 7 MODERATE / 4 MINOR.**

---

## SEVERE issues (blocking submission)

### S-01. 50/50 benchmark (S4) implementation contradicts the paper's description — CONFIRMED by code inspection
- **Location**: main.tex line 143 (Table 1 note), 36 (abstract), 186 (§4.4), 209 (Discussion); code: `experiments/k811v2_insurance_premium_vov_fixed.py:315` (and identical in `k811v2_main.py`, `k811_insurance_premium_vov.py:334`)
- **Issue**: Table 1 note states "S4 is 50/50 SPY/GLD with **monthly rebalancing**." The actual code is `s4_rets = 0.5 * spy_rets + 0.5 * gld_rets` — a **daily, continuously rebalanced constant-weight 50/50 with no transaction cost**, not monthly rebalancing. This is a genuine source-vs-paper drift. It directly underlies the headline "S2 Sharpe 0.63 vs 50/50 0.50" comparison used in the abstract, §4.4, Discussion and Conclusion. Codex spot-checked a truly monthly-rebalanced 50/50 on the bundled 2012–2024 raw-close data and obtained Sharpe ≈ 0.59, materially higher than the reported 0.50.
- **Main-thread verification**: Confirmed. `grep` of all K811 scripts shows `s4_rets = 0.5 * spy_rets + 0.5 * gld_rets` at the S4 block in every variant; no monthly-rebalance logic and no S4 cost deduction anywhere.
- **Why it matters**: A constant daily-rebalanced 50/50 captures a *different* (in fact larger) rebalancing premium than monthly, and pays zero cost. Calling it "monthly rebalanced" both mislabels the strategy and understates the benchmark's Sharpe, which weakens the paper's own "50/50 is a high bar" narrative in an uncontrolled way.
- **Fix**: Either (a) re-implement S4 as an explicit monthly-rebalanced 50/50 with the same return convention and a stated cost assumption, then re-run Table 1 + all dependent numbers (abstract, §4.4, Discussion, Conclusion); or (b) relabel S4 as "daily constant-weight 50/50 (continuous rebalancing, no cost)" everywhere and drop the "monthly" wording. Note: §4.4's separately-computed 54 bps monthly premium (2006–2024) is a *different* calculation from Table 1's S4 — the paper must not conflate the two.

### S-02. Cross-OOS evidence too thin to support the S2 trading-rule / cost-reduction contribution
- **Location**: main.tex lines 192–198, 211, 218, and abstract line 36
- **Issue**: The paper honestly discloses that of 6 non-overlapping two-year windows, only 4 are covered, and S2 outperforms BH in just **1 of 4**. The disclosure is good, but the evidence supports only a **full-sample / in-sample accounting result**, not "VVIX-conditional targeting reduces cost by 74%" as a deployable *design principle*. The omitted windows (2017–18 Volmageddon; 2022 bear) are precisely the periods most / least favourable to VoV conditioning, so the current 1/4 rate is not just incomplete but potentially biased. The "fire insurance that pays off rarely" analogy risks over-rationalising a 1/4 null.
- **Fix**: Run the two missing windows and report all 6/6. If the result remains weak, downgrade the S2 framing throughout abstract/intro/conclusion to "hypothesis-generating in-sample accounting result" and remove it from the contribution tier. Keep only the threshold-invariant decomposition claim (opportunity cost dominates) as the robust contribution.

### S-03. S3 (Smooth VoV) formula in the paper does not match the implementation — CONFIRMED by code inspection
- **Location**: main.tex line 101 (S3 definition), 164 (Table 2), 178; code: `k811v2_insurance_premium_vov_fixed.py:301,309` (identical in `k811v2_main.py:310,318`)
- **Issue**: LaTeX defines S3 as a **binary 0.5 blend**: `w_t = w_t^VT + (1 - w_t^VT)·1(z_t^VoV < 1.0)·0.5` (fixed halfway blend whenever z<1, pure VT when z≥1). The code implements a **continuous linear interpolation**: `insurance_intensity = clip(z,0,1); s3_weight = 1 - insurance_intensity·(1 - w_t^VT)`. These are mathematically different functions:
  - Code: z≤0 → full equity; z≥1 → full VT; 0<z<1 → linear in z.
  - LaTeX: any z<1 → fixed halfway blend; z≥1 → full VT (a step function, not linear).
  The reported S3 numbers in Table 2 (opp 2.85 / direct 0.46 / total 3.31) come from the continuous-clip code, so the paper's S3 equation misrepresents what produced the results. The claimed "0.3/0.7 blending coefficients yield qualitatively similar results" has no corresponding output in the package.
- **Main-thread verification**: Confirmed. Both k811v2 scripts contain the continuous `clip(z,0,1)` implementation; no fixed-0.5-blitz binary branch exists in code.
- **Fix**: Either rewrite the S3 equation to match the continuous formula actually used, or re-run with the fixed-0.5 binary blend to match the paper. Remove or substantiate the 0.3/0.7 sensitivity claim (add an appendix table if it was actually run).

---

## MODERATE issues

### M-01. Eq.(3) annualization unit / symbol `N` conflict
- **Location**: main.tex lines 86–89, 108, 169
- **Issue**: Eq.(3) writes `IP_direct = Σ c|w_t − w_{t−1}| / N`, and line 89 says "annualized over N years", but `N = 3262` is used everywhere as **trading days** (line 108, Table notes). Dividing a per-period cost sum by 3262 days is not the same as annualizing over 12.94 years. The decomposition identity still holds numerically in code (net = gross − cost), but the *written* equation is dimensionally ambiguous.
- **Fix**: Use distinct symbols: `T` = trading days (3262), `Y = T/252` = years (12.94). Write `IP_direct = (1/Y)·Σ c|w_t − w_{t−1}| = (252/T)·Σ c|Δw_t|`. Also state explicitly in Eq.(1) that `r^VT` is the **net-of-cost** return (otherwise the by-construction identity `IP_total = IP_opp + IP_direct` is not obvious).

### M-02. Table 2 component sum vs total rounding
- **Location**: main.tex lines 162–164
- **Issue**: S1 shows 4.20 + 0.43 = 4.63 but Total = 4.62. Underlying values (≈4.195 + 0.428 = 4.623) make this a rounding artifact, not an error; S2 (0.70+0.52=1.22) and S3 (2.85+0.46=3.31) sum exactly.
- **Fix**: Add a table note: "Components may not sum exactly to the total due to rounding."

### M-03. Threshold / filter justification remains cherry-pick-exposed
- **Location**: main.tex lines 100–104, 198, 211
- **Issue**: `z > 1.0` reads as a one-sigma heuristic but is not stated to be an **ex-ante** rule; the 5-day VIX-rising filter's "balances responsiveness against noise" is narrative, not evidence; the 0.5 blend is not formally validated. Reviewers will suspect in-sample tuning.
- **Fix**: Declare threshold/filter as a pre-specified heuristic (not tuned), OR do nested walk-forward selection on training windows only. In the text, confine the robustness claim to "the *decomposition* is invariant to threshold," not "the *trading rule* is robust."

### M-04. Apples-to-apples caveat undermined by S-01
- **Location**: main.tex lines 36, 186, 209, 218
- **Issue**: The "S2 vs 50/50 not apples-to-apples" disclosure is textually clear and honest, but because S4 is mislabeled (S-01), the caveat cannot fully repair the benchmark comparison.
- **Fix**: Fix S-01 first, then keep the caveat; report equity-timing vs diversified-rebalanced metrics separately.

### M-05. DM test described correctly but inference scope must be stated
- **Location**: main.tex lines 195–196; code: `src/volpred/stats/model_evaluation.py` (strategy_dm_test)
- **Issue**: The footnote now correctly describes negative-return loss, Bartlett–Newey-West HAC, max lag ⌈T^{1/3}⌉ (matches code — this was the audit_2026-06-10 fix). But this is a **HAC mean-return-difference test**, not a Sharpe / utility / cost-reduction / tail-insurance efficacy test. The Harvey (2016) |t|>3.0 hurdle is a conservative multiple-testing screen for factor discovery, not a standard strategy-comparison critical value.
- **Fix**: State explicitly: "We use the DM/HAC statistic as a conservative screen for mean-return differences, not as a formal test of Sharpe or utility dominance; the |t|>3.0 hurdle is imported from Harvey et al. (2016) as a conservative heuristic."

### M-06. 50/50 rebalancing premium 54 vs 63 bps convention disclosure widens the reproduce gate
- **Location**: main.tex line 184 (footnote); `reproduce_report.json` claim #9
- **Issue**: The footnote honestly discloses 54 bps from `auto_adjust=True` (dividend-adjusted) vs ≈63 bps from the raw-Close reproduce package (per the 2026-04-19 auto_adjust lesson in error_log). Honest, but shipping a ±10 bps tolerance to reconcile a headline number will read to a reviewer as a loosened replication gate. Also, this 54 bps uses **2006–2024** (GLD inception) while the paper's main sample is 2012–2024 — a second cross-period disclosure.
- **Fix**: Either ship the dividend-adjusted 2006–2024 series to reproduce 54 bps exactly, or make raw-Close 63 bps the headline and relegate 54 bps to robustness. Keep both period anchors explicit.

### M-07. "Gold crisis alpha" quantified claim lacks a supporting table
- **Location**: main.tex line 184
- **Issue**: "gold consistently appreciates during equity drawdowns" and "the HighVoV_Rising regime is precisely where gold delivers positive returns" are quantitative claims without a GLD-return-by-VoV-regime table in the K811v2 output.
- **Fix**: Add a GLD-return-by-VoV-regime table, or downgrade "consistently / precisely" to a conjecture.

---

## MINOR issues

### m-01. Lookahead is clean, but strategy notation should show the lag
- **Location**: main.tex lines 95, 100, 108; code: `k811v2_..._fixed.py` (uses `vov_zscore_lag`, `vix_rising_lag`, `vix_lag`)
- **Issue**: **Lookahead is verified clean** (main-thread + error_log 2026-05-06 K547 audit both confirm K811/v2 uses lagged features; z_t contains same-day VVIX but is shifted before multiplying next-day return). However the LaTeX method section writes "apply when z_t > 1.0", which can mislead a reader into thinking same-day signal is used.
- **Fix**: Write the strategy condition with explicit lag: `z_{t-1}^{VoV} > 1.0` and `VIX_{t-1} − VIX_{t-6} > 0`.

### m-02. CRRA disclosure sufficient
- **Location**: main.tex lines 135, 143
- **Issue**: Already discloses "mean CRRA utility, not certainty-equivalent" — adequate.
- **Fix (optional)**: Rename the Table row header to "Mean utility, CRRA γ=5" to prevent it being read as CE / welfare gain.

### m-03. "consistent with CRSP to within rounding precision" is unsupported in the package
- **Location**: main.tex line 108
- **Issue**: No CRSP comparison record exists in the current paper package (data are yfinance).
- **Fix**: Delete the clause, or add a CRSP spot-check log to `data_sources.md`.

### m-04. Contribution framing too ambitious for the evidence
- **Location**: main.tex lines 58–60, 205–218
- **Issue**: The author concedes the decomposition is "arithmetically straightforward"; the novelty is the empirical magnitude (91% opportunity cost), which is a measurement contribution, not a top-tier methodological one.
- **Fix**: Frame as an "empirical decomposition / measurement note" targeting FRL/IJF/JPM. For JBF+, add formal inference, complete OOS, and cross-asset external validation.

---

## Methodology deep-dive (per-item verdicts)

| Check | Verdict | Note |
|---|---|---|
| Decomposition identity `IP_total = IP_opp + IP_direct` | **mostly clean** | Holds under net/gross definitions; code net = gross − cost. Only Eq.(3) unit/`N` ambiguity (M-01) needs fixing. |
| Table 2 traceability & sums | **clean (rounding)** | 4.20+0.43 vs 4.62 is rounding (M-02). |
| Lookahead (VVIX z-score, signal lag) | **verified clean** | z_t uses same-day VVIX but is shifted before next-day return; code uses `*_lag` features; corroborated by error_log 2026-05-06 K547 audit. LaTeX notation should show the lag (m-01). |
| S4 (50/50) benchmark implementation | **NOT clean (SEVERE)** | Code is daily constant-weight, paper says monthly rebalanced (S-01). |
| S3 (Smooth VoV) formula vs code | **NOT clean (SEVERE)** | Continuous clip in code vs binary 0.5 blend in paper (S-03). |
| Threshold z>1.0 / 5-day filter / 0.5 blend justification | **NOT clean** | Post-hoc rationalisation risk; sensitivity supports decomposition invariance only, not rule optimality (M-03). |
| DM test spec vs code | **matches, scope limited** | Correct HAC mean-return screen; not a Sharpe/utility dominance test (M-05). |
| Cross-OOS completeness | **incomplete & possibly biased** | 4/6 windows, 1/4 wins; omitted windows are the decisive ones (S-02). |
| 54 vs 63 bps / 2006–2024 vs 2012–2024 disclosures | **honest but gate-loosening** | Cross-period + cross-convention (M-06). |

---

## Action plan for v3 (main-thread must-fix, priority order)

1. **S-01** — Fix or relabel the 50/50 benchmark; re-run all dependent numbers. *(blocking; touches abstract, Table 1, §4.4, Discussion, Conclusion)*
2. **S-03** — Reconcile S3 equation with code (or re-run to match paper). *(blocking; reproducibility)*
3. **S-02** — Run 2017–18 and 2021–22 windows; report 6/6; downgrade S2 framing if still weak. *(blocking; requires compute)*
4. **M-01, M-05, m-01** — Equation/notation/inference-scope clarifications (low effort, high credibility gain).
5. **M-03, M-06, M-07** — Threshold justification, reproduce-gate tightening, gold-regime table.
6. **MINOR m-02/m-03/m-04** — polish + contribution reframing.

**Prediction**: With S-01/S-02/S-03 resolved and M-01/M-05 clarified, the paper is a credible **FRL/IJF** submission (est. 3.5★). JBF+ requires the cross-asset external validation and formal inference in m-04.
