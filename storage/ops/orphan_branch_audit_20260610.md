# Orphan Branch Audit — 2026-06-10

Task: `platform_ops_orphan_branch_audit_20260610`

Scope:

- `worktree-agent-a446f906b29eeb057` (`K1431`)
- `worktree-agent-a984dee3c1e31ca5c` (`K1423`)
- `worktree-agent-add8052fcf1842aba` (`K1427`)

Method:

1. Check registered worktrees with `git worktree list`
2. Check branch existence with `git branch -vv`
3. Compare branch vs `main`
4. Check whether target `experiments/kXXXX/` exists on `main`

## High-Level Conclusion

- `K1431`: **safe stale orphan branch**
- `K1427`: **safe stale orphan branch, but do not merge over main**
- `K1423`: **not safe to delete; unique unmerged experiment content**

No registered worktree currently points to any of the three `worktree-agent-*` branches.

## Findings

### 1. `worktree-agent-a446f906b29eeb057` — `K1431`

Status: `SAFE_DELETE_WHEN_GIT_WRITABLE`

Evidence:

- Branch exists: `c924f2b8 K1431 VIX9D-VIX spread HAR-RV OOS PoC | NULL`
- `git worktree list` does **not** show any active worktree for this branch
- `git diff --stat main..worktree-agent-a446f906b29eeb057 -- experiments/k1431` returns empty
- `git diff --stat worktree-agent-a446f906b29eeb057..main -- experiments/k1431` returns empty

Interpretation:

- The branch ref still exists, but the `experiments/k1431/` content is already absorbed into `main`
- This is a classic orphan branch residue, not an unmerged recovery target

Recommended action:

- Delete branch ref when `.git` becomes writable:
  - `git branch -D worktree-agent-a446f906b29eeb057`

### 2. `worktree-agent-add8052fcf1842aba` — `K1427`

Status: `SAFE_DELETE_STALE_BRANCH`

Evidence:

- Branch exists with 2 unique commits:
  - `4d3381dd K1427: sector dispersion 把『齊跌』拆成輪動 vs 清算 — selloff regime 分類`
  - `3dcace48 K1427 sector dispersion 齊跌 vs 輪動 — IS PoC | MIXED verdict`
- `git worktree list` does **not** show any active worktree for this branch
- `experiments/k1427/` exists on `main`
- `git log --oneline -- experiments/k1427 | head` on `main` shows later commits:
  - `8f34c2cd` hourly-04 Codex re-review closure
  - `c842d746` hourly-03 caveat fixes
  - `5e9ccb05` main experiment commit
- Branch vs main diff is small and points to **older** content on the branch:
  - `README.md` lacks later Codex review sections present on `main`
  - `k1427.py` / `k1427_results.json` miss later taxonomy-definition synchronization and small post-review recalculations

Interpretation:

- `main` contains the later, reviewed, production-safe version
- The orphan branch is stale and should **not** be merged back over `main`

Recommended action:

- Delete branch ref when `.git` becomes writable:
  - `git branch -D worktree-agent-add8052fcf1842aba`

### 3. `worktree-agent-a984dee3c1e31ca5c` — `K1423`

Status: `PRESERVE_AND_RECOVER`

Evidence:

- Branch exists: `d15e5726 K1423: PCA + factor regression — sector-ETF alpha as unnamed sector-factor exposure (US vs TW semis)`
- `git worktree list` does **not** show any active worktree for this branch
- `experiments/k1423/` is **missing on main**
- Branch contains a full six-file experiment:
  - `experiments/k1423/README.md`
  - `experiments/k1423/k1423.py`
  - `experiments/k1423/k1423_results.json`
  - 3 figures
- `git diff --stat main..worktree-agent-a984dee3c1e31ca5c -- experiments/k1423` shows all six files as branch-only additions

Interpretation:

- This is not disposable residue
- It is an orphaned branch holding unique experiment artifacts not present on `main`
- If deleted now, `K1423` would be lost from repo history unless recovered later from branch ref or reflog

Recommended action:

- Do **not** delete this branch
- Recovery path when `.git` becomes writable:
  - either merge/cherry-pick the branch
  - or create a fresh recovery worktree from `worktree-agent-a984dee3c1e31ca5c`
- Suggested follow-up:
  - validate whether this `K1423` should remain separate from `experiments/K1423_ewma_hurst_pilot/`
  - if yes, merge it as canonical `experiments/k1423/`

## Operational Note

Initial audit session (earlier) could not delete stale branch refs because git write operations were blocked at that time (`fatal: Unable to create '.git/index.lock': Operation not permitted`). So that pass completed the classification only.

## Cleanup Execution — 2026-06-10 03:13 台灣時間 (hourly-03)

Git writable confirmed; recommended actions executed:

- `worktree-agent-a446f906b29eeb057` (K1431) → `git branch -D` ✅ deleted (was `c924f2b8`)
- `worktree-agent-add8052fcf1842aba` (K1427) → `git branch -D` ✅ deleted (was `4d3381dd`)
- `worktree-agent-a984dee3c1e31ca5c` (K1423 PCA) → ✅ recovered to `experiments/K1423_pca_sector_alpha/` then branch `-D` deleted (was `d15e5726`)
  - Recovery rationale: orphan K1423 = `PCA + factor regression — sector-ETF alpha (US vs TW semis)`, **topic-distinct** from existing `experiments/K1423_ewma_hurst_pilot/` on `main`. Suffix-named to keep both.
  - Recovered files: `README.md`, `k1423.py`, `k1423_results.json`, `fig1_pca_explained_var.png`, `fig2_alpha_before_after.png`, `fig3_pc1_loadings.png`

Verification:

- `git branch -vv | grep worktree-agent` → empty (no orphan refs remain)
- `git worktree list` → only main + refactor worktree registered
- `experiments/K1423_pca_sector_alpha/` populated with 6 files

Status: **CLEANUP COMPLETE**. Task `platform_ops_orphan_branch_audit_20260610` was already marked `succeeded` (audit work); this commit adds the executed actions to the audit trail.
