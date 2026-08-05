# resource_monitor 工作日誌（append-only）

## 2026-08-05T06:52:15Z — per-agent/per-model token 消耗分解報告 v1

- **outcome**: done
- **工作項**: `item_20260805T055820533785Z_per-agent-per-model-token-v1-to`（P2，已歸檔）
- **結論**: 平台 7 日（2026-07-29～08-04 UTC）billable 184.4M，Codex 佔 76.4% 且其中
  81.6% 是桌面互動而非自動化 backbone；同時查出兩個結構性會計缺陷——每日日報連續 6 天
  寫成 0（少記 141.1M）、Codex fork 讓單一對話被計為 76 個 session（重複上界 60.1M）。
- **產出**: `reports/2026-08-05_token_breakdown_v1.md`、
  `memory/token_breakdown_2026-08-04_7d.json`、`tools/token_breakdown.py`（可重跑）
- **未做**: F1/F2/F3 的修正都落在 `scripts/token_usage_report.py` 與 cron wrapper，
  不在本部門 owned_paths，**未自行修改**，已列 R1–R4 回報經理指派。
- **下次接手先看**: `memory/notes.md` 的「已知缺陷」與「分析陷阱」兩節。

## 2026-08-05T08:05:00Z — v2：異常規則、F2 定案、分類口徑修正

- **outcome**: done
- **工作項**: `item_20260805T074432202854Z_r5-r2-v1-f1-f2-platform-eng-own`（P2）
  ＋ `item_20260805T071751544758Z_f1-commit-dab112d3a-summaries-py`（P2），兩項均已歸檔
- **結論**:
  (1) R5 自辦完成 —— 新增 `agent_concentration`(>20%)、`session_longevity`(>48h)、
      `idle_burn_session`、`repeat_churn` 四條規則；同窗觸發 3 件（單一 Codex 桌面對話
      佔 34.2%、窗內存活 103.8h、main_thread 一處 Read×6 重複）。日級規則仍 0 件，證明
      v1 F4 的盲區是真的。
  (2) F2 定案 —— turn-level 重算得重複量 **4,067,614（Codex 2.89%／平台 2.21%）**，
      v1 的上界 60.1M **高估約 15 倍**，對外口徑須改用定案值；但 session 計數灌水是真的
      （280 → 131 個邏輯對話）。
  (3) 分類口徑 —— 欄位改名為 `mission_output_share_pct_upstream_NOT_KPI` 就地標死，
      並新增部門自有口徑：Claude 側 effectful **41.65%（下界）**，推翻「主線程只有 0.5% 產出」。
- **重要更正（發給 platform_eng 的 P1 request）**: v1 寫的「最小修法：session_id 改綁
  `session_meta.session_id`」**是錯的** —— 2815 個 rollout 檔有 2815 個相異
  `session_meta.id`，且該綁定自 `95831cdb6` 起早已存在。正確鍵是 `forked_from_id` /
  `parent_thread_id` 追到底的 fork root。已於 07:55Z 直送其 inbox（當時他們正在寫該檔）。
- **產出**: `reports/2026-08-05_token_breakdown_v2.md`、
  `memory/token_breakdown_2026-08-04_7d.json`（v2 schema）、`tools/token_breakdown.py`（v2）
- **未做**: F3（PRICING 覆蓋率 20.2%）仍未修，成本欄位不可對外；
  `weekly_2026-07-31.json` 仍是 0，需回填（不在本部門 owned_paths，已回報經理）。
- **下次接手先看**: `memory/notes.md` 的「已知缺陷」與「分析陷阱」兩節，特別是
  「上界不是結論」與「effectful 是下界」兩條。
