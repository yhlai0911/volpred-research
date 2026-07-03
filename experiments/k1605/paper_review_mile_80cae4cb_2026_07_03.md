# K1605 — 24h-of-publish Codex review (mile_80cae4cb)

- **Task**: `paper_review_mile_80cae4cb` (Codex 24h-rule, per `.claude/rules/agent-delegation.md` K1018 lesson)
- **Reviewer**: Codex (`codex exec`, gpt-5.4, read-only) — 2026-07-03
- **Article**: 「K1605：區域銀行 M/B 折價與後續波動，橫斷面穩健、OOS 不過關」(published 2026-07-02)

## Verdict: CONDITIONAL_PASS

| 面向 | 結論 |
|---|---|
| Lookahead bias | PASS — book equity filing lag + `signal.shift(1)`；forward RV `(t,t+H]`；OOS 訓練列 `df.iloc[: i - h]` 滿足 `target_end < forecast_origin` |
| DM / Harvey | PASS — `d = loss_rv_only - loss_mb` 方向正確、HLN correction、two-sided p、horizon-specific `h` 皆到位 |
| Fama-MacBeth | PASS — 日度 FMB（非月度），date-level slope → Newey-West/HAC，未把 asset-day 當 iid |
| Claim vs evidence | CONDITIONAL — 標題「橫斷面穩健、OOS 不過關」與 JSON 一致；發佈文章敘述正確。唯 README:148「Every rmse_improve_pct is negative」不精確 |
| Seed / sample / pooled iid | PASS — seed 固定、n 揭露、非 pooled asset-day iid |

## 必修項（已處理）

- **README:148** 原「**Every** `rmse_improve_pct` is negative」→ 修正為指出唯一微幅正值 `q60_a90 / KBE_h22 = +0.0179%`（DM p=0.990，無經濟/統計意義）。中心結論不變。
- **發佈文章無需修改** — 文章敘述為「加入 M/B 沒有改善 KRE/KBE 樣本外波動率預測」，本就正確；此不精確僅存於內部 README。

Codex tokens used: ~88.5K。
