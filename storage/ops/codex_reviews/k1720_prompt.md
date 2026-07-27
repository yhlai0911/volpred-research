# Codex read-only review — K1720

You are performing a **read-only** review of a completed research experiment before its
knowledge-base entry is written and its worktree is merged (K1259 gate: Codex review
must pass before `knowledge.json` write). Do **not** modify any file — output a written
verdict only.

## Experiment

**K1720 — Leveraged-ETF mechanical rebalancing and end-of-day volatility amplification.**
Hypothesis (JPM 2025): LETF close rebalance notional ∝ (k²−k)·r·AUM trades same-direction
into the close for all leveraged/inverse multiples, so on big up/down days synchronized
late-day flow (1) amplifies last-hour realized vol of the underlying and (2) pushes price
further the same direction (continuation), increasing in LETF AUM. Tested on QQQ (TQQQ+3 /
SQQQ−3) and SPX (SSO+2) complexes, 1h bars. Declared verdict: **NULL** on the sharp
mechanism (robust *descriptive* last-hour amplification not separable from whole-day
clustering; no directional continuation).

## Files (absolute paths — read only)

- Code:    `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-87c7269d-k1720/experiments/K1720/K1720.py`
- Results: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-87c7269d-k1720/experiments/K1720/K1720_results.json`
- README:  `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-87c7269d-k1720/experiments/K1720/README.md`
- Data:    `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-87c7269d-k1720/experiments/K1720/data/`

## Review checklist (AGENTS.md research-honesty constraints)

1. **Lookahead bias (highest risk)**: predictor observed strictly before outcome window?
   `day_close.shift(1)` for prev-close; event flag = expanding quantile of |r_intra|
   **shifted by 1 day** (min_periods=60); AUM used only as a cross-sectional constant.
   Confirm no same-day signal × same-day outcome leakage. Check the outcome window
   (15:30–16:00) is disjoint from the predictor (r_intra observed at 15:30).
2. **Control specification**: is the "last-hour excess after controlling rest-of-day vol"
   regression/partialling correct, and does it actually justify the NULL (i.e. the
   last-hour-specific coefficient is not significant once rest-of-day vol enters)?
3. **Statistical rigor**: standard errors / test used appropriate (HAC/robust where序列
   相關)? Any p-hacking, multiple-testing without adjustment, or over-reading of a
   descriptive result as causal?
4. **Numeric consistency**: spot-check `economic_magnitude` (e.g. (k²−k) coefficients:
   TQQQ=6, SQQQ=12, SSO=2; rebalance-notional-as-%-of-lasthour-dollar-vol) recomputes
   from the stated inputs. Seed fixed (=42) for any random procedure.
5. **Claim strength**: does the NULL verdict / README overclaim or underclaim relative to
   the evidence? Is the honest-null framing accurate?

## Output

End with a single line: `VERDICT: PASS` or `VERDICT: FAIL`.
If FAIL, list the specific defects (file:line where possible) that must be fixed before
merge. If PASS, note any minor caveats worth recording in the knowledge entry.
