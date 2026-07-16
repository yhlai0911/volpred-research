VERDICT: PASS

**Blocking defects:** None.

**Checks performed**

- HEAD is frozen commit `071fdc73a`; all tracked `experiments/k1706/` bytes match that commit.
- Specified SHA256 values match exactly for `K1706.py`, results, and README.
- External and results-embedded manifests are identical. Panel, assignment, OHLCV, spread, and script hashes all match the manifest.
- Boundary reconstruction found:
  - 0 October rows.
  - All 4,166 `symbol × analysis_period` groups have missing first raw return, adjusted return, and adjustment-factor change.
  - All 2,064 retained stocks have missing first-post Amihud return input.
  - Rebuilt panel matches the committed 340,283-row panel.
- Recomputed primary, heterogeneity, and placebo results match stored values within floating-point noise (`≤2.85e-14`).
- Confirmed intact: alternating-projection stock/date FE at `1e-12`, stock clustering, explicit `signal.shift(1)`, seed 42, 999 RI permutations, fixed `<0.10`/`>0.15` bins, separate Holm families, placebo tests, atomic validated JSON replacement, warned rather than silent parse skips, fatal input/convergence gates, and ≥20-day panel gate.

**Frozen success rule**

`range_bps` alone qualifies:

- Narrow primary RI: `p=.002`, Holm `=.016`.
- Narrow-minus-wide heterogeneity RI: `p=.001`, Holm `=.004`.
- Both range placebos: Holm `=1.0`.
- Sample gates comfortably pass: narrow C/treated `778/757`; wide `260/269`.

Therefore the range-only `CONFIRMATORY` label is justified.

**Non-blocking limitations**

Daily OHLCV proxies are not intraday measures; RI preserves spread-stratum counts but not every official randomization stratum; survivorship/data availability remains possible; 999 permutations impose finite p-value resolution.

**Trust statement**

I trust the confirmatory claim only for range heterogeneity under this frozen design. RV, log-dollar-volume, and Amihud are non-rejection/null diagnostics only; they provide no evidence of equivalence or absence of economically meaningful effects.
