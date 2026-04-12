# K1067: TSMC (2330.TW) Single-Stock A4f-EAV — Isolating the Diversification Channel

**[提出: 賴奕豪, 執行: Claude]**
**Date**: 2026-04-12
**Runtime**: 182 seconds
**Status**: Complete (NULL — H_vix dominates)

## 1. 問題描述（Problem）

K1064 在 0050.TW ETF 上測試三種權重方案（equal / sector / top50）的 A4f+EAV，
結果全部 NULL（DM t = +1.082 / +0.959 / +2.360，方向全部是 A4f baseline 勝，
θ₂ 在所有 refits 上均為負值 + 不顯著）。

兩個假設可解釋：

| 假設 | 內容 |
|------|------|
| **H_div** | Diversification dilution — 50 檔個股的 idiosyncratic earnings news 被加權平均抵銷 |
| **H_vix** | VIX absorption — VIX 已吸收所有系統性不確定性，EAV 無增量資訊 |

**關鍵性實驗**：在單一公司（TSMC, 2330.TW）上重做 A4f+EAV。
若 PASS → H_div 主導；若 NULL → H_vix 主導。

## 2. 動機（Why）

此檢驗直接影響 Paper 2 的設計：

| 若 H1 PASS (H_div) | 若 H1 FAIL (H_vix) |
|-------------------|-------------------|
| 可以用 sector-weighted 或 constituent-level EAV index 作為 A4f 回歸子 | 不該把 EAV 放進 A4f — 波動預測層面無實證價值 |
| 論文可以宣稱「earnings news → vol」具預測性 | 論文只能做 descriptive event-study，不做 prediction |

## 3. 研究假設（Hypotheses）

| # | 假設 | 通過標準 |
|---|------|---------|
| **H1** (主) | TSMC A4f+EAV DM 顯著勝 A4f baseline | Harvey \|t\|>3.0 且方向為 EAV_better |
| **H2** | θ₂ (EAV 係數) > 0 統計顯著 | One-sample t-test p<0.05 且 bootstrap CI 不含 0 |
| **H3** | 改善集中於 event window | T+1 subsample \|DM t\| > non-event \|DM t\| |
| **H4** | TSMC 改善 > K1064 ETF 最佳變體 | TSMC improvement_pct > -0.205%（K1064 equal） |

## 4. 方法（Method）

### 4.1 模型規格

**Baseline A4f**（K1058 已驗證）：

$$\tau_{t+1} = \max(\theta_0 + \theta_1 \cdot \text{VIX}^2_t,\ \varepsilon)$$
$$u_t = r_t / \sqrt{\tau_{t+1}}$$
$$g_t = \omega_g + \alpha u_{t-1}^2 + \gamma u_{t-1}^2 \mathbf{1}_{u<0} + \beta g_{t-1}$$
$$\sigma^2_{t+1} = \tau_{t+1} \cdot g_{t+1}$$

**Extended A4f-EAV**：

$$\tau_{t+1} = \max(\theta_0 + \theta_1 \cdot \text{VIX}^2_t + \theta_2 \cdot \text{EAV}_t,\ \varepsilon)$$

其中 `EAV_t = 1` 當日為 TSMC 財報公告日，否則 `0`。
台灣上市公司財報為**盤後公告**，資訊集於收盤確定，用以預測 `t+1` 波動 — 無 lookahead。

### 4.2 數據

| 資料 | 來源 | 期間 | 樣本數 |
|------|------|------|--------|
| 2330.TW daily OHLC | yfinance (auto_adjust=True) | 2010-01-05 ~ 2025-12-30 | 3911 交易日 |
| ^VIX daily Close | yfinance | 2010-01-01 ~ 2025-12-30 | forward-fill 對齊 |
| TSMC 財報公告日 | 財報公告日.txt (Big5) | 1987-2025 filter code=2330 | 64 筆落入期間 → 60 distinct 交易日 |
| OOS 期間 | | 2019-01-01 ~ 2025-12-30 | 1697 obs, 28 event days |

**注意**：TSMC 是個股而非 ETF，因此未使用 `clean_tw50_data`（那是 0050.TW 專用 split fix）；
改用 `yfinance auto_adjust=True` 自動處理 splits/dividends。
Max |log return| = 10.51%，未觸發極端值清洗。

### 4.3 估計與評估

- Rolling window = 2000, refit every 63 days (quarterly)
- OOS: 1697 obs, 27 refits
- Random seed = 42
- QLIKE on r² (Patton 2011, proxy-robust)
- DM test with Harvey (2016) |t|>3.0 threshold
- θ₂ one-sample t-test + 2000-rep bootstrap 95% CI
- Event-window, sub-period, lag robustness

### 4.4 前置診斷（error_log rule 5：觀察先於計算）

