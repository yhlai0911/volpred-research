# K1814 — 深度學習 vs HAR 的「中長 horizon 才贏」邊界檢定

**Model**: opus / xhigh (per model_router)
**Task**: K1814 (experiment lane, worktree topology)
**Worktree**: `.claude/worktrees/dispatch-slot-1-8af0700e-k1814`（branch `wt/dispatch-slot-1-8af0700e-k1814`）
**來源接地**: research_program.md line 598（unchecked open item）；文獻線索 JFEC / IJF 2025 "ML-vs-HAR"。

## ⚠️ K-id 紀律（本任務特有，務必遵守）
這個主題原本掛在 **K1731**，但該號碼在 2026-07-18 被另一個實驗（GEVReg-MIDAS-SSVS arm B）
未經 `kid_reserve` 佔用，其 31 個 commit 至今停在未 merge 的 branch
`wt/dispatch-slot-1-bd00f90a-k1731`，導致 `compute_queue` 的 literal-grep collision gate
永久拒派 K1731。主題已於 `storage/ops/k_id_registry.json` renumber 為 **K1814**。

- **所有檔名、目錄、commit message、results key 一律只用 `K1814` / `k1814`**。
- **禁止在 commit message 裡出現字串 `K1730` 或 `K1731`**（會替其他任務製造同一個 collision）。
- 不要去碰 `experiments/k1730/` 或 `experiments/k1731/`（那是別的實驗的產物）。

## 研究誠實原則（不可違反 — 見 AGENTS.md）
- 一切數字來自實際計算；標明資料來源、期間、樣本數。
- **Lookahead 是最高風險**：所有特徵只能用 t-1 及更早的資訊預測 t（或 t..t+h）；程式碼要有明確 lag / 滾動視窗切割，禁止用全樣本 scaler、全樣本 hyperparameter 挑選。
- 所有隨機程序 `seed=42`（numpy / torch / train-test split / early-stopping shuffle 都要）。
- Null result 如實報告；結論強度不可超過證據。
- 方法論必須有正式檢定（DM / Harvey-Leybourne-Newbold 小樣本修正），不要只看 loss 大小下結論。

## 為什麼還要做這題（先讀，避免重複踩坑）
知識庫中 **K1310–K1330 一系列 ML novel-method 實驗（GARCH-Neural / HAR-GNN / Transformer / KAN /
Conformal）連續 4 個 NULL**：在 1 日 horizon 上 DL 打不贏 HAR。本實驗**不是再提一個新架構**，
而是回答那批 NULL 留下的開放問題：**DL 的增量究竟在哪個 horizon 才出現（如果真的出現）**。
因此 **NULL 是完全可接受、且有價值的結果** —— 「1/5/22 日全都輸給 HAR」是明確結論，
不准為了做出正結果而調參到過擬合。開工前先 grep `storage/memory/knowledge.json` 讀 K1310–K1330
的既有結論（禁止整檔讀取，用 grep / jq 取單條）。

## 資料可行性 gate（**先做這一步，再寫任何模型**）
yfinance 的 intraday 歷史有硬上限（1m 約 7 天、5m 約 60 天）。**60 天的 5-min 資料無法支撐
22 日 horizon 的 OOS 評估** —— 這是本題最可能的失敗點，也是最可能被粉飾的地方。

開工第一件事：**實測** yfinance 對目標標的（^GSPC / SPY / QQQ）5-min 能取回的實際起訖與筆數，
把數字寫進 README。然後二選一，並在 README 明述選了哪條與為什麼：

- **(A) 5-min RV 路線**：只有在實際取回的樣本足以做 1/5/22 日 horizon 的滾動 OOS 時才走。
  明列 train / OOS 視窗長度與有效預測筆數；筆數不足以支撐 DM 檢定就不要硬做。
- **(B) 長歷史 proxy 路線**（若 A 不可行）：改用 daily OHLC 的 realized-range proxy
  （Parkinson / Garman-Klass / Rogers-Satchell），取得數十年樣本。**必須在 README 標題與
  結論都寫明「這是 realized-range proxy，不是 5-min RV」**，並說明 proxy 與 5-min RV 的
  已知偏誤方向。口徑不可混用。

**禁止**：宣稱用了 5-min RV 但實際只有 60 天；或把 proxy 當 5-min RV 報。

## 假說（可證偽）
1. **H1（短 horizon）**：h=1 日，DL（LSTM / 簡化 Transformer）的 QLIKE **不顯著優於** HAR-RV
   （複製 K1310–K1330 的既有 NULL，作為 sanity check —— 若這裡就贏了，先懷疑 bug/lookahead）。
2. **H2（邊界）**：存在一個 horizon h* ∈ {1, 5, 22}，使 h ≥ h* 時 DL 的 QLIKE 顯著優於 HAR。
3. **H3（機制）**：若 H2 成立，增量來源可歸因（例：長記憶 / 非線性 regime 轉換 / 跨期交互），
   而非單純的樣本雜訊；用消融（ablation）驗證。

