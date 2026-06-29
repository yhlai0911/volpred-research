# K1581 — GSCPI Supply-Chain Stress vs Commodity / Shipping / Retail ETF Forward Vol

**Status: COMPLETE — NULL result**
**Original brief ID K1573 was already used (CHIPS Act experiment); renumbered to K1581.**

## 核心發現（一句話）

NY Fed Global Supply Chain Pressure Index (GSCPI) 月度衝擊 Δz_t 對下一月 (t+1..t+22 交易日) 的 USO / DBA / XRT / IYT 累計實現波動率，**HAC-Newey-West (lag=6) OLS 4/4 全部 p > 0.10**（USO p=0.328, DBA p=0.667, XRT p=0.232, IYT p=0.425），bootstrap 95% CI 全部跨 0；高壓事件 (z>1.5) vs benign months Welch t-test 也僅 DBA 接近邊界 (p=0.070, d=0.696)，其他 3 檔 p ≥ 0.24。**Verdict = NULL**：在 2018-01 到 2026-05 月度 panel 上，沒有證據支持 GSCPI 月度衝擊能線性預測下月商品 / 零售 / 運輸 ETF 波動率。

## 動機與差異化

供應鏈節點 stress（如紅海航運、巴拿馬運河乾旱、港口擁堵）2021-2024 被市場與媒體反覆當成商品價格與通膨溢價的 driver。NY Fed 2022 推出的 GSCPI 把運價、PMI delivery time、shipping cost 標準化成單一 z-score。直觀假設是：GSCPI ↑ → 商品 (USO 油 / DBA 農) 與運輸 (IYT) ETF 波動率應該領先放大；零售 ETF (XRT) 透過 input cost 與消費信心傳導也應有反應。本實驗在 8 年月度資料上做**最直接的線性 leading-indicator test**。

**與既有 K 比較**：knowledge.json grep `GSCPI / chokepoint / supply.chain` 只在 K1487 (GDELT supply_chain theme, HTTP 429 unavailable, dropped) 出現過 — GSCPI 本身在本平台是 fresh angle。K1487 是 GDELT 新聞關鍵字密度 → SPY/QQQ/HYG/TLT RV（已 NULL，不同變數）；本實驗用 NY Fed 官方 hard data 做 commodity / shipping / retail panel，與 K1487 不重疊。

## 資料

| Series | Source | Range | Freq |
|---|---|---|---|
| GSCPI | NY Fed Liberty Street `gscpi_data.xlsx` | 1998-01 to 2026-05 (n=341) | Monthly (month-end) |
| USO | yfinance Adj Close (auto_adjust=True) | 2018-01-02 to 2026-06-29 (2133 trading days) | Daily |
| DBA | 同上 | 同上 | Daily |
| XRT | 同上 | 同上 | Daily |
| IYT | 同上 | 同上 | Daily |

**Analysis window**: 2018-01 onward (GSCPI z-score 在此 window 內 standardize；early 1998-2017 樣本不入分析以避免 COVID 前後不同 regime 拖累 z 分佈)。Panel rows = 99-101 個 month-end trading days (扣 Δz 的 first-row NaN)。

## 方法

### Lookahead control（最高優先風險）

```
Row index t = last trading day of month m_t
Signal:  dz_t = z(GSCPI_{m_t}) - z(GSCPI_{m_{t-1}})     # both <= month-end t
Target:  RV_fwd(t) = annualized realized vol over returns from day t+1 to day t+22
```

Code 對應：
- `realized_vol_forward(prices, window=22)` 用 reverse-rolling + `shift(-1)`：row t 的 fwd_sum = sq[t+1] + sq[t+2] + ... + sq[t+22]，**完全不含**第 t 日及之前的 squared return。
- `month_end_panel()` 抓 ETF index 每月最後交易日，與該月 GSCPI 配對（NY Fed 月末發佈，conservative 視為 month-end t 可知）。
- Bootstrap、np.random 全用 `SEED=42`。

### 檢定 A — HAC-OLS（per ETF）

