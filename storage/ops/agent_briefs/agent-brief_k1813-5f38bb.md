# K1813 — 隔夜/日內波動率溢酬（VRP）clustering 與星期效應擇時的可交易性

**Model**: opus / xhigh (per model_router)
**Task**: K1813 (experiment lane, worktree topology)
**Worktree**: `.claude/worktrees/dispatch-slot-1-8af0700e-k1813`（branch `wt/dispatch-slot-1-8af0700e-k1813`）
**來源接地**: research_program.md line 596（unchecked open item）；文獻線索 AEF / Harbourfront 2025-26 "VRP calendar effect"。

## ⚠️ K-id 紀律（本任務特有，務必遵守）
這個主題原本掛在 **K1730**，但 K1730 這個號碼在 2026-07-18 被另一個實驗
（GEVReg-MIDAS-SSVS arm A）未經 `kid_reserve` 佔用，且那些 commit 至今停在未 merge 的
branch `wt/dispatch-slot-1-bd00f90a-k1731` 上。因此 `compute_queue` 的
`_find_task_dispatch_collision`（literal grep commit message）永久拒派 K1730。
主題已於 `storage/ops/k_id_registry.json` renumber 為 **K1813**。

- **所有檔名、目錄、commit message、results key 一律只用 `K1813` / `k1813`**。
- **禁止在 commit message 裡出現字串 `K1730` 或 `K1731`** —— 那會在未 merge 期間替其他任務
  製造同一個 collision。要提來歷就寫「renumbered from an earlier squatted id」。
- 不要去碰 `experiments/k1730/` 或 `experiments/k1731/`（那是別的實驗的產物）。

## 研究誠實原則（不可違反 — 見 AGENTS.md）
- 一切數字來自實際計算；標明資料來源、期間、樣本數。
- **Lookahead 是最高風險**：訊號 `signal.shift(1)`、`return at t`，禁止 same-day 訊號乘 same-day 報酬；程式碼要有明確 lag。
- 所有隨機程序 `seed=42`。
- Null result 如實報告；結論強度不可超過證據。
- 區分實證 / 模擬；方法論要有正式檢定（不要只看圖下結論）。

## 假說（可證偽）
1. **H1（clustering）**：隔夜段已實現波動（overnight RV，close→next-open）本身有顯著自我叢聚（AR 結構），且與日內段（open→close）RV 的叢聚結構不同。
2. **H2（星期效應）**：overnight VRP（= overnight implied/expected vol proxy − realized overnight vol，或以 overnight RV 相對其滾動基準的偏離為 tradeable proxy）存在顯著 day-of-week 差異（例：週一 open gap 溢酬 vs 週五）。
3. **H3（可交易性，主結論）**：以 t-1 資訊建構的 day-of-week × overnight 擇時規則，**扣除交易成本後**，其風險調整報酬是否顯著優於 buy-and-hold / 無條件基準。**重點是「含成本後還剩什麼」，不是毛報酬。**

## 資料（唯一來源 yfinance，免費）
- ETF universe：至少 SPY，外加 QQQ / IWM / TLT / GLD（跨資產穩健性；不對稱是有價值的 null）。
- 欄位：daily OHLC。**overnight segment = 前一日 close → 當日 open**；**intraday segment = 當日 open → close**。
- 期間：資料起點（SPY ~1993）→ 最新；明列每檔實際樣本數與缺值處理。yfinance 的 adjusted vs raw open 要講清楚（overnight gap 對 adjustment 敏感 —— 用 raw OHLC 計 segment return，dividend/split 另行處理並記錄）。
- OOS split：明定 in-sample / OOS 切點（例 2015-01），星期效應係數只在 in-sample 估、OOS 驗。

## 方法（觀察先於計算）
1. **描述統計先行**：overnight vs intraday segment return 的分布、by-weekday 的均值/波動/樣本數表；overnight RV 的 ACF/PACF。先看資料再估模型。
2. **clustering 檢定**：overnight RV 與 intraday RV 各自 Ljung-Box / AR(1..5)；比較兩段係數（H1）。
3. **星期效應檢定**：weekday dummy 迴歸（overnight VRP proxy ~ weekday），**HAC/Newey-West SE**；聯合 F 檢定 weekday 係數全 0（H2）。多重比較（5 個 weekday × 多 ETF）用 BH-FDR 控制。
4. **可交易性（H3，主結論）**：以 **t-1 estimated** weekday signal 建 long/short 或 timing overlay；`position = f(weekday, signal).shift(1)`。報酬 = position × segment return at t。**成本情境**：至少 3 檔（0 / 1bp / 5bp per turn，寫明 turnover）。指標：ann. return、vol、Sharpe、maxDD、turnover。對基準做 **Diebold-Mariano 或 Sharpe 差異 bootstrap 檢定**（block bootstrap，seed=42），不要只比點估。
5. 穩健性：跨 ETF、跨子期間、成本敏感度。

## 交付物（三件套，寫入 worktree）
- `experiments/k1813/README.md`：motivation + 資料契約 + method + **lookahead policy 明述** + success criteria + 結果摘要 + 局限。
- `experiments/k1813/k1813.py`：可重跑，`seed=42`，明確 `.shift(1)` lag，segment 計算與成本模型清楚。
- `experiments/k1813/K1813_results.json`：byte-traceable 輸出（每個 README 數字都能對應到 json key）。**這是 result artifact 契約路徑，必須存在。**
- 圖表（ACF、by-weekday bar、equity curve with/without cost）放 `experiments/k1813/`。

### reproduce spec 在 run-time 產生（AGENTS.md 2026-07-22 硬規）
腳本收尾必須呼叫 canonical helper，讓 results 與 spec 由同一次 trace snapshot 寫出：

```python
from volpred.research.reproduce_spec import finalize_experiment

finalize_experiment(
    results=payload, entrypoint=__file__,
    canonical_result="K1813_results.json",
    inputs=[...], seeds=[("numpy", 42)], started_at=T0,
)
```

事後補 spec 會被 `scripts/check_experiment_artifacts.py` 在 merge / CI 擋下。
開工前自查：`python3 scripts/check_experiment_artifacts.py check --path experiments/k1813`

## Success criteria
- H1/H2/H3 各自給明確 accept/reject + 檢定統計量 + p 值（FDR 後）。
- **主結論以「含成本可交易性」為準**：若毛效應顯著但 1-5bp 成本後消失 → 如實報 null（這是有價值的結果，不可粉飾）。
- 跨 ETF 不對稱要點名。

## Codex 二審（primary path）
完成後產出 `experiments/k1813/review_verdict.json`（Codex review；quota 擋則 fallback subagent / audit）。未達 **CONDITIONAL_PASS** 不得宣稱結論、不得寫 knowledge（K1259：agent 禁寫 knowledge.json，由主線程收件時寫）。

## Worktree 紀律
- 只產出 `experiments/k1813/` 內檔案。**禁止修改** `storage/reports/feed.json`、`storage/memory/knowledge.json`、
  `storage/memory/thinking_journal.json`、`storage/memory/experiment_experiences.json`、Supabase / Mirror sync。
- 完成後在 worktree 內 commit（commit message 只提 K1813）。主線程之後用 `bash scripts/merge_worktree.sh` 合併。

## 收件（future PHASE A followup 會做，agent 不必做）
verify results==README==agent 三者一致 → 檢 verdict → 主線程寫 knowledge → merge_worktree.sh 整合 → 若含成本後有可交易 edge 且乾淨，考慮 reader-facing 選題（先過 arc-dedup gate）。
