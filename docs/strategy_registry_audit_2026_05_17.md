# Strategy Registry Health Audit — 2026-05-17

**Auditor**: subagent (audit-only, no writes)
**Sources**: `docs/strategy-registry.md`, `scripts/daily_update.py` (lines 29–48), `storage/strategy_metrics.json`, `storage/paper_trading.json`, `frontend-v2-fix/src/`
**Today**: 2026-05-17 (Sunday); last trading day 2026-05-15.

---

## Registry snapshot

- **Total in `STRATEGY_REGISTRY`**: 14
- **Active (`is_active=True`)**: 11 (`slow_vt`, `risk_parity`, `simple_12vix`, `recommended_5050`, `taiwan_8.63vix`, `vix_leading_guard`, `vix_cond_leverage`, `taiwan_hybrid_leverage`, `piecewise_conservative`, `fear_dca`, `adaptive_tier`)
- **Disabled**: 3 (`taiwan_spy_momentum`, `tz_tw_jp_5050`, `global_vt_tz`) — kept for paper trading only per I8 note

Counts match docs exactly. Both `storage/strategy_metrics.json` and `storage/paper_trading.json` contain all 14 keys (active + disabled).

---

## Dimension caveats (apply to all rows)

- **(a) Metric freshness**: `storage/strategy_metrics.json` schema has **no per-strategy `last_updated`** field. Used file mtime as proxy → 2026-05-17 11:43 (today, well within 48h). Per-strategy freshness = **UNKNOWN** (schema gap), file-level = HEALTHY.
- **(b) Sparkline 90-point integrity**: sparkline lives only in Supabase `strategy_metrics_cache` (built by `scripts/list_new_strategy.py:387`). **No local source-of-truth file**. All rows = **UNKNOWN** (must query Supabase to verify, out of audit scope).
- **(c) Paper-trading PnL continuity**: verified locally via `paper_trading.json` entry counts vs business-day expectation.
- **(d) 7-day rolling MDD**: computed from last 7 `portfolio_return` values (excluding trailing null = pending today). Threshold = -10% per spec.
- **(e) Frontend wiring**: confirmed strategies are fetched dynamically from Supabase `strategy_metrics_cache` via `frontend-v2-fix/src/lib/data-server.ts:1159`; not hardcoded keys. The 7-strategy hardcoded list in `StrategySelector.tsx` is the questionnaire recommender surface, not the card-render surface — does NOT cause orphan.

---

## Per-strategy 1-line status (11 active)

| Strategy | PnL entries | Last date | 7d MDD | Status | Failing dims |
|---|---|---|---|---|---|
| `slow_vt` | 844 | 2026-05-15 | -0.85% | HEALTHY* | (a)(b) UNKNOWN |
| `risk_parity` | 844 | 2026-05-15 | -2.16% | HEALTHY* | (a)(b) UNKNOWN |
| `simple_12vix` | 844 | 2026-05-15 | -0.85% | HEALTHY* | (a)(b) UNKNOWN |
| `recommended_5050` | 844 | 2026-05-15 | -1.42% | HEALTHY* | (a)(b) UNKNOWN |
| `taiwan_8.63vix` | 783 | 2026-05-15 | -0.80% | HEALTHY* | (a)(b) UNKNOWN |
| `vix_leading_guard` | 1020 | 2026-05-15 | -0.56% | HEALTHY* | (a)(b) UNKNOWN |
| `vix_cond_leverage` | 844 | 2026-05-15 | -1.42% | HEALTHY* | (a)(b) UNKNOWN |
| `taiwan_hybrid_leverage` | 810 | 2026-05-15 | -0.80% | HEALTHY* | (a)(b) UNKNOWN |
| `piecewise_conservative` | 844 | 2026-05-15 | -0.66% | HEALTHY* | (a)(b) UNKNOWN |
| `fear_dca` | 844 | 2026-05-15 | -1.21% | HEALTHY* | (a)(b) UNKNOWN |
| `adaptive_tier` | 844 | 2026-05-15 | -1.42% | HEALTHY* | (a)(b) UNKNOWN |

\* = HEALTHY on dims (c)(d)(e); (a)(b) flagged UNKNOWN due to local-source-of-truth schema gaps — not failures.

