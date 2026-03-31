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
- **50/50 SPY/GLD 不可動搖**（K2/K16/K19/K24/K54/K63/K64/K89 — 8 次驗證 + K534 理論解釋：correlation dynamics 不可預測）

#### Codex 第 7 次建議：從預測轉向策略（2026-03-27）[提出: Codex GPT-5.4]
**核心洞見**：瓶頸不是預測 RV，而是判斷何時 forecast 值得交易。
- [x] **Cross-Asset Vol Momentum**：K730 — 6/8 signals Granger-cause VIX（TLT lag=7 p=0.006, USO lag=5 p<0.001），但 OOS composite R² WORSE than VIX-only（-0.022）。Strategy wins 2/5 vs 50/50。**結論：可偵測但不可用。VIX sufficiency 第 24 次確認。** 文獻：Xu (2025) I-XTSM, CFA Institute (2025) MOVE→VIX stress-only。
- [ ] **Conditional Dispersion Trade**：預測 correlation risk premium mispricing → index vs sector options。需 sector ETF options data。
- [x] **Regime-Switched Carry Filter**：K763 NULL — binary switching 顯著差於 12/VIX（DM p<0.001）。平滑連續>離散二元。Codex 0 HIGH
- [x] **Alt Risk Premia Rotation**：K760 NULL — 混合 4 弱信號=信號稀釋。12/VIX 簡單最強。Codex 4/4 PASS
- [x] **Action-First ML (Meta-Model)**：K762 NULL — consensus=12/VIX 平滑版，不勝 50/50。Codex 2 HIGH（weight parsing + binary consensus）
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
- **VIX sufficient statistic**（25+ 次確認：K43/K48/K57/K61/K65/K80/K84 + K730 cross-asset + K731 term structure + K732 behavioral sentiment + 歷史 15 次）
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

**已完成實驗**：見 `docs/research_archive/completed_phases_2026-03.md`（I0, I1, I1b, I2, I3, I5, I6, I8, I9, I10, I11, I12, K199, K340, K341, K417）

**研究方向（開放）：**
- [ ] I4: VIX futures roll yield 策略 — contango 環境下的 roll yield 收割 vs 尾部風險保護 ⚠️ **BLOCKED: 需要 VIX futures 歷史數據（yfinance 無）**
- [ ] I7: 台灣投資人跨境避險實務 — 用台指期避台股、用 ES mini 避美股，匯率風險、保證金需求、稅務影響

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
- [x] 台灣公債殖利率曲線：K761 — partial r=0.117 at 126d（Harvey PASS），但交易 NULL。曲線反轉+台股牛市=減倉錯誤。Codex 0 HIGH
- [x] 台灣 CoVaR 傳染結構：K757 — **金融股→TSMC**（非反向）。TSMC CoVaR β=0.102 (p=0.0006)。VIX 仍足夠
- [ ] **金融股早期預警系統**：K757 發現 Fubon→TSMC Granger (F=6.11)。可建立金融股壓力指標作為 TSMC vol 早期預警
- [x] 台灣月頻 VT 最佳實務完整指南（mile_9fed5ece，3500 字，整合 K739b/K738/K636/K82/K725）

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
- 初稿、Codex 審查、引用驗證已完成（見 archive）
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
| 類型 | 位置 | 說明 |
|------|------|------|
| 完成 Phase 詳細記錄 | docs/research_archive/completed_phases_2026-03.md | 含所有 Phase O~K + K426-K753 逐實驗結果 |
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

**2026-03-27 學術前沿文獻掃描（4 方向 × 12 篇）：**