- ADF stat = -33.84, p < 0.0001 → 定態
- ARCH-LM(10) = 239.20, p = 1e-45 → 顯著異質變異（GARCH 合理）
- Skewness = +0.055, Kurtosis = 3.524（常態峰略高）
- In-sample corr(r², EAV_binary) = **-0.0011**（本身就無線性訊號）
- Naive r²_event / r²_nonevent: T+0 = 0.762, T+1 = 1.009（與 K1060 TSMC T+0=0.75, T+1=0.98 吻合）

## 5. 結果（Results）

### 5.1 主要 DM test

| 指標 | A4f baseline | A4f+EAV |
|------|-------------|---------|
| QLIKE | 1.165735 | 1.167766 |
| Spearman ρ | +0.2200 (p<0.001) | +0.2144 (p<0.001) |
| n_valid | 1697 | 1697 |

**DM test**: t = **+0.348**, p = 0.7281, improvement = **-0.070%**, direction = A4f_better

→ **H1 FAIL** — 遠低於 Harvey |t|>3.0 門檻，方向且為 A4f baseline 勝。

### 5.2 θ₂ 分布（H2）

| 統計量 | 數值 |
|--------|------|
| mean | **-4.476e-04** |
| median | +4.205e-05 |
| std | 1.382e-03 |
| positive fraction | 0.59 (16/27 refits) |
| one-sample t (θ₂>0) | **-1.68** |
| one-sided p | 0.9478 |
| Bootstrap 95% CI | **[-9.865e-04, +3.582e-06]** |

→ **H2 FAIL** — θ₂ 平均為負，CI 上界僅 3.58e-06（幾乎跨 0），one-sample t-test p=0.95 拒絕 θ₂>0。

### 5.3 Event-window 分析（H3）

| 子樣本 | n | DM t | QLIKE improvement |
|--------|---|------|-------------------|
| T+1 event | 28 | +0.083 | -0.249% |
| Non-event | 1669 | +0.323 | -0.172% |

→ **H3 FAIL** — event |t|=0.083 小於 non-event |t|=0.323（預期相反）。Event 改善甚至比 non-event 更負。

### 5.4 H4 — TSMC vs K1064 ETF

| 對照 | improvement vs A4f |
|------|-------------------|
| **TSMC A4f+EAV (本實驗)** | **-0.070%** |
| K1064 ETF equal-weight | -0.205% |
| K1064 ETF sector-weight | -0.207% |
| K1064 ETF top50-count | -0.419% |

→ **H4 PASS (marginal)** — TSMC 損失（-0.070%）確實小於三個 K1064 ETF 變體（-0.205% ~ -0.419%），
但 TSMC 仍是負改善，不足以支持 H_div 主導。

### 5.5 Sub-period stability

| Period | Window | n | DM t | improvement |
|--------|--------|---|------|-------------|
| 1 | 2019-01-02 ~ 2020-06-03 | 340 | +1.046 | -0.731% |
| 2 | 2020-06-04 ~ 2021-10-22 | 340 | +1.162 | -0.851% |
| 3 | 2021-10-25 ~ 2023-03-17 | 339 | +0.304 | -0.191% |
| 4 | 2023-03-20 ~ 2024-08-08 | 339 | **-0.438** | **+0.697%** |
| 5 | 2024-08-09 ~ 2025-12-30 | 339 | +0.059 | +0.050% |

→ EAV 在 5 個子期間中有 2 個（Period 4, 5）方向為 EAV_better，3 個為 A4f_better。
全部 |t|<1.2 均未達任何顯著水準。Period 4 僅為雜訊漂移。

### 5.6 Lag robustness

| EAV 定義 | θ₂ | In-sample QLIKE |
|---------|-----|-----------------|
| EAV_{t-1} (default) | -3.124e-05 | 1.108173 |
| EAV_{t-2} | +5.306e-05 | 1.109722 |
| EAV rolling-3d | -2.155e-05 | 1.108558 |

→ θ₂ 的符號不穩定（小數值上下浮動），QLIKE 差距 <0.002，lag 定義非主因。

## 6. 結論（Verdict）

| 假設 | 結果 |
|------|------|
| H1 (DM Harvey |t|>3) | **FAIL** (t=+0.348) |
| H2 (θ₂>0) | **FAIL** (t=-1.68, p=0.95) |
| H3 (event |t|>non-event |t|) | **FAIL** (0.083 < 0.323) |
| H4 (TSMC > K1064 best) | **PASS (marginal)** |

### 診斷：H_div vs H_vix

