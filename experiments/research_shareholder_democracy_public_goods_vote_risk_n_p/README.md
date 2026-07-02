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
- `data/raw/proxy_monitor_proposals_raw.json`: raw Proxy Monitor API cache.
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

Run:

```bash
uv run python experiments/research_shareholder_democracy_public_goods_vote_risk_n_p/research_shareholder_democracy_public_goods_vote_risk_n_p.py
```

Then read `research_shareholder_democracy_public_goods_vote_risk_n_p_results.json` for the verdict and diagnostics.
