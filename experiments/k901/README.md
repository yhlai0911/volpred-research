# K901: International VT Evidence — 13 Markets for Paper 3 Table 5

- Experiment ID: `k901`
- Status: pending_rerun (Codex FAIL fixed 2026-05-16; awaiting re-run via compute_queue)
- Created At: 2026-04-16T09:41:26.980187+00:00
- Run At: 2026-04-05 (original); compute_queue enqueued 2026-05-16 (post-fix)

## 問題描述

12/VIX VT 策略在 13 個國際市場是否有效？（Paper 3 Table 5 的完整數據來源）

## 動機

Paper 3 R2 HIGH A.2: "Table 5 (13 International Markets) untraceable. K567 only tested 6 markets." 此實驗補齊全部 13 市場的 Sharpe、MDD、GJR gamma、DM test 數據。

## 方法

- 市場：SPY, EWJ, EWG, EWU, EWA, EWC, EWZ, EEM, EFA, FXI, EWH, EWT, EWY（13 個）
- 策略：w_t = min(12/VIX_{t-1}, 1.0) equity，餘 SHY；signal.shift(1) 防 lookahead
- GJR-GARCH(1,1) rolling 估計（window=2000，年步）；全樣本估計
- Bootstrap Sharpe CI（n=5000，seed=42）
- DM test（volpred.stats）
- 資料：yfinance 2005-2026

## Codex Review — FAIL → 已修正（2026-05-16）

**原始 Codex review（2026-05-16）**：FAIL。2 個 Major issues：

1. **GJR silent fail**（L48, L224, L243, L264）：全域 `warnings.filterwarnings("ignore")` + bare `except: pass` + 不檢查 `convergence_flag`，導致非收斂估計值混入結果。
   - **修正**：移除全域 suppress；`convergence_flag != 0` 的視窗 skip 並計入 n_failed；只有 `converged==True` 且有限值的估計進入 rolling summary；加入 `n_attempted/n_converged/n_failed` 到結果 JSON。

2. **Bootstrap seed 缺失**（L270-289）：使用全域 `np.random.choice`，不可重現。
   - **修正**：`BOOTSTRAP_SEED = 42`；改用 `np.random.default_rng(BOOTSTRAP_SEED).choice()`；seed 寫入結果 JSON。

**3 個 Minor issues 同步修正**：
- signal 第一天 fillna(1.0) → dropna()（語義更正確）
- Sharpe>2x/MDD>80%/DM>3 等 sanity check 改為結構化 `review_flags` 欄位
- Spearman 加入常數輸入檢查

## 待辦

- [ ] compute_queue re-run（13 markets，2006-2026）
- [ ] Codex re-review（CONDITIONAL_PASS+ 才寫 knowledge.json）
- [ ] 通過後寫 knowledge.json + document_K901_kb_entry

## 預期結果（從原始跑結果推估）

MDD 改善 13/13 市場；Sharpe 改善部分市場；GJR gamma > 0 全部市場。

## 參考文獻

- Moreira & Muir (2017) JoF: Volatility-managed portfolios
- Bozovic (2024) IRFA: VIX-managed > realized-vol managed
- Hood & Raughtigan (2024/2025) JPM: VT alpha from implicit trend-following
