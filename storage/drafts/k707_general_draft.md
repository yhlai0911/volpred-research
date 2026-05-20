---
title: "散戶 20 問完整 FAQ：86 個實驗濃縮的答案（K707）"
audience: general
status: draft
tags:
  - faq
  - investor
  - vix
  - vt-strategy
  - allocation
  - cross-experiment
  - retail
experiment_refs:
  - K707
---

# 散戶 20 問完整 FAQ：86 個實驗濃縮的答案

> 「VIX 能預測明天漲跌嗎？」「最佳配置是什麼？」「VT 真的賺更多嗎？」過去一年多，研究系統累積了 86 個關於波動率與資產配置的實驗。K707 把這 86 個實驗的結論，濃縮成散戶最常問的 20 個問題與一句話答案。

[提出: VolPred 研究系統, 執行: Claude]

## K707 是什麼？跟 K703 有什麼不同？

K703（10 個數字 cheatsheet）把研究結論壓成「一張可貼桌邊的數字小抄」；**K707 走相反方向——以「讀者的問題」為主軸**，把 86 個實驗（K621–K706）重組成 20 個 Q&A 對。每個問題都有：

- 一句話答案（適合直接 quote）
- 詳細解釋（為什麼這樣？）
- 證據字典（哪幾個數字？）
- 對應實驗（哪幾個 K？）
- 信心等級（high / medium / low）

K703 是「**結論**」的 ranking，K707 是「**問題**」的 mapping。兩者互補：你想知道某個數字 → 查 K703；你想知道某個情境怎麼做 → 查 K707。

## 設計：誠實的 cross-K 彙整

86 個實驗中，K707 直接引用了其中 25 個獨特實驗（其餘 61 個是 supporting evidence、被間接合成成結論）。20 個問題的信心分佈是：

- **High confidence: 14 個**（多實驗交叉驗證 + Codex 審過）
- **Medium confidence: 6 個**（單一實驗或 effect size 較小）
- **Low confidence: 0 個**（會被退回研究階段）

這個分佈本身就是誠信宣示——我們不會把每個答案都標 high 給讀者「全包套餐」的錯覺。

### 圖表

#### 圖 1：20 問題 × 7 主題 × 信心度

![K707 問題分佈：資產配置 5、VT 策略 4、交易執行 4、市場預測 3、方法論 2、風險控制 1、總結 1](experiments/k707/k707_category_distribution.png)

7 個主題中**資產配置（5 題）+ VT 策略（4 題）+ 交易執行（4 題）= 65% 的問題**集中在這三類——也是散戶最關心的「我該買什麼？怎麼調？怎麼省手續費？」。市場預測（3 題）的答案幾乎都是「不能精準預測」。

## 選 8 個 SEO 高價值的問題詳細寫

20 個問題若全部展開會變 4000+ 字。以下挑出**最高 SEO 價值 + 最具 share 潛力**的 8 題，其餘 12 題在最後「速答清單」帶過。

### Q1: VIX 能預測明天漲跌嗎？— **不能**

VIX 預測**波動率大小**的相關係數是 0.570（中等強度），但預測**漲跌方向**的相關係數只有 **0.042**——基本上是 0。即使讓你用「完美事後資訊」基於 VIX 調倉（oracle 策略），Sharpe 也只從 0.86 升到 1.143——而代價是每年換手 73.7 次，扣掉交易成本後 alpha 消失。

> VIX 告訴你「明天會震多大」，**不告訴你「往哪個方向震」**。

證據出處：K697 + K626。信心：high。

### Q2: 什麼配置最好？— **50/50 SPY/GLD**

在 21 種配置的網格搜尋中，**50% SPY + 50% GLD 的 Sharpe 最高（0.548）**，打敗：

- 60/40 SPY/GLD（0.536）
- 60/40 SPY/TLT（0.420）
- Markowitz 最優化（0.405）
- 風險平價（0.369）
- 100% SPY（0.395）

DM 統計檢定顯示：**沒有任何配置在統計上顯著優於 50/50**。背後原因——SPY 和 GLD 波動率幾乎相同（19.32% vs 18.31%），相關性極低（0.058），50/50 本身就是最優的風險平價配置，不需要任何最佳化。

證據出處：K702 + K704 + K645。信心：high。

### Q3: VT（波動率目標）策略能賺更多嗎？— **Sharpe 不行，MDD 大降**

修正所有 lookahead bias 後（K686 + K687），**沒有任何 VT 策略在 Sharpe 上打敗 BH 50/50**（0.545）。最接近的 EWMA VT 也只有 0.525。

但 VT 真正的價值在風險控制：

| 策略 | Sharpe | MDD |
|---|---|---|
| BH 50/50 SPY/GLD | 0.545 | -32.49% |
| EWMA VT | 0.525 | **-17.03%** |
| 12/VIX VT | 0.438 | **-12.21%** |

