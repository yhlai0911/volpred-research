# Research Program: Autonomous Volatility Prediction

## 目標（持續推進，永不完成）
1. 持續找出選定資產的最佳 1-step ahead 波動率、VaR/ES、報酬率預測模型
2. 持續建立一般非專業投資人可運用的各種交易策略
3. 持續找出利用研究成果獲利的模式
4. 持續找出並優化本網站的風格、經營模式、發展方向，持續修正朝之前進

## 約束

### 統計有效性（最重要，違反即無效）
| 項目 | 最低要求 | 建議 | 依據 |
|------|---------|------|------|
| GARCH 估計 window | ≥500 | ≥2000 | Hwang & Valls Pereira (2006): w<500 persistence bias >5% |
| OOS 評估期間 | ≥252 天 | ≥504 天 | 至少 1 年才能涵蓋不同 regime |
| DM test 樣本 | ≥200 | ≥500 | t-test 漸近分配需要足夠樣本 |
| Cross-sectional 測試 | ≥7 資產 | ≥15 | N<7 的 Spearman 很不穩定 |
| Bootstrap | ≥1000 reps | ≥5000 | <1000 CI 不精確 |
| Harvey (2016) threshold | t>3.0 | — | 多重檢定下 t>1.96 不夠 |
| Sharpe CI | SE ≈ 1/√N_years | — | 19 年 SE=0.23，差異<0.1 不顯著 |

**違反這些約束的結果應標記為 preliminary / unreliable，不可作為結論。**

### 多頻率研究約束
| 頻率 | 最低 OOS obs | 適合模型 | 不適合模型 | 資料年限需求 |
|------|------------|---------|-----------|------------|
| 日頻 | ≥252 | GARCH, EWMA, HAR | — | 8+ 年 |
| 週頻 | ≥104 (2yr) | EWMA, rolling std, GARCH | — | 10+ 年 |
| 月頻 | ≥60 (5yr) | EWMA, rolling std, regime | GARCH (收斂不穩) | 20+ 年 |
| 季頻 | ≥20 (5yr) | rolling std, regime | GARCH, HAR | 30+ 年 |
| 年頻 | ≥10 | descriptive only | 所有參數模型 | 50+ 年 |

### 跨資產假日處理
- 多資產投組中若某資產無當日價格（假日），使用**前一交易日價格** forward-fill
- 假日資產的當日 return = 0（非交易日不計入報酬）
- 不可混用不同市場的交易日期——各市場用自己的 return，合併時 ffill 價格
- `DataManager.get_price_data()` 預設已做 ffill，但計算 return 時需額外檢查

歷史教訓：
- w=252 的 GARCH 有 persistence bias -3%（M1 發現）
- w=504 仍有偏誤，w=2000 近乎無偏（M4 驗證）
- N=7 的 Spearman ρ=1.000 看似完美但 LOO 後仍然 1.000 才可信（N95 驗證）
- 模擬的 options P&L（N178-N180）因缺乏真實數據而完全不可靠

### 資料期間
- OOS 期間（主）: 2023-01-01 ~ 2024-12-31
- OOS 期間（驗證）: 2025-01-01 ~ 2026-03-31（R8 確認 15 個月驗證通過）
- OOS 期間（高波動）: 2022-01-01 ~ 2023-12-31
- 評估獲利期間：2025-01-01 ~ 2026-03-21（隨時間延伸）
- Rolling window 預設 2000（w=504 僅在特殊情況使用，gamma sign invariant to window）
- 5-min 數據：SPY 46 天 / 0050.TW 35 天（需 60+ 天 HAR-RV，ETA 2026-04-11）。收集正常（collect_us_data.py 自動調用 collect_5min_data.py）

### 評估指標（完整框架見 CLAUDE.md）
- **統計性**：QLIKE (主), MSE, MAE, HMSE, Mincer-Zarnowitz R², DM test, MCS, GW test
- **風險管理**：Trinity test (Kupiec+CC+DQ), Fissler-Ziegel, Acerbi-Szekely ES, Basel traffic light
- **經濟性**：Sharpe (Harvey t>3), MDD (bootstrap p<0.001), Calmar, Sortino, CRRA utility, CE return, Net Sharpe (after TX), Turnover
- **跨模型**：CCS Score, FDR audit, Cross-OOS 5 periods, Weight StdΔw
- 每個實驗必須 re-estimate each window（no lookahead）

## 研究多元化原則

**不要停留在模型舒適區。** 已驗證的結論（VIX sufficiency 23 次、50/50 不可動搖 8 次）不需要繼續堆積 null results。研究應同時在兩條軸推進：

### 漸進式延伸（從已知出發）
- 從現有面向自然衍生新問題
- 用新數據重新驗證舊結論
- 把已知方法應用到新資產/新市場

### 跳躍式探索（進入未知領域）
- **每個 session 至少 1 個「完全不同方向」的實驗**
- 不同領域的模型：NLP 情緒分析、替代數據（衛星/網路流量）、圖神經網路、因果推論
- 不同資產生態：加密 DeFi 協議、私募市場、碳權交易、大宗商品指數
- 不同研究方法論：行為金融實驗設計、市場微結構（order flow）、網絡/傳染模型、agent-based simulation
- 不同應用場景：ESG 整合波動率、氣候風險定價、地緣政治事件驅動策略
- 不同視角：投資人行為偏誤利用、制度摩擦套利、監管變化影響

### 判斷「是否在舒適區」的檢查清單
- [ ] 這個實驗是否只是「換一個 overlay 測 VT」？→ 可能在舒適區
- [ ] 這個模型/方法是否已經在其他實驗中用過？→ 考慮全新方法
- [ ] 預期結果是否又是一個 null result？→ 如果連續 3 個 null，換方向
- [ ] 這個問題能否用完全不同的方法回答？→ 嘗試不同方法論

### 研究主題來源（必須多元，不能只靠既有面向自選）

研究主題的發掘應來自多個管道，**定期檢索學術前沿論文是核心做法之一**：

| 來源 | 頻率 | 做法 | 寫入位置 |
|------|------|------|---------|
| **學術前沿文獻檢索** | 每 session 至少 1 次 | WebSearch arXiv/SSRN/JFE/JFM 搜尋最新 vol forecasting、futures hedging、risk management 論文 → 提取可測試的假說 → 寫入「待探索方向」 | 待探索方向區 + 對應面向 |
| **Codex/Gemini 建議** | 每 5-10 個實驗 | 主動詢問「接下來該研究什麼方向？」→ 標注 `[提出: Codex/Gemini]` | 對應面向 |
| **用戶指定** | 隨時（最高優先） | 用戶提出的方向立刻寫入 research_program.md | 對應面向 |
| **會員問題** | 每 6 小時 cron | 評估排名會員提問 → 高分問題轉為研究方向 | 對應面向 |
| **實驗過程中衍生** | 每個實驗後 | A 的結果暗示 B → 記錄 B 為新待辦 | 對應面向 |
| **跨 AI 交叉驗證** | 不定期 | 一個 AI 提出假說 → 另一個設計實驗 → Claude 執行 | 對應面向 |

**學術文獻檢索的標準流程：**
1. 搜尋關鍵詞：volatility forecasting, optimal hedge ratio, realized variance, VIX, GARCH extensions, risk management + 年份 2024-2026
2. 對每篇論文提取：標題、作者、期刊、方法、核心發現、與我們研究的關聯
3. 判斷可行性：數據是否可得（yfinance/FRED）？方法是否可複製？
4. 寫入 research_program.md「待探索方向」區，標注來源論文和 BLOCKED 狀態
5. 優先執行與現有研究路線互補的方向（而非重複已飽和的方向）

## 研究面向（螺旋式推進，非線性完成）

研究不是線性階段，而是持續探索的多個面向。每個面向可以隨時回訪：
新數據、新方法、新 insight 都可能讓之前「收斂」的面向重新打開。

### 面向 A: 波動率預測模型（多頻率探索）
**不限日頻**——週、月、季、年頻率都要探索。低頻率的注意事項：
- 樣本數隨頻率下降（月頻 20 年 ≈ 240 obs，季頻 ≈ 80，年頻 ≈ 20）
- 年頻 GARCH 不可行（<30 obs），改用 EWMA、rolling std、或 regime model
- 低頻模型需更長資料期間（月頻建議 30+ 年，季頻 50+ 年 if possible）
- OOS 期間要延伸到最新數據——如果 cache/存檔不到最近日期，用 `force_refresh=True` 重抓
- 月頻策略的 Harvey threshold 更嚴（fewer observations → wider CI）


