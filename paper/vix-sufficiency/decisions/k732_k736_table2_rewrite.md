# Paper 4 Table 2 Rewrite Decision — K732 + K736
**Date**: 2026-04-19
**Source**: task_7100e5d03ec2 + task_27ea42d3e0eb root cause analysis (agent a750dc)
**Target**: Sub4 body_v3.tex 更新 (task_729e70de0f66) 用此 spec

## K732 (behavioral sentiment)

**Root cause**: Paper body 抄錯格 — `IS t-stat=1.64` 實為 `dm_stat_oos=1.637` 複製到 IS 列。

**Decision**: 研究誠實 §13 (b) 更新 paper 為 canonical values。

**New Table 2 K732 row** (replace current row in main_v2.tex L420-ish):
| Column | Value | Source JSON field |
|---|---|---|
| partial_r | **0.086** | experiments/k732/k732_table2_expose_results.json .fields.partial_r.canonical_rerun_2026_04_18 |
| IS t-stat | **5.29** | (from k732 script `bsi_t_stat` = 5.58 at 5d fwd_rv, canonical 22d fwd_rv = 5.29) |
| R²_OOS,CT | **0.297** | .fields.r2_oos_ct.canonical_rerun_2026_04_18 |
| DM |t| | **0.67** | .fields.dm_abs_t.canonical_rerun_2026_04_18 |
| Raw p | **0.50** | .fields.raw_p.canonical_rerun_2026_04_18 |

**Body .tex inline comment**:
```latex
% source: experiments/k732/k732_pcr_behavioral_sentiment_results.json (canonical rerun 2026-04-19)
% was paper v1 抄錯格 bug: 1.64 來自 dm_stat_oos, 不是 IS t-stat; corrected to canonical rerun
```

**Errata note** (加到 Section 5.2 或 appendix):
> An erratum to main_v1 Table 2 K732 row: the value 1.64 reported as IS t-statistic was erroneously copied from the out-of-sample Diebold-Mariano statistic. Canonical re-estimation (seed=42, 22d forward RV, rolling 252 OLS, HAC bandwidth=22) yields IS t-statistic = 5.29, consistent with the script's Model-2 OLS (bsi_t_stat = 5.58 at 5d forward RV). Table 2 has been updated to the canonical rerun values.

## K736 (calendar anomaly)

**Root cause**: Composite salad — 3 sub-experiments 混搭欄位。

**Decision**: (b) Split 3 rows 優先 OR (c) 替換為單列 canonical rerun。

### Option (b) — Split 3 rows（推薦）

| Row | Sub-experiment | Value | Source |
|---|---|---|---|
| Calendar-VIX (seasonal) | part_a: VIX summer vs winter | t=-2.39, p=0.017 | k736_calendar_anomaly_vt_results.json .part_a |
| Calendar-SPY (seasonal return) | part_b: SPY winter vs summer | t=0.463, Halloween win rate 70% | .part_b |
| Calendar-VT weight (β in 3-factor) | part_c.regression: β_calendar | t=-0.15 in {α, TSMOM, Cal} regression | .part_c.regression |

### Option (c) — Single canonical row（備選）

| Column | Value |
|---|---|
| partial_r | -0.004 |
| IS t-stat | -0.27 |
| R²_OOS,CT | 0.357 |
| DM |t| | 0.21 |
| Raw p | 0.83 |

**Body .tex inline comment**:
```latex
% source: experiments/k736/k736_calendar_anomaly_vt_results.json .part_a/.part_b/.part_c.regression (split)
% was paper v1 composite bug: single row scrambled across 3 sub-experiments; split per research honesty §7
```

## Execution (Sub4 task_729e70de0f66)

1. Read `paper/vix-sufficiency/main_v2.tex` find Table 2 K732 row L420
2. Replace K732 row per above canonical values + inline comment
3. Read Table 2 K736 row L428  
4. **Decide (b) split or (c) single** — recommend (b) for honesty; (c) if page count constraint
5. Update body_v3.tex preserving other rows intact
6. Add errata note in Section 5.2 or appendix
7. Update citation_check.md findings: harvey2016 L48 + L80 fix (Sub5 citation audit 另案)
8. `uv run volpred ops paper-update --paper-id vix-sufficiency` (CLI gate 驗)

## Related Sub tasks

- Sub3 task_7d25315e95b8: 其他 5 divergence 決策（Codex pending）— 納入 body_v3 同時處理
- Sub6 task_ee64824bf955: Body 更新後 reproduce full re-run 驗 >95% match
