# 波動率預測與波動率目標策略：2024-2026 最新文獻回顧

> 搜尋日期：2026-03-21
> 涵蓋範圍：arXiv, SSRN, JFE, RFS, JBF, Mathematical Finance, J. Applied Econometrics, J. Futures Markets, Quantitative Finance, Financial Innovation 等

---

## 一、波動率預測新方法（GARCH 家族的挑戰者）

### 1.1 MF2-GARCH：多頻率 GARCH 模型 ★★★
- **論文**: Conrad & Engle (2025), "Modelling Volatility Cycles: The MF2-GARCH Model", *Journal of Applied Econometrics*, 40(4), 438-454
- **核心發現**: 結合短期 GJR-GARCH + 長期乘法誤差模型 (MEM)。長期組件利用 GARCH 標準化殘差的可預測性，動態調整短期預測。在 S&P 500 的長期 OOS 預測中，**顯著優於** 單組件 GJR-GARCH、GARCH-MIDAS-RV 和 log-HAR
- **與我們的關聯**: 直接挑戰我們目前的 GJR-GARCH 主力模型。MF2-GARCH 的優勢在於「短暫波動率飆升後不會過度高估」——這正是我們 VT 策略中 GJR 的已知問題
- **複製建議**: ★★★ 強烈建議。Conrad & Engle 已提供 Matlab 工具箱 (github.com/juliustheodor/mf2garch)，且 NYU V-Lab 已大規模應用於 2100+ 個股。需要移植為 Python 版本
- **來源**: https://onlinelibrary.wiley.com/doi/full/10.1002/jae.3118

### 1.2 「線性模型打不敗嗎？」 ★★★
- **論文**: Branco, Rubesam & Zevallos (2024), "Forecasting Realized Volatility: Does Anything Beat Linear Models?", *Journal of Empirical Finance*, 78
- **核心發現**: 評估 10 個全球股市指數（2000-2021），結論：(1) 額外預測因子在日/週頻改善 OOS 預測; (2) **非線性 ML 模型整體無法顯著優於線性模型**; (3) 經濟價值方面，**更簡單的模型反而更好**
- **最佳模型分類**: 統計精度 → leveraged HAR/HARX; VaR 準確性 → 神經網路; 經濟價值 → leveraged HAR + semi-variance HAR
- **與我們的關聯**: 這直接驗證了我們的 Phase J 核心發現——12/VIX 這種極簡方法在經濟價值上最優。「no single model dominates all three categories」呼應我們的 CCS Score 結論
- **複製建議**: ★★ 不需複製，但引用為理論支撐。Leveraged HAR 值得嘗試（加入 leverage term 到 HAR 模型）
- **來源**: https://www.sciencedirect.com/science/article/abs/pii/S0927539824000598

### 1.3 圖神經網路 (GNN) + HAR 跨資產波動率預測 ★★
- **論文**: Zhang et al. (2025), "Forecasting Realized Volatility with Spillover Effects: Perspectives from Graph Neural Networks", *International Journal of Forecasting*, 41(1), 377-397
- **核心發現**: 用 GNN 建模跨資產波動率溢出效應，短期（1 天至 1 週）預測準確度顯著提升。提出 GNN-HAR 架構
- **論文 2**: arXiv 2410.22706 — Graph Signal Processing + HAR，用圖傅立葉變換捕捉全球股市動態
- **與我們的關聯**: 我們的跨資產 VT 研究（K25: 國際股市 VIX 通用性）可能受益於波動率溢出建模
- **複製建議**: ★ 低優先。概念有趣但實作複雜度高，且我們的策略以月度 VT 為主，溢出效應在月度頻率可能不重要
- **來源**: https://www.sciencedirect.com/science/article/abs/pii/S0169207024000967

---

## 二、HAR-RV 與 Realized Volatility 進展

