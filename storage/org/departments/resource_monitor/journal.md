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

## 2026-08-05T09:10:00Z — v3：對外口徑清單與影響面盤點

- **outcome**: done
- **工作項**: `item_20260805T084436183518Z_v2-1-f2-v1-60-1m-4-07m-15-v1-fo`（P2，已歸檔）
- **結論**:
  (1) **184.4M -> 180.3M 完全沒有對外** —— 全量掃 storage/、docs/、.claude/、
      storage/notifications/ 後 11 處命中全在 `storage/org/` 內部。內部修即可。
  (2) **280 -> 131 有對外** —— 每日 08:00 token email 帶三個 session 維度欄位
      （`unique_sessions` KPI、`by_session` top-3、說明敘事）；內部側另有
      `storage/reports/token_usage/` 98 份中 87 份帶非零 session 計數。
  (3) **自我更正（方向更嚴重）**：v2 報的 R2 集中度 34.2% 是 session_id 層級下界，
      fork root 收斂後真值 **59.0%**（106,410,266 / 180,312,894）——一個 Codex 桌面對話
      吃掉平台 7 日近六成。R3 壽命 103.76h 同為下界。per-session 平均 0.50M -> 1.04M。
  (4) **盤點外的重大發現**：**連續 6 封已寄出的日報寫「今日 0 billable」**
      （07-31～08-05，`sent=True`），是 F1 日界缺陷的對外顯現；且老闆已在回應該線
      （08-05T01:45 P1 回信、02:28 平台承諾今日交付）。已附更正方式建議請經理裁決。
  (5) **F3 已可回答，不必等 platform_eng**：covered 20.2% / uncovered 79.8%，
      **Codex 側覆蓋率 0.0%**；成本下界 1242.43 美元，上界無法給定，
      外推參考值約 6141 美元（非量測、不可對外）。
- **產出**: `reports/2026-08-05_external_figure_inventory.md`；
  `reports/2026-08-05_token_breakdown_v1.md` 加 SUPERSEDED 標頭；`memory/notes.md` 三節新增
- **送出**: 經理回報（P1，reply-to 本工作項）＋ governance 更正 request（P2，34.2% -> 59.0%）
- **未做**: R3 壽命的 root 層級重算（只標下界，不給假數字）；
  `weekly_2026-07-31.json` 仍是 0（不在 owned_paths，已第二次上報）
- **下次接手先看**: `memory/notes.md` 新增的「對外口徑地圖」——判「這數字對外了嗎」
  一律先掃 `storage/notifications/` 的 `sent=True`，不要重查一遍全 repo。

## 2026-08-05T09:16:00Z — D6 三項 ＋ 自我更正（同 session 續辦）

- **outcome**: done
- **工作項**: `item_20260805T090331099550Z_d6-...`（P2，經理裁決 D6）已歸檔；
  `item_20260805T091405166238Z_...`（governance 回覆，已獨立複算驗證 59.0%）已歸檔
- **(a) weekly_2026-07-31.json —— 撤回前兩輪的說法，是我判讀錯誤**：該檔的 `week_range`
  是 2026-07-31 → 2026-08-07（**未來的一週**），07-31 08:01 產出時該週才開始 1 分鐘。
  commit `dab112d3a` 的 `_report_covers_its_period()` 正為此設計，會在 08-07 後自動重產。
  實測：`build_token_usage_maintenance()` → `action=skip`、`weekly_due=false`、
  最近完整週＝`weekly_2026-07-24.json`（238,499,898）。**不需回填、不需送 platform_eng。**
  教訓：報表是 0 時先讀 `week_range` 判斷期間結束了沒，再跑 plan 函式看系統怎麼看它。
- **(b) 34.2% 是下界，真值 59.0%**（fork root 收斂）—— 已直送 governance，對方回讀
  `codex_duplicate_audit` 獨立複算確認，並據此解除了自己的 blocked-on-R2。
- **(c) idle_burn caveat 從 md 正文升級為機器可讀**：`kpi_field_warnings` 新增三條
  （`idle_burn_session_NOT_A_PASS`、`agent_concentration_IS_A_LOWER_BOUND`、
  `effectfulness_bounds`），並改 `tools/token_breakdown.py` 讓之後每次產出都自帶。
- **產出**: `tools/token_breakdown.py`（warnings）、`memory/token_breakdown_2026-08-04_7d.json`
  （回填 warnings）、`memory/notes.md`（撤回週報缺陷條目＋教訓）、
  `reports/2026-08-05_external_figure_inventory.md` §5（撤回第 6 項）、`state.json`
- **下次接手先看**: open_items 只剩 4 項真的沒做的 ＋ 1 項等 08-07 自動重產後回讀。
