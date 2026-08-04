# K1739 remediation — 修正 round-4 review 的 6 項 blocking defects 後重新凍結待審

**Model**: opus / xhigh (per model_router)
**Source task**: `assign_9a384b90`（P1, experiment）
**工作目錄（cwd）**: `.claude/worktrees/dispatch-slot-1-ae8721c1-k1739`（已註冊 linked worktree，branch `k1739-slot1-ae8721c1`，既有 commit `73cac199a`）
**實驗目錄**: `experiments/K1739/`

---

## 0. 先讀（不可跳過）

1. `experiments/K1739/codex_review_round4.md` — 本次要修的完整 FAIL 報告（與 canonical repo 的 `storage/ops/codex_reviews/k1739_round4_verdict.md` 同內容）
2. `experiments/K1739/README.md` — 現行 reader-facing 敘述（42KB，你要改的主要對象之一）
3. `experiments/K1739/K1739.py` — 現行實作（69KB）
4. `docs/error_log.md`（至少搜 K1701 / K1708 / K1709 三條）
5. `.claude/skills/autonomous-research/references/experiment-preamble.md`
6. `AGENTS.md` 的「研究誠實原則」與「實驗 artifact gate」兩節

## 1. 背景與定位（讀懂再動手）

K1739 是「商品期貨短期（1–4 週）動能與反轉共存 × vol regime」驗證實驗，主檢定量是 β2。
**現況不是失敗、不是遺失、也不需要搶救**：10 個 artifact 已完整 commit 在本 branch，
`review_verdict.json` 的 6 個 pinned sha256 與 commit 內 bytes 全部相符，certification gate
已實測正確擋住 merge（理由 = reviewer verdict is FAIL）。

Codex round-4（gpt-5.6-sol, max effort）判 **FAIL**：Standards 2 項 + Spec 4 項 blocking。
**你的工作只有一件事：把這 6 項缺陷從根修掉，重跑一次，重新凍結成可被重審的 bytes。**

現行結論是 **NULL**（β2 未達顯著）。修正後結論仍可能是 NULL —— 這完全可接受且必須如實報告
（AGENTS.md 研究誠實原則第 9 條）。**嚴禁**為了讓實驗「看起來有結果」而放寬任何門檻。
反過來也一樣：修正後若結論改變，必須誠實呈現並說明是哪一項修正造成的。

## 2. 六項 blocking defects — 逐項修復契約

### D1（Spec）pooled asset-clustered inference 只做成 diagnostic，沒進 adjudication/FDR

原始 brief 第 77 行寫死：**「主結論以 pooled panel（asset clustered SE）為準」**。
現行程式卻把 Driscoll–Kraay 當 primary，asset-clustered 只存成未裁決的 diagnostic。
這不是形式問題 —— common-sample horizon 2 與 4 的 stored cluster t-stat 分別是 **2.767 / 2.619**，
與被推上 primary 的 DK 路徑有實質分歧。

同時存在一個真實的方法論張力：**G=6（六個資產）的 cluster 漸近理論無效**，
直接把 6-cluster SE 當 primary 一樣不誠實。

**修法契約（三件事都要做，缺一不可）**：
1. **先預先宣告（predeclare）再看數字**：在 `K1739.py` 裡以常數／設定區塊寫死一個
   *joint adjudication rule*，明確規定 DK、asset-clustered（G=6）、stationary bootstrap
   三條推論路徑如何共同裁決 β2 的顯著性。宣告區塊要有註解說明理由，並且在 README
   與 results JSON 都原樣輸出這條規則。
2. **必須正面處理 G=6 的小 cluster 問題**，不得靜默選一條路徑收工。可接受的做法舉例
   （你自己判斷並說明理由，不必照抄）：對 cluster 路徑改用 wild cluster bootstrap 或
   小 G 修正（CR3 / t(G-1) 臨界值），或預先宣告 primary = 三路徑的保守交集
   （任一路徑不顯著即不判顯著）。**唯一禁止的是「沒有預先規則、事後挑一條」**。
3. **被裁決出來的那條 inference 必須是進 BH-FDR 的那條**。現在 FDR 吃的是 DK；
   修完之後 FDR 必須吃 adjudicated 結果。DK 與 cluster 的分歧要在 results JSON 裡
   保留成可查欄位（每個 cell 兩條 t-stat 都留），不是刪掉一條了事。

### D2（Spec）asset-level BH-FDR 漏掉 common-sample family

原始 brief 第 74 行：**「多重檢定（4 horizons × 2 樣本 × asset-level）一律過 BH-FDR」**。
現行只對 full-sample 的 24 個 asset-level test 做 BH，**common-sample 的 asset-level family 完全缺席**。