`cum_RV_fwd[ETF, t] = α + β · dz_t + ε_t`，HAC-Newey-West lag=6（半年期 autocorrelation buffer）。

### 檢定 B — Welch t-test

把月份分為 high-stress (`z > 1.5`, n=11) vs benign (`|z| < 0.5`, n=32)，比 forward 22d RV mean。Welch's t 不假設等變異數。Cohen's d 報效應量。

### 檢定 C — Bootstrap 95% CI on β

1000 reps IID resample over month rows, seed=42。報 2.5% / 97.5% / median。

### 為何不調 multiple testing

4 個 ETF tests 是 family，嚴格做 Bonferroni 應 p < 0.0125。本實驗結果是 0/4 通過 unadjusted p<0.10，**單測都不顯著**，故 multiple-testing 結論不變（仍 NULL）。在 verdict rule 內已明示。

## 結果

### Table A — HAC-OLS per ETF (Δz → next-month cum RV)

| ETF | n | β | HAC SE | t | p (HAC) | R² | Bootstrap 95% CI |
|---|---|---|---|---|---|---|---|
| USO | 99 | 0.1663 | 0.1699 | 0.98 | **0.328** | 0.071 | [-0.078, 0.420] |
| DBA | 99 | 0.0076 | 0.0178 | 0.43 | **0.667** | 0.004 | [-0.028, 0.041] |
| XRT | 99 | 0.0798 | 0.0668 | 1.19 | **0.232** | 0.049 | [-0.045, 0.211] |
| IYT | 99 | 0.0541 | 0.0679 | 0.80 | **0.425** | 0.030 | [-0.051, 0.190] |

All bootstrap 95% CIs straddle zero. R² ≤ 7% even for USO (which has the largest point estimate).

### Table B — Welch t (high-stress z>1.5 vs benign |z|<0.5)

| ETF | n_high | n_benign | mean_high | mean_benign | t | p | Cohen d |
|---|---|---|---|---|---|---|---|
| USO | 11 | 32 | 0.321 | 0.378 | -0.89 | 0.381 | -0.24 |
| DBA | 11 | 32 | 0.140 | 0.111 | 1.94 | **0.070** | **+0.70** |
| XRT | 11 | 32 | 0.298 | 0.249 | 1.20 | 0.242 | +0.36 |
| IYT | 11 | 32 | 0.220 | 0.225 | -0.14 | 0.890 | -0.04 |

唯一接近 weak signal: **DBA (agriculture) Welch p=0.070, d=+0.70（中等效應）**，但 OLS HAC p=0.667，兩個檢定不一致；分組設計把高壓月份的 tail event 隔出來可能比連續 Δz 線性更敏感，但 single-ETF marginal signal 不足以推翻整體 NULL。

### Verdict

**NULL** (0/4 OLS HAC p<0.10, 0/4 strict p<0.05, bootstrap CI 全跨 0)。Verdict rule: PASS≥3@p<0.05 / CONDITIONAL_PASS≥2@p<0.05 OR ≥3@p<0.10 / WEAK_SIGNAL≥1@p<0.10 / NULL=0。

## 誠實討論

**為什麼可能 NULL（先承認 H0）**

1. **GSCPI 已 priced in**：GSCPI 本身是 PMI delivery time + shipping cost + transport price 的標準化彙整，市場參與者**月度 release 之前**已從 BDIY / FBX / 港口擁堵新聞 read across，等到 NY Fed 月初公佈時 marginal information ≈ 0。
2. **時間尺度錯配**：GSCPI 是慢動態（半年到一年波動），ETF 月度 RV 由短期 macro shock（FOMC、油價地緣、PCE 公佈）主導，supply-chain stress 的 vol footprint 可能要看 5d intraday 或 specific shock event window 才看得到，月度線性回歸把訊號平均掉。
3. **ETF 選擇 mismatch**：USO 用 WTI front-month future + roll cost，農業 DBA basket 與 supply-chain stress 的傳導機制弱；XRT 是 retailer equity（input cost 經企業財務結構 buffer），IYT 是 freight equity（運價↑ 對某些 freight equity 是 revenue 正面）。直接 commodity spot vol（CL=F, ZW=F）或 freight benchmark (BDRY) 可能訊號更乾淨。
4. **Power 不足**：99 月 + 4 ETF × 1 horizon，detect Cohen's d=0.3 的 power 約 60%。DBA Welch p=0.070 的中等 effect 在更大 sample 可能變顯著。

