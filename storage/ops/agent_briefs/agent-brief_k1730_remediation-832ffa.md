# K1730 remediation — Codex 一審 FAIL 的四項阻斷缺陷修復

**Model**: opus / xhigh (per model_router)
**Task id**: assign_98a32740（P1 urgent lane，來源 = 老闆指派）
**Worktree（唯一可寫範圍）**: `.claude/worktrees/dispatch-slot-1-558d7893-k1730`
**實驗目錄**: `experiments/k1730/`

## 0. 開工前必讀

1. `AGENTS.md`「研究誠實原則」13 條 — 尤其第 9（Null result 如實報告）、第 10（不可過度宣稱）、第 11（lookahead）、第 12（fixed seed）。
2. `experiments/k1730/codex_review_v1.md` — Codex gpt-5.6-sol / high 的完整逐點 findings（檔尾 `VERDICT: FAIL`）。**逐條讀完再動手**，不要只看下面的摘要。
3. `experiments/k1730/review_verdict.json` — 四項 blocking_defects 的機讀版；`reviewed_sha256` 記錄了一審當下的檔案指紋。
4. `experiments/k1730/K1730_ARM_A_FULL_RUN_COLLECTION.md` — 目前的結論敘述（**含被 Codex 指為 overclaim 的措辭，需改**）。

## 1. 要修的四項（全部 blocking，缺一即再度 FAIL）

### (1) README.md 缺件 + 結論措辭降級
- 補 `experiments/k1730/README.md`（三件套硬規則：README + 主腳本 + results.json）。內容須含：研究問題、資料來源／期間／樣本數、模型設定、評估口徑、**誠實的結論強度**、已知局限。
- 全面掃 README 與 `K1730_ARM_A_FULL_RUN_COLLECTION.md`：**禁止**把 permutation 結果稱為 "decisive"／「決定性」／等義詞。NULL 結論可以留，但強度必須降到證據支持的水準。

### (2) Permutation 重新設計
- 現況：全樣本 shuffle macro tensor。Codex 判定這破壞了 macro tensor 的時序結構、且未保留 within-window 對齊 → 無法支撐 placebo／lookahead 的解釋。
- 改為 **block permutation 或 circular shift placebo**（保留序列相依結構），且 target 與 HAR 端輸入完全不動。
- README 要寫出**設計論證**：為什麼這個 placebo 的虛無假設正確、破壞了什麼、保留了什麼。固定 seed。

### (3) GEV multistart 收斂率 0.47–0.51 的解釋修正
- Codex 指出：對非法參數用常數 `1e10` penalty + 寬隨機起點會**機械性**壓低收斂率 → 現有「似然面多峰」的判定未被建立。
- 改成 finite/smooth penalty（或改良起點策略，例如 method-of-moments 初始化 + 合理範圍抽樣），**重跑 multistart**。
- 依重跑後的收斂率與最優解分佈，**重新判定**是否真多峰。若仍多峰 → 誠實揭露並報告 basin 分佈；若收斂率大幅上升 → 撤回原「多峰」宣稱並在 README 註明更正（AGENTS.md 第 13 條）。

### (4) SSVS 未收斂（worst R-hat 1.61 / min ESS 6.25 / Geweke |z| 49.3）
- 二選一，擇一做到底並寫清楚：
  - **(a)** 增加鏈數／迭代／reparameterize（例如 non-centered、調 slab/spike 尺度），重跑到 R-hat < 1.05 且 ESS 足夠，才可把 PIP 當推論用；或
  - **(b)** 明確把 PIP 與 posterior predictive **降級為 diagnostic-only**，README 與 collection 文件中所有據此的宣稱一併降級或刪除。
- **禁止**把未收斂的 sampler 產物包裝成穩健推論。

## 2. 完成條件（三件套 + 可驗證）

- `experiments/k1730/README.md` 存在且與 results.json 數字**逐項對齊**（不得有 README 說 A、JSON 是 B）。
- `experiments/k1730/k1730_gevreg_midas_ssvs_results.json` 更新為重跑後的真實輸出（permutation 新設計、GEV 重跑、SSVS 依 (a)/(b) 處理）。**所有數字必須來自實際執行**，禁止手改 JSON。
- 圖若因重跑而失效 → 重生；未重跑的圖不要動。
- 重生 verdict template：`experiments/k1730/review_verdict.json` 以新 commit 為 `reviewed_commit`、status 重設為待審（不要自己填 PASS）。
- 在 worktree 內 commit（**不要** merge 回 main，也**不要**寫 `storage/memory/knowledge.json`）。

## 3. 產出

- 主 artifact：`experiments/k1730/k1730_gevreg_midas_ssvs_results.json`
- 另在 `experiments/k1730/REMEDIATION_v2.md` 寫一份對照表：Codex 四項 finding → 你做了什麼 → 哪個檔案／行號 → 重跑後數字如何變。這份是二審的 entry point。

## 4. 誠實紅線

- 結果變好變壞都如實寫。NULL 仍是 NULL 就寫 NULL。
- 若某項修不動（例如 SSVS 怎麼調都不收斂）→ 走 (b) 降級路線並說明嘗試過什麼，**不要假裝收斂**。
- 不得用 `--no-verify`、不得 force push、不得虛構數字。
