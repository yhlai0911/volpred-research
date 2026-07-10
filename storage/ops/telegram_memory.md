# [已廢棄 · TOMBSTONE 2026-07-10] Telegram 專用長期記憶

> **此平行記憶檔已廢棄，記憶已統一到 auto-memory（同一個大腦）。**
>
> canonical 記憶 = `~/.claude/projects/-Users-yhlai0911-volpred-research/memory/`（MEMORY.md 索引
> + 各 memory 檔）。headless `telegram_responder` 啟動時 `claude -p` **自動載入這份大腦**，與
> 老闆在 VS Code 互動 session 用的是**同一份記憶** —— Telegram 與本機是同一個運營經理、同一個
> 大腦，共讀共寫，不再有平行記憶。
>
> **為什麼廢**：原本假設「headless session 沒有 auto-memory 自動注入」才另建此檔。2026-07-10
> 實測推翻該假設（headless `-p` 預設載入 auto-memory；只有 `--bare` 才跳過）。平行記憶造成
> Telegram 寫的本機看不到、靠主線程手動搬 = 兩個大腦。統一後消除。
>
> **要記長期指示**：responder / 主線程用內建 memory 系統寫進 auto-memory（一檔一事實 +
> MEMORY.md pointer），不要再寫這個檔，也不要用 `scripts/telegram_memory.py`（已 tombstone）。

---

## 原內容歷史存檔（已 migrate 到 auto-memory，保留供追溯）

以下為廢棄前的條目。有效內容已遷入 auto-memory：
- 迷思實驗室系列 → `project_myth_lab_series.md`（已完整覆蓋）
- 事件溫度計系列 → `project_event_thermometer_series.md`（2026-07-10 新建）
- 論文授權 msg 309 → `feedback_paper_autonomy_optimize_acceptance.md`（2026-07-10 新建）
- 記憶檔上線 / 迷思含 EP 兩條 → 過時，不遷移

```
- [2026-07-05 建立] 本記憶檔上線；老闆問「可以有一個 Telegram 專用的長期記憶嗎」→ 是。
- [2026-07-06 15:09 台灣] 迷思實驗室系列（含 EP.X）— 已被 15:45 更正取代。
- [2026-07-06 15:45 台灣] 迷思實驗室系列改純前綴「迷思實驗室｜」（全形｜）不掛集數；已上線8篇。
- [2026-07-06 16:02 台灣] 事件溫度計系列🌡️：即期事件前後分析，前綴「事件溫度計｜」；SoT=config/article_series.json。
- [2026-07-09 19:17 台灣] 論文線授權（msg 309）：依專業判斷優化 acceptance，不再逐次問投稿，真 ready 就自主推進。
```