**修法**：補上 common-sample asset-level 家族的 BH-FDR。family 的切法（每個樣本各自一族，
或依 brief 的字面合成一族）要在程式裡明確宣告並在 README 說明；兩種 family 定義都要
在 results JSON 留下 adjusted p，讓審查者能自行驗證，不要只留一種。

### D3（Spec）SUPPORTED 判定允許 robustness sign flip

原始 brief 第 94 行：**「任一 robustness 翻號就降級結論」**。
現行 SUPPORTED 分支容許最高 20% 的 robustness sign 不一致。這個分支對現在的 NULL 是休眠的，
**但它實作了錯誤的成功規則**，必須修。

**修法**：把容忍度改成 0 —— 任何一個 robustness variant（vol window 21/63/126、regime median vs
tercile、common vs full sample、去掉 UNG）出現 β2 符號翻轉，顯著結果一律降級
（SUPPORTED → INCONCLUSIVE）。降級路徑要有測試涵蓋：寫一個小型 unit test 餵入人工造的
sign-flip 情境，斷言分級真的被降級。**不要只改常數就宣稱修好。**

### D4（Standards）文獻引用錯誤作者／縮寫

已被點名的三筆：
- *Understanding Momentum and Reversal* 作者是 **Kelly, Moskowitz, and Pruitt (2021)**，不是 Cheng et al.
- Han 與 Xu/Wang 的 initials 有誤
- Da, Liu, and Schaumburg (2014) 被引成了另一篇論文

**修法**：把 README 文獻段落的**每一筆**引用逐條核對到真實出處（作者全名／年份／期刊／標題），
不是只修被點名的三筆。**任何你無法核實到具體出處的引用，直接刪掉** —— 留著一筆
無法核實的引用，等同造假（AGENTS.md 研究誠實原則第 1、2 條）。核對過程與最終清單
寫進 remediation 報告。

### D5（Standards）README 宣稱 byte-identical 重現，但事實不是

`run_utc`、`runtime_seconds`、`runtime_env` 與 reproduce-spec 的 runtime metadata 每次跑都會變，
且 `pd.read_csv` 沒設 `float_precision="round_trip"`。

**修法（三項都要）**：
1. `pd.read_csv` 加上 `float_precision="round_trip"`（所有讀 CSV 的地方）。
2. README 的重現宣稱改成 **tolerance-equivalent reproduction**，不是 byte-identical；
   並明確列出哪些欄位本質上會變（run_utc / runtime_seconds / runtime_env / spec runtime metadata），
   以及在排除這些欄位後，哪些東西才真的是 byte-stable。
3. 順手補掉 nonblocking gap：在 CSV 說明、results JSON 與 README 三處**明確宣告
   source/index 的時區**。

### D6（Standards）部分 reader-facing 數字無法回溯到現行 results JSON

已被點名：README 的 CPER 價格範例、歷史 H2 數值 **1.716**。

**修法**：掃過 README 裡**每一個**數字，逐一確認能對應到 `K1739_results.json` 的某個欄位。
處理方式二選一 —— (a) 把該數字加進 results JSON 成為正式輸出欄位（由程式計算，不是手打），
或 (b) 從 README 刪除。**禁止**在 README 保留任何 results JSON 裡不存在的數字。
掃描結果做成一張對照表（README 數字 → results JSON 路徑）放進 remediation 報告。

## 3. 執行順序（照做）

1. 讀完 §0 全部檔案，把 6 項缺陷各自在 `K1739.py` / `README.md` 的確切位置先定位出來。
2. **先寫 predeclared adjudication rule（D1 第 1 步），再改任何計算**。順序反了就是 p-hacking。
3. 改程式（D1 / D2 / D3 / D5-1），改 README（D4 / D5-2 / D5-3 / D6）。
4. **重跑一次** `K1739.py`。資料是 `experiments/K1739/data/prices_daily.csv`（已快取，離線可跑），
   **禁止重新下載或更換資料**。seed 固定（bootstrap seed 42、B=2000、whole-week blocks、
   expected block length 8 —— 這些 round-4 已驗過正確，不要動）。
5. 收尾必須呼叫 canonical helper，讓 results 與 spec 由同一次 trace 寫出（AGENTS.md 2026-07-22 K1708 教訓）：
   ```python
   from volpred.research.reproduce_spec import finalize_experiment
   finalize_experiment(results=payload, entrypoint=__file__,
                       canonical_result="K1739_results.json", inputs=[...],
                       seeds=[("numpy", 42)], started_at=T0)
   ```
   **禁止事後手補 reproduce_spec.json。**
