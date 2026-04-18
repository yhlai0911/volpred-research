# K1229: Papers 5/7/8/9/10 + vt-crowding-abm Current-State Audit

**Audit Date**: 2026-04-17
**Scope**: 5 paper folders NOT touched in main session 2026-04-17 (which focused on Papers 1/2/3/4/6 + BTC GAS)
**Purpose**: Snapshot current status so main thread can prioritise next-session work
**Seed**: 42 (N/A for a read-only audit, recorded per rule)

> **Paper numbering legend** (resolved earlier this session):
> - Paper 5 → `vt-crowding-abm` (ABM tipping-point FRL short-form)
> - Paper 6 → `prg-periodic-garch` (NOT in this audit)
> - Paper 7 → `vt-insurance-cost` (opportunity/transaction decomposition FRL)
> - Paper 8 → `volatility-absorption` (diminishing-marginal-fear)
> - Paper 9 → `garch-x-vix` (multiplicative GARCH-X; submitted)
> - Paper 10 → `crypto-fear-channel` (renumbered from Paper 6 earlier today)
>
> Note: README files inside the folders still use the older "Paper 4/5/8" numbering labels in a few places. This mismatch is a documentation-only issue, not a content issue. Flagged as a low-priority cleanup.

---

## Paper 5: `vt-crowding-abm` — ABM VT crowding tipping point

- **Folder contents**: `main.tex`, `main.pdf`, `README.md`, `experiments.md`, `data_sources.md`, `reproduce.py`, `reproducibility_audit/`, `review_v1.tex`, `review_v1.pdf`, `reviews/`, `scripts/`, `experiments/`, `results/`, `figures/`.
- **Self-contained**: YES. Has data_sources.md, scripts/, results/, experiments.md, README.md.
- **Recent commits (git log)**: `65bdf9ef 2026-04-17 paper-folder backfill`, `1bd06dfe 2026-04-17 Paper 8 reproducibility audit: 97.5% matched, 4 divergent, ABM seed-deterministic: yes` (note: Paper 8 label in commit refers to the old numbering used by audit agent).
- **Supporting experiments** (per README): K827 (base), K827v2 (OAT), K827v3 (fixed liquidity; main Table 3), K864 (heterogeneous ABM / Table 2).
- **Session 2026-04-17 impact**: **Partial** — worktree agent a7dacfdf ran reproducibility audit (97.5% match, 4 divergences, seed-deterministic). Not touched by methodology changes (multistart K1216c does not apply; pure simulation).
- **Submission readiness**: ✅ Ready (R3 SEVERE=0). Audit flags 4 divergences: 1 trivial rounding, 1 threshold-classification labeling, 2 minor; none block submission.
- **Pending action items**: (a) fix DIV-2 threshold classification label in k827v3 script metadata; (b) confirm README paper-number label (says "Paper 5" — consistent).
- **Priority**: P4 (cosmetic; paper is submission-ready).

## Paper 7: `vt-insurance-cost` — Insurance premium decomposition

- **Folder contents**: `main.tex`, `main_v1.tex`, `main.pdf`, `README.md`, `experiments.md`, `data_sources.md`, `reproduce.py`, `reproducibility_audit/`, `review_v1.tex`, `review_v1.pdf`, `reviews/`, `scripts/`, `experiments/`, `results/`, `figures/`, `data/`.
- **Self-contained**: YES. Pre-downloaded CSVs in `data/`, full scripts and audit.
- **Recent commits**: `65bdf9ef 2026-04-17 paper-folder backfill`, `cb1dd9b4 2026-04-17 Paper 7 reproducibility audit: 96% matched, 2 divergent, no direction issues`.
- **Supporting experiments** (per README): K811 (pilot), K811v2 (main; Table 2), K846 (rebalancing premium), K860 (prospect theory supplement).
- **Session 2026-04-17 impact**: **Partial** — worktree agent a1343ea9 ran the reproducibility audit (96% match, 2 substantive divergences, 0 sign errors). Not directly touched by K1216c multistart work.
- **Submission readiness**: ✅ Ready (R3 SEVERE=0) + READY-FOR-SUBMISSION per audit.
- **Pending action items** (low severity, from audit):
  1. Sec 2.3: fix "97%" → "98%" at 1 bps (computed 4.195/4.281 = 98.0%).
  2. Sec 3.3 bound: "54–80 bps" → "54–81 bps" (K846 theoretical = 81.46).
  3. Footnote Sec 3.3: 2012–2024 sub-period ρ=0.04, 48 bps unverifiable — add to K846 script or remove.
  4. Decide inclusion/exclusion of K860 prospect-theory reference.
