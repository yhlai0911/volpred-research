# 論文優化 Sprint Handoff（2026-07-14 14:50 更新）

**用途**：compact / 新 session 後讀此檔無縫接續。總入口 `docs/paper_execution_master.md`；單篇規格 `paper/<name>/EXECUTION.md`。

**⚠️ 隊列項規則（2026-07-14 K1686 stale-裁定事故後立）**：隊列項**不得複製裁定內容**（「裁定已定 = X」這種句子禁止手寫）——裁定的 canonical 只有 `paper/<id>/EXECUTION.md` 裁定段 + `storage/paper_pipeline_status.json` blocker。隊列項只寫「下一步動作 + pointer」；接手 session 開工前**必讀 pointer 指向的 canonical 當前狀態**。違反的代價已發生一次：7/14 隊列抄了 7/12 已撤回的 FRL 首裁，差點把 JBF 可投的 volabs 錯誤降級改寫。機械側防線 = `paper_adjudication_gap` alert（gating task 完成未裁決 → 自動建 task）。

## 已完成並 commit（勿重做）
- **vt-crowding-abm P0 全收官（ea191161e，2026-07-14）**：P0-1~P0-5 done、gate 173/173、PDF 零洩漏、VT-only 殘留清除；剩 v6 review（in-flight）+ QF compliance
- vt-insurance-cost（478d4006e 等）/ vt-trend-following（4360ecfaa）/ leverage-direction（46f1766c3）/ taiwan-vt（6562076b6）/ vt-crowding-abm P0-2+P0-3（5ff463529）/ volabs+ftd 裁定（9b1260cfa、5ff463529）
- **prg-periodic-garch v7 全套完成（8123f77e7 → af81d2e73，2026-07-14）**：重寫 + 三軌審查（6 MAJOR 全修）+ gate 28/28：headline = timing-convention flip；flip 主表（K1699 close 0/6 + K1710 mixed 6/6 / open 5/6，單一 pinned vintage）；FRL 字數達標；reproduce gate GREEN 26/26（JSON→tex binding，無 live fetch）；paper-update 已同步線上。細節見 `paper/prg-periodic-garch/EXECUTION.md` 進度日誌 + v7 決策記錄。
- **vt-crowding-abm v6 review 通關（e3f6275d4，2026-07-14）**：DoD 7/9；剩 QF compliance gate + 投稿前最終同步。
- **volatility-absorption P0 全收官 + P1 快速項（e947c9e25 → 8a3974b11，2026-07-14）**：K1686 R2 裁定 = absorption 通過 ambient-fear-shock gate → JBF 線繼續、FRL 重框取消（handoff 舊隊列項是 stale 首裁）；body 整合新 §null_reexam（K897 退役、null inconclusive、58% threshold artifact、H gate +1.05 CI [0.33,1.76]）；C1–C5 全修；Table 2/3 pinned 重建（paired block bootstrap；誠實新發現 calm→normal p=0.103 不顯著）；gate 30→95 checks 100% GREEN；孤兒引用清零；42pp 編譯乾淨；paper-update 已同步。knowledge `da9ac9d2`。剩 P1-2 prior-art + 三軌 review。

## In-flight agents（收割後再派下一批）
- `abm-v6-review`：vt-crowding-abm v6 跨模型獨立審查（Codex adversarial 決定性軌 + transcript 存證）→ 產 `review_history/v6_review_20260714/README.md`；findings 主線程裁定
- ~~prg-v7-review~~ ✅ 已收割：MINOR_FIXES / 0 BLOCKING / 6 MAJOR 全修（e2ffd8d90 + af81d2e73）；Codex transcript 存證
- ~~abm-p04~~ ✅ 已收割：gate 173/173 + 主線程收官 P0 全部（1c15d3c11 + ea191161e）

## 待辦隊列（優先序）
1. volatility-absorption **review cycle**（P0 已全收官 2026-07-14，見下）：P1-2 prior-art 段（Low 2004 / Hibbert 2008 / FOW 1995，需文獻查證）→ 三軌 review（latex-academic-reviewer + citation-verifier + Codex adversarial，transcript 存證）→ findings 主線程裁定
3. forecast-tail-divergence FRL 短文 outline（K1698 H2_REJECTED）— 主線程
4. Tier 3：garch-x-vix（K1685 GO 已備）→ vix-sufficiency（K1655 DM/HAC class）→ eav-universal-magnitude → btc-gas-negative → crypto-fear-channel（禁 ready 標記直到 Codex 語義複核）

## 環境注意
- 論文 .tex 一律主線程；考古/機械/實驗派 Opus subagent
- 非 ASCII commit 走 `git commit -F`；不可 `git add -A`
- 系列文章 release pacing 已上線（4022136c8）：無人載具 EP-Final 將於 7/15 06:02 台灣自動釋出，勿手動催發

## 接續提示詞
讀本檔後：先收 in-flight 兩個 agent 的結果（prg review findings 主線程裁定並修 tex；abm P0-4 驗 commit），再按待辦隊列順序繼續。每篇完成 = EXECUTION.md 進度日誌 + commit + paper-update。