**單變量模型：**
- GARCH 家族（GARCH, GJR, EGARCH, TARCH, FIGARCH）
- 高頻模型（HAR-RV, Realized GARCH, Realized GJR）— 需 5-min 數據（SPY 46天/0050.TW 34天，~2026 Q2 解鎖）
- **★★★★ HAR Multi-Scale (K530)**：HAR-ABS 以 DM=-15.45 壓倒性勝過 GJR-GARCH，DM=-16.26 勝 EWMA——**1306 實驗中最強統計顯著性**。|r_t| proxy 比 r²_t 好 3x。HAR-VIX 最佳 (QLIKE=0.46)。β5(5日) 主導。0050.TW 同模式。等 5-min RV 後應更強。
- **★★★ Rough Volatility (K529)**：H=0.1 確認 roughness。HAR-Rough 顯著勝 GJR (DM=-7.04) 但未勝 EWMA。Time-varying H 反而更差。
- **K526 GARCH-MIDAS**: OOS 未勝 GJR，但 regime 轉換期（COVID/升息）有局部優勢。long-run τ 僅解釋 11% variance。
- **MF2-GARCH**（Conrad & Engle 2025: 短期 GJR + 長期乘法誤差模型）— 測試中
- ~~混頻模型（GARCH-MIDAS: 結合日頻 vol + 月頻總經變數）~~ → K526 已完成，null result
- 分解式模型（EMD-GARCH: 經驗模態分解 + GARCH）
- ML/DL — Branco 2024 確認非線性 ML 整體不優於線性模型，降低優先級
- 組合預測（GJR+HAR, stacking, 反 QLIKE 加權）
- 跨資產模型選擇（gamma rule, significance-based）

**多變量模型：**
- DCC-GARCH（動態條件相關）— 已有初步結果
- BEKK-GARCH（多資產波動率溢出）
- Copula-GARCH（非線性相依結構）
- Factor GARCH（共同因子驅動的波動率）
- 跨資產 Granger 因果（vol spillover）

### 面向 B: VaR/ES 風險管理
- 分配選擇（Normal, Student-t, GED, Skewed-t, FHS）
- Adaptive sigma floor
- Multi-step VaR（proper GARCH h-step formula）
- VIX/GARCH ratio 作為 VaR reliability indicator
- **Cornish-Fisher expansion**（CF-VaR: 用偏態/峰態修正 Normal VaR）
- **Copula-based VaR**（多資產聯合尾部風險）
- **EVT-VaR**（極值理論, Peaks-over-Threshold）
- Monte Carlo VaR（GARCH 路徑模擬）

### 面向 C: 投資策略
- Volatility Targeting（12/VIX, EWMA VT, Hybrid VT）
- Multi-asset portfolio（40/30/30, Conditional TLT）
- 報酬預測（Excess Fear Signal [Gemini], VRP timing）
- DCA + VT：**K59 DCA 用 24/VIX**，**K70 DCA 50/50 幾乎不需 VT（防禦階層）**
- Covered Call：**K72 XYLD + VT 不改善 50/50**
- **VaR-targeting**（K44: rescaled σ-targeting，非新 alpha 但提供直觀風險選擇框架）
- **VT alpha = trend following**（K46→K53→K79: r=0.564, N=22, threshold-robust）
- **VT 雙重機制**（K49: Sharpe 來自 TSMOM, MDD 來自 VIX position sizing, 90-97% 跨 5 資產）
- **VVIX/SKEW/VIX3M overlay**（K43: 全部 NULL，方向關閉）
- **利率 regime**（K62: 高利率保險費僅 1.8%/yr vs 低利率 6.10%）
- **退休情境**（K85→K87: VT 不翻倍提領率，只提供更穩定的 4% 存活）
- **稅務**（K86: 保險費佔 71-80% 成本，稅佔 20-29%。台灣 0% 資本利得稅 = 結構優勢）
- **50/50 SPY/GLD 不可動搖**（K2/K16/K19/K24/K54/K63/K64/K89 — 8 次獨立驗證）
- **5% BTC 唯一統計顯著改善但尾部風險代價**（K66: p=0.014, 但 coskewness -0.50）
- **Sector VT uniform**（K58: gamma 不預測行業 VT 效果）
- **International VT universal**（K68: 13/13 市場 MDD 改善，US VIX 通用）
- **Rebalancing: 月度最佳**（K48/K65/K75: 週/季/年全 NS）
- **VT 季節性 NULL**（K80）、**槓桿 NULL**（K81）、**Stop-loss NULL**（K83）
- **Factor tilts NULL**（K89: MTUM/VLUE/QUAL/USMV 全不改善 50/50）
- 台灣市場：**K55/K82/K88 台灣 VT 指南 + TSMC 集中度測試**

### 面向 D: 理論貢獻
- Gamma-mechanism proposition（VT alpha 機制）— **K53: r=0.564 (N=22) 確認但衰減**
- Diversification amplification（index vs stock gamma）
- MDD vs Sharpe 區分（mechanical vs skill）— **K49: 雙通道分離**
- Anti-tautology 驗證
- **VIX sufficient statistic**（22 次確認：K43/K48/K57/K61/K65/K80/K84 + 歷史 15 次）
- **VT 保險費定價**（K41: ~4%/yr 恆定，K62: 利率依賴，K74: 80% 時間落後是正常的）

### 面向 E: 即時市場分析
- Hormuz 危機追蹤
- 危機類型分類（financial/pandemic/monetary/oil）
- 即時 VaR/ES 預報
- Paper trading 績效追蹤

### 面向 I: 期貨避險（Futures Hedging）
**動機**：K341 建立框架（ES=F r=0.978, VIX>25 tail hedge 資本效率最高），需深化為完整研究路線。
**核心問題**：期貨避險能否系統性改善 50/50+VT？台灣投資人如何用台指期？

**⚠️ 方法論原則：避險效果用避險指標評估，不跟交易策略比 Sharpe/CAGR**
避險的目標是降低風險，不是最大化報酬。正確的避險評估框架：
| 指標 | 定義 | 用途 |
|------|------|------|
| Hedging Effectiveness (HE) | 1 - Var(hedged)/Var(unhedged) | 主要指標，Ederington (1979) |
| Basis Risk | Var(spot - h×futures) 的穩定性 | 殘差風險 |
| VaR/ES Reduction | hedged vs unhedged 的尾部風險改善 | 極端保護 |
| Utility (mean-variance) | E[R] - λ/2 × Var(R) | 風險偏好依賴 |
| 避險成本 | margin + roll + basis cost | 實際成本（非 vs B&H 機會成本）|
| OHR 穩定性 | 不同 regime 下 h 的波動 | 實務可行性 |

**已完成實驗（按正確順序排列）：**
- [x] I0: ★★★ Data Diagnostics (15 pairs) — A=9, B=3, C=3。USO-CL/UNG-NG 不適合 GARCH。Bond corr 不穩定。experiments/i0_futures_data_diagnostics.py

**已有基礎：**
- [x] K341: ★★ Futures Hedging Framework — VIX>25 tail hedge 效率 7.71 MDD/cost, 12/VIX VT 勝固定避險
- [x] K199: VIX Futures Basis — IS Harvey pass 但 OOS overfit
- [x] K340: ES Futures Basis — null（VIX 吸收）