## 方法
1. **描述統計先行**：RV（或 proxy）的分布、長記憶（ACF 衰減、Hurst / d 估計）、regime 切換觀察。先看資料再建模。
2. **Baseline = HAR-RV**（Corsi 2009）：日 / 週 / 月成分，OLS + HAC SE。**這是要被打敗的對象，必須誠實實作**
   （含 log-RV 版本；報 log 空間或水平空間要一致）。可再加 HAR-J / HARQ 作為強 baseline（可選）。
3. **DL 模型**：LSTM 與一個簡化 Transformer（單/雙層、小 d_model）。
   - 超參數只在 **training/validation 期**挑選，**禁止**用 OOS 挑。
   - scaler 只 fit 在 train window，roll forward 時重 fit。
   - 每個設定跑 **多 seed（≥5）**，報 mean ± sd —— 單 seed 的勝負沒有意義。
4. **評估**：直接多步預測（direct h-step），h ∈ {1, 5, 22}。
   - 主指標 **QLIKE**（對 vol 預測比 MSE 更適當），輔以 MSE / MAE。
   - **Diebold-Mariano 檢定**（Harvey-Leybourne-Newbold 小樣本修正，h>1 用 HAC/Newey-West with
     lag = h-1），對每個 horizon 分別做 DL vs HAR。
   - 3 個 horizon × 多模型 → **BH-FDR 控制多重比較**。
   - 滾動或擴張視窗 OOS，明列切點與有效預測筆數。
5. **消融 / 穩健性**：模型容量、視窗長度、log vs level、跨標的。

## 交付物（三件套，寫入 worktree）
- `experiments/k1814/README.md`：motivation（含 K1310–K1330 NULL 脈絡）+ **資料可行性 gate 的實測結果與路線選擇** + method + **lookahead policy 明述** + success criteria + 結果摘要 + 局限。
- `experiments/k1814/k1814.py`：可重跑，`seed=42`，明確 lag 與 rolling refit，模型定義與評估清楚。
- `experiments/k1814/K1814_results.json`：byte-traceable 輸出（每個 README 數字都能對應到 json key）。**這是 result artifact 契約路徑，必須存在。**
- 圖表（RV ACF、by-horizon QLIKE 比較含誤差棒、DM 統計量、預測 vs 實際）放 `experiments/k1814/`。

### reproduce spec 在 run-time 產生（AGENTS.md 2026-07-22 硬規）
腳本收尾必須呼叫 canonical helper，讓 results 與 spec 由同一次 trace snapshot 寫出：

```python
from volpred.research.reproduce_spec import finalize_experiment

finalize_experiment(
    results=payload, entrypoint=__file__,
    canonical_result="K1814_results.json",
    inputs=[...], seeds=[("numpy", 42), ("torch", 42)], started_at=T0,
)
```

事後補 spec 會被 `scripts/check_experiment_artifacts.py` 在 merge / CI 擋下。
開工前自查：`python3 scripts/check_experiment_artifacts.py check --path experiments/k1814`

## Success criteria
- 每個 horizon 給明確 accept/reject + QLIKE 差異 + DM 統計量 + p 值（FDR 後）+ 多 seed sd。
- **明確回答 h\***：若 1/5/22 全都不顯著 → 如實報「在本資料與本設定下不存在 DL 勝出的 horizon」。
- 若 h=1 就顯著勝出 → **先懷疑 lookahead 或 baseline 實作弱化**，回頭查再下結論。
- 資料可行性 gate 的實測數字（實際起訖、筆數、有效 OOS 預測數）必須在 README 明列。

## Codex 二審（primary path）
完成後產出 `experiments/k1814/review_verdict.json`（Codex review；quota 擋則 fallback subagent / audit）。
未達 **CONDITIONAL_PASS** 不得宣稱結論、不得寫 knowledge（K1259：agent 禁寫 knowledge.json，由主線程收件時寫）。
審查重點請明列：lookahead、baseline 是否被弱化、多 seed 是否真的跑、DM 修正是否正確、資料口徑是否與宣稱一致。

## Worktree 紀律
- 只產出 `experiments/k1814/` 內檔案。**禁止修改** `storage/reports/feed.json`、`storage/memory/knowledge.json`、
  `storage/memory/thinking_journal.json`、`storage/memory/experiment_experiences.json`、Supabase / Mirror sync。
- 完成後在 worktree 內 commit（commit message 只提 K1814）。主線程之後用 `bash scripts/merge_worktree.sh` 合併。

## 收件（future PHASE A followup 會做，agent 不必做）
verify results==README==agent 三者一致 → 檢 lookahead 與 baseline 實作 → 檢 verdict → 主線程寫 knowledge → merge_worktree.sh 整合。
