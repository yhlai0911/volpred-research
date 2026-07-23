# 判準／Actuator 全量裁決（2026-07-22）

來源：`assign_165c6a91`。判準能算出結論不代表它一定該自動改狀態；本次逐一依
「接 alert/task actuator」或「明定 operator/research diagnostic」裁決，避免留下只有
紅色日誌，也避免把需要人類決策的動作錯接成自動 mutation。

| 判準 | 裁決 | 唯一 actuator / 理由 |
|---|---|---|
| `check_session_health.evaluate` | operator diagnostic | `/clear` 是互動 session 動作，背景程序不能安全清掉使用者對話；移除 cron-friendly 宣稱。 |
| `check_persistence_stability` | research diagnostic | rolling GARCH 是重運算，window 變更須經 reviewed experiment/backtest；重跑走 compute queue，不自動改 `daily_update.py`。 |
| `audit_arc_dedup_overmatches.find_overmatches` | **接線** | verdict 移到 `volpred.ops.content_actuator_audits`，由 `content_quality_snapshot` 送進 hourly alerts；breach 會進既有 remediation task lifecycle。CLI 只負責 drill-down。 |
| `audit_audience_classification.build_report` | **接線** | 同上；HIGH-confidence general→research 候選成為 content-quality breach，但實際 reclassify 仍須正式更新流程，禁止直接改 feed JSON。 |
| `audit_topic_clusters` | operator drill-down | 自動 enforcement 已由 `check_arc_diversity` → alerts 擁有；90-day CLI 保留樣本診斷，不建立第二套 concentration owner。 |
| `foreign_disposition.apply_disposition`（反向形狀） | operator-gated actuator | `scripts/foreign_disposition.py --apply` 就是唯一 caller；自動呼叫必須猜 ownership/disposition，違反該模組的 zero-inference contract。 |

回歸驗收：arc overmatch 或 HIGH audience candidate 存在時，
`alerts._parse_content_quality_state` 必須回傳 `breached=True`，並在 title/body 指出對應
subcheck；不存在時不新增 breach。
