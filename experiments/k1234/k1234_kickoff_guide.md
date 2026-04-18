# Paper 10 (crypto-fear-channel) §2–§9 Kickoff Guide

**Source**: K1229 audit (`experiments/k1229/k1229_papers_audit.md`) + `paper/crypto-fear-channel/outline.md` + `body_v0_intro.tex`
**Produced by**: K1234 (2026-04-17, worktree agent-ad158010)
**Scope**: §2–§9 body drafting roadmap for main-thread adoption

---

## 1. Current State

| Item | Status | Source |
|------|--------|--------|
| Outline | ✅ Drafted (`outline.md`, 12 sections) | `paper/crypto-fear-channel/outline.md` |
| §1 Introduction | ✅ Drafted v0 (`body_v0_intro.tex`) | 4 stylized-fact paragraphs + abstract |
| Abstract | ✅ Drafted v0 (in `body_v0_intro.tex`) | N=2,812, 2015-02 to 2026-04 |
| References starter list | ✅ 8 inline `\bibitem` in `body_v0_intro.tex` | Bouri, Corbet, Matkovskyy, Hatemi-J, Diebold, Harvey, Conrad, \ldots |
| §2 Literature review | ⛔ **PENDING** | — |
| §3 Data and preliminaries | ⛔ **PENDING** | — |
| §4 Methodology | ⛔ **PENDING** | — |
| §5 Main results | ⛔ **PENDING** | — |
| §6 Robustness | ⛔ **PENDING** | — |
| §7 Forecasting and economic significance | ⛔ **PENDING** | — |
| §8 Discussion | ⛔ **PENDING** | — |
| §9 Conclusion | ⛔ **PENDING** | — |
| README.md / data_sources.md / experiments.md | ⛔ **MISSING** | paper-guide §"Self-contained" requires before body drafting |
| Target journal | ✅ JIFMIM → JEF → FRL backup | `outline.md` line 8 |

**Total pages target**: ~30 (per `outline.md` line 33). With §1 at 3 pages already drafted, §2–§9 have ~27 pages = ~9,000 words of body text remaining (excluding tables, figures, references).

---

## 2. Proposed §2–§9 Structure

The following expands `outline.md` lines 35–63 into section-level writing briefs with target word counts, required subsections, primary K-source, and key claims.

### §2 Literature Review (~1,000 words, ~3 pages)

**Subsections**:
- §2.1 Volatility spillover literature (Diebold & Yilmaz 2012; Engle 2002 DCC)
- §2.2 Cryptocurrency–equity linkage (Bouri 2020, Corbet 2018, Matkovskyy & Jalan 2019)
- §2.3 Asymmetric and tail causality (Hatemi-J 2012; Koenker & Bassett 1978 QR)
- §2.4 Positioning of the present paper (gap statement)

**Key claims to support**:
- Prior literature focuses on level/return spillover, not asymmetric volatility.
- Most studies stop at 2020 or exclude COVID sub-period.
- No prior paper combines asymmetric Granger + QR + Diebold-Yilmaz + honest OOS null in one framework (outline.md line 79).

**Primary K-source**: None (literature only). Use `body_v0_intro.tex` reference list as starter; expand to ~25 citations for a full §2.

**Drafting approach**: Main thread may dispatch `citation-verifier` / `academic-finance-reviewer` subagent for focused lit collection; use `sci-hub` skill to confirm DOIs.

---

### §3 Data and Preliminaries (~600 words, ~2 pages)

**Subsections**:
- §3.1 Sample construction — SPY, BTC-USD, VIX daily 2015-02 to 2026-04 (N=2,812)
- §3.2 Return and realized volatility definitions
- §3.3 Descriptive statistics (mean, std, skew, kurt, JB test) — Table 1
- §3.4 Correlation matrix — unconditional (Table 1 or 2)
- §3.5 Preliminary diagnostics — ADF stationarity, Ljung-Box autocorrelation

**Key claims**:
- All three series are stationary in returns.
- BTC return volatility is ~3–4× SPY.
- Unconditional corr(BTC_rv, VIX) already non-trivial but masks regime structure.

**Primary K-source**: K639 (2015-02 sample start confirmed) + K1025 (N=2,812 confirmed).

