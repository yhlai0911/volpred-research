# Paper 4 body_v4 Dual-Framing Edit Guide (resolve CONFLICT-A4)

> **CONFLICT-A4 pending user resolution.** User commit `7ecab636` (2026-04-17)
> suggested a "channel-specific pivot" for Paper 4. K1203 session gate
> concurrently unlocked the `UNIVERSAL_NULL_7_OF_7` framing, and K1208 authored
> the §5 Markdown draft in UNIVERSAL_NULL language (K1208 commit not yet known;
> draft lives at `experiments/k1208/k1208_draft.md`). **K1225 produces BOTH
> candidate framings as parallel edit guides so the user can pick exactly one
> before the main thread writes `body_v4.tex`.** Per CLAUDE.md paper-workflow
> rule, only `.md`/`.json` are produced here — no `.tex`.

---

## 0. Common baseline (applies to both Version A and Version B)

Both versions share the same source data, statistical design, and quality
gates. The framings differ only in rhetorical positioning and §5 narrative
structure; the tables, t-stats, and QLIKE numbers are identical.

### 0.1 Source commit traceability

| Experiment | Commit | Assets | Role |
|------------|--------|--------|------|
| K1116c | `64a9d569` | SPY | 6 PIT variants; alt-data NULL under publication-delay correction |
| K1116f | `885d7b0b` | GLD, TLT, BTC-USD | PIT (3 variants); TLT outlier identification |
| K1201 | `87059567` | QQQ, USO | PIT (3 variants); closed equity-tech + energy-commodity cells |
| K1203 | `477c504a` | EEM | PIT (3 variants) ^VIX primary + rv30 robustness; 7/7 panorama closed |
| K1208 | (draft) | 7-asset synthesis | §5 Markdown draft (UNIVERSAL_NULL framing) |
| K1218 | (draft) | — | Appendix A cross-paper reference (Paper 6 replication; reused here only as organisational template) |
| K1225 | (this) | — | Dual-framing edit guide resolving CONFLICT-A4 |

### 0.2 Canonical 28-cell panorama (identical in both versions)

Source: K1208 draft Table 5.1 + K1203 README §3.2. Sign convention: positive
t = alt-data beats native IV; negative t = native IV wins.

| Asset class | Asset | Native IV | base | epu | finstress | all | Source |
|-------------|-------|-----------|-----:|----:|----------:|----:|--------|
| US broad equity | SPY | ^VIX | -3.021 | -2.603 | -3.001 | -2.537 | K1116c |
| US technology equity | QQQ | ^VXN | -2.186 | -1.967 | -2.439 | -1.967 | K1201 |
| Precious-metal commodity | GLD | ^GVZ | -2.103 | -2.069 | -3.341 | -2.246 | K1116f |
| Energy commodity | USO | ^OVX | -3.049 | **-5.596** | -2.584 | **-3.735** | K1201 |
| Long-duration Treasuries | TLT | ^MOVE | +1.433 | -2.477 | **+3.743** | **-5.666** | K1116f |
| Cryptocurrency | BTC-USD | rv30 (self) | -5.494 | -3.550 | +1.370 | +0.203 | K1116f |
| Emerging-market equity | EEM | ^VIX (spillover) | -2.596 | -3.539 | -1.434 | -0.999 | K1203 |

### 0.3 Best-alt QLIKE improvement (5% Patton gate)

| Asset | QLIKE improvement | Gate | Comment |
|-------|------------------:|:----:|---------|
| SPY | -0.67% | FAIL | alt-data degrades |
| QQQ | -0.56% | FAIL | alt-data degrades |
| GLD | -0.63% | FAIL | alt-data degrades |
| USO | -0.84% | FAIL | strongest baseline win |
| TLT | +0.50% | FAIL | only positive, below gate |
| BTC-USD | +0.23% | FAIL | positive but tiny |
| EEM | -0.13% | FAIL | (rv30 robust: +0.09%) |

**Of 28 cells, exactly one (TLT finstress, +3.74) crosses Harvey |t|>3 in the
alt-data-wins direction. Zero cells pass the 5% QLIKE economic gate.**

