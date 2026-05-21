# CBOE SKEW 對 SPY 波動率有增量預測力嗎？保守 t>3 hurdle 下八模型 OOS 全敗

## 摘要

K979 把 CBOE SKEW (^SKEW) 放進 VIX 已存在的波動率預測迴歸，於 2010-02 至 2026-04 共 4,004 個交易日 SPY 樣本上跑八個 OLS 設定（1/5/22 日 forward RV + VIX² 非線性 + VIX×SKEW 交乘）。IS=2,222 / OOS=1,759（M7/M8 OOS=1,780）。**主結論**：採 Harvey-Liu-Zhu (2016, RFS) 風格的保守 t>3 hurdle，SKEW 條件 t-stat 三 horizon 全敗（1.876 / 1.108 / 0.687）；DM test p=0.997 無法拒絕「VIX 與 VIX+SKEW 預測精度相同」null。SKEW 五分位 forward RV 0.050→0.016 與 VIX-SKEW = -0.197 並存——控制 VIX 後 SKEW t-stat 退到 1.876，quintile 單調降幅大部分被 VIX 解釋；殘餘獨立 signal 是否為零需後續 residualized-SKEW / two-way sort。

前一篇 general（K447 mile_1b2ad1f8）以 Ridge + AUC 已展示 SKEW 對尾端 binary signal 微弱。本文以 numeric prediction + 保守 t hurdle + DM null + 八模型 OOS R² 對比作為 research 互補。

## 研究背景

CBOE SKEW 由 SPX OTM 選擇權的 risk-neutral skewness 反推（Bakshi-Kapadia-Madan 2003 框架），衡量 priced tail risk；VIX 衡量 ATM implied vol level。兩者同源 SPX option panel 但屬不同維度。實證文獻（Conrad-Dittmar-Ghysels 2013、Faff-Parwada-Tan 2021 JFS）SKEW 增量預測力結果 mixed。本實驗加碼：(i) 全 16 年 OOS、4,004 obs、(ii) 八模型同框架對比、(iii) 保守 t hurdle 下用回歸控制 VIX 來 disentangle quintile 單調性與 VIX 共變貢獻。

## 資料與方法

| 項目 | 設定 |
|------|------|
| 資料源 | yfinance: SPY, ^VIX, ^SKEW |
| 期間 | 2010-02-04 ~ 2026-04-06 (4,004 obs) |
| Target | RV1 / RV5 / RV22 = 平方日報酬年化值的前向移動平均 |
| IS / OOS | 2,222 / 1,759（M7/M8 OOS=1,780） |
| Lookahead 防護 | `df['vix'].shift(1)` / `df['skew'].shift(1)` (k979\_skew\_vol.py L168-170) |
| 估計 | OLS（無 HAC，列為局限） |
| 門檻 | 保守 t>3 hurdle（採 Harvey-Liu-Zhu 2016 RFS data-mining-aware 精神作 screen，非 textbook standard）；輔以 DM test (NW lag=12)；seed=42 |

### 描述統計

| 變數 | mean | std | skew | kurt | min | max |
|------|---:|---:|---:|---:|---:|---:|
| VIX | 18.43 | 6.88 | 2.39 | 11.02 | 9.14 | 82.69 |
| SKEW | 131.19 | 11.89 | 0.83 | 0.40 | 110.34 | 183.12 |
| RV1 ann. | 0.030 | 0.113 | 16.28 | 366.18 | 0.000 | 3.384 |

VIX-SKEW Pearson 相關 **-0.197**——本文後段 confounding 分析的關鍵 anchor。

## 八個競爭模型

```
RV_{t+h} = β₀ + β₁·VIX_{t-1} + β₂·SKEW_{t-1} + β₃·extra_{t-1} + ε_t
```

`extra` 在不同模型分別為 0、`VIX²_{t-1}`、`VIX×SKEW_{t-1}`，h ∈ {1, 5, 22} day。

![SKEW 與 VIX 的 scatter 與時序](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k979_skew_vix_scatter.png)
*圖 1：SKEW vs VIX scatter（相關 -0.197），與兩者標準化後時序——SKEW 的長期均值漂移與 VIX spike 並不同步。*

## 主結果：保守 t hurdle 全敗

| 模型 | Predictors | Target | IS R² | OOS R² | SKEW β | SKEW t | t>3? |
|------|-----------|--------|------:|-------:|-------:|------:|:----:|
| M1 | VIX | RV1 | 0.1717 | 0.1387 | — | — | — |
| M2 | VIX + SKEW | RV1 | 0.1730 | 0.1387 | 2.75e-4 | 1.876 | ✗ |
| M3 | VIX | RV5 | 0.2811 | 0.1838 | — | — | — |
| M4 | VIX + SKEW | RV5 | 0.2815 | 0.1844 | 1.00e-4 | 1.108 | ✗ |
| M5 | VIX | RV22 | 0.2719 | 0.1053 | — | — | — |
| M6 | VIX + SKEW | RV22 | 0.2721 | 0.1060 | 4.55e-5 | 0.687 | ✗ |
| M7† | VIX + SKEW + Interact | RV1 | 0.1731 | 0.1408 | 5.38e-4 | 1.195 | ✗ |
| M8† | VIX + VIX² + SKEW | RV1 | 0.1777 | **0.1978** | 1.53e-4 | 1.015 | ✗ |

