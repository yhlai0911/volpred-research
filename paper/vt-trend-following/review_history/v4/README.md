# Review Round v4 — vt-trend-following

**Date**: 2026-06-05
**Triggered by**: Third-party Gemini review to complement v2 latex-academic-reviewer (5H) + v3 latex-academic-reviewer (3H) + citation-verifier rounds. Per `feedback_3model_review_discipline`: production article 24h 內必走 Claude→Gemini→Codex 三模 review；paper 投稿同此 bar。
**Reviewer**:
- gemini-3.1-pro-preview (via `scripts/gemini_ask.py`, prompt 77K chars including full body_v3.tex)

---

## Overall Assessment

| Reviewer | Verdict | Severity Mix |
|----------|---------|--------------|
| Gemini   | **Major Revision** | 2 HIGH, 2 MEDIUM, 3 missing citations |

Gemini independently surfaced **two HIGH-severity econometric blind spots that latex-academic-reviewer (v2 + v3) and citation-verifier did not catch**:

### H1 (NEW, Gemini) — MDD retention >100% may be mechanical, not protective
- **Issue**: All 5 K1192 retention point estimates (95.6%, 102.2%, 103.7%, 106.2%, 109.0%) cluster at or above 100%. Economic logic would say *removing* TSMOM should *worsen* drawdown if TSMOM provides downside protection. Why does it *enhance*?
- **Mechanism Gemini diagnoses**: `r_PureVT = r_VT − β̂·TSMOM`. At market troughs (March 2009, March 2020), markets often rebound sharply causing "momentum crashes" (massive negative TSMOM returns). Subtracting a large negative reinjects a large positive into PureVT *exactly at the bottom*, mechanically lifting MDD retention above 100%.
- **Required fix**: Decompose daily PureVT returns around MDD troughs (e.g., 2009-03, 2020-03). Show whether MDD improvement comes from real VIX timing or from the short-TSMOM hedge profiting during V-shaped rebounds.
- **Why latex-reviewer missed**: Both prior rounds focused on internal consistency (table cells vs section text) and citation accuracy. The economic-mechanism critique requires linking the decomposition formula to a known empirical regularity (momentum crashes per Daniel & Moskowitz 2016) — outside the scope of pure-LaTeX or pure-citation review.

### H2 (NEW, Gemini) — Block bootstrap 252-day block destroys MDD's long-memory structure
- **Issue**: Block size = 252 days, sample length 21 years (~5,300 obs). Each synthetic path = only ~21 independent blocks. Major drawdowns (2008, 2022) have peak-to-recovery paths well over 252 days. Scrambling 1-year blocks severs the autocorrelation of multi-year secular bear markets.
- **Mechanism**: Synthetic Buy-and-Hold MDDs are mechanically *shallower* than empirical ones because long-memory drawdown paths are broken. MDD_BH (denominator of retention) shrinks → retention ratio inflated → 90% CI lower bounds pushed upward.
- **Required fix**: Use stationary bootstrap with expected block size 3–5 years (preserves full peak-to-trough-to-recovery cycles), OR report absolute MDD *differences* rather than the highly sensitive retention *ratio*.
- **Why latex-reviewer missed**: Bootstrap block-size choice in MDD context is a subtle technical issue requiring familiarity with extreme-value statistics + long-memory series.

### M1 (NEW, Gemini) — Split-sample r=0.793 may be regime-shift artifact, not endogeneity fix
- **Issue**: Paper claims split-sample (γ from 2007-2016, TSMOM loading from 2017-2026) *strengthens* the cross-sectional link (0.564 → 0.793), interpreting this as endogeneity-clean robustness. But the paper itself notes the increase is driven by "regime shift" — safe havens (bonds, gold) flipping from near-zero to positive TSMOM loading in 2017-2026.
- **If γ is structural (asset-intrinsic) but TSMOM loading flips purely due to macro regimes (equity-bond correlation breakdown after 2022 inflation shock), the causal narrative breaks down**. The correlation is being driven by macro regime change, not the leverage-effect mechanism.
- **Required fix**: With N=22, cross-sectional regressions are fragile. Add a "Risk Asset vs. Safe Haven" dummy control. If the γ coefficient loses significance after this control, the leverage effect is a proxy for asset class, not an independent driver.

