# P10 Crypto-Fear-Channel Outline ↔ Experiments Audit Report

**Task**: `task_7d2c24fa1ae2` ([P25] outline → experiments 一致性 audit)
**Audit date**: 2026-04-26
**Sources audited**:
- `paper/crypto-fear-channel/outline.md`
- `paper/crypto-fear-channel/body_v0_intro.tex`
**Experiments verified**:
- `experiments/k1025/k1025_results.json` (primary citation source — all intro `% source:` comments point here)
- `experiments/k639/k639_results.json` (outline-level supporting reference)
- `experiments/k746b/k746b_bitcoin_vix_fixed_results.json` (outline-level supporting reference)
**Tolerance**: ≤1e-3 absolute or rounding-consistent → verified; otherwise → divergent.

---

## Audit Table

| # | claim_text | source_section | experiment_id | claimed_value | actual_value | status | notes |
|---|---|---|---|---|---|---|---|
| 1 | Sample period 2015-02 to 2026-04 | abstract + outline §Key empirical material | K1025 | 2015-02 ~ 2026-04 | `2015-02-02 to 2026-04-08` | verified | exact endpoints |
| 2 | N = 2,812 daily obs | abstract + outline §Key empirical material | K1025 | 2,812 | `n_observations = 2812` | verified | |
| 3 | OOS window = 1,826 days (2019-2026) | intro §Forecastability gap | K1025 | 1,826 days, 2019--2026 | `oos_n = 1826`, `oos_start = 2019-01-01` | verified | |
| 4 | Asym Granger BTC neg → VIX sig at lags 1-5 | intro §Asymmetry | K1025 | sig at lags 1-5 | F = {18.96, 14.79, 10.18, 7.34, 6.64}; p ∈ [3.7e-6, 1.4e-5] | verified | All five lags p < 1e-5 |
| 5 | Asym Granger BTC pos → VIX NS at lags 1-5 | intro §Asymmetry | K1025 | NS at lags 1-5 | F = {2.00, 0.20, 0.20, 0.17, 0.28}; min p = 0.157 | verified | best p = 0.157 — clearly NS |
| 6 | Symmetric Granger BTC RV → VIX sig at lags 2-10 | intro §Asymmetry | K1025 | sig at lags 2-10 | lag 1: p = 0.422 (NS); lags 2-10: all p < 0.05 | verified | Intro correctly states 2-10, not 1-10 |
| 7 | QR β at τ=0.05 = -2.86 | intro §Tail concentration | K1025 | -2.86 | -2.8627503 | verified | rounds to -2.86 |
| 8 | QR β at τ=0.25 = -2.34 | intro §Tail concentration | K1025 | -2.34 | -2.3426337 | verified | rounds to -2.34 |
| 9 | QR β at τ=0.50 = +2.61 | intro §Tail concentration + outline §Target table | K1025 | +2.61 | 2.6129602 | verified | rounds to +2.61 |
| 10 | QR β at τ=0.95 = +22.31 | intro §Tail concentration + outline §Central claim | K1025 | +22.31 | 22.307901 | verified | rounds to +22.31 |
| 11 | 8.5× upper-tail amplification (τ=0.95/τ=0.5 ≈ 8.54) | abstract + intro + outline §Central claim | K1025 | 8.54 | 22.307901 / 2.612960 = **8.537** | verified | exact match within rounding |
| 12 | Granger F = 11.05 in 2020, p < 10⁻⁶ | intro §Regime dependence | K1025 | F=11.05, p<10⁻⁶ | F = 11.0509, p = 7.94e-7 | verified | p = 7.94e-7 indeed < 1e-6 |
| 13 | Abstract: 2020 F = 11.05, p < 0.001 | abstract | K1025 | p < 0.001 | p = 7.94e-7 | verified | weaker (more conservative) statement than intro; both true. **Style note**: consider unifying abstract↔intro to "p < 10⁻⁶". |
| 14 | Granger NS in 2015-2017, 2018-2019, 2021-2022, 2023-2026 | intro §Regime dependence + outline §Central claim | K1025 | all NS | F = {0.59, 0.23, 1.95, 0.46}; p = {0.443, 0.630, 0.163, 0.709} | verified | All four sub-periods clearly NS |
| 15 | BTC is net receiver in DY framework | abstract + intro §Regime dependence + outline §Central claim | K1025 | net receiver | `mean_net_btc = -76.89` (negative → receiver) | verified | -76.89% net receiver position |
| 16 | DM t = -0.98 (Harvey corrected) | intro §Forecastability gap + outline §Honest negative | K1025 | -0.98 | `dm_stat_harvey = -0.9800` | verified | rounds to -0.98 |
| 17 | DM p = 0.33 | intro §Forecastability gap + outline §Honest negative | K1025 | 0.33 | `dm_pval = 0.3270` | verified | rounds to 0.33 |
| 18 | DM \|t\| < 3 (below Harvey threshold) | intro §Forecastability gap + outline §Honest negative | K1025 | below threshold | \|-0.98\| = 0.98 < 3.0; `harvey_pass = False` | verified | |
| 19 | OOS spans 2019--2026 | intro §Forecastability gap | K1025 | 2019--2026 | `oos_start = 2019-01-01`, dataset ends 2026-04-08 | verified | |
| 20 | Outline §Key material: K639 confirmed BTC → SPY RV Granger lag 1-10 | outline §Key empirical material | K639 | sig at lags 1-10 | lag 1: p = 0.560 (**NS**); lags 2-10: all p ≤ 0.024 | divergent (minor) | Lag 1 is NOT significant in K639 (`p = 0.560`). The outline phrasing "lag 1-10" overstates. **Recommendation**: in Methodology / Lit-review draft, state "lags 2-10" for K639, matching the K1025 phrasing already in intro. Not present in body_v0_intro.tex, so no body edit needed yet. |
| 21 | Outline §Key material: K746b BTC vol asymmetrically Granger-causes VIX (neg branch dominates) | outline §Key empirical material | K746b | confirms asymmetric direction | K746b's `part_b_granger_fixed` shows VIX→BTC|absret|, not the asymmetric BTC±→VIX pair K1025 reports. Asymmetric BTC→VIX evidence lives in K1025, not K746b. | divergent (minor) | The outline credits K746b for an asymmetric BTC→VIX result that is actually contained in K1025. K746b confirms a different but related lemma (VIX→BTC absret has weak/lagged causality). **Recommendation**: rephrase outline §Key material to credit K1025 as the asymmetric Granger source; reposition K746b as preliminary supporting evidence on the BTC-VIX dyad. Not in body_v0_intro.tex, so no body edit needed yet. |