**研究方向：**
- [x] I1: ★ GARCH-based OHR — GARCH 不勝 EWMA（DM 全 NS）。Correlation 決定複雜度：SPY-ES corr>0.95→h=1 足夠，TLT-ZN corr<0.90→dynamic 必要（Harvey t=3.88）。EWMA(0.94) 是最佳實務。experiments/I1_garch_ohr.py
- [x] I1b: ★★ Commodity Futures Dynamic Hedging — Static OHR wins 5/6 pairs！GLD DM t=-3.8★（dynamic HURTS）。USO-CL catastrophic（corr 0.510）。Static 對所有資產類別都夠用。experiments/i1b_commodity_futures_hedge.py
- [x] I2: ★★ 台指期避險 — GARCH OHR~0.74（非 1.0），50/50 0050+GLD 仍是 Sharpe 冠軍（0.940）。GARCH hedge only MDD -14.0%（equity-only 最佳）。Futures on top of VT: 統計顯著但經濟邊際。SPY NOT viable cross-hedge（corr=0.15）。experiments/i2_taiwan_futures_hedge.py
- [x] I3 Fixed: Multi-futures HE 評估 — ES only HE=94.3% ≈ ES+GC+ZN 94.2%（DM 全 NS）。多期貨對 SPY 零增量。experiments/i3_fixed_hedging_metrics.py
- [ ] I4: VIX futures roll yield 策略 — contango 環境下的 roll yield 收割 vs 尾部風險保護 ⚠️ **BLOCKED: 需要 VIX futures 歷史數據（yfinance 無）**
- [x] I5: Regime-Switching Hedge Ratio — NULL。OHR 跨 VIX regime 穩定。experiments/i5_regime_hedge_ratio.py
- [x] I12: ★★ Window Sensitivity — 最佳窗口取決於 corr + structural stability。High corr→Naive 最好。Medium corr→長窗口(500d+)。Low corr + shift→短窗口(60-120d)。experiments/i12_window_sensitivity_hedge.py
- [x] K417: ★★★ Naive Hedge Superiority (Cao & Conlon 2025 JFM) — PARTIALLY REJECTED。Complex beats Naive 10/15 pairs (67%)。Correlation r=-0.899 是決定性 moderator。Equity: Naive 3/3。Commodity: Complex 4/4。Bond: Complex 3/4。FX: marginal 3/4
- [x] I11: ★★★ Full Panel 15 Pairs — Naive wins 8/15, Complex wins 7/15。Correlation threshold refined: >0.96→Naive, 0.89-0.96→mixed, <0.89→Complex。USO-CL disaster (HE=-817%)。Bond pairs 全需 dynamic (TLT-ZN t=9.2★★★)。experiments/i11_full_panel_daily_garch_hedge.py
- [x] I10: ★ VOV State-Dependent Hedging (Li & Chen 2025 JFM) — 方向確認但幅度微小（HE 差 1.9pp）。Partial r(VVIX,HE|VIX)=0.003 FAIL。SPY-ES corr>0.96 壓縮了所有差異。VIX sufficient for hedging decisions
- [x] I9: ★★★ Proper Hedging Effectiveness (Academic Standard) — Ederington HE + VaR/ES + Utility。SPY-ES corr>0.95: h=1 足夠（HE 94%）。TLT-ZN corr=0.81: EWMA t=6.91★（HE 45%→68%）。GLD-GC: OLS→85% 略勝 Naive。避險價值取決於 corr + h 偏離度 + unhedged 風險。experiments/i9_proper_hedging_effectiveness.py
- [x] I6 Fixed: 避險 vs 投資組合（分開評估）— Section A 避險: Static OHR HE=94.5%, TX 0.12%/yr。Section B 投資組合: 50/50 Sharpe 1.155, 50/50+VT MDD -14.3%。兩個框架不混用。experiments/i6_fixed_hedging_metrics.py
- [ ] I7: 台灣投資人跨境避險實務 — 用台指期避台股、用 ES mini 避美股，匯率風險、保證金需求、稅務影響
- [x] I8: 期貨基差波動率預測 — NULL（confirms K340）。SPY-ES r=-0.045 FAIL, GLD-GC null, TLT-ZN IS t=5.11★ BUT OOS collapses (ΔR²=-0.074)。Sixth Law confirmed。VIX sufficient re-confirmed

**學術參考（待查）：**
- Baillie & Myers (1991): Bivariate GARCH OHR
- Kroner & Sultan (1993): Time-varying OHR with error correction
- Lien & Tse (2002): Some recent developments in futures hedging
- Alexander & Barbosa (2007): Minimum variance hedge ratios
- 台灣：Chen et al. 台指期最適避險比率系列研究

### 面向 G: 跳躍式探索（全新方向線）
**這些方向與現有 VT/GARCH 研究顯著不同，目的是打破舒適區。**

- **NLP 情緒分析**：用 FinBERT/LLM 分析財經新聞情緒，預測次日波動率或報酬
- **替代數據**：Google Trends 搜尋量（已測 null for VT overlay，但可用於報酬預測）、衛星停車場數據、航運追蹤
- **市場微結構**：order flow imbalance → 短期波動率預測、bid-ask spread dynamics
- **網絡/傳染模型**：用圖模型分析波動率在資產間的傳播路徑（beyond linear Granger）
- **因果推論**：用 DiD / RDD 分析政策事件（例如 Fed 升息）對波動率的因果影響
- **Agent-Based Simulation**：模擬不同比例投資人使用 VT 對市場穩定性的影響（如果所有人都用 12/VIX 會怎樣？）
- **加密 DeFi**：AMM 池的 impermanent loss 與波動率的關係、DeFi yield 策略的風險管理
- **氣候金融**：極端天氣事件對商品/保險公司波動率的影響
- **行為金融**：投資人對 VT 的心理接受度實驗、為什麼知道 VT 有效卻不用？
- **跨學科方法**：物理學的相變模型、生態學的 regime shift detection、複雜系統理論

### 面向 TW: 台灣市場專線
**核心結論：8.63/VIX + 月度再平衡是台灣投資人的最佳 VT 策略**

**已確立的結論：**
- 8.63/VIX = 12/(VIX×1.39)，修正後 Sharpe 0.69，MDD -15.3%（Q1/R15）
- VIX 優於 VXEEM（R12: Spearman 0.595 vs 0.459，因 0050.TW≈50% TSMC→美國科技情緒）
- SPY→台股 spillover 真實存在（T5b: r=0.376, Granger F=58.8）
- SPY Momentum 5d/10d → 0050.TW c2c Harvey PASS，但 **o2o FAIL**（I8 timing bias）→ 學術發現非交易策略
- 台灣 0% 資本利得稅 = VT 結構優勢（K26/K86）
- TAIEX gamma 0.153 > 0050 0.087 > TSMC 0.039（T5a），ETF 分散化放大 gamma
- 台灣 MIDAS: 進口 YoY 唯一有增量（G12），其餘景氣燈號/M2 全 null
- 本土指標（外資買賣超/融資融券/PUT-CALL）全 null（G8）

**開放議題：**
- [ ] VIXTWN 數據累積到 252 天後驗證 ratio 穩定性（Q6）
- [ ] 台灣 5-min 數據 HAR-RV（0050.TW 35 天，ETA 2026 Q2）
- [ ] 台灣公債殖利率曲線 → vol 預測
- [ ] 台灣 CoVaR 傳染結構（0050→TSMC→金融股）
- [ ] 台灣月頻 VT 最佳實務完整指南（整合所有發現）

**論文**：第二篇 `paper/taiwan-vt/main.tex`（34 頁）涵蓋台灣 VT + TZ 資訊傳遞

### 面向 F: 網站與系統
- 前端功能（12/VIX 計算器, Feed 品質, Paper 下載）
- 部署架構（v2 Supabase + Zeabur）
- 知識索引（LanceDB embedding）
- AI 協作模式（Claude + Codex + Gemini）
- 平台操作層（`/admin/*`、`/api/admin/*`、`uv run volpred ops ...`）
- 讀者分析回饋（analytics summary → 研究與發文方向）
- 會員問題排行與研究候選池

### 面向 H: 論文撰寫與投稿
**第一篇：Leverage Direction Matters**
- `paper/leverage-direction/main.tex`（60 頁，3 contributions）
- 目標：Journal of Banking and Finance (JBF)
- 狀態：H3-H9 完成 Codex+Gemini 審查修正
- [ ] 最終校稿 + `/latex-academic-reviewer` 全面審查
- [ ] `/citation-verifier` 引用驗證
- [ ] 投稿準備（cover letter, highlights, graphical abstract）

**第二篇：Taiwan VT + TZ Information Transmission**
- `paper/taiwan-vt/main.tex`（34 頁）
- 目標：Pacific-Basin Finance Journal 或 Emerging Markets Review
- [x] 完成初稿（H10, 26→28 頁）
- [x] Codex 審查 + 修正（H11, 5 issues fixed）
- [x] 加入 G20 景氣燈號結果（G22）
- [x] 加入進口 YoY macro guard (G12/G13)（G22）
- [x] `/citation-verifier` 引用驗證（H13, 14/14 OK）
- [ ] Gemini 審查
- [ ] `/latex-academic-reviewer` 全面審查

