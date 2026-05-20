# Handoff — 2026-05-20 20:17 台灣時間

**寫入時機**：運營 cycle 收尾（CLAUDE.md Compact 規則）
**角色**：VolPred 平台 autonomous 運營經理（用戶 = 老闆，report-only，full autonomy 已授權，不問選擇題）

---

## 本 cycle 完成（最新在上）— commit `e1733d8c`

- **Paper 1 Table 7 errata + paper-update sync**（paper_body，`Paper1_new_experiments_Tables_4_6_7_8` → succeeded）：
  - K1187 reproducibility issues 處理：加入 Notes + Replication note 到 Table 7（tab:vt）— GLD = 2022-2026、SPY = 2014-2026、BTC = post-2019 期間揭露
  - errata_pending.md batch-4 section 新增；K1198 Step 4 DONE
  - main_v3.tex 編譯乾淨（66 頁）；paper-update sync 成功（updated_at: 2026-05-20T12:13:39Z）
  - Paper 1 三批 errata 全數落地（batch-1 K1185/K1188 + batch-2 K1186/K1206 + batch-3 K1198 + batch-4 K1187）
- **Daily data refresh**：leverage-direction 3 CSVs +22 rows（2026-05-14~20 新交易日）

## 本 cycle 完成（前期）— commit `8fdcc6ab`

- **K-id collision 無限迴圈修復（3-strike 級結構修）**：dispatcher 永遠推薦 K1308 x3。根因 `generate_research_backlog.py` find_next_k_id 無視在途 next_tasks ids + dedup keyword 對中文失效。已修產生器（傳 in-flight ids + source_line 精確 dedup）+ 清 next_tasks.json 569→560（K1308 dup×3 / 9 collision 重配 K1384-1392 / 標題重複×6）。
- **ops_dashboard 虛報 cron stale 修復**：UTC 時間戳被 mktime 當 local → 虛增 +8h。改 calendar.timegm。handoff 長期「daily cron 偶爾 stale」部分即此 bug。
- **2 篇 pending FB 補發**：mile_8d61b9b3（OVX/VIX 伊朗戰爭）+ mile_32eb397f（VIX dispersion/Mag6）發 Ivan Lai FB + 留言連結，trending_repost_log 標 success。
- **2 條 stale cron 補跑**：release_pool + paper_sync_all（exit 0）。
- dashboard 現 7/7 區段全綠。

## 待驗證 / 候補

- **無進行中背景 agent**。
- **novel-method 實驗 soft pause**：next_tasks 內 PatchTST(K1383) 帶 `diversity_rule_post_null_quartet` block（4 連 NULL K868/K1301/K1303/K1309 後暫停 novel-method 直到 quartet 文章獲 Codex+讀者訊號）。dispatcher 目前頂層候選 K1313/K1385/K1386 皆 novel-method，性質同屬暫停範圍但未標 block — 下次 session 若要派實驗需先確認 quartet 文章訊號狀態，或改派非 novel-method / daily_article。
- **refill_task_pool.py dedup bug 候補**：會產生 `write general-audience article` 通用標題 dup（本 cycle 清 4 個但根因未修）。下次碰 article refill 時修。
- 未 commit：storage/ 運營狀態檔自然 drift。

## 未回應用戶的問題

無。

## 關鍵檔案

- ops 巡檢：`uv run python scripts/ops_dashboard.py`
- dispatcher：`uv run python scripts/continue_task_dispatch.py --dry-run`
- 決策日誌：`storage/ops/autonomous_decisions.jsonl`
- 教訓：`docs/error_log.md`（2026-05-20 entry）
- FB 發文教訓：`.claude/skills/trending-repost/SKILL.md` Step 7

---

## 接續提示詞

> 讀 `storage/ops/handoff_latest.md` 了解上一段脈絡。你是 VolPred 平台自主運營經理（用戶 = 老闆，report-only，full autonomy 已授權，不問選擇題；決策直接做、做錯事後修）。
>
> 接續步驟：
> 1. 跑 `uv run python scripts/ops_dashboard.py` 取得平台 7 區段健康狀態
> 2. 有 critical/warn 先處理（daily cron stale 就 `bash ~/.volpred/bin/cron_<id>.sh` 補 + 更新 `storage/ops/cron_last_run.json`）
> 3. production OK 就從 `storage/next_tasks.json` pending 池派工（先 `jq '[.[-5:]|.[].task_type]' storage/work_log.json` 查多樣化，≥3 同 type 必換）。注意：dispatcher 頂層候選 K1313/K1385/K1386 是 novel-method 實驗，受 `diversity_rule_post_null_quartet` soft pause 影響 — 派實驗前先確認 quartet 文章訊號，否則改派非 novel-method 或 daily_article。
> 4. FB 發文嚴守 `.claude/skills/trending-repost/SKILL.md` Step 7 的 8 條
> 5. 寫文章嚴守 `anti-ai-style` 9 地雷 + 內容要厚 + Layer 4 narrative-arc dedup
> 6. 重大決策寫入 `storage/ops/autonomous_decisions.jsonl`
> 7. compact 前必更新本 handoff 檔
>
> 無未回應的用戶問題、無進行中背景 agent。直接從 dashboard 巡檢開始下一個 cycle。
