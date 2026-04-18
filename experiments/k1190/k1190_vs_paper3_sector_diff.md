# K1190 vs Paper 3 Sector Analysis: Comparison

## Paper Claim (main.tex Section 3.4, lines 350-354)

"We test whether the cross-asset gamma–TSMOM link extends to within-equity variation using 11 SPDR sector ETFs (December 1998–March 2026). The Pearson correlation between gamma and VT's Sharpe improvement is r = 0.163 (p = 0.632)—economically small and statistically insignificant. The structural explanation is that gamma variation within equity sectors is compressed ([0.077, 0.160]) relative to the cross-asset range ([-0.037, 0.261])."

## Comparison Table

| Metric              | Paper 3 Claim | K1190 Computed | Diff    | Match? |
|---------------------|---------------|----------------|---------|--------|
| Pearson r           | 0.163         | 0.089          | 0.074   | (c)    |
| p-value             | 0.632         | 0.796          | 0.164   | ~      |
| gamma min           | 0.077         | 0.072          | 0.005   | YES    |
| gamma max           | 0.160         | 0.165          | 0.005   | YES    |
| N sectors           | 11            | 11             | 0       | YES    |
| r direction         | positive      | positive       | —       | YES    |
| r significance      | NS            | NS             | —       | YES    |

## Sector-Level Gamma Estimates

| Ticker | K1190 Gamma | Paper Range | In Range? |
|--------|-------------|-------------|-----------|
| XLB    | 0.097       | [0.077, 0.160] | YES   |
| XLE    | 0.077       | [0.077, 0.160] | YES   |
| XLF    | 0.152       | [0.077, 0.160] | YES   |
| XLI    | 0.137       | [0.077, 0.160] | YES   |
| XLK    | 0.129       | [0.077, 0.160] | YES   |
| XLP    | 0.115       | [0.077, 0.160] | YES   |
| XLU    | 0.072       | [0.077, 0.160] | NEAR  |
| XLV    | 0.142       | [0.077, 0.160] | YES   |
| XLY    | 0.117       | [0.077, 0.160] | YES   |
| XLRE   | 0.083       | [0.077, 0.160] | YES   |
| XLC    | 0.165       | [0.077, 0.160] | NEAR  |

Note: XLU and XLC are at the boundaries. XLC (launched 2018, shorter history) shows slightly higher gamma due to post-2018 tech-heavy composition.

## Key Divergences and Explanations

### 1. r = 0.089 vs 0.163 (diff 0.074)
- **Direction**: same (positive)
- **Significance**: both NS (p > 0.6)
- **Economic meaning**: identical — gamma does not predict sector VT benefit
- **Likely cause**: XLRE and XLC have shorter histories (2015 and 2018 respectively); if the paper applies a different treatment for these shorter-history ETFs (e.g., using proxy data or VNQ for XLRE pre-2015), the cross-sectional pattern could differ slightly

### 2. gamma range [0.072, 0.165] vs [0.077, 0.160]
- Nearly identical — difference is ≤ 0.005 at both ends
- XLU is the minimum (0.072), XLC is the maximum (0.165)
- These are within-sample-variability range

## Conclusion

**Status: (c) gamma_range_matched_r_diverges**

The core finding is reproduced: gamma variation within equity sectors is compressed relative to the cross-asset range, and the gamma–VT benefit correlation is economically near-zero and statistically insignificant. The paper's boundary condition claim stands.

The quantitative r divergence (0.089 vs 0.163) is modest and does not affect the scientific interpretation. Both values are far below statistical significance (p >> 0.05), and the paper correctly reports this as a null result.