6. 圖表重新產生（三張 figures 都要與新的 results 一致）。
7. 跑 `uv run python scripts/experiment_gates.py run --path experiments/K1739` —— 四道
   source-integrity gate 必須全過。
8. 跑 `python3 scripts/check_experiment_artifacts.py check --path experiments/K1739`。
9. **重新產生裁決骨架**（這一步不可省、不可手寫）：
   ```bash
   uv run python scripts/experiment_gates.py verdict-template --path experiments/K1739 \
     --out experiments/K1739/review_verdict.json
   ```
   產出來的是帶 `FILL:` placeholder 與新 pinned sha256 的骨架。
   **你只產生骨架，不填任何 verdict 欄位**。填 verdict 是 Codex round-5 的事。
10. 寫 remediation 報告 `experiments/K1739/remediation_round5.json`（schema 見 §4）。
11. 在本 worktree branch commit 全部變更（commit message 要說明改了什麼、為什麼）。

## 4. 必交付 artifact（成功後置條件）

`experiments/K1739/remediation_round5.json`，schema：

```json
{
  "round": 5,
  "source_task_id": "assign_9a384b90",
  "prior_verdict_artifact": "storage/ops/codex_reviews/k1739_round4_verdict.md",
  "defects": [
    {"id": "D1", "axis": "spec", "summary": "...",
     "fix": "改了什麼（檔案 + 函式 + 行為差異）",
     "evidence": "怎麼驗證修好了（測試名 / 重跑前後數字 / gate 輸出）",
     "residual_risk": "還有什麼沒能完全解決，或 null"}
  ],
  "adjudication_rule": {"declared": "預先宣告的 DK×cluster×bootstrap 裁決規則原文",
                        "rationale": "為什麼這樣裁決，含 G=6 小 cluster 問題怎麼處理"},
  "conclusion": {"before": "NULL", "after": "...", "changed_because": "..."},
  "readme_number_traceability": [{"readme_value": "...", "results_json_path": "..."}],
  "citations_verified": [{"cited": "...", "verified_source": "...", "action": "kept|corrected|removed"}],
  "reruns": {"command": "...", "started_utc": "...", "completed_utc": "..."},
  "gates": {"experiment_gates_run": "pass|fail + 輸出摘要",
            "check_experiment_artifacts": "pass|fail + 輸出摘要"},
  "verdict_template_regenerated": true,
  "pinned_sha256_after": {"K1739.py": "...", "K1739_results.json": "...", "README.md": "...",
                          "figures/beta2_by_horizon.png": "...", "figures/h2_regime_returns.png": "...",
                          "figures/past_vs_future_by_regime.png": "..."}
}
```

`defects` 陣列必須有 D1–D6 共 6 筆，一筆都不能少。

## 5. 硬性禁令

- ❌ **禁止手改 `review_verdict.json`**。只能用 `experiment_gates.py verdict-template` 產生骨架。
  sha 會因為你的修改而漂移、gate 會再擋一次 —— **那是設計，不是 bug**。
- ❌ **禁止自行填 PASS**。只有 Codex round-5 對凍結後 bytes 重審給出的新 PASS 才算數。
- ❌ **禁止 merge**、禁止碰 main checkout、禁止 `git worktree remove --force`。
- ❌ **禁止寫 `storage/memory/knowledge.json`**（K1259 gate：knowledge 條目只能主線程寫，
  且只有 PASS 後才寫）。也禁止碰 `storage/reports/feed.json`、`thinking_journal.json`、
  `experiment_experiences.json`、Supabase / Mirror sync。
- ❌ **禁止 `--no-verify`、禁止 force push**。
- ❌ **禁止換資料、禁止改 seed、禁止調參數讓結果變顯著**。研究誠實 > 一切。
- ✅ 你只能寫 `experiments/K1739/` 內的檔案（+ 必要時 `src/volpred/` 的 bug 修正，若真的
  發現 canonical helper 有缺陷 —— 那要在 remediation 報告單獨說明）。

## 6. 成功標準

1. D1–D6 六項全部有實質修正 + 可驗證證據（不是文字宣稱）。
2. 實驗重跑一次成功，results / spec / figures 三者一致且同一次 trace 產出。
3. `experiment_gates.py run` 與 `check_experiment_artifacts.py check` 都通過。
4. `review_verdict.json` 是新產生的骨架（新 sha、未填 verdict）。
5. `remediation_round5.json` 完整交付，6 筆 defect 齊全。
6. 全部 commit 在 `k1739-slot1-ae8721c1`，工作區乾淨。
7. 最後輸出一段結構化摘要：6 項修正各一行、裁決規則原文、修正後結論分級、
   新 pinned sha、commit hash、artifact 路徑。