---

## Summary Counts

- **verified**: 19
- **divergent (minor)**: 2 (K639 lag-1 overstatement; K746b mis-attribution — both **outline only**, not in body_v0_intro.tex)
- **untraceable**: 0

## Critical Divergences

**None at intro-body level.** All 19 numeric claims in `body_v0_intro.tex` (which is the version that may be reviewed / submitted) trace exactly to `experiments/k1025/k1025_results.json` within ≤1e-3 rounding.

The 2 minor divergences both live in the kick-off **outline** (§Key empirical material) — no journal-visible artifact yet. They are recommendations for tightening the outline's K639/K746b crediting before the lit-review/methodology section is drafted.

## Stylistic / Internal-Consistency Note (non-blocking)

- Abstract reports 2020 Granger as `p < 0.001`; intro reports `p < 10⁻⁶`. Both technically true (actual p = 7.94e-7), but inconsistent. Consider unifying to `p < 10⁻⁶` for sharper statement, or keep abstract conservative deliberately. **Not a divergence** — both are upper bounds the actual p-value satisfies.

## Recommended Supervisor Actions

1. **No urgent action required for body_v0_intro.tex** — all 19 intro number claims pass audit cleanly.
2. Before drafting Section 2 (Lit review) / Section 4 (Methodology), update `outline.md` §Key empirical material:
   - K639 line: change "lag 1-10" → "lag 2-10" to match K639's actual lag-1 NS result.
   - K746b line: rephrase to credit K1025 for the asymmetric BTC→VIX Granger evidence; describe K746b as a preliminary BTC-VIX dyad analysis (its asymmetric result that K1025 later refined).
3. Consider unifying abstract↔intro p-value reporting for the 2020 Granger (`< 0.001` vs `< 10⁻⁶`); harmless either way.
4. Continuing intro-driven body drafting can proceed without K1025 re-run; numeric foundation is solid.

## Pre-existing reproducibility_audit/ inventory (no overlap)

- `nonK_sweep_report.md` (2026-04-18, 2.9 KB) — different scope (non-K reference sweep), not duplicating this audit.

## signal_payload

```json
{
  "verified_count": 19,
  "divergent_count": 2,
  "untraceable_count": 0,
  "critical_divergences": [],
  "minor_divergences": [
    {
      "location": "outline.md §Key empirical material",
      "claim": "K639 confirmed BTC → SPY RV Granger at lag 1-10",
      "issue": "Lag 1 is NS in K639 (p=0.560); only lags 2-10 are significant.",
      "recommendation": "Edit outline.md to read 'lag 2-10'."
    },
    {
      "location": "outline.md §Key empirical material",
      "claim": "K746b — BTC volatility asymmetrically Granger-causes VIX (negative-BTC branch dominates)",
      "issue": "Asymmetric BTC→VIX result lives in K1025, not K746b. K746b's relevant Granger is VIX→|BTC absret|.",
      "recommendation": "Rephrase outline.md to credit K1025; reposition K746b as preliminary BTC-VIX dyad evidence."
    }
  ],
  "recommend_supervisor_actions": [
    "No action required for body_v0_intro.tex (all 19 numeric claims verified).",
    "Tighten outline.md §Key empirical material K639/K746b crediting before lit review/methodology drafting.",
    "Optionally unify abstract↔intro p-value statement for 2020 Granger (< 0.001 vs < 10⁻⁶); both correct."
  ],
  "intro_numeric_audit_passed": true,
  "outline_minor_overstatements": 2
}
```
