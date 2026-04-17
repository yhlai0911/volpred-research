# Session 2026-04-17 Master Index (FINAL post-K1216c)

**Produced by**: K1226 worktree agent (`agent-ad8509ed`) consolidating K1212 delta + K1219 dashboard + K1220 briefing + K1222b post-K1216c revision guide + K1223/K1224 edit guides + K1216c ROOT_CAUSE_METHODOLOGY.

**Session duration**: ~14+ hours / ~45 K experiments (K1133–K1225 range) / ~$3500-4000 estimated spend (Claude Code billable + agent dispatch + worktree merges).

**Supersedes**: K1212 delta (early session), K1219 dashboard (mid-session), K1220 executive briefing (pre-K1216c). K1226 is the **final** session close briefing.

**Seed**: 42 (declared for compliance; K1226 produces Markdown + JSON only, no RNG).

**Purpose**: single authoritative close-of-session briefing so the user can approve immediate-ready cherry-picks and prioritise 6 remaining decision gates. All numerical claims are verbatim from upstream experiment JSONs / knowledge entries.

---

## 1. TL;DR (1 paragraph)

The Paper 2 §5 fragility discovery (K1213/K1216/K1216b) culminated in K1216c's ROOT_CAUSE_METHODOLOGY verdict — 9/9 markets (5 EM + AU + 4 DEV) are multistart-FRAGILE, which means the K1216b headline ρ = −0.071 was an asymmetric-refinement artefact, not a cross-market collapse. Applying the identical 100-start protocol panel-wide restores Spearman ρ(inst_pct, θ_rel) to **+0.379 (p = 0.201, N=13)** — Fisher-z indistinguishable from the canonical +0.441 (p ≈ 0.87). Paper 2 §5 narrative therefore **rebounds** to "modestly weaker but surviving ladder" + adds a **new methodological contribution** (multistart audit for shared-MIDAS joint pooled MLE). In parallel: Paper 1 Batch 2 (K1209 → K1224 edit guide, 7 items, 60–90 min) and Paper 6 Appendix A + errata (K1218 → K1223 edit guide, 6 items, 80–120 min) are both IMMEDIATE-READY for main-thread cherry-pick with no user decision. Paper 4 UNIVERSAL_NULL panorama (K1208) and Paper 3 K1128 4-branch synthesis (K1217) remain BLOCKED on user framing decisions. BTC GAS negative paper (K1214, 4829 words) is BLOCKED on go/no-go. Net: 2 papers READY, 4 papers BLOCKED on user decisions, 6 decision gates outstanding, ~80 min of no-decision execution unlocked immediately.

---

## 2. Critical Update since K1220 briefing

**K1216c** (`experiments/k1216c/`, commit `3cf6bc84`, knowledge id `f63b6e01`, completed 2026-04-18 147.5s runtime) is the **most important** update since the K1220 executive briefing. It resolves the K1216b fragility interpretation question:

- K1213 AU + K1216 BR/IN/MX + K1216b CH/ID established 5 EM markets + AU as multistart-FRAGILE under 100-start L-BFGS-B (LR 146–598, θ shifts 182–1976%).
- K1216b mixing refined EM with canonical DEV gave **asymmetric** Spearman ρ = −0.071 (p = 0.82, N=13) — interpreted provisionally as "cross-market ladder COLLAPSED".
- **K1216c runs the identical protocol on US/EU/JP/TW**: all 4 DEV markets also FRAGILE. LR stats: US +2836.68, EU +837.97, JP +235.57, TW +587.78 (all >> χ²(1) = 3.84).
- **9-market panel-wide refined Spearman ρ = +0.379 (p = 0.201, N=13)** — rebound from the K1216b artefact; Fisher-z test vs canonical +0.441 yields z = 0.16, p ≈ 0.87.

### Paper 2 §5 narrative state evolution (4 stages):

| Stage | Exp | Evidence scope | Primary ρ (N=13) | Narrative | Status |
|---|---|---|---|---|---|
| K1211 | K1165→K1171 canonical | single-start pooled MLE | +0.385 (N=13) / +0.441 (N=12) | STRENGTHENED ladder + 3 caveats | SUPERSEDED |
| K1215 | + K1213 AU multistart | AU above-ladder reclassification | +0.418 | STRENGTHENED + AU reclass | SUPERSEDED |
| K1222 | + K1216/K1216b 5 EM refined (DEV canonical) | **asymmetric** refinement | **−0.071, p=0.817** | COLLAPSE; WITHDRAWN | **SUPERSEDED — artefact** |
| **K1222b FINAL** | + K1216c 9-market audit | **symmetric**: 5 EM + AU + 4 DEV all refined | **+0.379, p=0.201, Harvey t=+1.36** | **MODESTLY WEAKER + NEW methodology contribution** | **ACTIVE** |

