# K1663 — 已實現共變異數 HAR → 最小變異組合的樣本外檢定

**Verdict: NULL / 負面（對 HAR-RCov 而言）** — 在日頻可得資料下，對共變異數矩陣做 HAR
（Cholesky-HAR）建構的 GMV 組合，**打不贏簡單強 baseline**：EWMA(RiskMetrics) 在樣本外
已實現波動上**顯著較低**，Ledoit-Wolf shrinkage 則以幾乎相同的波動、**換手率低 18 倍**
取得壓倒性的實務優勢。HAR-Cholesky 只贏過它自己的建構原料（naive 22 日 rolling cov），
沒有增量價值。此結果與庫內先驗（K444 / K737 / K1028）完全一致。

- **實驗類型**：experiment（多變量共變異數預測 → 組合構建）
- **資料**：yfinance 日資料，`SPY, QQQ, GLD, TLT, IWM`（5 檔），2004-11-19 ~ 2026-07-08
- **樣本外**：2007-11-21 ~ 2026-07-08，**4,684 個 OOS 交易日**（含 2008 GFC、2020 COVID、2022 熊市）
- **seed**：20260709（OLS / Ledoit-Wolf 皆 deterministic，seed 為防禦性固定）
- **審查**：主線程負責 Codex / reviewer 審查（本 worktree agent 禁寫 knowledge.json）；
  另已於 worktree 內跑一次 `feature-dev:code-reviewer` 獨立 lookahead 稽核（見下方「審查」節）。

---

## 1. 動機與差異化

庫內波動率研究**幾乎全是單變量**（單資產 GARCH/HAR-RV/VaR）。少數多變量工作
（K444 DCC、K1028 DCC-A4f、K1041 DCC-A4f VaR、K157/K737 組合構建）反覆得到同一個
教訓：**動態共變異數在組合層常打不贏簡單 baseline**（EWMA、CCC、1/N），除非相關性
本身變動很大（K1041 SPY/GLD VaR 是唯一例外）。

本實驗補上一塊新拼圖：**直接對「realized covariance 矩陣」做 HAR**（而非對邊際波動 +
相關性分開建模），比對它在 **GMV（全域最小變異）組合**的樣本外表現。動機是若 HAR-RCov
有效，可上架成「組合構建產品」（直接的 monetization 貢獻）。結果誠實地是 NULL。

---

## 2. 資料

| 項目 | 內容 |
|---|---|
| 來源 | yfinance（`auto_adjust=True` 調整後收盤），快取於 `data/prices.csv` |
| 資產 | SPY（美股大盤）、QQQ（那斯達克）、GLD（黃金）、TLT（20年期美債）、IWM（小型股） |
| 期間 | 2004-11-19 ~ 2026-07-08（GLD 上市日 2004-11 為共同起點），5,440 個報酬日 |
| 報酬 | **簡單報酬**（`pct_change`）——組合報酬 `w·r` 唯有簡單報酬才精確 |
| OOS | burn-in 756 天（~3 年）後，OOS = 4,684 天 |

籃子跨股/債/黃金，涵蓋相關性會反轉的資產對（COVID 時 SPY/GLD 相關由正轉負），
是「動態共變異數若有用、最該顯現」的環境。

---

## 3. 方法

### 3.1 日頻 RCov proxy（誠實揭露 — 最重要的 caveat）

我們**只有日資料**，無法計算真正的高頻 realized covariance。本實驗的日頻「已實現
共變異數」是 **22 日 rolling 樣本共變異數** `RCov_t = Cov(returns[t-21 .. t])`：

- 這是一個**有雜訊、被平滑過的 proxy**，**不是** intraday realized covariance。
- 測量誤差大（HARQ-style 疑慮：Bollerslev-Patton-Quaedvlieg 2016 指出 RV 測量誤差會
  衰減 HAR 係數）。
- 因此本實驗定位為 **「日頻可得資料下的共變異數構建方法比較」**，**不宣稱**等同
  Chiriac-Voev(2011) 等高頻 realized-covariance-HAR 文獻的結果。

選 22 日 rolling cov 而非日報酬外積 `r_t r_t'` 的原因：外積是 rank-1 奇異矩陣，無法做
Cholesky 分解；22 日窗（>5 檔資產）保證正定，Cholesky-HAR 才能乾淨實作。

### 3.2 HAR-Cholesky 模型（保證正定的參數化）

對每日 `RCov_t` 做 Cholesky 分解 `RCov_t = L_t L_t'`（下三角），取其
`N(N+1)/2 = 15` 個自由元素向量 `c_t`。對**每個** Cholesky 元素做標準 Corsi(2009) HAR：

```
c_{t,k} = β0 + βd · c_{t-1,k} + βw · mean(c_{t-5..t-1,k}) + βm · mean(c_{t-22..t-1,k}) + ε
```

