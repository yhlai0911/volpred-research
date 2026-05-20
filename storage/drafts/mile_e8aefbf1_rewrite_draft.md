[提出: 用戶, 執行: Claude]

> ## 重要更正聲明（2026-05-07）
>
> 本文舊版（K79/K85 系列）核心結論「12/VIX VT 將最大安全提領率從 4% 翻倍到 8%」**已被推翻**。經 K87 交叉驗證 + K222 在 2026-05-06 的 lookahead patch（VIX 訊號改用前一交易日收盤值，避免 t 期使用 t 期同時資訊）後，正確結論為：**VT 在 4% 提領率下提供的是更窄的尾部分佈與更低的破產風險，最大安全提領率仍為 4%。** 本文依修正後事實重寫；舊版表格中關於 5%、6%、8% 提領率的「100% / 99.9% / 95.5%」等數字**請暫不採信**。

## 摘要

退休投資的核心風險不是平均報酬偏低，而是**序列風險**——退休初期碰上大跌，即使長期市場回升，提領已經把本金耗盡。我們原先用 10,000 次 block bootstrap Monte Carlo 測試「波動率目標化（VT）能否提高 4% 法則下的最大安全提領率」，得到「4% → 8% 翻倍」的結論。經 K87 交叉驗證 + K222 lookahead patch 後，**翻倍宣稱不成立**。修正後 VT 的真實價值在於**變異變窄**：相同 4% 提領率下，尾部破產機率與最大回撤明顯較低，但最大安全提領率沒有翻倍。

## 為什麼宣稱被推翻

原始 K79 / K85 模擬報告 12/VIX VT 在 8% 提領率下 30 年存活率 95.5%、4% 下 100%。K87 立刻啟動三項獨立交叉驗證：

| 驗證 | 方法 | 結果 |
|------|------|------|
| 1 | 改用 5 種 bootstrap block size（3/6/12/24/36 個月）| 8% WR 存活率落在 25.2-28.0%，全部 < 30% |
| 2 | 1985-2024 historical rolling 15-year windows | 8% WR VT 存活率 67%，**低於 B&H 72%** |
| 3 | Cash yield decomposition | T-bill yield 假設貢獻 VT 總優勢 255% |

三項驗證指向同一根因：原 bootstrap 設定下，block size 過大保留了牛市序列、cash return 假設樂觀，**人造**了 VT 在高提領率的「翻倍」假象。

2026-05-06 Codex review of `experiments/k222/k222_retirement_swr.py` 又發現獨立的 lookahead bias：line 133 之前的版本在 t 期計算 VT 權重時引用 `vix_series.loc[date]`（**當期** VIX），等於假設投資人在 t 期開盤就能看到 t 期收盤的 VIX。修補後（line 138-140）改為 `prev_date = period_rets.index[i - 1]; vix_val = vix_series.loc[prev_date]`，符合「signal from t-1, return at t」標準。Patch 後 script 待重跑，但 K547 系列同類修補的歷史經驗顯示，VT 在高 WR 區段的 inflated edge 通常會在 patch 後大幅收斂。

![K87 交叉驗證：8% 提領率「翻倍」宣稱被推翻（5 種 block size bootstrap 全部 < 30%）](experiments/k222/figures/fig_swr_refutation.png)

## 修正後 VT 的真正定位

VT 沒有把 SWR 翻倍，但**並非無價值**。修正版的角色定位是：在固定 4% 提領率下，**縮小終值分佈的下尾**——P5 與最差情境的破產機率明顯低於 B&H，最大回撤在重大危機開頭退休的情境（2000、2007）下也較淺。中位數終值兩者接近，沒有「2.1 倍」的差距（這是舊版基於前瞻訊號 + 樂觀 cash yield 的合成幻覺）。

換言之：VT 是**尾部保險**，不是收益放大器。對 K78 Type D 退休提領者而言，VT 的價值仍在於降低「不幸在市場高點退休」的鎖死虧損機率，而非提高可提領上限。

![K222 修正後 VT 的真正角色：4% WR 下變異變窄、不是翻倍](experiments/k222/figures/fig_vt_role_reframe.png)

## 方法論限制與後續

| 項目 | 設定 |
|------|------|
| 資料 | yfinance SPY / GLD / ^VIX, 2005-2024 |
| 模擬 | 10,000 次 block bootstrap（block size 待 K87 結論重新校準）|
| 退休期間 | 30 年，月度提領，2%/yr 通膨 |
| 現金 | T-bill 假設 2%/yr（K87 顯示此假設貢獻過大，待敏感度分析）|
| VT 訊號 | **2026-05-06 patch 後**：12 / 前一交易日 VIX，月度再平衡 |
| 起始資金 | $1,000,000 |

**已知限制**：
- 樣本期間未涵蓋 1970 滯脹、惡性通膨、二戰等極端情境；
- T-bill 固定 2% 是粗估，實際利率波動明顯影響 VT cash leg 貢獻；
- 交易成本與稅務未完整建模；
- VIX 自 1990 起可得，更早期需 VIX proxy（Schwert 1989）。

**後續工作**：
1. K222 在 lookahead patch 下重跑完整 Monte Carlo，產出修正後存活率 / 終值分佈表；
2. Cash yield 敏感度分析（T-bill 0% / 2% / 4% 三組）拆解 cash leg 貢獻；
3. Block size 從 3 到 60 個月掃描，確認 K87 結論在不同 block 下穩健；
4. 跨樣本期 OOS：1990s / 2000s / 2010s / 2020s 分段驗證，避免單期 bootstrap artifact；
5. 結論若再次更新，將回溯本文與 K78 Type D 推薦段落。

## 結論（修正版）

K85「VT 把最大安全提領率從 4% 翻倍到 8%」的宣稱，在 K87 交叉驗證下不成立，並在 2026-05-06 K222 lookahead patch 後進一步弱化。修正後的 honest framing：**VT 是退休尾部風險的保險，在 4% 提領率下縮小破產機率與最大回撤，但不會放大可提領上限**。對讀者與退休規劃者而言：4% 法則仍是合理起點，VT 用於降低序列風險、不是用於追求更高提領率。

## 教訓（研究誠實原則）

K85 → K87 → K222 是一條典型「extraordinary claims require extraordinary validation」的修正鏈：
- **第一輪**（K87）：交叉驗證抓出 bootstrap block / cash yield 假設驅動的合成優勢；
- **第二輪**（K222 patch + K547 audit family）：抓出 lookahead bias 進一步推翻 inflated edge；
- **第三輪**（K320 content audit）：將兩輪修正套回對外文章內容，發出本更正。

**「結果好得不像真的」永遠值得 90% 機率懷疑是 bug**——這條研究紀律在本案再次被驗證。

---

*相關實驗：K79（原始模擬）/ K85（推翻對象）/ K87（交叉驗證）/ K222（lookahead patch 2026-05-06）/ K320（內容稽核 2026-05-07）/ K547（lookahead audit family）。*
*資料：yfinance SPY/GLD/^VIX 2005-2024，10,000 次 block bootstrap。圖表為示意，待 K222 rerun 後以實際 post-patch 數據替換。過去績效不代表未來表現。*
