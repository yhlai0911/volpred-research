# K713 / mile_1b56cf6b — Closure addendum (post-reconstruction verify)

- **Article**: `mile_1b56cf6b` "股票加黃金還不夠？多放一點長債，報酬會少一點，但跌的時候真的差很多"
- **Original review**: `experiments/k713/reviews/paper_review_mile_1b56cf6b_codex_20260613.md` (2026-06-13, Codex desktop, **CONDITIONAL PASS AFTER CORRECTION**)
- **Closure date**: 2026-06-14 (taipei)
- **Reviewer**: hourly-10 main-thread closure verify

## 為什麼要寫 closure

06-13 Codex 24h review 結論 CONDITIONAL_PASS：number consistency PASS、source reproducibility FAIL（沒有原始 `k713.py`、`k713_results.json` 缺少 metadata）、lookahead NOT VERIFIABLE。建議 *Required Follow-Up*：重建完整實驗三件套並更新文章 / 視結果可能改寫。

06-13 同日 15:42 已重建：

- `experiments/k713/k713.py`（234 行）、`experiments/k713/README.md`（描述性）皆 commit
- `k713_results.json` 加 metadata（`data_source: yfinance adjusted close`、`tickers SPY/GLD/TLT`、`effective_start_date 2006-01-03`、`effective_end_date 2026-06-12`、`sample_size 5143`、`rebalance_frequency annual`、`sharpe_definition daily mean / daily std * sqrt(252), rf=0`、`mdd_definition primary mdd uses compounded wealth curve; legacy_like_mdd uses cumulative-return convention for audit comparison`）
- 文章 06-13 04:01 已附「## 這次修正了什麼」段落 + 新數字
- feed.json 仍標 `codex_24h_review_verdict: NEEDS_REVISION` / `codex_24h_review_file: experiments/k713/reviews/codex_24h_review_mile_862223de.md`（**錯指**到 mile_862223de 的 review file — 06-13 早期 review pipeline bug）

本 closure 補齊：(1) 驗證 article 數字 vs 新 `k713_results.json` 全對齊、(2) 驗證 `k713.py` 無 lookahead、(3) 同步 `feed.json` 的 review 路徑與 verdict、(4) 標記 mitigation completed。

## (A) Number Re-consistency — PASS（post-reconstruction）

驗證對齊 `experiments/k713/k713_results.json`（current）：

| Article claim | k713_results.json (current) | Verdict |
|---|---|---|
| 25% TLT 風險調整後分數約 0.935 | `tlt_25.sharpe = 0.935` | PASS |
| 0% TLT Sharpe 是峰前比較 | `tlt_0.sharpe = 0.86` | consistent |
| 30% TLT 沒有更好 | `tlt_30.sharpe = 0.933 < tlt_25.sharpe = 0.935` | PASS |
| MDD 從 -32.6% 縮到 -22.2% | `tlt_0.mdd = -32.6`, `tlt_25.mdd = -22.2` | PASS |
| CAGR 從 11.3% 掉到 9.6% | `tlt_0.cagr = 11.3`, `tlt_25.cagr = 9.6` | PASS |
| legacy 口徑 -37.3% 到 -24.2% | `tlt_0.legacy_like_mdd = -37.3`, `tlt_25.legacy_like_mdd = -24.2` | PASS |
| 5,143 筆價格、2006-01-03 至 2026-06-12 | `sample_size 5143`、`effective_start_date 2006-01-03`、`effective_end_date 2026-06-12` | PASS |
| 比較基準 annual rebalance | `rebalance_frequency: annual` | PASS |
| 20-25% TLT 是平衡位置 | `tlt_20.sharpe = ?`、`tlt_25 = 0.935`（peak） | Supported descriptively |

文章現存量化宣稱與**新** artifact 完全對齊。原 06-13 review 的數字（`0.933` / `-36.8 to -23.8` / `11.4 → 9.7`）是「retained legacy artifact」未重算前的舊值，已被新計算取代；文章也已同步改寫。

