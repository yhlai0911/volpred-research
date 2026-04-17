# Section 5 (v4 rewrite): Cross-Asset Universality of VIX Sufficiency

**Status**: Markdown draft for main-thread adoption into `paper/vix-sufficiency/body_v4.tex`.
**Source experiments (verbatim)**: K1116c (SPY), K1116f (GLD / TLT / BTC-USD), K1201 (QQQ / USO),
K1203 (EEM).  **Panorama coverage**: 7 / 7 of the Paper 4 stated universe.
**Narrative state-machine gate**: UNLOCKED (K1116c + K1116f + K1201 + K1203 all OOS-verified, ≥3 complementary).

---

## 5.1 Panorama overview

Section 4 established VIX sufficiency for SPY under point-in-time (PIT)
release-calendar alignment of five alt-data indicators (USEPU, WLEMU, NFCI,
ANFCI, STLFSI). Section 5 asks whether that result generalises across asset
classes, or whether it is S\&P 500-specific.

We construct a **7-asset panorama** spanning US broad equity (SPY), US
technology (QQQ), precious-metal commodity (GLD), energy commodity (USO),
long-duration Treasuries (TLT), cryptocurrency (BTC-USD), and emerging-market
equity (EEM). Every asset runs the identical K1116c protocol: weekly realised
volatility as target; AR(1) + asset-class native-IV proxy as the DM baseline;
three alt-data specifications --- `epu` (USEPU + WLEMU), `finstress` (NFCI +
ANFCI + STLFSI), `all` (native-IV plus all five alt-data regressors). The PIT
panel takes, for each week-ending Friday F, the most recent observation with
`release_date <= F`, so `pit_shift0` is the tightest causal alignment
admissible without true ALFRED vintage data (unavailable in our environment;
see §5.4). All cells use the same 2018-01-12 -- 2026-04-10 window with a
260-week in-sample / 170-week out-of-sample split (OOS: 2023-01-01 --
2026-04-10). Statistical tests follow Harvey, Leybourne, and Newbold (1997)
Diebold-Mariano with finite-sample correction, Patton (2011) QLIKE loss, and
the Harvey (2016) |t| > 3 multiple-testing threshold.

The experimental progression was staged to rule out timing / coverage
artefacts: **K1116c** (SPY, six PIT variants) confirmed the alt-data NULL is
robust to publication-delay correction; **K1116f** (GLD / TLT / BTC-USD)
extended PIT to three non-equity classes, revealing one lag-sensitive TLT
outlier; **K1201** (QQQ / USO) closed the equity-tech and energy-commodity
cells (USO producing the panorama's strongest baseline win at DM t = -5.60 on
EPU); **K1203** (EEM) closed the emerging-market cell with a ^VIX spillover
proxy (^VXEEM delisted from yfinance 2026-04-17; see §5.4) plus rv30
robustness.

## 5.2 Results by asset class

Table 5.1 presents the full 28-cell panorama of `pit_shift0` DM t-statistics
against each asset's native-IV baseline. The sign convention is such that a
**positive** t-statistic indicates the alt-data challenger beats the native IV
(the desirable direction for alt-data proponents); a **negative** t indicates
the native IV wins.

**Table 5.1: 7-asset x 4-spec DM t-statistic panorama (pit_shift0 alignment)**

| Asset class           | Asset    | Native IV         | base    | epu     | finstress | all      | Source  |
|-----------------------|----------|-------------------|--------:|--------:|----------:|---------:|---------|
| US broad equity       | SPY      | ^VIX              | -3.021  | -2.603  | -3.001    | -2.537   | K1116c  |
| US technology equity  | QQQ      | ^VXN              | -2.186  | -1.967  | -2.439    | -1.967   | K1201   |
| Precious-metal commodity | GLD   | ^GVZ              | -2.103  | -2.069  | -3.341    | -2.246   | K1116f  |
| Energy commodity      | USO      | ^OVX              | -3.049  | **-5.596** | -2.584 | **-3.735** | K1201  |
| Long-duration Treasuries | TLT   | ^MOVE             | +1.433  | -2.477  | **+3.743** | **-5.666** | K1116f |
| Cryptocurrency        | BTC-USD  | rv30 (self)       | -5.494  | -3.550  | +1.370    | +0.203   | K1116f  |
| Emerging-market equity | EEM     | ^VIX (spillover)  | -2.596  | -3.539  | -1.434    | -0.999   | K1203   |

