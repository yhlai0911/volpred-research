# Telegram 專用長期記憶

老闆（Ivan）透過 Telegram 這個即時頻道交代、想**長期記住**的偏好 / 指示 / 事實。
每次 `telegram_responder` 啟動會先讀本檔（headless session 沒有 interactive memory
自動注入，所以這裡是它唯一的跨 session 記憶通道）。

寫入方式：`uv run python scripts/telegram_memory.py add "內容"`（自動帶台灣時間戳）。
讀取方式：`uv run python scripts/telegram_memory.py list` 或直接 `cat` 本檔。

與其他記憶的分工：
- 本檔 = **Telegram 頻道專屬**的老闆偏好 / 指示，responder 每次自動載入。
- `~/.claude/.../memory/*.md` = Claude interactive session 的一般跨 session 記憶。
- `storage/memory/*.json` = 研究知識庫（knowledge / experiment experiences）。

---

## 條目
<!-- 每條一行：- [YYYY-MM-DD HH:MM 台灣] 內容 -->
- [2026-07-05 建立] 本記憶檔上線；老闆問「可以有一個 Telegram 專用的長期記憶嗎」→ 是。之後在 Telegram 說「記住：…」我就寫進這裡。
- [2026-07-06 15:09 台灣] 文章系列「迷思實驗室」🧪：拿投資人常聽的說法/網路傳言，用真數據+統計檢定驗一次、可複現。標題格式一律 '迷思實驗室 EP.X｜<標題>'（全形｜，掛集數）。首發3集：EP.1 開盤第一小時(mile_467226e7)、EP.2 融資餘額創高(mile_0f7d1501)、EP.3 黃金避風港(mile_08820c3d)。之後每篇續編 EP 號。
- [2026-07-06 15:45 台灣] 更正(2026-07-06)：迷思實驗室系列標題**不掛集數 EP.X**，改純前綴 '迷思實驗室｜<標題>'（全形｜）。同一迷思多篇留1篇published、其餘unpublished(不可用draft會重發)。已上線8篇。取代先前含EP.X的那條。
- [2026-07-06 16:02 台灣] 新系列「事件溫度計」🌡️（boss 2026-07-06 定名）：即期事件(FOMC/CPI/非農/財報/重大宣告)前後分析，標題前綴 '事件溫度計｜'。權威 marker=details.event_series_slot；going-forward event_article 一律掛。與迷思實驗室並列。系列 SoT=config/article_series.json。
