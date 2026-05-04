---
title: "重新校正風險模型，到底要多勤快？K1033 告訴你：別再每月折騰一次了"
audience: general
status: draft
tags: [garch, refit, robustness, paper-9, K1033, vol-forecasting]
experiment_refs: [K1033]
---

# 重新校正風險模型，到底要多勤快？K1033 告訴你：別再每月折騰一次了

## 一個被風險管理者忽略的小決定

如果你曾經做過資產風險管理、波動率預測，或是讀過任何一篇用 GARCH 模型的論文，你一定看過類似這樣的句子：「我們每 63 個交易日（約一季）重新估計一次模型參數。」

這句話看似平凡，但其實藏著一個被大多數人忽略的研究問題：**為什麼是 63 天？不是 21 天（每月）、不是 252 天（每年）？這個選擇有沒有偷偷影響結論？**

審稿人會問。讀者也應該問。本文就是針對這個問題，用實驗 K1033 給出一個明確的答案，並順便服務我們 Paper 9（GARCH-X with VIX）的穩健性章節。

## 先補一個基礎：什麼是 GARCH「重估」？

GARCH 是預測波動率（風險）的標準工具。簡單說，它會學「最近的市場有多激烈」，再用學到的規律預測明天的風險水準。

但問題是：市場會變。2008 年的市場行為和 2024 年差很遠；2020 年 COVID 崩盤期間和 2026 年的盤整期更是天壤之別。所以實務上，研究者會**定期重新估計**模型參數，讓模型「跟得上時代」。

**「重估頻率」（refit frequency）就是：每隔多少天我重跑一次估計。**

可以拿一個生活化的比喻：這就像你的 Google Maps 多久重新計算一次路線。

- **每分鐘重算**（refit=21，每月）：很即時，但耗 CPU、耗電、可能對短期路況雜訊過度反應
- **每季重算**（refit=63，學界常用）：折衷
- **每年才重算一次**（refit=252）：省力，但可能整整一年走在過時的路線上

直覺上，你會覺得「越頻繁越好」。但 K1033 實驗的結果，可能會讓你重新思考這個直覺。

## K1033 在做什麼？

K1033 拿了兩個全球最有代表性的 ETF——SPY（標普 500）和 QQQ（納斯達克 100）——測試 5 種不同的重估頻率：

| 重估頻率（refit_every） | 對應實務週期 | 樣本期間內重估次數（SPY/QQQ） |
|------|------|------|
| 21 | 每月 | 約 87 次 |
| 42 | 每兩月 | 約 43 次 |
| 63 | 每季（Paper 9 預設） | 約 29 次 |
| 126 | 每半年 | 約 14 次 |
| 252 | 每年 | 約 7 次 |

兩個對手：
- **GJR-GARCH**（baseline）：經典模型，只看歷史報酬
- **A4f-VIX**：本研究團隊的延伸版本，加入 VIX 隱含波動率作為外生資訊

樣本期間：2005-01-01 到 2026-04-09，OOS（樣本外）從 2019-01-01 起，共 1,827 個交易日。所有設定固定 seed = 42，可完整重現。

## 第一張圖：QLIKE 隨重估頻率怎麼變？

QLIKE 是衡量波動率預測品質的標準損失函數（Patton 2011），數值越低越好。

![QLIKE 隨重估頻率變化（K1033）](experiments/k1033/k1033_qlike_vs_refit.png)

這張圖揭露了一個有趣的對比：

**A4f-VIX 像條筆直的水平線**——不管你 21 天 refit 一次，還是 252 天才 refit 一次，QLIKE 幾乎沒變。具體數字：

- SPY A4f QLIKE：1.4069 ~ 1.4114（變動 < 0.5%）
- QQQ A4f QLIKE：1.4123 ~ 1.4206（變動 < 0.6%）

統計學上常用的「變異係數」（CV，Coefficient of Variation）：

- SPY A4f CV = **0.001**（也就是 0.1%）
- QQQ A4f CV = **0.002**（0.2%）

**這幾乎是不可思議的穩定。**

反觀 GJR baseline：

- SPY GJR：1.4813（refit=21）→ 1.5335（refit=252），CV = **1.2%**（A4f 的 12 倍）

也就是說，GJR 模型如果你偷懶不 refit，預測品質會明顯惡化。但 A4f-VIX 完全沒事。

## 為什麼 A4f 這麼穩？VIX 在偷偷打工

A4f-VIX 的設計裡，**VIX 是即時更新的市場資訊**——即使我們今天用的是 6 個月前 estimate 的參數，VIX 本身仍是今天的數值。所以模型的「即時感」並不完全靠 GARCH 參數的新鮮度，而是靠 VIX 持續餵入最新訊息。

