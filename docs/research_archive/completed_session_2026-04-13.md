# Session 2026-04-13 Completed — 22+ experiments + infrastructure overhaul

**Session scope**: Paper 2/3 dead-end closures + Paper 4 universal IV sufficiency compendium formation + skill architecture refactor + Taiwan microstructure Cont-Tankov decomposition discovery.

**Token cost**: ~$2,237 week total (week 4/10–4/17), ~70% spent this session.

## Experiments (22 complete)

### Paper 2 Taiwan firm-selection (route exhausted)
| K | Title | Verdict |
|---|-------|---------|
| K1067b | UMC A4f-EAV | MIXED (event +39% PASS, full OOS Harvey NS) |
| K1067c | MediaTek A4f-EAV | MONOTONICITY FAIL (decisive reverse) |
| K1103 | τ-lag bug-fix 3-firm | SCENARIO STABLE (K1067b/c results hold) |
| K1104 | N=24 sector regression | fabless p=0.039 * |
| K1106b | N=14 sector-diversified | **fabless p=0.004 *** (cherry-pick artifact)** |
| K1109 | Pre-reg random N=31 | sector REJECTED (BH-adj p=0.278) |
| K1113 | Firm-level 6 covariates | STRONG NULL (CV R²=-0.66, Tier A=0) |

**Meta**: Observable firm attributes cannot predict EAV heterogeneity. Need private data.

### Paper 3 copula-GARCH (route exhausted)
| K | Title | Verdict |
|---|-------|---------|
| K1100 | SPY-GLD Student-t/Clayton | NULL (tail-independent) |
| K1100b | 5 equity pairs | NULL all (incl SPY-QQQ λ_L=0.589) |
| K1100f | SPY-ES spot-futures + PRG | NULL (high-ρ portfolio degeneracy) |
| K1100g | TAIFEX vs SPY microstructure | Dim2 overnight anchor (later disproven) |
| K1100g_d1 | TAIFEX day vs night PRG | in-sample LRT χ²=12.5 (OOS rejected) |
| **K1100g_d2** | **OOS validation** | **K1100g_d1 REJECTED** (LRT 0, DM reverse) |
| K1115 | SPY VaR breach clustering | NULL (GARCH absorbs clustering) |

**Meta**: E055 three conditions (collinear / tail-dependent / single-asset) ALL rejected. Lai 2024 PRS is TAIFEX-specific not generalizable.

### Paper 4 Universal IV Sufficiency (FORMING)
| K | Title | Verdict |
|---|-------|---------|
| K1116 | FRED EPU+NFCI+STLFSI on SPY | NULL (strong negative) |
| K1116b | Publication-delay verification | TLT "niche" was bug artifact; narrative STRENGTHENED |
| K1118 | Cross-asset GLD/TLT/BTC native IV | NULL all |
| K1121 | Alt-data allocation 6 strategies | NULL all (p>0.16 vs 50/50) |

**Meta**: Paper 4 compendium = 10 experiments × 5 asset classes × 2 applications, all NULL. Target: Journal of Forecasting.

### Taiwan microstructure (new paper candidate)
| K | Title | Verdict |
|---|-------|---------|
| K1124 | TAIFEX OFI diffusive vol | NULL with stylized fact (Taiwan mean-revert) |
| K1125 | OFI × jump prediction | DM t=+2.82 significant, sell-side asymmetric |
| K1128 | VIX tertile regime | OOS-internal high-VIX DM +3.59 but IS degenerate |

**Meta**: K1124+K1125 = Cont-Tankov (2004) decomposition empirically confirmed on TAIFEX. Paper Taiwan microstructure candidate.

### Model compendium — GAS
| K | Title | Verdict |
|---|-------|---------|
| K1129 | GAS-t on USO/GLD/UNG/BTC | 4/4 NULL, BTC DM -4.58 reverse |

**Meta**: Combined with K437/K1038 equity NULL = 8+ assets GAS NULL. Fold into Paper 4 as alt-model NULL category.

## Major infrastructure changes

1. **Option B question-claim** — atomic status transition `ranked → researching` prevents cross-session member_qa race (commit 873f1310)
2. **Monitor session-start integration** — scripts/session_startup.md + CLAUDE.md pointer (Monitor session-only must set each session)
3. **Cron 3min → 4min heartbeat** — cache TTL 5min, 25% heartbeat cost reduction
4. **Paper workflow 3-skill refactor** — paper-stage-classifier / paper-review-cycle / paper-update (separation of concerns)
5. **Review report archive structure** — paper/<id>/review_history/v<n>/ Markdown format, git-tracked
6. **docs/skill-registry.md** — canonical skill index with scope boundaries + handoff map
7. **Event article cadence** — T-7/T-2/T+0/optional T+1, 2 previews + 1 immediate + 0-1 followup quota
8. **CLAUDE.md slimming** — 107 lines moved to scripts/session_startup.md; Monitor + cron + paper SOP → skills

## Critical experiences recorded (E044–E065)

- **E052/E053** — Cherry-pick bias in hypothesis-driven sampling; pre-registration 2-commit audit trail
- **E054** — Paper 2 firm-selection exhaustion verdict
- **E055/E056** — Copula domain constraints; pivot depth 4-level framework
- **E057** — Hypotheses-fail-but-experiment-contributes pattern
- **E058** — Parquet cache mask-bug (K1100g night_open/close)
- **E059** — LRT-vs-DM divergence as overfit warning
- **E060** — When to stop挖 a direction (L4 framing change needed)
- **E061** — Knowledge-base precheck saves duplicate experiments
- **E062** — FRED publication-delay hidden lookahead
- **E063** — Lee-Mykland BV window slicing + OOS standardization
- **E064** — IS-based regime cutoffs degenerate on unprecedented volatility
- **E065** — Triple-gate saves false positive; score-driven hurts in extreme regime

## Error log additions (2026-04-13)

1. LRT+DM divergence overfit pattern (K1100g_d1 → K1100g_d2)
2. Parquet cache mask-bug (K1100g)
3. FRED publication delay (K1121)
4. TAIFEX bar-bucket + active contract lookahead (K1124)
5. BV window + OOS standardization leakage (K1125)
6. IS-based regime cutoffs degeneracy (K1128)

## Pending user decisions (carry over)

1. **Paper 3 strategic** (A negative paper / B TAIFEX microstructure / C abandon) — now tentatively deprioritized to priority 4
2. **Paper 4 main-thread writing start** — vix-sufficiency expansion plan v2 ready, +9.2p → 48p
3. **leverage-direction v3** — v2 review complete (7 HIGH issues), need main-thread fixes
4. **TSMC 04/16 hot-take** — gated until 04/16 14:00+

## Notes for 2026-04-14+

- ~2200/week token spend running hot (cache + 22 experiments)
- Reply verbosity should go down (E059/E060 pattern: strategic summaries can be 3-4 lines)
- Paper 6 (crypto fear) untouched today, K639/K746b/K1025 素材齊備
- Papers 7/8 still early stage (<20p), not review-ready