### 0.4 TLT finstress outlier disposal (shared by both versions)

Three independent arguments characterise the +3.74 cell as **regime artefact,
not replicable signal**:

1. **Lag sensitivity.** `pit_shift1` collapses DM t from +3.74 to **+2.00**
   (Harvey-insignificant). A structural signal should be lag-invariant.
2. **QLIKE economic gate.** Best-alt QLIKE improvement over ^MOVE is
   **+0.50%**, an order of magnitude below the 5% Patton (2011) gate.
3. **Kitchen-sink collapse.** The `all` spec (^MOVE + 5 alt-data regressors)
   gives DM t = **-5.67** at `pit_shift0` — strong overfitting signature
   inconsistent with a genuinely orthogonal finstress signal.

### 0.5 ^VXEEM data-availability caveat (shared)

CBOE's ^VXEEM is historically the natural native-IV proxy for EEM. A
2026-04-17 yfinance probe confirmed ^VXEEM / VXEEM / ^VXFXI / ^CIV are all
unavailable via Yahoo Finance (HTTP 404 / "possibly delisted"), while ^VIX
itself is active. K1203 adopts a dual-baseline design: **primary EEM + ^VIX**
(spillover proxy; weekly EEM-VIX correlation ≈ 0.75) and **robustness EEM +
rv30** (30-day rolling realised vol, IV-free, same convention as K1116f BTC).
The EEM NULL verdict is invariant across the two baselines.

### 0.6 Statistical design (shared)

- Window: 2018-01-12 to 2026-04-10 (260-week IS / 170-week OOS; OOS start
  2023-01-01).
- Target: weekly realised volatility $\sqrt{\sum r^2_{daily}}$, minimum 4
  trading days per week.
- Baseline: AR(1) + asset-class native IV (or rv30 for BTC-USD + EEM robust).
- Alt-data specs: `epu` = USEPU + WLEMU; `finstress` = NFCI + ANFCI + STLFSI;
  `all` = native IV + 5 alt regressors.
- Tests: DM-HLN with Harvey (1997) finite-sample correction; QLIKE (Patton
  2011) on $r^2$ proxy; Harvey (2016) |t| > 3 threshold; 5% QLIKE economic
  gate.
- Seed 42 (all random operations).

### 0.7 Appendix A integration (shared)

K1218's appendix template is available for reuse, though its substantive
content addresses Paper 6 (PRG). For Paper 4, an independent Appendix A is
recommended to document (a) the K1116c six-PIT-variant robustness grid, (b)
the ^VXEEM-unavailable dual-baseline protocol, and (c) the TLT
regime-artefact disposal. This is common to both Version A and Version B.

---

## Version A — Channel-Specific Framing

### A.1 §5 Title (Version A)

> **Section 5: Alt-Data Channels and Native IV Dominance Across Asset Classes**

### A.2 Opening narrative (Version A)

> Section 4 established that, for S&P 500 volatility, ^VIX subsumes five
> alt-data channels (EPU, weekly leading economic uncertainty, and the
> NFCI / ANFCI / STLFSI financial-stress family) under point-in-time
> publication-lag alignment. Section 5 asks a narrower, channel-oriented
> question: *for each asset class, which alt-data channel — if any — could
> challenge the asset's native implied-volatility index?* We construct a
> 7-asset × 4-specification panorama (28 cells) and report, for each asset's
> native IV proxy, the best alt-data channel's Diebold-Mariano t-statistic
> and QLIKE economic improvement.
>
> The channel-specific reading reaches a clear conclusion: across seven
> asset classes spanning US broad equity (SPY), US technology equity (QQQ),
> precious-metal commodity (GLD), energy commodity (USO), long-duration
> Treasuries (TLT), cryptocurrency (BTC-USD), and emerging-market equity
> (EEM), **no alt-data channel delivers Harvey-threshold improvement over
> the asset-class native IV under PIT alignment**. The only marginal
> exception is the TLT / financial-stress channel at `pit_shift0` (DM
> t = +3.74), which we characterise in §5.3 as a regime-artefact rather
> than a replicable rates-channel signal. Native IV proxies (^VIX, ^VXN,
> ^OVX, ^GVZ, ^MOVE, and ^VXEEM-or-proxy with rv30 robustness) **dominate
> at the asset-class-specific channel level**.