**第三篇：Is Volatility Targeting Just Trend Following?**
- `paper/vt-trend-following/main.tex`（24 頁）
- 目標：待定（可考慮 Journal of Portfolio Management 或 Financial Analysts Journal）
- 核心貢獻：分解 VT 的 alpha 來源（K46→K53→K79: r=0.564, VT alpha = trend following）
- [ ] Codex/Gemini 審查
- [ ] `/latex-academic-reviewer` 全面審查
- [ ] `/citation-verifier` 引用驗證

**未來可能的第四篇：VIX Sufficient Statistic**
- 23+ 個指標全被 VIX 吸收的 comprehensive study
- 適合 Journal of Financial Economics 或 Review of Financial Studies
- 需要更多跨市場驗證（目前只有 US + Taiwan）

## 決策框架

### 何時深入某面向
- 發現新線索（例：Gemini 建議 Excess Fear Signal → 立刻測試）
- 新數據可用（例：5-min 累積到 60 天 → 重測 HAR-RV）
- 舊結論需重新驗證（例：gamma decline → VT 還有效嗎？）

### 何時暫停某面向
- 連續 3 次實驗無改善 → 暫停但不關閉（標記為「等待新 input」）
- 缺乏數據或工具 → blocked（標記預計解除日期）

### 何時回訪已「完成」的面向
- 數據量增加（OOS 延伸、5-min 累積）
- 新方法出現（文獻搜尋發現）
- 用戶提出新需求
- 之前的 null result 可能因條件改變而翻轉

## 發佈規範
- 每個發現即時記錄（thinking + knowledge + feed）
- Feed 文章用 `feed-publisher` skill，確保品質
- 平台型發佈（文章池、排程、節奏釋出、下架、重釋出）轉交 `admin-ops`
- 預設可先進文章池（`draft` / `scheduled`），再依節奏釋出，不必每次都立即公開
- 所有議題標注發起者（Gemini/Codex/Claude/用戶）
- 具體發現存 `research_findings.md`（加入 embedding）
- Claude 應定期讀取平台摘要（尤其 analytics / questions summary），把讀者回饋與高分會員問題納入研究來源

## 研究發現與成果
詳見 `research_findings.md`（已加入知識索引 embedding）

### 已完成研究階段（存檔，查詢見下方路徑）

**查詢追蹤路徑：**
| 類型 | 位置 | 說明 |
|------|------|------|
| 完成 Phase 詳細記錄 | docs/research_archive/completed_phases_2026Q1.md | 590 行，含所有 Phase O~K 逐實驗結果 |
| 知識庫（發現） | storage/memory/knowledge.json | 3,189+ 筆，記錄**發現了什麼**。grep 搜尋：grep -i '關鍵詞' storage/memory/knowledge.json |
| 經驗庫（教訓） | storage/memory/experiment_experiences.json | Exxx 編號，記錄**學到了什麼**（成功/失敗原因、方法論教訓、避坑指南） |
| 知識索引（向量搜尋） | storage/knowledge_index/ | LanceDB，用 build_knowledge_index.py 重建 |
| 實驗腳本 | experiments/k*.py | 119+ 個 Python 腳本，每個可獨立執行 |
| 實驗結果 | experiments/k*_results.json | 每個實驗的完整 JSON 結果 |
| Feed 文章 | storage/reports/feed.json + storage/reports/mile_*.json | 562+ 篇文章（含 content） |
| 研究記憶 | storage/memory/thinking_journal.json | 研究決策推理過程 |
| 論文 | paper/leverage-direction/ / paper/taiwan-vt/ / paper/vt-trend-following/ | 三篇論文 LaTeX 源碼 |
| 數據 | yfinance 線上（每次實驗即時下載）+ data/vixtwn/ + storage/5min_data/ | 日頻 OHLC + VIXTWN + 5-min |
| 策略 Paper Trading | storage/paper_trading.json | 9 策略 × 7,950+ entries |
| 同步狀態 | storage/.supabase_sync_state.json | Supabase 增量同步狀態 |

| Phase | 期間 | 實驗數 | 核心成果 |
|-------|------|--------|---------|
| O | 2026-03-16 | ~15 | VaR 方法論：Trinity test, FHS, CF-VaR |
| P | 2026-03-17 | ~20 | 自建模型 GJR-HAR, QLIKE ceiling 建立 |
| Q | 2026-03-17 | ~25 | 跨市場 VT, Asia-Pacific lead-lag |
| R | 2026-03-17 | ~15 | GARCH 應用擴展, VRP discovery |
| S-U | 2026-03-17 | ~15 | Narrative-GARCH, Rough Vol, Panel |
| J | 2026-03-18 | ~15 | 策略優化, 50/50 SPY/GLD 確立 |
| K(early) | 2026-03-18 | ~30 | Options surface, portfolio science |
| K(K183-K289) | 2026-03-24 | 107 | 大規模 sweep, Taiwan deep, 期貨避險 |
| K(K426-K507) | 2026-03-26~27 | 82 | SSVS, HAR, ensemble, MCS, VIX9D, commodity, forex |

**82 個實驗的關鍵成果摘要（K426-K507）：**
- ★★★ GJR-X(VIX9D): best forecaster (K490, DM t=6.63)
- ★★★ MCS: 5-model superior set (K481, Econometrica method)
- ★★★ K500 Grand Retrospective: 119 experiments, one sentence summary
- ★★ HAR log-range: 8/10 cross-OOS (K469, with tautology correction K468)
- ★★ Semivariance: 4/5 cross-OOS equity (K460, gamma-driven K453)
- ★★ Universal persistence law: mean=0.980 across 14 assets (K491)
- ★ VIX sufficiency: 32x confirmed + causal K477 (VIX is sink not source)
- ★ 12/VIX irreducible kernel: 5x confirmed for VT strategy
- ★ 50/50 SPY/GLD irreducible: K507 dynamic allocation all fail
- ★ Prediction ≠ Application: 4x confirmed (K440/K467/K470/K488)
- ⚠️ Cross-OOS caught 4 false positives (K459/K474/K476/K506)

### 待探索方向（2025-2026 文獻前沿）
**來源：arXiv + JFE + ScienceDirect 2025-2026 文獻搜索**
- [ ] Rough Volatility (fBm H≈0.1) — Gatheral 2014 "Volatility is Rough" 的最新 multivariate extension (arXiv:2504.15985)。我們的 QLIKE ceiling 是否被 rough vol 打破？
- [ ] XAI for Volatility — 幾乎沒人用 Explainable AI 解釋 vol 預測。我們的 GARCH 參數解釋性 + ML 預測性能否結合？
- [ ] Intraday Commonality — 跨資產日內 vol 因子改善預測 (JFE 2024)。等 5-min 數據 60+ 天可以測試
- [x] Panel Data ML — U1 null result（顯著更差）。更多變數=更多估計噪音。QLIKE ceiling #14
- [ ] K33: MOVE-based bond VT（進行中）
- [ ] K34: Rough Vol multivariate extension（進行中）
- [ ] Vol-Timing with ML — ML-based VT 策略優於 GARCH-based (ScienceDirect 2024)。但我們的 LSTM/GBM 已失敗——T22 confirms ML cannot beat GARCH cross-asset
- [ ] Non-Gaussian Rough Vol — α-stable increments (arXiv:2507.15437)。適用於 BTC 等厚尾資產
- [ ] HAR + Wavelet 分解 (JFM 2026) — 分解 RV 為短中長期成分，低頻最佳。等 60 天 5-min 數據
- [ ] Graph Signal Processing HAR (arXiv:2410.22706) — 跨資產 vol spillover 整合。等 5-min 數據
- [ ] Regime-aware In-Context Learning (arXiv:2603.10299) — LLM 做 vol forecasting，全新前沿
- [ ] 「HAR ceiling」驗證 — Los Flamingos 2025 報告 well-tuned HAR 也打不敗（HAR = 高頻版的 GARCH ceiling？）

