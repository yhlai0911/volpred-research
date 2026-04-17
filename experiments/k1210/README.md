# K1210 — Forensic AU below-ladder residual: test H1 (cadence) vs H2 (precision)

> **TL;DR**: K1171 reported AU θ_rel=0.150 (second-lowest in N=13 ladder)
> at inst_pct=0.368 (mid-ladder, expected θ_rel≈0.3–0.4). K1207 showed
> sector adjustment *amplifies* AU residual by −31% — sector is NOT the
> driver. K1171 left two hypotheses on the table: **H1** semi-annual
> reporting cadence vs **H2** HAND_CODED ±1-day date imprecision.
>
> K1210 runs three fair-comparison pooled-MLE experiments on the same
> 10-stock ASX Top 10 panel, same 216 HAND_CODED events, same GJR(1,1)+
> VIX²+EAV MIDAS spec as K1171.
>
> **Headline verdicts**:
>
> | Hypothesis | Verdict | Key statistic |
> |---|---|---|
> | H1 semi-annual cadence | **REJECTED_FLAT** | Δθ_rel = +0.00008 (+0.05%) when 206 synthetic quarterly events injected at midpoints |
> | H2 HAND_CODED precision | **SUPPORTED (strong)** | Jitter ±3 tdays SD/mean = **1.07** (σ=0.160 vs baseline 0.150); 2/2 yfinance comparisons differ by 2 days |
> | C stock-driven | **STOCK_DRIVEN (extreme)** | Drop-BHP raises θ_rel by **+1.22** (0.150 → 1.369); 6 of 10 drops raise θ_rel by ≥0.3 |
>
> **Root cause commitment: `H2_ONLY+STOCK_DRIVEN`** — but with a more
> consequential side finding: the **pooled MLE shared θ_EAV is
> numerically unstable** for the AU sample. Per-stock individual
> θ_EAVs average ~1.8e−4 (BHP 3.08e−4, CSL 3.32e−4, RIO 4.60e−4) yet
> the pooled shared θ_EAV is 3.16e−5 — an order of magnitude lower
> than the per-stock mean. Jitter seeds 49 and 52 jump to θ_rel 0.42
> and 0.61; drop-1 LOO shifts are 0.01–1.22 across stocks. Multiple
> signals indicate the pooled MLE for AU is near a pathological basin.
>
> **Paper 2 §5 AU footnote recommendation** (rewrite — see §7):
> AU's below-ladder reading in K1171 is **numerically fragile** and
> should NOT be cited as a structural residual. The pooled MLE for AU
> collapses to a local minimum at θ_EAV ≈ 3e−5 that is inconsistent
> with per-stock estimates (~1.8e−4 mean) and is highly sensitive to
> event-date precision (jitter SD/mean = 107%). AU should be tagged as
> **INCONCLUSIVE** in the N=13 panel, not as a "below-ladder developed-
> market residual". This does NOT invalidate the K1171 Spearman
> weakening (N=13 ρ=+0.385 vs N=12 ρ=+0.441) — AU's θ_rel just has
> wider error bars than K1171 acknowledged.

[提出: K1171 residual forensic backlog (K1171 §6.1, K1207 AU exception), 執行: Claude worktree agent]

**Random seed**: 42 (global) + 43..52 (10 jitter replicates)
**Data sources**: K1171 data/ cache (re-used, no new fetch)
**Runtime**: 30.4s on M1 Max (numba-cached from K1171)
**Sample**: 10 ASX Top 10 stocks × 3036 trading days × 216 HAND_CODED events

---

## 1. 動機（Why）

K1171 (N=13 cross-market ladder extension) identified AU as a
**below-ladder residual**: at institutions_pct=0.368 (mid-ladder), AU
should sit at θ_rel ≈ 0.3–0.4 under the developed-market pattern
(TW=0.17, EU=0.14, JP=0.39, US=0.59), but AU lands at **θ_rel=0.150**
— second-lowest in N=13 (only EU at 0.14 is lower).