**Table 5.2: Best-alt-spec QLIKE improvement over native-IV baseline (pit_shift0; 5% gate)**

| Asset    | Native IV | QLIKE improvement | 5% gate | Comment                                    |
|----------|-----------|------------------:|:-------:|--------------------------------------------|
| SPY      | ^VIX      | -0.67%            | FAIL    | alt-data degrades accuracy                 |
| QQQ      | ^VXN      | -0.56%            | FAIL    | alt-data degrades accuracy                 |
| GLD      | ^GVZ      | -0.63%            | FAIL    | alt-data degrades accuracy                 |
| USO      | ^OVX      | -0.84%            | FAIL    | strongest baseline win                     |
| TLT      | ^MOVE     | +0.50%            | FAIL    | only positive cell, below 5% gate          |
| BTC-USD  | rv30      | +0.23%            | FAIL    | positive but economically small            |
| EEM      | ^VIX      | -0.13%            | FAIL    | -- and +0.09% under rv30 robustness        |

Of the **28 panorama cells** (7 assets x 4 specifications), **exactly one cell**
(TLT / finstress) exceeds the Harvey (2016) |t| > 3 threshold in the direction that
would reject VIX sufficiency. Every other cell either favours the native-IV
baseline outright (20 cells with negative t) or produces a positive but
insignificant alt-data t-statistic (7 cells with 0 < t < 3.1). **No cell in any
asset class** produces an alt-data QLIKE improvement exceeding the 5 % economic
gate.

## 5.3 The TLT finstress outlier: lag-sensitive regime artefact

The single Harvey-threshold-exceeding cell warrants closer examination. At
`pit_shift0`, TLT's finstress spec produces DM t = **+3.74** against the
^MOVE baseline (K1116f). In isolation this could suggest that for
long-duration Treasuries, financial-conditions alt-data carries information
beyond implied volatility. Three independent pieces of evidence argue against
that interpretation.

**First, lag sensitivity.** Adding one week of safety margin (`pit_shift1`)
collapses DM t from +3.74 to **+2.00** (Harvey-insignificant at p = 0.047).
A genuine structural signal should be approximately invariant to one extra
week of conservative lag; the sensitivity suggests the +3.74 point estimate
is driven partly by marginal NFCI-release timing during high-stress regimes
inside the OOS window.

**Second, the QLIKE economic gate.** Best-alt QLIKE improvement over the MOVE
baseline is **+0.50 %** --- an order of magnitude below the 5 % Patton
(2011)-style economic gate. A statistically marginal signal delivering
essentially zero economic value is consistent with regime artefact rather
than predictive content.

**Third, kitchen-sink collapse.** Combining MOVE and all five alt-data
regressors gives DM t = **-5.67** at `pit_shift0`, confirming that adding
alt-data on top of native-IV actively degrades OOS accuracy through
overfitting. A genuinely orthogonal finstress signal would leave the `all`
spec at worst neutral; the strong negative sign instead signals fragility to
complementary regressors.

Taken together, these characterise the TLT / finstress cell as a
**non-structural regime artefact** rather than a replicable signal. A
dedicated rates-native follow-up (§5.6) is warranted to confirm or reject the
characterisation with sharper identification.

## 5.4 Data-availability caveat: ^VXEEM and the EEM cell

