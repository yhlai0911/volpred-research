---
name: project_codex_audit_20260710_disposition
description: 2026-07-10 Codex 稽核（SHEPHERD 式 runtime 量尺）的裁決：做哪三項、不做哪三項、為什麼
metadata: 
  node_type: memory
  type: project
  originSessionId: 89dc521f-9708-432d-bd38-b88abab2aab8
---

2026-07-10 外部 Codex 對 volpred 做架構稽核（HEAD 7bf1da2f0f），給 2.5/5，主張 P0 = 拆 topology 四欄 schema + TaskContract 大一統 + 策略 gate；P1 = Effect Gateway + phase_z 歸屬；P2 = advisor/replay。7 個查證 agent 逐條核實：**事實層幾乎全對**（197/200 actor=unknown、2286 筆/269 欄位/23 status/236 dispatch_lane 等數字精確吻合；策略五條旁路屬實且比它說的更寬）。

**但它用「SHEPHERD 式 agent runtime 成熟度」當量尺，不是本專案的目標函數（盈利 + 5 mission）。** 依 `docs/error_log.md` 實際事故史重排後的裁決：

**已做（commit 8edae506e + e2cf6bb87，2026-07-10）**
1. phase_z auto-commit 測試閘門（它排 P1）— error_log:31 紅燈 5 天沒發現，慣犯
2. actor 歸因儀器 VOLPRED_ACTOR（它排 P1）— error_log:80 當天就擋住 pregate enforce 決策
3. 策略 activation gate 收在 supabase_sync 兩函式 + list_new_strategy（它排 P0）— 降級理由見下

**不做（含理由，別再被同一份報告說服）**
- **TaskContract 大一統**：診斷對（next_tasks 是 queue+archive 混合體，90.8% 是 succeeded），但遷移 2288 筆活資料風險高、對 monetization 零貢獻。務實版 = 寫入端 status controlled vocabulary（repo 已有 `blocked_reasons.py` 先例）+ succeeded 歸檔。
- **topology 拆四欄 + stages[]**：該 enum 落地不到 3 分鐘就被稽核（commit ee0fa93a0 13:30:46 → 稽核 13:33），0 個 task 帶欄位，唯一 consumer 是 LLM orchestrator 的 advisory 標註且被明文允許 override。抽象錯置目前只污染命名。低成本正確版 = 改名 `execution_surface` + 映射搬 `config/models.json`。
- **全套 Effect Gateway / SHEPHERD replay**：研究層 replay 已被研究誠實原則覆蓋（三件套+固定 seed+論文 reproduce package）；ops 層 `src/volpred/ops/rollback.py` 是死基礎設施（supervisor 零引用，快照停在 2026-04-18），該除役而非再疊一層。**且 fail-closed 的 Effect Gateway 會違反老闆 standing rule「沒發文比重複發文嚴重」**（dedup 一律 fail-open）。

**策略 gate 降到 P1 的理由**：六類風險中它是唯一**從未實際發生**的一類。五項 gate 誕生於 2026-03-29，比史上最後一次上架（2026-03-28）晚一天 → 現存 11 檔全是 grandfathered（已 backfill receipt，標 `"grandfathered"` 非 `true`）。此後 3.5 個月零上架，6/21 三檔高 Sharpe 候選全被誠實 audit 拒絕 —— 該擋的每次都擋住，只是靠判斷不是機械。相對地 git 併發、dispatch race、publish idempotency 都是多次 3-STRIKE 的實發事故。

相關：[[feedback_declare_complete_requires_class_sweep]]、[[project_strategy_lifecycle_standing_directive]]、[[feedback_fix_silent_fallback_immediately]]
