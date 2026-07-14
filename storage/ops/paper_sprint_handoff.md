# 論文優化 Sprint Handoff（2026-07-14 12:30 更新）

**用途**：compact / 新 session 後讀此檔無縫接續。總入口 `docs/paper_execution_master.md`；單篇規格 `paper/<name>/EXECUTION.md`。

## 已完成並 commit（勿重做）
- **vt-crowding-abm P0 全收官（ea191161e，2026-07-14）**：P0-1~P0-5 done、gate 173/173、PDF 零洩漏、VT-only 殘留清除；剩 v6 review（in-flight）+ QF compliance
- vt-insurance-cost（478d4006e 等）/ vt-trend-following（4360ecfaa）/ leverage-direction（46f1766c3）/ taiwan-vt（6562076b6）/ vt-crowding-abm P0-2+P0-3（5ff463529）/ volabs+ftd 裁定（9b1260cfa、5ff463529）
- **prg-periodic-garch v7 全套完成（8123f77e7 → af81d2e73，2026-07-14）**：重寫 + 三軌審查（6 MAJOR 全修）+ gate 28/28：headline = timing-convention flip；flip 主表（K1699 close 0/6 + K1710 mixed 6/6 / open 5/6，單一 pinned vintage）；FRL 字數達標；reproduce gate GREEN 26/26（JSON→tex binding，無 live fetch）；paper-update 已同步線上。細節見 `paper/prg-periodic-garch/EXECUTION.md` 進度日誌 + v7 決策記錄。

## In-flight agents（收割後再派下一批）
- `abm-v6-review`：vt-crowding-abm v6 跨模型獨立審查（Codex adversarial 決定性軌 + transcript 存證）→ 產 `review_history/v6_review_20260714/README.md`；findings 主線程裁定
- ~~prg-v7-review~~ ✅ 已收割：MINOR_FIXES / 0 BLOCKING / 6 MAJOR 全修（e2ffd8d90 + af81d2e73）；Codex transcript 存證
- ~~abm-p04~~ ✅ 已收割：gate 173/173 + 主線程收官 P0 全部（1c15d3c11 + ea191161e）

## 待辦隊列（優先序）
1. ~~volatility-absorption body 重寫為 FRL 方法論短文~~ **裁定更正（2026-07-14）**：K1686 R2（Codex PASS）通過事前固定 ambient-fear-shock gate → **JBF 線繼續、FRL 重框取消**（舊隊列項抄自 7/12 已撤回的首裁，stale）。現行工作 = JBF 線 body 修訂（K897 退役 + null inconclusive + H 規格整合）+ P0-2/3/4 — 主線程，見 `paper/volatility-absorption/EXECUTION.md` 2026-07-14 裁定
3. forecast-tail-divergence FRL 短文 outline（K1698 H2_REJECTED）— 主線程
4. Tier 3：garch-x-vix（K1685 GO 已備）→ vix-sufficiency（K1655 DM/HAC class）→ eav-universal-magnitude → btc-gas-negative → crypto-fear-channel（禁 ready 標記直到 Codex 語義複核）

## 環境注意
- 論文 .tex 一律主線程；考古/機械/實驗派 Opus subagent
- 非 ASCII commit 走 `git commit -F`；不可 `git add -A`
- 系列文章 release pacing 已上線（4022136c8）：無人載具 EP-Final 將於 7/15 06:02 台灣自動釋出，勿手動催發

## 接續提示詞
讀本檔後：先收 in-flight 兩個 agent 的結果（prg review findings 主線程裁定並修 tex；abm P0-4 驗 commit），再按待辦隊列順序繼續。每篇完成 = EXECUTION.md 進度日誌 + commit + paper-update。
