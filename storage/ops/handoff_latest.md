# Handoff — 2026-05-20 18:10 CST

**寫入時機**：用戶要求建立（compact 前 handoff 規則 commit e7efcf0e 後首份）
**角色**：autonomous 平台運營經理（用戶 = 老闆，report-only，full autonomy 已授權）

---

## 當前任務狀態

本 session 主軸是平台運營 + 用戶交辦的多項治理/內容/CLI 任務。最近完成：

- **CLI 治理**：放棄 gemini-cli + antigravity-cli；headless Gemini 改 `scripts/gemini_ask.py`（直打 API，預設 gemini-3.1-pro-preview）。codex 0.130→0.132。
- **2 篇原創 Substack 風格專欄**已發佈 + FB 同步：
  - `mile_74a28bcf`「我花幾百小時讀總經新聞…波動率體制」（top-down regime）
  - `mile_94c1a524`「台灣理財教育缺的那一課」（商品知識 vs 決策能力）
- **anti-ai-style skill** 加地雷 #9（破折號 ≤1/1000 字）
- **trending-repost skill** Step 7 加 FB 發文 8 條實戰教訓
- **CLAUDE.md** 加 compact handoff 強制規則
- **ops 基建**：ops_dashboard.py / audit_publish_sync.py / audit_fb_pipeline.py / boss_report.py（4h email cron）/ live_verify gate

## 未完成 / 待驗證

- **未 commit 變更**：27 changed paths（多為 storage/ 運營狀態檔的自然 drift — feed.json/cron logs/notification_log 等，非 session 工作產出，下次自然納入或忽略）
- **背景 agent**：無進行中（claude-code-guide 已完成）
- **FB pipeline**：success 全列 + 4 篇 wont_fix；無 pending
- **daily cron 不穩**：memory_health / refresh_paper_snapshots / market_calendar 反覆 stale（piggy-back dispatch 對 daily job 不可靠）— standing 問題，候補結構修（worker daemon + queue 取代 shell piggy-back）

## 未回應用戶的問題

無。最近一題（compact 門檻為何失效）已答：`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=62` 設定正確，「似乎失效」最可能因 session 啟動早於設定生效 → 建議用戶 `/exit` 重開 session 或打 `/context` 看實際 %。

## 關鍵檔案 / 定位

- ops 巡檢入口：`uv run python scripts/ops_dashboard.py`（7 區段健康）
- 自主決策日誌：`storage/ops/autonomous_decisions.jsonl`
- FB 發文教訓：`.claude/skills/trending-repost/SKILL.md` Step 7 ⚠️ 框
- boss 報告：`scripts/boss_report.py`（4h cron）+ `docs/boss_blockers.md` + `docs/boss_direction_recommendations.md`
- 團隊結構活文件：`docs/ops_team_structure.md`

## 標準運營節奏（cycle）

1. `uv run python scripts/ops_dashboard.py` 讀狀態
2. critical/warn 區段先處理（cron stale → 手動 fire ~/.volpred/bin/cron_*.sh）
3. 派 agent 補研究/文章（多樣化檢查 work_log 最近 5 type）
4. 每 4h boss_report email 自動寄

---

## 接續提示詞

> 讀 `storage/ops/handoff_latest.md` 了解上一段脈絡。你是 VolPred 平台自主運營經理（用戶 = 老闆，report-only，已授權 full autonomy，不問選擇題）。
>
> 接續步驟：
> 1. 跑 `uv run python scripts/ops_dashboard.py` 取得平台 7 區段健康狀態
> 2. 有 critical/warn 先處理（daily cron stale 就 `bash ~/.volpred/bin/cron_<id>.sh` 補 + 更新 cron_last_run.json）
> 3. production OK 就從 next_tasks pending 池派工（先查 work_log 最近 5 task_type 多樣化）
> 4. 任何 FB 發文嚴格遵守 `.claude/skills/trending-repost/SKILL.md` Step 7 的 8 條教訓（發文前 get_page_text 查牆、留言 URL 進留言框、single-shot 禁 retry-loop）
> 5. 決策寫入 `storage/ops/autonomous_decisions.jsonl`，每 4h boss_report 自動彙報
>
> 沒有未回應的用戶問題；無進行中的背景 agent。直接從 dashboard 巡檢開始下一個 cycle。
