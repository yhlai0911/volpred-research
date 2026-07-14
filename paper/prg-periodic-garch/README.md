# Paper 6: Forecast-Timing Conventions and the Value of Overnight Information in Volatility Forecasting

**Target Journal**: Finance Research Letters (FRL)
**Status**: v7 major rewrite (2026-07-14) — headline pivot to the **timing-convention flip**; body rewritten, reproduce gate 100% GREEN (26/26). Pending: v7 review cycle (latex-academic-reviewer + citation-verifier + Codex) before any ready/submit flag.
**Manuscript**: `main.tex` (9 pp double-spaced; body ≈1.9k words ≤2,500; abstract 249 ≤250). Pre-rewrite version frozen as `main_pre_v7.tex`.

## One-sentence claim (v7)
The same session-level volatility model (PRG), on the same pinned data, delivers DM statistics against its benchmark from −2.3 to +10.1 depending only on the forecast-timing convention; evaluated coherently, overnight information has real value at the open horizon (5/6 markets Harvey-significant vs an information-matched GJR-X) and none at the day-ahead close horizon (0/6 vs GJR).

## Canonical evidence (v7) — single pinned vintage 2026-07-12
| Experiment | Panel | Result |
|---|---|---|
| `experiments/k1699/` | Close convention (six markets) | 0/6 Harvey vs GJR (both plug-in variants); Codex PASS_WITH_CAVEAT; bit-identical reruns |
| `experiments/K1710/` | Mixed anchor + Open panel + ON shares (same snapshots, SHA-asserted) | Mixed 6/6 Harvey (+4.3..+6.4); Open 5/6 Harvey vs fair GJR-X (QQQ +1.56 NS); Codex PASS; bit-identical |

All prices dividend/split-adjusted (disclosed in Data section); snapshots pinned under `experiments/k1699/data/` and `experiments/K1710/data/` with `float_precision="round_trip"` reads.

## Reproduction
```bash
uv run python paper/prg-periodic-garch/reproduce.py          # JSON→tex binding gate (no live fetch)
uv run python paper/prg-periodic-garch/scripts/gen_flip_table.py  # regenerates Table 2 rows + prose numbers
```

## Historical note (pre-v7 lineage)
The v6-era manuscript ("Session-Boundary Information Transfers") reported mixed-timing headline DM values (SPY 6.00 etc.) built on unpinned, vintage-drifting yfinance pulls via K874c/d/e, K880/K880b/K880v2, K881/K881b, K883/K884, K886, plus VaR/ES and VT-economic tables. K1544 (2026-06-24) showed a fair current-overnight GJR-X beats the mixed-timing PRG object in all six markets, triggering the narrative pivot; the 2026-07-11 Fable deep review specified the dual-convention rewrite. Those legacy tables were removed in v7 (re-addable only from pinned reruns — see EXECUTION.md P1). Full errata archaeology: `review_history/fable_deep_review_20260711/P0-1_errata_map.md`.
