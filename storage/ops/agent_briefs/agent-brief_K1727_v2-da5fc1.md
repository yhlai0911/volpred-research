# K1727 — Volatility targeting: risk-asset-only efficacy, cross-asset re-validation

**Model**: opus / xhigh (per model_router)

## Task
Re-validate the claim that **volatility targeting (VT) improves risk-adjusted returns for risky assets (equities/credit) but is near-useless for bonds/FX/commodities**. Source hypotheses: JPM "The Impact of Volatility Targeting" + Man Group 2025.

Auto-generated from `research_program.md` (line 587). This is a fresh dispatch — the prior worktree produced no output.

## Data
- Use **yfinance** only. Asset set (one representative liquid ETF per bucket):
  - Equities: `SPY` (and optionally `QQQ`)
  - Credit: `HYG` (high yield), `LQD` (IG)
  - Rates/bonds: `TLT` (long UST)
  - FX: `UUP` (USD index proxy)
  - Commodities: `DBC` (broad) and/or `GLD`
- Daily adjusted closes; longest common history available per asset (document start dates).

## Method (per `.claude/rules/experiments.md`)
For **each asset independently**:
1. Estimate realized vol from trailing daily returns (e.g. 20d rolling std, annualized). **Lookahead policy: the vol/scaling signal MUST be `signal.shift(1)`** — position at day t uses info available through t-1 only.
2. Build two portfolios: (a) **fixed-notional** (constant unit exposure), (b) **vol-targeted** (scale exposure to a constant target vol, e.g. 10% annualized; cap leverage at a documented bound e.g. 2x).
3. Compare: **Sharpe gain (VT - fixed)**, plus **left-tail extreme frequency** (e.g. frequency/severity of daily returns beyond -3 sigma or worst-1% days, and max drawdown).
4. Report per-asset and grouped (risky = SPY/HYG/LQD vs non-risky = TLT/UUP/DBC/GLD). The hypothesis predicts Sharpe gain concentrated in risky assets and negligible/negative for bonds/FX/commodities.

## Deliverables (byte-traceable, in this worktree)
- `experiments/K1727/README.md` — motivation + method + **lookahead policy** + success criteria
- `experiments/K1727/K1727.py` — reproducible, `signal.shift(1)`, `seed=42`, saves the results JSON
- `experiments/K1727/K1727_results.json` — per-asset Sharpe(fixed), Sharpe(VT), Sharpe gain, left-tail metrics, sample start/end dates, n_obs

## Success criteria
- CONDITIONAL_PASS minimum: results reproduce, lookahead correct (shift(1)), and the risky-vs-non-risky Sharpe-gain contrast is quantified (with direction stated honestly even if it contradicts the hypothesis).
- Honest reporting: if VT gain is NOT concentrated in risky assets, say so — a NULL/contradicting result is a valid outcome, do not fabricate numbers.

## Review
- Codex review primary path; fallback to subagent audit if Codex quota blocked.
- Knowledge entry (knowledge.json) ONLY after CONDITIONAL_PASS minimum — and NOT written by the agent (main-thread writes knowledge; agent leaves results + README for collection).

## Mission sanity check
This is basic-research validation of a well-known finance result on free data — no monetization/PII/scraping concerns. Pure yfinance + pandas.