**方向 1: ML-GARCH 混合模型（5 篇）**
- [ ] **KAN-GARCH-MIDAS** (J. Applied Economics 2025, 作者未標) — Kolmogorov-Arnold Network 取代 MLP 處理 GARCH-MIDAS 的長期宏觀成分，MAE 優於傳統 GARCH 8%（SP500 0.2532 vs 0.2743），COVID 前後穩健。**與我們關係**：K862 已記錄 ML 整體無法勝 GARCH（Branco 2024 支持），但 KAN 是結構化 NN（可學習 activation），非黑箱——值得測試是否打破 QLIKE ceiling
- [ ] **GARCH-Informed NN (GINN)** (arXiv:2410.00288, 2024) — GARCH 初始化 LSTM calibration。**與我們關係**：K426 已測 GINN null。但該論文用 5-min RV 做 target，我們用 daily proxy——proxy 差異可能解釋結果差異
- [ ] **Sentiment-Augmented GARCH-LSTM** (Computational Economics 2025) — VaR 場景加入情緒指標。**與我們關係**：K473 Attention/Google Trends OOS null，但該論文用 NLP 情緒（不同信號）
- [ ] **KAN for VIX Forecasting** (Expert Systems with Applications 2025) — 直接用 KAN 預測 VIX，可解釋。**與我們關係**：VIX 預測是 VT 策略上游——如果 VIX 可預測，12/VIX 策略可增強
- [ ] **MF2-GARCH** (J. Applied Econometrics 2025, Conrad & Engle) — 短期 GJR + 長期乘法誤差模型，顯著優於單組件 GJR 和 HAR。**與我們關係**：K862 已記錄，K475 GJR+HAR ensemble 5/5 是否等價？MF2 用 MEM 不是 HAR——可能是更優替代

**方向 2: HAR-RV 新方法（4 篇）**
- [ ] **Bespoke Realized Volatility** (J. Econometrics 2026, Patton & Zhang) — ML 估計最優「客製化」RV（加重日末數據），886 隻美股 OOS 顯著改善 HAR 和 GARCH-X。**與我們關係**：★★ 我們 K465 HAR log-range 8/10 用標準 Parkinson——bespoke 可能進一步改善。但需要 tick data（目前無）
- [ ] **Volatility Forecasting Factors** (SSRN 2025, Cinquetti, Hong, Nolte) — 287 個高頻因子動態選擇，擴展 HAR。**與我們關係**：等 5-min 數據 60+ 天（已在待探索）
- [ ] **HAR-PD Path-Dependent** (arXiv:2503.00851, 2025) — HAR + 路徑依賴波動率模型，用 price memory 捕捉趨勢。**與我們關係**：已在待探索。可用日頻近似測試
- [ ] **Window Size Selection** (J. Forecasting 2025, Feng & Zhang) — 最優滾動窗口 1000-2000，U-shape loss。**與我們關係**：★ 直接確認我們的 W=2000 選擇合理（非 ad hoc）。可做 sensitivity sweep 驗證

**方向 3: VIX / Vol Targeting 策略（2 篇）**
- [ ] **VIX-Managed Portfolios** (Int. Rev. Financial Analysis 2024) — VIX 水平直接調整槓桿，1990-2023 alpha 顯著。**與我們關係**：★ 我們的 12/VIX 本質相同（inverse VIX scaling）。該論文 8431 日觀察確認策略有效——可引用支持我們的 VT 結論
- [ ] **ML Risk-Based Allocation** (Scientific Reports 2025) — LSTM + differentiable risk budgeting + regime switching，Sharpe 1.38（+55% vs risk parity）。**與我們關係**：用 VIX/TED/yield curve 做 regime indicator。我們 K503 VIX mean-reversion null，但該方法是 regime-adaptive 不是 mean-reversion

**方向 4: Rough Volatility 與 Hurst（3 篇）**
- [ ] **Multivariate fBm for RV** (arXiv:2504.15985, 2025) — 不同 Hurst 指數 + 非零相關的多變量 fBm，OOS 改善單變量。**與我們關係**：K862 記錄 rough vol 實務不如 GARCH（Abi Jaber 2025）。但多變量版本可能不同——需測試
- [ ] **Time-Varying Hurst via EWMA** (arXiv:2509.05820, 2025) — EWMA 驅動動態 Hurst 參數，勝傳統 rough Bergomi。**與我們關係**：Hurst 隨 regime 變化的 idea 可用在 GJR gamma 上（gamma 也非恆常）
- [ ] **Adaptive Fractal Dynamics** (Frontiers Applied Math 2025) — 小波分析估計時變 Hurst，RMSE -12.3%, R²>0.72。**與我們關係**：如果 Hurst 真的時變且可預測，這是突破——但需驗證是否只是 in-sample fitting

**方向 5: Transformer 與深度學習（2 篇補充）**
- [ ] **Vision Transformer for RV** (arXiv:2511.03046, 2025) — 從 IV surface 圖像預測 30-day RV。**與我們關係**：完全新範式（image→vol），但需 options data
- [ ] **PatchTST-lite vs HAR-RV** (MDPI 2025) — 首次系統比較 Transformer 與 HAR-RV，2000-2025 美股。**與我們關係**：已在待探索。K142/T22/R10 三次確認 ML 日頻不勝 GARCH，但 Transformer 在 RV（高頻 proxy）上可能不同

