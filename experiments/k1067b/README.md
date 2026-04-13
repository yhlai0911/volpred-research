# K1067b: UMC (2303.TW) Single-Stock A4f-EAV — Maximum Power Test vs K1067 TSMC

**[提出: 賴奕豪, 執行: Claude]**
**Date**: 2026-04-13
**Runtime**: 201 seconds
**Status**: Complete — **MIXED verdict** (event-window PASS, full-OOS NULL)

## 1. 問題描述（Problem）

K1067 在 TSMC (2330.TW) 上測試 A4f+EAV vs A4f baseline，結果 NULL（DM t=+0.348,
θ₂ mean=-4.5e-4, 方向為 A4f baseline 勝）。我們當時初步判定 **H_vix 主導**（VIX 已吸收
earnings 相關不確定性）。

但 K1067 的 NULL 可能**不是** H_vix 主導的證據，而是**統計功效（power）不足**：
TSMC 是 K1060 Top 4 中 T+1 amplification 最弱的（0.983），因為 TSMC 的財報**早已被市場預期**
（大量分析師覆蓋，法說會前已 price-in）。

**決定性實驗**：改做 UMC (2303.TW)——**K1060 Top 4 中 T+1 amplification 最強的（2.579）**，
方法論**完全一致**於 K1067，僅改 ticker。這樣任何差異都歸因於「UMC 的 earnings surprise
強度」，而非實作不同。

## 2. 動機（Why）— Paper 2 決定性實驗

| 若 H1 PASS (DM |t|>3) | 若 H1 FAIL + H4 PASS | 若 H1 + H4 都 FAIL |
|---------------------|----------------------|-------------------|
| K1067 NULL 是 power 問題 | UMC 有訊號但不足顯著 | H_vix 主導跨 surprise 頻譜 |
| Paper 2 可保留 EAV，但必須選高 surprise 公司 | Paper 2 只能做 descriptive event-study | Paper 2 必須移除 EAV regressor |

## 3. 研究假設（Hypotheses）

| # | 假設 | 通過標準 |
|---|------|---------|
| **H1** (主) | UMC A4f+EAV DM 顯著勝 A4f baseline | Harvey \|t\|>3.0 且方向 EAV_better |
| **H2** | θ₂ (EAV 係數) > 0 統計顯著 | One-sample t-test p<0.05 且 bootstrap CI 不含 0 |
| **H3** | 改善集中於 event window | T+1 subsample \|DM t\| > non-event \|DM t\| |
| **H4** | UMC 改善 > K1067 TSMC 改善 | `UMC improvement_pct > TSMC -0.070%`（power 假設）|

## 4. 方法（Method）

### 4.1 模型規格（與 K1067 完全一致）

**Baseline A4f**：

$$\tau_{t+1} = \max(\theta_0 + \theta_1 \cdot \text{VIX}^2_t,\ \varepsilon)$$

**Extended A4f-EAV**：

$$\tau_{t+1} = \max(\theta_0 + \theta_1 \cdot \text{VIX}^2_t + \theta_2 \cdot \text{EAV}_t,\ \varepsilon)$$

`EAV_t = 1` 當 t 日為 UMC 財報公告日，否則 `0`。台灣財報盤後公告，預測 t+1 波動——無 lookahead。

### 4.2 數據

| 資料 | 來源 | 期間 | 樣本數 |
|------|------|------|--------|
| 2303.TW daily OHLC | yfinance (auto_adjust=True) | 2010-01-05 ~ 2025-12-30 | 3911 交易日 |
| ^VIX daily Close | yfinance | 同期間 | forward-fill 對齊 |
| UMC 財報公告日 | 財報公告日.txt filter code=2303 | 2010-2025 | 64 筆 → 60 distinct 交易日 |
| OOS 期間 | | 2019-01-01 ~ 2025-12-30 | 1697 obs, 28 event days |

Max |log return| = 10.47%（與 TSMC 10.51% 相仿）。

### 4.3 估計與評估

- Rolling window = 2000, refit every 63 days (quarterly) — **與 K1067 一致**
- OOS: 1697 obs, 27 refits — **與 K1067 一致**
- Random seed = 42 — **與 K1067 一致**
- QLIKE on r² (Patton 2011), DM Harvey |t|>3.0 — **與 K1067 一致**
- θ₂ one-sample t-test + 2000-rep bootstrap CI — **與 K1067 一致**

### 4.4 前置診斷

