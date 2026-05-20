---
title: "波動率聚集真的能設計成 timing 策略嗎？K576 NULL：12/VIX 已經把它做進去了"
audience: general
status: draft
phase: methodology
tags: vol-clustering,vix,vt-strategy,null-result,methodology
kid: K576
experiment_refs: K576
---

# 波動率聚集真的能設計成 timing 策略嗎？K576 NULL：12/VIX 已經把它做進去了

> **K576 一句話**：把「波動率聚集」（volatility clustering）轉成 4 種 cluster-based timing 策略，跨 5 個 OOS 期間實測下來，**沒有一個在風險調整後的表現上勝過 12/VIX 基準**（所有 cross-OOS Sharpe 差的 p 值都 > 0.13）。原因不是「聚集不存在」——而是 **12/VIX 本身就是一個 continuous 版本的 cluster exploiter**，cluster overlay 想做的事它已經做了。

## 為什麼這個問題會讓研究者反覆繞回來

打開任何一本實證金融教科書，「波動率聚集」幾乎是第一個被點名的 stylized fact：

- Engle (1982, *Econometrica*) 在 ARCH 模型開篇就描述「大震盪後常常跟著大震盪」
- Cont (2001, *Quantitative Finance*) 列舉的金融時序 11 大 stylized facts，volatility clustering 排第一

直覺上這是免費的午餐：既然知道風險來了會「黏著」一陣子，理論上就可以**避開高 vol 區段、搶佔 vol 回落的反彈**。VT（volatility targeting）策略族群的一個經典變體就是想抓這個 dynamic — 偵測到 cluster 進場時就降槓桿，看到 cluster 結束就加碼。

問題是：這條路在這個工作站之前已經反覆走過幾次：

- **K260**：cluster duration（聚集會持續多久）的預測，對策略價值是零
- **K571**：VIX 均值回歸速度的快慢，慢慢進場反而傷害績效；12/VIX 已是最佳分母
- **K109**：用 Hawkes process 做 jump 觸發建模，被 GARCH 連續 tracking 完全壓過

K576 是把這個問題**正面、徹底地再實測一次**——這次特別針對「cluster timing 是不是 VT 策略可以再加分的維度」，跨 5 個 OOS 期間 + Harvey (2016) 嚴格統計門檻。

## K576 是怎麼設計的

**資料**：SPY + ^VIX，2005-01-03 到 2026-03-26，共 5,341 個交易日（涵蓋 2008 GFC、2010 歐債、2015 中國、2018 vol-mageddon、2020 COVID、2022 升息熊、2025 修正）。

**Cluster 定義**：VIX 連續 5 天以上高於自身 22 日 MA → 判定進入「聚集」；VIX 第一天跌回 MA 以下 → cluster 結束。整個 21 年樣本共偵測到 **147 個 clusters**，平均持續 11.6 天、中位數 10 天，最長 43 天。

**Post-cluster 反彈是真的**：cluster 結束後 5 天平均報酬 +1.22%（t=6.13）、10 天平均 +1.80%（t=6.31）。這不是雜訊，是真實的可觀察 pattern。

**4 個 cluster overlay 策略**（基準是 12/VIX 標準 VT）：

1. **post_cluster_boost**：cluster 結束後 10 天用 15/VIX（更積極）
2. **duration_scaling**：cluster 持續越久，事後 k 越大（12→18，加快回到滿倉）
3. **pre_cluster_defense**：VIX 5 日加速 >20% 朝 MA 衝 → 用 10/VIX（提前防守）
4. **cluster_count**：60 天內出現 ≥3 次 clusters → 切到 10/VIX（高頻聚集警戒）

每個策略都有 **`signal.shift(1)` 等效 lag**，無 lookahead；DM 檢定 + Harvey cross-OOS Sharpe t-test 雙重評估。

## 真實結果：報酬可以多賺，但風險同比例多扛

### 圖 1：4 個策略的 full-sample Sharpe vs 12/VIX

![圖 1：full-sample Sharpe 比較](/experiments/k576/k576_fig1_sharpe_compare.png)

| 策略 | 年化報酬 | 年化波動 | Sharpe | MDD |
|---|---:|---:|---:|---:|
| **12/VIX baseline** | 6.70% | 9.45% | **0.7092** | −28.6% |
| post_cluster_boost | 7.27% | 10.01% | 0.7267 | −30.3% |
| duration_scaling | 7.09% | 9.98% | 0.7104 | −31.8% |
| pre_cluster_defense | 6.71% | 9.45% | 0.7099 | −28.5% |
| cluster_count | 6.40% | 9.26% | 0.6914 | −28.4% |

5 個策略的 Sharpe 全部聚在 **0.69–0.73** 一個極窄區間。最有戲劇性的 post_cluster_boost 確實**多賺 0.57 個 pp 年化報酬**，但代價是波動 +0.56 pp、MDD 多吃 1.6 pp——按比例還掉之後 Sharpe 從 0.7092 變 0.7267，幾乎是統計噪音。

### 圖 2：跨 5 個 OOS 期間的 Sharpe 差 + 嚴格 p 值

![圖 2：cross-OOS Sharpe 差](/experiments/k576/k576_fig2_cross_oos.png)