### A.3 Version A — §5 section structure

| § | Title | Word target |
|---|-------|------------:|
| 5.1 | Alt-data channels per asset class: panorama construction | 300 |
| 5.2 | Channel-by-channel results (Table 5.1 + Table 5.2) | 450 |
| 5.3 | The TLT / financial-stress channel outlier | 400 |
| 5.4 | ^VXEEM channel availability and the EEM dual-baseline | 200 |
| 5.5 | Channel-specific summary commitment | 250 |
| 5.6 | Limitations: unexamined channels | 200 |

### A.4 Version A — cherry-pick locations in `body_v3.tex`

- Replace current §5 (whichever section treats cross-asset; in `main_v3.tex`
  the era-stability section at line 533 and sufficiency summary at
  line 806).
- Reframe K1208 draft headings into **channel terminology**: "the EPU
  channel", "the financial-stress channel", "the native IV channel",
  "rates-specific channels".
- Insert Table 5.1 with a **channel grouping** header row that maps each
  alt-data spec to the channel it represents:
  - `base` column: "AR(1)-only (no channel)"
  - `epu` column: "Economic-uncertainty channel"
  - `finstress` column: "Financial-stress channel"
  - `all` column: "Kitchen-sink (all channels + native IV)"
- Appendix A (shared template) is cited in §5.4 as the formal
  channel-availability audit and in §5.3 as the TLT channel-artefact
  robustness grid.

### A.5 Version A — narrative commitment text (drop-in)

> **Under PIT publication-lag alignment, no alt-data channel tested
> (economic-uncertainty, financial-stress, or the kitchen-sink combination)
> delivers Harvey (2016) |t| > 3 improvement over the asset-class native IV
> baseline for any of SPY, QQQ, GLD, USO, TLT, BTC-USD, or EEM. The single
> Harvey-threshold cell (TLT / financial-stress, DM t = +3.74 at
> `pit_shift0`) fails (i) the 5% QLIKE economic gate, (ii) the `pit_shift1`
> lag-robustness check, and (iii) the kitchen-sink specification, and is
> therefore characterised as a non-structural regime artefact rather than
> a replicable rates-channel signal. Asset-class-specific native IV indices
> — ^VIX, ^VXN, ^OVX, ^GVZ, ^MOVE, and the ^VIX-plus-rv30 dual baseline for
> EEM — dominate all tested alt-data channels in the 7-asset panorama.**

### A.6 Version A positioning (why this framing)

- **Claim scope is modest.** "No channel we tested beats native IV for the
  assets we tested" is harder to attack than "native IV is universally
  sufficient".
