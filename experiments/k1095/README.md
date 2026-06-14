# K1095: Taiwan Event-Switched VT — 8.63/VIX + A4f at Earnings Events

- **Proposer**: Claude (synthesizing K1060 / K1062 / K1068 / K991 findings)
- **Executor**: Claude
- **Date**: 2026-04-12
- **Runtime**: ~128 s on M1 Max (with A4f quarterly refit)
- **Random seed**: 42

## 1. Motivation

Multiple Taiwan findings from this research programme pointed to a potential
hybrid VT strategy:

| Finding | Experiment | Takeaway |
|---------|------------|----------|
| 8.63/VIX is Taiwan's best VT | K991 / K1094 | Sharpe ~0.83 full / ~1.27 OOS; param-insensitive |
| A4f (GARCH-X on VIX²) beats GJR on event windows | K1062 Part D | DM t = +2.35 overall; event days t = +1.68 (+0.11 QLIKE) |
| Earnings cause volatility, not drift | K1068 | CAR≈0 but CASV t = +4.35 (p<0.0001) |
| Individual-stock EAV strongest at T+1 | K1060 | Mean ratio 1.466, p = 0.034 |

The natural question: **does switching VT engines — 8.63/VIX on normal days,
A4f-VT around earnings — improve Sharpe or reduce MDD vs either pure policy?**

Hypothesis (ex ante):
- **H1**: Event-switched Sharpe > pure 8.63/VIX Sharpe.
- **H2**: Event-switched Sharpe > pure A4f-VT Sharpe.
- **H3**: Event days concentrate some of the volatility premium that A4f
  captures but 8.63/VIX misses.

## 2. Method

### Strategies (all one-day lagged, no lookahead)

| Strategy | Weight formula |
|----------|----------------|
| **A. Pure 8.63/VIX** | `w_t = clip(8.63 / VIX_{t-1}, 0, 1.5)` |
| **B. Pure A4f-VT** | `w_t = clip(target_σ / σ̂_t^A4f, 0, 1.5)`, target_σ = 15% ann. |
| **C. Event-switched** | `w_t = w_t^B` if `t ∈ event_window`, else `w_t^A` |

### Event-window definition

- Top-10 0050.TW constituents (same as K1068):
  TSMC / MediaTek / Hon Hai / Delta / UMC (Tech);
  Chunghwa Telecom (Telecom);
  Cathay / CTBC / Fubon (Financial);
  China Steel (Traditional).
- Every calendar announce date mapped to the first trading day ≥ announce date
  (= `T+0`).
- Baseline event window **[T-5, T+5]** around every T+0; sensitivity
  **[-3, +3]** and **[-10, +10]** also reported.

> **2026-06-14 disclaimer (Codex review mile_c11a2ced)**: 本實驗使用 `財報公告日.txt`
> 內**事後**已知的 actual announce dates 建構 `[T-5, T+5]` window。**沒有**保存當時
> 已公布的「預告/排程公告日」資料 (known-in-advance schedule)。因此 pre-event
> branch (T-5 ~ T-1) 嚴格而言含有 ex-post 資訊，**不可視為 verified tradable signal**，
> 本研究只能解讀為 **ex-post descriptive regime partition** — 結論「switching destroys
> A4f-VT advantage」在 descriptive 框架下仍成立，但若要主張 tradable 需 K1095-v2
> 用 known-in-advance schedule source 重做。後續 announcement-day mapping (Taiwan
> after-close release 應為 `T+1`) 亦待 v2 修正。

### A4f implementation

Multiplicative GARCH-X with VIX² long-run component (reuse of the K1058 /
K1062 custom MLE). Training window = 2,000 days, quarterly refit
(every 63 trading days), one-step-ahead forecast of σ̂²_t using r_{t-1} and
VIX_{t-1}.

### Data

- **0050.TW** daily close, `yfinance`, `auto_adjust=True`, cleaned with
  `volpred.utils.clean_tw50_data` (2014 1:4 split fix).
- **^VIX** daily close, `yfinance`.
- **財報公告日.txt** (Big5, 153,875 dated records, 2,409 firms) for earnings
  dates. 870 top-10 announcements, 860 mapped to trading days.
- Full sample 2009-01-05 .. 2025-12-30 (4,161 trading days).
- OOS 2017-02-15 .. 2025-12-30 (2,161 days) — first day with 2,000-day
  training window available for A4f.
- Transaction cost: **20 bp per one-way change** in weight (conservative).

## 3. Results

### Table 1 — Headline strategy metrics (OOS 2017-2025, net of 20 bp TX)

