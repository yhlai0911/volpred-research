# K1246: Paper 10 Crypto-Fear-Channel Reproduction Package Drafts

**Status**: DONE (drafting only)
**Paper**: 10 — Crypto Fear Channel (`paper/crypto-fear-channel/`)
**Produced by**: Claude (main → worktree `agent-a3b10f9b`)
**Prior ids**: K1234 (Paper 10 §2-§9 kickoff guide), K1238 (Paper 10 §3 data draft), K1241 (Paper 10 §6.1 primary GARCH-X NULL)

---

## Purpose

K1234 kickoff guide §5 flagged that Paper 10 requires **five self-contained items**
per `docs/paper-guide.md` ("Self-contained paper folder") **before first body drafting
commits**. As of 2026-04-17, `paper/crypto-fear-channel/` contains only
`outline.md` + `body_v0_intro.tex` + `reproducibility_audit/`. The remaining
pre-flight artifacts are missing.

K1246 produces **three key Markdown files** ready for drop-in adoption by the
main-thread into `paper/crypto-fear-channel/`:

1. `data_sources.md` — item (1) of the 5-item checklist (data origin, license, retrieval)
2. `experiments.md` — item (4) (supporting K-experiment index)
3. `scripts/README.md` — part of item (2) (reproduction entry points)

The remaining two items (README.md for the paper; main reproduce.py) are
**explicitly out of scope for this worktree** because:

- `README.md` at the paper root encodes *main-thread editorial metadata*
  (title, target journal, status tracker) that should live in the main-thread
  commit history, not in a worktree draft.
- `reproduce.py` is an executable artifact, not a Markdown draft; K1246 is
  scoped to Markdown drafts per the K1234 kickoff guide §5 request.

Main-thread adoption procedure is documented in §3 below.

---

## Source experiments traced

All Markdown drafts in this experiment reference only real, on-disk K-experiment
paths in the main repo. Filesystem verification performed 2026-04-17 on main
repo:

| K id | Path | Status | Role in Paper 10 |
|------|------|--------|------------------|
| K1025 | `experiments/k1025/` | exists | Primary framework (§5.1–§5.3, §6.1–§6.2, §7.1) |
| K639 | `experiments/k639/` | exists | BTC→SPY Granger baseline (§5.1 robustness cite) |
| K746b | `experiments/k746b/` | exists | Asymmetric BTC→VIX Granger confirm (§5.1) |
| K1241 | `experiments/k1241/` | exists (main only) | §6.5 pooled GARCH-X NULL |
| K1214 | `experiments/k1214/` | exists | BTC GAS-t negative paper cross-reference (companion) |
| K1133 | `experiments/k1133/` | exists | BTC sub-period regime context |
| K1133b | `experiments/k1133b/` | exists | 5-model Student-t attribution + MS-GAS-t |
| K1234 | `experiments/k1234/` | exists | Paper 10 §2-§9 writing kickoff guide (non-numerical) |
| K1238 | `experiments/k1238/` | exists | Paper 10 §3 initial Markdown draft |

Note: K1241 does not yet exist in this worktree snapshot (branched at
`eab2319e`) but exists on main as of task launch — this is expected given
K1241's recent creation by a separate worktree. The Markdown drafts reference
the correct path for post-merge adoption.

---

## Main-thread adoption procedure

Once the main-thread reviewer confirms content, adoption is a three-step copy:

```bash
# 1. Copy the drafts into the paper folder
cp experiments/k1246/data_sources.md     paper/crypto-fear-channel/data_sources.md
cp experiments/k1246/experiments.md      paper/crypto-fear-channel/experiments.md
mkdir -p paper/crypto-fear-channel/scripts
cp experiments/k1246/scripts_README.md   paper/crypto-fear-channel/scripts/README.md

# 2. Create paper-level README.md (main-thread decision; template fields below)
#    Fields: title, target journal, status, lead author, K-support list,
#    data-source one-line summary
#    Do NOT take the K1246 README as canonical — K1246 wrapper is experiment-
#    level metadata, paper README is publication metadata

# 3. Create reproduce.py once §3/§4/§5 body drafts are first merged
#    Per paper-guide rule (c): bit-for-bit reproduce paper body numbers from
#    experiments/k1025/k1025_results.json + k639 + k746b + k1241 JSONs.
```

The main-thread reviewer should **not** simply `cp -r experiments/k1246/*` into
the paper folder, because the K1246 wrapper README and manifest are experiment-
level metadata that do not belong at the paper root.

---

## Files in this experiment

- `k1246_README.md` — this file (wrapper metadata, not for paper folder)
- `data_sources.md` — drop-in draft for `paper/crypto-fear-channel/data_sources.md`
- `experiments.md` — drop-in draft for `paper/crypto-fear-channel/experiments.md`
- `scripts_README.md` — drop-in draft for `paper/crypto-fear-channel/scripts/README.md`
- `k1246_package_manifest.json` — structured 5-item compliance tracking

---

## Verification

Before merge, Codex/main-thread reviewer should confirm:

- [ ] All K paths in `experiments.md` resolve to real directories
- [ ] All data sources in `data_sources.md` match the canonical yfinance ticker
      set in `experiments/k1025/k1025.py` line 16 and `experiments/k1241/k1241.py`
- [ ] `scripts_README.md` entry-point wrapper names are not fabricated —
      K1246 deliberately documents the **existing** `experiments/kXXXX/kXXXX*.py`
      entry points rather than inventing new `run_kXXX_*.py` wrappers
- [ ] `data_sources.md` period end date matches K1025 coverage (2026-04-08)
      and K1241 coverage (2026-04-14); any tightening/extension must be
      documented in `data_sources.md` §"Version log"

---

## References

- `docs/paper-guide.md` — 5-item self-contained paper folder requirement
- `experiments/k1234/k1234_kickoff_guide.md` — §5 reproduction package parallel tasks
- `experiments/k1238/k1238_data_draft.md` — §3 data section (source of sample period, N, descriptives)
- `experiments/k1241/README.md` — §6.1 primary GARCH-X NULL
- `paper/crypto-fear-channel/outline.md` — canonical paper outline
- `paper/crypto-fear-channel/body_v0_intro.tex` — canonical §1 introduction with locked scope