- **Aligns with existing Paper 4 vocabulary.** `main_v3.tex` already uses
  channel language ("behavioral channels" line 210, "fear channel"
  line 226, "eleven signal families... represents one channel of
  information" line 806). Version A extends this vocabulary rather than
  introducing new terminology.
- **Opens natural follow-up structure.** Each unexamined channel (credit
  spreads, insider flows, options skew beyond ^VIX) becomes a clear future
  cell in the taxonomy.
- **Matches user commit `7ecab636`** (2026-04-17) "channel-specific pivot".

---

## Version B — UNIVERSAL_NULL Framing

### B.1 §5 Title (Version B)

> **Section 5: Cross-Asset Universality of Native IV Sufficiency**

### B.2 Opening narrative (Version B)

> Section 4 established VIX sufficiency for SPY under point-in-time
> release-calendar alignment of five alt-data indicators. Section 5 asks
> whether that result **generalises across asset classes**, or whether it
> is S&P 500-specific. We construct a 7-asset panorama spanning US broad
> equity (SPY), US technology (QQQ), precious-metal commodity (GLD),
> energy commodity (USO), long-duration Treasuries (TLT), cryptocurrency
> (BTC-USD), and emerging-market equity (EEM), and run the identical
> K1116c protocol on each: weekly realised volatility target; AR(1) +
> native IV proxy baseline; three alt-data specifications; Harvey |t| > 3
> and 5% QLIKE gates.
>
> The panorama verdict is **universal**: native implied-volatility proxies
> are sufficient for one-step-ahead realised-volatility forecasting across
> all seven asset classes. Alt-data indicators cannot deliver Harvey-threshold
> improvement under PIT publication-lag alignment in any cell except TLT /
> financial-stress, which fails three independent robustness checks (§5.3)
> and is disposed of as a regime artefact. The v3 "native IV sufficient"
> framing, previously limited to SPY, now carries **7/7 cross-asset panorama
> support** anchored in four OOS-verified, code-reviewed experiments.

### B.3 Version B — §5 section structure (K1208 draft verbatim)

| § | Title | Word target |
|---|-------|------------:|
| 5.1 | Panorama overview | 350 |
| 5.2 | Results by asset class (Table 5.1 + Table 5.2) | 400 |
| 5.3 | The TLT finstress outlier: lag-sensitive regime artefact | 400 |
| 5.4 | Data-availability caveat: ^VXEEM and the EEM cell | 250 |
| 5.5 | Final narrative commitment | 250 |
| 5.6 | Limitations and future work | 350 |

### B.4 Version B — cherry-pick locations in `body_v3.tex`

- **Full §5 replacement** with `experiments/k1208/k1208_draft.md` content.
- Integrate Table 5.1 (28-cell panorama) verbatim as the main result table.
- Integrate Table 5.2 (QLIKE improvement vs 5% gate) as the economic-gate
  summary table.
- Update abstract and §1 introduction to claim "universal native-IV
  sufficiency across seven asset classes" rather than "SPY native-IV
  sufficiency with cross-asset hints".
- Appendix A (shared template) is cited in §5.4 as the ^VXEEM audit and
  dual-baseline justification.

### B.5 Version B — narrative commitment text (drop-in, K1208 verbatim)

> **Native implied-volatility proxies (^VIX, ^VXN, ^OVX, ^GVZ, ^MOVE, and
> ^VXEEM-or-proxy with rv30 robustness) are sufficient for one-step-ahead
> realised-volatility forecasting across seven asset classes: US broad
> equity (SPY), US technology equity (QQQ), precious-metal commodity
> (GLD), energy commodity (USO), long-duration Treasuries (TLT),
> cryptocurrency (BTC-USD), and emerging-market equity (EEM).
>
> Alt-data regressors (economic policy uncertainty, weekly leading-economic
> uncertainty, and the NFCI / ANFCI / STLFSI financial-stress family)
> cannot deliver Harvey (2016) |t| > 3 improvement over the native-IV
> baseline under point-in-time publication-lag alignment. Only TLT /
> finstress exceeds that threshold at `pit_shift0` (DM t = +3.74), but it
> fails (i) the 5% QLIKE economic gate (+0.50% improvement), (ii) the
> `pit_shift1` robustness check (collapses to +2.00), and (iii) the
> kitchen-sink `all` spec (DM t = -5.67), and is therefore characterised as
> a non-structural regime artefact rather than a replicable rates-specific
> signal.**

### B.6 Version B positioning (why this framing)

- **Strong negative-result methodology contribution.** UNIVERSAL_NULL is a
  publishable finding in the Harvey (2016) / Harvey, Liu, Zhu (2016) tradition
  — it advertises a pre-registered cross-asset replication that cannot be
  rescued by alt-data, rather than a cherry-picked positive finding.
- **Matches K1203 gate language.** K1203 README §4 explicitly declares
  `UNIVERSAL_NULL_7_OF_7 with TLT caveat` as the verdict and unlocks the
  narrative-state-machine gate under that banner.
- **K1208 draft already written in this language.** Zero text-rewrite cost
  — cherry-pick is literally copy-paste of `k1208_draft.md` into
  `body_v4.tex`.
- **Paper positioning is unified.** Introduction, abstract, §4, §5, and
  conclusion all carry the same "native-IV sufficient" thesis at different
  scales (SPY → 7-asset universe). Version A requires introduction edits to
  soften the universal claim to channel-specific.

---

## Decision Matrix (for user)

| Consideration | Version A (Channel-Specific) | Version B (UNIVERSAL_NULL) |
|---------------|:-----------------------------:|:---------------------------:|
| Matches user commit `7ecab636` | YES | partial |
| Matches K1203 gate language | partial | YES |
| Reviewer-attack surface | smaller (modest claim) | larger (strong claim) but data-backed |
| Alignment with existing `main_v3.tex` vocabulary | YES (channels already used) | partial (needs abstract + §1 update) |
| K1208 draft re-use | heavy rewrite | verbatim copy-paste |
| Future-work hook | rich (untested channels) | narrower (more assets, HAR-RV daily) |
| Paper positioning | asset-class taxonomy | universal negative-result methodology |
| Word count §5 | ~1,800 | ~1,800 (K1208 verbatim) |

**Recommendation for main thread**: execute whichever version the user
selects. If the user declines to pick within the active session, default to
**Version B** because (a) K1203 session gate explicitly unlocked under
UNIVERSAL_NULL language and (b) the K1208 draft is already written in this
framing, minimising rewrite risk. Version A remains available as a
lower-risk alternative if a reviewer attacks the universal claim.

---

## Common Integration Steps (both versions)

Once a version is picked, the main thread executes:

1. Create `paper/vix-sufficiency/body_v4.tex` by copying `body_v3.tex`.
2. Apply the chosen version's §5 rewrite (A.1-A.5 or B.1-B.5).
3. Integrate shared Appendix A (template in `experiments/k1218/`) via
   `\appendix` + `\section{...}`.
4. Replace or insert Table 5 (28-cell panorama) using canonical numbers in
   §0.2 of this guide.
5. Update bibliography additions:
   - Both versions: Harvey, Liu, Zhu (2016) multiple-testing; Patton (2011)
     QLIKE; Harvey, Leybourne, Newbold (1997) DM-HLN; Croushore & Stark
     (2001) vintage-data; Aboura & Chevallier (2015) EM VIX spillovers.
   - Version A additional: Baker, Bloom, Davis (2016) EPU as channel
     exemplar; Brave & Butters (2011) NFCI channel.
   - Version B additional: Harvey (2017) pre-registration; Ioannidis (2005)
     negative-result bias.
6. Run `xelatex main_v4.tex` twice to resolve cross-references.
7. Run `uv run volpred ops paper-update --paper-id vix-sufficiency` to sync
   PDF slug, Supabase, and Mirror.
8. Commit with message indicating the chosen version:
   - Version A: `Paper 4 body_v4 channel-specific framing (CONFLICT-A4 resolved: A)`
   - Version B: `Paper 4 body_v4 UNIVERSAL_NULL_7_OF_7 framing (CONFLICT-A4 resolved: B)`

---

## User Action Required

Pick **Version A** or **Version B** before main thread executes. Both
guides are ready within `experiments/k1225/`; the chosen version's §5
narrative, table structure, and cherry-pick locations are fully specified
above.

Main thread should not proceed to `body_v4.tex` until this conflict is
resolved — running with the wrong framing risks a second rewrite round
that contradicts either user intent (A) or the K1203 session gate (B).

---

## Source traceability

| Artefact | Location | Role |
|----------|----------|------|
| §5 panorama draft (UNIVERSAL_NULL) | `experiments/k1208/k1208_draft.md` | Version B verbatim source |
| 7/7 panorama + gate | `experiments/k1203/README.md` | Gate evidence for both |
| Appendix template | `experiments/k1218/k1218_appendix_draft.md` | Shared Appendix A reuse |
| Panorama CSV | `experiments/k1208/k1208_panorama_table.csv` | 28-cell exact 4-decimal |
| Canonical synthesis | `experiments/k1208/k1208_results.json` | Structured metadata |
| Paper body | `paper/vix-sufficiency/body_v3.tex` (+ `main_v3.tex`) | Pre-rewrite state |
| This guide | `experiments/k1225/k1225_dual_framing_guide.md` | CONFLICT-A4 resolution |

---

*K1225 produces `.md` + `.json` only (per CLAUDE.md paper-workflow rule:
worktree agents must not write `.tex`). Main thread owns the `body_v4.tex`
cherry-pick once the user picks Version A or Version B.*