| 證據 | 傾向 |
|------|------|
| H1 FAIL 在單一公司層面（無法歸因於 diversification） | **H_vix** |
| θ₂ mean 為負，bootstrap CI 上界幾乎跨 0 | **H_vix** |
| Event 和 non-event 均為 A4f_better | **H_vix** |
| TSMC 改善 > ETF 改善（但仍為負） | H_div (弱) |

→ **H_vix DOMINATES**（VIX 吸收主導）。

**TSMC T+1 ratio = 0.98 (K1060)** 本身就是 10 檔中最弱的，而且這個弱訊號的微量方向性
在 A4f 架構下被 `τ = θ₀ + θ₁·VIX²` 已吸收的部分幾乎完全掩蓋（in-sample corr = -0.0011）。

### Paper 2 意涵

1. **不應把 TW_EAV_factor 當作 A4f 的 exogenous regressor** — 單一公司層級也拉不出訊號，
   結構性問題不是 diversification，而是 **VIX 在 A4f framework 已吸收系統性不確定性**。
2. **K1064 的 NULL 不是 bug 也不是 diversification 稀釋的單一問題** — 而是 earnings indicator
   對 A4f 架構本質上的冗餘（redundant given VIX²）。
3. **Paper 2 可以保留 K1059 的 descriptive finding**（A4f vs GJR 的優勢在 event window 擴大，
   DM t=2.50 vs 1.22）— 那是關於 *architecture* 的 statement，不是 *regressor* 的 statement。
4. **後續方向**：
   - 測試 EAV 作為 GARCH (not A4f) 的 regressor → 排除 VIX 的吸收
   - 測試 high-beta 個股（如 2303 UMC, T+1=2.58）作為 power test
   - 改用 earnings *surprise magnitude*（不是 indicator）作為連續 regressor
   - 改用 implied vol premium (IV rank) 或 option-implied jump intensity 做 predictor

## 7. 局限性（Limitations）

- 單一公司（TSMC）樣本：28 event days OOS 對 conditional DM 檢定力低
- EAV 為 binary indicator（非 surprise magnitude）—可能低估實際訊息強度
- VIX 是美股指標，TSMC 是台股 ADR-heavy 半導體龍頭 — 兩者相關性本就高（US-TW lead-lag 之 K1060 前置研究）
- 未排除 macro confounders（CPI、FOMC 等事件與 earnings 可能重疊）

## 8. 檔案清單

| 檔案 | 用途 |
|------|------|
| `k1067.py` | 實驗主腳本（182s runtime） |
| `k1067_results.json` | 完整結果（含 dm_tests, theta2, event_window, subperiod, robustness, h4） |
| `k1067_dm_comparison.png` | TSMC vs K1064 ETF variants DM t-stat 比較 |
| `k1067_event_window_analysis.png` | Event T+1 vs non-event conditional DM |
| `k1067_theta2_evolution.png` | θ₂ 27 refits time-series + bootstrap CI |
| `README.md` | 本檔 |

## 9. 參考文獻

- Engle, R. F., Ghysels, E., & Sohn, B. (2013). Stock market volatility and macroeconomic fundamentals. *Review of Economics and Statistics*, 95(3), 776-797.
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246-256.
- Harvey, C. R., Liu, Y., & Zhu, H. (2016). … and the cross-section of expected returns. *Review of Financial Studies*, 29(1), 5-68.
- Patell, J. M., & Wolfson, M. A. (1984). The intraday speed of adjustment of stock prices to earnings and dividend announcements. *Journal of Accounting Research*, 22.

### 相關實驗（知識庫引用）

- K1058: A4f on 0050.TW baseline (DM vs GJR t=-1.26, VaR Trinity PASS)
- K1059: A4f vs GJR event-window amplification (DM t=2.50 vs 1.22)
- K1060: Per-stock EAV, TSMC T+1 ratio = 0.983 (10-stock overall T+1 = 1.466)
- K1062: ETF T+1 ratio = 1.132（diversification dilution 假設的來源）
- K1064: ETF A4f+EAV — 全部 NULL（本實驗的直接前身）

## 10. 自我質疑 (Preamble Rule 5 Checklist)

| # | 問題 | 回答 |
|---|------|------|
| 1 | Mechanical or empirical? | **Empirical** — θ₂ 顯著性需要 OOS 估計，不可從模型定義推導 |
| 2 | 跟 research_program.md 方法論矛盾？ | 無。使用標準 Patton QLIKE + Harvey DM threshold |
| 3 | 不同 target/proxy 會改變結論？ | 可能 — 若用 RV 或 implied vol 作為 target，結果可能改變。但 A4f 是 r² 原生模型，此處 target 正確 |
| 4 | Sharpe > 2x baseline? | N/A（波動預測不是交易策略） |
| 5 | 結論強度超過證據？ | 未過度宣稱 — NULL 結果明確記錄，H_vix vs H_div 以證據權衡表達 |
