# K1234 — Paper 10 (crypto-fear-channel) §2–§9 Kickoff Guide

**Date**: 2026-04-17
**Task type**: Documentation / planning (no data computation)
**Paper**: `paper/crypto-fear-channel/`
**Target journals (per outline)**: JIFMIM (1st) → JEF (2nd) → FRL backup (short-form)
**Trigger**: K1229 audit commit `ad67f236` flagged Paper 10 as *Kickoff* — body §2–§9 pending.

## Purpose

K1229 established Paper 10 is at kickoff stage (outline + `body_v0_intro.tex` only).
Main thread needs a concrete per-section guide before drafting begins, covering:

1. **Per-section outline** (§2–§9) with target word counts, subsections, key claims.
2. **Required supporting experiments** — check what already exists (K639, K746b, K1025) vs. what must be run.
3. **Writing sequence** — which section to draft first for efficient dependency flow.
4. **Reproduction package parallel tasks** — `experiments.md`, `data_sources.md`, `scripts/`, `figures/` (paper-guide §"Self-contained paper folder" requires these before first body drafting).

Per CLAUDE.md: worktree agents MUST NOT write `.tex` body content. This task produces
markdown / JSON kickoff guide only; main-thread takes it from there.

## Sources (actual filesystem reads)

- `paper/crypto-fear-channel/outline.md` (6,879 bytes) — 12-section plan, abstract v0, references starter list.
- `paper/crypto-fear-channel/body_v0_intro.tex` (9,597 bytes) — §1 Introduction v0 with abstract + 4 stylized-fact paragraphs + 8 inline references.
- `paper/crypto-fear-channel/reproducibility_audit/nonK_sweep_report.md` — earlier kickoff audit confirming: `btc_liquidation_abm`, `btc_var_methods`, `btc_derivatives_vol` are all empty stubs; no non-K folder contributes to Paper 10.
- `experiments/k1229/k1229_papers_audit.md` §"Paper 10" — audit finding: K639 + K746b + K1025 are the three canonical supporting experiments.
- Supporting experiment folders verified: `experiments/k639/`, `experiments/k746b/`, `experiments/k1025/` all contain README + .py + *_results.json (per Source-of-Truth rule).

## Main-thread adoption

After merging K1234, main-thread should:

1. Use `k1234_kickoff_guide.md` as drafting roadmap.
2. Follow the recommended writing sequence (Data → Methodology → Main Results → ...).
3. Before first body section lands, create the 5 self-contained paper-folder items
   (README.md, data_sources.md, experiments.md, scripts/README.md, figures/).
4. Cite K639/K746b/K1025 JSON files as canonical number sources (all under `experiments/`).

## Strict rules observed

- No `.tex` files produced; markdown + JSON only.
- No shared-state modifications (`storage/memory/*.json`, `feed.json` untouched).
- Seed 42 noted for record-keeping, though this task has no stochastic code.
- All referenced files verified by filesystem read; no fabricated claims about paper contents.

## Deliverables

- `k1234_kickoff_guide.md` — the section-by-section roadmap.
- `k1234_kickoff_plan.json` — structured machine-readable form.
- `README.md` — this file.
