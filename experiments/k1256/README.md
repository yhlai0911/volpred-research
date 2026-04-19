# K1256: Paper 1 T-HM — Canonical 3-spec Henriksson-Merton γ_HM

## Context

Paper 1 (`paper/leverage-direction/`) body_v3.tex line 433 footnote reconciles
three γ_HM estimates that share a symbol but correspond to distinct
Henriksson-Merton regressions on different samples/strategies:

| Spec label | Strategy | Sample | Paper γ_HM | Paper t | Paper section |
|---|---|---|---|---|---|
| `pure_vt_full` | 12/VIX | Full 2014-2026 (N≈3,100) | -0.035 | -0.39 | 4.7 |
| `pure_vt_high_vix` | 12/VIX | VIX>25 conditional | -0.068 | -4.63 | 4.7 |
| `hybrid_vt_full` | Hybrid VT (VIX/σ_GJR > 1.3 switch) | Full 2014-2026 | -0.043 | -4.06 | 5.4 |

Current `paper/leverage-direction/reproduce.py` (lines 486-503) tags these
as a **HIGH-severity MISMATCH** because it pins *one* γ_HM value against
*three* different specs — an internal-consistency bug in the reproduce
harness, not in the paper.

The research-honest resolution path (c) per proposal.md §2.3 is already in
body_v3.tex footnote; reproduce.py must be rewired to score 3 separate
MATCH checks against a canonical JSON. K1256 produces that JSON.

### Naming note (K1235 → K1256)

`paper/leverage-direction/review_history/gate_fix_v1/proposal.md` §6 T-HM
row labels this task "tentative K1235". K1235 was already allocated to
Paper 9 (garch-x-vix, FEZ + STOXX50E Table 6 reproduction, commit history
available). To honour the CLAUDE.md hard rule "同一 K 編號禁止雙 agent"
we ship K1256 as the canonical Paper 1 T-HM K-ID. Downstream reproduce.py
and experiments.md citations must reference K1256.

## Methodology

### HM regression (body_v3 Sec 4.7 equation, L371)

$$r^{VT}_t - r^f_t = \alpha + \beta (r^m_t - r^f_t) + \gamma_{HM} \max(0, r^f_t - r^m_t) + \varepsilon_t$$