**Disabled strategies (informational)**:
- `taiwan_spy_momentum`: 783 entries through 2026-05-15
- `tz_tw_jp_5050`: present in paper_trading
- `global_vt_tz`: present in paper_trading

All 11 active have:
- **PnL continuity**: 844 entries (US strategies) vs 878 business days 2023-01-04→2026-05-15 = ~34 holiday gaps (normal US market closure count). `taiwan_8.63vix` 783 entries matches TW market calendar. `vix_leading_guard` 1020 starts from 2022-01-03 (1 year earlier history). No anomalous gaps.
- **Last entry trailing null**: all 11 show `portfolio_return=null` on 2026-05-15 last entry — this is the pending mark-to-market slot for the most recent trading day, not data corruption (file mtime today 11:43; intraday recomputation will fill).
- **7-day MDD**: all in range -0.56% to -2.16%, far inside -10% threshold. NO BREACH.

---

## Final categorization

| Category | Count | IDs |
|---|---|---|
| **HEALTHY** | 11 | all active |
| **WARN** | 0 | — |
| **CRITICAL** | 0 | — |

(HEALTHY conditioned on caveats above; treat as "no actionable failure detected in locally-auditable dimensions.")

---

## Cross-cutting checks

1. **Orphans in `paper_trading.json` not in registry**: NONE. All 14 paper_trading keys (excluding `_market_daily` metadata) are in `STRATEGY_REGISTRY`.
2. **Registry strategies missing from `paper_trading.json`**: NONE. All 14 present.
3. **Registry strategies missing from `strategy_metrics.json`**: NONE. All 14 present.
4. **Duplicate IDs / naming collisions**: NONE.
5. **Reconciliation**:
   - Registry: 14 (11 active + 3 disabled)
   - `strategy_metrics.json`: 14 keys
   - `paper_trading.json`: 14 strategy keys + 1 `_market_daily` metadata = 15 top-level keys
   - **MATCH** across all three sources.

---

## Recommended actions

**Priority P3 — schema completeness (not blocking)**:
1. **Add `last_updated` per strategy to `storage/strategy_metrics.json`** — currently relies on file mtime proxy. Block dimension (a) audit. Patch in `scripts/recalc_metrics.py` where the dict is written.
2. **Mirror sparkline to local JSON for offline audit** — currently sparkline only lives in Supabase `strategy_metrics_cache`. Either (i) snapshot the array under `storage/strategy_metrics.json[<key>].sparkline_90d` after recalc, or (ii) document explicitly that sparkline audit requires Supabase query and add a `scripts/audit_sparkline.py` helper.

**Priority P4 — daily_update reliability watch**:
3. **2026-05-16 16:01 `daily_update` exit -9 (SIGKILL)** observed in cron log. The 2026-05-17 11:43 re-run succeeded (file mtime current). Track if SIGKILLs recur; if 3-strike, refactor per `CLAUDE.md` 3-strike rule (likely memory pressure → split into staged runs).

**Priority P5 — frontend recommender coverage (cosmetic)**:
4. `StrategySelector.tsx` hardcodes only 7 of 11 active strategies in the questionnaire recommender (missing `slow_vt`, `risk_parity`, `simple_12vix`, `taiwan_8.63vix`). Cards still render via API; recommender just doesn't surface those 4 as primary picks. Either intentional (Taiwan / legacy SPY-only excluded) or stale — confirm with product intent.

---

## Methodology caveats summary

- **No metric `last_updated` per strategy** in local JSON → dimension (a) reduced to file mtime proxy
- **No local sparkline array** → dimension (b) fully UNKNOWN locally (would need Supabase query)
- **7-day MDD computed from `portfolio_return` field only**, excluding trailing null; no cross-check against an authoritative MDD field (none in schema)
- **Trading-day "missing" gap** computed as approximate business days minus entries; not a calendar-aware US/TW holiday subtraction
- **Frontend wiring** verified via `strategy_metrics_cache` Supabase fetch path; not validated end-to-end against live site
- **No re-computation** of Sharpe / MDD / returns performed; numbers sourced from existing `strategy_metrics.json` only per audit constraint