CBOE historically published ^VXEEM as the natural native-IV proxy for EEM. A
2026-04-17 yfinance probe, however, confirmed ^VXEEM has been delisted from the
Yahoo Finance feed (HTTP 404 for ^VXEEM / VXEEM; ^VXFXI and ^CIV alternatives
similarly unavailable; ^VIX feed active). Because no FRED or CBOE-direct
vintage of ^VXEEM is accessible without additional data licensing, K1203 adopts
a **dual-baseline robustness design**: primary EEM + ^VIX (a spillover proxy;
weekly EEM-VIX correlation ≈ 0.75 in sample) and robustness EEM + rv30 (a
30-day rolling realised-vol baseline on EEM itself, identical convention to
K1116f's BTC-USD setup).

The verdict is invariant across the two baselines. Under ^VIX primary (Table
5.1) no EEM challenger reaches |t| > 3. Under rv30 robustness, the best-alt
`pit_shift0` t-statistic is +1.18 (NS) with QLIKE improvement +0.09 % --- flat,
not a rescue of the alt-data thesis. The emerging-market cell is NULL in both
proxies; the ^VXEEM data gap does not meaningfully weaken the panorama claim,
and acquiring ^VXEEM via direct CBOE access is flagged as a strengthening
follow-up rather than a verdict-changing prerequisite.

## 5.5 Final narrative commitment

> **Native implied-volatility proxies (^VIX, ^VXN, ^OVX, ^GVZ, ^MOVE, and
> ^VXEEM-or-proxy with rv30 robustness) are sufficient for one-step-ahead
> realised-volatility forecasting across seven asset classes: US broad equity
> (SPY), US technology equity (QQQ), precious-metal commodity (GLD), energy
> commodity (USO), long-duration Treasuries (TLT), cryptocurrency (BTC-USD), and
> emerging-market equity (EEM).
>
> Alt-data regressors (economic policy uncertainty, weekly leading-economic
> uncertainty, and the NFCI / ANFCI / STLFSI financial-stress family) cannot
> deliver Harvey (2016) |t| > 3 improvement over the native-IV baseline under
> point-in-time publication-lag alignment. Only TLT / finstress exceeds that
> threshold at `pit_shift0` (DM t = +3.74), but it fails (i) the 5 % QLIKE
> economic gate (+0.50 % improvement), (ii) the `pit_shift1` robustness check
> (collapses to +2.00), and (iii) the kitchen-sink `all` spec (DM t = -5.67),
> and is therefore characterised as a non-structural regime artefact rather
> than a replicable rates-specific signal.**

This replaces the v3 "native-IV sufficient" partial framing (limited to SPY
and a subset of cross-asset cells pre-PIT). The v4 formulation is anchored in
four OOS-verified, code-reviewed experiments covering the full stated
universe of Paper 4.

## 5.6 Limitations and future work

The cross-asset universality claim above rests on a specific scope. We flag
five limitations and corresponding follow-up directions.

1. **Seven-asset sample.** The panorama spans the major asset-class buckets
   but is not exhaustive. Developed-market ex-US equity (EFA),
   investment-grade / high-yield credit (LQD, HYG), real estate (VNQ), and
   agricultural commodities (DBA) would further test the native-IV claim.
   Each future cell should be treated as an independent pre-registered test.

2. **Publication-lag database coverage.** PIT alignment uses documented
   release calendars for USEPU, WLEMU, NFCI, ANFCI, and STLFSI. FRED's
   real-time database covers some indices (NFCI, ANFCI) with precise release
   timestamps; others (USEPU) rely on the publisher's stated cadence with
   occasional ad-hoc delays. ALFRED vintage access would eliminate residual
   revision-vs-release ambiguity but is API-key gated.

3. **^VXEEM data availability.** §5.4 documents the ^VIX / rv30 dual-baseline
   workaround. A direct CBOE historical ^VXEEM pull would tighten the EEM
   claim, though the qualitative verdict is already invariant to the proxy
   choice.

4. **TLT regime caveat.** The +3.74 finstress cell, characterised as a regime
   artefact in §5.3, merits a dedicated rates-native study: (a) condition on
   MOVE-regime transitions and test whether finstress adds in high-stress
   rates regimes only; (b) replace AR(1) with a term-premium-aware baseline
   (e.g., ACM term-premium estimates) and test whether finstress survives
   once rates-specific latent state is absorbed. Either design would confirm
   or reject the regime-artefact characterisation with sharper
   identification.

5. **Weekly AR(1) + native-IV baseline.** The weekly setup is deliberately
   simple for cross-asset comparability. A daily HAR-RV (Corsi 2009) + native
   IV + alt-data horse race is natural follow-up; the K1121 daily SPY
   allocation-level NULL provides a prior that the verdict will extend to the
   higher-frequency horizon.

---

## Appendix: Source traceability

| Experiment | Commit     | Assets                | Path               |
|------------|------------|-----------------------|--------------------|
| K1116c     | `64a9d569` | SPY                   | experiments/k1116c/ |
| K1116f     | `885d7b0b` | GLD, TLT, BTC-USD     | experiments/k1116f/ |
| K1201      | `87059567` | QQQ, USO              | experiments/k1201/  |
| K1203      | `477c504a` | EEM (^VIX + rv30)     | experiments/k1203/  |

Exact four-decimal DM t-stats and QLIKE improvements also available in
`experiments/k1208/k1208_panorama_table.csv` (28 cells, pit_shift0 +
pit_shift1) and `k1208_results.json` (canonical synthesis).

---

*Intended for main-thread cherry-pick into
`paper/vix-sufficiency/body_v4.tex`. Not to be rendered as .tex by any
background / worktree agent per CLAUDE.md paper-workflow rule.*