†M7 / M8 OOS n=1,780（reg_df3 scope，含 VIX² lag-2 與交乘計算需求的非缺失 obs；M1-M6 OOS n=1,759）。

Research take-away：

1. **三 horizon SKEW t-stat 全敗**，最高 1.876 仍離 3.0 很遠；降到 |t|>2.0 寬鬆門檻 22 日 horizon 仍只有 0.687。
2. **SKEW 對 OOS R² marginal ≈ 0**：M2-M1 = -8.85e-6、M4-M3 = +5.79e-4、M6-M5 = +6.85e-4，全 noise level。
3. **OOS R² 真正改善來自 VIX² 非線性**：M8 OOS R² **0.1978** 比 M2 的 0.1387 高 +5.91 pp；VIX² t-stat = **3.546**（唯一通過 t>3 的非 VIX 線性項），SKEW t-stat 1.015。**未來邊際在 nonlinearity（與 K1018 一致），不在加 SKEW。**

## DM test：formal null 不能拒絕

M1 (VIX) vs M2 (VIX+SKEW)，OOS 1,759 obs，loss = squared error，d = e₁ − e₂（M1 sq err − M2 sq err），Newey-West lag=12：

| 量 | 值 |
|---|---:|
| DM statistic | -0.00396 |
| p-value (two-sided) | **0.9968** |
| mean loss diff (M1 − M2) | -2.19e-7 |
| 顯著？ | **No** |

mean loss diff **負號**意味 M1 squared error 平均略小於 M2，M1 微勝 — 與 OOS R² 0.1387 ≈ 0.1387 對齊。p=0.997 是極端不顯著 null，比起 K447 mile_1b2ad1f8 的 Ridge AUC binary 比較是更嚴格的 numeric-prediction null check。

## Conditional vol：先看 quintile pattern，再用回歸 disentangle

本文最有研究價值的 nuance。先看 SKEW 五分位下的 forward RV：

| SKEW 分位 | n | mean RV1 | median RV1 |
|-----------|---:|---------:|-----------:|
| Q1 (low SKEW) | 802 | **0.0495** | 0.0101 |
| Q2 | 800 | 0.0324 | 0.0066 |
| Q3 | 800 | 0.0272 | 0.0057 |
| Q4 | 801 | 0.0225 | 0.0045 |
| Q5 (high SKEW) | 800 | **0.0161** | 0.0042 |

Q1→Q5 mean forward RV **單調遞減** 0.050→0.032→0.027→0.023→0.016，減 67.4%。乍看是強訊號——「SKEW 越高，未來 RV 越低」。

> **方法註**：Q1-Q5 quintile sort 採 same-day `SKEW_t` 對 forward `RV_{t+1}`，與主回歸 M1-M8 全 lag (`SKEW_{t-1}`, `VIX_{t-1}`) 規格不同。SKEW 為當日收盤可觀測，sort 仍為 valid forward-looking exercise，但敘事須與回歸區分；後段 confounding 分析以**回歸**為準。

![SKEW 分位下的 conditional forward RV 與極端 SKEW vol 行為](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k979_conditional_vol.png)
*圖 2：SKEW 五分位 forward RV1（左）與 P5/P10/P90/P95 極端 SKEW 樣本（右）下未來 RV 對比。*

把 raw quintile 與 -0.197 VIX-SKEW corr 放一起出現 **confounding hypothesis**：SKEW 與 VIX 負相關 → Q1 樣本部分集中在 high VIX 期、Q5 偏 low VIX；控制 VIX 後 SKEW 條件 t-stat 退到 1.876 (M2 1d)，quintile 單調降幅大部分被 VIX 解釋。**但這只支持「confounding 存在」，不足以斷定 SKEW 完全無殘餘獨立 signal。** 要區分「VIX 完全 mediator」vs「SKEW 仍有 marginal 獨立 signal」需後續 (a) residualized-SKEW 對 forward RV 二次分位、(b) VIX×SKEW 5×5 two-way sort。可斷言：**單看 quintile 表下「SKEW 有 stand-alone 預測力」是 specification fallacy**；但也不能反稱「純機械 artifact」— 證據是 confounding-dominant，非 mechanical-only。

P5/P95 極端樣本 mean RV1 比例 4.76 倍（0.0671 vs 0.0141）同呈 raw 形式負向 cluster；殘餘獨立性同需 residualized 分析切割。

## 年度 OOS R²：脆弱性提示

