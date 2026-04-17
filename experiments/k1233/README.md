# K1233: Papers 5 + 7 Small Tex Fix Consolidation

**Date**: 2026-04-17
**Type**: Consolidation / edit-guide (no new computation)
**Seed**: 42 (N/A — read-only guide)
**Status**: Guide ready for main-thread execution

## Purpose

K1229 audit (commit `ad67f236`, `experiments/k1229/k1229_papers_audit.md`) flagged
Papers 5 (`vt-crowding-abm`) and 7 (`vt-insurance-cost`) as **READY** (96% / 97.5%
match, R3 SEVERE=0, submission-ready). The remaining items are **small tex fixes**
plus one K860 inclusion decision.

K1233 consolidates both papers into a single edit-guide so the main thread can:

1. Apply Paper 7 three tex fixes in one pass (~15 min),
2. Apply Paper 5 one tex-metadata fix in one pass (~10 min),
3. Recompile and `paper-update` each paper separately for clean commit history.

## Source

- **K1229 audit**: `experiments/k1229/k1229_papers_audit.md`,
  `experiments/k1229/k1229_paper_audit.json` (Paper 5 section + Paper 7 section).
- **Paper 5 diff report**: `paper/vt-crowding-abm/reproducibility_audit/diff_report.md`
  (dated 2026-04-17, 97.5% match, 4 divergences).
- **Paper 7 diff report**: `paper/vt-insurance-cost/reproducibility_audit/diff_report.md`
  (dated 2026-04-17, 96% match, 2 divergent + 2 unverifiable).

## Files

- `README.md` — this file.
- `k1233_tex_fix_guide.md` — concrete edit-guide with per-fix location, current
  text (verbatim), proposed text (verbatim), rationale, and LaTeX diff.
- `k1233_fixes.json` — structured per-fix payload for automation / tracking.

## Main-Thread Adoption Sequence

The guide lists fixes **grouped by paper** and in **line-number order** for
single-pass editing:

1. **Paper 7** (`paper/vt-insurance-cost/main.tex`):
   - Fix P7-1: line 108 — `97\%` → `98\%`.
   - Fix P7-2: line 186 — `54--80~bps` → `54--81~bps`.
   - Fix P7-3: line 184 footnote — either add sub-period block to K846 script,
     or reword the footnote to explicitly mark it as "unreported back-of-envelope".
   - Decision P7-4: K860 prospect-theory — recommendation is **EXCLUDE** from
     main.tex (already not cited; keep as supplementary in experiments.md only).
2. Recompile: `cd paper/vt-insurance-cost && xelatex main.tex && xelatex main.tex`.
3. Publish: `uv run volpred ops paper-update --paper-id vt-insurance-cost`.
4. Commit: `git add paper/vt-insurance-cost/ && git commit -m "Paper 7 tex polish: K1229 audit fixes (98%, 54–81bps, footnote)"`.
5. **Paper 5** (`paper/vt-crowding-abm/main.tex` + script):
   - Fix P5-1: `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity.py`
     line 603/605 — `if deg_30 > 30` / `elif deg_50 > 30` → documentation cutoff
     change to align with paper footnote's 50% definition. **No main.tex change
     needed**: the paper table values and footnote are already consistent; only
     the JSON metadata field `threshold_region` is misclassified.
   - **Optional** P5-2 (LOW): line 36 abstract "estimated below 5\%" — add
     footnote citing ECB FSR or industry estimate. Only needed if reviewer
     explicitly flags it (already READY per audit).
6. Recompile: `cd paper/vt-crowding-abm && xelatex main.tex && xelatex main.tex`.
7. Publish: `uv run volpred ops paper-update --paper-id vt-crowding-abm`.
8. Commit separately from Paper 7 for clean history.

## Supporting Experiments

No new computation. All pending fixes resolve by text/metadata edit. If P7-3
elects path (a) "add sub-period to K846 script", that is a ~15-min script edit
+ JSON regeneration to record `rho_2012_2024` and `rebalancing_premium_bps_2012_2024`;
this is **optional** — path (b) "reword footnote to mark as unreported" leaves
the paper body intact.

## Success Criteria

- Every fix has: location (file + line number), current text (verbatim quoted),
  proposed text (verbatim quoted), rationale (why), severity (from audit).
- Every fix is **atomic** (one edit, no cascading changes).
- Either paper marked DONE/NO_ACTION where applicable (abstract 5% is optional).

## Effort Estimate

- Paper 7: ~15 min editing + 2 min compile + 3 min paper-update = **~20 min**.
- Paper 5: ~10 min script-metadata edit + 2 min compile + 3 min paper-update = **~15 min**.
- **Total: ~35 min** (consistent with K1229 estimate of "30-minute pass").

## Strict Boundaries (K1233)

- Worktree agent **does NOT edit main.tex** — only produces `.md` + `.json`
  guide files.
- Main thread applies edits per paper-workflow rule "agent 不寫 body.tex".
- No shared-state writes (no Supabase / Mirror / knowledge.json / feed.json).
- All file reads were filesystem reads; no external data fetched.