**K1222** (`experiments/k1222/k1222_revision_guide.md`, commit `75df1c8f`) is **SUPERSEDED** — it was written on top of the asymmetric-refinement artefact and framed the ladder as WITHDRAWN. **K1222b** (`experiments/k1222b/k1222b_revision_guide.md`, completed in same session) is the active FINAL revision guide; it restores the ladder to "modestly weaker but surviving" status and promotes the multistart methodology from appendix-only to an additional Paper 2 §5.4 contribution.

---

## 3. Per-Paper Master Status Matrix (post-K1216c)

| Paper | Target journal | Primary drafts | Edit guide | User decision required | Status |
|---|---|---|---|---|---|
| **Paper 1** leverage-direction | per README | K1209 Batch 2 (3574 words) | **K1224** (7 items, 60–90 min) | None | **READY** |
| **Paper 2** taiwan-vt | per README | K1211 (2380 w) + K1215 (both SUPERSEDED by K1222b) + **K1222b** (2925 w, FINAL) | pending K1226b rewrite-ticket (next session) | Confirm K1222b adoption (15 min read) | **READY (pending 15-min review)** |
| **Paper 3** vt-trend-following | per README | K1217 CONDITIONAL draft (4991 words) | pending | Pick pivot a / b / c (K1205 recommends **b**) | **BLOCKED** |
| **Paper 4** vix-sufficiency | per README | K1208 UNIVERSAL_NULL draft (1762 words) | pending K1225 (dual-framing A/B, not yet produced this session) | CONFLICT-A4: pick Version A channel-specific vs Version B UNIVERSAL_NULL | **BLOCKED** |
| **Paper 6** prg-periodic-garch | Finance Research Letters | K1218 Appendix A (930 words) + K1221 pre-submission audit | **K1223** (6 items, 80–120 min) | None | **READY** |
| **NEW BTC GAS** | Journal of Empirical Finance (primary) / JFEC (fallback) | K1214 negative-paper draft (4829 words) | none | Go / no-go; confirm paper slot | **BLOCKED** |

**Summary counts**: READY = 3 (Paper 1, Paper 2 pending-15-min, Paper 6). BLOCKED on user decision = 3 (Paper 3, Paper 4, BTC GAS).

---

## 4. Immediate-Ready Actions (no user decision needed, ~80 min total)

### 4.1 K1224 → Paper 1 body_v4 (60–90 min)

**Guide**: `experiments/k1224/k1224_edit_guide.md` (7 items, 1 dropped).

**Target file**: new `paper/leverage-direction/body_v4.tex` + `main_v4.tex`; baseline commit `0a442356` (Batch 1 already applied).

**Items** (exec top-to-bottom):

1. Table 3 vs Table 8 SPY 2023–24 GJR QLIKE aggregation footnote (K903 / K1188) — 10 min.
2. Table 6 VaR panel errata: 3 cells + Trinity pass-rate sentence + footnote (K1186 / K1206) — 20 min.
3. Table 4 base = GARCH(1,1) not GJR footnote (K1185) — 5 min.
4. Table 7 per-asset evaluation period disclosure (K1187) — 10 min.
5. Table 7 GLD 1.56 Sharpe forensic footnote (K1187) — 5 min.
6. New `paper/leverage-direction/experiments.md` (K903 / K1185–K1206) — 10 min.
7. Tables 10/11/12 + §4.2.3 unified pre-K footnote (K1198) — 10 min.

**Dropped**: γ_HM Sec 4.7 second disambiguation (Batch 1 commit `0a442356` Sec 5.4 already covers).

**Close**: `xelatex main_v4 × 2` + `uv run volpred ops paper-update --paper-id leverage-direction` + commit "Paper 1 errata batch 2 (v4)".

### 4.2 K1223 → Paper 6 body_v2 + Appendix A (80–120 min)

**Guide**: `experiments/k1223/k1223_edit_guide.md` (6 items, blockers 65–80 min + polish 15–45 min).

**Target file**: `paper/prg-periodic-garch/main.tex` (line 430); baseline commit `7d35418b` (Eq.(5)–(6) errata defence, v3 PDF).

**Items** (exec top-to-bottom):

