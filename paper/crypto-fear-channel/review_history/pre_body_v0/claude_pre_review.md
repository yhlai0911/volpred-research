# Pre-Body Review v0: body_v0_intro.tex

**Reviewer**: Claude (feature-dev:code-reviewer subagent `ad7deab7c9390278f`)
**Date**: 2026-04-20 01:08 UTC
**Stage**: kickoff — intro drafted, body pending
**Scope**: `paper/crypto-fear-channel/body_v0_intro.tex` + `outline.md` + `README.md` + `experiments/k1025/k1025_results.json`
**Purpose**: Pre-audit groundwork for Codex task_7d2c (scheduled 2026-04-24 10:27 UTC wake), so Codex can focus on substantive gaps not low-hanging fixes.

---

## 1. Overall Impression

Well-structured kickoff draft. Motivation-gap-contribution triad present, three stylized facts clearly telegraphed, honest NULL reporting is a genuine strength. Abstract publication-ready in tone.

**Key concerns**:
- Several numbers in intro/abstract require source-binding verification against K1025 JSON (2 discrepancies found)
- Asymmetric-Granger methodology description misattributes Hatemi-J (2012)
- Sample-start rationale and BTC exchange transparency missing
- Literature coverage thin for JIMFIM tier

**Readiness**: Acceptable for kickoff. Must resolve HIGH issues before body drafting.

## 2. HIGH Priority Issues

### H1 — Granger lag coverage mismatch
- **File/line**: `body_v0_intro.tex` L36 (asymmetry paragraph), L24 (abstract)
- **Problem**: Intro claims asymmetric Granger "lags 1 through 10"; K1025 JSON `.asymmetric_granger.btc_neg_to_vix` only covers lags 1-5. Symmetric test covers 1-10; asymmetric only 1-5.
- **Fix direction**: Change asymmetric context to "lags 1 through 5"; add `% source: experiments/k1025/k1025_results.json .asymmetric_granger.btc_neg_to_vix (lags 1-5)`.
- **Confidence**: 95

### H2 — Hatemi-J (2012) mischaracterization
- **File/line**: L36
- **Problem**: Intro attributes positive/negative RV separation to Hatemi-J (2012) framework. Hatemi-J uses CUSUM partial-sum decomposition of levels; K1025 likely implements simpler returns decomposition. This is technical method attribution error — referee will flag.
- **Fix direction**: Read `experiments/k1025/k1025.py` to confirm actual method, then either correct description or cite Hatemi-J as motivating asymmetric testing (not specific implementation).
- **Confidence**: 85

### H3 — QR beta sign reversal unexplained
- **File/line**: L38 (tail concentration), L24 (abstract)
- **Problem**: Intro frames "essentially flat at low-to-median quantiles (2.61 at τ=0.5)" but JSON shows β=-2.86 at τ=0.05, -2.34 at τ=0.25 — negative to positive sign reversal. "8.5× amplification" loses meaning if sign flips. Substantive interpretive issue.
- **Fix direction**: Explicitly acknowledge sign reversal — negative at low-VIX quantiles (bull-market coexistence), positive at median/upper. Reframe 8.5× as upper-tail amplification vs median (τ=0.95/τ=0.5). Actually a richer story.
- **Confidence**: 92

### H4 — BTC data source/exchange not specified + yfinance drift risk
- **File/line**: L24 abstract + implicit throughout
- **Problem**: Abstract says "BTC-USD" without exchange. yfinance's BTC-USD is Coinbase but undisclosed. No `data/` snapshot per paper-workflow rule → exposed to P8/P9 yfinance drift precedent (sign flip on β, forced errata).
- **Fix direction**: (a) Disclose exchange in Section 3 + abstract parenthetical "(Coinbase spot, via Yahoo Finance)". (b) Pin `data/btc_spy_vix_snapshot.csv` with `auto_adjust=False` BEFORE body drafting, mandated by paper-workflow snapshot pinning rule.
- **Confidence**: 90

### H5 — No reproduce.py → paper cannot enter review stage per gate
- **File**: `README.md` lists as pending
- **Problem**: Paper-workflow rule: reproduce.py + match_rate≥95% + green alert = review-stage prerequisite. P9 garch-x-vix lesson (submitted with full review history but missing reproduce gate) is direct precedent.
- **Fix direction**: Create `paper/crypto-fear-channel/reproduce.py` scaffolding in parallel with body drafting; validate 6 key numbers (QR betas, DM stat, COVID F-stat). Track as hard pre-review gate.
- **Confidence**: 88

