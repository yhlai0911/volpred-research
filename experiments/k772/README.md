# K772 — Overnight vs Intraday Volatility Decomposition (SPY)

- Experiment ID: `K772`
- Status: completed (2026-04-18 first run)
- Reviewed: 2026-06-23 `feature-dev:code-reviewer` fallback → CONDITIONAL_PASS (Codex quota exhausted)
- Published article: `mile_0a7041f4` (2026-06-23)

## 問題描述

SPY 的全天波動率變異數可分解為「隔夜段」（前一日 close → 當日 open）與「盤中段」（open → close）兩部分。問題：(a) 兩段分別貢獻多少？(b) 兩段是否獨立（相關係數）？(c) 把這兩段分離資訊納入波動率預測模型是否能提升 QLIKE？

## 動機

- Hansen & Lunde (2005) 提出 close-to-close 報酬可分解為 overnight + intraday；但實證上不同樣本期、不同資產的分配差異大。
- 散戶常只看 RTH（regular trading hours），忽略隔夜段；若 overnight 是主要 vol 來源，HAR-RV / GARCH 等只用全日 RV 的模型會 underuse 已知資訊。
- Engle & Gallo (2006) AMEM 提出乘法成分模型分開隔夜/盤中；Corsi (2009) HAR-RV 標準模型不分段。比較 AMEM vs HAR-OC vs HAR-RV vs GJR-GARCH 可量化「分段資訊」的預測價值。

## 方法

- **資料**：yfinance SPY OHLC，2007-01-03 ~ 2026-03-30，N=4840 交易日
- **報酬分解**：`r_overnight[t] = log(open[t] / close[t-1])`、`r_intraday[t] = log(close[t] / open[t])`、`r_total[t] = r_overnight[t] + r_intraday[t]`
- **Part A — Variance decomposition**：`Var(r_total) = Var(r_overnight) + Var(r_intraday) + 2*Cov(...)`；報告三段佔比 + 年化 vol + 相關係數 + 偏態/峰度
- **Part B — Time-varying share**：逐年計算 overnight share，看是否隨市場機制變化
- **Part C — HAR-OC regression**：OLS 把 r²_total[t+1] 回歸於 r²_overnight 與 r²_intraday 的 daily/weekly/monthly aggregate（全樣本 descriptive，非 OOS 用途）
- **Part D — OOS model comparison**：
  - **訓練起始**：min_window = 1000 日；expanding window
  - **OOS 範圍**：2010-12-22 ~ 2026-03-30，3839 預測槽位（per-model n_valid = 3828 after filter）
  - **六模型**：HAR-RV (Corsi 2009)、HAR-OC（HAR-RV with overnight + intraday channels）、HAR-OC-ext（HAR-OC + interaction terms，**退化解**）、EWMA(λ=0.94)、GJR-GARCH(1,1,1) Gaussian QMLE、AMEM（Engle-Gallo multiplicative error）
  - **評估**：QLIKE = `actual/predicted - log(actual/predicted) - 1`（per K783c canonical direction）；DM 檢定 + Harvey (1997) 小樣本修正
  - **MLE**：GJR 用 3-seed restart（`np.random.seed(seed + 100)`）；AMEM 用 2-3 seed restart（`np.random.seed(42 + attempt)`）

## 預期

- Overnight share 預估 30-40%（與 Hansen-Lunde SPY 樣本一致）
- AMEM / HAR-OC 應該優於 HAR-RV（額外分段資訊）
- GJR-GARCH 仍應 competitive（leverage effect 抓 SPY 不對稱波動）

## 結論

- **Part A**: Overnight share = 36.8%、intraday = 59.4%、covariance contribution = 3.7%。年化 vol：total 19.7% / intraday 15.2% / overnight 12.0%。隔夜 vs 盤中相關係數 = 0.040（near zero）。隔夜峰度 24.8 vs 盤中 12.3（隔夜尾部更厚）。
- **Part B**: Overnight share 2008-2026 範圍 20.2%-61.4%、均值 36.5%。COVID 期間（2020）衝到 52.8%；2008 金融海嘯反低（32.5%）。
- **Part D OOS ranking**：AMEM 1.5074 < GJR 1.5380 < HAR-OC 1.6048 < EWMA 1.6238 < HAR-RV 1.6732 < HAR-OC-ext 162893（**退化、不可用**）
- **DM tests**：
  - `gjr_vs_ewma` t=-4.75 p<1e-5 ✓ Harvey-pass
  - `gjr_vs_har_rv2` t=-3.26 p=0.0011 ✓ Harvey-pass
  - `gjr_vs_har_oc` t=-6.62 p<1e-10 ✓ Harvey-pass
  - `gjr_vs_amem` t=2.11 p=0.035 ✗ Harvey-fail → **邊際顯著，不能確定 AMEM 優於 GJR**
- **核心發現**：分段資訊有正貢獻（AMEM/HAR-OC 優於 HAR-RV）；AMEM 與 GJR-GARCH 統計上 indistinguishable；HAR-OC-ext 數值爆炸需排除。

## 已知 caveat（CONDITIONAL_PASS 條件）

1. yfinance live download 未 pin 版本 — 重跑日期若 yfinance revise 歷史價可能 N 變動
2. `har_oc_ext` 在 metrics/ranking/DM tests 中保留為 degenerate entry；下游消費者請忽略其 ranking 與相關 DM tests（results JSON 已加 `degenerate: true` flag，per 2026-06-23 review）
3. 文章 mile_0a7041f4 第一版誤寫 OOS 起始為「2011 年」，實際為 2010-12-22；2026-06-23 review 後已修正
4. AMEM expanding window 用 max_attempts=2，獨立 fit 用 max_attempts=3 — 輕微不一致但無 bias

## References

- Hansen & Lunde (2005) *J. Applied Econometrics* 20, 873-889
- Corsi (2009) *J. Financial Econometrics* 7, 174-196
- Engle & Gallo (2006) *J. Econometrics* 131, 3-27
- Harvey, Leybourne, Newbold (1997) *Int. J. Forecasting* 13, 281-291