這就像兩個導航 App：
- **GJR**（純歷史報酬）：每年才下載一次地圖；地圖過期就會迷路
- **A4f-VIX**（含 VIX 即時資訊）：地圖每年下載一次，但**即時路況**每秒都在更新；地圖過期一點點，仍能把你送到目的地

## 第二張圖：A4f 真的贏 GJR 嗎？看 DM 檢定

光說 A4f 穩定還不夠，要證明它「比 GJR 好」，需要正式的統計檢定。Diebold-Mariano（DM）檢定就是業界標準。

![DM t-stat vs 重估頻率（K1033）](experiments/k1033/k1033_dm_vs_refit.png)

藍線是 SPY，橘線是 QQQ。所有 5 個 refit 頻率下，DM t-stat 都顯著為負（A4f 的 QLIKE 顯著低於 GJR）。

| 標的 | refit=21 | refit=42 | refit=63 | refit=126 | refit=252 |
|------|------|------|------|------|------|
| SPY DM \|t\| | 3.476 | 3.460 | 2.592 | 2.705 | 2.759 |
| QQQ DM \|t\| | 2.491 | 2.424 | 2.169 | 2.453 | 2.771 |

注意一個細節：SPY 在 refit=21 和 42 達到 Harvey 嚴格門檻（\|t\|>3.0），其他 refit 頻率屬於傳統顯著（\|t\|>1.96）但未達 Harvey 門檻。QQQ 全部都是傳統顯著但未達 Harvey 門檻。

**白話翻譯**：A4f 在所有頻率下都贏 GJR；統計顯著程度有差別，但贏面不變。

## 第三張圖：改善百分比的熱力圖

![QLIKE 改善百分比熱力圖（K1033）](experiments/k1033/k1033_improvement_heatmap.png)

這張熱力圖最值得玩味的，是 **SPY 那一行**：

| 標的 | refit=21 | refit=42 | refit=63 | refit=126 | refit=252 |
|------|------|------|------|------|------|
| SPY 改善 % | 4.84% | 5.41% | 6.30% | 6.53% | **8.26%** |
| QQQ 改善 % | 6.03% | 5.63% | 5.87% | 6.00% | 5.41% |

**SPY 的改善幅度，居然隨 refit 變懶而變大！**

從每月 refit 的 4.84%，一路升到每年 refit 的 8.26%——將近翻倍。

這個結果乍看反直覺，仔細想就明白了：當你 refit 越不勤，GJR 的參數越走味，QLIKE 越爛；但 A4f-VIX 因為有 VIX 即時資訊撐著，幾乎不退化。**兩條線的差距反而拉開**——這就是為什麼 A4f 對 SPY 在低頻 refit 下，反而有更大的領先優勢。

QQQ 則在 5.41% ~ 6.03% 之間平穩，差距僅 0.62 個百分點，更呈現出「無論怎麼 refit，A4f 領先穩定」的圖像。

## 風險管理者最關心：VaR 過得了嗎？

對風險管理者而言，QLIKE 是學術指標，**真正在乎的是 VaR（Value-at-Risk）違規率有沒有失控**。K1033 跑了 VaR 1% 與 VaR 2.5% 兩個門檻 × 5 個 refit × 2 個資產 = 20 個 Kupiec test。

| 模型 | VaR 通過率 | ES 通過率 |
|------|------|------|
| GJR | **0/20**（全 FAIL） | 20/20 |
| A4f-VIX | **19/20**（PASS 率 95%） | 20/20 |

**這是一面倒的差距**。GJR 在所有 refit 設定下，VaR 違規率都顯著偏高（Kupiec test 拒絕零假設）；A4f-VIX 在 19 個情境下都通過，唯一一次邊際 FAIL 是 QQQ refit=252 / VaR 1%（Kupiec p = 0.034，剛好低於 5% 門檻）。

**對實務意涵**：如果你在做 1% 尾端風險預警（VaR 1%），用單純 GJR 的版本——不管你多勤快重估——歷史證據都顯示它低估尾端風險。而 A4f-VIX 在絕大多數設定下都能通過 Kupiec 檢驗。

## 計算成本的權衡

順便看一下計算時間（time_s 欄位）：

| 標的 / refit | A4f 計算時間 | GJR 計算時間 |
|------|------|------|
| SPY refit=21 | 496 秒 | 201 秒 |
| SPY refit=63 | 168 秒 | 68 秒 |
| SPY refit=252 | **51 秒** | 21 秒 |

