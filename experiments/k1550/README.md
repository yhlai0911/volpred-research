# K1550 - FINRA Short-Volume Squeeze-Pressure Proxy

## Research Question

Do public FINRA short-sale volume shocks predict higher next-5-day realized volatility, jump intensity, or left-tail loss for liquid small-cap / meme-risk stocks?

This is a proxy experiment. It does not observe true short interest, securities-lending utilization, borrow fees, recalls, options gamma, or prime-broker inventory. The tested signal is a reduced-form squeeze-pressure proxy:

```text
squeeze_pressure_score_t =
  z(21d change in FINRA short_volume / FINRA off-exchange total_volume)_t
  + z(21d rolling short-volume flow / 21d average yfinance volume)_t
```

## Literature Basis

- FINRA Short Sale Volume Data: public daily short-sale volume files and the official caveats around interpreting those files. Source: https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data
- FINRA Daily Short Sale Volume Files: source convention for CNMS daily files. Source: https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data/daily-short-sale-volume-files
- FINRA Information Notice 5/10/19: explains limitations in using daily short-sale volume as a proxy for short-sale activity. Source: https://www.finra.org/rules-guidance/notices/information-notice-051019
- Hong, Li, Ni, Scheinkman, and Yan (2015), Days to Cover and Stock Returns: motivates the economic role of days-to-cover style short-interest pressure. Source: https://www.nber.org/system/files/working_papers/w21166/w21166.pdf
- Foucault, Sraer, and Thesmar (2011), Individual Investors and Volatility: motivates retail-attention / individual-investor volatility channels. Source: https://faculty.haas.berkeley.edu/dsraer/SRD.pdf

Related prior memory: K1502 found that public FINRA off-exchange short-volume ratios did not robustly forecast next-day idiosyncratic volatility across a similar retail/small-cap basket. K1550 tests a different horizon and outcome: top-decile squeeze-pressure events vs next-5-day realized variance, jump, and left-tail outcomes.

## Data

- FINRA source: cached K1502 CNMS daily short-sale volume files originally sourced from FINRA daily files.
- Price source: cached K1502 yfinance price panel.
- Sample: 2023-01-03 to 2026-06-12.
- Universe: 21 liquid/current-name small-cap or meme-risk tickers covered by the K1502 cache: `GME`, `AMC`, `BB`, `KOSS`, `OPEN`, `KSS`, `PLTR`, `SOFI`, `HOOD`, `RIVN`, `LCID`, `CHWY`, `DKNG`, `AFRM`, `UPST`, `MARA`, `RIOT`, `COIN`, `CVNA`, `TLRY`, `F`.
- FINRA rows: 18,144.
- Panel rows after return construction: 18,123.

This is not a historical Russell 2000 constituent test. A live IWM-holdings version would require a separate data-ingestion pass and broader ticker-level coverage.

## Method

For each ticker:

1. Compute FINRA short ratio as `short_volume / offex_total_volume`.
2. Compute the 21-trading-day change in short ratio.
3. Compute a flow-based days-to-cover proxy as rolling 21-day FINRA short volume divided by rolling 21-day average yfinance volume.
4. Convert both components to rolling 252-day z-scores with at least 126 observations.
5. Define a squeeze-pressure event when the score on day `t` is above the rolling 252-day 90th percentile computed through `t-1`.
6. Compare event days against non-event days for:
   - log forward 5-day realized variance;
   - forward 5-day jump indicator, where max absolute daily return over `t+1` to `t+5` exceeds 2x trailing 63-day sigma at `t`;
   - forward 5-day left-tail indicator, where the cumulative return over `t+1` to `t+5` is below the rolling 252-day 10th percentile through `t-1`.

Lookahead controls:

- The event threshold is shifted by one day, so day `t` is compared only with history through `t-1`.
- All forecast targets start at `t+1` and end at `t+5`.
- The jump threshold uses trailing volatility through day `t`.
- The left-tail threshold uses only historical forward-return outcomes through `t-1`.
- Random bootstrap procedures use `SEED = 1550`.

Formal tests:

- Ticker-level Welch t-statistics compare event vs control log forward 5-day RV.
- Cross-ticker aggregate effects use a 5000-rep bootstrap CI over ticker-level effects.
- A sign test checks whether positive log-RV effects dominate across tickers.

## Results

Verdict: `NULL_NO_ROBUST_SQUEEZE_RISK_VOL_SIGNAL`.

Aggregate results across 21 tickers:

| Metric | Result |
|---|---:|
| Median log forward-5d RV event effect | -0.0583 |
| Mean log forward-5d RV event effect | -0.0412 |
| Positive log-RV tickers | 10 / 21 |
| Log-RV bootstrap 95% CI | [-0.1760, 0.1039] |
| Sign-test p-value | 1.0000 |
| Median jump-rate effect | -0.0111 |
| Positive jump-rate tickers | 9 / 21 |
| Jump-rate bootstrap 95% CI | [-0.0388, 0.0161] |
| Median left-tail-rate effect | -0.0269 |
| Positive left-tail tickers | 6 / 21 |
| Left-tail bootstrap 95% CI | [-0.0383, 0.0080] |

The strongest positive log-RV effects appear in `BB`, `KOSS`, `PLTR`, `F`, and `GME`, but the basket-level evidence is mixed and fails the robustness gate. Several high-attention names, including `AMC`, `OPEN`, `RIVN`, `CVNA`, and `MARA`, show negative event-minus-control log-RV effects in this reduced-form setup.

Interpretation: public FINRA short-volume pressure alone is not a reliable squeeze-risk volatility signal in this cache-backed 21-name sample. The result is consistent with K1502's caution that FINRA public short-volume ratios are noisy proxies and should not be treated as direct short-interest or borrow-cost measures.

## Figures

- `figures/k1550_log_fwd5_rv_event_effect.png`
- `figures/k1550_jump_tail_effects.png`

## Reproduction

```bash
uv run python experiments/k1550/k1550.py
```

Main artifacts:

- `k1550.py`
- `k1550_results.json`
- `data/finra_cnms_filtered.csv`
- `data/prices.parquet`
- `data/panel.parquet`
- `data/panel_preview.csv`
- `figures/*.png`
- `codex_review.md`

## Limitations

- FINRA short-sale volume is short-selling flow, not true outstanding short interest.
- The flow-based days-to-cover proxy is not actual shares short divided by average volume.
- No borrow fees, stock-loan utilization, recall risk, exchange short interest, options positioning, or gamma data are included.
- The universe is a fixed 21-name current basket from the K1502 cache, not historical Russell 2000 constituents.
- Event-vs-control comparisons are reduced-form and do not control for earnings dates, news, market beta, sector shocks, or microstructure effects.
- Knowledge promotion is deferred to the main K1259 writer gate; this Codex experiment does not write `storage/memory/knowledge.json`.