### 2.1 HAR-RV-CARMA：Kalman 濾波加權混合模型
- **論文**: HAR-RV-CARMA (2025), *MDPI Risks*, 13(11), 223
- **核心發現**: 結合 HAR-RV 與連續自迴歸移動平均 (CARMA) 模型，用 Kalman 濾波動態權重機制融合兩者。減少過擬合
- **與我們的關聯**: 我們的 HAR-RV 正在等待足夠 5-min 數據。此模型提供了一個可能的增強方向
- **複製建議**: ★ 低優先。等 5-min 數據累積到 252 天再考慮
- **來源**: https://www.mdpi.com/2227-9091/13/11/223

### 2.2 Uncertain HAR-RV 模型（不確定性理論）
- **論文**: Shi (2026), "Uncertain HAR-RV Models and Their Extensions", *Journal of Futures Markets*
- **核心發現**: 用不確定性理論替代概率理論來建模 HAR-RV，應用於中國原油期貨波動率預測
- **與我們的關聯**: 方法論新穎但與我們的股票/ETF 研究方向較遠
- **複製建議**: ☆ 不建議
- **來源**: https://onlinelibrary.wiley.com/doi/10.1002/fut.70049

### 2.3 HAR + 機器學習方向性預測 ★★
- **論文**: (2024), "Predicting Directional Volatility: HAR Model with Machine Learning Integration", *Applied Economics Letters*
- **核心發現**: SVM 在波動率方向性預測中表現最佳，持續產生顯著的經濟收益
- **與我們的關聯**: 方向性預測（波動率上升或下降）可能對 VT 策略的 rebalancing 決策有用
- **複製建議**: ★ 有興趣但非核心。等 HAR 基礎模型完成後再考慮加入 SVM 層
- **來源**: https://www.tandfonline.com/doi/full/10.1080/13504851.2024.2401512

### 2.4 RV 預測綜合回顧 ★★★
- **論文**: (2025), "Advances in Forecasting Realized Volatility: A Review of Methodologies", *Financial Innovation*
- **核心發現**: 2000-2024 年 RV 預測文獻全面回顧。**混合 CNN-LSTM 模型在預測精度上排名最高**。但該論文同時指出研究缺口和改進建議
- **與我們的關聯**: 極佳的文獻地圖。可作為論文引用的核心參考
- **複製建議**: ★★ 閱讀全文並更新我們的 model hierarchy
- **來源**: https://link.springer.com/article/10.1186/s40854-025-00809-5

---

## 三、VT（波動率目標）策略新變體

### 3.1 VT = Trend Following？ ★★★★
- **論文**: Hood & Raughtigan (2024/2025), "Volatility Targeting Is Trendy: How Trend Following Explains Alpha in Volatility-Managed Strategies", SSRN 4773781 → *Journal of Portfolio Management*, 2025
- **核心發現**: VT 的超額報酬主要來自 **trend following 暴露**——因為 leverage effect（報酬方向與波動率幅度的負相關）使得 VT 自然嵌入了動量信號。**控制 trend exposure 後，equity VT 的 alpha 消失**。但 commodity、fixed income、FX 的 leverage effect 不存在，所以結論不適用
- **與我們的關聯**: ★★★★ 非常重要！這解釋了我們 K21（commodity VT 失敗）和 K24（HY bond VT 失敗）的結果——**沒有 leverage effect 就沒有 VT alpha**。也呼應 Q19 gamma-mechanism 只在 pure equity 成立
- **複製建議**: ★★★ 應該複製。分解我們現有策略的 VT alpha 到 trend component 和 non-trend component。這可能成為論文的重要引用
- **來源**: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4773781

### 3.2 多因子波動率管理組合 ★★★
- **論文**: DeMiguel, Martin-Utrera & Uppal (2024), "A Multifactor Perspective on Volatility-Managed Portfolios", *The Journal of Finance*, 79(6)
- **核心發現**: 條件均值-方差多因子組合（權重隨市場波動率降低）OOS + 淨成本 Sharpe 比無條件組合**高 13%**（1% 顯著水準）。因子風險價格通常隨市場波動率下降
- **與我們的關聯**: 我們的 50/50 SPY/GLD VT 是簡化版。此論文提供了更嚴格的理論框架
- **複製建議**: ★★ 理論支撐，但實作複雜度可能超出零售投資者可用範圍
- **來源**: https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13395

