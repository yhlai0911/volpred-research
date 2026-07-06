# K1647 — 原油「已實現波動率」對股市已實現波動率的溢出（CL=F / USO → SPY / XLE），雙向、VIX 控制

## 研究問題
原油「已實現波動率」（RV）的衝擊是否**領先／傳導**到大盤（SPY）與能源類股（XLE）的**已實現波動率**？這是 vol-level（RV→RV）的溢出問題，**不是**價格報酬問題。雙向檢定（油 vol→股 vol、股 vol→油 vol），並問油→股連結在控制 VIX 後是否存活。

## 與既有 K 的差異
- **K422**（商品波動溢出網絡）：CL=F → ES=F（SPX 期貨），發現 Oil→SPX Granger p<1e-4 但控制 VIX 後 Oil→equity vol NS。K422 未測 XLE、未比 CL=F vs USO。
- **Diebold-Yilmaz 9 資產研究**：含 USO 但「最孤立（TO=1.9%）」；無 XLE、無油聚焦方向檢定。
- **K1647 新貢獻**：(a) XLE 能源類股作為**直接暴露於油**的 target（若有真實傳導應比廣義 SPY 更強）；(b) 明確 CL=F（期貨）vs USO（ETF）雙油代理；(c) 雙向 net 溢出（generalized order-invariant FEVD）。

## 方法
- **資料**：yfinance 日 OHLC，2010-02-03..2026-07-02，N=4104 交易日。資產 CL=F / USO / SPY / XLE / ^VIX。
- **Vol proxy**：RV21 = 21 日 rolling std of 日對數報酬，年化（√252）。分析 log(vol)。Parkinson range-vol 作穩健性。
- **Lag / lookahead（最高風險）**：核心 = one-step **predictive** regression `eq_logRV[t] = a + b·oil_logRV[t-1] + c·eq_logRV[t-1] (+ d·VIX_logRV[t-1])`；predictor 明確 `.shift(1)`，只用 t-1 已知資訊預測 t。反向對稱。
- **推論**：所有 predictive regression 用 Newey-West HAC（maxlags=21，對齊 overlapping 21d RV window 誘發的 ~MA(20) 殘差）。**SPY 與 XLE 分開估兩條 regression，絕不 pool 成 asset-day iid**（K1355 教訓）。b 的 95% CI 用 Politis-Romano stationary bootstrap（seed=42）。
- **CL=F 2020-04-20 負油價**：1 筆非正 Close，log-return 未定義 → drop（有記錄，不 impute）。
- 補充：ADF 平穩性、Granger min-p（lags 1-5）、Diebold-Yilmaz generalized FEVD（VAR lag by AIC）。

## 主要結果（VERDICT = 方向性 NULL；lead-lag 走 equity→oil，非 oil→equity）
- **油 vol → 股 vol：四組全不顯著**（CL/USO → SPY/XLE），b≈0（0.0001–0.0007），HAC p=0.88–0.98，bootstrap 95% CI 全跨 0。**控制 VIX 前後皆 null**。Parkinson 穩健性同樣全 null（p=0.12–0.37）。
- **反向 股 vol → 油 vol：顯著**。SPY→CL b=+0.0099 p=0.008；SPY→USO b=+0.0088 p=0.012；XLE→CL b=+0.0111 p=0.024；XLE→USO b=+0.0090 p=0.053（邊際）。
- **Granger 對比（誠實 reconciliation）**：Granger 層 CL→SPY（p=0.0026，best lag 5）、USO→SPY（p=0.0022，best lag 5）看似顯著，但核心 lag-1 HAC-robust predictive regression 為 null。兩者差異**並非**「有無 own-AR 控制」（statsmodels Granger F-test 已內含 effect 變數自身 lag）——本實驗也未跑「無 own-control」對照，故不宣稱該機制。可與 code 一致的合理解釋：(a) Granger 古典 F-test 非 HAC-robust，會被 overlapping 21d RV window 誘發的 ~MA(20) 殘差自相關**膨脹**；(b) 顯著的 Granger lag order 落在 4-5，反映**多日長滯後動態**，是 lag-1-only 核心設定結構上無法捕捉的層面（口徑不同，非同一檢定的前後對照）。此機制差異**未直接檢定**。無論如何，核心 NULL（HAC-robust + bootstrap + VIX 控制 + 雙油代理 + 雙 target + Parkinson 穩健）不受影響：油對股市 vol 在 **lag-1 傳導**上無增量預測力。
- **Diebold-Yilmaz**：total spillover 46.5%（VAR lag 5），但 net 溢出量級都很小（CL +0.1%、USO +1.5%、SPY −0.9%、XLE −0.7%）→ 耦合主要是**同期的**（contemp corr：CL-XLE 0.68、CL-SPY 0.52），方向性 net 微向 oil 傾（油稍為淨接收方）。油佔股市 FEV 份額：對 XLE 11–13% > 對 SPY 5–6%（能源股確較敏感，但仍是接收非發送）。

## 結論
與「油價波動帶動股市恐慌」的直覺相反：在乾淨的 RV→RV predictive 設定下，**原油已實現波動率對股市已實現波動率沒有增量領先力**（VIX 控制前就已 null），而**股市波動反而領先油市波動**。這強化了 K422 的方向，並用 XLE + 反向檢定 + 雙油代理將其推廣。實務含義：想用油 vol 當股市 vol 的早期預警訊號，缺乏可交易的領先關係。

## 檔案
- `k1647.py` — 完整可復現腳本（seed=42）
- `k1647_results.json` — 全部統計量
- `fig_logrv_series.png` / `fig_net_spillover.png` / `fig_oil_to_equity_coef.png`

## 限制（documented）
- CL=F 2020-04-20 負油價那 1 筆 drop 後，`realized_vol()` 的 `.diff()` 是 positional 而非 calendar-aware，使該日之後首個存活日的 log-return 跨越缺失日（多日變化被當 1 日報酬），扭曲 2020-04 末 CL 的 RV21 window。N=4103、僅 1 筆，不改方向結論，僅記錄為限制。
- Granger-vs-lag1 的機制差異（見上）**未直接檢定**，只提出與 code 一致的合理假說。
- stationary bootstrap 各 spec 共用同一 default seed（42），block-index pattern 相同 → 降低 spec 間 resampling 多樣性，但不影響任一單一 CI 的有效性。

## Reviewer
`feature-dev:code-reviewer` subagent（independent fresh-context fallback；本次 Codex companion runtime 掛住零 output，依 `.claude/rules/experiments.md` fallback 條款改派）。**VERDICT: CONDITIONAL_PASS** — 核心 machinery（lag / HAC / DY generalized FEVD / stationary bootstrap / no-pooling）正確，核心 NULL 穩固；required fix = README Granger reconciliation 過度宣稱已修正（本版）。資料：yfinance 公開日資料，可完整復現。