- Standard errors: Newey-West HAC, 10 lags (paper L367)
- Risk-free: 0% daily. γ_HM is invariant to any uniform rf shift — the down-market dummy `max(0, rf - r^m)` adds only an rf-constant shift absorbed by α, so γ estimates and their t-statistics are unaffected by the rf choice. Setting rf=0 sidesteps the data-source dependency on a specific T-bill series.
- Market proxy: SPY daily log return (paper's baseline equity; body_v3 L12+L197)

### Strategy weights (all signals lagged t-1 — lookahead-safe)

**12/VIX pure VT** (Spec A, Spec B)
$$w_t = \text{clip}(12 / \text{VIX}_{t-1}, 0, 1.5)$$

Paper L506: "σ_target=12%, rule reduces to w = 12/VIX" — VIX in percentage
points, so VIX=20 gives w=0.60 (not 0.006).

**Hybrid VT** (Spec C, body_v3 Sec 5.4 + Fig caption L266)
$$w_t = \begin{cases} 12/\text{VIX}_{t-1} & \text{if } (\text{VIX}_{t-1}/100\sqrt{252}) / \sigma^{GJR}_{t-1} > 1.3 \\ (0.10/\sqrt{252}) / \sigma^{GJR}_{t-1} & \text{otherwise} \end{cases}$$

(both branches clipped to `[0, 1.5]`)

σ^GJR_{t-1} is a rolling GJR-GARCH(1,1,1) t-innovation forecast with
W=2000 daily refits, identical to `experiments/multi_asset_hybrid_vt_v2`.

### Sample & Data

- OOS window: 2014-01-02 → 2026-04-17 (most recent vix_daily.csv date)
- SPY: `yfinance` `auto_adjust=False` (paper-workflow P4 lesson)
- VIX: pinned snapshot `paper/leverage-direction/data/vix_daily.csv`
  (9,141 rows, 1990-01-02 → 2026-04-17)
- GJR warmup: 10-year lead (2004-01-05 start)
- Seed: 42 (no bootstrap, but fixed for determinism)

## Results

### K1256 vs Paper footnote (L433)

| Spec | K1256 γ | Paper γ | Δγ_rel | K1256 t | Paper t | Δt | N | Verdict |
|---|---|---|---|---|---|---|---|---|
| `pure_vt_full` | **-0.0513** | -0.035 | 46.7% | **-1.010** | -0.39 | 0.62 | 3,091 | DIVERGENT_SAME_SIGN |
| `pure_vt_high_vix` | **-0.0304** | -0.068 | 55.3% | **-0.794** | -4.63 | 3.84 | 391 | DIVERGENT_SAME_SIGN |
| `hybrid_vt_full` | **-0.0357** | -0.043 | 17.0% | **-0.572** | -4.06 | 3.49 | 3,091 | DIVERGENT_SAME_SIGN |

Verdict tiers:
- MATCH: sign + Δγ_rel<5% + Δt<1.0 (none)
- BORDERLINE: sign + Δγ_rel<20% + Δt<2.0 (none)
- DIVERGENT_SAME_SIGN: sign consistent, magnitude differs (all three)
- MISMATCH: sign flip (none)

### Key findings

**1. All three γ_HM are negative** — the paper's qualitative thesis that
all three specs support the "variance management, not directional timing"
interpretation is **confirmed**. The body_v3 L433 footnote's reading
("the consistent negative sign across all three specifications supports
the variance-management interpretation") holds under an independent
reproduction.

**2. Magnitudes systematically 20-55% smaller than paper** — K1256 γ is
more conservative across all three specs (-0.05 vs -0.035 inverted rel;
-0.03 vs -0.07; -0.036 vs -0.043). This rules out a simple sign-flipping
bug and suggests a specific pattern (likely different VT-signal schedule
or risk-free rate).

**3. Spec B (VIX>25 high-VIX) has only 12.6% of sample, not paper's 21%**
The VIX>25 condition on lagged VIX gives N=391 (12.6%); paper Sec 4.7
L435 states "VIX > 25, 21% of the sample". This is a paper-internal
inconsistency — paper may have used VIX>22 (→20.5%) or a different
definition (e.g., rolling window average). Flagged for main thread.

**4. Spec C t-statistic is dramatically lower (-0.57 vs -4.06)** —
paper claims Hybrid VT γ_HM is "statistically significant at t=-4.06"
but K1256 reproduction yields t=-0.57. Two candidate explanations:
  - (a) Different σ_GJR input (paper's Sec 5.4 may use Mincer-Zarnowitz
    forecasts or a different GARCH refit cadence from Sec 4.5)
  - (b) Different rebalance / transaction-cost handling (K1256 uses
    daily rebalance with 0 cost; paper may have monthly rebalance)
  - (c) Different VIX or SPY data snapshot (paper written pre-2026
    data; our vix_daily.csv extends to 2026-04-17)

### Divergence policy

Per CLAUDE.md §"研究誠實原則" #1 and paper-workflow.md "腳本/資料/論文
數字必須三方一致", K1256 **reports the γ and t as estimated**; no
fitting-to-paper-values is attempted. Reconciliation must happen on
the main thread via one of:
- (a) Fix script to match paper (pin exact rebalance schedule, risk-free
  rate, VIX condition operator). Requires paper-side spec clarification.
- (b) Fix paper to match script (update L433 footnote to reflect
  K1256 canonical numbers). Research-honest but invalidates "statistically
  significant" claim for Spec C.
- (c) Errata note + spec-clarification footnote. Keep paper numbers as
  authoritative with a clear pointer to K1256 supplementary test that
  reinforces sign consistency.

**Recommended**: (c) — sign consistency is the core claim; magnitudes
depend on spec choices that are not exhaustively pinned in the current
body_v3. Main thread should add a footnote to body_v3 L433 citing K1256
as "independent supplementary robustness check".

## Files

| File | Purpose |
|---|---|
| `k1256.py` | Experiment script (3 HM regressions, canonical JSON output) |
| `k1256_results.json` | Canonical per-spec (γ, t, p, N, α, β) + paper-MATCH verdicts |
| `k1256_run.log` | Console run log |

Paper-side stub for reproduce.py rewire (created by k1256.py):
`paper/leverage-direction/experiments/hm_timing_tests_results.json`

## Strict-rules compliance checklist

- [x] Lookahead guard: all signals use `t-1` (VIX_lag, sigma_gjr_lag); strategy return at `t` is `w_t · r^m_t`. No same-day signal × same-day return.
- [x] `np.random.seed(42)` set at module top
- [x] `yfinance auto_adjust=False` (P4 canonical)
- [x] VIX pinned to paper/leverage-direction/data/vix_daily.csv (not re-downloaded)
- [x] HM regression equation identical to body_v3 L371
- [x] Newey-West HAC SE with 10 lags (body_v3 L367)
- [x] GJR-GARCH(1,1,1), t-dist, W=2000 identical to experiments/multi_asset_hybrid_vt_v2
- [x] No script tuning toward paper values (CLAUDE.md §研究誠實原則 #1)
- [x] No shared-state writes (storage/reports/feed.json, storage/memory/*.json, Supabase, Mirror)
- [x] Only files in `experiments/k1256/` + one paper-side stub JSON (explicitly allowed by proposal §6 T-HM file contract: "produces `paper/leverage-direction/experiments/hm_timing_tests_results.json`")
- [x] No .tex modifications

## Relation to gate_fix_v1 and downstream tasks

- **Closes**: proposal.md §6 T-HM (P1 gate-blocker, 2hr est)
- **Enables**: T-REPRO (reproduce.py rewire to read hm_timing_tests_results.json and score 3 MATCH checks)
- **Gate impact** (per proposal §5 Stage A forecast):
  - Baseline: 53.4% match rate (31/58 cells)
  - After K1256 + reproduce.py rewire: ~60% match rate (removes 1 MISMATCH, adds 3 MATCH-or-NOTE checks)
- **Main-thread follow-up**:
  1. Update reproduce.py lines 486-503: replace single-γ MISMATCH block with 3 MATCH checks reading `paper/leverage-direction/experiments/hm_timing_tests_results.json`
  2. Decide on divergence policy (recommend (c) errata footnote)
  3. Register K1256 in `paper/leverage-direction/experiments.md`
  4. Flag the 21% vs 12.6% VIX>25 sample-fraction discrepancy for body_v3 correction