### 3.3 條件 VT + Jump 風險 ★★
- **論文**: (2024), "Conditional Volatility Targeting Strategy Considering Jump Effects: Evidence from Sustainable ESG Equity Index", *Pacific-Basin Finance Journal*
- **核心發現**: 用 ARMA-GARCH-Jump 模型捕捉跳躍持續性，在 ESG 股指上實現更高績效
- **與我們的關聯**: Jump risk 是我們尚未探索的維度。我們的 GJR-GARCH 不含 jump component
- **複製建議**: ★ 中低。加入 jump component 到 GARCH 是可行的擴展
- **來源**: https://www.sciencedirect.com/science/article/abs/pii/S0927538X24002774

### 3.4 VT 最佳再平衡邊界 ★★★
- **論文**: (2025), "Target Volatility Strategies: Optimal Rebalancing Boundary for Transaction Cost Minimization", *Financial Markets and Portfolio Management*
- **核心發現**: 加入再平衡邊界（不是每天調整，而是權重偏離超過閾值才調整）可降低交易成本同時維持風險控制
- **與我們的關聯**: ★★★ 直接相關！我們已知月度再平衡優於日度（J10），這篇提供了理論最優解
- **複製建議**: ★★★ 強烈建議。測試不同 rebalancing boundary levels 對我們 12/VIX 策略的影響
- **來源**: https://link.springer.com/article/10.1007/s11408-025-00486-5

### 3.5 Research Affiliates 多資產 VT ★★
- **論文**: Research Affiliates (2024), "Harnessing Volatility Targeting in Multi-Asset Portfolios"
- **核心發現**: 5% vol target 多資產指數（226 全球股市 + 政府債 + 商品期貨）。尾部風險管理：短期 RV > 7% 時清倉到現金。全樣本 VT 組合 Sharpe 高於非管理組合，但 2009-2019 低波動期反而落後
- **與我們的關聯**: 「低波動期 VT 落後」呼應我們的 K36/K39/K40 trilogy（保險費會複合）
- **複製建議**: ★ 概念已驗證，不需複製
- **來源**: https://www.researchaffiliates.com/publications/articles/1014-harnessing-volatility-targeting

---

## 四、機器學習波動率預測（OOS 有效的）

### 4.1 Transformer 架構 ★★
- **論文**: (2025), "Deep Learning and Transformer Architectures for Volatility Forecasting: Evidence from U.S. Equity Indices", *MDPI JRFM*, 18(12), 685
- **核心發現**: PatchTST、Informer、Autoformer 優於第一代 Transformer。**混合 CNN-Transformer 架構同時優於傳統 DL 和計量模型**
- **與我們的關聯**: 我們已測試 LSTM 失敗（日頻殘差 iid），但 Transformer 架構可能不同
- **複製建議**: ★ 低優先。需要大量數據和調參，且 Branco et al. (2024) 已表明經濟價值方面簡單模型更好

### 4.2 ML 波動率 + 經濟價值 ★★
- **論文**: (2025), "Volatility Forecasting and Volatility-Timing Strategies: A Machine Learning Approach", *Research in International Business and Finance*
- **核心發現**: ML 波動率模型構建的 timing 組合在高波動期表現優異。Bagged CART 優於線性分類模型 0.47-0.79%/月
- **與我們的關聯**: 「高波動期表現優異」——但低波動期呢？VT 的核心問題是 unconditional performance
- **複製建議**: ★ 低。與我們的 12/VIX 簡單方法相比，增量可能微小

