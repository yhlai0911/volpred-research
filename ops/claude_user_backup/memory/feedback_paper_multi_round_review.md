---
name: 學術論文必經多輪 latex-academic-reviewer 審核與修訂才能投稿
description: Paper status「READY GREEN reproduce gate」≠ 可投稿；必須再經過多輪 latex-academic-reviewer + paper-review-cycle 收斂
type: feedback
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---
# 學術論文必經多輪 review cycle 才能投稿

學術論文（P1-P10 在 `paper/` 目錄內所有）即使達到 reproduce gate ✅ READY GREEN 100%，**不可直接 ping 用戶投稿**。**必須先啟動 paper-review-cycle skill 跑多輪 latex-academic-reviewer + citation-verifier 並行審查 + 主線程修訂 + 重審，直到收斂**才考慮投稿建議。

**Why**：用戶 2026-04-27 明示。投稿前 reviewer 找出的 issue 比 reproduce gate 抓的 layer 更深（argument quality / equation derivation / symbol consistency / citation completeness / writing style / claim-evidence matching）。Reproduce gate 只保證 numerical reproducibility，不代表 paper 寫作品質達 top-tier journal 門檻。直接投稿 = high desk-reject probability + reviewer cycle 浪費。

**How to apply**：
- 看到 paper status「✅ READY GREEN — 等用戶 confirm 投稿」**不要直接 send_alert ping 用戶投稿**。改 ping「該啟動下一輪 paper-review-cycle」或主線程主動啟動
- `research_program.md` Paper Portfolio Status 顯示 4 papers READY (P4ins / P5 / P6 / P7) 時，先用 paper-stage-classifier 判定 stage（early / draft / review / ready / submitted），review stage 才跑 paper-review-cycle，submitted 才考慮投稿
- 多輪定義：每輪 = latex-academic-reviewer + citation-verifier 並行 → review_history/v(n)/ Markdown reports → 主線程修訂 body → 編譯 PDF → paper-update sync。round n 直到 reviewer report 沒新 MAJOR issue 才算收斂
- 投稿建議只有在「stage=submitted-ready + reviewer 連續 2 輪無新 MAJOR」才 ping 用戶
- 違反這條規則會被視為「ops 投稿心態凌駕學術品質心態」— 違背 Mission L7「把學術論文寫好」+ top-tier journal 目標