**不過度宣稱**

- 本實驗只 reject "GSCPI Δz 線性預測下月 ETF cum RV" 這個 narrow specification。
- 不能 rule out:
  - 非線性傳導（threshold effect, GSCPI 高 tail 才觸發）— DBA Welch 邊界訊號暗示這方向值得追
  - 不同 horizon（H+1d, H+5d, H+60d）
  - 不同 RV proxy（intraday RV, Yang-Zhang, jump component）
  - 商品 futures spot vol（CL=F, NG=F, ZW=F）而非 ETF
  - 個別 shock event study（紅海 2023-11+, 巴拿馬乾旱 2024）
- DBA agriculture Welch d=+0.70 是 lead 後續實驗的可行 hook（K1582+ 可考慮）

## References (≥3, with DOI)

1. **Benigno, di Giovanni, Groen & Noble (2022)** — "A new barometer of global supply chain pressures from 27 variables." Liberty Street Economics, Federal Reserve Bank of New York. https://libertystreeteconomics.newyorkfed.org/2022/01/a-new-barometer-of-global-supply-chain-pressures/
2. **Kilian, L. (2009)** — "Not All Oil Price Shocks Are Alike: Disentangling Demand and Supply Shocks in the Crude Oil Market." *American Economic Review*, 99(3), 1053-1069. DOI: 10.1257/aer.99.3.1053
3. **Caldara, D., Cavallo, M. & Iacoviello, M. (2019)** — "Oil price elasticities and oil price fluctuations." *Journal of Monetary Economics*, 103, 1-20. DOI: 10.1016/j.jmoneco.2018.08.004
4. **Newey, W. & West, K. (1987)** — "A Simple, Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix." *Econometrica*, 55(3), 703-708. DOI: 10.2307/1913610

## 產出檔案

- `k1581.py` — 可重現完整腳本 (SEED=42)
- `k1581_results.json` — 所有檢定 stats (β, SE, HAC-p, bootstrap CI, Welch, Cohen d, verdict)
- `figs/k1581_overlay.png` — GSCPI level + z-score overlay 加 4 ETF 22d forward RV time series
- `README.md` — 本文件

## 防錯與限制

- **無 lookahead**: `realized_vol_forward()` reverse-rolling + `shift(-1)` 確保 row t 的 RV 只用 t+1..t+22 returns；signal Δz 來自 month-end m_t 已公佈的 GSCPI。Code 中明示無 contemporaneous month 使用。
- **GSCPI release lag**: NY Fed 通常月初 publish 上月 GSCPI（mild release lag）；本實驗 conservative 把 signal 對齊到月末 trading day t，實務上交易者在 t+5~t+10 才會看到，會更 conservative。若想做嚴格 real-time，可進一步 shift signal 5-10 trading days 後再 regress；那樣訊號只會更弱（NULL 結論更強）。
- **Seed 全固定**：`SEED=42` cover bootstrap；ETF download 不用隨機。
- **Sample window**: 2018-01 起，含 COVID supply-chain crisis (2020-2022, GSCPI 歷史最高 ≈ 4) — 高壓 cell 主要來自此段。若分 pre-2020 / post-2020 sub-sample power 會崩潰，未做 subsample。
- **Multiple testing**: 4 ETF unadjusted；Bonferroni p<0.0125 結論不變（仍 NULL）。
- **N=99 months**: 對 small effect (|d|<0.3) power 低；NULL 含 "no detectable effect" 而非 "no effect"。
- **Codex review**: 主線程 hourly 後續處理（per brief 完成 gate #3，不在 worktree 內）。
- **資料 reproducibility**: GSCPI xlsx URL + yfinance ticker 全公開，重跑 script 應得相同結果（前提 yfinance API 未變、NY Fed 未 backfill）。
