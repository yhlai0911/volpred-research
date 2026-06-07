# BTC-GAS Paper — Supporting Experiments Index

Each row below maps a K-ID to its specific paper-section contribution. All numeric claims in the paper trace back through this table to the underlying experiment results JSON.

## K-ID index

| K-ID | Path | Title | Contribution to paper |
|------|------|-------|------------------------|
| K1129 | `experiments/K1129/` | GAS-t on Commodity Markets — Does Creal-Koopman-Lucas advantage reappear? | Cross-asset GAS-t baseline. Documents the full-sample BTC reversal (DM-HLN = -4.67, QLIKE 9.92% worse than GJR-N) that motivates the entire paper. Source for Section 1 puzzle hook. |
| K1133 | `experiments/k1133/` | Regime-switching GAS-t on BTC — is K1129 reversal regime-dependent? | Sub-period decomposition. Isolates Period 1 (pre-institutional, 2017-2020) as origin of the reversal; Period 2 (FTX-Luna) and Period 3 (spot-ETF) show no GAS-t deficit (|DM-HLN| < 1.1). Source for Section 4 cross-period table. |
| K1133b | `experiments/k1133b/` | BTC GAS-t decomposition — innovation vs GAS dynamics vs regime-switching | Factorial 5-model design (M1 GJR-N, M2 GJR-t, M3 GAS-t, M4 GAS-N, M5 GJR-N-std) + MS-GAS-t rescue. Decomposes Period 1 reversal: innovation contrast +2.67 (Normal beats t within GAS), dynamics contrast -1.90 NS (GAS dynamics not significantly worse than GJR). MS-GAS-t adds +5.97 vs single-state GAS-t but still NS vs GJR-N (+0.28). Source for Sections 5 + 6 + the Key Numbers table. |

## Section → experiment mapping

| Section | Primary source | Secondary sources |
|---------|---------------|-------------------|
| §1 Introduction | K1129 (puzzle: full-sample reversal) | K1133, K1133b (preview of resolution) |
| §2 Literature Review | n/a (literature only) | — |
| §3 Data & Methodology | K1133b (factorial design + estimation protocol) | K1129 (rolling 1000-day, refit cadence) |
| §4 Cross-Period Decomposition | K1133 (period split) | K1133b (Period 1 DM-HLN heatmap) |
| §5 Factorial Diagnosis | K1133b (M1-M5 contrasts) | — |
| §6 MS-GAS-t Rescue | K1133b (MS extension + state-prob recursion) | — |
| §7 Why Pre-Institutional? | K1129 cross-asset context | K1133 period-specific kurtosis stats |
| §8 Robustness | K1133b leave-one-year-out + alternative loss + Codex lookahead audit | K1133 boundary sensitivity |
| §9 Conclusion | (synthesis only) | — |
| Appendix A skewed-t/GED | K1133b (alternative innovation specs) | — |
| Appendix B ETH/BNB OOD | K1129 cross-asset coverage | — |

## Methodological pre-registration

- **K1133 period split**: Pre-registered in `experiments/k1133/README.md` (committed 2026-04-12, before any factorial run). Three institutional regimes selected on structural criteria (no spot ETF / FTX-Luna recovery / spot-ETF approval), not Bai-Perron or other data-driven break tests.
- **K1133b factorial decomposition**: Methodology note v1.0 dated 2026-04-15 specifies the innovation × dynamics 2×2 design (+ 1 standardised-Normal control = 5 models) and the +2.67 / -1.90 contrast logic *before* running estimation. This is the canonical pre-registration referenced in Section 5.

## Provenance audit checklist (paper-update gate)

- [ ] Every Table row in body sections carries `% source:` LaTeX comment pointing to a JSON field in one of the three experiment result files.
- [ ] `reproduce.py` (to be added) loads pinned `data/btc_daily_20260410.csv`, re-runs the three experiments, and asserts `match_rate ≥ 95%` against the committed JSONs.
- [ ] No headline number appears in the paper that is not in `drafts/v0_outline_abstract.md` Key Numbers table.
- [ ] Codex independent review of `k1133b.py` confirms lookahead-safe (status: CONDITIONAL PASS as of 2026-04-17; verification follow-up scheduled before R1 submission).