**Data source**: yfinance (SPY, BTC-USD, VIX) — free, no license restrictions. Period is hardcoded in K1025 scripts.

---

### §4 Methodology (~800 words, ~3 pages)

**Subsections** (mirrors `outline.md` §4 breakdown):
- §4.1 Symmetric and asymmetric Granger causality (Hatemi-J 2012 cumulative-sum decomposition)
- §4.2 Quantile regression for tail dependence (Koenker & Bassett 1978; τ grid 0.05–0.95)
- §4.3 Diebold-Yilmaz spillover index (252-day rolling; 10-day FEVD horizon)
- §4.4 EWMA / DCC correlation conditional on VIX regime
- §4.5 Forecasting evaluation framework — AR(p) baseline vs. AR(p) + BTC-RV; Diebold-Mariano (Diebold & Mariano 1995) under Harvey (2016) |t|>3 threshold

**Key equations** (to formally render in .tex):
- Asymmetric Granger: $\Delta y_t^{\pm} = \sum_{k=1}^{p} \alpha_k^{\pm} \Delta y_{t-k}^{\pm} + \sum_{k=1}^{p} \beta_k \Delta x_{t-k}^{\pm} + \varepsilon_t$
- QR: $Q_{VIX_t}(\tau | BTC_{rv,t}) = \alpha(\tau) + \beta(\tau) BTC_{rv,t}$
- DM statistic: $DM = \bar{d} / \sqrt{\hat{V}(\bar{d})/T}$ with $d_t = L(e_{1t}) - L(e_{2t})$

**Primary K-source**: K1025 for full framework + K746b for asymmetric Granger method reference.

**Note**: Reuse K1025 code comments verbatim in text — per `outline.md` line 94, main-thread approved this.

---

### §5 Main Results (~1,500 words, ~4 pages)

**Subsections** (per `outline.md` §5):
- §5.1 Asymmetric Granger causality — Table 2 (F-stats, 10 lags, pos/neg branches) + Figure 1 (p-value heatmap)
- §5.2 Tail dependence — Figure 2 (QR coefficient path across τ ∈ [0.05, 0.95]) + Table 3 (τ=0.5, 0.75, 0.90, 0.95 coefficients)
- §5.3 Regime-conditional correlation — Figure 3 (EWMA corr by VIX quartile) + Table 4 (mean corr by regime)

**Key claims** (with numbers from K1025):
- F-stat (BTC_neg → VIX, lag 5): significant (exact value from `k1025_results.json`)
- F-stat (BTC_pos → VIX, lag 5): non-significant at any conventional level
- QR coefficient at τ=0.5: 2.61; at τ=0.95: 22.31 → **8.5× amplification** (outline.md line 24, body_v0_intro.tex paragraph "Tail concentration")
- EWMA corr(BTC, SPY): rises in high-VIX regime → **BTC is not a safe-haven** (outline.md line 31)

**Primary K-source**: K1025 for all three subsections; supplement with K746b asymmetric Granger where K1025 does not cover lag-by-lag.

**Figure files required**: 3 main figures. Check `experiments/k1025/` for existing .png outputs; may need to regenerate for paper-quality typography. Decide: soft-link from `experiments/k1025/` or regenerate in `paper/crypto-fear-channel/figures/`.

---

### §6 Robustness (~800 words, ~3 pages)

**Subsections** (per `outline.md` §6):
- §6.1 Rolling Diebold-Yilmaz spillover (COVID vs pre/post, 252-day window) — Figure 4
- §6.2 Sub-period Granger (5 regimes: 2015–17, 2018–19, 2020, 2021–22, 2023–26) — Table 5
- §6.3 Pre-ETF vs post-ETF microstructure (2015–2018 vs 2019–2026) — Table 6

**Key claims**:
- BTC is a **net receiver** in DY framework (outline.md line 26).
- Granger significance concentrated **only in 2020** ($F=11.05$, $p<10^{-6}$) — other 4 sub-periods fail to reject.
- ETF-era robustness: sign and magnitude preserved post-2019.

**Primary K-source**: K1025 (all three subsections).

**Possible gap**: pre-ETF vs. post-ETF split — verify K1025 explicitly provides this, or mark as "needs new experiment" (see §3 below).

