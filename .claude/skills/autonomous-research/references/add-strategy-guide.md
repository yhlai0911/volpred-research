# Strategy Platform Handoff

本文件是通過`strategy-launch-gate.md`後的相容入口。研究skill不直接上架策略；
canonical metadata與active status以`STRATEGY_REGISTRY`及`docs/strategy-registry.md`為準。

## Preflight

1. 執行`uv run python scripts/task_pool_control.py status`。
2. 回讀`config/project_targets.json`；不保存frontend/service/path副本。
3. 回讀current strategy registry與active peer set。
4. 確認experiment artifact、review verdict與knowledge item仍指向相同bytes。

## Research handoff package

- strategy key與明確weight/signal formula
- information set與lag
- same-period evaluation receipt
- cross-OOS、sensitivity、cost、turnover與risk evidence
- experiment id、canonical result/spec、review及knowledge provenance
- operating explanation與article proposal

缺任一項回到HOLD，不用平台mutation補證據。

## Platform owner actions

平台owner依canonical CLI與registry contract處理：

- metadata/upsert：`uv run volpred ops strategy-upsert ...`
- active status：`uv run volpred ops strategy-set-active ...`
- metrics/daily update：使用`uv run volpred ops ...`正式入口
- frontend/runtime target：由`config/project_targets.json`解析

實際arguments、schema及required fields每次從CLI help與registry文件取得；本skill不複製。
不呼叫private DB helper，不手改歷史paper-trading資料，不直接複製frontend檔案。

新策略只從正式forward-tracking流程自然累積；歷史比較保留在experiment artifact。

## Read-back

上架不能只看command exit：

- registry的strategy key、display metadata與active state
- strategy API/DB acknowledgement
- metrics對應current target
- 下一次正式daily calculation的weight與tracking receipt
- article linkage（若發布owner已完成）

任一read-back不一致時`contained`並交平台owner修root cause。

## Task mode

若需platform follow-up，每次materialize前重新讀task-pool mode：

- queued execution：走canonical producer。
- direct execution：保留handoff或在已授權時使用GitHub Issue；不新增legacy task。
- restore/unreadable：fail closed。
