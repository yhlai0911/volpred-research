# v3 → v4 diff — International contribution retraction rewrite (K1695 exposure artifact)

**Date**: 2026-07-16
**Trigger**: K1695 certified rerun (review PASS 2026-07-15, `experiments/k1695/review_verdict.json`) established that the "13-market international drawdown protection" claim is an exposure artifact: the 12/VIX overlay realizes only 0.52–0.66× buy-and-hold volatility (13/13 markets exceed the 20% mismatch threshold), a constant-weight no-timing benchmark reproduces most of the raw MDD improvement, and the exposure-matched gap does not reject a circular-shift no-timing null in either sample (common −0.87 pp, p=0.559; inception-aware +4.96 pp, p=0.212; 0/13 Holm survivors in both).

**Narrative decision (B)**: rather than deleting the third contribution, it is reframed honestly — the raw MDD reduction is genuine *risk reduction through conditional de-levering* (the signal is real: realized weight path attains the lowest volatility among all 231 calendar phases of itself; raw statistic rejects its phase null at p=0.039 on the long sample), but it is **not** volatility timing and **not** same-risk drawdown protection. Raw MDD is never reported alone (repo methodology hard rule, `experiments.md` §MDD scale artifact).

## Changed locations (all in body_v4.tex)

1. **Abstract**: international sentence rewritten — raw numbers retained, exposure-matched decomposition and no-timing null results added; "broad de-risking protection" framing removed.
2. **Intro contributions list (contribution 3)**: full rewrite. Now presents the decomposition itself as the contribution (raw headline → de-levering attribution → portable exposure-matched protocol). Insurance-pricing and global-financial-cycle framing removed from the contribution statement.
3. **Intro literature paragraph**: "extend volatility-as-insurance to a global setting" → "revisit … finding the international payout is primarily de-levering".
4. **§ International Evidence** (retitled "Raw Drawdown Reduction Is De-Levering, Not Timing", new `\label{sec:international}`): three paragraphs rewritten — raw results; two decomposition diagnostics (constant-weight no-timing benchmark; λ-scaled exposure-matched comparison + circular-shift null); what survives (risk reduction, phase-rank evidence, r=−0.817 reinterpreted as tracking exposure reduction).
5. **Table 5** (`tab:international`): retitled "Raw MDD Reduction and Exposure-Matched Decomposition"; two new columns (Vol. ratio, Matched ΔMDD) from `experiments/k1695/table5_rows.csv`; inference block expanded to four rows (raw CI, exposure-matched CI, circular-shift null p-values + Holm, no-timing benchmark); notes rewritten (λ definition, null definition, DM/EM matched averages).
6. **Figure 2 paragraph + caption**: "insurance quadrant" framing removed; both axes flagged as raw quantities primarily reflecting de-levering; EWZ noted as the only strongly negative matched gap (−14.7 pp).
7. **Forensic note (discussion)**: "core international finding preserved" → raw 13/13 count reproduced but v4 decomposition attributes it to de-levering; v2 protection interpretation withdrawn.
8. **Discussion** (retitled "Insurance Pricing Reconsidered: What the Premium Actually Buys"): the premium buys a mechanically smaller risk budget co-moving with VIX; r=−0.817 prices exposure reduction; SPY breakeven arithmetic retained as a US-only cost description.
9. **Limitations (sixth)**: restated in exposure-matched terms; inception-aware +5.0 pp neither confirmed nor ruled out ("one crisis is not a test").
10. **Conclusion (second practical implication)**: de-levering framing; leverage-flexible investors should not read raw drawdown reduction as timing skill.

## Unchanged

- All US / 22-asset TSMOM-retention results (K1192/K1417/K1376/K55 bindings) — not affected by K1695.
- "Why VIX Level Provides Insurance Beyond Trend" subsection (US-only analysis).
- Table 5 raw per-market columns (reproduced exactly by the certified rerun).

## Gate

- `reproduce.py` extended with `verify_table5_international` (33 new byte-match checks bound to `experiments/k1695/k1695_results.json` + decision fields, incl. `claim_status == "retracted"` and `raw_delta_mdd_reportable_alone == False`).
- Reproduce gate after rewrite: match_rate 100%, alert green, gate pass.
- xelatex ×2: 42 pages, 0 errors, 0 undefined citations.