- **Priority**: P3 (FRL submission candidate; 2 text fixes + 1 K860 decision = a quick 30-minute pass).

## Paper 8: `volatility-absorption` — Diminishing-marginal-fear

- **Folder contents**: `main.tex`, `main_v2.tex`, `main_v2.pdf`, `v1_to_v2_diff.tex`/`.pdf`, `README.md`, `experiments.md`, `data_sources.md`, `reproduce.py`, `reproduce_report.json`, `citation_check.md`, `reproducibility_audit/` (only `nonK_sweep_report.md`), `review_v1.tex`/`.pdf`, `reviews/`, `scripts/`, `experiments/`, `results/`, `figures/`.
- **Self-contained**: PARTIAL. `reproducibility_audit/` contains only the non-K sweep; no full audit README like Papers 5/7/9. `reproduce_report.json` (generated earlier) shows verification rate = 50.7% (38 match / 8 mismatch / 29 untraceable).
- **Recent commits**: `65bdf9ef 2026-04-17 paper-folder backfill`, older R1-review commits (no full audit ran for Paper 8 on 2026-04-17).
- **Supporting experiments** (per README): K716 (absorption regression — **no .py**), K718/K719/K720/K721/K722 (all **no .py**), K741 (NFP revision), K897 (null simulation), K903 (robustness), K904 (shock+NFP fix).
- **Session 2026-04-17 impact**: **None direct**. Paper 8 had a backfill but no new audit or K-run. The known S1–S4 and missing-script issues from 2026-04-05 R1 review are still open.
- **Submission readiness**: ⚠️ Draft — R1 review open, 5 SEVERE (S1 null sim K897 is now done, but S2/S3/S4 open; K716–K722 .py scripts never reconstructed).
- **Pending action items**:
  1. Reconstruct K716/K718/K719/K720/K721/K722 .py scripts OR split results out of `main_v2.tex` (per paper-guide "reproduce.py must match body").
  2. Resolve Table 5 N-column methodology (S2).
  3. Resolve Tables 9–10 untraceability (S3).
  4. Fix Table 6 NFP systematic discrepancies (S4).
  5. Run full reproducibility audit (to match the Paper 5/7/9 protocol).
- **Priority**: **P2** — largest gap among the five. Not submission-blockable if K716–K722 re-run succeeds (otherwise the paper falls under paper-guide `(a)(b)(c)` rule and must choose: fix scripts, adjust body, or document errata).

## Paper 9: `garch-x-vix` — Multiplicative GARCH-X with VIX

- **Folder contents**: `main.tex`, `main_v1_backup.tex`, `README.md`, `experiments.md`, `data_sources.md`, `citation_check.md`, `compute_mcs_dm.py`, `mcs_dm_results.json`, `reproducibility_audit/` (full: 6 files), `review_history/v1/`, `review_v1.tex`/`.pdf`, `scripts/`, `figures/`, `results/`.
- **Self-contained**: YES. `reproducibility_audit/` has diff_report, CSV, script_output.json, README, non-K sweep, undocumented-K additions.
- **Recent commits** (richest activity among the five):
  - `f96888d1 2026-04-17 Paper 9 experiments.md: register K1045/K1003/K1001/K1023 (audit quick-win)`
  - `26c7a6ed 2026-04-17 Paper 9 no-source rescan: 19 undocumented K found, 7 still missing, 0 ambiguous`
  - `4e84d37f 2026-04-17 Paper 9 reproducibility audit: 85% matched, 7 divergent, NEEDS-FIX`
  - `5b785551 2026-04-17 paper-folder backfill`
  - `d6dc65a6 4-hour sync: Paper 9 citation check + token report`
  - `7960fc20 Paper 9 citation check done (needs revision: 1 MAJOR + 5 MED)`
  - `2bf5f2f6 2026-04-17 Paper 9 bib fix: 1 MAJOR + 5 MED + 2 MINOR DOI per citation_check v1`
