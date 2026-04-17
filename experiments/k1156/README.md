# K1156 — Paper 2 Cover Figure: 6-Market Cross-Validation Visualization

> **TL;DR**: Publication-quality cover figure for `paper/taiwan-vt` showing
> direction-universal cross-market validation of the overnight U.S.→Asia
> information transmission channel (the empirical anchor for Paper 2's
> VIX-proxy VT). Six Asia-Pacific markets (TW, JP, KR, AU, SG, HK) all
> exceed the Harvey (2016) c2c $t = 3.0$ threshold in the paper's canonical
> Appendix table; K1176 replicates the same six markets from yfinance daily
> OHLC and confirms the qualitative story. **Pure visualisation — no new
> estimation.** All bar values trace back to either Paper 2 `body_v3.tex`
> Appendix Table 7 (`tz_results`) or the existing `experiments/k1176/`
> JSON output.

[提出: User K1156, 執行: Claude (worktree agent)]

**Type**: visualization-only (no new model fits, no new data downloads)
**Random seed**: 42 (deterministic; no stochastic component in figure)
**Data inputs**: Paper canonical numbers + K1176 replicated numbers

---

## 1. Why this figure (motivation)

Paper 2 (`taiwan-vt`) Appendix `app:tz` documents that the U.S.→Asia
overnight information transmission channel — the same channel that justifies
using U.S. VIX as a Taiwan implied-volatility proxy in the main VT body —
generates statistically significant c2c Sharpe across **six** Asia-Pacific
markets (TW, JP, KR, AU, SG, HK). This is the cross-market consistency
result that warrants a single lead-in / cover figure.

