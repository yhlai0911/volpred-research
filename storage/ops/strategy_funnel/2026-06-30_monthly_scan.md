# Strategy Candidate Funnel — 2026-06-30 月度 scan

**Scan window**: 2026-06-01 ~ 2026-06-30（30 天）
**Source**: `storage/memory/knowledge.json` verdict=PASS/CONDITIONAL_PASS
**Filter**: keyword scan on content/summary（sharpe/position/exposure/weight/策略/actionable/trading/long-short/VT/long-only）

## 結論：0 actionable forecast signal candidates 進 strategy_lifecycle

近 30 天 PASS / CONDITIONAL_PASS K 約 60+ 條，filter 後 12 條進入 manual review，無一符合 actionable funnel 三條件：

1. OOS-verified vol forecast DM significant 且 calibration OK
2. 有清晰 long/short/timing rule
3. Sharpe gate 可 pass（保守 ≥0.6 net of cost）

## Manual review 12 條結果

| K | verdict | 排除原因 |
|---|---------|---------|
| K1422 | PASS | Commodity HAR-QR tail forecast DM sig，但 QR q05 Kupiec rejected GLD/UNG（coverage gap -2.36pp / -2.28pp）；calibration 未過，不能直接 paper-trade |
| K1341 | PASS | Russell/S&P reconstitution mean-reversion NOT supported；persistence > reversion |
| K1529 | PASS | Tax-friction degradation of VT / Risk-Parity existing rules；既有策略 tax adjustment，非新 funnel candidate |
| K1334 | C.PASS | Downside-CVaR 99% exposure target NULL vs 63d vol target（bootstrap CI cross 0） |
| K1509 | C.PASS | TIPS regime-conditional vol decomposition descriptive；無 trading rule |
| K1471 | C.PASS | VT-crowding ABM redesign — VT Sharpe 隨 adoption 單調侵蝕；risk insight 非 actionable signal |
| K1445 | C.PASS | URA/KRBN alt-asset vol clustering descriptive PoC |
| K1417 | C.PASS | Paper 3 v4 bootstrap MDD CI（既有 VT-trend 策略 robustness） |
| K1056 / K1057 | C.PASS | Article review 24h-rule |
| K1423 | C.PASS | Time-Varying Hurst pilot（H mean=0.50，無 actionable rule） |
| K698 | C.PASS | Contrarian VT 既有策略 review |
| K772 | C.PASS | Overnight/intraday decomposition methodology |

## Funnel pattern observation（actionable insight）

近 30 天研究 effort 偏向：
- **Paper R1 narrative + methodology refinement**（K1416 HLN retrofit、K1417 bootstrap CI、K1422 fair baselines）
- **NULL findings 累積**（K1334 / K1341 / K1471 / K1473 等 risk-insight）
- **Descriptive PoC 與 review**（K1509 / K1445 / K772 / K1056 / K1057）

**vs 策略開發**：~0 新策略 candidate experiment（per memory `feedback_strategy_dev_over_audit` 老闆 standing directive: 策略開發 effort > audit 舊）

## 不行動

1. **不派 strategy_lifecycle subtask** — 無候選符合 funnel gate
2. **不下架既有策略** — per `feedback_strategy_dev_over_audit` + K1573 教訓（vol-targeting 數學特徵不是 bug，audit 發現「同質性」不觸發下架）
3. **3 檔 inactive 待 audit 不翻 active** — tz_tw_jp / taiwan_spy_momentum / global_vt_tz 維持 inactive 直到 lookahead audit 通過（per `project_strategy_lifecycle_standing_directive`）

## Forward proposal

Funnel 空 + standing directive 偏好策略開發 → 應 enqueue 1-2 條 **新策略開發 experiment** 補 funnel，候選方向（從 publication_candidates uncovered K + journal topic discovery）：

- **Earnings announcement vol crush + put-skew timing**（覆蓋 Section-3 missing earnings）
- **Cross-asset RV spillover signal**（K1509 TIPS regime-aware 概念延伸到 cross-asset rotation）
- **Tail-risk timing via realized semi-variance**（已有文獻基礎，未在 platform 上跑）

不在本 ops task scope，記入 next research backlog（不 hard enqueue 避免污染 dispatcher）。

## Next monthly fire

**Cadence**: 月度，下次 2026-07-30。