### 4.3 Options-Driven 波動率預測 ★★★
- **論文**: Michael, Cucuringu & Howison (2025), "Options-Driven Volatility Forecasting", *Quantitative Finance*, 25(3)
- **核心發現**: 用 IV surface 降維（PCA）+ Heston/Bates 模型校準提取隱含波動率，增強 HAR 模型的日頻預測。**選擇權資訊可以顯著改善 RV 預測**
- **與我們的關聯**: 這正是 Codex/Gemini 建議的方向——options-implied surface (VVIX/SKEW/VIX term structure)
- **複製建議**: ★★★ 中高。需要取得 VIX term structure 數據，但概念可用簡化版實現（例如用 VIX/VIX3M 比率）
- **來源**: https://www.tandfonline.com/doi/full/10.1080/14697688.2025.2454623

---

## 五、VIX 期限結構 / VVIX 研究

### 5.1 VVIX 跳躍分解與 VIX 預測 ★★
- **論文**: Qiao, Cui, Zhou & Liang (2025), "Volatility of Volatility and VIX Forecasting: New Evidence Based on Jumps, the Short-Term and Long-Term Volatility", *Journal of Futures Markets*, 45(1), 23-46
- **核心發現**: 基於高頻 VIX 數據，用小波分析分解跳躍和短/長期波動率成分。結合 HAR-DJI-GARCH 和 GARCH-MIDAS 模型
- **與我們的關聯**: VIX 跳躍資訊可能增強我們的 12/VIX 策略（J13: conditional VT 全 null → 但 VIX jump 是否是被遺漏的 conditioning variable？）
- **複製建議**: ★★ 中等。需要高頻 VIX 數據
- **來源**: https://onlinelibrary.wiley.com/doi/abs/10.1002/fut.22553

### 5.2 VIX 期限結構與未來 RV ★★★
- **論文**: (2025), "VIX Term Structure and Future Realized Volatility", *Applied Economics*
- **核心發現**: VIX 期限結構的斜率和曲率可預測未來 realized volatility
- **與我們的關聯**: ★★★ 重要！如果 VIX term structure 斜率能預測 RV，可能提升我們的 VT timing
- **複製建議**: ★★★ 用 VIX/VIX3M 或 VIX/VIX6M 比率作為簡化版 term structure 斜率，測試對 VT 策略的增量
- **來源**: https://www.tandfonline.com/doi/full/10.1080/00036846.2025.2601895

### 5.3 VIX Candlestick Shadows (ULD) ★
- **論文**: (2024), "Forecasting Stock Returns: The Role of VIX-based Upper and Lower Shadow of Japanese Candlestick", *Financial Innovation*
- **核心發現**: VIX 日線的上下影線差 (ULD) 是強力報酬預測因子，OOS R² 達 3.988%，CE gain 達 327 bps
- **與我們的關聯**: 新穎但可能過擬合。需要驗證 OOS 穩健性
- **複製建議**: ★ 有趣但可疑

### 5.4 ML 預測 VIX ★★
- **論文**: (2025), "Predicting VIX with Adaptive Machine Learning", *Quantitative Finance*
- **核心發現**: 動態訓練 + 非線性方法 + 全面經濟變數可以高精度預測每日 VIX。比以往報告的精度更高
- **與我們的關聯**: 如果能高精度預測 VIX，理論上可以改善 VT timing
- **複製建議**: ★ 低。VIX 預測 vs 直接用 VIX 做 VT，增量可能有限

---

## 六、Rough Volatility 實務應用

### 6.1 Rough vs Markovian：誰更好？ ★★★
- **論文**: Abi Jaber & Li (2025), "Volatility Models in Practice: Rough, Path-Dependent, or Markovian?", *Mathematical Finance*, 35(4), 796-817
- **核心發現**:
  - 1 週至 3 個月到期：**rough vol 模型不如同參數數量的 1-factor Markovian 模型**
  - 延伸到更長到期：rough vol 不一致地優於 Markovian
  - **非 rough 的 path-dependent 模型 + 2-factor Markovian 模型**（3-4 參數）表現最佳
  - ATM SPX skew 與 rough vol 的 power-law 形狀不相容