---

### §7 Forecasting and Economic Significance (~700 words, ~2 pages)

**Subsections** (per `outline.md` §7):
- §7.1 Out-of-sample DM test — AR(VIX) vs AR(VIX) + BTC_rv, OOS 1,826 days (2019–2026) → **honest NULL** ($t=-0.98$, $p=0.33$)
- §7.2 Crisis-period sub-forecast — restrict OOS to VIX > 25 days; does BTC_rv help there?

**Key claims**:
- In-sample Granger causality **does not** translate to OOS predictive power — Granger ≠ forecastability (outline.md line 29).
- Harvey (2016) |t|>3 threshold not met → per contemporary methodology standards, BTC_rv is not a usable VIX predictor on average.
- Possibly: crisis-conditional sub-forecast shows improvement (hypothesis; verify from K1025 JSON).

**Primary K-source**: K1025 (§7.1 confirmed); §7.2 conditional sub-forecast — **verify existence in K1025 before drafting**; if missing, need new experiment (see §3).

**Tone**: This is the honest-NULL section. Report transparently; do not bury in appendix.

---

### §8 Discussion (~600 words, ~2 pages)

**Subsections** (per `outline.md` §8):
- §8.1 Asymmetry mechanism — retail sentiment / margin / liquidation cascade hypotheses
- §8.2 Why Granger ≠ forecastability (sparse-signal argument)
- §8.3 Policy implications — BTC ETF margin design, prudential supervision in stress

**Key claims**:
- Retail-heavy BTC market transmits **fear, not euphoria** (body_v0_intro.tex §"Asymmetry" paragraph).
- Spillover is a **crisis-time amplifier**, not steady-state channel → margin/capital requirements should be regime-dependent.
- Sparse tail-concentrated signal + long OOS averaging → explains AR-augmentation null.

**Primary K-source**: Interpretive section; no new numbers. Cite K1025 / K746b / K639 for prior results only.

---

### §9 Conclusion (~300 words, ~1 page)

**Structure**:
- Paragraph 1: Restate 3 stylized facts (asymmetry, tail concentration, regime dependence).
- Paragraph 2: Forecastability gap headline.
- Paragraph 3: Contribution summary (3 contributions from body_v0_intro.tex last paragraph of §1).
- Paragraph 4: Limitations (single-asset SPY receiver, no IV data, COVID-only regime identification).
- Paragraph 5: Future research (memecoin comparison, Deribit IV extension, multi-asset receiver).

**Primary K-source**: None (summary only).

---

## 3. Required Supporting Experiments

| Claim | Needed K | Exists? | Verification | Action |
|-------|----------|---------|--------------|--------|
| BTC → SPY RV Granger (lag 1-10) | K639 | ✅ YES | `experiments/k639/k639_results.json` + `.py` + README | Use as-is |
| BTC_neg → VIX asymmetric Granger | K746b | ✅ YES | `experiments/k746b/k746b_bitcoin_vix_fixed_results.json` + `.py` + README | Use as-is |
| Full framework (asymm Granger + QR + DY + EWMA + 5-period) | K1025 | ✅ YES | `experiments/k1025/k1025_results.json` + `.py` + README | Use as-is |
| Crisis-period sub-forecast (§7.2) | TBD | ⚠️ **VERIFY** | Check K1025 `.json` for VIX>25-conditional DM | If missing → new K12xx: crisis-conditional OOS |
| Pre-ETF vs post-ETF split (§6.3) | TBD | ⚠️ **VERIFY** | Check K1025 sub-period breakdown | If only 5-period, may need new K12xx: 2-split ETF era |
| Memecoin comparison (open decision, `outline.md` line 85) | — | ❌ NO | — | **Main-thread decide**: in-scope or cut? |
| Deribit BTC IV (open decision, `outline.md` line 86) | — | ❌ NO | — | **Main-thread decide**: data not free historically; likely cut |
| Multi-asset receiver (SPY + GLD + TLT, `outline.md` line 87) | — | ⚠️ **PARTIAL** | K639 has SPY only; would need extension | **Main-thread decide**: add or cut |

### Minimum experiment gap to start drafting