K1171 §6.1 listed four candidate mechanisms:
1. Sector composition (5 banks + 2 miners in ASX Top 10 — tested and
   **rejected** by K1207; sector adjustment *amplifies* AU residual
   by −31%).
2. Semi-annual reporting cadence (vs quarterly in US/BR/MX/IN → fewer
   EAV events per year → estimation-noise channel).
3. HAND_CODED ±1-day precision (curated IR-archive dates may be
   trading-day-precise for majors but drift for mid-cycle reports).
4. AUD FX noise (out of K1210 scope; future K).

This experiment adjudicates (2) vs (3) head-to-head, plus a drop-stock
LOO diagnostic to check if a single stock drives the pooled fit.

---

## 2. 方法（Method）

All three experiments re-use the exact K1171 spec (fair comparison):
GJR(1,1) + VIX²_{t−1} + EAV_{i,t−1} MIDAS, 6 free params per stock,
shared θ0/θ_VIX/θ_EAV across stocks in pooled MLE with stock-FE
α/γ/β. Hessian SE via finite-difference on θ_EAV. ≥15 events + ≥500
obs filter. All EAV lagged t−1 inside `_pooled_negll` (lookahead
clean).

**Code re-use**: K1210 imports `k1171_per_stock_refit.fit_pooled_market`
and `build_eav` directly to guarantee spec identity. No parameter
drift, no re-tuning.

### 2.1 Exp A — semi-annual vs synthetic-quarterly

- **Baseline**: 216 K1171 HAND_CODED events (~22 per ticker, every
  ~6 months).
- **Synthetic quarterly**: for each ticker, insert midpoint events
  between consecutive originals, snapped to nearest trading day, with
  ±1-day collision avoidance. Result: 422 events (206 synthetic +
  216 original), approximating quarterly cadence.
- **Design note (critical)**: synthetic events carry **zero real
  information** (they are mechanical midpoints, not actual earnings).
  This test is a **H1 REJECTION probe**: if cadence alone drove
  θ_rel down via estimation sparsity, adding more (even zero-info)
  EAV=1 days would *not* lift θ_rel. If θ_rel stays flat, H1
  (sparsity hypothesis) is rejected. If θ_rel rises dramatically,
  that is a MECHANICAL artefact of more zero-info days diluting σ²
  estimation, not H1 support.

### 2.2 Exp B — HAND_CODED precision

- **B1 yfinance compare**: fetch `Ticker(t).earnings_dates` for all
  10 AU tickers at run time. K1171 §3.1 noted coverage is weak
  (yfinance returns 0–3 events per ASX ticker). Match yfinance
  events to nearest HAND_CODED within ±10 days; record diff_days.
- **B2 Jitter sensitivity**: 10 replicates with seeds 43..52, each
  perturbing every event's trading-day position by uniform
  discrete ±3 trading days. Re-fit pooled MLE per replicate.
  If jitter SD is large fraction of baseline θ_rel, event-window
  contamination is first-order.

### 2.3 Exp C — drop-1 LOO

For each of 10 AU stocks, drop it from the panel and re-fit pooled
MLE on the remaining 9. Record θ_rel delta from baseline.

### 2.4 Verdict thresholds

- **H1 SUPPORTED** if synthetic-quarterly θ_rel rises ≥30% AND
  outside jitter SE.
- **H1 REJECTED_FLAT** if |Δθ_rel / baseline| < 10%.
- **H2 SUPPORTED** if (a) ≥50% yfinance-vs-HAND_CODED matches differ
  by ≥1 day OR (b) jitter SD/mean ≥ 20%.
- **C STOCK_DRIVEN** if any single drop shifts θ_rel by ≥0.10
  absolute.

---

## 3. 結果（Results）

### 3.1 Exp A — cadence (H1 test)

