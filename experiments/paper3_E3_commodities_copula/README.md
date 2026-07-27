# Paper3_E3 — Copula-GARCH on Commodity × {Equity, Bond} Pairs

**Status:** ✅ SUCCEEDED (formal re-run of the arm that failed silently 2026-05-29)
**Date:** 2026-07-27
**Proposer:** Boss directive 2026-05-29 + synthesis §E3 decision `assign_f3419501` (2026-07-21)
**Source task:** `paper3_E3_commodities_copula_rerun_20260721` (P2 experiment)
**Author:** VolPred Research System (Claude, main-thread design + worktree execute)

---

## 1. Why this experiment exists (the adjudication charter)

Paper 3's reframe is **asset-class-specific copula advantage**. Two arms were done:

- **E1** (individual US stocks): NULL — no Harvey-significant Copula-GARCH advantage.
- **E2** (cross-market equity): NULL on copula advantage, BUT the *one* significant
  `λ_L → DM` scaling relationship carried the **opposite sign to the pre-registered
  H3**, did **not** replicate in E1, and the two arms were heterogeneous
  (Q = 8.805, p = 0.0030).

With only two **equity** arms, the synthesis could not separate *"H3 itself is wrong"*
from *"the E2 cross-market arm carries an arm-specific structure"*. A **third,
non-equity** asset class is diagnostic **in either direction**:

- reverse-sign scaling **replicates** in commodities → the reversal is a real,
  cross-asset-class finding;
- it does **not** replicate → the E2 reversal is **arm-specific**, and the pooled
  scaling story is not a stable asset-class law.

E3 failed **silently** on 2026-05-29 (no recorded reason, no partial artifact, 7 weeks
no retry), which left the downstream synthesis permanently blocked. This run closes
that gap under the **E2 skeleton** and the **E2 criterion**.

---

## 2. Design (E2 skeleton, verbatim numerical core)

`paper3_E3.py` is a direct adaptation of
`experiments/paper3_E2_cross_market_copula/paper3_E2.py`. **Only** the asset registry,
pair list, asset-class labels, headers, output paths, plot colours, and verdict text
were changed. The entire numerical core — DCC-A4f-ASYM estimation, Student-t / Clayton
copula MLE, rolling refit, CF-rolling / MC VaR-ES, Trinity backtests, FZ scoring, and
the DM test — is **byte-identical to E2** (which was already Codex-reviewed and merged).

- **Models (3):** `DCC-A4f-ASYM`, `Copula-t-A4f-ASYM`, `Copula-Clayton-A4f-ASYM`.
- **Marginals:** A4f-ASYM with `VIX²` regressor for **all** assets (VIX = global
  systemic risk factor priced across risk assets incl. commodities — Christoffersen
  et al. 2012 RFS). VIX is **retained** rather than swapped for commodity-specific vol
  indices (OVX/GVZ) so the **three arms share one ruler**; OVX/GVZ is a robustness
  extension, not the primary spec.
- **Portfolio:** equal-weight (0.5/0.5), α ∈ {1%, 2.5%}.

### Criterion — HARD CONTRACT, verbatim E2

DM significance uses the **HLN small-sample factor × raw t** compared to
`student_t.ppf(0.975, df)` (`paper3_E3.py` `dm_test`, lines ~790–824), **identical** to
`paper3_E2.py:757-794`. It deliberately does **not** reuse E1's hardcoded
`abs(t) > 3.0`, which the synthesis showed caused **14 false negatives out of 108** E1
tests (`e1_rescored_unified_criterion.json`). Three arms on one ruler is the precondition
for cross-arm counting.

### Lag / lookahead (verbatim E2)

Recursion uses `ret[t-1]` / `x2[t-1]`; the portfolio return is realized at `t`; copula
and marginals are refit only on data through `t-1`. Baseline (DCC) and alternatives
(copula) share the **same** recursion and lag. No additional lookahead is introduced by
the commodity registry.

---

## 3. Data

| Asset | Ticker used | Fallback (unused) | Class |
|---|---|---|---|
| GOLD   | `GC=F` (COMEX gold futures) | GLD  | commodity_metal |
| OIL    | `CL=F` (WTI crude futures)  | USO  | commodity_energy |
| COPPER | `HG=F` (COMEX copper futures)| CPER | commodity_metal |
| WHEAT  | `ZW=F` (CBOT wheat futures) | WEAT | commodity_agri |
| SPY    | `SPY` (S&P 500 ETF)         | —    | equity_us |
| TLT    | `TLT` (20+yr Treasury ETF)  | —    | bond_us_treasury |
| VIX    | `^VIX` (regressor)          | —    | — |