### M2 (NEW, Gemini) — "Insurance premium" vs VRP confound
- **Issue**: Paper interprets 4%/year Sharpe drag as "insurance premium" for MDD protection. But VIX contains the Variance Risk Premium (VRP). 12/VIX strategy underweights equities precisely when VRP is highest (during panics), so the Sharpe drag may simply be the mathematical consequence of *failing to harvest VRP*, not paying an insurance premium.
- **Required fix**: Clarify the distinction — is the Sharpe drag (a) insurance cost for drawdown protection, or (b) opportunity cost of not harvesting VRP? Different welfare implications. Critical for JPM practitioner readers.

### Missing Citations

- **Bollerslev, Tauchen & Zhou (2009)** — VRP literature. Essential to address M2 confound.
- **Campbell & Cochrane (1999)** "By Force of Habit" — necessary to justify why investors might rationally pay 4% Sharpe drag to avoid drawdowns (habit formation / drawdown aversion utility foundation).
- **Bondarenko & Bernardo (2019)** — pricing of out-of-the-money protection / volatility-as-asset-class.

---

## Differentiation from Prior Rounds

| Round | Reviewer Type | Severity Focus | H Found |
|-------|--------------|----------------|---------|
| v2 (review_v2.tex) | latex-academic-reviewer | sample period, BAB proxy, MDD scope, datapoint reproducibility | 5 HIGH |
| v3 (2026-05-23) | citation-verifier + latex-reviewer | partial-update inconsistencies (table vs text) | 3 HIGH |
| **v4 (2026-06-05)** | **gemini-3.1-pro-preview** | **economic mechanism + bootstrap methodology** | **2 HIGH (NEW class)** |

Gemini reviewed at the *interpretive* layer (does the mechanism narrative hold? are the inference methods appropriate for the question?), which is structurally orthogonal to the latex-reviewer's *internal-consistency* layer and citation-verifier's *bibliographic* layer. Three-model review discipline confirmed value.

---

## Next Steps

1. **Address H1 (MDD mechanical artifact)**: Add subsection 3.3.x with daily PureVT decomposition around MDD troughs (2009-03, 2020-03, 2022-09). If MDD improvement primarily comes from rebound profit → reframe paper's interpretation; if it persists after removing rebound day → mechanism stands.
2. **Address H2 (bootstrap block size)**: Re-run K1192 with stationary bootstrap (mean block 3–5 years) OR add absolute MDD-difference table alongside retention-ratio table. Compare CIs.
3. **Address M1 (regime shift)**: Add safe-haven dummy control in cross-sectional regression. Report whether γ retains significance.
4. **Address M2 (VRP confound)**: Add 1–2 paragraph clarification in §4 distinguishing insurance premium vs VRP opportunity cost.
5. **Add 3 missing citations** to bibliography + brief reference in §1 / §4.

Estimated workload: 1 new compute job (stationary bootstrap K1192 re-run) + 1 follow-up experiment for MDD trough decomposition + 4 paragraph-level paper revisions. Recommend creating `Paper3_v4_revision_pipeline` follow-up task pool entry.

---

## Provenance

- Prompt: `/tmp/gemini_p3_prompt.md` (77,300 chars, includes full body_v3.tex)
- Raw output: `/tmp/gemini_p3_review_raw.md`
- Model: `gemini-3.1-pro-preview` (via `scripts/gemini_ask.py`)
- Caller: hourly-dispatch 04 (task `gen_exp_Gemini_審查`, claim session `76da7d30ea4d`)
