# Loop-health 指標 + Dreaming 慢 loop（2026-06-29 loop-engineering 層）

本文件是運營經理「系統有沒有在變好」自省層的操作參考。被動載入；觸發 ops 相關 path 時隨 platform-ops-manager skill 一起可用。

## 為什麼有這層

既有監控回答兩個問題：「loop 還活著嗎」（`alerts.py` 的 freshness / dead-man switch）、「基礎設施健康嗎」（`health.py`）。都不回答 loop-engineering 的核心問題：**「loop 有沒有在變好？」**—— 同類錯誤是否反覆、任務是否一次完成、糾正是否變多。近期一串事故（FB rot、daily_update 假警報、dbcddc0 CI 紅、「安靜 tick」）共通點：**該被系統先抓到、卻靠老闆人工抓到**。這層補上那個閉環。

## 兩個 loop（刻意分層）

| | Fast loop | Slow loop |
|---|---|---|
| 模組 | `src/volpred/ops/loop_health.py` | `scripts/dreaming_review.py` |
| 何時跑 | 搭既有 hourly fire 便車（`ops_dashboard` / `check_alerts`），零新排程 | 每日 05:25 cron（`dreaming_review` job） |
| 做什麼 | 聚合 4 個指標成 snapshot | 跨 session 找重複失敗模式、產 findings + proposal |
| 入口 | `uv run volpred ops loop-health` | `uv run volpred ops dreaming-run [--dry-run]` |

## 4 個 loop-health 指標（全部 derived，附信號強度）

- **first_pass_success** — 近 14d 成功任務中一次完成的比例（從 work_log failed→succeeded 序列推導）。`status_history` 覆蓋率低 → 自帶 `coverage`；不足時回 `low_coverage`（info，不 breach）。
- **task_outcome** — 近 14d 任務終態 success/fail/blocked 比例（支撐紮實，主「有沒有在出貨」訊號）。
- **error_recurrence** — 重複的 cron 非零退出 + diagnostics tag。exit142 標 `known`（自癒，不升級）。**注意：cron-exit 即時告警是 `host_cron_fail` 的責任，loop_health 只記錄重複數據供 dashboard + dreaming，不獨立寄 alert。**
- **correction_trend** — 近 4 週糾正事件斜率（上升=品質退化）。

`overall` = 最差子狀態（`unknown`/`low_coverage` 不升級）。

## Dreaming 的 5 類 detector

repeated_tool_failure / recurring_error / stale_knowledge / missing_retry_strategy / loop_metric_regression。每個 fail-open（warn 後 skip）。輸出 `storage/ops/dreaming/<date>.json` + 滾動 `baseline.json`（per-signature 連續 run strike count）。

## Auto vs Propose — 硬邊界（研究誠實 + 永遠修流程不修資料）

讀 dreaming report 時依 `remediation` 欄判斷：

- **AUTO（一律安全，dreaming 自己做）**：寫 dated report、append `autonomous_decisions.jsonl`、寄 email。
- **AUTO-DISPATCH（低風險衍生狀態，建修復 task）**：gate 在 `--apply-auto`（**預設關**），且只對 three-strike escalation。預設 daily run 不派工 → 先人工審。
- **PROPOSE-ONLY（治理檔，絕不自動改）**：`docs/error_log.md` / `.claude/rules/*` / `CLAUDE.md` / `storage/memory/knowledge.json` / `docs/refactor_plan_*`。dreaming 只把建議寫進 report 的 `proposal` 欄 + `governance_target` + email。**主線程審完才手動套用。**

## Three-strike 升級

一個 signature 連 **3 次** dreaming run 都出現 → severity 升 `critical`、email level=critical。這是 `docs/refactor_plan_<topic>.md` Three-Strike 根治的種子。dreaming 不自動建 refactor_plan（屬 docs/，propose-only）—— 主線程開檔。

## 主線程收到 dreaming email 時做什麼

1. 看 `storage/ops/dreaming/<date>.json` 完整 findings。
2. 治理類 proposal → 評估是否套用（改 error_log / rule / knowledge），**手動**做，不讓 dreaming 改。
3. escalations(critical) → 開 refactor_plan 走 Three-Strike。
4. auto_dispatch 類（orphaned failure）→ 決定 retry 或 mark blocked（controlled reason）。
5. loop_metric_regression → 查對應 work_log / correction 根因。

## 已知 follow-up（2026-06-29 建置時發現）

- `alerts._parse_cluster_cap_drift_state` 的 `recent_cluster_counts` 不吃 `storage_dir` → 讀真實 feed，測試無法隔離（`tests/test_alerts.py` 用 monkeypatch quiet）。應 refactor 成 storage_dir-aware。
- 首次 dreaming run 抓到 `hourly_dispatch.log:exit1` 在 06-26/27 近全班失敗（API 死，06-29 已恢復）—— 真事故，dreaming 正確 surface。

## Enforcement Layer Map（2026-07-02 owner 指令「不要疊床架屋」落地）

每個 concern 只有一個 enforcement owner。新增約束時**先查此表挑既有落點**，不開新 runner/cron/hook file：

| 層 | Owner 機制 | 管什麼 | 現駐 checks |
|---|---|---|---|
| **L1 機械不變量** | `.claude/settings.json` hooks + `scripts/git_hooks/pre-push`（單一 runner）+ `.github/workflows/` | 每 turn / 每 push 必須成立的格式性約束 | Stop: final-text、save_session_state；pre-push: encoding sweep + silent-fallback baseline；CI: provenance、encoding |
| **L2 營運存活** | `check_alerts`（hourly piggy-back，單一 alert registry）+ email dedup | 「X 還活著/新鮮嗎」 | release gap / draft low / host cron fail / knowledge stale / paper stale |
| **L3 改善迴圈** | `loop_health`（fast）+ `dreaming_review`（slow，propose-only） | 「loop 有沒有在變好」 | 4 指標 + 5 detector；事故經 error_log 結構化 entry 餵進來，不另建 watchdog |
| **L4 行為指引** | CLAUDE.md（頂層 mandate）→ `.claude/rules/`（path 觸發）→ memory（背景 why）→ skills（SOP） | 需要判斷的行為 | 同一 concern 在 L4 內也只佔一個主位，其他位置放 pointer |

**收編規則**：
1. 新 invariant → 落 L1（既有 hook/runner 加 check），不建新 hook file。
2. 新 freshness/liveness 檢查 → 落 L2（alerts.py 加 entry），不建新 cron。
3. 新失敗模式偵測 → 落 L3（dreaming 加 detector），不建新 patrol script。
4. 行為被機械化（L4→L1）後，同 commit 把 L4 的長段 prose 縮成一行 pointer；why 留 error_log。
5. 違反此表 = 疊床架屋，code review / dreaming 應標 finding。

**前例**：encoding sweep（2026-07-02）正例 — 收進既有 pre-push runner + CI，零新層；final-text hook（同日）修正案例 — hook 上線同 commit 未收編 CLAUDE.md 長段，後補（見 error_log 14:25 entry）。