| Cadence | N events | pooled θ_EAV | θ_EAV t | θ_rel |
|---|---|---|---|---|
| Semi-annual (K1171 baseline) | 216 | 3.164e−5 | +2.40 | **0.1498** |
| Synthetic quarterly | 422 | 3.165e−5 | +2.72 | **0.1499** |
| Δ | +206 | +2e−9 | +0.32 | **+0.00008 (+0.05%)** |

- θ_rel moved by 0.05% when event count nearly doubled. **H1
  SEMI-ANNUAL SPARSITY HYPOTHESIS: REJECTED_FLAT**.
- The t-stat went up (+2.40 → +2.72) because more zero-info EAV=1
  days slightly tighten the Hessian SE, but the point estimate did
  not move. Cadence is not the driver.

### 3.2 Exp B — precision (H2 test)

**B1 yfinance coverage** (2026-04-18 re-check, consistent with K1171
§3.1):

| Ticker | yfinance hits | Matched to HAND (±10d) | diff_days |
|---|---|---|---|
| BHP.AX | 1 | 1 | **−2** (yfinance 2023-02-19 vs HAND 2023-02-21) |
| WBC.AX | 1 | 1 | **−2** (yfinance 2022-11-05 vs HAND 2022-11-07) |
| NAB.AX | 1 | 0 | >10d diff (filtered) |
| ANZ, CBA, CSL, MQG, RIO, TLS, WES | 0 | 0 | — |

- Only 2/216 events have yfinance cross-reference; both differ by 2
  trading days. Sample too small for a definitive H2 yfinance signal
  alone, but **100% of comparable matches** are off by ≥1 day.

**B2 Jitter sensitivity** (10 replicates, ±3 trading days):

| rep | seed | θ_rel | θ_EAV |
|---|---|---|---|
| 1 | 43 | 0.1468 | 3.10e−5 |
| 2 | 44 | 0.1501 | 3.17e−5 |
| 3 | 45 | 0.1504 | 3.18e−5 |
| 4 | 46 | 0.1467 | 3.10e−5 |
| 5 | 47 | 0.1537 | 3.25e−5 |
| 6 | 48 | 0.1459 | 3.08e−5 |
| 7 | 49 | **0.4189** | **8.85e−5** |
| 8 | 50 | 0.1451 | 3.07e−5 |
| 9 | 51 | 0.1456 | 3.07e−5 |
| 10 | 52 | **0.6052** | **1.28e−4** |

- Mean 0.221, SD 0.160. **SD/mean = 72%**; SD/baseline = **107%**.
- 8/10 replicates stay near baseline (0.145–0.154, SD within those
  8 = 0.003); **2/10 jump to 0.42 / 0.61** (seeds 49, 52).
- The bimodal distribution is the key diagnostic: random ±3-day
  perturbation occasionally **escapes the pooled-MLE local basin**
  and lands near a higher-θ_EAV mode consistent with the per-stock
  individual MLE mean (~1.8e−4 → θ_rel ≈ 0.85).
- **H2 SUPPORTED — but mechanism is stronger than K1171 envisioned**:
  the ±1-day concern is real, and moreover it reveals that the
  pooled MLE has **multiple local minima** for AU.

### 3.3 Exp C — drop-1 LOO

| Dropped | θ_EAV | θ_EAV t | θ_rel | Δ from baseline |
|---|---|---|---|---|
| (none = baseline) | 3.16e−5 | +2.40 | **0.1498** | — |
| BHP.AX | 2.74e−4 | +5.46 | **1.369** | **+1.219** |
| RIO.AX | 2.25e−4 | +5.44 | **1.102** | **+0.953** |
| TLS.AX | 2.21e−4 | +6.18 | **1.004** | **+0.854** |
| MQG.AX | 1.69e−4 | +5.73 | **0.817** | **+0.667** |
| NAB.AX | 1.04e−4 | +4.75 | **0.486** | **+0.336** |
| ANZ.AX | 9.88e−5 | +4.53 | **0.466** | **+0.316** |
| CBA.AX | 3.48e−5 | +2.48 | 0.162 | +0.012 |
| WBC.AX | 3.43e−5 | +2.34 | 0.162 | +0.012 |
| WES.AX | 3.20e−5 | +2.25 | 0.147 | −0.003 |
| CSL.AX | 2.57e−5 | +2.06 | 0.122 | −0.027 |

