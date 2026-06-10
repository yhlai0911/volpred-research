# K1465 — Day-of-Week Clustering of Overnight/Intraday Variance and VRP Tradability

- Experiment ID: `k1465`
- Status: complete (awaiting Codex review)
- Verdict: **NULL** (with one orthogonal positive finding on variance — see §結果)
- Created At: 2026-06-11 (Asia/Taipei)
- Source task: `storage/next_tasks.json` id=research_clustering

## 1. 研究問題

1. SPY ETF 2010–2026 共 ~4,100 個交易日，**overnight 報酬²** 與 **intraday 報酬²** 在 day-of-week 上是否系統性不同？
2. **VRP proxy**（IV² − RV_5d，BTZ 2009）在不同 weekday 是否顯著差異？
3. 若 VRP 有 weekday 異質性，淨於 30 bps 單邊成本後是否可交易？

## 2. 動機與差異化

- VRP 的星期效應在 2025–26 學術文獻（AEF / Harbourfront）有零星觀察但**無一致結論**；多數論文聚焦 monthly / FOMC cycle / overnight-vs-intraday 分解（Lou, Polk & Skouras 2019 JFE）。
- 本實驗把兩條 axis 交叉：**calendar (DoW) × variance-decomposition (overnight vs intraday)** + VRP magnitude — 直接檢定「投資人是否系統性在特定 weekday over-pay for insurance」。
- **差異化 vs `experiments/vrp_regime_decomposition/`**：後者僅為 planning stub（VRP 低 / 中 / 高 regime 分組），K1465 攻擊**正交軸**（calendar clustering，非 magnitude regime），且納入可交易性 backtest。

## 3. 資料與方法

| 項目 | 設定 |
|---|---|
| 資料源 | yfinance — SPY + ^VIX（`auto_adjust=False`，用 AdjClose/Close 比率聯動校正 Open） |
| 期間 | 2010-01-05 → 2026-06-10（**4,129 個交易日**，含 2020 COVID / 2022 升息 / 2025） |
| In-sample | 2010-01 → 2022-12（n=3,266） |
| OOS | 2023-01 → 2026-06（n=862） |
| Overnight return | `open_t / close_{t-1} − 1`（split-adj） |
| Intraday return | `close_t / open_t − 1` |
| RV_5d | 過去 5 日 `r_id²` 累加 × (252/5) — **不含當日**，無 lookahead |
| VRP | `(VIX_t/100)² − RV_5d_t` |
| Signal lag | 所有 trading signal `.shift(1)`；DoW 雖機械可知，仍 explicit lag 以通過 review |
| 統計 | Kruskal–Wallis + Dunn pairwise（Bonferroni 校正）+ DM (HLN-corrected) |
| 隨機 seed | 42 |
| 成本 | 30 bps / leg |

### 防 lookahead

- `RV_5d_t` 只用 t-1 .. t-5 的 intraday returns。
- 所有交易 signal `.shift(1)`：`signal_lag = signal.shift(1).fillna(0)`。
- Best-DoW 選擇**只用 in-sample**（2010–2022）VRP mean 排序，再用同一個 best-DoW 跑 OOS。

## 4. 結果

### 4.1 描述統計（KW H / p）

| Series | KW H | KW p | 結論 |
|---|---|---|---|
| Overnight r² (full) | 16.47 | **0.0025** | **拒絕** — 隔夜變異有 DoW 結構 |
| Intraday r² (full) | 11.29 | **0.024** | **拒絕** — 日內變異有 DoW 結構 |
| VRP (full) | 2.30 | 0.680 | 不拒絕 — VRP 無 DoW 結構 |
| VRP (OOS) | 0.73 | 0.948 | 不拒絕 — OOS 同樣無結構 |

**核心發現**：原始 squared returns 有顯著 weekday 結構，但 **VRP 因為 IV²（市場已 pricing）與 RV 同步動，weekday 效應在 spread 上抵銷**。市場有定價這個 calendar pattern。

### 4.2 VRP × DoW Mean（年化）

| DoW | Full | OOS |
|---|---|---|
| Mon | 0.0226 | 0.0162 |
| Tue | 0.0221 | 0.0161 |
| Wed | 0.0216 | 0.0150 |
| Thu | 0.0221 | 0.0155 |
| Fri | 0.0212 | 0.0154 |

最大 / 最小差 < 7 bps，落在抽樣噪音內。

