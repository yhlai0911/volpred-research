# K1068: Traditional Event Study (CAR / CASV) for Taiwan Earnings Announcements

- **Proposer**: User (methodological correction of K1059/K1060/K1062)
- **Executor**: Claude
- **Date**: 2026-04-13
- **Runtime**: ~6 seconds
- **Random seed**: 42

## Motivation

K1059/K1060/K1062 tested Taiwan earnings-announcement volatility using a
**simplified** approach: event-day r<sup>2</sup> divided by non-event-day r<sup>2</sup>.
The user correctly pointed out that this is **not** the standard event-study
methodology used in finance. The gold standard from MacKinlay (1997) is
**Cumulative Abnormal Returns (CAR)**, estimated from a market model over a
proper estimation window, and summed over event windows such as [-5, +5].

K1068 re-examines the same 10-stock Taiwan earnings sample with the classical
methodology so that the results are directly comparable with the published
academic literature (and so that our own claims are robust to the critique
"your vol-ratio is not a real event study").

## Problem statement

1. **H1** - Is CAR over [-5, +5] significantly non-zero? (return event)
2. **H2** - Does CAR[0, +1] (immediate reaction to post-close announcement)
   differ from CAR[+2, +5] (drift)?
3. **H3** - Is CASV (cumulative abnormal squared volatility) elevated during
   the event window? (the volatility event)
4. **H4** - Is there sectoral heterogeneity (Tech / Financial / Telecom /
   Traditional)?

## Method

### Normal return
Market Model (MacKinlay 1997 standard):
```
R_it = alpha_i + beta_i * R_mt + eps_it
```
- Estimation window: `[T-250, T-11]` trading days (avoid pre-event leakage).
- Minimum 100 valid obs in the estimation window.
- Market index proxy: `^TWII` (TAIEX, broader than 0050.TW).

### Abnormal returns and CAR
```
AR_it = R_it - (alpha_hat_i + beta_hat_i * R_mt)
CAR_i(t1, t2) = sum_{t=t1..t2} AR_it
```
Event window: **[-5, +5]** (11 trading days). Decomposed into:

| Window   | Interpretation                                  |
| -------- | ----------------------------------------------- |
| [-5, -1] | Pre-event / leakage                             |
| [0, +1]  | Immediate reaction (TW earnings are post-close) |
| [+2, +5] | Drift                                           |
| [-5, +5] | Total                                           |

### Statistical tests
- **Brown & Warner (1985)** cross-sectional t-test on CAR.
- **Patell (1976)** standardized-CAR test:
  `SCAR_i = CAR_i / sqrt(L * sigma_i^2)`.
- **Boehmer, Masumeci & Poulsen (1991)** standardized cross-sectional t-test
  (robust to event-induced variance changes).
- **CASV** (Patell-Wolfson 1984): `sum (AR^2 / sigma_i^2 - 1)` tested against
  zero with a one-sample t-test.
- **One-way ANOVA** across sectors on CAR[-5, +5].

### Data
- Earnings dates: `財報公告日.txt` (Big5, 153,875 records, 2,409 firms).
- 10 stocks identical to K1060 (Tech: 2330 / 2454 / 2317 / 2308 / 2303;
  Financial: 2882 / 2891 / 2881; Telecom: 2412; Traditional: 2002).
- 2010-01-01 .. 2025-12-31, 3,906 trading days.
- **560 usable events** after filtering for sufficient estimation window.
- yfinance daily close, auto_adjust=True. Individual stocks do **not** use
  `clean_tw50_data` (that is ETF-specific).

## Expected results (ex ante)

Given K1060 found a T+1 volatility spike (mean ratio 1.466, p=0.034), we
expected:
- Weak **return** signal (CAR small / insignificant) - earnings surprises
  net out across 10 stocks covering 40+ years of event dates.
- Strong **volatility** signal (CASV significantly positive) - the volatility
  spike documented in K1060 should survive the methodological upgrade.
- Possible **sectoral** heterogeneity (Tech strongest per K1060 T+1 ratios).

## Results

### Table 1 - Pooled CAR and CASV by window (N=560 events)