- **Source:** yfinance (live download; `network: "allow"`).
- **Availability probe (2026-07-27):** all four commodity futures + SPY + TLT + VIX have
  ~5,400 rows back to **2005-01-03**. ETF fallbacks (GLD 2004-11, USO 2006-04, **CPER
  2011-11, WEAT 2011-09**) are fallback-only; CPER/WEAT are too short but **do not fire**
  because the futures primaries have full history. `config.ticker_used` confirms **all
  six primaries fired** — no fallback triggered.
- **Period:** `2007-01-01` → `2026-07-24` (last available bar).
- **Inner join:** all 6 assets + VIX required on every day → **4,910 obs per pair**
  (2007-01-04 → 2026-07-24). All 8 pairs share the identical calendar sample.
- **OOS:** `2015-06-01` → `2026-07-24`, **2,795 days per pair**. `window=1250`,
  `refit_every=63`, `seed=42`, `MC_PATHS=5000`. The OOS spans 2018-Q4, the 2020 COVID
  crash, and the 2022 bear — at least one bear market, per research standard.

### Config note (hard contract #3): what changed vs E2, and why

`OOS_START` / `WINDOW` / `REFIT_EVERY` are **unchanged** from E2. `DATA_START` was moved
earlier (E2 `2010-01-01` → E3 `2007-01-01`) for two reasons: (a) the 6-asset
commodity-futures × equity/bond inner join loses more days to non-overlapping holidays
than E2's equity-only panel, and `window=1250` needs comfortable margin before
`OOS_START=2015-06-01`; (b) placing the **2008 GFC** inside the early in-sample refit
windows strengthens copula tail-dependence estimation. This **only lengthens the pre-OOS
training buffer** — the OOS scoring window is byte-for-byte the E2 convention.

---

## 4. Results

### 4.1 Per-pair table (OOS 2015-06-01 → 2026-07-24, n = 2795)

| Pair | Class | corr | λ_L(t) | λ_L(Clay) | DM t (DCC vs Cop-t) | DM t (DCC vs Clay) | Harvey copula win? |
|---|---|---:|---:|---:|---:|---:|:--:|
| GOLD-SPY   | comm-vs-equity | +0.036 | 0.0091 | 0.0003 | −1.240 | −1.996 | N |
| OIL-SPY    | comm-vs-equity | +0.268 | 0.0142 | 0.0752 | +1.582 | +0.751 | N |
| **COPPER-SPY** | comm-vs-equity | +0.307 | 0.0022 | 0.0835 | **+2.613** | −1.069 | **Y** |
| WHEAT-SPY  | comm-vs-equity | +0.103 | 0.0000 | 0.0004 | −1.041 | −1.032 | N |
| GOLD-TLT   | comm-vs-bond   | +0.134 | 0.0316 | 0.1044 | −0.055 | −1.087 | N |
| OIL-TLT    | comm-vs-bond   | −0.209 | 0.0009 | 0.0000 | −0.708 | −0.951 | N |
| COPPER-TLT | comm-vs-bond   | −0.169 | 0.0000 | 0.0000 | −1.020 | −0.279 | N |
| WHEAT-TLT  | comm-vs-bond   | −0.077 | 0.0000 | 0.0000 | +0.863 | +0.877 | N |

DM `t > 0` ⇒ copula better (lower QLIKE); `t < 0` ⇒ DCC better. Correlations are
economically sensible: gold–equity near-zero (safe haven), copper/oil–equity positive
(pro-cyclical), commodity–bond mostly negative.

### 4.2 Copula VaR/QLIKE advantage — **not defensible**

- **Uncorrected per-pair Harvey count:** 1 / 8 pairs (**COPPER-SPY**, Copula-t vs DCC,
  t = +2.613, p = 0.0090) beats DCC at the HLN-corrected critical value.
- **Multiple testing (BH-FDR over all 16 DCC-vs-copula DM tests):**
  **0 copula wins survive at q = 0.10 and q = 0.05.** With 16 tests, ~1 nominal hit at
  5% is chance. The single COPPER-SPY hit is **not** a robust asset-class advantage.
- The second-smallest p-value (GOLD-SPY Clayton, t = −1.996, p = 0.0461) is Harvey-sig
  in **DCC's** favour, not the copula's.