1. B1 BLOCKER — Table 1 0050.TW OOS date 2019/12→2021/01 (K1221 audit 3.4) — 15 min.
2. B2 BLOCKER — Add Appendix A (K1200 clean-slate replication) before `\end{document}`; cross-ref at line ~206 — 55 min.
3. W1 WARN — New `paper/prg-periodic-garch/data/README.md` — 10 min.
4. W2 WARN — Append to `data_sources.md` — 5 min.
5. W3 WARN — Pin canonical in `reproduce.py` — 30 min.
6. B3 BLOCKER — `uv run volpred ops paper-update --paper-id prg-periodic-garch` — 5 min.

**Canonical Appendix A numbers (verbatim K1200)**: GJR QLIKE 0.8542/0.8544, PRG Extended QLIKE 0.7478/0.7355, DM t 6.004/6.128, Spearman ρ 0.5678/0.5761, OOS 1823/1823.

**Close**: `xelatex main × 2` + `paper-update` + commit.

### 4.3 Paper 2 §5 K1222b adoption (post 15-min review) — deferred

After 15-min user confirmation of K1222b supersession, main thread cherry-picks K1222b §3 block (13 items) into `paper/<paper2>/body_v(n+1).tex`. K1226b rewrite-ticket TBD next session.

---

## 5. Decision Gates Prioritised (post-K1216c)

| # | Priority | Gate | Change vs K1220 P# | User action | Time | Downstream impact |
|---|---|---|---|---|---|---|
| P1 | **HIGH** | Paper 2 §5 — adopt **K1222b FINAL** (ρ=+0.379 REBOUND + multistart methodology contribution) | **REVISED** from K1220 P1 (was "pick a/b/c path") — K1216c resolves choice: K1222b already consolidates | Read K1222b revision guide (2925 words) + confirm adoption | 15 min | Paper 2 submission credibility: ladder REBOUNDS; new methodological contribution §5.4 |
| P2 | MEDIUM | Paper 4 CONFLICT-A4 — channel-specific (prior decision `7ecab636`) vs UNIVERSAL_NULL (session gate K1203) | **UNCHANGED** from K1220 P2 | Pick Version A or Version B framing | 5 min | Paper 4 body_v4 rewrite unblock; K1208 UNIVERSAL_NULL draft currently leans Version B |
| P3 | MEDIUM | Paper 3 K1128 pivot (a/b/c) — K1205 recommends (b) hybrid null+positive | **UNCHANGED** from K1220 P3 | Commit path (a)/(b)/(c) | 30 min thinking | Paper 3 narrative commit; enables `paper/prg-hybrid-null/` scaffolding per K1217 |
| P4 | LOW | BTC GAS negative paper go / no-go | **UNCHANGED** from K1220 P4 | Confirm new paper slot + target JEF primary | 5 min | New paper pipeline; K1214 draft (4829 w) ready |
| P5 | LOW | Approve K1224 Paper 1 Batch 2 execution | **UNCHANGED** | 2 min approval | 2 min | Clears JBF reproducibility audit |
| P6 | LOW | Approve K1223 Paper 6 Appendix A + errata execution | **UNCHANGED** | 2 min approval | 2 min | FRL submission path clear |

**Net change vs K1220**: P1 moved from "wait for K1216b/K1216c + pick path" to "review consolidated K1222b"; P2/P3/P4/P5/P6 unchanged. Total user time for all 6 gates ≈ 65 min (thinking) + 4 min (approvals) + 45 min body review = ~115 min for full session close.

---

## 6. Session Achievements Summary

### 6.1 Major findings

