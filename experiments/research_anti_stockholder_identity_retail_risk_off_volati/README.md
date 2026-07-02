# Anti-Stockholder Identity Public Proxy and Retail-Risk-Off Volatility

## Question

Can an anti-stockholder / non-participation identity proxy lead retail-risk-off volatility in meme/retail-heavy equities, ARKK, IWM, and a high-idiosyncratic-volatility single-name basket?

Backlog item:

> Anti-stockholder identity / "not owning stocks" sentiment as a retail-risk-off volatility proxy.

## Data

- Public identity-attention fallback: Wikimedia daily pageviews from 2020-01-01 to 2026-07-01 for identity-relevant retail/speculation/rigged-market pages: `WallStreetBets`, `Meme_stock`, `GameStop_short_squeeze`, `Short_squeeze`, `Market_manipulation`, `Day_trading`, and `Robinhood_Markets`.
- Generic bearish/fear control: Wikimedia daily pageviews for `Stock_market_crash`, `Bear_market`, `Recession`, `VIX`, `Financial_crisis`, and `Stock_market_bubble`.
- Finance-attention denominator: Wikimedia pageviews for `Stock_market`, `S&P_500`, `Nasdaq_Composite`, `Dow_Jones_Industrial_Average`, and `Investment`.
- Retail leverage control: FINRA monthly margin statistics, lagged 22 trading days after monthly forward filling.
- Market targets and controls: yfinance daily OHLCV for retail/meme names, `ARKK`, `IWM`, high-idio candidate names, `SPY`, `QQQ`, and `^VIX`.
- Final sample: 2020-01-02 to 2026-07-01, 1,633 trading days, 24 target cells.

Google Trends and GDELT phrase probes were attempted during setup but were rate-limited in this runtime. They are not used in the reported data. This experiment is therefore a public-attention fallback, not a direct measure of anti-stockholder identity.

## Method

The primary signal is a 21-day normalized identity-attention z-score:

```text
log1p(21-day identity pageviews) - log1p(21-day broad finance anchor pageviews)
```

Lookahead controls:

1. Identity-attention signals use `.shift(1)`.
2. Generic fear-attention controls use `.shift(1)`.
3. FINRA monthly margin controls use `.shift(22)` after daily forward filling.
4. Targets are future windows `t+1..t+h`, with `h=5` and `h=22`.
5. Expanding OOS forecasts embargo train rows by the target horizon.

Targets:

- Future log realized variance.
- Future log downside semivariance.
- Future log dollar-volume crash proxy, defined as lagged trailing 22-day log dollar volume minus future average log dollar volume.

Controls include own trailing target-family measures, own recent group returns, generic fear attention, VIX level, SPY/QQQ market controls, and FINRA margin debt YoY growth.

Gate:

- Positive coefficient.
- HAC `t >= 3`.
- Holm-adjusted p-value below 0.05 across 24 primary cells.
- Positive expanding-OOS MSE improvement with DM-style HAC t-statistic at least 3.

## Files

- `research_anti_stockholder_identity_retail_risk_off_volati.py`: reproducible script.
- `research_anti_stockholder_identity_retail_risk_off_volati_results.json`: machine-readable results.
- `knowledge_candidate.json`: non-canonical candidate summary for later Claude/K1259 knowledge gate.
- `data/analysis_panel.csv`: final date-level analysis panel.
- `data/summary_table.csv`: 24 primary test cells.
- `data/wikimedia_pageviews_*.csv`: raw cached Wikimedia pageview pulls.
- `data/finra_margin_statistics.*`: cached FINRA source data and parsed monthly panel.
- `data/yfinance_ohlcv_panel.csv`: raw cached yfinance OHLCV panel.
- `figures/wikimedia_attention_signal.png`: attention proxy diagnostics.
- `figures/primary_test_diagnostics.png`: HAC t-stats and OOS diagnostics.
- `codex_review.md`: source-level reproducibility review.

## References

- Henkel and Pugnaghi-Zimpelmann, "Proud to Not Own Stocks: How Identity Shapes Financial Decisions", Review of Financial Studies advance article, 2026: https://academic.oup.com/rfs/advance-article/doi/10.1093/rfs/hhag034/8677631
- Da, Engelberg, and Gao, "In Search of Attention", Journal of Finance, 2011: https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2011.01679.x
- Barber and Odean, "All That Glitters: The Effect of Attention and News on the Buying Behavior of Individual and Institutional Investors", Review of Financial Studies, 2008: https://academic.oup.com/rfs/article-abstract/21/2/785/1607197
- Foucault, Sraer, and Thesmar, "Individual Investors and Volatility", Journal of Finance, 2011: https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2011.01668.x
- Wikimedia Analytics API pageviews documentation: https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/examples/page-metrics.html
- FINRA margin statistics: https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics
- yfinance project documentation: https://ranaroussi.github.io/yfinance/

## Current Result

Run:

```bash
uv run python experiments/research_anti_stockholder_identity_retail_risk_off_volati/research_anti_stockholder_identity_retail_risk_off_volati.py
```

Verdict: `WEAK_RAW_ONLY_NO_ROBUST_OOS_PASS`.

Primary diagnostics:

- Retail/meme 22-day RV: coefficient `+0.1604`, HAC t `2.85`, raw p `0.0044`, Holm p `0.1060`, OOS MSE improvement `-4.22%`, DM t `-0.72`.
- Retail/meme 22-day downside semivariance: coefficient `+0.1435`, HAC t `2.25`, Holm p `0.5432`, OOS MSE improvement `-5.00%`, DM t `-0.93`.
- High-idio 22-day downside semivariance: coefficient `+0.1423`, HAC t `2.14`, Holm p `0.6821`, OOS MSE improvement `-5.78%`, DM t `-0.90`.
- Best OOS cell is high-idio 22-day volume crash, with OOS MSE improvement `+1.17%`, but HAC t is only `1.15` and DM t is `0.21`.

Interpretation: the Wikimedia identity-relevant public-attention fallback shows a weak in-sample positive association with 22-day retail/meme volatility and downside semivariance, but it fails the pre-registered robustness gate and worsens OOS forecasts in the main positive cells. Treat this as evidence that this public fallback is not a robust leading retail-risk-off signal. It is not evidence against the identity channel itself because direct identity or survey microdata are not observed.

Limitations:

- Wikimedia pageviews are a weak public-attention fallback, not a direct measure of anti-stockholder identity or non-participation attitudes.
- Google Trends and GDELT phrase proxies were not used because both were rate-limited in this run environment.
- FINRA margin debt is monthly, broad, and lagged; it cannot identify high-frequency household risk-budget shocks.
- Daily OHLCV targets cannot observe retail order imbalance, broker-specific flow, or options activity.
- The experiment is diagnostic for public proxy usefulness only; it is not a causal test of identity formation or household non-participation.
