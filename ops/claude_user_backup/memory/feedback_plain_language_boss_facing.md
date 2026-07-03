---
name: feedback_plain_language_boss_facing
description: 所有給老闆看的描述（alert/email/telegram/報告）用人看得懂的白話，不堆專有名詞
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 3f71195b-6e58-49ab-bff2-4ddd20a3f8c8
---

老闆 2026-07-03（Telegram msg 77）硬性糾正：**「描述的時候要用人看得懂的話，不適用（要）用一堆專有名詞堆疊而已」**。

觸發 incident：內容品質巡檢 WARN alert 的描述塞滿 jargon（`publish_rhythm:drought`、`content_completeness 2/12`、`daily_digest_uniqueness=duplicate`、`arc-dup`、`anti-rehash`、`release-pool-by-settings`、`cluster-pressure`…），老闆看不懂在講什麼。

**Why**：老闆是最終仲裁者但不是每天讀 code 的人。描述堆術語 = 老闆得自己翻譯才知道發生什麼事 = 溝通失效。給老闆的訊息目的是「讓他 3 秒懂發生什麼、嚴不嚴重、我打算怎麼辦」，不是展示系統內部詞彙。

**How to apply**（所有 boss-facing 輸出 — alert email、telegram-send、每日摘要、決策信、boss report）：
1. **結論先講白話**：「發文脫班了」不是「publish_rhythm entered drought state」。
2. **術語要就地翻譯或替換**：非講不可的內部名詞後面加一句白話（「anti-rehash（防止同一題換殼重發）」）；能替換就替換（「arc-dup」→「舊題的重複殼」、「cluster-pressure」→「同類題最近發太多」）。
3. **一句話影響 + 一句話我的行動**：老闆只需要知道嚴重度和我怎麼處理。
4. **禁止**：一行塞 3+ 個 snake_case 內部欄位名當描述主體；把 log 原文直接貼給老闆當「說明」。
5. 內部 log / knowledge.json / error_log 保留精確術語沒問題 —— 這條**只**約束 boss-facing 面。

結構修任務：alert / send-alert 的 description 模板要內建白話化層（見 next_tasks `platform_ops_plainify_alert_descriptions`）。相關：[[feedback_email_on_major_decisions]]、[[feedback_task_end_summary_format]]、[[feedback_decision_email_html_form]]。
