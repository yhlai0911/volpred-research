# K528 round-7 — 結構性不變量 gate 硬化（gate hardening）

**Model**: opus / xhigh (per model_router)
**Task id**: k528_round7_gate_hardening (pool, P2, experiment)
**Worktree (你唯一可寫的 cwd)**: `.claude/worktrees/k528-round7-204d556b`（branch `k528-nfp-official-dates`, HEAD 5b1f154c1）
**背景**: round-6 收件審查（`k528_round6_collection_verdict.json`）判 B1-B4 全 PASS，但點出 3 個 non-blocking 缺陷。本 round 專責把 N1（阻擋 merge 的真正風險）修到有迴歸測試護體；N2/N3 順手補齊。**這是 primary-path Codex certify（k528_primary_codex_certify_merge）的前置** —— 先硬化再送 Codex，免得同一輪被打回。

## 必修缺陷

### N1（最重要）— 「結構性不變量」gate 名不符實
round-6 裁決自稱有「結構性不變量」gate，實測它只是 **5 詞 blocklist + 兩個無條件豁免**：
- 6 個注入測試有 **4 個同義改寫溜過**，例如：
  - 「237 場 NFP 是週五發布的」
  - 「published on a Friday」
- **同行只要出現 `243`（即使語意無關）→ 整行豁免**（line-level exemption 可被無關數字挾持）。
- **denial marker 可被挾持**（出現否定詞就整行放行）。
今天樹是乾淨的所以 B1 判 PASS，但這個 gate 擋不住「改寫後的迴歸」——正是它該擋的東西。

**要做的**：
1. 先在 worktree 內定位這個 gate 的實作檔（grep round-6 裁決/verdict json 內引用的 gate 腳本路徑；很可能在 `scripts/` 或 K528 experiment 目錄下的檢查器）。**開工第一步是把當前 gate 的邏輯讀懂並在 README/註解寫下它「宣稱擋什麼 vs 實際擋什麼」的落差**。
2. 把 gate 從「5 詞字面 blocklist + 無條件行豁免」改為真正的結構性檢查：偵測「把 proxy 期（≈237/243 場 NFP 週五發布）當成官方全樣本陳述」這類語意迴歸，而非單一字面詞。**豁免必須有條件**（例如：只有在明確的 errata/對照語境、且帶正確 official-vs-proxy 對照時才豁免），不可因同行出現某數字或否定詞就整行放行。
3. **迴歸測試護體**：把上述 6 個注入（含 4 個溜過的同義改寫、行內無關 243 挾持、denial-marker 挾持）全部寫成失敗案例測試，硬化後全數被擋；同時保留至少 2 個 legitimate 語境（正確 errata / 正確對照）確認不誤傷。測試放進既有測試套件，可重跑。

### N2 — README.md:268 缺對照
`README.md:268`「237 筆在週五」是內部章節、gate 掃不到，且無 `243` official 對照。補上 official（243）vs proxy（237）的明確對照與一句 provenance，讓內部章節也自洽。

### N3 — 線上文章 errata 不完整
線上文章 `mile_35eef830` 的 errata 只記 2026-07-18 事件日更正，**未說明 proxy 期數字已被 official 取代**。在 worktree 內把要補的 errata 文字草擬成一段（收尾 fire 再實際 publish；你只需在 worktree 產出 `errata_mile_35eef830.md` 草稿 + 說明）。

## 硬要求
- **不得放寬正確性換取 gate 通過**：目標是 gate 更嚴謹而非更寬鬆；legitimate 語境不可誤傷（附反例測試證明）。
- 所有改動 commit 進 worktree（ASCII message 含 task id `k528_round7_gate_hardening`）。**不要自己 merge**、不要碰 canonical main。
- 若定位後發現 gate 實作與描述不符或已被他班改過，如實在 README 記錄現況再決定最小硬化範圍，不要臆測重寫無關檔案。

## 必產出 artifact（output contract）
- `experiments/K528/round7_gate_hardening_summary.json`：byte-traceable 收尾摘要，至少含 —— gate 實作檔路徑、硬化前後對每個注入案例的擋/放結果（6 injections + ≥2 legitimate）、新增測試檔路徑與通過數、N2/N3 處理狀態。這是本 job 的成功後置條件，缺此檔視為未完成。

## Success criteria
- N1 gate 硬化完成 + 6 個注入迴歸測試全綠 + ≥2 legitimate 反例不誤傷；N2 README 對照補齊；N3 errata 草稿產出；`round7_gate_hardening_summary.json` 產出。
- 收尾（後續 fire 的 PHASE A 依 followup 處理）：primary-path Codex review → PASS 則 merge_worktree.sh 整合 → certify K528；FAIL 則建 round-8。