- **Supporting experiments** (per README): K889, K889b, K889v2, K988, K988b, K989, K1045 (Table 11 residuals), K1023 (Props 1–2), K1003/K1001, plus cross-asset K1085/K1088/K1077/K1083/K1098.
- **Session 2026-04-17 impact**: **Significant (but already landed in prior commits)**. Nothing new on 2026-04-17 is pending beyond the known action items below.
- **Submission readiness**: ✅ Submitted (under review at JEF / IJoF). Replication-package NEEDS-FIX (auditor verdict); science is solid.
- **Known 2026-04-17 pending items**:
  1. **CITATION (from `citation_check.md` + commit `2bf5f2f6`)**: 1 MAJOR (`Bayer & Hackethal 2020` is FABRICATED — must REMOVE + replace; suggested Prokopczuk et al. 2016 or Bekaert & Hoerova 2014) + 5 MEDIUM DOI issues + 2 MINOR (incl. `wang2017` key → `wang2015`).
  2. **REPRO audit (`reproducibility_audit/README.md`)**: 7 divergent + 54 "no-source" cells (34.8%). FEZ DM t=3.45 has NO SOURCE — reviewer-exposable. Main horse-race table is fully reproducible.
  3. **EXPERIMENTS.md**: 19 undocumented K found; 7 still missing post-registration.
- **Priority**: **P3** — paper is already submitted. Items 1 & 2 must land before any revision response; should be queued for when reviewer comments arrive (or proactively if submission allows an errata).

## Paper 10: `crypto-fear-channel` — BTC → VIX asymmetric spillover

- **Folder contents**: `outline.md`, `body_v0_intro.tex` (introduction only, v0), `reproducibility_audit/` (only `nonK_sweep_report.md`).
- **Self-contained**: NO (and not expected — paper is kickoff-stage). Missing: README.md, data_sources.md, experiments.md, scripts/, results/, figures/, reproduce.py, main body sections 2–9.
- **Recent commits**: `c1165d6f 2026-04-17 Paper numbering fix: Crypto Fear Channel = Paper 10 (not Paper 6)`, `5585bfc5 2026-04-17 Paper 6 kick-off outline + cross-market research article (pool refill)` (this earlier commit message still says "Paper 6" pre-renumbering).
- **Supporting experiments** (per outline.md): K639 (BTC→SPY Granger), K746b (asymmetric BTC→VIX), K1025 (full framework: asymmetric Granger + QR + Diebold-Yilmaz + EWMA + 5-subperiod + OOS null).
- **Session 2026-04-17 impact**: **Earlier session** — numbering resolved; v0 intro drafted. Body sections 2–9 and replication package not yet started.
- **Submission readiness**: 🛠️ **Kickoff**. Per paper-guide, self-contained package not required at kickoff but must be filled in before first body drafting begins.
- **Pending action items**:
  1. Confirm target journal (current pref: JIFMIM → JEF → FRL).
  2. Draft §2 (lit review) and §3 (data).
  3. Create `README.md`, `data_sources.md`, `experiments.md` (K639/K746b/K1025) once body drafting starts.
  4. Decide open questions in outline.md: memecoin comparison?, IV data (Deribit)?, single vs multi-asset receiver?, forecasting section length?
- **Priority**: **P4** — valid research path, but behind the other four in session priority (no pending submission deadline; lots of text to draft).

---

## Summary Table

| # | Paper | Self-contained | Readiness | Recent audit | Top pending action | Session impact | Priority |
|---|-------|---------------|-----------|-------------|-------------------|----------------|----------|
| 5 | vt-crowding-abm | ✅ Yes | ✅ Ready (R3 SEVERE=0) | 97.5% match, 4 div | DIV-2 threshold label cleanup | Partial (audit ran 2026-04-17) | P4 |
| 7 | vt-insurance-cost | ✅ Yes | ✅ Ready (R3 SEVERE=0) | 96% match, 2 div | "97%"→"98%", "80"→"81", K860 decision | Partial (audit ran 2026-04-17) | P3 |
| 8 | volatility-absorption | ⚠️ Partial | ⚠️ Draft (R1, S2/S3/S4 open) | 50.7% rate (old reproduce_report) | Reconstruct K716–K722 .py **or** apply paper-guide (a)/(b)/(c) | None direct | **P2** |
| 9 | garch-x-vix | ✅ Yes | ✅ Submitted (replication NEEDS-FIX) | 85% match, 7 div + 54 no-source | Citations: 1 MAJOR fabricated + 5 MED; FEZ t=3.45 no-source | None new 2026-04-17 | P3 |
| 10 | crypto-fear-channel | ❌ No (kickoff) | 🛠️ Kickoff (outline + intro only) | — | Draft §2–§9; build README/data_sources/experiments.md | Earlier session (numbering) | P4 |