| Window    | Mean CAR | t_BW   | p_BW   | t_Patell | t_BMP  | Mean CASV | t_CASV | p_CASV    |
| --------- | -------- | ------ | ------ | -------- | ------ | --------- | ------ | --------- |
| [-5, -1]  | +0.0017  | +1.29  | 0.198  | +1.22    | +1.07  | +1.390    | +3.38  | 0.0008    |
| [0, +1]   | -0.0002  | -0.25  | 0.801  | -0.55    | -0.42  | +1.358    | +4.15  | <0.0001   |
| [+2, +5]  | -0.0015  | -1.40  | 0.163  | -1.29    | -1.23  | +0.380    | +1.55  | 0.122     |
| **[-5, +5]** | **-0.0001** | **-0.04** | **0.966** | **-0.19** | **-0.16** | **+3.128** | **+4.35** | **<0.0001** |

### Table 2 - Per-stock CAR[-5, +5] and CAR[0, +1]

| Ticker   | Name             | Sector      | N_ev | CAR[-5,+5] | t_BW   | CAR[0,+1] | t_BW   | CASV[-5,+5] |
| -------- | ---------------- | ----------- | ---- | ---------- | ------ | --------- | ------ | ----------- |
| 2330.TW  | TSMC             | Tech        | 56   | -0.0019    | -0.52  | +0.0018   | +1.07  | +0.114      |
| 2454.TW  | MediaTek         | Tech        | 55   | +0.0076    | +0.82  | +0.0049   | +1.46  | +1.695      |
| 2317.TW  | Hon Hai          | Tech        | 56   | +0.0009    | +0.11  | -0.0014   | -0.32  | +6.608      |
| 2308.TW  | Delta            | Tech        | 57   | -0.0002    | -0.04  | +0.0017   | +0.41  | +3.063      |
| 2303.TW  | UMC              | Tech        | 56   | +0.0051    | +0.51  | -0.0058   | -1.40  | +6.965      |
| 2412.TW  | Chunghwa Telecom | Telecom     | 56   | +0.0036    | +1.48  | +0.0005   | +0.46  | +0.169      |
| 2882.TW  | Cathay Holdings  | Financial   | 56   | -0.0042    | -0.97  | -0.0010   | -0.43  | +3.447      |
| 2891.TW  | CTBC Financial   | Financial   | 56   | -0.0077    | -1.68  | -0.0053   | -2.85  | +3.199      |
| 2881.TW  | Fubon Financial  | Financial   | 56   | -0.0054    | -1.08  | +0.0001   | +0.06  | +1.946      |
| 2002.TW  | China Steel      | Traditional | 56   | +0.0015    | +0.26  | +0.0021   | +0.77  | +4.052      |

CTBC Financial (2891) is the single stock with a **significantly negative**
CAR[0,+1] (t=-2.85, p<0.01). UMC has the largest volatility spike (CASV=+6.97).

### Table 3 - Sector-level aggregates (events pooled within sector)

| Sector      | N_stocks | N_events | CAR[-5,+5] | t_BW   | CAR[0,+1] | CASV[-5,+5] |
| ----------- | -------- | -------- | ---------- | ------ | --------- | ----------- |
| Tech        | 5        | 280      | +0.0023    | +0.65  | -0.0000   | +3.694      |
| Financial   | 3        | 168      | -0.0058    | -2.16  | -0.0021   | +2.864      |
| Telecom     | 1        | 56       | +0.0036    | +1.48  | +0.0005   | +0.169      |
| Traditional | 1        | 56       | +0.0015    | +0.26  | +0.0021   | +4.052      |

ANOVA across sectors on CAR[-5,+5]: **F=1.15, p=0.33** (not significant).

### Hypothesis verdicts

| Hypothesis | Verdict | Key numbers |
| ---------- | ------- | ----------- |
| **H1**: CAR[-5,+5] != 0 | NOT SUPPORTED | mean=-0.0001, t_BW=-0.04, p=0.97 |
| **H2**: CAR[0,+1] vs CAR[+2,+5] | SIMILAR | paired t on difference not significant |
| **H3**: CASV[-5,+5] > 0 | **STRONGLY SUPPORTED** | mean=+3.128, t=+4.35, **p<0.0001** |
| **H4**: Sector heterogeneity | NOT SUPPORTED (F-test) | F=1.15, p=0.33 - but Financial sector CAR is marginally negative (t=-2.16) |

### Headline takeaway

- Taiwan earnings announcements generate **no systematic directional price
  reaction** across the pooled 10-stock sample (CAR close to zero across
  every window; standard return-event tests all insignificant).