**ZERO new experiments required** to start drafting §2–§5 + §8 + §9. Start body writing immediately with K639/K746b/K1025 as-is.

**Potential new experiments** (only if main-thread decides to include them):
- K12xx-A: Crisis-conditional (VIX>25) sub-forecast — verify first in K1025 JSON; if absent, 1-day experiment.
- K12xx-B: Pre-ETF vs post-ETF 2-split Granger — 1-day experiment; only if §6.3 claim must be made.
- K12xx-C: Multi-asset receiver (SPY+GLD+TLT) — 2-day experiment; may strengthen §6 but optional.

---

## 4. Writing Sequence (Recommended)

Ordered to build from factual base → mechanism → context → summary:

| Order | Section | Reason | Depends on |
|-------|---------|--------|------------|
| 1 | §3 Data | Establishes fact base, sets notation, minimal inference | Nothing |
| 2 | §4 Methodology | Specifies machinery before applying it | §3 notation |
| 3 | §5 Main Results | Applies §4 to §3 data; primary contribution | §3, §4; K1025 JSON |
| 4 | §6 Robustness | Extends §5 to sub-samples and alternative specs | §5 baseline; K1025 JSON |
| 5 | §7 Forecasting | Separate OOS analysis; honest-NULL highlight | §4 DM framework; K1025 JSON |
| 6 | §2 Literature Review | Written last because contribution framing depends on knowing §5–§7 results | §5–§7 headline |
| 7 | §8 Discussion | Interprets §5–§7 through mechanism + policy lens | §5, §6, §7 |
| 8 | §9 Conclusion | Summary + limitations + future research | All prior |

**Alternative**: If main-thread prefers linear 2→3→...→9 order, accept the trade-off that §2 may need rewriting after §5–§7 crystallize the contribution.

**Rationale for non-linear sequence**: `outline.md` line 89 already suggests this: "Draft Abstract + Introduction" first, then "Methodology section — reuse K1025 method descriptions directly", "Results tables from K1025/K639/K746b JSON (no new experiment needed)", only then "Literature review drafting".

---

## 5. Reproduction Package Parallel Tasks

Per `.claude/rules/paper-workflow.md` §"Self-contained paper folder", the 5 required items must be added **before first body drafting commits**. Current state:

| File | Exists? | Action |
|------|---------|--------|
| `paper/crypto-fear-channel/README.md` | ❌ NO | **Create before §2 draft**: title, target journal, status=kickoff, K list (K639, K746b, K1025), data summary |
| `paper/crypto-fear-channel/data_sources.md` | ❌ NO | **Create before §2 draft**: yfinance (SPY, BTC-USD, VIX), period 2015-02 to 2026-04, daily, no license restriction |
| `paper/crypto-fear-channel/experiments.md` | ❌ NO | **Create before §2 draft**: K639 (BTC→SPY Granger), K746b (asymm BTC→VIX), K1025 (full framework) |
| `paper/crypto-fear-channel/scripts/README.md` | ❌ NO | **Create before §5 draft**: entry points pointing at `experiments/k639/`, `experiments/k746b/`, `experiments/k1025/` |
| `paper/crypto-fear-channel/figures/` | ❌ NO | **Create before §5 draft**: 4 main figures (from K1025 .png); soft-link or regenerate |
| `paper/crypto-fear-channel/results/` or `tables/` | ❌ NO | **Create before §5 draft**: output tables (1 descriptive + 5 main) as `.tex` fragments or `.pdf` |
| `paper/crypto-fear-channel/reproduce.py` | ❌ NO | **Create before first submission**: one-shot script that re-runs K1025 + regenerates main tables/figures |

**Why create early**: per user 2026-04-17 feedback — "投稿時才補會措手不及". Building these in parallel with §2–§9 drafting avoids pre-submission scramble.

---

## 6. Estimated Writing Effort

