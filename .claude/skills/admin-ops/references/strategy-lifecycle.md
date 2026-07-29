---
paths:
  - "scripts/daily_update.py"
  - "scripts/evaluate_new_strategy.py"
  - "storage/strategy_metrics.json"
---

# Strategy Lifecycle Handoff

策略資格與 active set 的 canonical 定義在 `STRATEGY_REGISTRY` 與
`docs/strategy-registry.md`；本 reference 只管通過研究 gate 後的平台投影。

## Sequence

1. 以 `docs/strategy-registry.md` 與正式 evaluator 確認同期間、cross-OOS、review、
   sensitivity、MDD gates 全過。
2. 在 canonical registry／calculation owner 完成策略變更；保留 inactive 策略的歷史
   identity，不刪除。
3. 查 live command contract：

   ```bash
   uv run volpred ops strategy-upsert --help
   uv run volpred ops strategy-set-active --help
   uv run volpred ops recalc-metrics --help
   ```

4. 透過 CLI 投影 metadata、active state 與 metrics，保存每個 receipt。
5. 從 public strategy overview 與 active frontend 的策略頁回讀 exact identifier、
   active state、metric date 與 display metadata。

不可旁路 canonical workflow 改 remote strategy row 或 metrics artifact。研究 gate
未過、projection mismatch 或時間基準不一致時，策略維持原狀並回到對應 owner。
