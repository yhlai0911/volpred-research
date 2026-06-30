---
name: feedback_agent_output_extraction
description: 從 agent output 擷取文章內容時必須徹底清理，不可混入 agent metadata
type: feedback
---

從 agent output 檔案擷取文章時，agent output 是 JSONL 格式，文章內容後面跟著 agent hook metadata（parentUuid、sessionId、toolUseID 等）。

**Why:** 多篇文章被混入 agent 系統 JSON metadata，造成網頁顯示程式碼。手動修了 3 次仍有殘留——因為只修資料沒修流程。

**How to apply:**
1. **不要直接從 agent output 檔案用 regex 擷取**——JSONL 格式有多行 JSON，regex 無法可靠截斷
2. **正確做法**：Agent 完成後，把文章內容直接在 Python string 中寫好，傳給 `publish_milestone(description=content)`。不要從 agent output 檔案讀取再傳
3. **如果必須從 agent output 讀取**：用 JSON parser 解析 JSONL，找到 result 欄位，只取 result.text 內容
4. **永遠驗證**：發佈前檢查 description 最後 200 字元不含 `uuid`、`sessionId`、`parentUuid`、`toolUseID`
5. **publisher.py 已加入 sanitize**（`\\n` → `\n`），但不會自動清理 agent metadata——那是上游問題