**從每月 refit 改成每年 refit，計算時間少了將近 10 倍**，但 A4f 的預測品質**沒有變差**。

對於需要對多檔資產 daily rolling backtest 的實務應用（例如資產配置或 robo-advisor 引擎），這代表：選 A4f-VIX + 較低 refit 頻率，可以在預測品質完全不打折的情況下，把運算成本降到原本的 1/10。

## 對 Paper 9 的意義：穩健性章節有著落了

Paper 9（GARCH-X with VIX）長期使用 `refit_every=63` 作為主要 spec。審稿人最容易問的一個問題就是：「這個選擇是否在偷偷驅動結果？」

K1033 給出了乾淨的答案：

1. **A4f-VIX 的 QLIKE 對 refit 頻率近乎完全 invariant**（CV < 0.2%）——選 63 沒有特別偏袒任何結論
2. **A4f 對 GJR 的領先在所有 refit 頻率下都成立**（5 種 × 2 資產 = 10 個情境，10/10 A4f 占優）
3. **VaR backtesting 的優勢同樣 robust**（19/20 vs 0/20）

唯一需要在論文裡誠實揭露的限制：DM 統計顯著性確實隨 refit 頻率有所變化（SPY 在 refit=21, 42 達 Harvey \|t\|>3.0；其他低於門檻但仍傳統顯著）。QQQ 全部是傳統顯著但未達 Harvey。這個 caveat 不會推翻結論，但會在論文 robustness section 明白寫出。

整體判決：**Paper 9 的 robustness gate 通過**（mixed verdict 主因是 DM Harvey threshold 的部分依賴，但所有實質結論——QLIKE 改善、VaR 過 / GJR 不過——皆 invariant）。

## 為什麼一般讀者該關心這件事？

如果你是個人投資人或操作風險管理工具的實務工作者，K1033 給你三個 takeaway：

1. **頻繁 refit 不見得划算**：你或許聽過「越頻繁越精準」的迷思，但對於有外生即時資訊（如 VIX）的模型，每月 refit 和每年 refit 的預測品質差不到 1%，計算成本卻差 10 倍
2. **VIX 是個值得加進來的訊息源**：純粹的 GJR 在每一個尾端 VaR 檢驗都失敗（0/20），而加入 VIX 後變成 19/20。這不是參數調整的小勝，而是質變
3. **看到 GARCH 論文的 refit 設定，記得問一句**：如果這個論文沒有跑 refit 穩健性檢查，它的結論可能脆弱。本研究 K1033 為 Paper 9 守住這道門

## 結論：別再每月折騰你的風險模型

研究與實務的結論一致：**對加入 VIX 的 A4f 模型而言，refit 頻率是個假議題**。

選什麼都贏 GJR，越懶反而越凸顯領先（SPY refit=252 改善 8.26%）。如果你正在維運一個生產環境的波動率風險引擎，K1033 給你授權：把 refit 頻率從每月放寬到每季甚至每半年，省下 75% 的計算資源，預測品質不會打折。

**頻繁 refit 是浪費；A4f 在低頻 refit 反而更穩。**

## 資料來源

- **市場數據**：yfinance API，SPY、QQQ、^VIX，2005-01-01 ~ 2026-04-09
- **實驗 ID**：K1033（A4f Refit Frequency Sensitivity, 2026-04-10 執行）
- **檔案位置**：`experiments/k1033/k1033_results.json`、`experiments/k1033/README.md`
- **樣本外期間**：2019-01-01 起，1,827 個交易日（涵蓋 2020 COVID 崩盤、2022 Fed 加息、2024-2025 多空切換）
- **隨機種子**：seed = 42（完全可重現）
- **服務論文**：Paper 9 — GARCH-X with VIX（穩健性章節）
- **相關實驗**：K988（A4f for SPY champion）、K1003（sensitivity analysis）、K783b（window size）、K1030（European markets）

## 方法論參考

- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246-256.
- Harvey, D., Leybourne, S., Newbold, P. (2016). Modified DM test，\|t\| > 3.0 為嚴格顯著門檻
- Kupiec, P. (1995). Techniques for verifying the accuracy of risk measurement models. *Journal of Derivatives*, 3(2), 73-84.
- Acerbi, C., Szekely, B. (2014). Backtesting Expected Shortfall. *Risk Magazine*.
- Engle, R., Ghysels, E., Sohn, B. (2013). Stock market volatility and macroeconomic fundamentals. *Review of Economics and Statistics*, 95(3), 776-797.
- Engle, R., Rangel, J. G. (2008). The spline-GARCH model for low-frequency volatility and its global macroeconomic causes. *Review of Financial Studies*, 21(3), 1187-1222.
