# 思維模式：永遠修流程，不修資料

**任何問題都不能用手動修正解決。** 必須追溯到底層流程，使修正可以自動化、流程化、規格化。

## 絕對禁止的手動操作

| 層次 | 錯誤做法 | 正確做法 |
|------|---------|---------|
| 資料錯誤 | 手動改 JSON/DB | 修正產生資料的程式碼，讓下次自動正確 |
| 發佈失敗 | 手動 sync 到 Supabase | 修正 publisher.py 讓它自動 sync + retry |
| 格式問題 | 手動修文章內容 | 修正 serialization 邏輯（如 `\\n` 雙重轉義）|
| 缺欄位 | 手動 PATCH DB | 修正 sync 函式讓它帶正確欄位 |
| 排版壞掉 | 手動清理 metadata | 修正 publisher.py 自動 sanitize |
| DB schema 不支援 | 用 session cron 繞過 DB 限制 | 改 DB schema（migration）+ 改程式碼適配 |
| 流程缺失 | 手動逐篇操作 | 寫入 skill/config 讓流程自動化 |
| 節奏控制 | 手動釋出文章 | DB 設定 interval + cron 自動觸發 release-pool-by-settings |

## 診斷三步驟

1. **問「為什麼會發生？」** — 找根本原因，不是症狀
2. **問「下次會不會再發生？」** — 如果會，修正流程
3. **問「能不能寫進 skill/code/config？」** — 讓修正永久化

## 記錄要求

每次根本修正後：
1. 更新 `docs/error_log.md`（問題、現象、過程、解決方法）
2. 寫入對應 skill 或 memory（讓未來 session 不重蹈覆轍）
