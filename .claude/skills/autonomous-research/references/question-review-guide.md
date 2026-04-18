<!-- AUTO-GENERATED FROM agent-specs/. Edit canonical sources instead. -->

# Open Questions 重評指南

## 觸發時機
- 每 6 小時 cron（「會員問題研究」）
- 每個 Phase 完成後
- 累積 5+ 實驗後

## 重評流程
1. 讀取 `storage/memory/open_questions.json`
2. 對每個 `status=open` 或 `partially_answered` 的問題：
   - 搜尋 knowledge.json 是否有相關新發現
   - 檢查 research_program.md 是否有對應實驗結果
   - 如果已被回答 → 更新 status + answer + 引用實驗編號
   - 如果部分回答 → 更新 answer，保持 partially_answered
   - 如果仍然 open → 重新評估 priority（有新線索 → 提高 priority）
3. 寫回 JSON

## 注意事項
- answer 必須引用具體實驗編號（如 J3, K1, T3）
- 不要刪除問題，只改 status
- 新實驗產生的新問題應用 `m.add_question()` 記錄
- Open Questions 是大方向問題，小實驗結果放 knowledge