- **Six of ten drops shift θ_rel by ≥ 0.3 absolute** — the "single
  stock" framing is too narrow. The pool does not have one outlier
  stock; it has a pathological pooled-MLE solution.
- Drop-BHP shifts θ_rel to **1.37** — above MX (1.20) and near IN
  (1.17). In other words, **the AU panel can move from second-
  lowest to third-highest in the N=13 ladder by dropping one
  stock**.
- Verdict: **C_STOCK_DRIVEN**, but with the deeper signal that **the
  baseline pooled fit is in a degenerate basin**.

### 3.4 Cross-check — per-stock vs pooled θ_EAV

Using K1171's per-stock MLE (exported in
`k1171_per_stock_table_newmkts.csv`, 10 AU rows):

| Stock | Per-stock θ_EAV | Per-stock t |
|---|---|---|
| BHP | 3.077e−4 | +2.40 |
| CSL | 3.321e−4 | +1.56 |
| NAB | 1.222e−4 | +1.78 |
| ANZ | 7.858e−5 | +1.93 |
| WBC | 8.871e−5 | +2.01 |
| WES | 1.047e−3 | — (params_at_bound) |
| MQG | 1.105e−4 | +1.74 |
| TLS | 5.44e−5 | +0.60 |
| RIO | 4.596e−4 | +2.49 |
| CBA | 8.846e−5 | +0.61 |

- Mean per-stock θ_EAV (ex-WES which hit bound) = **1.81e−4**.
- Pooled θ_EAV = **3.16e−5** (≈ 6× lower than per-stock mean).
- Standard pooled MLE with iid shocks should produce a precision-
  weighted mean of individual estimates. The 6× gap is a strong
  sign the pooled likelihood surface has a second (lower-θ) basin
  that the optimizer found for the full 10-stock panel but not for
  9-stock subpanels where it escapes.

---

## 4. Verdict breakdown

| Test | Threshold | Observed | Verdict |
|---|---|---|---|
| H1 synthetic-quarterly θ_rel uplift | Δ ≥ +30% | +0.05% | **H1 REJECTED_FLAT** |
| H2 yfinance ≥1d diff | ≥ 50% of matches | 100% of 2 matches | borderline (low n) |
| H2 jitter SD/mean | ≥ 20% | **72%** (107% vs baseline) | **H2 SUPPORTED** |
| C drop-1 Δ | ≥ 0.10 absolute | **1.22 (BHP)**, 6/10 ≥ 0.30 | **C_STOCK_DRIVEN** |

**Combined**: `H2_ONLY+STOCK_DRIVEN`, escalated to **NUMERICAL_
FRAGILITY** given the per-stock vs pooled gap.

---

## 5. Interpretation

### 5.1 H1 is cleanly rejected

Doubling the event count via synthetic midpoints does not move θ_rel.
The cadence story in K1171 §6.1 bullet #2 was plausible a priori but
is not empirically supported. The semi-annual-vs-quarterly distinction
is a **counting** artefact, not an estimation-noise artefact — EU
reports quarterly and sits at θ_rel=0.14 (same as AU), so cadence
alone cannot explain where a market lands on the ladder.

### 5.2 H2 is supported, but the deeper issue is pooled-MLE stability

The ±3-day jitter test was intended to bound HAND_CODED precision
bias within a narrow range around 0.150. Instead, it revealed a
bimodal θ_rel distribution: 8/10 replicates stay within 0.003 of
baseline, 2/10 jump ×3–4. This is not a precision-sensitivity
pattern; it's a **multi-basin likelihood** pattern.