| Phase | Duration | Task |
|-------|----------|------|
| Pre-flight (before any body draft) | 1 day | README.md + data_sources.md + experiments.md + scripts/README.md + figures/ scaffolding |
| §3 Data | 0.5 day | ~600 words + Table 1 (descriptive stats) |
| §4 Methodology | 1 day | ~800 words + 4 equation blocks |
| §5 Main Results | 2 days | ~1,500 words + 3 tables + 3 figures |
| §6 Robustness | 1.5 days | ~800 words + 3 tables + 1 figure |
| §7 Forecasting (honest NULL) | 1 day | ~700 words + 1 table |
| §2 Literature Review | 1.5 days | ~1,000 words + 15 new citations |
| §8 Discussion | 1 day | ~600 words |
| §9 Conclusion | 0.5 day | ~300 words |
| Internal review (latex-academic-reviewer) | 1 day | `paper-review-cycle` skill |
| Reproduce.py + reproduce_report.json | 0.5 day | paper-guide §"three-way consistency" check |
| Citation verification (citation-verifier) | 0.5 day | DOI / author / quote check |
| **Subtotal: drafting (with zero new experiments)** | **~11 days** | — |
| Optional new experiments (K12xx-A/B/C) | 1–4 days | Only if open decisions resolved toward inclusion |
| **Total: ready-for-first-submission** | **~2–3 weeks (main-thread)** | — |

Assumes main-thread focused 2–3 hour sessions per weekday; reviewer cycle by academic-finance-reviewer skill after first complete draft.

---

## 7. Open Decisions Main-Thread Must Resolve

These are carried forward from `outline.md` lines 83–87. Resolving them shapes the §6 and §8 scope:

1. **Include memecoin (DOGE / PEPE / SHIB) as alternative fear channel?** — would require new K12xx-D; outline calls it "would need new experiment". **Recommend: defer to R&R round; keep out of v1**.
2. **Add Deribit BTC options IV?** — data not free historically. **Recommend: cut; acknowledge in §9 limitations**.
3. **Single-asset (SPY) vs multi-asset (SPY + GLD + TLT) receiver?** — main contribution. **Recommend: v1 = SPY only; multi-asset = v2 or R&R round**.
4. **Forecasting section length — honestly-NULL in body or relegate to appendix?** — **Recommend: keep in body §7 as headline honest-NULL; reinforces Harvey 2016 methodology standard and distinguishes paper from correlation-only literature**.

---

## 8. Risk Notes for Main-Thread

- **Paper narrative state machine rule** (CLAUDE.md §"自動化與控制面"): Single experiments must not directly trigger paper body rewrites. K1234 is planning only — does not modify body. When main-thread adopts: at least 3 complementary experiments (K639 + K746b + K1025) already exist, satisfying the 3-experiment minimum.
- **Lookahead bias** (CLAUDE.md §"研究誠實原則" 11): verify K1025 DM test uses `signal.shift(1)` or equivalent lag; Granger causality by definition has lag, but OOS DM must also respect lag discipline. Codex-review K1025 before finalizing §7.
- **Three-way consistency** (paper-guide): once §5 numbers land in .tex, `reproduce.py` must reproduce them bit-for-bit from K1025 JSON or be revised per rule (a)/(b)/(c).
- **Honest NULL reporting** (CLAUDE.md §"研究誠實原則" 9): §7 DM null must NOT be spun as "weak evidence of predictability". Language must clearly state: Granger ≠ forecastability; BTC_rv is not a usable VIX predictor on average.

---

## 9. Output Checklist for Main-Thread

- [ ] Create `paper/crypto-fear-channel/README.md`
- [ ] Create `paper/crypto-fear-channel/data_sources.md`
- [ ] Create `paper/crypto-fear-channel/experiments.md`
- [ ] Create `paper/crypto-fear-channel/scripts/README.md`
- [ ] Create `paper/crypto-fear-channel/figures/` (soft-linked or regenerated)
- [ ] Resolve 4 open decisions (§7 above)
- [ ] Verify §6.3 pre-ETF/post-ETF split exists in K1025 or queue K12xx-B
- [ ] Verify §7.2 crisis-conditional sub-forecast exists in K1025 or queue K12xx-A
- [ ] Draft §3 → §4 → §5 → §6 → §7 → §2 → §8 → §9 (recommended sequence)
- [ ] Run `paper-review-cycle` after first complete draft
- [ ] Run `citation-verifier` on full reference list before submission
- [ ] Build `reproduce.py` and run `reproduce_report.json` pre-submission
- [ ] Apply paper-guide "three-way consistency" check before first submission
