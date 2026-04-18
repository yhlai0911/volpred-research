# K1247 — Paper 4 CONFLICT-A4 Decision Cheatsheet

**Purpose**: 2-minute read cheatsheet distilling K1225 dual-framing A/B guide
(~2791 words, ~15 min read) into a ~360-word single-page summary so the user
can pick Version A or Version B in 2-3 minutes and unblock P2 gate.

**Context**: Paper 4 (`vix-sufficiency`) §5 rewrite is blocked on CONFLICT-A4.
- User commit `7ecab636` (2026-04-17) → channel-specific pivot
- Session K1203 gate → UNIVERSAL_NULL_7_OF_7
- Same 28-cell data supports both framings

K1225 produced two full parallel §5 edit guides (~2791 words combined). K1247
compresses the decision to a 30-second comparison table + 3-bullet "pick A"
and 3-bullet "pick B" justifications + default B recommendation.

## Source

- `experiments/k1225/k1225_dual_framing_guide.md` (~2791 words; both framings fully specified)
- `experiments/k1225/k1225_dual_framing.json` (structured metadata)
- `experiments/k1226/k1226_decision_snapshot.json` P2 entry
- `experiments/k1236/k1236_decision_gates.json` P2 gate

## Reduction

- K1225 full guide: ~2791 words
- K1247 cheatsheet: ~360 words
- Reduction ratio: ~87%

## Files

- `k1247_cheatsheet.md` — 2-min decision cheatsheet (main deliverable)
- `k1247_quick_pick.json` — structured metadata
- `README.md` — this file

## Strict rules observed

- No `.tex` output (per CLAUDE.md paper-workflow rule; agent can only emit `.md` + `.json`)
- Both options honestly presented (no silent bias)
- Default recommendation + justification for both directions
- 30-second table format for at-a-glance dimension comparison
- Seed 42 (no RNG used; declared for compliance)
- Worktree scope: `experiments/k1247/` only
- No shared-state writes (no `storage/memory/`, no `paper/`, no `research_program.md`)

## After user pick

Main thread (not this worktree) executes:
1. Copy `paper/vix-sufficiency/body_v3.tex` → `body_v4.tex`
2. Apply chosen version's §5 rewrite from K1225 guide (A.1-A.5 or B.1-B.5)
3. Integrate shared Appendix A (K1218 template)
4. xelatex main_v4.tex twice; `uv run volpred ops paper-update --paper-id vix-sufficiency`
5. Commit with CONFLICT-A4 resolution tag

## Compliance

- Seed: 42
- RNG used: no
- TeX output: no
- Shared-state mutations: none
- Output formats: `.md`, `.json`