**⇒ Under the shared E2 ruler + FDR, commodities show no defensible copula VaR/QLIKE
advantage. The E1 (stocks) + E2 (cross-market equity) NULL now spans a THIRD, non-equity
asset class.**

### 4.3 The other axis, reported honestly (no selective reporting)

The synthesis warned that E2's copula **calibration** edge at α = 2.5% must be reported
alongside the QLIKE null. For E3:

| Model | Trinity pass 1% | Trinity pass 2.5% | mean FZ @1% (lower=better) |
|---|:--:|:--:|---:|
| DCC-A4f-ASYM | 7/8 | 8/8 | −5.0907 |
| Copula-t-A4f-ASYM | 6/8 | 6/8 | **−5.1168** |
| Copula-Clayton-A4f-ASYM | 7/8 | 5/8 | −5.1154 |

So on **QLIKE (DM)** DCC wins; on **Trinity coverage** DCC is best (8/8 at 2.5%); on
**mean FZ** the copulas are marginally lower (better) on average — but this FZ gap is
**not** Harvey-significant on any pair and does **not** survive FDR. Reported for
completeness, not as a claim.

### 4.4 Scaling adjudication — **the reason E3 exists**

| | ρ (Spearman) | p | sign |
|---|---:|---:|---|
| E3 λ_L(Student-t) vs DM t (Cop-t vs DCC) | **+0.190** | 0.651 | positive, ns |
| E3 λ_L(Clayton) vs DM t (Clay vs DCC) | −0.515 | 0.192 | negative, ns |
| E2 (reference) Student-t scaling | (negative) | (sig, reverse-of-H3) | negative |

