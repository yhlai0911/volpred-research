# K929: Asymmetric Volatility Transmission SPY→0050.TW

## Problem
K919 found SPY→Taiwan gap channel dominates with overall beta=0.472 (R²=0.355). But is the transmission symmetric? Does fear (SPY decline) transmit more strongly than greed (SPY rise)?

## Motivation
- K919: Gap beta overall 0.472, slightly asymmetric (down 0.479 vs up 0.429)
- Behavioral finance: loss aversion → negative news transmits more strongly
- GJR-GARCH gamma > 0 → negative shocks amplify volatility
- **Hypothesis**: SPY large declines cause more extreme 0050.TW gaps than equivalent SPY gains

## Method
1. **Data**: SPY + 0050.TW daily OHLC (2012-2026, yfinance), VIX
2. **Symmetric regression**: tw_gap(t+1) = alpha + beta * spy_ret(t) + eps
3. **Asymmetric regression (GJR-style)**: tw_gap(t+1) = alpha + beta_pos * spy_ret(t) * I(spy>0) + beta_neg * spy_ret(t) * I(spy<=0) + eps
4. **Wald test**: H0: beta_neg = beta_pos
5. **Bootstrap CI** (10,000 reps) for asymmetry coefficient (beta_neg - beta_pos)
6. **Quintile analysis**: Non-linear pattern in extreme returns
7. **Extreme events**: SPY > 2sigma vs SPY < -2sigma gap distributions
8. **VIX regime interaction**: 4 quartiles
9. **Structural break**: Pre/post night session (2017), pre/post COVID (2020)
10. **Rolling asymmetry**: 2-year (504 trading days) rolling window

## Results — NULL: No Significant Asymmetry

### Key Findings
- **Symmetric beta = 0.4504** (t=18.34, R²=0.317, N=3,471)
- **beta_pos = 0.460, beta_neg = 0.442** — difference is tiny (-0.019)
- **Wald test p = 0.812** — cannot reject symmetry
- **Bootstrap 95% CI for (beta_neg - beta_pos): [-0.161, 0.125]** — straddles zero
- **P(beta_neg > beta_pos) = 42.3%** — no evidence of fear dominance

### Extreme Events: Also Symmetric
- SPY < -2sigma (N=97): mean TW gap = -1.298%
- SPY > +2sigma (N=61): mean TW gap = +1.418%
- Absolute gap ratio = 0.92 (greed actually slightly stronger at extremes!)
- KS test p=0.886 — distributions indistinguishable

### Exception: Med-High VIX Regime
- **Only in VIX 16-20 range**: beta_neg=0.631 vs beta_pos=0.433, ratio=1.46x (Wald p=0.019)
- Low VIX: symmetric (ratio=1.01)
- High VIX (>20): also symmetric (ratio=0.99)
- This isolated finding does not constitute robust evidence of general asymmetry

### Rolling Asymmetry
- Mean diff = -0.009 (near zero)
- 53.5% of windows show beta_neg > beta_pos — essentially 50/50
- Large variation over time (std=0.157)

### Structural Breaks
- Night session (2017): asymmetry narrowed from -0.042 to -0.009
- COVID (2020): no material change

## Conclusion
**The "fear contagion > greed diffusion" hypothesis is NOT supported.** SPY→0050.TW overnight gap transmission is essentially symmetric at beta approximately 0.45. Both positive and negative SPY signals transmit with nearly equal intensity. The one exception (Med-High VIX regime, ratio=1.46x, p=0.019) is isolated and does not survive multiple comparison correction.

This is an important null result: it means Taiwan's overnight reaction to US markets is proportional and balanced, not fear-driven. The gap channel is a neutral information conduit.

## Limitations
- Uses daily close-to-close SPY return as proxy for overnight news
- 0050.TW gap includes both US-driven and local overnight news
- Forward-fill SPY returns on TW-only trading days may introduce noise
- No control for local Taiwan macro/political events
- Split adjustment for 0050.TW via clean_tw50_data (pre-2014 issue)

## Data Source
- yfinance: SPY, 0050.TW (OHLCV), ^VIX
- Period: 2012-01-05 to 2026-04-02
- N=3,471 aligned observations
- 0050.TW cleaned via `clean_tw50_data()`

## Error Log Rules Applied
- 0050.TW: used `clean_tw50_data`
- Fixed seed: `np.random.seed(42)` and `np.random.default_rng(42)`
- This is NOT a strategy backtest, so no lag/lookahead concern (pure regression)

## References
- Engle & Ng (1993) - News Impact Curves
- Glosten, Jagannathan & Runkle (1993) - GJR-GARCH
- Baele (2005) - Volatility spillover in equity markets
- Bekaert, Ehrmann, Fratzscher & Mehl (2014) - Global crises and equity market contagion

## Output Files
- `k929_asymmetric_transmission.py` - Main experiment script
- `k929_asymmetric_transmission_results.json` - Full results
- `k929_asymmetry.png` - 4-panel: scatter + quintile + bootstrap + VIX regime
- `k929_extreme_events.png` - 3-panel: extreme distributions + boxplot + rolling