1. **K1216c ROOT_CAUSE_METHODOLOGY** (knowledge `f63b6e01`) — 9/9 markets multistart-FRAGILE (not EM-specific). Two-basin likelihood surface in shared-MIDAS joint pooled GJR pool — universal design issue, independent of market development status.
2. **Paper 2 §5 ρ REBOUND** to +0.379 (p = 0.201, N=13) — K1222b FINAL. NOT the collapse to −0.071 that K1216b asymmetric refinement suggested. Fisher-z equivalent to canonical +0.441 (p ≈ 0.87).
3. **Paper 4 UNIVERSAL_NULL 7/7** (K1116 → K1116b → K1116c → K1116f → K1201 → K1203 → K1208) — native IV sufficient across SPY/GLD/TLT/BTC/QQQ/USO/EEM under true publication-lag PIT alignment. TLT finstress DM t = +3.74 rejected under triple-gate test (QLIKE < 5%, 2/3 subperiods NS, augment flips to −5.67).
4. **Paper 6 defensibility** — K1200 clean-slate PRG replication confirms K880 DM = 6.00 is conservative (K1200 DM = 6.13). K880v2 two-phase forecast timing eliminates the original lookahead. Option (b) narrative pivot is legitimate, not fabrication.
5. **Paper 2 foundry 6-layer NULL** (K1108 series) — industry fixed effect absorbs foundry-specific content; institutional-ownership proxy remains the dominant driver.
6. **Paper 3 K1128 4-branch NULL** (K1128 discrete / K1131 spline / K1199 expanding / + K1142 vol-norm partial) — structural root cause: IS VIX range [9, 37] does not intersect COVID OOS [12, 83]. K1142 `|OFI|/σ_t` is regime-free (best of 4, OOS t = +2.255 Harvey-fail, AUC 0.671). K1205 integrity check 7/7 PASS; path (b) recommended.
7. **BTC GAS negative result** (K1133/K1133b) viable as standalone paper — DM t = −4.58 full sample, P1 pre-institutional DM t = −4.67 Harvey-significant; ~75% Student-t innovation attribution vs ~25% GAS dynamics (NS); Catania (2018) MS-GAS-t does not rescue.

### 6.2 Drafts / guides produced (this session, Markdown only)

| K | Artefact | Words | Role |
|---|---|---|---|
| K1156 | Paper narrative notes | (upstream) | context |
| K1204 | Paper 2 consolidation notes | (upstream) | context |
| K1205 | Paper 3 integrity check | — | decision input |
| K1208 | Paper 4 UNIVERSAL_NULL body draft | 1,762 | BLOCKED on P2 |
| K1209 | Paper 1 Batch 2 draft | 3,574 | feeds K1224 |
| K1211 | Paper 2 §5 STRENGTHENED draft | 2,380 | **SUPERSEDED by K1222b** |
| K1212 | Session delta | ≈1,900 | earlier consolidation |
| K1214 | BTC GAS negative paper | 4,829 | BLOCKED on P4 |
| K1215 | Paper 2 §5 + K1213 AU revised draft | — | **SUPERSEDED by K1222b** |
| K1217 | Paper 3 CONDITIONAL draft | 4,991 | BLOCKED on P3 |
| K1218 | Paper 6 Appendix A draft | 930 | feeds K1223 |
| K1219 | Cherry-pick dashboard | — | **SUPERSEDED by K1226** |
| K1220 | Executive briefing | — | **SUPERSEDED by K1226** |
| K1222 | Paper 2 §5 WITHDRAWN guide | — | **SUPERSEDED by K1222b** |
| K1222b | Paper 2 §5 FINAL revision guide | 2,925 | ACTIVE (feeds body_v(n+1)) |
| K1223 | Paper 6 edit guide | — | ACTIVE (6 items) |
| K1224 | Paper 1 edit guide | — | ACTIVE (7 items) |
| K1225 | Paper 4 dual-framing guide | — | **not yet produced this session; planned for P2 unblock** |
| **K1226** | **Master index (this)** | ~2,400 | **ACTIVE FINAL close briefing** |

**Total paper-related Markdown output** (this session): ~30,000 words across 18 drafts/guides.

### 6.3 Knowledge entries

~90+ entries added this session in the K1100–K1225 K-number range. Most recent high-impact entries:

- `f63b6e01` K1216c ROOT_CAUSE_METHODOLOGY (9/9 fragile; ρ rebounds).
- `b40d669f` K1216b ALL_5_EM_FRAGILE (asymmetric-refinement artefact exposed).
- `5cf52ce6` K1216 BR/IN/MX WIDESPREAD_FRAGILITY.
- `e4d376ad` K1213 AU ABOVE_LADDER_OVERTURNED.
- `5d2d2435` K1207 SECTOR_ORTHOGONAL_CONFIRMED (F=689.5, p=7.9e-14).

### 6.4 Blocked persistent (unchanged from K1220)

- K1100h Dropbox tick TAIFEX 2017–2021 (external data).
- K1116d `FRED_API_KEY` (missing env).
- K1161b paid options data.
- K1175 GDELT/GCP BigQuery capacity.
- I4 yfinance VIX futures gap.

---

## 7. Execution Plan for Next Session

### 7.1 Immediate (no user decision needed, ~80–120 min)

1. **K1224 → Paper 1 body_v4 cherry-pick** (60–90 min): 7 items top-to-bottom; `xelatex main_v4 × 2`; `paper-update --paper-id leverage-direction`; commit.
2. **K1223 → Paper 6 body_v2 + Appendix A** (80–120 min): 6 items top-to-bottom; `xelatex main × 2`; `paper-update --paper-id prg-periodic-garch`; commit.

