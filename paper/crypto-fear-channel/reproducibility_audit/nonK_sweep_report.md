# Paper 10 (crypto-fear-channel) — Non-K Forensic Sweep Report

**Date**: 2026-04-17
**Agent**: Non-K Forensic Sweep (worktree agent-a30d366f)
**Task**: Map non-K experiment folders to Paper 10 no-source items

---

## Paper 10 Audit Status

Paper 10 (crypto-fear-channel) is in very early stage — only `body_v0_intro.tex` and `outline.md` exist. No `reproducibility_audit/diff_report.md` exists (just created this directory). No formal no-source list exists.

Paper 10 appears to be about cryptocurrency fear/sentiment channels and volatility, possibly BTC-related.

---

## Non-K Folders Potentially Relevant to Paper 10

| Folder | Content | Relevance |
|--------|---------|-----------|
| `btc_liquidation_abm` | Planning stub. Created 2026-04-16. | AMBIGUOUS — BTC-related, could support Paper 10 |
| `btc_var_methods` | Draft stub. | AMBIGUOUS — BTC VaR methods |
| `btc_derivatives_vol` | Has results JSON? Check below | Potentially relevant |

---

## Non-K BTC-Related Folders

| Folder | Has Real Data? | Content |
|--------|---------------|---------|
| `btc_liquidation_abm` | NO — planning stub | Status=planning |
| `btc_var_methods` | NO — draft stub | Status=draft, metrics={} |
| `btc_derivatives_vol` | NO — draft stub | Status=draft, data_sources=[] |

All three BTC-related non-K folders are empty stubs. No actual BTC analysis results exist in non-K folders.

---

## K-Uppercase Folders with BTC Relevance

Several K-uppercase folders may be relevant to Paper 10:
- `K1040` (experiments/K1040/): README indicates OOS direction prediction — possibly BTC?
- `K1041` (experiments/K1041/): README shows portfolio VaR and rolling correlation charts — possible BTC cross-asset?
- `K1042` (experiments/K1042/): net_flow vs SPY quintile returns — possibly BTC/crypto flow?

These are K-numbered experiments handled by parallel agents (K1179, K1194, K1186) per the task brief and are outside this agent's scope.

---

## Summary

| Category | Count |
|----------|-------|
| Non-K BTC/crypto folders inspected | 3 |
| Folders with real data | 0 |
| All stubs | 3 |
| Paper 10 no-source items identified | **Cannot assess** (no diff_report.md exists; paper is outline-stage only) |

**Verdict**: Paper 10 is too early-stage for a meaningful non-K sweep. The paper has only `body_v0_intro.tex` and `outline.md`. All BTC-related non-K folders are empty stubs. A reproducibility audit cannot proceed until the paper has a complete draft with specific numerical claims.

---

## Action Recommendations

1. **No action needed now** — Paper 10 is in outline/intro stage only.
2. Once Paper 10 has a complete body draft, run the standard `diff_report.md` audit.
3. Execute `btc_liquidation_abm` and `btc_derivatives_vol` if they're intended to provide Paper 10's core empirical results.
4. Consider whether Paper 10 needs TAIFEX crypto data or CBOE BTC options data (see external-data-sources skill).