對於風險厭惡程度 γ ≥ 5 的投資人，EWMA VT 在 CRRA 效用框架下勝出。**VT 是 drawdown insurance，不是 alpha generator**。買它的理由是「我不能承受 32% drawdown」，不是「我想多賺幾個百分點」。

證據出處：K687 + K688 + K690。信心：high。

### Q7: 恐慌時要賣嗎？— **不要！等 VIX 回到 Normal**

VIX spike 後的平均回歸**半衰期 10.2 天**。VIX 從 >25 回到 <20 的中位數時間是 15 天，回到 <15 是 95 天。**在 VIX 回歸期間，SPY 的年化報酬率高達 33.7%（Sharpe 1.34）**。馬可夫鏈分析（K673）確認：Crisis 狀態 45% 機率在 1 個月內回到 Normal。

**恐慌時賣出 = 賣在最低點 + 錯過回彈**。正確做法：什麼都不做，等待回歸；如果有現金，VIX 跌破 30 後 60 天的平均累積報酬是 +7.21%。

證據出處：K658 + K673。信心：high。

### Q11: 黃金為什麼有效？— **報酬相近 + 相關性極低 + 危機時有 alpha**

GLD 有效的三個原因：

1. **報酬與 SPY 相當**（CAGR 10.53% vs 10.42%）——不是「死錢」避險
2. **與 SPY 相關性接近零**（0.058）——50/50 配置讓組合波動率從加權平均 18.8% 降至 13.5%（**降 27.2%**）
3. **危機時（VIX > 30）GLD 年化報酬 +12.24%**——提供正向 alpha

**黃金的價值不是「危機時飆漲」，而是「一直有報酬 + 一直不相關」**。這就是 return parity 的威力，也是為什麼 50/50 SPY/GLD 比加 TLT、加 EFA 都更好。

證據出處：K645 + K702。信心：high。

### Q14: 最大可能虧多少？— **50/50+VT 的 1 年 MDD>20% 機率為 0**

K664 的滾動窗口 drawdown 分析（4,837 個窗口）：

| 策略 | P(1 年 MDD > 10%) | P(1 年 MDD > 20%) |
|---|---|---|
| BH SPY | 57.0% | 高 |
| Piecewise Conservative | **5.3%** | 0% |
| 50/50 SPY/GLD + 12/VIX | — | **0%** |

**Piecewise 將 P(MDD > 10%) 相對 SPY 降低 91%**。如果你完全無法承受超過 10% 的虧損，Piecewise Conservative 是唯一選擇——但要付出代價（見 Q18）。

證據出處：K664（4,837 窗口 bootstrap）。信心：high。

### Q18: 保守型策略的代價是什麼？— **CAGR 從 11.4% 跌到 3.1%，放棄 73% 報酬**

Q14 的 Piecewise Conservative 看起來很美——直到你看到代價。

| 指標 | BH 50/50 | Piecewise Conservative |
|---|---|---|
| CAGR | 11.38% | 3.13% |
| Sharpe | 0.856 | 0.61 |

機會成本 72.5%。原因是 VIX ≥ 20 就強制降倉，但 **VIX 20–25 區間的預期報酬其實是正的**——Piecewise 的 avoidance ratio 高達 84.9%，意思是 85% 的「避開損失」其實是避開了正報酬。

> 如果你風險承受度高，保守策略代價太大；如果你 γ ≥ 10（極端保守），它的 CRRA 效用仍有價值。

證據出處：K654。信心：high。

### Q19: Codex/AI 審查重要嗎？— **非常重要**

K700 統計：**80 個實驗中有 4 次 Codex 審查，每次都抓到關鍵 bug**。最戲劇性的是 K679：原始報告 Sharpe 1.68 看起來爆強——Codex 一審發現 same-day lookahead，修正 lag 後 Sharpe 跌到 **0.355**（修正後跌幅 1.325 Sharpe points，**100% 是 artifact**）。

**如果沒有 Codex 審查，會發佈 3 個錯誤的「突破性發現」**。教訓很簡單：

> 任何 Sharpe > 1.0 的策略結果，發佈前必須經過獨立審查。
> 「研究結果好得不像真的」= 90% 有 bug。

8 個被推翻的結論中，3 個是 Codex 直接抓到的。這也是為什麼信心分佈裡沒有 low——low 信心的會被退回研究階段，不會以 Q&A 形式定稿。

證據出處：K700 + K686 + K619 + K623。信心：high。

#### 圖 2：10 個最有 SEO 價值的問答 + 關鍵數字

![K707 top 10 answers：每題一句話答案 + 一個關鍵數字](experiments/k707/k707_top10_answers.png)

#### 圖 3：4 種散戶 × 5 大主題的行動地圖

