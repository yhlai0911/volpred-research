# Shareholder-Democracy Public-Goods Vote Risk

## Question

Do shareholder-democracy or public-goods proposal votes predict next-day firm realized variance, and is there detectable sector ETF spillover?

This is a bounded public-data pilot for the backlog item:

> Shareholder-democracy public-goods vote risk: N-PX / contested ESG proposal whether it predicts firm RV and sector spillover.

## Data

- Proposal/vote events: public Proxy Monitor API, `https://api.proxymonitor.org/proposals-search/`
- Public resolution cross-check: As You Sow resolutions snapshot, `https://apps.asyousow.org/rs-data.php`
- Prices: yfinance daily adjusted close, downloaded with `auto_adjust=False` and then using the explicit `Adj Close` column.
- Analysis period: 2020-2024 proposal events.

This pilot is not a full Form N-PX mutual-fund-vote panel. It does not observe each fund's vote, holdings, index-manager concentration, or ISS/FactSet enriched classifications. Those are required for a full version of the idea.

## Method

1. Download all public Proxy Monitor proposal records and normalize ticker, date, proposal type, vote support, and proponent metadata.
2. Tag public-goods proposals using conservative environmental/social/public-policy keywords and Proxy Monitor general classifications.
3. Tag shareholder-democracy proposals using voting-rights and governance keywords.
4. Aggregate multiple proposals to one firm-date event.
5. Align event dates to the first trading day on or after the calendar event date.
6. Use `raw_event_signal.shift(1)` so the next close-to-close squared return at `t` is predicted only by an event signal from `t-1`.
7. Compare next-day squared returns against each firm's prior 60-trading-day variance baseline.
8. Run one-sample bootstrap/t-tests, public-goods vs other-proposal Welch/bootstrap tests, clustered OLS by target date, and a simple OOS QLIKE add-on test.
9. Map industries coarsely to sector ETFs for a bounded spillover check.

## Files

- `research_shareholder_democracy_public_goods_vote_risk_n_p.py`: full reproducible script.
- `research_shareholder_democracy_public_goods_vote_risk_n_p_results.json`: machine-readable results.
- `data/raw/proxy_monitor_proposals_2020_2024_window_raw.json`: raw Proxy Monitor API cache for the analysis window plus the cutoff boundary batch.
- `data/raw/proxy_monitor_fetch_meta.json`: API reported count, fetched row count, and stop reason.
- `data/raw/as_you_sow_resolutions_snapshot.json`: raw As You Sow snapshot cache.
- `data/raw/yfinance_adj_close_*.csv`: yfinance price cache.
- `data/proxy_monitor_proposals_normalized.csv`: normalized proposal table.
- `data/firm_proposal_events_aggregated.csv`: firm-date event table.
- `data/firm_event_risk_rows.csv`: firm-level event-study rows.
- `data/sector_event_risk_rows.csv`: sector ETF event-study rows.
- `figures/`: diagnostic charts.

## References

- He, Kahraman, and Lowry (2023), "ES Risks and Shareholder Voice", Review of Financial Studies.
- Michaely, Ordonez-Calafi, and Rubio (2022), "Mutual funds' strategic voting on environmental and social issues", Review of Accounting Studies.
- SEC (2022), Form N-PX amendments press release.
- Tidy Finance (2025), ISS Shareholder Proposals data tutorial.

## Current Result

Completed run:

```bash
uv run python experiments/research_shareholder_democracy_public_goods_vote_risk_n_p/research_shareholder_democracy_public_goods_vote_risk_n_p.py
```

Verdict: `null_or_inconclusive`.

Key diagnostics:

- Proxy Monitor API reported 10,953 proposal rows; the script fetched 3,200 rows and stopped once the date-descending API crossed before the 2020 analysis window.
- Analysis sample: 2,911 proposals from 2020-2024, 242 firms, 1,184 firm-date events.
- Price coverage: 1,103/1,184 firm-date events with usable yfinance history and 340/340 sector ETF event rows.
- Public-goods firm events: mean scaled abnormal next-day RV = 1.415, bootstrap 95% CI [-0.053, 3.510], t-test p = 0.127.
- Public-goods vs other proposal events: mean difference = 1.240, bootstrap 95% CI [-0.227, 3.284], Welch p = 0.187.
- OOS QLIKE public-goods event multiplier: loss difference = -0.784, bootstrap 95% CI [-2.612, 0.208], paired p = 0.300.
- Sector ETF spillover: mean scaled abnormal RV = 0.053, bootstrap 95% CI [-0.156, 0.284], p = 0.645.

Interpretation: this public-data pilot does not provide a statistically reliable firm-RV or sector-spillover signal. There is weak positive firm-level direction in some specifications, but confidence intervals include zero and the OOS QLIKE improvement is not significant. A full N-PX/ISS/FactSet panel remains required before making a stronger claim about large-manager vote pressure or contested ESG proposal channels.