（日 / 週 / 月三個 lag，全部嚴格落後）。預測 `ĉ_{t}` 後重組
`L̂_t` → `Σ̂_t = L̂_t L̂_t'`，**結構性保證正定**（對角線設下限 `1e-5` 防退化）。
係數以 **expanding window** 每 21 個交易日重估一次（`np.linalg.lstsq` OLS）。

> 為何選 Cholesky 而非 matrix-log：兩者都能保證 PD；Cholesky 對 rank-1/近奇異更穩健，
> 且是 Chiriac-Voev(2011) 的 canonical 選擇。任務允許二擇一。

### 3.3 Benchmark 共變異數估計（全部只用 ≤ t-1 資訊）

| 方法 | 定義 |
|---|---|
| **Rolling sample cov (22d)** | `Σ̂_t = RCov_{t-1}`（即 HAR 的建構原料，RCov 的 random-walk 預測） |
| **EWMA (RiskMetrics)** | `Σ_t = λ Σ_{t-1} + (1-λ) r_t r_t'`，λ=0.94，遞迴、causal |
| **Ledoit-Wolf shrinkage** | `sklearn.covariance.LedoitWolf`，252 日窗，往結構化 target 收縮 |

另加 **1/N 等權**組合作為 DeMiguel(2009) 參考錨（非共變異數方法，只列 metrics）。

### 3.4 GMV 組合

- **允許放空**（主要）：`w = Σ⁻¹1 / (1'Σ⁻¹1)`（closed-form）。
- **不允許放空**（robustness）：`min w'Σw  s.t.  1'w=1, w≥0`，scipy SLSQP。

### 3.5 Lookahead 防線（最高優先風險）

| 防線 | 實作位置 |
|---|---|
| 組合日 `t` 的權重只用 origin `τ = t-1` 的資訊 | `build_forecasts` 迴圈 `tau = t - 1` |
| HAR 特徵 `Xd/Xw/Xm` 全 `shift(1)` → 只含 ≤ t-1 | `har_features()` |
| HAR betas 訓練列 `s ≤ τ`，預測目標 `c_t` 從不進訓練集 | `train = valid_rows[valid_rows <= tau]` |
| rolling / ewma / LW 的窗尾都 = τ（不含 t） | `rcov[tau]` / `ewma_path[tau]` / `R[tau-LW_WIN+1:tau+1]` |
| 權重 `w`（來自 ≤t-1 的 Σ）實現於**當日** `R[t]` → 明確一日 lag | `run_portfolio`：`w @ R[t]` |
| baseline 與 HAR **同一 lag 慣例**（全部 ≤ t-1） | 同上，統一在 `build_forecasts` |

> **反 lookahead 的實證訊號**：若有前視偏誤洩漏未來資訊，HAR 會「看起來太好」。
> 實際上 HAR **輸給** EWMA、Sharpe 僅 ~1.0（不誇張）、GMV 波動（8.5-9%）合理地低於
> 等權（13%）—— 這些都與「無 lookahead」一致。

### 3.6 評估與檢定

- **主要目標**：GMV 樣本外**年化已實現波動率**（越低越好，GMV 的目標函數）。
- **換手率**：`mean(Σ|w_t − w_{t-1}|)`（每日平均）。
- **Sharpe**（次要）：GMV 不以報酬為目標，勿過度解讀。
- **統計檢定 — Diebold-Mariano（Engle-Colacito 2006 口徑）**：
  loss = **GMV 組合日報酬平方** `p_t²`（GMV 最小化組合變異，故 `E[p²]` 越低 = 共變異數
  預測越好）。這是**單一組合時間序列**，直接對 loss differential 做 DM，
  **不涉及 asset-day pooling**（避開 K1355 的 iid 陷阱）。HAC 用 Newey-West（Bartlett
  kernel，自動 bandwidth）+ Harvey-Leybourne-Newbold 小樣本修正、t 分佈臨界值。
  符號慣例：**負 DM = HAR 較佳**。

---

## 4. 結果

### 4.1 樣本外 GMV 表現（允許放空，主要）

| 方法 | 年化已實現波動 | 換手率 Σ\|Δw\| | Sharpe | max w | min w |
|---|---:|---:|---:|---:|---:|
| HAR-Cholesky | 9.028% | 0.2685 | 1.016 | 3.12 | −1.86 |
| Rolling 22d | 9.065% | 0.2697 | 1.007 | 3.15 | −1.91 |
| **EWMA 0.94** | **8.578%** | 0.1680 | 1.034 | 2.43 | −1.36 |
| **Ledoit-Wolf** | 8.922% | **0.0149** | 1.008 | 1.01 | −0.40 |
| 1/N 等權 | 13.165% | 0.0000 | 0.847 | 0.20 | 0.20 |