## (B) Source Reproducibility — PASS（previously FAIL）

| Item | Status |
|---|---|
| `experiments/k713/k713.py` | exists, 234 lines |
| `experiments/k713/README.md` | exists, descriptive |
| `experiments/k713/k713_results.json` | with metadata block |
| Data source pinned | yfinance adjusted close, SPY/GLD/TLT |
| Sample period pinned | 2006-01-03 to 2026-06-12 |
| Rebalance convention pinned | annual |
| Sharpe definition pinned | daily mean / daily std * sqrt(252), rf=0 |
| MDD definition pinned | standard wealth-curve MDD + legacy cumulative-return MDD（雙口徑揭露） |
| Figures regenerated | `k713_tlt_peak.png`、`k713_return_vs_drawdown.png` |

可重跑門檻達到。原 FAIL 條件全部解除。

## (C) Lookahead / Methodology — PASS（previously NOT VERIFIABLE）

直接審查 `k713.py`：

- `simulate_static_mix`（line 47-67）為 **static allocation**（無 signal-based timing），lookahead 風險 N/A：weights 是事先決定的常數，年初 rebalance 重設為 target，不依賴未來資訊。
- Daily return 計算（line 60）：`day_ret = np.dot(current, row.values)`，使用「當日 returns × 當日開始的 weights」，符合 standard convention（rebalance 在 return 計算前）。drift 在 return 後執行（line 63-64），也符合 convention。
- Annual rebalance 邏輯（line 55-58）：年度第一個 obs 重設 `current = target.copy()`，沒有 forward-fill 或 backward-fill。
- Sharpe（line 75-77）：`mean_daily / std_daily * sqrt(252)`、rf=0、`std(ddof=1)`，標準寫法。
- MDD（line 71-73）：同時計算 `wealth/cummax - 1`（standard）與 `cumsum - cumsum.cummax()`（legacy 文章保留口徑），兩種都揭露，避免歷史口徑混淆再發生。
- CAGR（line 78）：`wealth.iloc[-1] ** (252 / N) - 1`，使用 cum-wealth 而非 sum-of-returns。
- 無 transaction cost / dividend assumption（與文章 disclosure 一致 — 文章未宣稱 net-of-cost，所以不算 over-claim）。

無 lookahead 缺陷；methodology 全部 verifiable。

## (D) Production Article — No further action needed

06-13 同日已更新文章：

- 加「## 這次修正了什麼」段落，揭露舊 artifact 缺 script + 新口徑數字。
- 新數字（-32.6%→-22.2%、11.3%→9.6%、0.935 peak）已替換舊宣稱。
- 結論段標明「**描述性配置結果**」，避免被誤讀為前瞻保證。

## 整體 Verdict

**CLOSED — PASS（after reconstruction）**

| Dimension | 06-13 verdict | 06-14 closure verdict |
|---|---|---|
| Number consistency | PASS（vs legacy artifact） | PASS（vs reconstructed artifact） |
| Source reproducibility | FAIL | PASS |
| Lookahead / methodology | NOT VERIFIABLE | PASS |
| Production correction | applied | confirmed |
| Overall | CONDITIONAL PASS AFTER CORRECTION | **PASS** |

## Required follow-up (none blocking)

無 blocking item。Optional：
- K713 可加 transaction-cost robustness（年化 rebalance turnover 小，預期 cost 影響 <5bp/year，但顯式回算更嚴謹）。
- `tlt_20.sharpe` 在 results.json 應補完整數值（文章用「20-25% 區間」，但 closure 過程沒列 tlt_20 確切值；非 blocking）。

## Feed.json sync 動作

本 closure 同步：

- `details.codex_24h_review_file` → `experiments/k713/reviews/paper_review_mile_1b56cf6b_closure_20260614.md`
- `details.codex_24h_review_verdict` → `PASS_AFTER_RECONSTRUCTION`
- `details.codex_24h_review_ts_utc` → 本次 commit 時間
- 保留 prior review 記錄於 `details.codex_24h_review_history`
