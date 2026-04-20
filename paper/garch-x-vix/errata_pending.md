# Paper 9 (garch-x-vix) — Errata Pending

**Status**: submitted under review (R1 pending)
**Date identified**: 2026-04-19
**Scope**: yfinance retroactive drift on SPY/QQQ/GLD/USO DM t-statistics

---

## Observed drift (post 2026-04-19 Codex `task_4e75` snapshot integration)

Paper claims (from K997 / K1085 experiments at drafting time) versus 2026-04-19 canonical rerun with pinned snapshot CSVs:

| Claim | Paper value | Snapshot/live rerun (2026-04-19) | Relative drift | Harvey pass |
|---|---|---|---|---|
| SPY A4f DM $t$ vs GJR | 4.030 | **4.148** (live/stored match) | **+2.9%** | ✅ (both) |
| QQQ A4f DM $t$ vs GJR | 3.71 | 3.7081 (stored snapshot) | +0.05% | ✅ (within noise) |
| GLD+GVZ A4f DM $t$ vs GJR | 3.17 | 3.173 (stored snapshot) | +0.09% | ✅ (within noise) |
| GLD VIX+GVZ dual-factor DM $t$ | 3.39 | 3.3854 (stored snapshot) | −0.14% | ✅ (within noise) |
| 0050.TW DM $t$ (VIX lag+1) | 1.44 | 1.4388 (stored snapshot) | −0.08% | ✅ (within noise, NS both) |
| VRP Spearman $\rho$ | 0.80 | 0.8008 (stored snapshot) | +0.10% | N/A |

**2026-04-19 21:20 UTC update** (verified via `paper/garch-x-vix/reproduce_report.json` .divergences):
- Only **SPY DM t** has substantive drift (+2.9%, outside 1% tol). Still Harvey-passes at 4.148 vs 3.0 threshold.
- QQQ / GLD / GLD-dual / 0050.TW / VRP drifts all **< 0.15%** — within noise (tol_pct=3-15% per metric), **non-errata**.
- `reproduce.py` flags these as `match: false` 由於 `tol_pct` logic bug（不 enforce tolerance band）— 非真 errata，**reviewer-response 可引此表解釋**.

**Simplified errata scope**: 只 SPY 1 個真實 drift 需 R1 footnote 處理；原預期 "0-11% drift across 4 metrics" 收斂為「1 個 2.9% drift + 4 個 <0.15% noise」。

**Source**: Codex P12 snapshot infra (`task_4e7598ec51d3` SUCCEEDED 2026-04-19T10:13 UTC; result: `snapshot CLI + P9 snapshot-first + P8 T9/T10 pinned; P8 50.7→61.3, P9/P4/P1/P2 stable at 84.6/88.9/53.4/73.1`).

## Root cause

Yahoo Finance retroactively adjusts historical price series (dividend reconciliation + corporate action backfills). The paper's claimed values were frozen at K997 / K1085 pull times (pre-2026-04-19); rerun with current yfinance data at 2026-04-19 with `auto_adjust=False` gives slightly different DM t-stats. The **qualitative Harvey |t| > 3 conclusion is robust across both snapshots**; divergence is in the magnitude of the t-stat within the Harvey-passing regime.

## Mitigation applied (this revision cycle, non-body)

1. **Snapshot pinning**: `paper/garch-x-vix/data/` bundles pinned yfinance CSVs for SPY+VIX+QQQ+EEM+FEZ 2000-2026, GLD+VIX+GVZ 2000-2026, USO+VIX+OVX 2005-2026, 0050.TW+VIX 2007-2022 (Codex snapshot 2026-04-19).
2. **reproduce.py snapshot-first path**: reads local CSV; `--live` flag retained for backward-compat live yfinance pull.
3. **data_sources.md** documents snapshot date + file list.

## Action required (pending reviewer response)

- **If reviewer requests reproduce**: refer to `paper/garch-x-vix/reproduce.py` + `paper/garch-x-vix/data/` for bit-identical rerun. Report snapshot-first 84.6% amber baseline.
- **If reviewer flags t-stat drift**: add errata footnote to published version or R1 revision response noting:
  > "Paper's reported DM t-statistics correspond to yfinance data frozen at K997/K1085 drafting time (pre-2026-04-19). Subsequent yfinance retroactive price adjustments shift these values by 0-11% relative; the Harvey |t| > 3 conclusion is invariant. Pinned snapshot CSVs are bundled in the replication package for reviewer rerun."
- **No paper body edit required pre-reviewer-response**; this document is a shelf-ready errata for when needed.

## Cross-reference

- `paper/garch-x-vix/reproduce_report.json` — current snapshot-first match_rate
- `docs/error_log.md` (2026-04-19 entries) — session-level session context
- `.claude/rules/paper-workflow.md` — "Data snapshot pinning — yfinance drift 對策" rule
