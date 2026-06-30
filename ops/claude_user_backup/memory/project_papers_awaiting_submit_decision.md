---
name: project_papers_awaiting_submit_decision
description: 兩篇論文 submission-ready 卡在「投稿與否」決策；M3 真瓶頸是 submit gate 不是研究；paper_stale alert 已兜底
metadata: 
  node_type: memory
  type: project
  originSessionId: 9b03f82f-4b5a-4fd1-8247-88240cdbc856
---

2026-06-21 查證（boss email-11851/11854 點名 M2+M3 idle 後）：M3「看似停滯」的真因**不是研究停**，而是做到 submission-ready 的論文卡在「投稿與否」這個 user-policy 決策點，被擱著沒 surface。

**狀態快照（2026-06-21）**：
- `garch-x-vix` → 已 submitted（under review）✓ 無需動作
- `leverage-direction` → `READY_FOR_UPLOAD`（自 2026-06-08，JBF；reproduce 171/171 GREEN 重驗於 6-21；package 完整）→ 卡投稿 ~13 天
- `prg-periodic-garch` → `Submission-ready (all clear)`（自 2026-04-19，FRL；reproduce 15/15 GREEN）→ 卡投稿 **~63 天**
- 其餘 9 篇：active major_revision（btc-gas-negative / crypto-fear-channel / eav-universal-magnitude / taiwan-vt / vix-sufficiency / volatility-absorption / vt-crowding-abm / vt-insurance-cost / vt-trend-following）— 有真內部下一步

**How to apply**：
- 投稿與否依 CLAUDE.md 是少數需用戶判斷的事 → 已 email surface（notification 22793d79）。**boss 未回前，每隔幾 tick 在 boss report 重提這兩篇 ready-but-unsubmitted**，不可再讓它沉默 2 個月。
- boss 一旦說「投」→ leverage 走 JBF Editorial Manager、prg 走 FRL portal；submission package 都已備（cover letter / highlights / graphical abstract / supplementary）。實際 upload 需 boss 帳號（outward-facing，不自主執行）。
- M3 結構兜底已建：`paper_stale` alert（`src/volpred/ops/alerts.py::_parse_paper_stale_state`，commit 98a0052a）— paper/ 整條線 >7d 無 .tex/.md 變動自動 warn、>14d critical。看到此 alert **立即推進最成熟論文的下一步**，不 defer。
- revision-stage 9 篇：後續 tick 主線程逐篇推進（禁 background agent 寫 .tex），paper_stale 防止整條線靜默。

關聯 [[feedback_dont_deflect_act_on_repeated_complaints]] [[project_paper_portfolio_decisions_2026_04_27]] [[feedback_no_user_policy_block]]。