These two can run in parallel main-thread windows (different paper folders, no shared state).

### 7.2 After user decisions (per-decision ~60 min)

3. **If user confirms K1222b (P1)** → Paper 2 body_v(n+1) rewrite per K1222b 13 cherry-pick items; `xelatex × 2`; `paper-update --paper-id <paper2>`; commit. Revert any K1222 "WITHDRAWN / COLLAPSED / artefact" language if partially merged.
4. **If user picks Paper 4 CONFLICT-A4 (P2)** → Paper 4 body_v4 rewrite per K1225 Version A or B (K1225 to be produced before body rewrite; currently K1208 leans Version B UNIVERSAL_NULL).
5. **If user picks Paper 3 pivot (P3)** — path (b) recommended → initialise `paper/prg-hybrid-null/` per K1217; new paper scaffolding + README + experiments.md + body_v1.tex.
6. **If user approves BTC GAS (P4)** → initialise `paper/btc-gas-negative/` per K1214; target JEF primary (JFEC fallback); new paper scaffolding.

### 7.3 Longer-term follow-ups

7. **K1100g_d9 cadence verify** (N225 asymmetric-t sign flip disambiguation — pending).
8. **K1202b primary-source hand-verify** (Paper 2 foundry submission credibility — pending).
9. **Paper 2 §5 body_v(n+1) add K1216c multistart methodology §5.4** (new additional contribution per K1222b §3).
10. **K1216d (optional)** — 100-multistart on CA/HK/KR (3 remaining unaudited markets). Expected to also shift; final Spearman likely in [+0.30, +0.50]. Not prerequisite for K1222b adoption per K1222b §6.
11. **K1173 aggregate ρ rebuild** against PANEL-WIDE K1216/K1216b/K1216c refined inputs (if retained in Paper 2 §6 robustness).
12. **Figure 5 panel update** — K1222b §4 Figure mapping: add new Figure 5H (3-scenario Spearman trajectory: canonical +0.441 / asymmetric −0.071 / 9-market refined +0.379).

---

## 8. Source Traceability

- **K1212 session delta**: `experiments/k1212/k1212_research_program_delta.md` (≈1,900 words) + `k1212_session_stats.json` (88 knowledge entries, 74 unique K ids). Earlier consolidation.
- **K1219 cherry-pick dashboard**: `experiments/k1219/k1219_dashboard.md` (6 drafts, 20,057 total words) + `k1219_session_actions.json`. Earlier cherry-pick.
- **K1220 executive briefing**: `experiments/k1220/k1220_executive_briefing.md` + `k1220_decision_matrix.json`. Pre-K1216c.
- **K1216c root-cause**: `experiments/k1216c/README.md` + `k1216c_results.json` + `k1216c_multistart_results.csv` + `k1216c_9market_trajectory.png`. Knowledge `f63b6e01`. **Most recent update.**
- **K1222b FINAL revision guide**: `experiments/k1222b/k1222b_revision_guide.md` (2,925 words) + `k1222b_vs_k1222_diff.json`. Supersedes K1222.
- **K1223 Paper 6 edit guide**: `experiments/k1223/k1223_edit_guide.md` + `k1223_edit_items.json`.
- **K1224 Paper 1 edit guide**: `experiments/k1224/k1224_edit_guide.md` + `k1224_edit_items.json`.
- **Knowledge**: `storage/memory/knowledge.json` — ~90 new entries this session; top 5 listed §6.3.
- **Pending queue**: `storage/next_tasks.json` — legacy working list (not canonical queue per CLAUDE.md).

---

## 9. Compliance

- K1226 produces **Markdown + JSON only**; no `.tex` output, no mutation of `paper/**`, `storage/**`, `research_program.md`, or `knowledge.json`.
- All numerical claims **verbatim** from upstream experiment JSONs / knowledge entries (K1216c, K1222b, K1223, K1224, K1220, K1218, K1217, K1214, K1209, K1211, K1208).
- K1220 briefing is **referenced** as the pre-K1216c state; K1226 is the **FINAL** post-K1216c close briefing.
- Worktree scope: only `experiments/k1226/`. No shared-state writes.
- Seed 42 declared (no RNG used).

---

*End of K1226 master index. Produced 2026-04-18 by worktree agent `agent-ad8509ed`. Supersedes K1212/K1219/K1220. K1222 superseded by K1222b (both referenced for trajectory traceability).*
