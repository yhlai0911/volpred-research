# K1211 — Paper 2 §5 cross-market institutional ladder rewrite draft (MARKDOWN)

**Status**: COMPLETED — markdown draft produced for main-thread cherry-pick.
**Date**: 2026-04-17 (executed 2026-04-18 UTC).
**Worktree**: `agent-a407c489`.
**Task type**: pure writing + canonical number lookup (**no new estimation**).
**Random seed**: 42 (unused — no sampling; declared for reproducibility).

---

## 1. Purpose

Paper 2 §5 (cross-market institutional-ownership + analyst-coverage
mechanism for earnings-announcement volatility) has reached a
narrative-state-machine unlock gate after nine complementary experiments:

- **K1165** — N=7 base confirmation (TW/EU/JP/US + KR/CA/HK), ρ = +0.75,
  STRENGTHENED.
- **K1166** — per-stock θ_EAV refit with tautology removed (N=108
  pooled), panel Harvey t = 3.556, CONFIRMED.
- **K1168** — N=10 extension (+BR/CH/IN), ρ = +0.612, STRENGTHENED.
- **K1172** — N=12 extension (+MX/ID; ZA dropped for
  under-coverage), ρ = +0.441, PARTIAL.
- **K1171** — N=13 extension (+AU HAND_CODED earnings), ρ = +0.385,
  DATA_LIMITED. Introduces AU below-ladder residual.
- **K1173** — EM refined institutional proxy (SEBI / CVM / BMV / SSE
  aggregators, 40 tickers), Δρ = −0.056 NULL. Falsifies yfinance
  proxy-artefact hypothesis for EM above-ladder residual.
- **K1163** — EU full-coverage refit (N=30, 11 HAND_IRCALENDAR tickers),
  θ_rel = 0.194, ROBUST. K1153 low-cluster verdict confirmed under
  full coverage.
- **K1204** — synthesis + figures (32/32 integrity PASS; Figures A–E).
- **K1207** — GICS sector-FE orthogonality test, F = 689.5 p = 7.9e-14,
  `SECTOR_ORTHOGONAL_CONFIRMED`. Adds third level on top of the K1204
  two-level decomposition.

Per CLAUDE.md `論文 narrative state machine`, unlocking the body rewrite
requires ≥ 3 complementary OOS-verified experiments with peer review; the
seven primary experiments (K1165 / K1166 / K1168 / K1172 / K1171 / K1173
/ K1163) plus synthesis (K1204) plus sector verification (K1207) are all
cleared. **K1211 produces the §5 rewrite draft in MARKDOWN** — not
`.tex` — so that the main thread can cherry-pick into `body_v4.tex`.

**K1211 does not write to `paper/*/body_v?.tex`, does not add new
estimation, does not compute new statistics. All numbers are verbatim
from the source experiment JSONs cited in §3 below.** K1210 (AU forensic
root-cause decomposition) is pending in a parallel worktree at draft
time and is flagged as a residual caveat in §5.5 / §5.7.

## 2. Deliverables (all within `experiments/k1211/`)

| File                     | Purpose                                                                    |
|--------------------------|----------------------------------------------------------------------------|
| `k1211_draft.md`         | Paper 2 §5 rewrite draft in Markdown — ready for cherry-pick into `body_v4.tex`. |
| `k1211_panorama.csv`     | 5-iteration N-extension trajectory table (machine-readable).               |
| `k1211_results.json`     | Canonical-number consolidation + source-commit traceability metadata.      |
| `README.md`              | This file — adoption path, traceability, compliance checks.                |

No new figures are produced. The main thread should re-use existing
figures (K1204 Figure A–E, K1207 R² decomposition) as Figures 5A–5F per
the mapping in `k1211_draft.md` §Table 5.

## 3. Source traceability (verbatim commits)

Every number in `k1211_draft.md` is traceable to a specific source
experiment JSON committed in the main branch:

| Source experiment | Source commit | Source file(s)                                                                                  |
|-------------------|---------------|--------------------------------------------------------------------------------------------------|
| K1165             | `11c3f4bf` (per K1165 entry)     | `experiments/k1165/k1165_results.json`                                      |
| K1166             | `db9c41ef`                       | `experiments/k1166/k1166_results.json`                                      |
| K1168             | `7d2ee0ef`                       | `experiments/k1168/k1168_results.json`                                      |
| K1171             | `17436274`, `051e840b`           | `experiments/k1171/k1171_results.json`                                      |
| K1172             | `8c226669`, `a837beaf`           | `experiments/k1172/k1172_results.json`                                      |
| K1173             | `ea5c6340`, `e604ed70`           | `experiments/k1173/k1173_results.json`                                      |
| K1163             | `158781aa`, `5ea1ecf1`           | `experiments/k1163/k1163_results.json`                                      |
| K1204             | `cf5188eb`, `6e23e593`           | `experiments/k1204/k1204_results.json` + Figures A–E PDF/PNG                |
| K1207             | `bd365d27`, `760ffb4e`           | `experiments/k1207/k1207_results.json` + 3 PNG figures                      |

(K1165/K1166/K1168 commit hashes are the synthesised commit trail from
`git log --all --grep=K116[58]` — the main-thread cherry-pick should
validate the current HEAD of those files against the JSON fields used
in K1204's 32/32 integrity-check report.)

Current main-branch reference HEAD at K1211 execution time: `35bf94d7`
(worktree branch `worktree-agent-a407c489`).

## 4. Main-thread adoption path

1. **Read**: `experiments/k1211/k1211_draft.md` end-to-end (~1,900 words
   including Table 5).
2. **Cherry-pick**: adapt §5.1 → §5.7 into the target Paper 2 body_v4.tex.
   Preserve numbers verbatim. Expected Table 5 + Figures 5A–5F.
3. **Cite**: bibliography entries required are those already present in
   K1165–K1207 references — `ferreira2008`, `bartram2012`, `harvey2016`,
   `patton2011`; plus GICS methodology (MSCI / S&P Dow Jones Indices).
4. **K1210 gate**: if K1210 forensic root-cause decomposition for AU
   below-ladder lands before submission, cherry-pick its verdict into
   §5.5 replacing the "pending" language. If K1210 stays open, submit
   with AU caveat (ii) as documented.
5. **Compile**: `xelatex main_v4.tex` then `uv run volpred ops
   paper-update --paper-id <paper2-id>`.
6. **Integrity check**: re-run the K1204 32/32 shared-key assertion
   any time one of the source experiment JSONs is updated (refit,
   errata). Update this draft's numbers accordingly before cherry-pick.

## 5. Compliance checklist (CLAUDE.md)

| Rule                                                                               | Status |
|------------------------------------------------------------------------------------|:------:|
| No `.tex` writes from worktree agent                                               | PASS — only `.md`, `.csv`, `.json` output |
| Numbers verbatim from source JSONs                                                 | PASS — K1204 32/32 integrity canonical   |
| Seed 42 declared (no sampling; declarative)                                         | PASS   |
| Worktree only touches `experiments/k1211/`                                         | PASS   |
| No shared-state modification (feed, knowledge, supabase, mirror)                   | PASS   |
| `research_program.md` / `knowledge.json` updates reserved for main thread           | N/A — not attempted |
| Paper narrative state machine — ≥3 complementary experiments                        | PASS (9)|
| Cross-experiment numerical divergence halt check                                   | PASS — K1204 32/32 PASS, no conflicts detected in trajectory table |
| `paper/*/body_*.tex` untouched                                                     | PASS   |
| Commit on completion                                                               | PENDING — will commit after README finalised |

No divergence detected across K1165 / K1166 / K1168 / K1172 / K1171 /
K1173 / K1163 / K1207 canonical numbers. K1204 synthesis already
verified 32/32 shared-key equality.

## 6. Parallel K-experiments context

- **K1210** (AU forensic root-cause decomposition, executing in
  `agent-a16275fd` worktree): expected to determine whether AU
  below-ladder residual is driven primarily by semi-annual reporting
  cadence, HAND_CODED ±1-day event-date precision, or ASX large-cap
  sector composition (banks + miners). K1211 references K1210 as pending
  in §5.5 and §5.7 caveat (ii).
- **K1174–K1177 / K1208–K1209** (proposed follow-ups): not blockers for
  Paper 2 §5 rewrite; relegated to limitations / future-work section.