- ADF stat = -62.15, p < 0.0001 → 定態
- ARCH-LM(10) = 181.55, p = 1.1e-33 → 顯著異質變異
- Skewness = +0.462, Kurtosis = 3.739
- In-sample corr(r², EAV_binary) = **+0.0319**（K1067 TSMC 為 -0.0011——**UMC 有更強的原始訊號**）
- Naive r²_event / r²_nonevent: T+0 = 1.130, **T+1 = 2.474**（確實接近 K1060 的 2.579）

## 5. 結果（Results）

### 5.1 主要 DM test

| 指標 | A4f baseline | A4f+EAV |
|------|-------------|---------|
| QLIKE | 1.305196 | 1.292930 |
| Spearman ρ | +0.2394 (p<0.0001) | +0.2530 (p<0.0001) |
| n_valid | 1697 | 1697 |

**DM test**: t = **-1.371**, p = 0.1704, improvement = **+0.517%**, direction = **EAV_better**

→ **H1 FAIL** — 未達 Harvey |t|>3.0 門檻，但**方向正確**（EAV 勝）、整體改善 +0.517%（K1067 TSMC 為 -0.070%）

### 5.2 θ₂ 分布（H2） — **極強的 PASS**

| 統計量 | UMC (K1067b) | TSMC (K1067) |
|--------|-------------|--------------|
| mean | **+6.599e-04** | -4.476e-04 |
| median | +6.212e-04 | +4.205e-05 |
| std | 2.223e-04 | 1.382e-03 |
| positive fraction | **1.00 (27/27 refits)** | 0.59 (16/27) |
| one-sample t (θ₂>0) | **+15.43** | -1.68 |
| one-sided p | **6.68e-15** | 0.9478 |
| Bootstrap 95% CI | **[+5.76e-04, +7.42e-04]** | [-9.87e-04, +3.58e-06] |

→ **H2 PASS (極顯著)** — UMC 的 θ₂ **所有 27 個 refits 都為正**，均值 +6.6e-4，t=15.43。
與 K1067 TSMC 的 θ₂ mean 為負且 CI 幾乎跨 0 形成強對比。

### 5.3 Event-window 分析（H3）— **PASS**

| 子樣本 | n | DM t | QLIKE improvement |
|--------|---|------|-------------------|
| **T+1 event** | 28 | **-2.204** | **+39.266%** |
| Non-event | 1669 | -0.160 | -0.106% |

→ **H3 PASS (顯著)** — event window 的 |DM t|=2.204 遠大於 non-event |DM t|=0.160。
**在 28 個 event days 上，EAV 版本 QLIKE 改善 +39.3%**（DM p=0.036，傳統 1.96 水準已達）。

這意味：**EAV 的預測價值真實存在，但只在 event window 內**。分散到全 OOS (n=1697)，
被 99% 的 non-event days 稀釋，整體 DM 難以達 Harvey 門檻。

### 5.4 H4 — UMC vs K1067 TSMC（power 假設）— **PASS**

| 對照 | T+1 amp (K1060) | DM t | improvement | θ₂ mean |
|------|----------------|------|-------------|---------|
| **UMC (K1067b)** | **2.579** | **-1.371** | **+0.517%** | **+6.6e-4** |
| TSMC (K1067) | 0.983 | +0.348 | -0.070% | -4.5e-4 |
| ETF equal (K1064) | — | +1.082 | -0.205% | — |
| ETF sector (K1064) | — | +0.959 | -0.207% | — |
| ETF top50 (K1064) | — | +2.360 | -0.419% | — |

→ **H4 PASS** — UMC 的 EAV 改善（+0.517%）**嚴格大於** TSMC 的（-0.070%）。
而且 UMC 的 DM 方向已經倒向 EAV_better（t=-1.371），而所有 ETF 和 TSMC 都傾向 A4f_better。
**這強力支持「高 T+1 amplification → 更大的 EAV 預測邊際」的 power 假設**。

### 5.5 Sub-period stability

| Period | Window | n | DM t | improvement |
|--------|--------|---|------|-------------|
| 1 | 2019-01-02 ~ 2020-06-03 | 340 | -1.412 | +1.512% |
| 2 | 2020-06-04 ~ 2021-10-22 | 340 | **+0.473** | -1.165% |
| 3 | 2021-10-25 ~ 2023-03-17 | 339 | -1.095 | +1.711% |
| 4 | 2023-03-20 ~ 2024-08-08 | 339 | -1.240 | +3.057% |
| 5 | 2024-08-09 ~ 2025-12-30 | 339 | -0.447 | +0.270% |

→ 5 個子期間中 **4/5** 都是 EAV 方向領先（DM t<0），方向相對穩定。Period 2（COVID 後半到
FED 縮表期）是唯一反向，可能對應特殊流動性事件主導波動、earnings 訊號被淹沒。

### 5.6 Lag robustness