- **與我們的關聯**: Rough vol 在學術界被質疑。對我們的 GARCH 方法沒有直接影響，但降低了我們追求 rough vol 的優先級
- **複製建議**: ☆ 不需要。Rough vol 在實務中不如預期
- **來源**: https://onlinelibrary.wiley.com/doi/10.1111/mafi.12463

### 6.2 Deep Calibration of Rough Vol ★
- **論文**: (2025), "On Deep Calibration of (Rough) Stochastic Volatility Models", *Journal of FinTech*
- **核心發現**: 神經網路解決 rough vol 模型的校準瓶頸，可做到即時校準
- **與我們的關聯**: 技術上有趣，但 rough vol 本身實務價值存疑（見 6.1）
- **複製建議**: ☆ 不建議

---

## 七、其他值得注意的研究

### 7.1 Heterogeneous Volatility Information in Realized GARCH ★★
- **論文**: (2025), "Heterogeneous Volatility Information Content for the Realized GARCH Modeling and Forecasting Volatility", *Studies in Nonlinear Dynamics & Econometrics*
- **核心發現**: 在 Realized GARCH 中嵌入 VIX、VIX1D、RV、Daily Range 等異質波動率度量，檢驗它們對條件波動率估計的差異影響
- **與我們的關聯**: VIX1D 是新指標（2023 年推出），可能對日內交易有價值
- **複製建議**: ★ 低優先，但 VIX1D 數據值得追蹤

### 7.2 Skew-t 在 Realized GARCH 中的應用 ★★
- **論文**: (2025), "Modelling and Forecasting Financial Volatility with Realized GARCH Model: A Comparative Study of Skew-t Distributions", *MDPI Econometrics*
- **核心發現**: Log-linear Realized GARCH + Skew-t 分配，用 MCMC 和 GRG 兩種方法估計
- **與我們的關聯**: 呼應我們的 Skewed Student-t 發現（6/6 資產通過 Kupiec，唯一全通過）
- **複製建議**: ★ 低，我們已經驗證 Skew-t 是最佳 VaR 分配

### 7.3 加密貨幣波動率的模型聚類 ★
- **論文**: (2024), "Predicting Cryptocurrency Volatility: The Power of Model Clustering", *Economic Modelling*
- **核心發現**: 模型聚類方法（ensemble）改善加密貨幣波動率預測
- **與我們的關聯**: 對我們的 BTC RV VT 策略可能有增量
- **複製建議**: ☆ 低優先

---

## 總結：對我們研究計畫的影響

### 立即可行動（高優先）

| 排序 | 研究方向 | 依據論文 | 預期影響 |
|------|---------|---------|---------|
| 1 | **分解 VT alpha 的 trend following 成分** | Hood & Raughtigan (2024) | 解釋 K21/K24/Q19 的結果，可能成為論文重要引用 |
| 2 | **測試 VIX term structure 斜率對 VT 的增量** | Applied Economics (2025) + Michael et al. (2025) | 用 VIX/VIX3M 比率測試是否改善 12/VIX 策略 |
| 3 | **測試 rebalancing boundary 對 12/VIX 的影響** | FMPM (2025) | 可能降低 turnover 同時維持績效 |
| 4 | **MF2-GARCH 模型移植** | Conrad & Engle (2025) | 可能取代 GJR-GARCH 成為新預測主力 |

### 中期探索

| 排序 | 研究方向 | 依據論文 | 備註 |
|------|---------|---------|------|
| 5 | Leveraged HAR 模型 | Branco et al. (2024) | 等 5-min 數據充足 |
| 6 | Options-driven RV prediction (VIX PCA) | Michael et al. (2025) | 需要 options 數據 |
| 7 | Downside-only VT | JBF (2021) | 用 semi-variance 替代 total variance |

