# Codex review — K1339 (commodity backwardation→contango regime switch event study)

**Reviewer**: Codex CLI 0.139.0 (ChatGPT auth, gpt-5.4)
**Review date**: 2026-06-15
**Verdict**: **CONDITIONAL_PASS** (downgraded from agent self-report PASS)

## 5 issues flagged

1. **Multiple testing not in verdict**: CPER H30 `p=0.003` survives Bonferroni at 18 vol cells (`0.10/18=0.0056`) but is borderline at 36 tests (vol + δρ ⇒ `0.0028`). Hard claim should be tempered.
2. **Event non-independence**: 95 events with 60/90-day overlapping forward windows → iid bootstrap CI/p are biased narrow. A block bootstrap or per-event independence filter would be more honest.
3. **Regime proxy validity**: 21d-vs-63d ETF momentum is *not* a true futures-curve roll-yield measurement. Cannot strongly label flips as "backwardation/contango" — better called "momentum-regime switch in inflation-sensitive ETFs."
4. **Seed not fully reproducible**: per-cell bootstrap uses `SEED + abs(hash((direction,H,asset)))%10000`. Python's `hash()` is salted by `PYTHONHASHSEED` env, so reruns under different hash seeds shift p-values (independence sign-flip null confirms CPER H30 `p=0.0026` robust across `PYTHONHASHSEED ∈ {0,1,2}`, but in principle it is non-deterministic).
5. **Bootstrap p-value form**: code computes centered bootstrap (`|μ_boot - μ_obs| ≥ |μ_obs|`), not the sign-flip null that the README comment implies. Independence sign-flip null cross-check by Codex: H30 CPER `p=0.0026`, H30 UNG `p=0.079`, H60 CPER `p=0.087` — broadly consistent with reported numbers but caveat remains about event dependence.

## Lookahead — broadly passes

- `regime_state` uses `prices.shift(1)` ✓
- Sustained-10d filter returns event_date = day-10 (uses only realised data through that date) ✓
- Forward window placement `[event_date+1, event_date+H]` ✓
- Cross-confirm anchor takes the latest partner flip, not future flips ✓

## Recommended action

- Write knowledge.json entry with **CONDITIONAL_PASS** verdict (not PASS).
- Narrative for any downstream feed article must use "momentum-regime switch in commodity ETFs" framing, not "true backwardation/contango regime switch."
- For a publishable paper claim, would need (a) block bootstrap, (b) FDR correction over the full 36-cell grid, (c) explicit independence-filtered subset.
- CPER (copper) contango→backwardation H30 vol jump +18% (p≈0.003) is the strongest signal and survives the sign-flip null cross-check; this is the only single result worth highlighting.

## Verdict (final)

CONDITIONAL_PASS — write knowledge entry, but caveat heavily; do not paper-publish without methodological hardening.
