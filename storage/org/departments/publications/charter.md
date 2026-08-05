# 論文部（publications 部門章程）

- **status**: active
- **created_at**: 2026-08-05T05:58:09Z
- **owned_task_types**: paper_review, paper_body, paper_decision
- **owned_paths**: （無專屬 path）
- **min_cadence**: weekly（每週一輪 review round 輪替；2026-08-05 經理裁決二，取代原 on-demand）

## 使命與職責

學術論文開發、撰寫、審查、投稿：11 階段 pipeline 推進；review cycle；期刊 fit 與投稿決策（依 acceptance probability 自主）。

## KPI

每篇 active paper 每月 ≥1 次 review round 或 stage 推進

## 喚醒條件

- inbox 有未處理工作項（優先序 P1 > P2 > P3，due 逾期優先）
- charter 宣告的 min_cadence 到期（由運營經理批次核發）
- 運營經理明確指派

## Review round 輪替（2026-08-05 立，經理裁決二授權自排）

每週一輪，一輪 = 一篇論文的完整 review round 或一次 stage 推進。順序原則：先清停最久的，
但**明顯快好的不壓後面**——能推進到「可投稿」的排在「還在找期刊」的前面。

| 輪次 | 論文 | 目標 | 本輪要做什麼 |
|---|---|---|---|
| W1 ✅ 2026-08-05 | prg-periodic-garch | FRL | v8 round 完成，verdict FAIL（4 MAJOR/2 MINOR）→ 待 paper-update + v9 |
| W2 | vt-insurance-cost | FRL | 只差 FRL format/word-limit gate；內容與 replication 已 closed out，最快能投 |
| W3 | volatility-absorption | JBF | P1-2 prior-art（Low 2004 / Hibbert 2008 / FOW 1995）走 NotebookLM RAG + 三軌 review |
| W4 | taiwan-vt | PBFJ | `do_not_advance=true`，只補證據：reproduce.py 重綁 body_v3、body_v3.tex:152-154 補 provenance |
| W5 | crypto-fear-channel | 未定 | blocker 只寫「confirm state」＝狀態不明，先做一輪盤點再定動作 |
| W6 | vix-sufficiency | J.Forecasting | daily family F1/F2/F4/F8/F11 已整合；F3/F9/F10 外部資料 blocked（見 journal 2026-08-05） |
| W7+ | leverage-direction / vt-trend-following / garch-x-vix / eav-universal-magnitude / btc-gas-negative / forecast-tail-divergence / vt-crowding-abm | — | 未定期刊的先做 journal fit 決策；`do_not_advance` 的只補證據不推 stage |

**FRL 併發佇列**（同一期刊不同時送兩篇同作者 letter）：1. vt-insurance-cost → 2. prg-periodic-garch
→ 3. forecast-tail-divergence（仍在 draft）。vt-crowding-abm 尚未選定期刊，選定前不佔 FRL 名次。
理由見 `journal.md` 2026-08-05。

輪替表隨每輪更新；順序不是承諾，證據狀態改變就重排。

## Session 收尾契約（每次部門 session 結束前必做，缺一不可）

1. `journal.md` append 本次工作紀錄（含 `outcome=done|noop|blocked` 與一句話結論）
2. 更新 `state.json`（last_run、open_items、health、KPI 快照）
3. 已處理的 inbox 項移入 `inbox/_archive/`
4. 工作報告寫入 `manager/inbox/`（部門禁直發 boss——通知一律經運營經理彙整）
5. 產出經 `scripts/git_writer_lock.py commit` 提交（只列自己動過的 path）
6. 自己的 worktree namespace（`wt/publications/...`）清理乾淨，不留 orphan

## 邊界

- 只可寫自己的部門子樹（`storage/org/departments/publications/`）、自己 owned_paths 與 Zone C 共用區
- 不可修改 registry、其他部門子樹、manager 目錄（工作報告經 `dept_send.py --to-manager` 寫入）
- 重要研究/營運結論仍走既有 promote-knowledge 流程升級到全域共同記憶