**2026-03 文獻搜索更新：**
- [ ] HAR-PD (Path-Dependent) — arXiv:2503.00851, 結合 HAR + 路徑依賴波動率模型，利用 long/short-term memory 捕捉趨勢特徵。等 5-min 數據
- [ ] Adaptive Multi-Factor HAR (FoFI 2026, Cinquetti et al.) — 287 個高頻因子的 adaptive selection，動態更新 forecasting structure 以適應 regime shift。等 5-min 數據
- [ ] Options-Driven Vol Forecasting (Quantitative Finance 2025) — 用 option price data 提取新型 vol estimator 增強 HAR。⚠️ **BLOCKED: 需 options 歷史數據**
- [ ] 期貨避險最新方法：Partial Cointegration Hedging (RQFA 2023) — VIX 期貨 vs 股指期貨的 partial cointegration 避險策略，tail risk reduction 優於 OLS/VAR/VECM
- [ ] Regime-Switching Correlation Hedging — 多狀態 regime switching 相關性模型在期貨避險中優於靜態 OLS，但 TX costs 高。與我們 K341 框架銜接
- [ ] Financial Innovation 2025 review — realized volatility forecasting 方法論綜述，含 rough vol + ML + HAR extensions 最新進展

**2026-03-25 新增文獻方向（期貨避險 + Transformer vol）：**
- [ ] Quadratic Hedging under GARCH (J. Futures Markets 2026, Ma) — LRM/GRM 動態規劃 + willow tree 結構計算避險比率。方法論可借鑑但需 options 數據
- [ ] Copula-based GARCH Hedge (Hsu et al.) — 用 copula 捕捉 spot-futures 非線性相依結構。我們 I1b 發現 static 已足夠，copula 是否改變結論？
- [ ] Wild Bootstrap OHR (JRFM 2024) — bootstrap 估計 OHR 信賴區間，比 DCC-GARCH 更穩健？
- [ ] Multi-Transformer Vol Forecast (Engineering App AI 2024) — Transformer 組合架構勝 GARCH 和單一 DL 模型。但我們 K142/T22/R10 已 3 次確認 ML 在日頻不勝 GARCH
- [ ] PatchTST-lite vs HAR-RV (MDPI 2025) — Transformer 在 RV 預測上的首次系統比較。等 5-min 數據可做
- [ ] CNN-Transformer Hybrid (European J. Finance 2025) — 結合 CNN 局部特徵 + Transformer 長距依賴。ML + GARCH 互補可能性
- [ ] GARCH-to-Neural (AAAI 2024) — 用 GARCH 結構初始化 NN，保持可解釋性。與 K142 XGBoost 失敗對比
- [ ] Neural Heteroscedasticity (Eng App AI 2025) — 高頻 NN-based GARCH，替代傳統 MLE。等 5-min 數據
- [x] I5: Regime-Switching Hedge Ratio — NULL。OHR 跨 regime 穩定。文獻預測 regime-switching 有效但我們實證否定
- [x] I1b: Static OHR 跨 6 資產類別勝出。文獻推薦 DCC/copula 的增量價值可疑

**2026-03-26 新增：Bayesian Subset Selection + Smooth Transition 方法論（用戶指定）：**
- [ ] K433: **Bayesian SSVS for ARX-GARCH** — So, Chen, Liu (2006) JRSS-C, 55(2), 201-224. Latent binary indicator δ_i + MCMC 從 2^(p+q) 子集空間搜索最優外生變數組合。比 K113 逐一測試更有力。**進行中**
- [ ] K431: **Smooth Transition GARCH (STGARCH)** — González-Rivera (1998), Hagerud (1997). 允許 GARCH 參數漸進轉換（VIX 作為 transition variable）。K427 發現結構性斷裂，ST 可能比 abrupt switch 更合適。**進行中**
- [ ] K432: **Bayesian MCMC GARCH** — 用 Metropolis-Hastings 估計 GJR-GARCH 後驗分布，量化參數不確定性。比 MLE 點估計更穩健。**進行中**
- [ ] Bayesian Subset Selection for TARMA — Chen, Liu, Gerlach (2011) Computational Statistics, 26, 1-30. 擴展 SSVS 到 threshold + MA terms，16M+ 可能子集
- [ ] Threshold Variable Selection for Asymmetric SV — Chen, Liu, So (2013) Computational Statistics, 28, 2415-2447. Combined threshold variable Z_t = Σω_i Z_i，同時選 threshold 變數和模型結構。五個亞洲市場實證
- [ ] SSVS for Variance Equation — 將 SSVS 擴展到 variance equation（GARCH-X 的 variance side 加外生變數），目前 K433 只處理 mean equation
- [ ] Threshold GARCH with Bayesian Model Selection — 結合 2006+2013 方法：threshold GARCH + SSVS 同時選 regime 結構和變數子集

**2026-03-26 本 session 完成實驗（K426-K460, 36 experiments）：**
- [x] K426: 高效 GINN — ML 仍無法打破 QLIKE ceiling（1.5s runtime，K419 效率修正）
- [x] K431: STGARCH — GJR 顯著勝（DM p<0.001），9 參數過擬合
- [x] K432: Bayesian MCMC — MLE 勝（大樣本後驗集中於 MLE 附近）
- [x] K433: **★ SSVS Definitive Null (SPY)** — 空模型勝 524K 子集。Mean equation 不需要外生變數
- [x] K434: BMA — BIC 權重退化（EGARCH-t 佔 99.8%）
- [x] K435: **★ Hillebrand Effect** — Persistence 膨脹 +0.073。ICSS 偵測 20 個斷裂
- [x] K436: VRP Daily — IS t=4.38 pass Harvey，bootstrap p=0.000。**⚠️ K459 修正：cross-OOS 0/5 QLIKE wins**
- [x] K437: GAS-t — Rank 6/6。Outlier downweighting 在日頻有害
- [x] K438: GARCH-X(VRP) — Null。GARCH-X(VIX) borderline -6.3%
- [x] K439: VRP Cross-Asset — Equity-specific (SPY/QQQ only)
- [x] K440: VRP-VT Strategy — **預測≠交易能力**。12/VIX irreducible kernel 第 7 次確認
- [x] K441: **★ Range-Based Vol** — Parkinson 6.8x, GK 5.5x 效率。Cross-proxy GJR consistent
- [x] K442: FIGARCH — d=0.61 長記憶確認但 OOS 不改善
- [x] K443: **★ Copula Tail Dependence** — Post-2020 SPY-TLT doubly broken（失去負相關+增加尾部共動）
- [x] K444: DCC-GARCH Portfolio — EWMA equally good for low-corr pair
- [x] K445: **★ BTC Inverse Leverage** — Regime-dependent 非永久（gamma 翻轉）
- [x] K446: GPR — Null。**Granger 因果反轉**：VIX→GPR 不是 GPR→VIX
- [x] K447: SKEW — Null（反而降低預測力）
- [x] K448: VVIX — Null（2.3% improvement, NS）
- [x] K449: **★★ Daily Semivariance** — RS⁻ 5.5x R² improvement (SPY)。Equity-specific (K453: gamma mechanism r=0.812)
- [x] K450: VRP+Semi Combined — 無協同（維度詛咒）
- [x] K451: Overnight/Intraday — 描述性豐富但預測 null
- [x] K452: Yield Curve — Null。Inverted = lower vol（反直覺）
- [x] K453: **★ Semivariance Cross-Asset** — 4/5 equity sig, gamma mechanism (r=0.812)
- [x] K454: **★★ Semivariance VaR** — Trinity 3/3 at 1%，勝 GARCH Skewed-t 1/3
- [x] K455: **★ Vol Spillover Network** — 74% total, SPY net +1.9%。COVID +13.2%
- [x] K456: Taiwan Semivar VaR — RS⁻ FAILS（gamma 低）。GJR-SkewT 勝
- [x] K457: Weekly Vol — QLIKE ceiling diffuse。GJR gamma 2.36x 放大
- [x] K458: **★ Meta-Analysis** — Information decomposition > complexity。corr(params, success)=-0.259
- [x] K459: **★ VRP Cross-OOS FAIL** — 0/5 QLIKE wins（significance ≠ forecasting）。VIX sufficiency #30
- [x] K460: **★★ Semivariance Cross-OOS PASS** — SPY 4/5 significant, 5/5 directional。Publication ready
- [x] K461: **★ SSVS Taiwan** — SPY_ret PIP=1.000（台股選出 SPY，美股選空模型——完美對比）。但 QLIKE 不改善（mean≠variance disconnect）
- [x] K462: Taiwan GARCH-X/STGARCH — Null。VIX IS t=3.58 但 OOS +7.1% worse（overfitting）。GARCH ceiling 延伸到台股
- [x] K463: TVP GARCH-X Taiwan — EWMA delta -1.71% 但 DM p=0.264 NS。方向正確但太小
- [x] K464: **★ Threshold SV Asian Markets** — HAR log-range 6/6 markets 最佳。Ref: Chen, Liu, So (2013)
- [x] K465: **★★★ HAR Log-Range Cross-OOS** — 10/10 (Parkinson), **8/10 (r² proxy, K469 驗證)**。Publication ready
- [x] K466: HAR+Semi Combined — 無協同。HAR encompasses semivariance (lambda=1.94)
- [x] K467: HAR VaR — 0/6 Trinity pass！Best forecaster ≠ best VaR（Parkinson misses jumps/overnight）
- [x] K468: **⚠️ Yang-Zhang Tautology Test** — Range proxy 偏好 range model。但 K469 證明影響極小
- [x] K469: **HAR r² Proxy Validation** — 8/10 cross-OOS。Tautology 只降 2/10。K465 結論 validated
- [x] K470: HAR-VT Strategy — +0.067 Sharpe but p=0.181 NS。**3rd prediction≠application** (K440 VRP, K467 VaR, K470 VT)
- [x] K471: Higher Moments — Rolling kurtosis +16pp R² but DM p=0.11 NS。BTC harmful。Kurtosis > skewness
- [x] K472: **Taiwan Comprehensive** — All US-validated methods fail on 0050.TW。GARCH ceiling is cross-market universal
- [x] K473: Attention/Google Trends — IS R²+6.2% but OOS 全 null。⚠️ K474 修正：weekly RV>VIX 是 artifact
- [x] K474: **Weekly RV vs VIX Cross-OOS** — VIX wins **6/6**。K473 retracted (level-OLS artifact)。**VIX sufficiency #31（含週頻）**