**即刻可行動項目（不需新數據，可用現有日頻數據）：**
1. ★ Window Size Sensitivity（確認 W=2000 最優）— 對應 Feng & Zhang 2025
2. ★ MF2-GARCH 實作（短期 GJR + 長期 MEM）— 對應 Conrad & Engle 2025
3. KAN-GARCH-MIDAS（如果 KAN 套件可用）— 結構化 NN 可能突破 ML ceiling
4. VIX-Managed Portfolio 文獻引用整理 — 支持 Paper 3 (VT-Trend)

**2026-03-26 新增：Bayesian Subset Selection + Smooth Transition 方法論（用戶指定）：**
- [ ] K433: **Bayesian SSVS for ARX-GARCH** — So, Chen, Liu (2006) JRSS-C, 55(2), 201-224. Latent binary indicator δ_i + MCMC 從 2^(p+q) 子集空間搜索最優外生變數組合。比 K113 逐一測試更有力。**進行中**
- [ ] K431: **Smooth Transition GARCH (STGARCH)** — González-Rivera (1998), Hagerud (1997). 允許 GARCH 參數漸進轉換（VIX 作為 transition variable）。K427 發現結構性斷裂，ST 可能比 abrupt switch 更合適。**進行中**
- [ ] K432: **Bayesian MCMC GARCH** — 用 Metropolis-Hastings 估計 GJR-GARCH 後驗分布，量化參數不確定性。比 MLE 點估計更穩健。**進行中**
- [ ] Bayesian Subset Selection for TARMA — Chen, Liu, Gerlach (2011) Computational Statistics, 26, 1-30. 擴展 SSVS 到 threshold + MA terms，16M+ 可能子集
- [ ] Threshold Variable Selection for Asymmetric SV — Chen, Liu, So (2013) Computational Statistics, 28, 2415-2447. Combined threshold variable Z_t = Σω_i Z_i，同時選 threshold 變數和模型結構。五個亞洲市場實證
- [ ] SSVS for Variance Equation — 將 SSVS 擴展到 variance equation（GARCH-X 的 variance side 加外生變數），目前 K433 只處理 mean equation
- [ ] Threshold GARCH with Bayesian Model Selection — 結合 2006+2013 方法：threshold GARCH + SSVS 同時選 regime 結構和變數子集

**K426-K476 完成實驗（已存檔）**：見 `docs/research_archive/completed_phases_2026-03.md`
**關鍵發現**：HAR log-range 8/10 cross-OOS (K469)、Semivariance 4/5 (K460)、GJR+HAR ensemble 5/5 (K475)。方法論：Prediction ≠ Application、Significance ≠ Forecasting、Cross-OOS 3/3 false positives caught。

**K478-K495 完成實驗（已存檔）**：見 `docs/research_archive/completed_phases_2026-03.md`

### 最終工具指南（K426-K495, cross-OOS validated）
| 任務 | SPY | Other equity | Non-equity | Taiwan |
|------|-----|-------------|------------|--------|
| **Forecasting** | **GJR-X(VIX9D) ★★★** | GJR+HAR ensemble | GARCH(1,1) | GJR alone |
| **VaR** | **GJR-X(VIX)** | GJR-X(VIX) | GJR alone | GJR-SkewT |
| **VT Strategy** | 12/VIX | 12/VIX adapted | Asset-specific | 8.63/VIX |

**最終最佳模型**：GJR-GARCH-X(VIX9D) — Forecasting QLIKE -17.7%, VaR Trinity 3/3, delta CV=0.08 (ultra-stable)。日頻方向已完全飽和，下一突破需 5-min HAR-RV（ETA 2026-04-11）。

### 報酬率預測（用戶提出，全新方向線）
- [ ] K501: **SSVS for Return Prediction** [提出: 用戶] — 用陳婉淑方法預測報酬率（不只波動率）。K461 已發現 SPY_ret PIP=1.000 for Taiwan (t=10.81)。**進行中**
- [ ] Return prediction → trading strategy pipeline：如果方向準確度 > 55% → 可做 long/short 策略
- [ ] 跨資產 return prediction：SPY、0050.TW、QQQ