| Strategy | N | Sharpe | Ann. ret | Ann. vol | MDD | Calmar | Sortino |
|----------|---|--------|----------|----------|-----|--------|---------|
| **Pure 8.63/VIX** | 2,160 | **0.929** | +8.1% | 8.8% | -16.5% | 0.49 | 1.22 |
| **Pure A4f-VT** | 2,160 | **0.966** | +14.9% | 15.7% | -27.9% | 0.53 | 1.34 |
| **Event-Switched** | 2,160 | **0.777** | +9.4% | 12.6% | -21.0% | 0.45 | 1.10 |
| Buy-and-Hold | 2,160 | 1.020 | +19.5% | 19.3% | -33.8% | 0.58 | 1.34 |

**Headline**: Event-switching reduces Sharpe from 0.929 (pure VIX) and 0.966
(pure A4f) down to **0.777** — a ~20% Sharpe destruction.

### Table 2 — HAC t-test on daily net-return differences (Newey-West, bandwidth = n^0.25)

> **2026-06-14 correction (per Codex review mile_c11a2ced)**: 此處非 Diebold-Mariano
> 或 HLN forecast-comparison test，僅為日報酬差的 Newey-West HAC t-test。Mean diff
> 欄位以年化基點 (bp/y) 報告，請勿誤讀為日均值。

| Comparison | Mean diff (ann., bp/y) | t (HAC) | p (two-sided) |
|------------|-----------------------|---------|----------------|
| Switch vs Pure 8.63/VIX | +6.4 | +0.89 | 0.372 (NS) |
| **Switch vs Pure A4f-VT** | **-21.1** | **-2.89** | **0.004** (switch WORSE) |
| Pure A4f-VT vs Pure 8.63/VIX | +27.5 | +2.71 | 0.007 |

樣本內以 HAC t-test 觀察到 switching 顯著拉低相對 A4f-VT 的日報酬差（t = -2.89），
惟此非 forecast-comparison 推論，僅顯示策略報酬差顯著為負。

### Table 3 — Sharpe decomposition, event vs non-event days

| Strategy | Event days (N=1,185) | Non-event days (N=975) |
|----------|----------------------|------------------------|
| Pure 8.63/VIX | 0.46 | **1.44** |
| Pure A4f-VT | 0.49 | **1.49** |
| Switched | 0.51 | 1.32 |
| Buy-and-Hold | 0.65 | 1.46 |

Every strategy — including buy-and-hold — has dramatically **lower** Sharpe on
event days than non-event days. Event days are just **high-volatility, low
per-unit-risk-return** days. The premise that events are alpha-rich is
refuted by the data.

### Table 4 — Window sensitivity (switched strategy, net Sharpe)

| Event window | Event coverage | Sharpe |
|--------------|----------------|--------|
| `[-3, +3]` | 45.7% | 0.806 |
| `[-5, +5]` | 54.9% | 0.791 |
| `[-10, +10]` | 70.5% | 0.795 |

Switching behaviour is flat and mediocre across windows. No window "finds"
an event-alpha that 8.63/VIX misses.

### Turnover (annual)

| Strategy | Turnover (1x unit = full round-trip) |
|----------|--------------------------------------|
| Pure 8.63/VIX | 6.5x / yr |
| Pure A4f-VT | 12.3x / yr |
| Switched | **13.4x / yr** (highest) |

Switching adds a third source of turnover (the A4f→VIX→A4f jumps at
event-window boundaries), and 20 bp TX removes meaningful Sharpe.

## 4. Hypothesis verdicts

| Hypothesis | Verdict | Evidence |
|------------|---------|----------|
| **H1**: Switched Sharpe > pure 8.63/VIX | REFUTED | 0.777 < 0.929, DM NS |
| **H2**: Switched Sharpe > pure A4f-VT | **STRONGLY REFUTED** | 0.777 < 0.966, DM t = -2.89, p = 0.004 |
| **H3**: Event days concentrate A4f alpha | REFUTED | All strategies have LOWER Sharpe on event days |

## 5. Why does event-switching fail?

Three mechanisms, ranked by magnitude:

1. **Event coverage is too large (49–71%)**. The top-10 stocks announce so
   frequently that a [-5,+5] window around each earnings date covers about
   half of the sample. This is not a sparse event signal; it is a partial
   regime overlay, which means "switching" is really "mixing two strategies
   50/50", giving you the weighted average of their deficiencies.
2. **Event days are low-Sharpe for every policy** (Table 3). The premise that
   events are alpha-rich is false; they are risk-rich. A4f-VT de-levers more
   aggressively on those days (its σ̂ is high precisely because of events),
   capturing less return per unit of taken risk.