### 4.3 Backtest（best DoW = Mon，選自 IS）

| 指標 | Strategy (Mon-only long-SPY proxy) | Buy & Hold SPY |
|---|---|---|
| Full Sharpe | **−1.30** | +0.85 |
| OOS Sharpe | **−2.09** | +1.39 |
| OOS t-stat | −3.87 | +2.56 |

策略**顯著輸**買進持有 — 與 NULL verdict 一致，且側面確認**「Monday effect」歷史 anomaly**（Mondays 報酬偏負）依然存在 — 但這對 VRP-harvesting 沒幫助。

### 4.4 DM test（HLN）— 用 best-DoW 切換 VRP / RV5 預測 RV

OOS DM = 1.53（p = 0.125）— 無顯著差異，flat VRP forecast 不比 DoW-gated 差。

## 5. Verdict 與結論

### NULL

- **主假設（VRP 有 DoW 結構）被拒絕**：KW p > 0.05 全期 + OOS 同時不顯著。
- **可交易性**：依設計切 OOS Mon-only 策略 Sharpe = −2.09，遠低於 buy-and-hold +1.39 — 即使有結構也不可交易。

### 順便的真實發現（orthogonal positive）

- **Variance² 本身有 DoW 結構**（overnight p=0.0025、intraday p=0.024）但 IV 已定價該結構。
- **Monday effect 在 SPY close-to-close 仍存在**（Mon-only 報酬顯著為負，t = −5.26 full）— 但這是純股票 anomaly，不是 VRP anomaly。

## 6. 限制

1. **Short-vol proxy = SPY r_co**（高度與 VIX 負相關但量級不同）。真實 VXX/SVXY/short-call backtest 會有 path-dependence 與 contango 成本，本實驗低估雙向。
2. **30 bps 是 SPY ETF 假設**，VIX-futures / 短倉 call 成本更高 → 真正 bar 更高 → NULL 結論更強。
3. **單一資產**。後續應在 QQQ、IWM、ES futures、VIX futures 直接 backtest（task brief 50min cap 內留 follow-up）。
4. **RV_5d 不含 overnight 變異**（BTZ 2009 convention），VRP 是保守估計。

## 7. 與其他 K 的關聯

- `experiments/vrp_regime_decomposition/`：正交軸（magnitude regime ≠ calendar DoW）。
- BTZ 2009 / Bekaert-Hoerova 2014：VRP 預測股票報酬，本實驗檢定** calendar conditioning** 能否 sharpen prediction → 答 NO。
- Lou, Polk, Skouras 2019 JFE：overnight vs intraday equity premium → 本實驗在 variance 維度發現對應 DoW heterogeneity 但無 spread 對應。

## 8. 後續建議

1. **不要再追 weekday VRP**。改測 **intraday hour clustering**（10:00 vs 15:00 VIX、open vs close gap）。
2. **改測 FOMC / CPI 公告週的 VRP 衝量**（event-driven 而非 calendar）。
3. **Overnight variance 顯著 DoW 結構**（Mon overnight 變異最大）可作 **single-asset article**（非 paper），不必再實驗即可寫科普文。

## 9. References

- Bollerslev, Tauchen & Zhou (2009). *Expected Stock Returns and Variance Risk Premia*. RFS 22(11), 4463-4492.
- Bekaert & Hoerova (2014). *The VIX, the variance premium and stock market volatility*. JoE 183(2), 181-192.
- Patton (2011). *Volatility forecast comparison using imperfect volatility proxies*. JoE 160(1), 246-256.
- Harvey, Leybourne & Newbold (1997). *Testing the equality of prediction mean squared errors*. IJF 13(2), 281-291.
- Lou, Polk & Skouras (2019). *A tug of war: Overnight versus intraday expected returns*. JFE 134(1), 192-213.

## 10. Files

```
experiments/k1465/
├── README.md                  ← this file
├── k1465.py                   ← reproducible script
├── k1465_results.json         ← all numbers + verdicts
├── data/spy_vix_raw.parquet   ← cached source data
└── figures/
    ├── a_dow_boxplot.png      ← overnight/intraday r² by DoW
    ├── b_vrp_by_dow.png       ← VRP violins by DoW
    ├── c_backtest_equity.png  ← strategy vs buy-and-hold
    └── d_pvalue_heatmap.png   ← Dunn pairwise p-values full vs OOS
```

Reproduce: `uv run python experiments/k1465/k1465.py` (cached parquet auto-used).
