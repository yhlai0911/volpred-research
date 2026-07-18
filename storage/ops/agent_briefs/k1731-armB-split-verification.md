# K1731 arm B — 拆段 1／2：成果驗收（verification only，禁止再跑實驗）

**Model**: opus / xhigh (per model_router)
**Parent timeout job**: `agent-brief_k1731_armB-f3e688`（7200s 額度用盡被砍，非失敗）
**Split stage**: `verification`
**Worktree（唯一可寫處）**: `.claude/worktrees/dispatch-slot-1-bd00f90a-k1731`

## 背景：這不是重跑，是收尾

上一段 agent 在被 timeout 砍掉前已經做完絕大部分工作。工作區裡有：

- `experiments/k1731/k1731_gevreg_midas_ssvs_returns_results.json`（原始）
- `experiments/k1731/k1731_gevreg_midas_ssvs_returns_results_corrected.json`（修正版）
- `k1731_mcmc_diagnostic_results.json`、`k1731_quickmode_results.json`
- `README.md`（30KB，含三輪自審紀錄）、fig1-fig4 四張圖
- `k1731_finalize_report.py`、`k1731_gevreg_midas_ssvs_returns.py` 等程式碼

**禁止重跑 MLE / MCMC / 全期 backtest。** 你的工作是驗收既有產出，不是再生一份。若驗收過程發現
必須重算某一小塊，只做那一小塊，並在產出裡註明重算了什麼、為什麼。

## 必須回答的問題（照順序）

1. **哪一份是 canonical？** 同時存在 `_results.json` 與 `_results_corrected.json` 是這批產出最大的
   風險——下游（文章／論文／knowledge）引錯就是引到已知有錯的數字。判定哪一份為準、另一份該不該
   改名或標記，並說明依據（兩者的 `specification` / `quick_mode` / 內容差異）。
2. **誠實性**：README 與 corrected results 裡每個宣稱數字，是否都能在指名的 artifact 裡找到？
   README 第三輪自審聲稱「traceability sweep 找不到不可追溯的數字」——**你要獨立複驗這個宣稱**，
   不是接受它。抽驗至少 15 個關鍵數字（覆蓋率、Kupiec/Christoffersen/DQ p 值、PIP、DM t 值、
   economic value），逐個標明出處欄位。
3. **lookahead 三項檢查**是否真的 0 violations？baseline 是否用同 lag、同 OOS 切法？
   （`lookahead_checks` 欄位 + 程式碼實際切法要對得起來，不能只看欄位寫 0。）
4. **符號與實作**：block minima 轉 maxima 的符號、DQ test 實作、DM test 的 HAC——這三處是
   parent brief 原本要 Codex 審的重點。用 `codex exec` 做代碼審（額度無限制），把 verdict 收進產出。
5. **experiments/k1730/ 是否未被改動**（arm A 不可被 arm B 污染）。
6. **README 未解決事項**（GARCH 收到 block realized trading-day count、MCMC 只覆蓋六變數規格、
   NFP benchmark component 未分離識別）是否已在 limitations 誠實揭露，還是只寫在 README 沒進 JSON。

## 產出（唯一 artifact）

`experiments/k1731/k1731_armB_verification.json`，至少包含：

```
{
  "canonical_artifact": "<檔名>", "canonical_reason": "...",
  "traceability": {"checked_n": N, "untraceable": [...]},
  "lookahead": {"violations": N, "baseline_alignment_ok": bool, "evidence": "..."},
  "codex_review": {"block_minima_sign": "...", "dq_test": "...", "dm_hac": "...", "verdict": "pass|issues"},
  "k1730_untouched": bool,
  "limitations_disclosed_in_json": bool,
  "verdict": "ready_to_merge | needs_fix",
  "blocking_issues": [...]
}
```

## 成功判準

`verdict` 有明確結論，且 `traceability.checked_n >= 15`。**發現問題 = 成功的驗收**，不是失敗——
`verdict: needs_fix` 加上具體 blocking_issues，比硬說 ready 有價值得多。禁止為了讓 verdict 好看
而放水；研究誠實 > 一切。

## 邊界

- 只寫上述 worktree，禁碰 main checkout、禁 git merge（合併是拆段 2 的事）。
- 禁寫 knowledge.json（主線程職責）。
- 時間預算 3600s。做不完就把已完成的檢查寫進 artifact 並標 `verdict: needs_fix`
  + `blocking_issues: ["驗收未完成：<還差什麼>"]`，不要拖到被砍。