![K707 persona action map：新手散戶/上班族/風險厭惡/退休族在配置/VT/Rebalance/DCA/風控的建議強度](experiments/k707/k707_persona_action_map.png)

不同 persona 的最佳組合不一樣：新手散戶把錢分到配置 + 月定投就好；風險厭惡型加 VT + 風控；退休族 VT + 風控優先於 DCA。

## 速答清單：剩餘 12 題

> 全文版本見 `experiments/k707/k707_results.json`，每題都附證據 dict + 對應 K 編號。

| Q | 短答 | K | 信心 |
|---|---|---|---|
| Q4 多久 rebalance？ | 美股每日，台股月頻 | K642 | high |
| Q5 多少錢起步？ | 美股 US$5,000，台股 15 萬 | K633/K632 | medium |
| Q6 0050 一張多少？ | 約 75,000 元（減資後） | K633 | medium |
| Q8 VIX 多少算高？ | >25 算高（17.2% 交易日），加 lag 後沒 alpha | K679/K686 | high |
| Q9 ETF 成本多少？ | 美股 2bp，台股 18.5bp（9.25 倍） | K642 | high |
| Q10 BTC 能避險？ | 不能，尾部相依 4.25 倍 | K639 | high |
| Q12 退休金該用 VT？ | 怕虧損就該用，降 sequence risk | K668/K688 | medium |
| Q13 每月定投怎做？ | Fear DCA，VIX>25 加碼 4% | K632/K670 | medium |
| Q15 NFP 重要嗎？ | 看 VIX regime，VIX>25 時效果消失 | K661 | medium |
| Q16 何時加碼？ | VIX 跌破 30 後，60 天均報酬 +7.21% | K658 | medium |
| Q17 複雜打敗簡單？ | 不會，50/50 打敗 Markowitz/Risk Parity | K702/K704 | high |
| Q20 一句話總結？ | 「50/50 SPY/GLD，不要動，怕虧加 EWMA VT」 | K687/K688/K697/K700/K702 | high |

## 限制與誠實 framing

- **僅限 US/TW 市場**：86 實驗的數據主要來自 SPY、GLD、^VIX、0050.TW，無法保證歐洲、亞洲新興市場適用
- **20 年樣本含特殊期間**：含 2008 GFC + 2020 COVID + 2022 升息，未來不一定重演
- **稅務未建模**：不同國家稅制差異大，沒納入 CAGR 計算
- **VIX ≠ realized vol**：VIX 是 implied vol，與已實現波動率有 risk premium gap
- **BTC 後 2020 相關性 regime shift 仍在演化**：Q10 的結論可能 5 年後需要更新

## 學術 framing

K707 的 cross-K aggregation 方法論連接到三條主線：

- **DeMiguel, Garlappi & Uppal (2009) RFS**——1/N 配置打敗最佳化（呼應 Q2 + Q17）
- **Moreira & Muir (2017) JF**——Volatility-managed portfolios（呼應 Q3）
- **Harvey, Liu and Zhu (2016) JFE**——multiple testing 在金融研究的破壞力（呼應 Q19 + Codex 審查紀律）

下一步研究方向：

1. K708+：把 K707 結論套到歐洲（VSTOXX/STOXX600）+ 日本（VXJ/Nikkei225），檢驗外推性
2. 把 86 實驗的 cross-K aggregation 流程寫成 reproducible pipeline，後續每 50 個新 K 自動更新一版 FAQ
3. 把 K703（numbers cheatsheet）+ K707（Q&A）+ K263（260+ map）整合成「散戶投資完整知識庫」單頁

## 參考文獻

- DeMiguel, Garlappi & Uppal (2009) *RFS* — Optimal vs Naive Diversification
- Moreira & Muir (2017) *JF* — Volatility Managed Portfolios
- Harvey, Liu and Zhu (2016) *JFE* — ...and the Cross-Section of Expected Returns
- Copeland & Copeland (1999) *JPC* — Market Timing with VIX
- RiskMetrics (1996) — Technical Document (EWMA λ=0.94)
- Maillard, Roncalli & Teiletche (2010) *JPM* — Risk Parity
- Markowitz (1952) *JoF* — Portfolio Selection
- Diebold & Mariano (1995) — Comparing Predictive Accuracy

---

**延伸閱讀**：
- K703「19 年研究濃縮成 10 個數字」——數字版 cheatsheet
- K263「260+ 場實驗濃縮成一張地圖」——主題地圖版
- K672「波動率預測研究的定論與開放問題」——定論 + 開放問題對照

**資料來源**：yfinance（SPY、GLD、^VIX、0050.TW、BTC-USD、TLT、EFA），2006–2026，~5,088 交易日。完整證據見 `experiments/k707/k707_results.json`。