The user task K1156 requested a `5-market validation` figure; the canonical
paper actually documents **six** markets in Appendix Table 7 plus the
post-table prose ("Hong Kong $t = 4.12$, Australia $t = 4.04$,
Singapore $t = 4.03$, Korea $t = 3.83$, Taiwan $t = 3.76$, Japan $t = 3.69$"),
so we render six bars rather than artificially trimming.

**K1153 / K1175 / K1178 were considered and explicitly rejected** as the
cover-figure source because they answer different questions:

| K | Topic | Why not used here |
|---|-------|--------------------|
| K1153 | A4f-EAV pooled panel θ_EAV across TW+US+JP+EU (4 markets) | Earnings-announcement channel for **Paper 1** lineage; not the overnight channel that motivates Paper 2 |
| K1175 | Paper 2 Table 3 single-market VT replication (TW only) | Single-market; no cross-market comparison axis |
| K1178 | Paper 3 Table 5 13-market international VT replication | Belongs to Paper 3 (`vt-trend-following`), not Paper 2 |

The K1156 figure therefore aligns directly with **Paper 2's own Appendix
Table 7** narrative.

---

## 2. What the figure shows

### Panel A (top): Newey–West HAC c2c $t$-statistic by market

- **Navy bars** — Paper canonical c2c $t$-stats from `body_v3.tex` Appendix
  prose (HK 4.12, AU 4.04, SG 4.03, KR 3.83, TW 3.76, JP 3.69).
- **Mid-blue bars** — K1176 reproduced c2c $t$-stats from yfinance daily
  OHLC (TW 6.76, JP 6.91, KR 4.88, AU 4.52, SG 4.83, HK 2.92).
- **Dark-blue diamond markers** — K1176 reproduced o2o (implementable)
  $t$-stats (TW 8.13, JP 8.34, KR 6.08, AU 6.17, SG 5.96, HK 4.14).
- **Dashed red line** — Harvey (2016) threshold $t = 3.0$.

**Reading the panel**: in the paper-canonical Appendix specification, all
six markets exceed the Harvey threshold on c2c. K1176 confirms 5/6 on c2c
(HK 2.92 < 3.0) and 6/6 on o2o (HK 4.14 > 3.0).

### Panel B (bottom): K1176 c2c Sharpe with confidence intervals

- **Mid-blue bars** — K1176 c2c Sharpe ratios per market with $\pm 1.96/\sqrt{T_{yr}}$
  asymptotic 95% CI (using the iid-Sharpe SE; deliberately conservative
  since it ignores HAC correction).
- **Orange star markers** — Paper canonical c2c Sharpe (TW 1.473, JP 1.306;
  the paper's Appendix Table 7 reports Sharpe only for these two markets).
- **Orange error bar at TW** — Paper's reported block-bootstrap 95% CI
  $[0.65, 2.24]$ (Appendix Robustness paragraph), CI width = 1.59.

---

## 3. Numbers used and their provenance

| Market | Paper c2c $t$ | K1176 c2c $t$ | K1176 o2o $t$ | K1176 c2c Sharpe | K1176 c2c MDD% | n trading days |
|--------|---------------|---------------|---------------|------------------|----------------|----------------|
| TW (0050.TW) | 3.76 | 6.76 | 8.13 | 1.92 | -10.6 | 3302 |
| JP (Nikkei 225) | 3.69 | 6.91 | 8.34 | 1.77 | -15.3 | 3307 |
| KR (KOSPI) | 3.83 | 4.88 | 6.08 | 1.37 | -15.4 | 3327 |
| AU (ASX) | 4.04 | 4.52 | 6.17 | 1.13 | -11.4 | 3448 |
| SG (STI) | 4.03 | 4.83 | 5.96 | 1.34 | -8.8 | 3419 |
| HK (HSI) | 4.12 | 2.92 | 4.14 | 0.80 | -32.1 | 3353 |

Source columns:

- **Paper c2c $t$**: `paper/taiwan-vt/body_v3.tex` (or `body_v2.tex` in the
  worktree shadow), Appendix `app:tz` Subsection "Main Results", post-table
  prose. The script verbatim-greps the six "$t = ...$" snippets at runtime
  and writes `paper_text_verification.all_six_t_stats_found_verbatim = true`
  into `k1156_results.json`. If a future paper revision changes the numbers,
  this check fires and the README must be updated.
- **K1176 c2c/o2o/Sharpe/MDD**: `experiments/k1176/k1176_results.json`
  → `individual_markets[<MKT>].c2c.{nw_tstat, sharpe, mdd_pct, n_days}`
  and `individual_markets[<MKT>].o2o.nw_tstat`.

### Where each number lands in `paper/taiwan-vt/body_v3.tex`

| Figure element | Paper source line (body_v3.tex) |
|----------------|---------------------------------|
| TW c2c Sharpe 1.473, o2o 0.87, $t$ 2.22 | Table `tz_results`, Panel A row 1 (~L534) |
| JP c2c Sharpe 1.306, o2o 0.78, $t$ 2.00 | Table `tz_results`, Panel A row 2 (~L535) |
| 6-market c2c $t$-stat list | Subsection prose after `tz_results` (~L555) |
| TW block bootstrap 95% CI [0.65, 2.24] | Appendix `Robustness` paragraph (~L577) |

---

## 4. Replication

```bash
# From repo root (or worktree root):
uv run python experiments/k1156/k1156.py
```

The script is fully deterministic. It performs no network I/O, no random
draws, and no re-estimation. Running it twice produces byte-identical
`k1156_results.json` (modulo the `timestamp_utc` field) and visually
identical PNG/PDF.

Outputs:

- `experiments/k1156/k1156_cover.png` (300 dpi raster, 356 KB)
- `experiments/k1156/k1156_cover.pdf` (vector, ~31 KB)
- `experiments/k1156/k1156_results.json` (canonical inputs + per-market table)

---

## 5. Where this figure should live in Paper 2

**Recommendation**: place as a **lead-in / Section 1 cover figure** or as
**Figure A1** (first appendix figure) in `paper/taiwan-vt/main.tex`,
captioned as a one-page visual summary of the Appendix `app:tz` content
that motivates the VIX-as-proxy design choice in the main body.

If integrated into `main.tex`, copy `k1156_cover.pdf` into
`paper/taiwan-vt/figures/fig0_cover_six_market.pdf` and add:

```latex
\begin{figure}[htbp]
  \centering
  \includegraphics[width=0.95\textwidth]{figures/fig0_cover_six_market.pdf}
  \caption{Cross-market validation of the U.S.\,$\rightarrow$\,Asia
    overnight information transmission channel...}
  \label{fig:cover_six_market}
\end{figure}
```

(Per `paper-workflow.md` rule, the actual main.tex edit must be done in
the main thread, not by the worktree agent.)

---

## 6. NOTED DIVERGENCE (transparency)

Per CLAUDE.md research-honesty rule #10 and the `paper-workflow.md`
"three-way consistency" requirement, K1156 explicitly records the known
paper-vs-replication divergence rather than masking it:

1. **HK c2c $t$**: paper 4.12 vs K1176 2.92. K1176 already documented this
   in its own `k1176_vs_paper2_table4_diff.md` and traced it to data-source
   differences (yfinance HSI returns vs the paper's underlying source).
   K1156 displays both bars side-by-side so the divergence is visible
   rather than buried.
2. **Sharpe magnitude**: K1176 c2c Sharpes run ~30% above the paper
   canonical for TW (1.92 vs 1.47) and JP (1.77 vs 1.31), again from
   data-source differences (split handling, dividend treatment). The
   Panel B orange stars sit visibly below the K1176 blue bars to expose
   this gap.
3. **All canonical paper numbers in the figure are reproduced verbatim**
   from `body_v3.tex` (or `body_v2.tex` shadow). No re-scaling, no
   re-fitting, no seed-tuning. The paper-vs-replication gap is shown,
   not hidden.

K1156 does **not** propose a fix to this divergence — that decision
((a) match script to paper / (b) match paper to script / (c) errata) is
a Paper 2 narrative-state-machine decision and must be made in the main
thread per CLAUDE.md.

---

## 7. Files

| File | Purpose |
|------|---------|
| `k1156.py` | Figure generator (deterministic, no estimation) |
| `k1156_cover.png` | Two-panel cover figure, 300 dpi |
| `k1156_cover.pdf` | Same figure, vector format for LaTeX inclusion |
| `k1156_results.json` | Canonical inputs, per-market table, paper-text verification flag |
| `README.md` | This file |

---

## 8. Related K experiments

- **K1176** — 6-market overnight-channel c2c/o2o replication (this figure's
  primary data source for replicated bars)
- **K1175** — single-market TW VT Table 3 replication (referenced in
  k1156_results.json but not used as figure input)
- **K1178** — 13-market Paper 3 international VT (separate paper, not this
  cover)
- **K1153** — TW+US+JP+EU four-market earnings-announcement panel
  (Paper 1 lineage, not Paper 2)

---

## 9. References

- Harvey, C. R., Liu, Y., & Zhu, H. (2016). … and the cross-section of
  expected returns. *Review of Financial Studies*, 29(1), 5-68.
  (Used for $t > 3.0$ multiple-testing threshold marker in Panel A.)
- Newey, W. K., & West, K. D. (1987). A simple, positive semi-definite,
  heteroskedasticity and autocorrelation consistent covariance matrix.
  *Econometrica*, 55(3), 703-708. (HAC SE used for all $t$-stats shown.)
- Andrews, D. W. K. (1991). Heteroskedasticity and autocorrelation
  consistent covariance matrix estimation. *Econometrica*, 59(3), 817-858.
  (Automatic-bandwidth NW lag selection used by K1176.)