Combined with the per-stock vs pooled gap (1.8e−4 vs 3.2e−5) and
drop-1 LOO showing 6/10 drops lift θ_rel by ≥0.3, the evidence points
to the AU pooled MLE being trapped in a secondary local minimum at
θ_EAV ≈ 3e−5 — a value that is internally consistent within the
likelihood at the full 10-stock panel but is discontinuously different
from every perturbation of the panel (drop 1 stock → pool escapes;
jitter ±3 days → ~20% chance of escape).

### 5.3 Why did K1171 not catch this?

K1171 ran one pooled fit at seed 42, inspected the per-stock table
separately, and did not cross-check the per-stock mean against the
pooled shared parameter. The multi-start per-stock MLE used 4 initial
points; the pooled MLE used a single `x0`. A pooled multi-start
procedure would likely have found the θ_EAV ≈ 1.8e−4 basin.

### 5.4 Implication for K1207 AU amplification

K1207 found sector adjustment *amplifies* AU residual by −31%.
Re-reading that result with K1210 in hand: K1207 used the same K1171
pooled θ_EAV=3.16e−5 as input, so its "AU residual" was fitted
against a numerically fragile starting point. The K1207 conclusion
"AU is not sector-explained" still holds mechanically — sector FE
acting on a fragile pooled estimate gives a fragile sector-adjusted
estimate — but the magnitude (−31% amplification) should be
interpreted with the same wider error bars.

### 5.5 Implication for K1171 cross-market Spearman

K1171 N=13 ρ=+0.385, p=0.194 used AU θ_rel=0.150 as the 13th point.
If AU's θ_rel is actually ≈ 0.85 (consistent with per-stock mean and
drop-BHP LOO), the Spearman changes. Rough sensitivity: placing AU at
θ_rel=0.85 (between BR 1.89 and CA 1.45) at inst_pct rank 7 would
*slightly weaken* the ladder (BR, AU, CA, US all high at high-mid inst
ranks). **Paper 2 §5 claim** that AU is "a below-ladder developed-
market residual" is not safe.

---

## 6. Limitations

1. **Single seed base for pooled MLE**: pooled MLE in K1171 (and
   hence the 0.150 baseline) was one-shot at seed 42. A multi-start
   pooled refit of AU is the obvious next experiment (K1211 proposed).
2. **Jitter test is a proxy for precision**: ±3 trading-day jitter is
   coarser than the real HAND_CODED uncertainty (expected ≤ ±1 day).
   A tighter ±1-day jitter might show smaller but still material SD.
3. **Synthetic-quarterly caveat**: midpoints are zero-info; the flat
   result rules out *pure sparsity* effect but cannot rule out a
   *structural* cadence effect (e.g., US analysts update forecasts
   at Q2/Q4 only vs AU all-year). Full test would require a
   quarterly-reporting-only AU panel, which does not exist.
4. **yfinance n=2 matches**: both off by 2 days, but sample too small
   to claim H2 yfinance evidence as primary.
5. **Spec inherited from K1171**: no re-examination of whether
   GJR(1,1)+VIX²+EAV MIDAS is the right model; constant-spec fair-
   comparison discipline takes priority.
6. **WES params_at_bound**: per-stock WES hit a bound in K1171; this
   may contribute to pooled-MLE pathology.

---

## 7. Paper 2 §5 recommendation

Replace K1171's "AU below-ladder residual" language with:

> *AU's pooled θ_EAV estimate is numerically sensitive to event-date
> perturbations and panel composition. A ±3-trading-day jitter of the
> 216 HAND_CODED release dates yields θ_rel standard deviation of
> 107% (SD 0.160 vs baseline 0.150); leave-one-out of individual
> stocks shifts θ_rel by up to +1.22 absolute. The ASX panel's per-
> stock mean θ_EAV (1.8 × 10⁻⁴) is six times the pooled shared-
> parameter estimate (3.2 × 10⁻⁵), consistent with the pooled MLE
> sitting in a secondary local minimum. We therefore report AU as
> **inconclusive** in the N=13 institutional-ownership ladder rather
> than as a below-ladder residual. The N=13 Spearman rank correlation
> (+0.385, p=0.194) is reported with this caveat.*