- [x] K475: **★★ Validated Ensemble** — GJR+HAR forecasting 5/5 top rank。⚠️ K476 修正：VaR 0/5 at 1%（HAR contaminates）
- [x] K476: **Ensemble VaR Cross-OOS** — 0/5 at 1%。GJR alone 3/5 (best)。K475 VaR claim overturned

### 跨兩 session 52 實驗總結（K426-K476）
**經過 cross-OOS 驗證的正面發現（3/52 = 6%）：**
1. ★★★ HAR log-range vol forecasting: 8/10 cross-OOS with r² proxy (K469)
2. ★★ Daily semivariance (RS⁻) for equity: 4/5 cross-OOS (K460), gamma-driven (K453 r=0.812)
3. ★★ GJR+HAR ensemble forecasting: 5/5 cross-OOS top rank (K475), but NOT for VaR (K476: 0/5)

**被 cross-OOS 推翻的 false positives（3/52 = 6%）：**
1. K436 VRP daily → K459: 0/5 QLIKE wins (VIX contains VRP)
2. K473 Weekly RV>VIX → K474: 0/6 (level-OLS artifact)
3. K475 Ensemble VaR 3/3 → K476: 0/5 (HAR contaminates tail estimation)

**最終工具指南（經過 cross-OOS 驗證）：**
| 任務 | 最佳方法 | 驗證 |
|------|---------|------|
| Vol forecasting | GJR+HAR ensemble | K475: 5/5 top rank |
| VaR estimation | GJR-GARCH alone | K476: 3/5 (best across periods) |
| VT strategy | 12/VIX | K440/K470: irreducible kernel (3x) |
| Equity vol prediction | + Semivariance RS⁻ | K460: 4/5 cross-OOS |

**方法論貢獻：**
- Prediction ≠ Application (K440/K467/K470, 3x confirmed)
- Significance ≠ Forecasting (K459 VRP, K473 RV)
- Information decomposition > Model complexity (K458: corr=-0.259)
- Proxy tautology awareness (K468/K469)
- GARCH ceiling cross-market universal (K472 Taiwan)
- VIX sufficiency #31 (日頻+週頻)
- Cross-OOS is essential quality control (3/3 false positives caught)

**後續實驗（K478-K484）：**
- [x] K478: Entropy — Null（Complexity Ceiling）
- [x] K479: Wavelet — Null（Decomposition Ceiling，HAR ad-hoc 已最優）
- [x] K480: Regime-switching tool selection — Forecasting/VaR tradeoff is fundamental
- [x] K481: **★★★ MCS Capstone** — 5-model superior set, ensemble 5/5 最穩健。Econometrica 級確認
- [x] K482: MCS-weighted ensemble — Equal weight wins（Timmermann combination puzzle）
- [ ] K483: Commodity vol（oil/gold）— **進行中**
- [ ] K484: **SSVS Variance Equation Component Selection**（用戶創意）— **進行中**。用陳婉淑方法選 GARCH 模型成分（不是選變數）

- [x] K483: **★ Commodity Vol** — Opposite of equity: GARCH(1,1) symmetric wins, HAR worst, oil inverted leverage
- [x] K484: **★★★ SSVS Variance Eq** — 4/5 components PIP=1.000, QLIKE -7.43%（用戶創意）
- [x] K485: SSVS Variance Eq Cross-OOS — 4/5 directional, 2/5 sig（promising, GJR+VIX better alone）
- [x] K486: **★★★ GJR-X(VIX) Breaks Impossible Triangle** — SPY forecasting -17% + VaR 5/5 pass
- [x] K487: GJR-X(VIX) Cross-Asset — Equity-specific forecasting, broader VaR (5/6 pass)

### 最終工具指南（63 experiments, cross-OOS validated）
| 任務 | SPY | Other equity | Non-equity | Taiwan |
|------|-----|-------------|------------|--------|
| **Forecasting** | **GJR-X(VIX) ★★★** | GJR+HAR ensemble | GARCH(1,1) | GJR alone |
| **VaR** | **GJR-X(VIX)** | GJR-X(VIX) | GJR alone | GJR-SkewT |
| **VT Strategy** | 12/VIX | 12/VIX adapted | Asset-specific | 8.63/VIX |
- [x] K488: GJR-X(VIX) VT — Cannot beat 12/VIX（4th prediction≠trading, risk premium is feature not bug）
- [x] K489: **★ VIX Term Structure** — VIX9D R²=0.41 for 5d vol, direction accuracy 58-61%
- [x] K490: **★★ GJR-X(VIX9D) beats GJR-X(VIX)** — 3/3 OOS (DM t=6.63), delta CV=0.08 (10x more stable), VIX9D subsumes VIX

### 最終最佳模型（66 experiments validated）
**GJR-GARCH-X(VIX9D)**: h_t = ω + α·ε² + γ·I(ε<0)·ε² + β·h + δ·VIX9D²/252
- Forecasting: best (QLIKE -17.7% vs GJR, DM t=6.63 vs VIX version)
- VaR 1%: Trinity 3/3 pass
- Delta: ultra-stable CV=0.08
- Limitation: VIX9D data only from 2018 (3 OOS periods vs 5 for VIX)
- [x] K491: **★★ Universal Persistence Law** — mean=0.980, std=0.014 across 14 assets. Hillebrand 14/14 (p=0.0002)
- [x] K492: Research Efficiency Meta-Study — 52.9% cross-OOS false positive rate, 8.5 experiments/finding
- [x] K493: GJR-X(VIX9D) Real-Time Signal — R²=0.614 (best thermometer), +22% higher weight than 12/VIX (safest umbrella)
- [x] K494: Forex Vol — No leverage (gamma≈0), EWMA wins JPY, persistence 0.994 (highest cross-asset)
- [x] K495: **★★★ Grand Unified Model Guide** — Gamma decision tree 15/15 within 1% of oracle. Capstone

### 71 Experiments Final Summary (K426-K495)
**研究完成度**：日頻方向已完全飽和。下一個突破需 5-min data HAR-RV（ETA 2026-04-05）。
**Decision tree for any asset**: Fit GJR → check gamma → choose model. Within 1% of oracle.

**2026-03-26 用戶指定新方向（必須記錄）：**