### 4.2 DM 檢定（Engle-Colacito；HAR vs baseline，負 = HAR 較佳）

| 對比 | DM stat | p-value | 結論 |
|---|---:|---:|---|
| HAR vs Rolling 22d | **−5.23** | <0.001 | HAR 顯著較佳（贏過自己的原料） |
| HAR vs EWMA | **+7.69** | <0.001 | **EWMA 顯著較佳** |
| HAR vs Ledoit-Wolf | +0.86 | 0.392 | 打平（NS） |

### 4.3 不允許放空（robustness，結論一致）

| 方法 | 年化波動 | 換手率 | Sharpe |
|---|---:|---:|---:|
| HAR-Cholesky | 9.093% | 0.1155 | 1.063 |
| Rolling 22d | 9.106% | 0.1153 | 1.061 |
| **EWMA 0.94** | **8.840%** | 0.0778 | 1.099 |
| Ledoit-Wolf | 9.173% | **0.0097** | 1.008 |
| 1/N 等權 | 13.165% | 0.0000 | 0.847 |

DM（no-short）：HAR vs Rolling **−2.90 (p=0.004)**；HAR vs EWMA **+6.70 (p<0.001)**；
HAR vs LW +（NS）。**兩種約束下結論相同**。

### 4.4 圖表

- `K1663_gmv_vol_turnover.png` — 各法 GMV 年化波動（左）+ 換手率（右）長條圖。
- `K1663_gmv_rolling_vol.png` — HAR / EWMA / LW 的 rolling 63 日年化波動時序（標示 GFC /
  COVID / 2022 壓力窗，EWMA 全程最低）。

---

## 5. 解讀

1. **HAR-RCov 沒有增量價值**：它只贏過 naive rolling-22（它自己的建構原料，等於「HAR
   加權歷史 vs 只用最後一窗」的差異），卻**輸給 EWMA**、**與 Ledoit-Wolf 打平**。
   HAR 的日係數主導 → 預測 ≈ 平滑後的 rolling cov，無法勝過設計更好的估計量。
2. **EWMA 是波動贏家**：λ=0.94（half-life ~11 天）對日頻雜訊的指數加權，比 HAR 的
   日/週/月固定結構更能追蹤共變異數的短期變化。
3. **Ledoit-Wolf 是實務贏家**：以幾乎相同的波動，換手率只有 HAR 的 **1/18**（0.0149 vs
   0.2685）。GMV 對估計誤差極敏感（權重可到 +3.1 / −1.9 的極端槓桿），shrinkage 把
   權重壓到合理範圍（max 1.01 / min −0.40），交易成本上碾壓所有方法。
4. **GMV vs 1/N**：所有共變異數方法都把波動從等權的 13.2% 壓到 8.5-9.2%（GMV 確實有效），
   但這是**共變異數建模的普遍好處**，不是 HAR 的功勞。DeMiguel(2009) 的 1/N 挑戰在此
   籃子/期間**不成立**（GMV 明顯降波動），但**方法間的差異**才是本實驗的問題，
   而 HAR 在其中墊底。
5. **為何 daily proxy 讓 HAR 難贏**：22 日 rolling cov 已是平滑估計，對它再套 HAR 幾乎
   是「平滑的平滑」；加上日頻 RCov 測量誤差大，HAR 能榨取的額外可預測結構有限。真正的
   高頻 RCov（若有 intraday 資料）測量誤差小得多，HAR 可能有機會——但那不在本實驗
   可得資料範圍內（誠實 caveat）。

---

## 6. 關鍵 caveat

- **Daily RCov proxy 雜訊大**：22 日 rolling cov ≠ 高頻 realized covariance；本結論**只**
  適用於日頻可得資料，不可外推到 intraday RCov 文獻。
- **無交易成本淨化的績效**：波動與 Sharpe 未扣交易成本；一旦計入成本，Ledoit-Wolf 的
  超低換手會讓它的實務優勢**更大**，HAR 的劣勢更明顯。
- **單一籃子/單一 rebalance 頻率**：5 檔美國流動 ETF、每日再平衡；不同籃子（如高相關股票
  對）或月頻再平衡可能改變 HAR 相對優劣（K1028 提示相關性穩定時動態模型無用）。
- **EWMA λ、LW 窗、HAR refit 頻率未做敏感度掃描**：用文獻標準值（λ=0.94、252d、月頻
  refit），非為本資料優化——這對 baseline 反而保守（未 cherry-pick）。

---

## 7. 文獻

1. **Corsi, F. (2009)**. A Simple Approximate Long-Memory Model of Realized Volatility.
   *Journal of Financial Econometrics* 7(2), 174–196. — HAR 模型原型（日/週/月異質成分）。
