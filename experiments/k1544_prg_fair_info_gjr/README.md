# K1544: Fair-Information GJR-X Current-Overnight Benchmark

## Purpose

This experiment addresses PRG v6 blocking issue #2: the prior paper Section 4.5
GJR-X benchmark used lagged overnight squared returns, while PRG's intraday
forecast conditions on the current-day overnight realization observed at the
day-d open.

The benchmark here keeps the old daily GJR-X structure but changes the
exogenous overnight term from `r2_overnight[t-1]` to `r2_overnight[t]`:

```text
h_t = omega
    + alpha * r_c2c[t-1]^2
    + gamma * 1(r_c2c[t-1] < 0) * r_c2c[t-1]^2
    + beta * h[t-1]
    + delta * x_overnight[t]
```

At each OOS day `t`, parameters are estimated only on observations before `t`.
The same-day overnight term is used only because it is known at the market open.
The same-day close-to-close return and full-day variance target are not used in
the forecast.

## Run

```bash
uv run python experiments/k1544_prg_fair_info_gjr/k1544_prg_fair_info_gjr.py
```

## Required Outputs

- `k1544_prg_fair_info_gjr.py`
- `k1544_prg_fair_info_gjr_results.json`
- `results.json`
- `per_market_table.csv`
- `per_market_table.md`
- `fig_prg_vs_fair_gjr.png`

## References Checked

- Bollerslev and Ghysels (1996), periodic GARCH.
- Patton (2011), QLIKE and imperfect volatility proxies.
- Diebold and Mariano (1995), Harvey et al. (1997), and Harvey et al. (2016),
  forecast comparison and conservative multiple-testing threshold.
- Linton and Wu (2020), Opschoor and Lucas (2021), Todorova and Soucek (2014),
  session-aware volatility and overnight information.

