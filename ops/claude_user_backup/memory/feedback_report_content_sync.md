---
name: feedback_report_content_sync
description: feed.json 和個別 reports/mile_xxx.json 的 content 欄位必須同步——API 優先讀個別檔案
type: feedback
---

**feed.json 和 reports/{id}.json 的 content 必須同步一致。**

**Why:** 已經出錯多次。API route 優先讀 `reports/mile_xxx.json`（個別檔案），如果個別檔案的 content 是空的，即使 feed.json 有完整 content，網頁仍然顯示空白。用戶已經多次反映「看不到詳細內容」。

**How to apply:**
1. **發佈時**：`record_and_publish.py` 必須同時寫入 feed.json 和 reports/{id}.json 的 content 欄位
2. **修正 content 時**：改 feed.json 時，**必須同步改 reports/{id}.json**
3. **檢查公式**：任何修改 feed 資料後，跑：
   ```python
   for item in feed:
       report_path = f'storage/reports/{item["id"]}.json'
       # 確保 report file 的 content == feed item 的 content
   ```
4. **API 優先順序**：`/api/publications/feed/[id]` 先讀 `reports/{id}.json`，再 fallback 到 `feed.json`
5. **絕對不要只改 feed.json 就以為完成了**
