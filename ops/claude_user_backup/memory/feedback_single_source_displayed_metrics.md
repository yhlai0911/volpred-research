---
name: feedback_single_source_displayed_metrics
description: 前端讀者頁顯示的瀏覽數（及同類指標）只能有唯一版本，一律走 canonical helper
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d8156bae-925d-45ef-81b3-f22b5decf244
---

老闆硬規則（2026-07-18 Telegram msg 978）：**前端頁面顯示的瀏覽數只能有唯一的版本。**
同一個 reader-facing 指標，不論出現在頁面哪個區塊、走 SSR 還是 API route，都必須經過同一個
canonical 計算函式（瀏覽數 = `frontend-v2-fix/src/lib/article-views.ts` 的
`getArticleDisplayedViews()`），禁止任何地方自己對底層表做 raw count。

**Why:** 文章頁曾同頁出現「22 次瀏覽」（頂部，走 canonical helper = seed + 真實增量）與
「已追蹤瀏覽 3 次」（互動區，`/api/analytics/reaction` 直接 raw count），兩數打架。老闆看到
就當成資料不可信 — reader-facing 數字自相矛盾比數字不精準更傷。

**How to apply:**
- 新增任何顯示瀏覽/互動/追蹤數的 UI 或 API 時，先找 canonical helper；沒有就建一個，不要就地查表。
- 改動這類指標後做 class sweep：grep 底層表名，確認沒有第二條計算路徑。
- 後台 admin 統計看 raw 數是合理的（口徑不同），但**任何 reader-facing surface 一律走 canonical**。
- 同一原則適用於其他展示型指標，不只瀏覽數。

相關：[[feedback_declare_complete_requires_class_sweep]]、[[feedback_v3_presentation_layer_only]]、
[[feedback_content_quality_patrol_gap]]
