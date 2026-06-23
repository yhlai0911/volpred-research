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
- `codex_review.md`

## Results

Final run: 2026-06-24 local session.

| Market | N | PRG QLIKE | PRG open-known QLIKE | Fair-info GJR-X QLIKE | PRG adv % | Open-known adv % | DM t fair-PRG | DM t fair-openPRG |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SPY | 1823 | 0.758061 | 0.680032 | 0.726747 | -4.31 | 6.43 | -2.803 | 2.115 |
| QQQ | 1981 | 0.770729 | 0.689119 | 0.742209 | -3.84 | 7.15 | -2.501 | 2.967 |
| GLD | 1613 | 0.820410 | 0.553532 | 0.587197 | -39.72 | 5.73 | -11.060 | 3.625 |
| EEM | 1734 | 0.678591 | 0.438422 | 0.528671 | -28.36 | 17.07 | -9.434 | 10.130 |
| 0050.TW | 1251 | 0.776468 | 0.562581 | 0.615490 | -26.15 | 8.60 | -6.567 | 3.870 |
| TAIFEX | 843 | 0.120932 | 0.039291 | 0.058561 | -106.51 | 32.91 | -6.256 | 5.608 |

DM sign convention: `fair-GJR loss - PRG loss`; positive favors PRG.

## Interpretation

The direct current-overnight GJR-X repair overturns the canonical paper timing
comparison: FairInfo GJR-X has lower QLIKE than canonical PRG Extended in all
six markets, with Harvey-significant wins in GLD, EEM, 0050.TW, and TAIFEX.

The diagnostic `PRG open-known` column changes the interpretation. If the
full-day forecast is explicitly evaluated at the market open and the already
realized overnight component is inserted as known information, PRG again beats
FairInfo GJR-X in all six markets. This means the blocking issue is not closed
by simply replacing lagged GJR-X with current GJR-X in the old narrative. Paper
integration needs a forecast-timing decision first:

- Canonical `h_overnight + h_intraday`: current-ON GJR-X is the stronger
  benchmark.
- Full-day-at-open `x_overnight + h_intraday`: PRG remains stronger, but this
  is a different target timing convention and must be stated explicitly.

No paper body files were changed.

## References Checked

- Bollerslev and Ghysels (1996), periodic GARCH.
- Patton (2011), QLIKE and imperfect volatility proxies.
- Diebold and Mariano (1995), Harvey et al. (1997), and Harvey et al. (2016),
  forecast comparison and conservative multiple-testing threshold.
- Linton and Wu (2020), Opschoor and Lucas (2021), Todorova and Soucek (2014),
  session-aware volatility and overnight information.