### 理論支撐（引用用）

| 論文 | 支撐我們的哪個結論 |
|------|-------------------|
| Branco et al. (2024) | 簡單模型在經濟價值上最優（= 12/VIX） |
| Hood & Raughtigan (2024) | VT alpha = trend following（= leverage effect 驅動） |
| DeMiguel et al. (2024) | 多因子 VT 有效（= conditional portfolio） |
| Abi Jaber & Li (2025) | Rough vol 實務價值有限（降低優先級） |
| Research Affiliates (2024) | 低波動期 VT 落後（= K41 保險費） |

### 已驗證的共識（無需複製）

- **ML 在日頻 RV 預測的 OOS 表現不一致** — 多篇論文確認沒有單一 ML 模型在所有指標上都贏
- **GARCH 家族仍是日頻基準** — 但 MF2-GARCH 和 leveraged HAR 可能是下一代
- **VIX 仍是月度以下的 sufficient statistic**（但 term structure 可能帶來增量）
- **Rough volatility 實務價值存疑** — 不如簡單 Markovian 模型

---

## 資料來源

### 波動率預測方法
- [Conrad & Engle (2025) MF2-GARCH](https://onlinelibrary.wiley.com/doi/full/10.1002/jae.3118)
- [Branco et al. (2024) Does Anything Beat Linear Models?](https://www.sciencedirect.com/science/article/abs/pii/S0927539824000598)
- [GNN-HAR: Forecasting RV with Spillover Effects](https://www.sciencedirect.com/science/article/abs/pii/S0169207024000967)
- [Graph Signal Processing for Global RV](https://arxiv.org/abs/2410.22706)
- [Advances in Forecasting RV: A Review](https://link.springer.com/article/10.1186/s40854-025-00809-5)
- [Heterogeneous Volatility in Realized GARCH](https://www.degruyterbrill.com/document/doi/10.1515/snde-2024-0013/pdf)

### VT 策略
- [Hood & Raughtigan (2024) VT Is Trendy](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4773781)
- [DeMiguel et al. (2024) Multifactor VT](https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13395)
- [Conditional VT with Jump Effects](https://www.sciencedirect.com/science/article/abs/pii/S0927538X24002774)
- [Optimal Rebalancing Boundary for VT](https://link.springer.com/article/10.1007/s11408-025-00486-5)
- [Research Affiliates Multi-Asset VT](https://www.researchaffiliates.com/publications/articles/1014-harnessing-volatility-targeting)

### VIX / VVIX
- [Qiao et al. (2025) VVIX and VIX Forecasting](https://onlinelibrary.wiley.com/doi/abs/10.1002/fut.22553)
- [VIX Term Structure and Future RV](https://www.tandfonline.com/doi/full/10.1080/00036846.2025.2601895)
- [ML Predicting VIX](https://www.tandfonline.com/doi/full/10.1080/14697688.2024.2439458)

### ML / Deep Learning
- [Options-Driven Volatility Forecasting](https://www.tandfonline.com/doi/full/10.1080/14697688.2025.2454623)
- [Transformer Architectures for Vol Forecasting](https://www.mdpi.com/1911-8074/18/12/685)
- [HAR + ML Directional Prediction](https://www.tandfonline.com/doi/full/10.1080/13504851.2024.2401512)
- [Kelly et al. Deep Learning from IV Surfaces](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4531181)

### Rough Volatility
- [Abi Jaber & Li (2025) Rough vs Markovian](https://onlinelibrary.wiley.com/doi/10.1111/mafi.12463)
- [Deep Calibration of Rough Vol](https://www.worldscientific.com/doi/10.1142/S2705109925500051)

### HAR-RV
- [HAR-RV-CARMA Hybrid](https://www.mdpi.com/2227-9091/13/11/223)
- [Uncertain HAR-RV Models](https://onlinelibrary.wiley.com/doi/10.1002/fut.70049)