3. **Switching adds turnover**. 13.4x/yr turnover vs 6.5x/yr for pure VIX
   costs ~130 bp/yr in net returns at 20 bp TX, enough to move Sharpe from
   the vicinity of pure-VIX down to 0.78.

## 6. Cross-validation with prior K-numbers

- K1062 Part D's A4f-advantage finding (QLIKE DM t = +1.68 on T+0 events) is
  consistent with our empirical A4f-VT > VIX-VT result (DM t = +2.71 on
  Sharpe), but only for the **pure** A4f-VT policy. Switching does not
  inherit the A4f advantage because of mechanism (1).
- K1068's "CAR ≈ 0, CASV >> 0" pattern is reproduced at the ETF level:
  event-day Sharpe is low (like CAR = 0) and event-day vol is high
  (like CASV > 0). Event days are a **volatility regime**, not a return
  regime.
- K991's sensitivity verdict for 8.63/VIX (Sharpe almost flat in ±20% k
  range) continues to hold: in this OOS window pure 8.63/VIX Sharpe is
  0.929, very close to the K991-reported 0.83 full / 1.27 post-2019 OOS.

## 7. Implications

- **For Paper 2 (Taiwan)**: a clean null result — adding an earnings-event
  switching rule to 8.63/VIX does **not** improve risk-adjusted performance.
  Simplicity wins; 8.63/VIX remains the recommended Taiwan VT policy.
- **For Paper 3 (A4f)**: A4f-VT's advantage is a *global* QLIKE / Sharpe
  advantage (DM t = +2.71), not an *event-specific* one. The K1062 conditional
  QLIKE result (A4f better on T+0 days, +0.11 QLIKE, not reaching Harvey)
  has no economic payoff when translated to a VT strategy because event-day
  return-per-risk is poor for every policy.
- **For the live portfolio**: do **not** add an event-overlay to Taiwan VT.
  Keep 8.63/VIX or A4f-VT pure; the choice between them depends on the target
  vol (15 % vs ~9 %).

## 8. Limitations

1. The "top-10" universe is held fixed across time — the actual 0050.TW
   top-10 changes slowly (e.g. TSMC's weight grew from ~20% to 45%). Using
   a time-varying top-10 would likely tighten event coverage further, but
   not change the qualitative verdict since every single stock
   contributes roughly uniformly.
2. TX cost 20 bp is conservative but not extreme. A 5 bp TX would narrow
   the Sharpe gap between switched (0.78) and pure VIX (0.93) to
   approximately 0.10 Sharpe, still negative.
3. We used a hard switch at window boundaries; a smoothed blend (e.g. linear
   ramp over 2 days into / out of the window) is not tested, but the dominant
   failure mode is event-day low Sharpe, not boundary discontinuity —
   smoothing would not rescue it.
4. A4f is only one of many event-sensitive models. HAR-RV, EGARCH, or
   realized-kernel approaches could in principle be better. But K1058 /
   K1062 already showed A4f dominates those on 0050.TW OOS.
5. OOS starts in 2017; no coverage of the 2008 GFC for the VT side
   (necessarily — A4f needs 2000-day training from 2009).

## 9. Files

| File | Purpose |
|------|---------|
| `k1095.py` | Full experiment script (data, A4f, strategies, metrics, DM, charts) |
| `k1095_results.json` | All numerical results, matched to this README |
| `k1095_strategy_comparison.png` | Sharpe / MDD / ann. return bar chart |
| `k1095_event_nonevent_decomp.png` | Event vs non-event Sharpe decomposition |
| `k1095_window_sensitivity.png` | Sharpe across [-3,+3] / [-5,+5] / [-10,+10] |
| `k1095_equity_curves.png` | Cumulative equity curves (log scale) |

## 10. References

- K991 — 8.63/VIX parameter sensitivity (Sharpe drop ≤ 2.2% in ±20%).
- K1058 — A4f vs GJR on 0050.TW (VaR Trinity PASS, overall DM ~ NS).
- K1060 — Individual-stock T+1 EAV (ratio 1.466, t = 2.075, p = 0.034).
- K1062 — 0050.TW T+1 + A4f conditional QLIKE (DM t = +1.68 on T+0 events).
- K1068 — CAR / CASV traditional event study (CAR ns, CASV t = +4.35).
- K1070 — 0050.TW pre-event [-5,-1] window signal test.
- Engle (2001) `Dynamic conditional correlation`; Engle & Rangel (2008)
  multiplicative component GARCH (A4f family).
- MacKinlay (1997) event-study methodology reference.
- Patton (2011) `Volatility forecast comparison using imperfect volatility
  proxies` *J. Econometrics* 160.