2. **Chiriac, R. & Voev, V. (2011)**. Modelling and Forecasting Multivariate Realized
   Volatility. *Journal of Applied Econometrics* 26(6), 922–947. — 以 **Cholesky 分解 +
   fractionally-integrated/HAR 動態**建模 realized covariance 保證正定，本實驗的 canonical
   方法來源。
3. **Bauer, G. H. & Vorkink, K. (2011)**. Forecasting multivariate realized stock market
   volatility. *Journal of Econometrics* 160(1), 93–101. — **matrix-log** 參數化建模
   realized covariance（本實驗選 Cholesky 的替代路線）。
4. **Engle, R. F. & Colacito, R. (2006)**. Testing and Valuing Dynamic Conditional
   Correlations for Asset Allocation. *Journal of Business & Economic Statistics* 24(2),
   238–253. — **本實驗 DM 檢定的口徑來源**：以「哪個共變異數預測產生最低 GMV/最小變異
   組合已實現變異」評比。
5. **Ledoit, O. & Wolf, M. (2004)**. Honey, I Shrunk the Sample Covariance Matrix.
   *Journal of Portfolio Management* 30(4), 110–119. — shrinkage 估計量，組合構建的
   強 baseline（本實驗的實務贏家）。
6. **DeMiguel, V., Garlappi, L. & Uppal, R. (2009)**. Optimal Versus Naive
   Diversification: How Inefficient Is the 1/N Portfolio Strategy? *Review of Financial
   Studies* 22(5), 1915–1953. — 因估計誤差，優化組合常打不贏 1/N；本實驗以 1/N 為錨。
7. **Bollerslev, T., Patton, A. J. & Quaedvlieg, R. (2016)**. Exploiting the errors: A
   simple approach for improved volatility forecasting (HARQ). *Journal of Econometrics*
   192(1), 1–18. — RV 測量誤差衰減 HAR 係數（本實驗 daily proxy 雜訊 caveat 的理論依據）。

庫內相關（proposer 對照）：**K444**（DCC vs EWMA 組合波動打平）、**K737**（1/N 難敵、
資產擴張稀釋 Sharpe）、**K1028**（相關穩定時 DCC≈CCC）、**K1041**（DCC-A4f VaR 唯一贏例）、
**K157**（相關預測改善可傳遞到 MinVar）。本 K 與前者的 NULL pattern 一致。

---

## 8. 審查

- **主線程**：負責正式 Codex / reviewer 審查後才寫 `knowledge.json`（worktree agent 禁寫）。
- **Worktree 內獨立稽核（`feature-dev:code-reviewer`，2026-07-09）**：針對 lookahead / DM /
  GMV 數學逐行稽核，**PASS — 無任何 confidence ≥80 的 lookahead 或會改變結論的 bug**。
  6 項檢查全過：四法 Sigma_hat 對齊（統一 `tau=t-1` origin）、HAR 訓練列 `s≤tau` 恆排除
  forecast target `C[t]`、DM(Newey-West+HLN) 口徑與符號慣例正確、GMV 公式正確、baseline
  與 HAR 同 lag、無 off-by-one。reviewer 明確指出「HAR 輸給 EWMA」與「無 lookahead」預期
  方向相符，支持結果可信度。
- **3 個 sub-threshold 觀察（confidence <40，皆非 issue，透明記錄）**：
  (1) EWMA 種子用前 22 日初始化 → 但 `BURN_IN=756` 使 `0.94^756 ≈ 5e-21` 完全衰減，零影響；
  (2) `dm_hln` 自相關項分母為 `(T-k)` 而非教科書 `T` → T≫L 時差異 <1%，不翻轉結論；
  (3) `RIDGE=1e-10` 偏小 → 但對四法一視同仁、不偏袒 HAR。均不改變 verdict。

## 9. 檔案

| 檔案 | 內容 |
|---|---|
| `K1663_rcov_har_gmv.py` | 可復現主腳本（seed=20260709） |
| `K1663_rcov_har_gmv_results.json` | per-method OOS vol / turnover / Sharpe / DM stat+pval / 樣本數 / 期間 |
| `plot_K1663.py` | 圖表生成 |
| `K1663_gmv_vol_turnover.png` | GMV 波動 + 換手率長條圖 |
| `K1663_gmv_rolling_vol.png` | rolling 63 日年化波動時序 |
| `data/prices.csv` | yfinance 快取價格 |
| `_series.npz` | 各法 OOS 組合報酬序列（畫圖用，非 canonical） |

**復現**：`uv run python experiments/K1663_rcov_har_gmv/K1663_rcov_har_gmv.py`
（若 `data/prices.csv` 不存在，需先用 yfinance 重抓；腳本預設讀快取）。