**The E2 reverse-sign scaling does NOT replicate in commodities.** The E3 Student-t
relationship is **positive** (opposite to E2's negative) and **not significant**
(p = 0.65); the Clayton relationship is negative but also not significant (p = 0.19).
Replication would require the E3 Student-t sign to **match E2's (negative) AND be
significant** — neither holds.

**⇒ Diagnostic verdict: E2's reverse-sign `λ_L → DM` relationship is ARM-SPECIFIC, not a
stable cross-asset-class law.** This is the honest, non-spun answer to the question E3
was created to settle. It does **not** rescue H3 (H3's predicted direction still fails);
it shows the E2 reversal is an equity-cross-market idiosyncrasy that a non-equity class
does not reproduce.

---

## 5. Honesty notes

- **Not too-good-to-be-true.** The headline is a NULL that extends E1/E2; the single
  COPPER-SPY hit is exactly the ~1-in-16 chance rate and dies under FDR. Correlations,
  λ_L (gold≈0 safe-haven, copper/oil>0 pro-cyclical), and DM signs are all economically
  coherent.
- **Inherited-pipeline caveat.** If the E1/E2 OOS pipeline itself harbours a lookahead
  defect, this E3 — reusing that exact skeleton — would **not** surface it. The recursion
  and refit are lag-clean by construction (§2), but this run does not independently
  re-audit the shared skeleton.
- **`network: "allow"` sample growth.** yfinance is a live download; the sample end
  advances every trading day, so a future re-run necessarily sees a longer sample and the
  numeric surface drifts slightly. `reproduce_spec.json` pins the code (sha256), seed
  (numpy=42), and method; the empirical surface is reproducible up to sample-end drift.
  Timestamp/runtime/`ticker_used` pointers are ignored in the spec comparison.
- **VIX-for-commodities.** Using ^VIX (not OVX/GVZ) as the commodity marginal regressor
  is a deliberate cross-arm-comparability choice, not an oversight (§2). It is a defensible
  global-risk proxy but a commodity-specific vol index is a valid robustness extension.

---

## 6. Artifact-gate results

- `uv run python scripts/check_experiment_artifacts.py check --path experiments/paper3_E3_commodities_copula`
  → **PASS** — `no K-id (knowledge check n/a) + reproduce_spec.json, spec check: strict`.
  (Named experiment dir carries no numeric K-id, so the knowledge-entry half is n/a; the
  knowledge write is the main-thread's collection step — worktree agents must not write
  `knowledge.json`, K1259.)
- `uv run python scripts/experiment_gates.py run --path experiments/paper3_E3_commodities_copula`
  → **PASS** — cleared 4 experiment-integrity gates (DM HAC lag, MDD scale artifact, etc.).
- `reproduce_spec.json` entrypoint sha256 verified equal to current `paper3_E3.py` bytes.

---

## 7. Reproduction

```bash
# Full run (all 8 pairs + auto-assemble); ~7 min, needs network for yfinance
uv run python experiments/paper3_E3_commodities_copula/paper3_E3.py
```

**Batch harness (orchestration only; numerical core untouched, results identical).**
Because the full run exceeds a single foreground budget and this job ran headless, each
pair is computed and pickle-cached independently under `_pair_cache/`, and the
cross-pair analysis + plots + results JSON assemble only once every pair is cached:

```bash
PAIRS_ONLY='GOLD-SPY,OIL-SPY' uv run python .../paper3_E3.py   # compute a subset
ASSEMBLE=1                     uv run python .../paper3_E3.py   # assemble from caches
```

Per-pair fits are independent and seeded (`42`), so batched execution is byte-identical
to one-process execution. `_pair_cache/` and `__pycache__/` are intermediates and are
**not** committed.

---

## 8. 給收件主線程的驗證清單 (verification checklist for the collecting main thread)

**關鍵數字位置：**
- Top-level `aggregate` in `paper3_E3_results.json`:
  `n_harvey_sig=1`, `pairs_with_copula_advantage_harvey=["COPPER-SPY"]`,
  `n_bh_fdr_q10_copula_wins=0`, `n_bh_fdr_q05_copula_wins=0`.
- `aggregate.scaling_adjudication`: `e2_reverse_sign_replicates_in_commodities=false`,
  Student-t ρ=+0.190 (p=0.651), Clayton ρ=−0.515 (p=0.192).
- `aggregate.dm_tests_dcc_vs_copula`: all 16 DM tests with p-values and BH-survival flags.
- Per-pair detail under `pair_results.<pair>.models` / `.dm_qlike` / `.copula_stats`.

**Gate results (§6):** both `check_experiment_artifacts` and `experiment_gates` PASS;
reproduce_spec sha matches.

**待 Codex 審碼要點 (for Codex review before knowledge write):**
1. Confirm `dm_test` (lines ~790–824) is byte-identical to `paper3_E2.py:757-794` — HLN
   factor × raw t vs `student_t.ppf(0.975, df)`; **no** `abs(t)>3.0`.
2. Confirm the DCC / copula / marginal / VaR / MC machinery is unchanged from E2 (diff
   should be limited to `MARKETS`, `PAIRS`, `PAIR_REGION_CLASS`, headers, paths, plot
   colours, verdict strings, the batch harness, and the `aggregate` block).
3. Sanity-check the new `aggregate` BH-FDR loop (lines in `assemble`) — two-sided p,
   step-up threshold `p_(k) ≤ (k/m)·q`, intersect with `copula_better`.
4. Lag / lookahead: recursion `ret[t-1]`/`x2[t-1]`, refit through `t-1`, baseline same lag.

**待寫 knowledge 的結論摘要 (proposed knowledge entry, MAIN THREAD writes it):**
> **Paper3_E3 (commodities × {SPY,TLT}, 8 pairs, 2015-06→2026-07 OOS, E2-verbatim
> criterion):** No defensible Copula-GARCH VaR/QLIKE advantage over DCC-A4f-ASYM —
> 1/8 uncorrected Harvey hit (COPPER-SPY), **0 survive BH-FDR**. The no-copula-advantage
> result now spans a **third, non-equity asset class** (with E1 stocks + E2 cross-market
> equity). **E2's reverse-sign `λ_L → DM` scaling does NOT replicate** in commodities
> (Student-t ρ=+0.190, p=0.65; opposite sign, ns) ⇒ E2's reversal is **arm-specific**,
> not a cross-asset-class law. Verdict: NULL on advantage; adjudication resolved toward
> arm-specificity. Reviewer: <Codex verdict>. K-id: <reserve on collection>.

**收件後主線程 followup (per dispatch brief):** 驗數字 → check_experiment_artifacts →
Codex 審碼 → 通過才寫 knowledge → merge worktree → 解除「不得宣稱跨資產類別」邊界
(E3 now covers the third asset class).

---

## 9. Failure / blocker record

**None — this run succeeded.** Recorded here because the hard contract requires it and
because this experiment exists precisely to correct a prior silent failure:

- The 2026-05-29 E3 attempt failed with **no recorded reason, no partial artifact, and no
  retry for 7 weeks**. Root cause of *that* failure is unknown (no logs survived). This
  re-run pre-empted a repeat by **probing yfinance availability first** (all six primaries
  return ~5,400 rows) and **smoke-testing** the full pipeline before the production run.
- No blockers were hit: data fetched cleanly, all 8 pairs converged, all gates passed.