### 新交易策略開發（用戶提出）
**已上架策略**（vix_cond_leverage / taiwan_hybrid_leverage / piecewise_conservative / fear_dca / adaptive_tier）：見 `docs/research_archive/completed_phases_2026-03.md`
- [ ] K502: **US→Taiwan Lead-Lag Strategy** [提出: 用戶] — 用 SPY return 信號交易 0050.TW。T32/T33 confirmed lead-lag (r=0.376)。**進行中**
- [ ] K503: **VIX Mean-Reversion Strategy** [提出: 用戶] — 利用 VIX spike 後的 mean reversion 做交易。K430/K491 支持。**進行中**
- [ ] 策略上架前必須：Cross-OOS ≥ 5 periods、3 年回測、Net Sharpe (after TX) > 0
- [ ] **不要輕易上架**——交易策略必須多次確認（cross-OOS + out-of-sample + sensitivity），避免上架後發現是錯誤

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
K519-K521 完成結果 + K527 Volume-GARCH 結果：見 `docs/research_archive/completed_phases_2026-03.md`
**結論**：上架暫停——需要找到在 5AM-9AM 之間可執行的交易機制才能重啟。E017: 所有台股用美股信號的策略必須手動驗證日期對齊。

#### 台指期貨 Overnight Gap Strategy（K515 延伸，高優先）
- [ ] K515 發現 overnight gap alpha 真實（SPY-conditioned 10.73bp/day, t=4.06）但 ETF TX 18.55bp 致命（K625 更正：原為 38.5bp）
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
5. ⚠️ 29 switches/year × 0.1855%/switch (ETF round-trip, K625 corrected) — 需修正論文中的 0.3% 引用
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

---

## Next Session Priorities（2026-03-30 起）

基於 K621-K701 session（81 實驗、paradigm shift: VT=insurance not alpha、K693 數據修正、4 Codex 審查），依優先級排序。

### 重大研究結論更新（2026-03-29 K687/K697/K700/K701）

**VT 策略是 drawdown insurance，不是 alpha generator。**
- K687：正確 lag 後，沒有 VT 策略在 Sharpe 上打敗 BH 50/50（0.545）
- K697：VIX 預測 vol（corr 0.57）但不預測 direction（corr 0.04）——daily alpha 理論不可能
- K701：weekly/monthly 也一樣（direction corr 全部<0.04）
- K688：VT 在 CRRA utility γ≥5 時勝出——drawdown protection 對風險厭惡投資人有價值
- K693：歷史 paper_trading 9935 筆修正 same-day→next-day return
- K700：Codex 審查防止 3 個 false breakthrough（37.5% false positive rate without review）

### P0: 時間敏感

| 項目 | 說明 | 截止日 |
|------|------|--------|
| **NFP 04/03 事後文章** | 非農數據發布後 1 天內發解讀文（K661 數據已備） | 04/04 |
| **HAR-RV 正式實驗** | 5-min 數據 ETA 04/11 達 60 天門檻 | 04/11 |
| **TSMC 營收 04/10** | 預告+解讀文 | 04/08, 04/11 |
| **TSMC 法說 04/16** | 預告+解讀文 | 04/14, 04/17 |

### P1: 高價值

**新研究主軸（用戶提出 2026-03-30）：**
- [ ] **什麼是好的交易策略？多維度評估框架**：不只看 Sharpe——CAGR、勝率、壓力情境表現、操作複雜度、TX 成本都要。高 Sharpe 但 CAGR 3% 不算好策略。建立量化評估矩陣。
- **恐慌麻痺效應（Paper 4）已完成**：33p 論文完成，Codex 審查通過，已上架 Supabase（target JFE）

**論文修正：**
- [ ] **Leverage-Direction**（K628 已瘦身 64→52p）：加入「VT is insurance」框架
- [ ] **Taiwan VT**：K636 修正 amplification（gamma vs vol level）、TX cost 已修正
- **VT-Trend**：6 項 K585 Codex 修正已完成（2026-03-30）

**平台經營方向（基於 analytics：192 views, 3 users, 10 reactions）：**
- [ ] **SEO 是最優先**：3 個用戶太少，需要 Google Search Console + sitemap 提交
- [ ] **加強入門內容**：「從零開始」是最熱門文章之一，應建立 /guide 頁面
- [ ] **減少學術文章比例，增加實務操作指南**：收藏(7)>按讚(3) = 讀者當工具書用
- [ ] K705 GAP-03：StrategySelector 不要突出 CAGR

### P2: 研究新方向