This is the honest reading and aligns with the research-honesty
principle (CLAUDE.md §10 "不可過度宣稱").

---

## 8. 檢定表（Preamble Rule #5）

| Check | Status |
|---|---|
| Mechanical vs empirical | Empirical — actual pooled MLE fits, not construction |
| Tautology? | No — tests independent hypotheses against shared data |
| ρ > 0.95 / t > 10? | No — max LOO t = +6.18 (below Harvey > 8 over-suspicion line); jitter shows INSTABILITY not inflation |
| Sharpe > 2× baseline? | N/A |
| Sample size | 10 stocks × 216 events = adequate for pooled MLE sensitivity tests |
| Result strength vs evidence | Conservative — downgrades K1171 claim, not upgrades |
| Seed discipline | Base 42 + 10 reps 43–52 (fixed) |
| Lookahead | Inherited K1171 spec; EAV_{t−1} shifted |

---

## 9. Files

- `k1210.py` — main driver (exp A/B/C + verdict + figures).
- `k1210_results.json` — aggregated results + verdict.
- `k1210_expA_quarterly.csv` — semi-annual vs synthetic-quarterly.
- `k1210_expB_jitter.csv` — 10-replicate jitter θ_rel distribution.
- `k1210_expB_yfinance_cmp.csv` — yfinance-vs-HAND diff_days.
- `k1210_expC_loo.csv` — drop-1 LOO table.
- `k1210_figA_cadence.png` — bar semi-annual vs synthetic quarterly.
- `k1210_figB_jitter.png` — jitter distribution with baseline marker.
- `run.log` — execution log (reproducible: `uv run python k1210.py`).

Reads (not copied):
- `/experiments/k1171/data/*.parquet, *.json` — prices, VIX, earnings.
- `/experiments/k1171/k1171_asx_earnings_dates.csv` — 216 HAND_CODED.
- `/experiments/k1171/k1171_per_stock_refit.py` — MLE primitives.

---

## 10. References

- Engle, R.F., Ghysels, E., Sohn, B. (2013). *Stock market volatility
  and macroeconomic fundamentals*. **RES** 95(3), 776–797.
- Harvey, C.R., Liu, Y., Zhu, H. (2016). *… and the cross-section of
  expected returns*. **RFS** 29(1), 5–68.
- Patton, A.J. (2011). *Volatility forecast comparison using imperfect
  volatility proxies*. **JoE** 160(1), 246–256.
- Bartram, S.M., Brown, G.W., Stulz, R.M. (2012). *Why are U.S.
  stocks more volatile?* **JF** 67(4), 1329–1370.

---

## 11. Related K

- **K1171**: N=13 cross-market extension with HAND_CODED AU earnings;
  reported AU θ_rel=0.150 as below-ladder residual. K1210
  downgrades this claim to INCONCLUSIVE due to pooled-MLE fragility.
- **K1207**: sector adjustment for AU/EM residuals; found sector
  amplifies AU −31%. K1210 inherits fragile pooled input —
  re-interpretation applies (§5.4).
- **K1211 (proposed)**: multi-start pooled MLE for AU (5–10 starts
  from different θ_EAV initializations) to map the likelihood surface
  and identify the dominant basin.
- **K1212 (proposed)**: tighter ±1-day jitter (vs K1210's ±3) to
  isolate precision-only sensitivity.
- **K1213 (proposed)**: re-run K1171 cross-market Spearman with AU
  replaced by per-stock mean θ_EAV / mean σ² (simple-average rather
  than pooled MLE) as robustness.