### 報酬率預測（用戶提出，全新方向線）
- [ ] K501: **SSVS for Return Prediction** [提出: 用戶] — 用陳婉淑方法預測報酬率（不只波動率）。K461 已發現 SPY_ret PIP=1.000 for Taiwan (t=10.81)。**進行中**
- [ ] Return prediction → trading strategy pipeline：如果方向準確度 > 55% → 可做 long/short 策略
- [ ] 跨資產 return prediction：SPY、0050.TW、QQQ

### 新交易策略開發（用戶提出，急需上架新策略）
- [ ] K502: **US→Taiwan Lead-Lag Strategy** [提出: 用戶] — 用 SPY return 信號交易 0050.TW。T32/T33 confirmed lead-lag (r=0.376)。**進行中**
- [ ] K503: **VIX Mean-Reversion Strategy** [提出: 用戶] — 利用 VIX spike 後的 mean reversion 做交易。K430/K491 支持。**進行中**
- [ ] 策略上架前必須：Cross-OOS ≥ 5 periods、3 年回測、Net Sharpe (after TX) > 0
- [ ] **不要輕易上架**——交易策略必須多次確認（cross-OOS + out-of-sample + sensitivity），避免上架後發現是錯誤

### 文章品質（用戶提出）
- [x] Feed 文章必須附圖表——已修正 3 篇文章、已寫入 feedback memory

**2026-03-26 Codex 建議的 5 個新方向（第5次審查）：**
- [ ] **Decision-focused policy learning** [提出: Codex] — 不預測 return/vol 再映射到交易，而是直接學習最優行動（contextual bandit / dynamic treatment）。回應核心發現「prediction ≠ trading」
- [ ] **Two-clock decomposition: overnight + intraday + jump** [提出: Codex] — 分開建模 close-to-open / open-to-close / jump probability，只交易有信號的 segment。K451 已做描述性分析但未做策略
- [ ] **Options surface state variables** [提出: Codex] — 超越 VIX/SKEW 的 scalar summary，用完整 IV surface（left-tail slope, corridor variance, GEX/vanna, 0DTE share）。⚠️ BLOCKED: 需 options 歷史數據
- [ ] **Dispersion / correlation-regime trading** [提出: Codex] — 將 DCC/copula/network 分析（K443/K444/K455）轉化為策略：sector dispersion, correlation breakdown trades, network-hub rotation
- [ ] **Event-surprise strategies** [提出: Codex] — 不是 calendar dummy（K498 null），而是用 surprise component（fed funds futures surprise, CPI surprise vs option-implied move）。條件預測比無條件預測更可行

Codex 優先排序：(1) Decision-focused policy (2) Overnight/intraday decomposition (3) Dispersion trading

**2026-03-26 Gemini 建議的 5 個新方向（台灣特色 + 免費數據）：**
- [ ] **Taiwan Price Limit Latent Volatility** [提出: Gemini] — 台股 ±10% 漲跌幅限制壓抑觀察波動率，limit-hit 日隱含更高真實 vol。GARCH-X 加 LimitHit dummy。Data: yfinance
- [ ] **FRED STLFSI4 Macro Stress Regime** [提出: Gemini] — 用聖路易金融壓力指數做 regime switching，壓力期降低 target vol (12%→8%)。Data: FRED STLFSI4
- [ ] **VIX→Taiwan Vol Spillover Strategy** [提出: Gemini] — VIX 在美股時段 spike > 15% → 次日台股開盤自動減倉。比 return lead-lag 更直接。Data: yfinance
- [ ] **TXO Put-Call Ratio Mean-Reversion** [提出: Gemini] — 台指選擇權 P/C ratio 作為散戶恐慌指標，極端值做反向操作。Data: TAIFEX 網站
- [ ] **EWT vs 0050.TW Vol Arbitrage Spread** [提出: Gemini] — 同一標的不同市場的 vol 差異信號。EWT vol >> 0050 vol → 預警台股 vol 將追趕。Data: yfinance

### 重要事件日曆（當月+下月，每月更新覆蓋）
**最後更新：2026-03-26。下次更新：2026-04-01。**

#### 美股事件
| 日期 | 事件 | 研究安排 | 文章安排 |
|------|------|---------|---------|
| **04/03 (五)** | **NFP 非農就業** | 就業數據與波動率關係 | 「非農報告前後該怎麼操作？」(general) |
| **04/09 (四)** | **GDP 第三估 + Personal Income** | GDP surprise 對 vol 影響 | 「GDP 數據出爐那天該注意什麼」(general) |
| **04/10 (五)** | **CPI 通膨數據** | CPI surprise vs option-implied（Codex event-surprise 建議） | 「通膨數據——歷史告訴我們市場怎麼反應」(general) |
| **04/28-29** | **FOMC 利率決議 + Powell 記者會** | FOMC 對 VIX/vol regime 影響 | 「Fed 決策對投資組合意味什麼」(general) |

#### 台股事件
| 日期 | 事件 | 研究安排 | 文章安排 |
|------|------|---------|---------|
| **04/10 (五)** | **TSMC 3月營收公告**（每月10日前） | TSMC 營收 surprise 對 0050 vol | 「台積電營收公告前後台股怎麼走？」(general) |
| **04/16 (四)** | **TSMC Q1 法說會** | TSMC earnings 對 0050.TW vol | 「台積電法說前後台股波動」(general+research) |
| **04/17 (五)** | **中經院台灣經濟預測** | 經濟預測修正對台股 sentiment | 搭配法說會文章 |
| **06月~** | **台股除權息旺季開始** | 除權息對 vol/return 的系統性影響研究 | 「除權息季節該參加還是避開？」系列文章 |

#### 除權息研究方向（用戶指定）
- [ ] 除權息前後波動率是否系統性改變？（類似 K498 earnings 但用台股個股/ETF）
- [ ] 高股息 ETF（0056/00878/00919）除息日前後的價格行為
- [ ] 「填息率」與波動率的關係——填息快的股票 vol 是否較低？
- [ ] 除息日對 0050.TW 的 vol 影響（0050 成分股集中除息期間）

#### SEC Filings 研究與文章方向（用戶提出）
美股的 10-K（年報）、10-Q（季報）、8-K（重大事件即時揭露）是重要的資訊來源和內容題材：

**研究方向（多角度，用戶指定）：**

*文字探勘 (Text Mining)*
- [ ] SEC filing 語調分析：用 Loughran-McDonald 金融情緒詞典對 10-K/10-Q MD&A 段落做正負情緒打分，看情緒變化是否預測後續 vol/return
- [ ] 10-K 可讀性（Fog Index / 文件長度）與後續 vol 的關係——文件越長越晦澀 = 公司在隱藏什麼？
- [ ] 8-K filing 文字 surprise：用 TF-IDF 或 embedding 計算 8-K 與前次 filing 的文字差異度，差異越大 = surprise 越大 → vol spike？
- [ ] Risk factor section 的年度變化：新增風險因子 vs 刪除風險因子 → 對 vol 的預測力

*情緒 (Sentiment)*
- [ ] Management tone（管理層語調）：法說會逐字稿 vs 10-K 書面語調的差異——口語更樂觀但書面更保守？
- [ ] Forward-looking statements 的情緒：MD&A 中「expect」「believe」「risk」的頻率變化趨勢
- [ ] 跨公司情緒傳染：SPY 前 10 大成分股的 filing sentiment 彙總 → 是否預測 index vol？

*財務 (Financial)*
- [ ] 10-K/10-Q filing 前後 SPY vol 是否有系統性模式？（類似 K498 earnings 但更廣泛）
- [ ] 8-K filing（unexpected events）對個股和 index vol 的 surprise 效果
- [ ] Accruals quality（應計品質）vs 後續 vol：低品質 earnings → 高未來 vol？
- [ ] 財務比率的年度變化（debt/equity, current ratio）vs 後續 vol

*管理 (Governance & Management)*
- [ ] CEO/CFO turnover 的 8-K 揭露 → 對 vol 的即時和延遲影響
- [ ] 審計意見變更（going concern, material weakness）→ vol spike 預測
- [ ] 內部人交易揭露（Form 4）與後續 vol/return 的關係
- [ ] TSMC 20-F（外國公司年報）filing 對 TSM/0050.TW 的影響