**從 K730-K752 實驗中衍生的新方向（2026-03-31 補充，已完成項目見 `docs/research_archive/completed_phases_2026-03.md`）：**

**高優先（有明確下一步）：**
- [ ] **HAR-RV 正式實驗**：K744 驗證數據 94% clean，K745 pipeline 通過。SPY 51 天（ETA 60 天 ~04/07），需 100+ OOS days ~05 月。到時重跑 HAR-RV vs HAR-ABS vs GJR 的完整比較
- [x] **Fix K739 Taiwan holiday handling**：K739b 修正完成。TW/US calendar 分離 + VIX asof-lookup。**所有 4 結論存活**（20/80 配置 + daily rebalance + VIX suff + calendar NS）
- [x] **Fix K746 Granger methodology**：K746b 修正完成。BTC vol → VIX Granger **存活**（p=0.0002, AIC lag=10）。VIX → BTC vol 較弱（p=0.013）。斷點 2022-08-10。**Paper 6 方向確認**
- [ ] **Paper 6: Crypto Fear Channel**：K746b 確認 BTC vol asymmetrically Granger-causes VIX。結合 coupling 增加 + tail dependence，可寫成「加密貨幣市場對傳統金融的波動率溢出」論文
- [ ] **Paper 5 正式撰寫**：草稿 31p 已完成。Codex 建議 J. Forecasting。需要：統一 pipeline（不只 VIX，含 HAR-RV/GARCH benchmark）、多重檢定控制、replication package
- [x] **K753 Liquidity-Vol**：NULL — partial r=0.089, VIX 已定價 volume。VIX sufficiency #12
- [x] **Volume Exhaustion Effect**：K754 REJECTED — extreme volume 預測更高 vol（+86.5%, t=6.01），非更低。K753 是 confound：VIX 已高→mean revert→低 spike 但高 RV
- [x] **VT Insurance 實務指南頁面**：/vt-calculator 完成。風險測驗→gamma→策略推薦。K738 confirmed

**中優先（新研究主題）：**
- [x] **FOMO 行為干預設計**：K755 — Lock-5d 最佳（+4% Sharpe vs 12/VIX），但仍不勝 BH 50/50。Mean reversion 真實（t=-2.07）。最佳用途=行為護欄（MDD -1-2pp），非 alpha
- [ ] **Robust VT 設計**：K743 的 floor(30%)/cap(90%) + EWMA 平滑 + 週頻 rebalance 組合。修正 Codex 找到的 bug 後重跑
- [ ] **VIX Regime 轉換預測**：K752 發現不同 era 的 VIX R² 差異大（0.24-0.64）。能否預測 VIX regime 何時轉換？（從低 vol QE 進入高 vol inflation era）
- [ ] **Drawdown Recovery 修正版**：K735 被 Codex 推翻（fake OOS + timing misalign）。修正方法論後重做——用 proper expanding window OOS + peak-to-first_cross recovery time
- [ ] **跨國 VIX sufficiency**：K752 證明 US 33 年成立。在其他市場（歐洲 VSTOXX、日本 VNKY、台灣 VIXTWN proxy）驗證？
- [ ] **Alternative data**：K750 Google Trends 是反應式。嘗試 Reddit/Twitter 情緒（可能更即時）或 options flow（CBOE 數據）
- [ ] **Intraday alpha**：5-min 數據就緒後，測試日內 VIX-equity lead-lag（K751 overnight 有 +0.45% R²，日內可能更多）

**低優先（長期探索）：**
- [ ] **VT 與 ESG 整合**：ESG 評分高的公司是否有不同的 gamma（leverage effect）？
- [ ] **Agent-Based Model 正式版**：K742 用簡化 Kyle's lambda。正式 ABM 可模擬異質投資人（VT users + momentum + value + passive）的市場均衡
- [ ] **因果推論**：用 DiD/RDD 分析 Fed 升息決議對 VIX regime 的因果影響（非相關）
- [ ] **Climate vol**：極端天氣事件頻率增加是否改變 vol 動態？（新的 non-stationary source）

### P3: 長期待辦

**研究：**
- [ ] Rough Volatility multivariate（需理論準備）
- [ ] Decision-focused policy learning（contextual bandit）
- [ ] 除權息季節研究（06 月）

**平台：**
- [ ] Feature gating（V0.7）
- [ ] API rate limiting（V0.9）
- [ ] Email/LINE 訂閱（W3.1）
