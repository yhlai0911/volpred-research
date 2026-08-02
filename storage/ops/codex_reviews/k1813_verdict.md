# K1813 Codex primary-path review

## Verdict: FAIL

The frozen bytes and commit identity are authentic, but two blocking defects remain:

1. `buy_and_hold` is not calculated as an actual buy-and-hold return.
2. The README converts an underpowered failure to reject into claims that the tradable effect does not exist.

These defects do not prove that H3 should be positive. The available numbers still look null-like. They do prevent the frozen experiment from supporting its stated conclusion at the required standard.

## Frozen-byte verification

Verified before review:

- Commit: `7a41cb362`
- `k1813.py`: 57,747 bytes, SHA-256 matches.
- `K1813_results.json`: 376,182 bytes, SHA-256 matches.
- `README.md`: SHA-256 matches.
- All four figure hashes match.
- All six cached CSV hashes and byte sizes match `reproduce_spec.json`.
- `reproduce_spec.json` identifies the same entrypoint and canonical result found on disk.

No frozen byte differed from the review request.

## Blocking defects

### B1 — The benchmark is not an actual buy-and-hold return

The segment returns are simple returns:

- `s_on = adj_open / prev_adj_close - 1` at `k1813.py:182`
- `s_id = adj_close / adj_open - 1` at `k1813.py:183`

But `run_strategy()` combines them additively:

```python
gross = w_on * seg["s_on"] + w_id * seg["s_id"]
```

at `k1813.py:522`, while `buy_and_hold` sets both weights to one at `k1813.py:966`.

Thus the reported benchmark is:

```text
s_on + s_id
```

instead of the actual close-to-close buy-and-hold return:

```text
(1 + s_on)(1 + s_id) - 1
= s_on + s_id + s_on*s_id
```

There is no coherent self-financing interpretation under which the position is reset to one unit of notional at the open, incurs no return-induced rebalance, and still has exactly zero turnover. Consequently, the claimed “buy-and-hold” benchmark, its Sharpe, its equity curve, and every H3 ΔSharpe comparison use the wrong benchmark series.

A read-only calculation from the frozen CSVs shows that the OOS Sharpe error happens to be small—approximately +0.0009 SPY, −0.0006 QQQ, +0.0007 IWM, −0.0008 TLT, and +0.0047 GLD when replacing the additive benchmark with the true close-to-close return. That suggests the headline null would probably survive, but it does not cure the benchmark-definition violation. Checklist item 3 is therefore a FAIL.

### B2 — The README overstates what this design can establish

The H3 bootstrap standard errors are not small enough to justify claims of absence:

- Plain overnight comparisons: approximately 0.18–0.26 ΔSharpe.
- Top-two rules: approximately 0.29–0.37.
- Avoid-worst rules: approximately 0.08–0.11.
- Across the full 25-comparison grid: approximately 0.08–0.37.

At SE 0.23–0.29, a two-sided 5% test generally needs an observed ΔSharpe around 0.45–0.57 merely to cross the nominal threshold; an approximate 80%-power effect is around 0.64–0.81. The experiment therefore cannot exclude moderate positive effects for several rules.

The formal evidence supports:

> No tested calendar rule produced a statistically significant positive ΔSharpe under this design.

It does not support the stronger statements:

- “可交易的那一軸……完全沒有星期結構” at `README.md:10`
- “效應本身不存在於可交易軸上” at `README.md:339`
- “不要再在 ETF 上追隔夜星期擇時” at `README.md:339`

The first-line claim that “1 bp 成本就足以殺死” the rules at `README.md:10` also conflicts with the later, better-supported explanation at `README.md:277-286` that the calendar rules already fail to add significant value at zero cost. This is a power/honesty failure under checklist item 6.

## Checklist findings

### 1. Lookahead — PASS

- T-bill rate is explicitly lagged at `k1813.py:241`.
- The ex-ante RV forecast uses `rv_on.shift(1).rolling(...)` at `k1813.py:482-484`.
- Frozen weekday selection uses only `seg.index < oos_start` at `k1813.py:941-945`.
- The walk-forward signal shifts within weekday before expanding at `k1813.py:632-639`.
- `next_on = w_on.shift(-1)` at `k1813.py:525` enters only `turn_close` at `k1813.py:527`; it never multiplies a return.
- For the walk-forward rule, the weight for the next overnight window is computable at the current close because it excludes its own future return.
- Frozen results report 12 causal perturbation probes per asset, no violations, and stable frozen selection.