| 年 | n | M1 R² | M2 R² | ΔR² (M2-M1) |
|---|---:|------:|------:|------------:|
| 2019 | 249 | 0.159 | 0.150 | -0.009 |
| 2020 | 253 | 0.107 | 0.109 | +0.002 |
| 2021 | 247 | -0.999 | -1.319 | -0.320 |
| 2022 | 243 | -0.054 | -0.056 | -0.002 |
| 2023 | 234 | -0.290 | -0.353 | -0.062 |
| 2024 | 241 | -0.401 | -0.437 | -0.036 |
| 2025 | 250 | 0.137 | 0.137 | -0.001 |
| 2026 YTD | 42 | -0.768 | -0.754 | +0.014 |

2021/2023/2024 負 OOS R² 顯示靜態係數套到變化 vol regime 本就脆弱，非 SKEW 之過；但年度切片 SKEW 也沒有任何一年 systematic 把 ΔR² 推到正且大於 noise — 六年負、兩年微正。

## 與 K447 mile_1b2ad1f8 互補

| 維度 | K447 (general) | K979 (research) |
|------|----------------|-----------------|
| target | binary tail / fwd_abs_ret / fwd_RV21 | numeric RV1 / RV5 / RV22 |
| 估計 | Ridge + CV | OLS（八模型） |
| framework | AUC、QLIKE、χ² | 保守 t>3 + DM |
| 樣本 | 2005-2026 (5,194) | 2010-2026 (4,004) |
| take-away | binary 訊號微弱 | numeric 增量為 0、VIX² 是路徑 |

兩篇同向，但 K979 把 conditional vol confounding 拆開、量化控制 VIX 後 SKEW t-stat 剩餘水準，並指出 VIX² nonlinearity 是邊際（與 K1018 一致）。

## 結論

1. SKEW 對 SPY 未來 RV（1/5/22 日 horizon）**沒有跨保守 t>3 hurdle 的增量預測力** — 八模型 OOS R² 對比、SKEW t-stat ∈ [0.687, 1.876]、DM p=0.997 三證據一致。
2. Quintile 單調遞減（0.050→0.016, -67%）與 VIX-SKEW = -0.197 confounding 並存；控制 VIX 後 t-stat <2，殘餘獨立 signal 是否為零需後續 residualized-SKEW / two-way sort。
3. 真正改善邊際在 **VIX² 非線性**（M8 OOS R² 0.198 vs M2 0.139；VIX² t-stat=3.546 通過 t>3），與 K1018 一致。
4. **單一 VIX 已是 sufficient statistic** 的證據再 +1（與 K504 / K1098 family 累積一致）。

## 局限性

- RV proxy 用平方日報酬年化值，noise 比 5-min realized vol 大；對 null 結論方向性影響有限。
- OLS 標準誤未做 NW HAC；可能略低估 SE，但 SKEW t-stat 全部 <2，HAC 修正後仍不可能跨 3.0。
- 未做 residualized-SKEW / VIX×SKEW two-way sort，僅能斷言 confounding-dominant，不能斷言純機械。
- 未測 SKEW 對極端事件（COVID 2020-03、SVB 2023-03）的即時短窗預測力 / 對 VaR/ES 的增量。

## 引用實驗

- **K979** (本實驗)：`experiments/k979/k979_skew_vol_results.json`
- **K447 mile_1b2ad1f8** (general, 2026-05-05)：Ridge + AUC
- **K1018**：VIX² nonlinearity（本文 M8 confirm path）
- **K504, K1098**：VIX 充分性家族
- **K210, K258**：歷史 SKEW null/spurious

## 引用文獻

- Harvey, C. R., Liu, Y., & Zhu, H. (2016). "...and the Cross-Section of Expected Returns." *Review of Financial Studies* 29(1), 5-68. https://doi.org/10.1093/rfs/hhv059
- Diebold, F. X. & Mariano, R. S. (1995). "Comparing Predictive Accuracy." *JBES* 13(3), 253-263.
- Patton, A. J. (2011). "Volatility Forecast Comparison Using Imperfect Volatility Proxies." *J. Econometrics* 160(1), 246-256.
- Bakshi, G., Kapadia, N. & Madan, D. (2003). "Stock Return Characteristics, Skew Laws..." *RFS* 16(1), 101-143.
- Conrad, J., Dittmar, R. F. & Ghysels, E. (2013). "Ex Ante Skewness and Expected Stock Returns." *JF* 68(1), 85-124.
- Faff, R., Parwada, J. T. & Tan, E. (2021). "The CBOE Skew Index and US stock market crashes." *JFS*.

## 更新歷史

- 2026-05-09 v1：初版發佈（K979 完整結果，audience=research）。
- 2026-05-09 v2：Codex review 修正 4 處（audit_source=codex_2026_05_09）：Harvey hurdle 改 Harvey-Liu-Zhu 2016 RFS 保守 screen + 替換 reference DOI；Q1→Q5 quintile 由 mechanical artifact 改 confounding-dominant；quintile timing 方法註說明 same-day vs lagged；DM mean loss diff sign 改 (M1−M2)；M7/M8 OOS n=1,780 標註。
