# K1694 round-6 repair — product/exchange-scoped official trading calendars

**Model**: opus / max (per model_router, task_type=experiment, attempt=1 — escalated because round-5 Codex verdict was a verifiable FAIL; `at_ceiling=true`, so this is the last effort rung — if round 6 also FAILs, the next step is the 3-strike path, not another identical retry.)

**Source task**: `assign_3cf55dd4` (P2, experiment)
**Worktree (your cwd, already registered)**: `.claude/worktrees/dispatch-slot-1-e98b43fc-k1694`
**Round-5 FAIL receipt**: `experiments/K1694/review_verdict.json` (reviewer: Codex gpt-5.6-sol, reviewed_commit `94b81c295b7e9be0f459dce98629bdf9bf1deb0e`, `merge_allowed: false`, `knowledge_promotion_allowed: false`)

## Read first (non-negotiable)

- `AGENTS.md` — 研究誠實原則 13 條，特別是 11（lookahead）、12（seed）、9（null result 如實報告）、10（不過度宣稱）
- `.claude/rules/experiments.md` — 實驗三件套與 finalize 流程
- `experiments/K1694/README.md` + `review_verdict.json`（完整讀，不要只讀摘要）
- `experiments/K1694/r4_repair_report.json`（前一輪修了什麼、為何仍不成立）

## What is actually broken

前一輪的修法從 **count-only cache gaps** 反推出一張 **universal** `CME_UNSCHEDULED_CLOSURES`
表，對「所有商品」一律移除 2012-10-29、2012-10-30、2018-12-05。原始交易所公告直接反駁這個推論：

- CME 2012-10-28 公告：Sandy 關閉的是 **U.S. equity-index futures**（以及部分利率複合體），
  **其他期貨照常**。
- CFTC submission 12-363：**NYMEX/COMEX 電子 Globex 仍可交易**。
- CME 2018-12-02 公告：2018 國殤日只關 **U.S. equity 與 interest-rate products**，
  其餘 Globex 市場正常。

K1694 橫跨 CME/CBOT/NYMEX/COMEX 與 ICE softs（能源、金屬、農產、畜產）。一張通用日曆
因此**不是證據**。Codex 已量化其後果：拿掉這張沒有依據的白名單後，2012-10 從 22/22 通過
變成 0/22，2018-12 的 CORN 從通過變成失敗 —— 也就是說目前的 **3,276 列樣本與所有衍生輸出
都不可採信**。

第二個 blocking defect（P2）：`test_endpoint_gate_accepts_an_untruncated_dated_cache` 把
`expected_month_endpoints()` 的輸出灌回去問同一份實作接不接受 —— 這只驗內部一致性，
**無法證偽一張錯的日曆**（tautological oracle）。

## Required deliverables（六項，逐項可驗）

1. **Source table**：每一個 ticker → 交易所 / 產品 schedule / 官方 URL。primary source only
   （交易所公告、CFTC filing、官方 holiday calendar）；二手整理不算。放在
   `experiments/K1694/calendar_sources.md`（或 .json），每列要能被第三人點開驗證。
2. **獨立 fixture 測試**：對三個爭議日期（2012-10-29、2012-10-30、2018-12-05）以及
   **CME 與 ICE 各自的代表性產品**，寫 product/date/open-status 的 primary-source fixtures。
   **絕對不可**再用 `expected_month_endpoints()` 當自己的 oracle。
3. **二選一，明確選一條並說明**：
   (a) 做 product- 與 exchange-scoped calendars，附 dated endpoint cache；或
   (b) **刪掉**那張沒有依據的白名單，並**明確下修** screen 的 completeness claim。
   選 (b) 完全可接受 —— null / 縮小宣稱是誠實結果，不是失敗。不要為了讓數字好看選 (a)。
4. **全面重跑**：`K1694.py` + lag sensitivity + figures + `finalize_experiment`。
   **禁止手改任何產出檔**。seed=42 固定，`signal.shift(1)`（或等效 lag）要在代碼裡看得見。
5. **量化改動**：明講移除/替換白名單後，樣本數、通過列數、以及主要結論各自怎麼變
   （例如 3,276 → N 列；2012-10 22/22 → ?/22；2018-12 CORN 狀態）。這是 round-5 明列的要求。
6. **Codex round-6 review**：跑完整 review 流程，把 verdict 寫回
   `experiments/K1694/review_verdict.json`（round=6）。

## Hard constraints

- **保留 provenance 與 worktree；FAIL 就不要 merge**。round-6 若仍 FAIL，如實寫 verdict，
  不要為了過關放寬標準。
- **不要自己寫 `storage/memory/knowledge.json`**（K1259 教訓）。knowledge 只在 PASS 之後
  由主線程的 programmatic writer 寫入。
- 假數字、湊樣本、事後挑日期 = 研究失敗，比交不出東西嚴重得多。
- 結論強度不得超過證據；如果證據只支持「我們無法排除 X」，就寫「無法排除」。

## Success criterion（收件時會驗這個）

`experiments/K1694/review_verdict.json` 存在且 `round == 6`，且下列其一為真：

- `verdict == "PASS"`（或 CONDITIONAL_PASS）且兩個 blocking defect
  （`product_scoped_calendar_required`、`calendar_truth_test_is_tautological`）都已解、
  所有衍生產出已重跑；或
- `verdict == "FAIL"` 但**如實**記錄哪一項無法解、為什麼、以及既有證據支持到什麼程度。

兩種都算完成這份工作。**唯一不接受的是宣稱修好了但證據不支持。**
