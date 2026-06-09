# Diebold-Mariano (1995) + Harvey-Leybourne-Newbold (1997)

- **Citations**:
  - Diebold, F. X., & Mariano, R. S. (1995). Comparing predictive accuracy. *Journal of Business & Economic Statistics* 13(3), 253–263.
  - Harvey, D., Leybourne, S., & Newbold, P. (1997). Testing the equality of prediction MSEs. *International Journal of Forecasting* 13(2), 281–291.
- **Used in K1432 for**: Pairwise OOS forecast accuracy comparison. DM stat with Newey-West HAC variance (lag = h − 1 for h-step forecasts), HLN small-sample correction, two-sided t_{n-1} p-value.
- **Implementation**: `dm_test()` in the script.
- **Sign convention used**: `d = loss_baseline − loss_alt`; positive DM → alternative beats baseline; negative DM → baseline beats alternative. K1432 OOS DM stats for stress-augmented vs. HAR-RV are uniformly **negative** (often p < 0.05) → stress augmentation significantly **worsens** forecasts.
