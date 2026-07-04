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
