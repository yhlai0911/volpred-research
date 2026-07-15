---
name: project-reader-preference-feedback-loop
description: Owner 2026-07-15 指令：讀者偏好自動分析是常態運營輸入（選題/圖文表使用）
metadata: 
  node_type: memory
  type: project
  originSessionId: 088b57da-f99e-4210-b03d-8f127c98bc2c
---

Owner 2026-07-15 directive：平台要自動化從多角度（議題、論述、文字、圖片、表格）分析
讀者偏好，歸納成運營參考（選題、圖文表使用）。Phase 1 = `scripts/analyze_reader_preferences.py`
（週一 06:45 排程）→ `storage/analytics/reader_preferences.json` + report.md →
`build_publication_candidates.py` 把合格偏好訊號當選題加分項。

**Why**：讀者行為數據是 M1（文章）×M5（流量）的直接回饋；不用等老闆當 QA。

**How to apply**：選題與寫作決策（feed-publisher / publication-candidates / trending）應查
reader_preferences.json 的合格結論；**樣本不足的 bucket 不得當依據**（min 10 篇/30 impressions，
median 口徑，傾向訊號非因果）。流量成長後逐步收緊門檻、擴充維度（滾動窗口、A/B 標題）。
關聯 [[reference-work-dashboard]]、feedback_website_article_quality_4dim。