- They do generate a **highly significant volatility reaction**: the
  cumulative abnormal squared volatility CASV[-5,+5] = +3.13 with t=+4.35
  (p<0.0001). The volatility spike K1060 identified via a simpler
  r<sup>2</sup>-ratio survives the methodological upgrade.
- The Financial sector shows a **marginally negative return reaction**
  (CAR[-5,+5] t=-2.16), driven mostly by CTBC, but the cross-sector ANOVA
  is not significant.

## Comparison with K1060 (simplified method)

| Metric        | K1060 (simplified)         | K1068 (traditional)                        |
| ------------- | -------------------------- | ------------------------------------------ |
| Normal proxy  | Rolling 60-day r<sup>2</sup> mean | Market model alpha + beta \* R_m     |
| Time window   | T+0 / T+1                  | [-5, +5] decomposed                        |
| Return metric | r<sup>2</sup> ratio        | CAR (signed), plus CASV for volatility     |
| Tests         | Welch t / bootstrap        | BW / Patell / Boehmer / ANOVA              |
| Return result | T+0 mean ratio 0.94 (ns)   | CAR[-5,+5] near zero (ns)                  |
| Vol result    | T+1 mean ratio 1.47, p=0.03 | CASV[-5,+5] = +3.13, t=+4.35 (p<0.0001)  |
| Cross-stock   | 6/10 > 1 at T+1            | CTBC alone has CAR t<-2.85 at [0,+1]       |

**Both methods agree on the core empirical fact**: Taiwan earnings events
cause volatility but not predictable drift. K1068's traditional method gives
(a) a much **stronger** statistical claim on the volatility side
(t=4.35 vs t=2.07), and (b) a **clearer null** on the return side (whereas
K1060's ratio framework cannot cleanly separate direction from magnitude).

## Limitations

- 10-stock sample, 56 events per stock on average. A larger panel (50-100
  stocks, stratified by size) would give tighter standard errors and let us
  test Financial-sector negativity more convincingly.
- `^TWII` is a price index; using a total-return index (TR) could marginally
  shift alphas but should not change the CASV result.
- Earnings announcement file does **not** distinguish EPS surprise sign, so
  any cancellation between positive and negative surprises reduces the
  likelihood of finding CAR != 0.
- Bootstrap for p-values is not implemented here (parametric t instead).
- No correction for overlapping event windows (events close in time for
  different stocks - probably limited in this sample).

## Next steps

1. **Expand to top-50 Taiwan stocks** and redo CAR/CASV; check whether
   Financial negativity is generalizable.
2. **Use EPS surprise sign** (positive vs negative) to run directional CAR
   tests - this is where Brown & Warner (1985) and Savor & Wilson (2016)
   typically find significant CAR.
3. **GARCH-augmented sigma** for CASV: replace constant sigma_i with a
   time-varying GARCH variance to get a cleaner volatility event metric
   (Corrado & Truong 2008 style).
4. **Overlap with dividend/guidance dates** to rule out confounding events.

## Files

- `k1068.py` - experiment script
- `k1068_results.json` - full results (pooled tests, per-stock, sector, hypotheses)
- `k1068_car_windows.png` - mean CAR by window with 95% CI
- `k1068_car_timeseries.png` - AAR and CAAR across [-5, +5]
- `k1068_sector_heterogeneity.png` - sector x window CAR heatmap
- `k1068_comparison_k1060.png` - cross-method scatter and effect-size bars

## References

- MacKinlay, A.C. (1997) "Event studies in economics and finance" *J Econ Lit* 35(1): 13-39.
- Brown, S. & Warner, J. (1985) "Using daily stock returns: The case of event studies" *J Fin Econ* 14(1): 3-31.
- Patell, J.M. (1976) "Corporate forecasts of earnings per share and stock price behavior" *J Acct Res* 14(2): 246-276.
- Boehmer, E., Masumeci, J., Poulsen, A.B. (1991) "Event-study methodology under conditions of event-induced variance" *J Fin Econ* 30(2): 253-272.
- Patell, J.M. & Wolfson, M.A. (1984) "The intraday speed of adjustment of stock prices to earnings and dividend announcements" *J Acct Res* 22: 223-252.
- Beaver, W. (1968) "The information content of annual earnings announcements" *J Acct Res* 6: 67-92.
- Savor, P. & Wilson, M. (2016) "Earnings announcements and systematic risk" *J Fin Quant Anal* 51(1): 197-224.
- K1059, K1060, K1062 - prior simplified event-study tests in this research
  programme.
