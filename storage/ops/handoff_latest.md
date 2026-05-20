# Handoff — 2026-05-20 18:18 台灣時間

**寫入時機**：用戶主動要求（即將 compact / 可能重啟 session）
**角色**：VolPred 平台 autonomous 運營經理（用戶 = 老闆，report-only，full autonomy 已授權，不問選擇題）

---

## 重啟後一切生效 — 已驗證保證

- **定時任務**：全走 OS 層，與 Claude Code session 無關。`com.volpred.check-alerts` LaunchAgent 每小時 fire → `run_due_jobs.py` piggy-back dispatch 全部 18 條 system_crontab job。另有 11 條 host crontab + 10 個 LaunchAgent。**session 關了照跑，不會漏。**
- **compact 門檻**：`.claude/settings.local.json` 的 `env.CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=62` 是有效設定（claude-code-guide 已查證為真實 env var）。**新 session 啟動時讀取 → 62% 立刻生效。**舊 session 沒生效是因為啟動早於設定 — 重開即修正。
- **session_crons**（CronCreate 型 prompt workflow）：離線時記入 `storage/ops/pending_sessions.json`，新 session 啟動 replay。

## 本 session 最近完成（最新在上）

- **排程孤兒修復**（commit `17679646`）：boss_report_4h / ops_dashboard / audit_publish_sync / audit_fb_pipeline 4 條因 `host_crontab_managed:false` 被 piggy-back 排除、從沒跑過。已改 true，驗證 fired exit 0。**boss_report 4h email 現在才真正自動化。**也 GC 6 個過期 event_jobs（15→9）。
- **email 時間台灣化**（commit `cdb3e790`）：boss_report + work_summary_6h 所有顯示時間改 UTC+8。
- **compact handoff 規則**（commit `e7efcf0e`）：CLAUDE.md 加「compact 前必寫 handoff + 接續提示詞」。
- **FB 發文教訓**（commit `2b2b9ebb`）：trending-repost SKILL Step 7 加 8 條實戰教訓。
- **2 篇原創專欄已發 feed + FB**：`mile_74a28bcf`（波動率體制）+ `mile_94c1a524`（理財教育）。
- **CLI 治理**：gemini-cli/antigravity-cli 棄用，headless Gemini 改 `scripts/gemini_ask.py`（Gemini 3.1 Pro）。

## 未完成 / 待驗證

- **無進行中背景 agent**。
- **FB pipeline**：全 success + 4 wont_fix，無 pending。
- **daily cron 偶爾 stale**（memory_health / refresh_paper_snapshots / market_calendar）— piggy-back 對 daily job 不穩，standing 問題，候補結構修（worker daemon 取代 shell piggy-back）。
- 未 commit：storage/ 運營狀態檔自然 drift（feed.json / cron logs / notification_log），非 session 產出。

## 未回應用戶的問題

無。

## 關鍵檔案

- ops 巡檢：`uv run python scripts/ops_dashboard.py`（7 區段）
- 決策日誌：`storage/ops/autonomous_decisions.jsonl`
- boss 報告：`scripts/boss_report.py`（4h cron，現已生效）/ `docs/boss_blockers.md` / `docs/boss_direction_recommendations.md`
- 團隊結構：`docs/ops_team_structure.md`
- FB 發文教訓：`.claude/skills/trending-repost/SKILL.md` Step 7
- 排程唯一來源：`config/runtime_schedules.json`

---

## 接續提示詞

> 讀 `storage/ops/handoff_latest.md` 了解上一段脈絡。你是 VolPred 平台自主運營經理（用戶 = 老闆，report-only，full autonomy 已授權，不問選擇題；決策直接做、做錯事後修）。
>
> 接續步驟：
> 1. 跑 `uv run python scripts/ops_dashboard.py` 取得平台 7 區段健康狀態
> 2. 有 critical/warn 先處理（daily cron stale 就 `bash ~/.volpred/bin/cron_<id>.sh` 補 + 更新 `storage/ops/cron_last_run.json`）
> 3. production OK 就從 `storage/next_tasks.json` pending 池派工（先 `jq '[.[-5:]|.[].task_type]' storage/work_log.json` 查多樣化，≥3 同 type 必換）
> 4. FB 發文嚴守 `.claude/skills/trending-repost/SKILL.md` Step 7 的 8 條（發文前 get_page_text 查牆 / 留言 URL 進留言框 / single-shot 禁 retry-loop / 每步 screenshot）
> 5. 寫文章嚴守 `anti-ai-style` 9 地雷（含 #9 破折號 ≤1/1000 字、標題不用「不是X而是Y」）+ 內容要厚（具體案例走教學）+ Layer 4 narrative-arc dedup
> 6. 重大決策寫入 `storage/ops/autonomous_decisions.jsonl`（含 intent/reasoning/outcome/next）
> 7. compact 前必更新本 handoff 檔（CLAUDE.md Compact Instructions 規則）
>
> 無未回應的用戶問題、無進行中背景 agent。直接從 dashboard 巡檢開始下一個 cycle。boss_report 每 4h 自動寄（已驗證生效）。