| 策略 | 平均 Sharpe 差 | 5 期勝率 | 嚴格統計 p |
|---|---:|:---:|---:|
| post_cluster_boost | +0.0206 | 3 / 5 | 0.262 |
| duration_scaling | +0.0052 | 3 / 5 | 0.827 |
| pre_cluster_defense | +0.0008 | 3 / 5 | 0.488 |
| cluster_count | −0.0168 | 1 / 5 | 0.138 |

**全部 p 值 > 0.13**，沒有一個達到 Harvey (2016) 在 *Review of Financial Studies* 提出的多重檢定門檻（須 |t| ≥ 3.0）。即便 post_cluster_boost 在 5 個期間平均 Sharpe 差 +0.0206 也只是「方向對、幅度小、不顯著」。

### 圖 3：post_cluster_boost 拆解——為什麼報酬增加，Sharpe 卻不動

![圖 3：報酬／風險拆解](/experiments/k576/k576_fig3_return_risk_decomp.png)

最有趣的策略 post_cluster_boost：年化報酬 **+8.5%**（相對基準），年化波動 **+5.9%**——分子分母幾乎同比例膨脹，Sharpe 紋風不動。**這是 cluster overlay 失效的 mechanism**，不是「策略爛」，是「baseline 已經把這件事內生地做了」。

## 核心 insight：12/VIX 本身就是 continuous vol-cluster exploiter

VT 策略 `weight = 12/VIX` 的數學特性是**自動 cluster scaling**：

- VIX = 40（cluster 中）→ 權重 = 0.30
- VIX = 30（cluster 開始消退）→ 權重 = 0.40
- VIX = 20（cluster 結束）→ 權重 = 0.60
- VIX = 12（持續低 vol）→ 權重 = 1.00

**這個 1/VIX 反比關係本身就是 continuous cluster exploitation**。當 cluster 進來、VIX 拉高 → 自動降槓桿；當 cluster 結束、VIX 回落 → 自動加碼搶反彈。所有 cluster overlay 策略想做的「discrete event timing」，都只是這條 continuous 曲線的離散近似版本——而離散版只會在轉折點對；連續版每一天都對。

這就是為什麼**「事後反彈是真實 pattern」**（10 天平均 +1.8%、t=6.31）和**「策略不顯著」**可以並存：可獲取的部分早就被 1/VIX 抓走了，cluster 規則只是**重新切片同一塊蛋糕**。

## 連結 evidence chain：K260 → K571 → K109 → K576

K576 不是孤立的 NULL，是一條一致的證據鏈：

- **K260**：「預測 cluster 還會持續多久」對策略價值 = 零（duration timing 不貢獻 alpha）
- **K571**：把 12/VIX 改成 cluster 結束後「慢慢進場」的版本反而傷害績效（slow re-entry harmful；continuous 比 ramp 好）
- **K109**：Hawkes process（discrete jump intensity 建模）被 GARCH（continuous variance tracking）完全壓過
- **K576**：4 種 cluster overlay 策略全部沒贏 continuous 12/VIX

四個獨立實驗、不同切入點、同一個結論：**continuous variance tracking 已經是 vol clustering 的最佳形式利用**，discrete overlay 不是再優化、是再切片。

## 對讀者的兩個 takeaway

**第一**，stylized fact 真實 ≠ 可獲取。Engle 與 Cont 描述的 vol clustering 100% 真實——本實驗 147 個 clusters、t=6.31 的 post-cluster 反彈是直接證據——但 *真實* 跟 *能否再被另一層策略再利用* 是兩件事。前者是統計性質，後者要過 Harvey p 值 + cross-OOS robustness 雙關。

**第二**，看到「策略多賺 X%」先看波動。post_cluster_boost +8.5% 報酬聽起來性感，但 +5.9% 波動拉走了風險溢酬——這是 VT/leverage 策略族群的標準陷阱：分子分母同比例膨脹是 noise，不是 alpha。

## 下一步

NULL 不代表終點，是對假說的釐清。可探索的方向：

- **Regime-switching VT**：不是 cluster on/off，而是 high-vol / low-vol 兩個 1/VIX 曲線斜率自切換（當前 K-family 第二批候選）
- **跨資產 vol clustering**：cluster 在 ES、商品、FX、新興市場的可獲取性是否不同（K480 系列指向台灣、新興市場可能有殘餘 alpha）
- **Realized vol cluster**：實現波動而非 IV 的 clustering（IV 含 risk premium，RV 是純物理量）

---

**研究誠實聲明**：本文所有數字直接 byte-for-byte 對應 `experiments/k576/k576_vol_clustering_vt_results.json`；策略 lag 在 `k576_vol_clustering_vt.py` 內以 signal-at-t-1 / return-at-t 強制；cross-OOS 5 個期間每一個都跑了完整 Harvey Sharpe t-test。所有 PNG 為 matplotlib 即時生成，無人工修飾。

**參考文獻**：
- Engle, R. F. (1982). Autoregressive conditional heteroscedasticity. *Econometrica*, 50(4).
- Cont, R. (2001). Empirical properties of asset returns: stylized facts and statistical issues. *Quantitative Finance*, 1.
- Harvey, C. R., Liu, Y., Zhu, H. (2016). ...and the cross-section of expected returns. *Review of Financial Studies*, 29.
- Hillebrand, E. (2005). Neglecting parameter changes in GARCH models. *Journal of Econometrics*.
- 內部實驗：K260（cluster duration zero value）、K571（12/VIX optimal）、K109（Hawkes vs GARCH）、K491（universal persistence law）。