| EAV 定義 | θ₂ | In-sample QLIKE |
|---------|-----|-----------------|
| **EAV_{t-1} (default)** | **+4.787e-04** | **1.180361** |
| EAV_{t-2} | +7.189e-05 | 1.192127 |
| EAV rolling-3d | +1.696e-04 | 1.185409 |

→ θ₂ 的**符號**在所有 lag 規格下都為正，與 K1067 TSMC 的上下浮動形成對比。
EAV_{t-1} 給出最大 θ₂ 和最低 QLIKE，確認 T+1 是主要訊號日。

## 6. K1067 vs K1067b 完整對照表

| 指標 | K1067 (TSMC) | K1067b (UMC) | 方向 |
|------|-------------|-------------|------|
| T+1 amplification (K1060) | 0.983 (weakest) | 2.579 (strongest) | — |
| In-sample corr(r², EAV) | -0.0011 | +0.0319 | UMC 強 29x |
| Full-sample T+1 ratio | 0.98 | **2.47** | UMC 強 2.5x |
| **H1 DM t** | +0.348 | **-1.371** | UMC 更強且方向對了 |
| **H1 DM p** | 0.728 | **0.170** | UMC 更接近顯著 |
| QLIKE improvement % | -0.070% | **+0.517%** | UMC 正 |
| **H2 θ₂ mean** | -4.5e-4 | **+6.6e-4** | 符號翻轉 |
| **H2 θ₂ positive fraction** | 0.59 | **1.00** | 100% 正 |
| **H2 one-sample t** | -1.68 | **+15.43** | 翻轉 |
| **H2 one-sided p** | 0.948 | **6.7e-15** | 極顯著 |
| **H3 event DM t** | +0.083 | **-2.204** | 事件窗大幅翻轉 |
| **H3 event improvement %** | -0.249% | **+39.27%** | UMC 大幅改善 |
| **H4 verdict** | n/a | **PASS** | UMC 嚴格勝 TSMC |
| **H1 Harvey PASS** | FAIL | FAIL | 兩個都不到門檻 |
| 整體結論 | NULL (A4f 勝) | MIXED (EAV 方向+事件窗勝) | — |

## 7. 結論（Verdict）

| 假設 | 結果 | 備註 |
|------|------|------|
| H1 (DM Harvey |t|>3) | **FAIL** (t=-1.371) | 方向正確但未達門檻 |
| H2 (θ₂>0) | **PASS (極顯著)** | t=+15.43, p=6.7e-15 |
| H3 (event |t|>non-ev|t|) | **PASS (顯著)** | event |t|=2.20 vs non-ev |t|=0.16 |
| H4 (UMC > TSMC K1067) | **PASS** | +0.517% vs -0.070% |

### Paper 2 決定性結論：MIXED — 既非純 H_vix 主導，也非純 H_signal

**三個結論相互印證**：

1. **K1067 TSMC 的 NULL 有顯著 power 成分**：UMC 的所有 θ₂ 都為正（100% vs TSMC 的 59%），
   方向翻轉、DM t 從 +0.348 變成 -1.371。**K1067 過去的「H_vix 主導」判定需修正為「H_vix 主導 +
   power 不足」**。

2. **EAV 信號真實存在，但集中於 event window**：event days DM t=-2.204, QLIKE 改善 +39.3%；
   non-event days 基本無影響。這符合 earnings surprise 的理論預期——**信息瞬時釋出**，
   non-event days 無增量訊息。

3. **但整體 OOS 仍未達 Harvey |t|>3**：原因是 event days 只占 1.6%，99% non-event days 稀釋了
   訊號。要在 A4f framework 下取得 Harvey 顯著性，**必須要 event days 占比更高或單個 event
   的強度更大**。

### 對 Paper 2 的具體建議

**建議：從 A4f 主模型中移除 EAV，但保留為 descriptive event-window 分析的 regressor**。

理由：
- Harvey |t|>3.0 是 Paper 2 針對 main prediction claim 的必要門檻。UMC K1067b 的 -1.371 不符合。
- 但 event window DM t=-2.204 與 θ₂ 的高度穩定（100% positive）構成獨立可報告的 descriptive finding。
- 論文可以這樣定位：**「A4f+EAV 在 event day 上實質改善波動預測（QLIKE +39%, DM p=0.036），
  但 event days 的稀有性（1.6%）使其在全 OOS 層面無法達 Harvey threshold。」**
- 這是 **honest MIXED reporting**，既不過度宣稱也不過度否定。

### K1067 判定需回溯修正

