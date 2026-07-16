---
name: project_loop_engineering_layer
description: Loop-engineering 閉環層（loop-health 指標 + dreaming 慢 loop + 內容巡檢補完）2026-06-29 上線
process_owner: .claude/skills/platform-ops-manager/references/loop-health-and-dreaming.md
metadata: 
  node_type: memory
  type: project
  originSessionId: 84ae09c8-9673-48d4-b7bc-6113766e22dc
---

2026-06-29 落地的 **loop-engineering 閉環層** — 補上「系統有沒有在變好」這個 VolPred 原本缺的閉環（教學五件套裡 memory/skills/guardrails/progressive-disclosure 本來就成熟）。

**Fast loop** `src/volpred/ops/loop_health.py` → `uv run volpred ops loop-health`：4 個 derived 指標（first_pass_success / task_outcome / error_recurrence / correction_trend），搭 hourly ops_dashboard + check_alerts 便車、零新排程。breach 走 `alerts._parse_loop_health_state`（已接 build_alert_condition_report）。**error_recurrence 故意不獨立 breach** — cron-exit 即時告警是 host_cron_fail 的責任，跨 run 升級是 dreaming 的責任。dashboard 有 loop_health section。

**Slow loop** `scripts/dreaming_review.py` → `uv run volpred ops dreaming-run [--dry-run] [--apply-auto]`：每日 05:25 cron（`dreaming_review` job in runtime_schedules，piggy-back via check_alerts；wrapper `~/.volpred/bin/cron_dreaming_review.sh`，永遠 exit 0）。5 類 detector（repeated_tool_failure/recurring_error/stale_knowledge/missing_retry_strategy/loop_metric_regression）+ 滾動 baseline（`storage/ops/dreaming/baseline.json` per-signature strike count，連 3 次 = three-strike critical）。輸出 `storage/ops/dreaming/<date>.json`。

**硬邊界（研究誠實）**：治理檔（error_log/rules/CLAUDE.md/knowledge.json）一律 **propose-only** — dreaming 只寫 proposal + email，**絕不自動改**。auto 限：寫 report / append autonomous_decisions / email / retract 重複 digest / 派修復 task（`--apply-auto` 預設關）。

**內容巡檢補完**：`content_quality.py` 補了 4 個 check（arc_diversity / content_completeness / release_deadlock / frontend_render，frontend probe 預設關、hourly check_alerts 用 `VOLPRED_FRONTEND_PROBE=1` 開）。

**首跑發現**：(1) hourly_dispatch 06-26/27 近全班失敗（API 死，已恢復）— dreaming 正確 surface；(2) `alerts._parse_cluster_cap_drift_state` 的 recent_cluster_counts 不吃 storage_dir → 讀真實 feed、測試無法隔離（test_alerts 用 monkeypatch quiet）→ **待 follow-up 改 storage_dir-aware**。

SOP 在 [[feedback_skill_autonomy]] 管的 `.claude/skills/platform-ops-manager/references/loop-health-and-dreaming.md`。測試 `tests/test_loop_health.py` + `tests/test_dreaming_review.py`。