No forward weight leaks into P&L.

### 2. In-sample/OOS separation — PASS

- `is_mask = seg.index < 2015-01-01` is used for the sign screen, top-two ranking, and worst-weekday choice at `k1813.py:935-945`.
- These selected weekday sets are frozen before the OOS strategy evaluation.
- OOS begins at `k1813.py:936`.
- The walk-forward variant is causal through the within-weekday `shift(1)`.

No OOS return is used in the frozen selections.

### 3. Benchmark fairness — FAIL

Common trading dates, cost parameters, risk-free series, and lag convention are applied consistently. Results also confirm:

- OOS observations: 2,909 for every book.
- Reported buy-and-hold turnover: exactly `0.0`.
- A 100%-bill position would algebraically have `total = rf_daily` and `excess = 0`.

However, the additive simple-return construction at `k1813.py:522` means the benchmark is not actual buy-and-hold. See blocking defect B1.

A smaller boundary issue is that OOS slicing omits any position-entry cost charged on the last pre-OOS close. This is one side at most and does not drive the result.

### 4. Cost and interest accounting — PASS with clarification

- Risk-free accrual is lagged and calculated actual/360 over `cal_days` at `k1813.py:531`.
- Cash is credited as `(1-w_on)*rf_daily` at `k1813.py:532`.
- Assigning the full daily accrual to the overnight interval is internally coherent for these close/open books.
- Buy-and-hold receives no cash credit; an overnight-only position receives no cash credit while invested overnight.
- Costs are per side and include open and close target-weight changes.

`net_with_cash` is the correct total-return base, but H3 Sharpe and bootstrap tests actually use `excess = net_with_cash - rf_daily` through `k1813.py:544`, `993-1007`, and `1021-1023`. That is economically defensible and is explained in the README, although `verdicts.H3.criterion` saying simply “scored on net_with_cash” is imprecise.

### 5. Inference — PASS for the main null, with qualifications

- Seed 42, B=2,000, and block length 20 are recorded consistently.
- Bootstrap comparisons are paired by using the same block indices for both strategies.
- HAC bandwidth is declared and implemented as `max(10, ceil(4*(n/100)^(2/9)))`.
- Joint weekday tests correctly test equality using four contrasts rather than testing all means against zero.
- H2 FDR families are explicit:
  - 25 asset×weekday contrasts per outcome.
  - Five joint-F tests per outcome.
- H3’s 25 comparisons are not multiplicity-adjusted in the frozen code. This does not weaken H3 REJECT: there is no positive nominal winner, and multiplicity adjustment cannot create one.
- The reported nine nominally significant losses are not nine independent findings: several are byte-identical degenerate rules. If BH is applied over the 25 H3 p-values, all nine survive at q=0.10, but only two survive at q=0.05.
- Bootstrap p-values can be exactly zero because no plus-one correction is used at `k1813.py:618`. They should be read as below the Monte Carlo resolution, not literally zero.

A single block length with no sensitivity check is a limitation, but no positive comparison is close enough to make it a blocking inference defect.

### 6. Power and honesty — FAIL

See blocking defect B2. The correct conclusion is failure to find a winner, not proof that the tradable effect is absent.

### 7. README versus results — PASS on numerical transcription

More than ten requested values were checked directly:

- H2c VRP q-values:
  - SPY 0.121899
  - QQQ 0.030272
  - IWM 0.175681
  - TLT 0.00013565
  - GLD 0.00166568
- H2c RV q-values:
  - SPY 0.243845
  - QQQ 0.054234
  - IWM 0.280051
  - TLT 0.00155884
  - GLD 0.00942266
- SPY always-overnight at 1 bp: ΔSharpe −0.53256, p=0.016.
- TLT always-overnight at 1 bp: ΔSharpe −0.71360, p=0.0035.
- IWM always-overnight at 1 bp: ΔSharpe +0.03802, p=0.8765, correctly rounded to 0.88.
- SPY turnover: top-two 204.70 and always-overnight 503.91 sides/year, correctly rounded to 205 and 504.
- TLT Thursday in-sample overnight mean: −2.1761 bps, correctly rounded to −2.18.
- SPY buy-and-hold reported Sharpe: 0.690734.
- TLT buy-and-hold reported Sharpe: −0.123830.
- The five Friday controlled-VRP q-values are all below 0.10, as stated.