**K1067 knowledge.json 的「H_vix DOMINATES」判定需要加入警語**：K1067b 顯示 TSMC 的 NULL 至少
一部分是 power 問題。正確描述應為：「在 TSMC (low-surprise 公司) 上 EAV 無增量訊息，但在 UMC
(high-surprise) 上有可測得的 event-window 改善，整體 DM 未達 Harvey 因 event 稀有性」。

## 8. 局限性（Limitations）

- Event days OOS 僅 28 個，條件 DM 的統計功效仍有限
- EAV 為 binary indicator，未用 earnings surprise magnitude
- UMC 和 TSMC 同屬半導體（相關性~0.76），未排除 sector-level effects
- 未考慮 earnings announcement 與 macro events（FOMC、CPI）的時序重疊
- 可能 UMC 歷史較多小型投資人、訊息反應週期不同——需跨 sector 驗證

## 9. 衍生方向（寫入 research_program.md）

1. **MediaTek (2454.TW) 第三重驗證** — K1060 T+1=1.67（中間值）。若 K1067b 的 power 假設正確，
   MediaTek 的 event-window DM t 應該介於 TSMC 的 +0.083 和 UMC 的 -2.204 之間。這將驗證
   T+1 amplification 與 EAV predictive edge 的**單調關係**。

2. **Earnings surprise magnitude 作為連續 EAV** — 改用「實際 EPS - 分析師共識」標準化為 surprise
   score，而非 binary indicator。這應顯著提升 non-event days 的可用性（部分非 earnings 日有
   pre-announcement 或 guidance 修訂）。

3. **GARCH-X + EAV (排除 VIX)** — 目前 A4f 裡 VIX² 可能吸收了 systematic earnings component。
   測試 GARCH(1,1) + EAV（不含 VIX）作為對照。若 EAV 在無 VIX 的模型中顯著更大，證明 K1067/K1067b
   的 Harvey FAIL 是 VIX 占位效應，而非 EAV 本身無訊號。

## 10. 檔案清單

| 檔案 | 用途 |
|------|------|
| `k1067b.py` | 實驗主腳本（201s runtime） |
| `k1067b_results.json` | 完整結果（含 dm_tests, theta2, event_window, subperiod, robustness, h4） |
| `k1067b_dm_comparison.png` | UMC vs TSMC vs K1064 ETF DM t-stat 比較 |
| `k1067b_event_window_analysis.png` | Event T+1 vs non-event conditional DM（**本實驗核心 finding**）|
| `k1067b_theta2_evolution.png` | θ₂ 27 refits time-series + bootstrap CI（100% 正）|
| `README.md` | 本檔 |

## 11. 參考文獻

- Engle, R. F., Ghysels, E., & Sohn, B. (2013). Stock market volatility and macroeconomic fundamentals. *Review of Economics and Statistics*, 95(3), 776-797.
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246-256.
- Harvey, C. R., Liu, Y., & Zhu, H. (2016). … and the cross-section of expected returns. *Review of Financial Studies*, 29(1), 5-68.
- Patell, J. M., & Wolfson, M. A. (1984). The intraday speed of adjustment of stock prices to earnings and dividend announcements. *Journal of Accounting Research*, 22.

### 相關實驗（知識庫引用）

- K1058: A4f on 0050.TW baseline (DM vs GJR t=-1.26, VaR Trinity PASS)
- K1059: A4f vs GJR event-window amplification (DM t=2.50 vs 1.22)
- K1060: Per-stock EAV, TSMC T+1=0.983, **UMC T+1=2.579 (strongest)**, MediaTek T+1=1.67
- K1062: ETF T+1 ratio = 1.132（diversification dilution 假設來源）
- K1064: ETF A4f+EAV — 全部 NULL
- **K1067: TSMC A4f+EAV NULL (本實驗的直接前身)**

## 12. 自我質疑 (Preamble Rule 5 Checklist)

| # | 問題 | 回答 |
|---|------|------|
| 1 | Mechanical or empirical? | **Empirical** — θ₂ 顯著性、event window DM 改善需要 OOS 估計 |
| 2 | 跟 research_program.md 方法論矛盾？ | 無。Patton QLIKE + Harvey DM + Event-window subsample 都是標準做法 |
| 3 | 不同 target/proxy 會改變結論？ | Proxy 層面穩健（A4f 是 r² 原生模型）。但如果用 **earnings surprise magnitude** 代替 binary，結論可能更強（N8 衍生方向） |
| 4 | Sharpe > 2x baseline? | N/A（波動預測不是交易策略） |
| 5 | 結論強度超過證據？ | **否** — MIXED verdict 明確記錄，H1 FAIL + H2/H3/H4 PASS 分別報告，未把部分 PASS 包裝為整體 PASS |
