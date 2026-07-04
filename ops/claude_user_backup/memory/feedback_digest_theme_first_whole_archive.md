---
name: feedback_digest_theme_first_whole_archive
description: 精選導讀必須「先由時事訂主題→從整庫找佐證回答主題」，不是本週研究 recap；反覆糾正後升級成 rule + 機械 gate
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f8812992-1d97-4a32-b431-990f67a8d709
---

boss 反覆要求（2026-07-01 三次 + 2026-07-05 再犯後硬性糾正）：**精選導讀 (daily_digest)
是主題策展，不是本週研究 recap。**

**正確兩段流程（順序不可顛倒）**：
1. **先由當下時事/重要宣告/熱門現象/熱門標的/具體投資議題訂主題**（不是從近期文章反推主題，
   也不是挑純研究/方法論主題）。
2. **再從整個 archive（全部時間、跨全庫）撈 5-8 篇佐證文章來回答主題訂出的問題**。所有引用文章
   都是為了回答主題，不是並列摘要。嚴禁只湊近一兩週剛發的文。

**Why**：這條 boss 早講過，但一直只寫在 `scripts/enqueue_daily_digest.py` 的 prompt 字串裡 ——
不在治理層（CLAUDE.md/rules/skills）、沒有 enforcement gate，所以反覆被忘/違反。boss 2026-07-05
點名「這麼重要的要求沒寫入指引文件嗎」。這是典型「藏在腳本 prompt 的要求 → 反覆復發」的 anti-pattern。

**How to apply**：
- 治理規則已寫入 `.claude/rules/publishing.md`「精選導讀策展硬規則」段（觸 feed/publisher/digest 路徑 auto-load）。
- 機械 gate 已建：`publisher._audit_digest_archive_span`（publish 路徑內，單一 enforcement owner）——
  量 `details.digest_articles` 發佈日期跨度：span<14 天硬擋（本週 recap）、<45 天或深庫來源<2 篇 warn；
  fail-open；校準過 5 期真實導讀不誤擋。test: `tests/test_digest_archive_span_gate.py`。
- gate 只能量「跨度」；「主題是否時事驅動」無法機械判定 → 寫導讀時自我檢查此規則，別再從近期文章反推主題。
- 教訓推廣：重要且反覆的要求不能只留在某個腳本的 prompt 字串，要進治理層 + 儘量加機械 gate
  （[[feedback_content_quality_patrol_gap]] 同類：只有 boss 會發現的問題就是缺巡檢/gate）。
