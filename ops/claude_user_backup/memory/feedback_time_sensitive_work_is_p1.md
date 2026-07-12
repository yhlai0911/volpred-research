---
name: feedback_time_sensitive_work_is_p1
description: 時效性/即時性的研究與發文一律 P1，與 user-assigned 同級，插隊所有 scheduled 工作
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 0b5bb4f5-76e6-4f36-9f37-bb10bc61ec0a
---

老闆 2026-07-12（Telegram msg 588）：「有些時事性、即時性的研究和發文 也是要排最優先級」。

時效性任務 = event_article（CPI / FOMC / NFP / 財報 / 台積電營收）、trending_repost、突發市場事件驅動的實驗與文章。這些一律 `priority: 1`，與 user-assigned 同級，排在所有 scheduled 研究、補池、ops chore 之前。

**Why**：時效窗口過了價值直接歸零（事件文章隔一週發等於沒發，曝光與分享率全掉）；非時效的研究晚一天幾乎沒有損失。優先序要反映「錯過的成本」，不是「任務類型的重要性」。

**How to apply**：派工挑任務時，先掃 pending queue 有沒有 event-driven / 時效任務，有就先派它，不管 work_log 的類型多樣性輪轉。手動建立時效任務時明寫 `priority: 1`（自動路徑 `event_jobs.build_pending_event_task` 與 `refill_reader_facing_pool._build_trending_task` 已固定 P1）。規則寫在 CLAUDE.md「核心 dispatch 規則」。相關：[[feedback_urgent_work_bypass_queue]]、[[feedback_dispatch_over_diversity]]、[[feedback_trending_repost_route]]。