The charts visually match their recorded series and do not add unsupported statistical annotations. The H3 equity plot inherits the incorrect buy-and-hold construction identified in B1.

### 8. Degenerate-rule disclosure — PASS

Frozen results confirm that SPY, QQQ, IWM, and GLD have positive in-sample means on all five weekdays. For each of those assets:

- `dow_gated_overnight` is identical to `always_overnight`.
- The frozen walk-forward rule also resolves to the same OOS path.
- ΔSharpe versus always-overnight is exactly `0.0`.
- p-value is exactly `1.0`.

This is clearly disclosed at `README.md:288` and is not presented as five independent discoveries. TLT is the only non-degenerate sign-screen case because Thursday is −2.176 bps in sample.

### 9. Reproduce-spec integrity — PASS

- `entrypoint.sha256` matches frozen `k1813.py`.
- `entrypoint.size_bytes` is exactly 57,747.
- `results.code_trace` has the same hash and size.
- `canonical_result_identity.sha256` matches the results file.
- `canonical_result_identity.size_bytes` is exactly 376,182.
- Every pinned input CSV matches its recorded hash and byte size.

The K1708 identity failure is not present.

## Non-blocking observations

- H2b is supported as a full-sample descriptive result: all five assets reject weekday equality for both RV and the physical-measure forecast-error proxy after five-test BH-FDR.
- H2c is accurately narrowed to QQQ, TLT, and GLD. The controlled joint-F q-values support that statement.
- The Friday result is properly labelled exploratory, and its five controlled-VRP cells pass the declared 25-cell BH family. Cross-asset dependence means “5/5” should not be read as five independent replications.
- Wording that SPY/IWM are “accounted for” by calendar-window length is somewhat causal for a regression control. `README.md:328` provides the appropriately qualified version: they become insignificant after one reasonable proxy control.
- The headline’s “0 of 25” includes the non-calendar `always_overnight` control. The formal H3 verdict code evaluates 20 actual calendar-rule combinations at `k1813.py:1074-1082`; both counts yield zero winners, but the denominator should be named consistently.
- H1a is well supported. H1b is correctly reported as failure to reject, with its limited precision explicitly acknowledged at `README.md:333`.

```json
{
  "kid": "k1813",
  "verdict": "FAIL",
  "reviewer": "codex/gpt-5 (high)",
  "reviewed_at": "2026-08-02T08:44:11Z",
  "reviewed_commit": "7a41cb362",
  "review_artifact": "experiments/k1813/codex_review.md",
  "blocking_defects": [
    "The purported buy-and-hold benchmark adds overnight and intraday simple returns instead of compounding them, so the benchmark, equity curve, and H3 delta-Sharpe comparisons are not based on an actual buy-and-hold return.",
    "The README overstates an underpowered failure to reject as evidence that the tradable weekday effect does not exist; the observed bootstrap standard errors cannot exclude moderate positive delta-Sharpe effects."
  ],
  "reviewed_sha256": {
    "K1813_results.json": "6b29611d346afb29188a95f49789cfc4d07ea2a40b4f848e904648af82b69382",
    "README.md": "667604cbc6ddea83a1324025e38c8c9f020c11a9c9efbecfdaa707b6e14715ba",
    "figures/fig_acf_segments.png": "c54a6ba7bf907bae5e23cc25507ba75e06fe016d8462e985342e35ad9534218a",
    "figures/fig_cost_sensitivity.png": "9b45ab69f0a1b9963d725718af30b71d6c06a450b6c1074f56015b077ce67769",
    "figures/fig_equity_curves.png": "55d602315636457c0b33f830a3a4d0d929b0d7952e31d2a5ae74a54f32bf9de8",
    "figures/fig_weekday_bars.png": "08abc5e7bf634f4398a08f042095f27cdf32904b1b63ad7d17af3febf70b1f08",
    "k1813.py": "a9e19bc27714c0bf5b1f95c590cc5755eef7f6f849d13ac1532bb7aed68a0f0b"
  }
}
```