---

## Cross-cutting Observations

### Shared methodology concerns
- **K1216c multistart fragility** (main-session finding): Papers 5/7/8 are simulation / descriptive-regression / event-study based, so multistart MLE fragility **does not apply**. Paper 9 is GARCH-MLE-based and **could** in principle be affected — but Paper 9's horse-race is single-spec joint MLE with wide grid starts already documented in K1045 diagnostics; the A4f winner is robust across K988/K988b/K989. **Recommendation**: spot-check Paper 9 A4f estimates are on the global optimum (quick — rerun k988 with 16-start grid). Paper 10 uses Granger + QR + DY + DCC, none GARCH-MLE estimation-heavy; not at risk.

### Shared data sources
- **yfinance**: SPY, VIX, GLD, QQQ, TLT, 0050.TW, BTC-USD appear across Papers 7/8/9/10. A single data_sources.md canonicalisation would reduce duplication; currently each paper has its own.
- **TAIFEX / VIXTWN**: Paper 9 (K1098) only.
- **ABM pure-simulation**: Paper 5 only (no external data).
- **NFP dates (manual)**: Paper 8 only.

### Documentation mismatches
- Several reproducibility_audit READMEs use the older numbering ("Paper 7" = vt-insurance-cost, "Paper 8" = vt-crowding-abm) while the paper folder READMEs use the new numbering ("Paper 4" = vt-insurance-cost, "Paper 5" = vt-crowding-abm). Main-thread should pick one convention and sweep.
- Paper 8 (volatility-absorption) README calls itself "Paper 8" while the current audit assigns Paper 8 to this slot — aligned.

### Audit-protocol coverage gap
- Papers 5/7/9 have the full 6-step audit protocol (data_sources + scripts + results + experiments + audit README + diff_report).
- Paper 8 has `reproduce_report.json` (older format) + only `nonK_sweep_report.md` — needs the full protocol.
- Paper 10 is kickoff; protocol not expected yet.

---

## Main-Thread Action List (priority-ordered)

1. **[P2] Paper 8 reproducibility rescue** — decide between:
   - (a) reconstruct K716–K722 .py from extant logs/results JSON,
   - (b) revise main_v2 body to match only K741/K897/K903/K904 (drop K716–K722 claims),
   - (c) document an explicit errata per paper-guide; commit with "pending errata, magnitude <X>%".
   - Either path must then run the full 6-step audit to match Papers 5/7/9.
2. **[P3] Paper 9 revision prep** — when reviewer comments arrive (or proactively):
   - Remove Bayer & Hackethal (2020), replace with Prokopczuk et al. (2016) or Bekaert & Hoerova (2014).
   - Fix 5 MEDIUM DOI issues + 2 MINOR key issues (wang2017 → wang2015).
   - Locate or retract FEZ DM t=3.45 (currently no-source).
   - Resolve the 7 remaining undocumented K references.
3. **[P3] Paper 7 FRL polish** — 3 tex fixes + 1 decision (K860 inclusion); ~30 min pass, then recompile + paper-update.
4. **[P4] Paper 5 FRL polish** — fix DIV-2 threshold classification label in k827v3 script metadata; recompile.
5. **[P4] Paper 10 advance to body drafting** — dispatch main-thread 1–2 hr drafting session on §2 and §3; create README/data_sources/experiments.md as body drafts land.
6. **[housekeeping] Paper numbering sweep** — align audit-README numbering with current Paper 1–10 schema.

---

## Limits of this audit

- Read-only: no new code executed, no recomputation of numbers.
- Git log restricted to the five target folders; no deep dive into experiment JSONs.
- Paper 10 PDF not yet compiled (only body_v0_intro.tex); no compile-check performed.
- Paper 5 and 7 commit messages still use old numbering labels ("Paper 7/8") — this is cosmetic only and does not affect content.
