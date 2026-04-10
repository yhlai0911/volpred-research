# K1014: HAR-PD (Path-Dependent) Volatility Forecasting

**[Proposed: Claude, Executed: Claude]**

## Research Question

Do path-dependent features (trend, convexity, momentum, jump, asymmetry, implied-realized gap) improve HAR volatility forecasting beyond the standard HAR(1,5,22) specification?

## Motivation

- K530 showed HAR-ABS crushes GJR with DM=-15.45
- Standard HAR uses only level features (RV1, RV5, RV22), ignoring the *shape* of the volatility path
- arXiv:2503.00851 proposes path-dependent features for HAR
- Question: does capturing path shape (trends, curvature, jumps) add predictive value at daily frequency?

## Method

### Models
| Model | Description |
|-------|-------------|
| HAR | Standard HAR(1,5,22) on \|r\| |
| HAR-PD | HAR + 6 path-dependent features (OLS) |
| HAR-PD-LASSO | HAR + LASSO-selected path features |
| A4f-N | MF-GJR-X (tau = theta0 + theta1 * VIX^2, free omega) |
| GJR-N | Standard GJR-GARCH(1,1) |

### Path Features
| Feature | Definition |
|---------|-----------|
| TREND | RV_5d - RV_22d (short vs long-term) |
| CONVEX | RV_1d - 2*RV_5d + RV_22d (acceleration) |
| MOM | RV_1d / RV_5d - 1 (momentum) |
| JUMP | max(\|r\|)_5d / mean(\|r\|)_5d - 1 (jump proxy) |
| ASYM | sum(r^2 where r<0) / sum(r^2) over 5d (downside fraction) |
| VIX_GAP | VIX daily vol - RV_5d (implied-realized spread) |

### Configuration
- Data: SPY 2005-01-04 to 2026-04-07 (n=5,347)
- OOS: 2019-01-01 onwards (n=1,824)
- HAR window: 1,000 days rolling OLS
- GARCH window: 2,000 days, refit every 63 days
- Evaluation: QLIKE on r^2 (Patton 2011), DM test (Harvey t>3.0), Spearman rho
- seed=42

## Results

### QLIKE on r^2 (lower is better)
| Model | QLIKE | Spearman rho |
|-------|-------|-------------|
| **HAR** | **1.2826** | **0.5183** |
| HAR-PD | 1.6270 | 0.3712 |
| HAR-PD-LASSO | 1.4835 | 0.4034 |
| A4f-N | 1.4344 | 0.4178 |
| GJR-N | 1.5180 | 0.3698 |

### Pairwise DM Tests (QLIKE on r^2)
| Comparison | DM stat | Winner | Significant? |
|-----------|---------|--------|-------------|
| HAR-PD vs HAR | +5.53 | HAR | Yes (HAR dominates) |
| HAR-PD-LASSO vs HAR | +6.19 | HAR | Yes |
| HAR-PD vs HAR-PD-LASSO | +4.13 | HAR-PD-LASSO | Yes |
| HAR vs GJR-N | -7.69 | HAR | Yes |
| HAR-PD vs A4f-N | +2.99 | A4f-N | No (below Harvey 3.0) |
| HAR vs A4f-N | -8.78 | HAR | Yes |
| A4f-N vs GJR-N | -3.47 | A4f-N | Yes |

### Significant Path Features (last refit, |t| > 3.0)
| Feature | Coefficient | t-stat | Significant? |
|---------|------------|--------|-------------|
| vix_gap | 0.979 | 7.27 | Yes (only significant feature) |
| mom | -0.001 | -2.02 | No |
| asym | 0.002 | 1.84 | No |
| jump | -0.0001 | -0.21 | No |
| trend | 0.090 | ~0 | No (multicollinear) |
| convex | -0.208 | ~0 | No (multicollinear) |

## Key Finding: Multicollinearity Problem

The path features `trend` and `convex` are **exact linear combinations** of HAR features:
- `trend = rv5 - rv22`
- `convex = rv1 - 2*rv5 + rv22`

This creates **perfect multicollinearity** in the HAR-PD OLS, producing NaN/extreme standard errors and unstable coefficients. The rolling OLS parameters fluctuate wildly, degrading forecast accuracy. This is why HAR-PD is significantly **worse** than HAR, not just equal.

## Conclusions

1. **HAR-PD significantly WORSENS HAR** (DM=+5.53): Path features don't add value -- they introduce multicollinearity noise at daily frequency
2. **LASSO doesn't help enough**: HAR-PD-LASSO (DM=+6.19 vs HAR) is even worse, likely because LASSO selects unstable features in-sample
3. **Standard HAR dominates all models** on QLIKE(r^2): QLIKE=1.283 vs next best A4f=1.434
4. **VIX_GAP is the only significant path feature** (t=7.27): The implied-realized spread carries genuine information
5. **A4f beats GJR** (DM=-3.47): VIX-driven long-run component improves GARCH, consistent with K988
6. **HAR beats A4f significantly** (DM=-8.78): Even with VIX, GARCH cannot match HAR on r^2

## Implications for Future Work

- **HAR + VIX_GAP only** (without other path features): A parsimonious HAR(1,5,22) + VIX_GAP model could be tested -- it avoids multicollinearity while capturing the only significant path feature
- **Orthogonalize path features**: Before adding to HAR, residualize trend/convex against rv1/rv5/rv22 to remove collinearity
- **5-min RV target**: Path features may be more valuable when evaluated against proper 5-min RV rather than r^2 proxy
- Note: HAR beating GARCH on r^2 is partly mechanical (HAR uses r-based features). Cross-model comparison must use QLIKE on r^2 (Patton 2011 proxy-robust)

## References

- arXiv:2503.00851 - Path-dependent HAR
- Corsi (2009, JFE) - HAR-RV model
- Patton (2011, J Econometrics) - QLIKE loss function
- Harvey et al. (2016) - Multiple testing threshold t > 3.0
- K530 - HAR-ABS vs GJR baseline (DM=-15.45)
- K988 - MF-GJR-X A4f specification

## Files

- `k1014.py` - Experiment script
- `k1014_results.json` - Full results with QLIKE, DM tests, Spearman, feature significance
- `k1014_comparison.png` - 4-panel comparison plot