## 3. MEDIUM Priority Issues

### M1 — Sample start 2015-02 rationale absent
Add one sentence in Section 3 explaining 2015-02 start (likely BTC-USD volume threshold or yfinance data availability).

### M2 — COVID subperiod n=253 small-sample concern
Acknowledge n=253 for COVID window; robustness check with ±3-month bandwidth.

### M3 — DY net-receiver magnitude missing
BTC net spillover = -76.9% is striking — add magnitude in regime-dependence paragraph.

### M4 — Bidirectional Granger buried
VIX → BTC RV (lag 1: F=6.71, p=0.010) — acknowledge bidirectionality to prevent "cherry-picked causality direction" criticism.

### M5 — Literature coverage thin
7 references in stub; JIMFIM expects 25-35. Missing: Conlon & McGee (2020) COVID safe-haven, Guesmi et al. (2019) crypto portfolio, Baur et al. (2018) BTC speculative, Ji et al. (2019) BTC-equity connectedness, Akhtaruzzaman et al. (2021) COVID contagion.

### M6 — Forecasting section placement inconsistent
Outline flags null-result placement as open decision; intro pre-commits to full Section 7. Resolve + lock outline before body.

### M7 — ETF regime (2024-01) not in structured analysis
Intro raises ETF framing; K1025 groups 2023-2026 non-significantly. Add Chow/Bai-Perron break test at 2024-01 OR temper framing.

### M8 — Corbet et al. (2018) citation mismatch
Cited for "crisis co-movement" but actually about FOMC reactions (Economics Letters, 165:28-34). Replace with Conlon & McGee 2020 or Ji et al. 2019.

## 4. LOW / MINOR

- **L1**: Abstract ~220 words; JIMFIM typically 150 max
- **L2**: `\citet` vs `\citep` mixed; finance journals prefer `\citep` for parenthetical
- **L3**: Passive voice in contribution paragraph ("is reported transparently")
- **L4**: Missing `\usepackage{hyperref}`, `microtype`
- **L5**: Hand-formatted bibliography stub → migrate to `.bib` file for citation-verifier compat

## 5. Gaps for Codex Pre-Body Audit (2026-04-24 task_7d2c)

**Gap A — Claim-to-JSON number cross-check (HIGH, blocks body)**
Systematically verify every number in intro/abstract against K1025 JSON field paths. Produce `reproducibility_audit/claim_check_v0.json` mapping each stat to JSON field. Numbers to verify: QR beta τ=0.5 (2.61 vs 2.613), τ=0.95 (22.31 vs 22.308), DM -0.98 vs -0.980, COVID F=11.05 vs 11.051, 8.5× ratio vs 8.54. H1 lag coverage also lives here.

**Gap B — K1025.py asymmetric Granger implementation**
Read `experiments/k1025/k1025.py` to confirm whether asymmetric test uses Hatemi-J CUSUM partial sums or simpler positive/negative returns decomposition. H2 methodology description correction depends on this.

**Gap C — Literature gap list with candidate citations**
Produce 15-20 candidate papers (with DOIs) for BTC-equity spillover literature section: safe-haven (2018-2020), DCC crypto vol, crisis contagion (COVID 2020), ETF-era market structure (2024-2025). Feeds Section 2 body drafting.

**Gap D — Outline-to-body consistency audit**
Current outline 12 sections; intro roadmap references 9 (Sections 2-9). Reconcile Sections 10-12 (references/appendices/data statement) in intro roadmap OR renumber outline.

**Gap E — Reproduce.py scaffold**
Scaffold `paper/crypto-fear-channel/reproduce.py` reading K1025/K639/K746b results JSONs validating 6 key stats. Required before main-thread review cycle per project gate (prevent P9 failure pattern).

**Gap F — Data snapshot creation**
Run `scripts/snapshot_yfinance.py` (if covers BTC-USD/SPY/VIX) to pin `paper/crypto-fear-channel/data/snapshot_btc_spy_vix.csv` with `auto_adjust=False`. Mandated by paper-workflow snapshot pinning rule. Protects against H4 yfinance drift risk.

---

**Summary for main-thread reviewer**: 5 HIGH + 8 MEDIUM + 5 LOW + 6 Codex-gaps. Highest priority: H1 (numeric claim mismatch), H2 (method attribution), H4 (data transparency + snapshot), H5 (reproduce gate). Body drafting should wait until HIGH items + Codex Gap A+B resolved.