*台灣重大訊息（用戶提出，MOPS 公開資訊觀測站）*
- [ ] MOPS 重大訊息公告（https://mops.twse.com.tw）：台灣上市櫃公司的即時揭露（類似 8-K），包括營收公告、董事會決議、私募、合併、訴訟等
- [ ] 台股重大訊息公告頻率/內容 vs 後續 vol/return：公告密度高的期間是否 vol 更高？
- [ ] 0050 成分股重大訊息的彙總 sentiment → 是否預測 0050 vol？
- [ ] 法說會逐字稿語調分析（台灣上市公司法說會，可從公開資訊觀測站或各公司 IR 取得）

**文章方向（一般讀者）：**
- [ ] 「10-K、10-Q、8-K 是什麼？散戶為什麼該關心美股年報」(general 教育文)
- [ ] 「財報季前後的波動規律——數據告訴你什麼時候最危險」(general)
- [ ] 「如何從 SEC filing 讀出公司的真實風險」(general 教學文)
- [ ] 「CEO 換人了——股價會怎樣？8-K 告訴你的事」(general)
- [ ] 「年報越厚越危險？文件可讀性與股價波動的關係」(general)

#### 經濟政治不確定性 & 搜尋趨勢 — 持續議題（用戶提出，需定期更新）
過去研究：G14 Google Trends (partial r sig but 反轉)、J3 (IS r=0.634 but VT null)、K446 GPR (reversed causality)、K473 (OOS null)。
這些主題作為**vol research** 已被 VIX sufficiency 限制，但作為**讀者內容和市場解讀**仍然非常重要：

**定期文章（每月至少 1 篇）：**
- [ ] 「本月 Google 搜尋趨勢告訴你什麼？」—— 用 pytrends 抓當月熱門金融搜尋詞，解讀散戶情緒
- [ ] 「經濟政策不確定性指數（EPU）最新動態」—— FRED EPU + 台灣 EPU，搭配時事解讀
- [ ] 「地緣政治風險現在有多高？」—— GPR index 最新值 + 歷史比較 + 對 VIX 的影響
- [ ] 「恐懼與貪婪指數解讀」—— CNN Fear & Greed + VIX + put-call ratio 綜合判讀

**研究更新（當重大事件發生時）：**
- [ ] 特定事件的 Google Trends spike → VIX 反應速度和幅度分析（event study）
- [ ] EPU/GPR 在 tariff/sanction/election 期間的特殊行為
- [ ] 台灣選舉/兩岸關係事件 → VIXTWN/0050 vol 反應（需更長 VIXTWN 數據）

**執行原則：**
- 事件前 2-3 天發佈「預告」文章（一般讀者 + 研究各 1 篇）
- 事件後 1 天發佈「解讀」文章
- 研究實驗在事件前 1 週完成，結果寫入文章
- 用 CronCreate 設定 one-shot reminder 確保不遺漏
- **每月 1 日更新此日曆，覆蓋而非累積**

#### 成交量作為波動率預測因子（用戶提出，理論支持強）
**文獻基礎**：
- Lamoureux & Lastrapes (1990) "Heteroskedasticity in Stock Return Data: Volume versus GARCH" JoF — volume 加入 variance eq 後 ARCH 效應消失，persistence 大幅下降
- Clark (1973) MDH (Mixture of Distributions Hypothesis) — volume 和 vol 都由信息流驅動
- Tauchen & Pitts (1983) — MDH 的正式推導
- K435/K491: persistence 膨脹 +0.073（Hillebrand）→ volume 可能是消除假 persistence 的關鍵

**過去研究（知識庫）**：
- K113: volume GARCH-X null — 但用的是 microstructure proxy 不是 MDH 框架
- K135: GLD volume ratio IS sig 但 OOS null
- K136: BTC volume-conditioned gamma 有效（唯一正面）
- K418: Taiwan volume null（yfinance proxy 太粗糙）

**新研究方向**：
#### ⚠️ K519 上架暫停（K521 data alignment bug）
- [x] K519 VT-Sized Overnight 原本通過全部上架標準（Sharpe 1.079, 5/5 OOS, t=4.26）
- [x] K520 Sensitivity 確認穩健（4/4 維度 wide safe zones）
- [x] **K521 發現 merge_asof bug**：SPY(T) 配 TW(T) 但 SPY 收盤在台股交易之後
- [x] 修正後 Sharpe 更高（4.445）但暴露 I8 timing bias：gap 在開盤拍賣 priced in
- [x] **上架暫停**——需要找到在 5AM-9AM 之間可執行的交易機制才能重啟
- [x] E017: 所有台股用美股信號的策略必須手動驗證日期對齊

- [x] K527: **Volume-GARCH (Lamoureux & Lastrapes 1990 replication)** [提出: 用戶, 執行: K527] — IS persistence drop 確認（SPY 4%, 0050 92%），但 **OOS 完全失敗**（DM t=1.05）。Volume 是 contemporaneous effect（Clark MDH），不是 predictive。detrended volume (V/MA252) 也無效。
- [x] MDH 框架結論：volume 和 vol 同源於 info flow，加入 variance eq 只改善 IS fit 不改善 OOS forecast
- [x] Volume detrending：L&L 用 detrended volume 確實改善 IS，但 OOS 仍然 null（K527 vs K113 一致結論）

#### 台指期貨 Overnight Gap Strategy（K515 延伸，高優先）
- [ ] K515 發現 overnight gap alpha 真實（SPY-conditioned 10.73bp/day, t=4.06）但 ETF TX 38.5bp 致命
- [ ] **台指期貨（TX futures）TX cost 只有 ~2-3bp** → 可能可行！
- [ ] 需要：台指期貨歷史日頻數據（TAIFEX 或 yfinance TWF=F?）
- [ ] 測試：buy TX futures at close, sell at open, SPY-conditioned
- [ ] 如果 Net Sharpe > 0.5 + cross-OOS 4/5 → 第一個可能上架的新策略

#### Codex 第6次審查：Taiwan VT 論文（2026-03-27）
**5 個需修正的問題：**
1. ⚠️ 4.6x amplification 用 10 個股票樣本太小，機制解釋（correlation asymmetry/retail herding）過強
2. ⚠️ Opening auction "remarkably efficient" 語氣太強——只有 c2c-o2o gap 不算直接的 auction efficiency test
3. ⚠️ TZ alpha 用不可交易的 c2c headline，o2o Sharpe 低於 Harvey——混淆了
4. ⚠️ Table 3 策略比較混用 2010-2026/2016-2026/2020-2026 不同期間——not apples-to-apples
5. ⚠️ 29 switches/year × 0.3%/switch ≠ 1.7% annual cost（算術錯誤需修正）
6. 語氣過於 promotional（"formal statistical confirmation", "fatal timing problem"）→ 需 tone down

#### Codex 第6次審查：Leverage-Direction 論文（2026-03-27）
**3 個最弱聲明 + 邏輯錯誤：**
1. ⚠️ TZ arbitrage 在 intro/conclusion 說 "tradable alpha" Sharpe 1.61，但 appendix 承認 78% 不可捕捉、o2o fails Harvey
2. ⚠️ gamma>0.10 model selection rule 看似 post-hoc（12 cases 太少），且同一 SPY 數據後面說 symmetric GARCH outranks GJR
3. ⚠️ Proposition 1 的 rank correlation 接近 mechanical（beta_trend 由 GJR gamma 生成，非獨立驗證）
4. 🔴 日期不一致：data section 說 2017-2025 但引用 2026-03 驗證
5. 🔴 gamma window 先說 "non-overlapping" 後說 "504-day stepped by 63 days"（矛盾）
6. 裁判最可能批評：heavily searched design overstates OOS results，Asian arbitrage 不 survive implementability

#### Codex 審查：VT-Trend-Following 論文（2026-03-27）
**3 個最弱聲明 + 3 個錯誤：**
1. ⚠️ "almost entirely independent of trend following" 語氣過強（只 5 assets + MDD 是單一路徑統計）
2. ⚠️ gamma "mechanical explanation" 過於因果（N=22 mixed cross-section，是 correlation 非 mechanism）
3. ⚠️ "irreducible" / "VT≠TF" 的 trend strategy 比較缺少表格/specification 細節
4. 🔴 L164 "mechanically zero" vs Table 1 報非零 Δalpha（矛盾）
5. 🔴 Table 3 M5 描述含 MOM+BAB 但 β_MOM 空白、N 常數但 note 說 post-2011
6. 🔴 L352 說 EWT 改善但表格是 EWJ（text/table mismatch）
