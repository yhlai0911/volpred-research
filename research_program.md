# Research Program: Autonomous Volatility Prediction

## 目標（持續推進，永不完成）
1. 持續找出選定資產的最佳 1-step ahead 波動率、VaR/ES、報酬率預測模型
2. 持續建立一般非專業投資人可運用的各種交易策略
3. 持續找出利用研究成果獲利的模式
4. 持續找出並優化本網站的風格、經營模式、發展方向，持續修正朝之前進

## 行為準則（統一區）

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

### 模型比較公平性標準（2026-03-31 建立，K777/K778 教訓）

**不同類型波動率模型（GARCH/MEM/HAR）預測不同 target（σ²/|r|/RV）。比較必須公平。**

| 評估層次 | 方法 | 為什麼需要 | 依據 |
|---------|------|----------|------|
| **各自最佳** | 每個模型在原生 target 評估 | 展示各自天花板 | — |
| **統一 proxy-robust** | QLIKE on r²（squared return） | r² 是 σ² 的無偏估計，排名有理論保證 | Patton (2011) |
| **分配無關** | Spearman rank correlation | 不需要任何轉換或分配假設 | — |
| **多模型控制** | MCS（Model Confidence Set） | 控制 data snooping，找不可區分最佳集 | Hansen, Lunde & Nason (2011) |
| **經濟價值** | 策略 Sharpe/MDD/Utility | 預測好 ≠ 交易好（K770b 教訓）| — |
| **高頻標準**（若有 5-min） | QLIKE on RV | 最精確的真實 vol proxy | Hansen & Lunde (2005) |

**每次模型比較實驗必須至少包含前 3 層。不可只報告對自己有利的 target。**
**MEM 可直接建模 r²（不需轉換）——與 GARCH 在相同 σ² 空間公平比較。**
**K782 教訓：Proxy 比模型更重要——HAR 在 |r| 目標 DM=-15.45（K530），但在 r² 目標全輸 GJR。**

### 經濟顯著性評估（VaR/ES）
**不同模型預測不同東西，計算 VaR 時必須做正確的分配轉換，不可直接用預測值當 VaR：**

| 模型 | 原生預測 | → VaR 轉換 | 注意 |
|------|---------|-----------|------|
| GARCH/GJR | σ² | VaR = σ × z_α | z_α 取決於創新分配（Normal/Student-t/Skewed-t）|
| MEM(\|r\|) | E[\|r\|] | σ = E[\|r\|] / C_gamma → VaR | C 來自 Gamma 分配，非 √(2/π) |
| MEM(r²) | E[r²] | σ = √E[r²] → VaR | Gamma 創新 |
| HAR-RV | E[RV] | σ = √RV，需 HAR 殘差分配 | log-normal 或 F |

- Backtesting: Kupiec + Christoffersen + Basel traffic light
- K768 Conformal VaR: model-agnostic 後校準（避開分配假設）

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
- ⚠️ **K783/K783b 結論**：expanding window 在 SPY 勝 w=2000 但在 QQQ 反向（小 window 勝）。**最優 window 因資產而異，w=2000 仍是合理通用預設。**
- 5-min 數據：SPY 46 天 / 0050.TW 35 天（需 60+ 天 HAR-RV，ETA 2026-04-11）。收集正常（collect_us_data.py 自動調用 collect_5min_data.py）

### 評估指標
- **統計性**：QLIKE (主), MSE, MAE, HMSE, Mincer-Zarnowitz R², DM test, MCS, GW test
- **風險管理**：Trinity test (Kupiec+CC+DQ), Fissler-Ziegel, Acerbi-Szekely ES, Basel traffic light
- **經濟性**：Sharpe (Harvey t>3), MDD (bootstrap p<0.001), Calmar, Sortino, CRRA utility, CE return, Net Sharpe (after TX), Turnover
- **跨模型**：CCS Score, FDR audit, Cross-OOS 5 periods, Weight StdΔw
- 每個實驗必須 re-estimate each window（no lookahead）

### 研究多元化原則

**不要停留在模型舒適區。** 已驗證的結論（VIX sufficiency 23 次、50/50 不可動搖 8 次）不需要繼續堆積 null results。研究應同時在兩條軸推進：

**漸進式延伸（從已知出發）**
- 從現有面向自然衍生新問題
- 用新數據重新驗證舊結論
- 把已知方法應用到新資產/新市場

**跳躍式探索（進入未知領域）**
- **每個 session 至少 1 個「完全不同方向」的實驗**
- 不同領域的模型：NLP 情緒分析、替代數據（衛星/網路流量）、圖神經網路、因果推論
- 不同資產生態：加密 DeFi 協議、私募市場、碳權交易、大宗商品指數
- 不同研究方法論：行為金融實驗設計、市場微結構（order flow）、網絡/傳染模型、agent-based simulation
- 不同應用場景：ESG 整合波動率、氣候風險定價、地緣政治事件驅動策略
- 不同視角：投資人行為偏誤利用、制度摩擦套利、監管變化影響

**判斷「是否在舒適區」的檢查清單**
- [ ] 這個實驗是否只是「換一個 overlay 測 VT」？→ 可能在舒適區
- [ ] 這個模型/方法是否已經在其他實驗中用過？→ 考慮全新方法
- [ ] 預期結果是否又是一個 null result？→ 如果連續 3 個 null，換方向
- [ ] 這個問題能否用完全不同的方法回答？→ 嘗試不同方法論

### 研究主題來源（必須多元）

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
  - **⚠️ K782 修正**：HAR 在 r² target 上**全輸** GJR（5d/22d/66d DM 全正）。HAR 優勢限於 |r| target。日頻 squared returns 做的 RV 不足以讓 HAR 發揮。**Proxy 比模型更重要**。
- **★★★ Rough Volatility (K529)**：H=0.1 確認 roughness。HAR-Rough 顯著勝 GJR (DM=-7.04) 但未勝 EWMA。Time-varying H 反而更差。
- **K526 GARCH-MIDAS**: OOS 未勝 GJR，但 regime 轉換期（COVID/升息）有局部優勢。long-run τ 僅解釋 11% variance。
- **MF2-GARCH**（Conrad & Engle 2025: 短期 GJR + 長期乘法誤差模型）— 測試中
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

### 面向 F: 網站與系統
- 前端功能（12/VIX 計算器, Feed 品質, Paper 下載）
- 部署架構（v2 Supabase + Zeabur）
- 知識索引（LanceDB embedding）
- AI 協作模式（Claude + Codex + Gemini）
- 平台操作層（`/admin/*`、`/api/admin/*`、`uv run volpred ops ...`）
- 讀者分析回饋（analytics summary → 研究與發文方向）
- 會員問題排行與研究候選池

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

### 面向 I: 期貨避險（Futures Hedging）
**動機**：K341 建立框架（ES=F r=0.978, VIX>25 tail hedge 資本效率最高），需深化為完整研究路線。
**核心問題**：期貨避險能否系統性改善 50/50+VT？台灣投資人如何用台指期？

**⚠️ 方法論原則：避險效果用避險指標評估，不跟交易策略比 Sharpe/CAGR**
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
- [ ] **金融股早期預警系統**：K757 發現 Fubon→TSMC Granger (F=6.11)。可建立金融股壓力指標作為 TSMC vol 早期預警

**論文**：第二篇 `paper/taiwan-vt/main.tex`（34 頁）涵蓋台灣 VT + TZ 資訊傳遞

## Codex/Gemini/用戶建議（統一區）

### Codex 第 7 次建議：從預測轉向策略（2026-03-27）[提出: Codex GPT-5.4]
**核心洞見**：瓶頸不是預測 RV，而是判斷何時 forecast 值得交易。
- [ ] **Conditional Dispersion Trade**：預測 correlation risk premium mispricing → index vs sector options。需 sector ETF options data。
（已完成項目見 archive：K730 Cross-Asset Vol Momentum, K763 Regime-Switched Carry Filter, K760 Alt Risk Premia Rotation, K762 Action-First ML）

### Codex 第 8 次建議：從 vol 預測轉向風險管理實務（2026-03-31）[提出: Codex GPT-5.4]
**核心洞見**：VIX sufficiency 已確認——不再嘗試打敗 VIX，改為用 VIX 建構更好的風險管理工具。
- [ ] **跨資產 All-Weather VT**：SPY+TLT+GLD+DBC+SGOV+BTC ETF 組合，target-vol + weight caps + cash floor。超越 2-asset。可行性高。
- [ ] **債券壓力去風險信號**：HYG/LQD/TLT spread + rolling vol → 預測 SPY downside semivariance。非 VIX 依賴的去風險規則。
- [ ] **Dispersion Timing（index vs sector）**：當 sector 分散度高時，equal-weight sectors > hold SPY。long-only ETF 實作。
- [ ] **Tail-First ES 配置 + Conformal Calibration**：從「預測 vol」轉向「控制尾部風險」。inverse-ES 配置 + 校準覆蓋率 OOS 驗證。
- [ ] **Event-Risk Budgeter（CPI/FOMC/NFP/Earnings）**：事件窗口自動半倉。實務投資人工具，不只是事後分析。

### Codex 第 5 次建議（2026-03-26）[提出: Codex]
- [ ] **Decision-focused policy learning**：不預測 return/vol 再映射到交易，而是直接學習最優行動（contextual bandit / dynamic treatment）。回應核心發現「prediction ≠ trading」
- [ ] **Two-clock decomposition: overnight + intraday + jump**：分開建模 close-to-open / open-to-close / jump probability，只交易有信號的 segment。K451 已做描述性分析但未做策略
- [ ] **Options surface state variables**：超越 VIX/SKEW 的 scalar summary，用完整 IV surface（left-tail slope, corridor variance, GEX/vanna, 0DTE share）。⚠️ BLOCKED: 需 options 歷史數據
- [ ] **Dispersion / correlation-regime trading**：將 DCC/copula/network 分析（K443/K444/K455）轉化為策略：sector dispersion, correlation breakdown trades, network-hub rotation
- [ ] **Event-surprise strategies**：不是 calendar dummy（K498 null），而是用 surprise component（fed funds futures surprise, CPI surprise vs option-implied move）。條件預測比無條件預測更可行

Codex 優先排序：(1) Decision-focused policy (2) Overnight/intraday decomposition (3) Dispersion trading

### Gemini 第 2 次建議（2026-03-31，行為金融 + 方法論 + 實務工具）[提出: Gemini]
- [ ] **Retail Reflexivity & Gamma-Driven Skew**：0DTE 散戶 flow 導致 delta-hedging 連鎖反應，可能打破 VIX sufficiency。量化 "Volatility Gap"（VIX-implied vs flow-induced realized move）。⚠️ BLOCKED: 需 order flow 數據
- [ ] **Path Signatures for Rough Volatility**：用 rough path theory 的 signature transform 編碼日內價格路徑的幾何特性，捕捉 HAR 遺漏的路徑依賴性。需 5-min 數據（ETA 04/11）
- [ ] **Convexity-Adjusted Insurance Premium Tool**：VT 的核心問題是 carry cost。用 Vol-of-Vol 聚類判斷保險是否被高估，建議「Strategic Under-Hedging」在高 VoV-decay 期間回收被拖累的 alpha。可結合 K41 保險費定價（~4%/yr）

### Gemini 第 1 次建議（2026-03-26，台灣特色 + 免費數據）[提出: Gemini]
- [x] ~~Taiwan Price Limit Latent Volatility~~ → **K790v2 完成 NULL**：>5% 天數僅 0.9%，GJR asymmetry 已捕捉。DM 全 NS。
- [ ] **FRED STLFSI4 Macro Stress Regime**：用聖路易金融壓力指數做 regime switching，壓力期降低 target vol (12%→8%)。Data: FRED STLFSI4
- [ ] **VIX→Taiwan Vol Spillover Strategy**：VIX 在美股時段 spike > 15% → 次日台股開盤自動減倉。比 return lead-lag 更直接。Data: yfinance
- [ ] **TXO Put-Call Ratio Mean-Reversion**：台指選擇權 P/C ratio 作為散戶恐慌指標，極端值做反向操作。Data: TAIFEX 網站
- [x] ~~EWT vs 0050.TW Vol Arbitrage Spread~~ → **K792 完成**：Granger YES (F=28.4) 但方向反（高 ratio → vol 下降）。Trading 虧損。Mean reversion 陷阱。

### 用戶提出方向
- [x] ~~什麼是好的交易策略？~~ → **K793 完成**：8 維度評估 6 策略。BH 50/50 #1 (75.4), Risk Parity #2 (73.7), Piecewise #3 (54.0，唯一正 stress)。單一 Sharpe 遺漏大量 tradeoffs。
- [x] **HAR-RV with 5-day RV** [提出: 用戶, 2026-03-31] → **K782 完成**：GJR-GARCH multi-step 在 5d/22d/66d 全勝 HAR。日頻 squared returns 做的 RV 不足以讓 HAR 發揮優勢——需等 5-min 數據。
- [ ] **MEM（Multiplicative Error Model）** [提出: 用戶, 2026-03-31]：Engle & Gallo (2006) 的相乘誤差模型，作為 GARCH 和 HAR 之外的第三條路線。適合正值時間序列（RV, volume, duration）。
- [ ] K501: **SSVS for Return Prediction** [提出: 用戶] — 用陳婉淑方法預測報酬率（不只波動率）。K461 已發現 SPY_ret PIP=1.000 for Taiwan (t=10.81)。**進行中**
- [ ] Return prediction → trading strategy pipeline：如果方向準確度 > 55% → 可做 long/short 策略
- [ ] 跨資產 return prediction：SPY、0050.TW、QQQ
- [ ] K502: **US→Taiwan Lead-Lag Strategy** [提出: 用戶] — 用 SPY return 信號交易 0050.TW。T32/T33 confirmed lead-lag (r=0.376)。**進行中**
- [ ] K503: **VIX Mean-Reversion Strategy** [提出: 用戶] — 利用 VIX spike 後的 mean reversion 做交易。K430/K491 支持。**進行中**
- 策略上架前必須：Cross-OOS ≥ 5 periods、3 年回測、Net Sharpe (after TX) > 0
- **不要輕易上架**——交易策略必須多次確認（cross-OOS + out-of-sample + sensitivity），避免上架後發現是錯誤

### Bayesian Subset Selection 方法論（用戶指定，2026-03-26）
- [ ] K433: **Bayesian SSVS for ARX-GARCH** — So, Chen, Liu (2006) JRSS-C, 55(2), 201-224. Latent binary indicator δ_i + MCMC 從 2^(p+q) 子集空間搜索最優外生變數組合。比 K113 逐一測試更有力。**進行中**
- [ ] K431: **Smooth Transition GARCH (STGARCH)** — González-Rivera (1998), Hagerud (1997). 允許 GARCH 參數漸進轉換（VIX 作為 transition variable）。K427 發現結構性斷裂，ST 可能比 abrupt switch 更合適。**進行中**
- [ ] K432: **Bayesian MCMC GARCH** — 用 Metropolis-Hastings 估計 GJR-GARCH 後驗分布，量化參數不確定性。比 MLE 點估計更穩健。**進行中**
- [ ] Bayesian Subset Selection for TARMA — Chen, Liu, Gerlach (2011) Computational Statistics, 26, 1-30. 擴展 SSVS 到 threshold + MA terms，16M+ 可能子集
- [ ] Threshold Variable Selection for Asymmetric SV — Chen, Liu, So (2013) Computational Statistics, 28, 2415-2447. Combined threshold variable Z_t = Σω_i Z_i，同時選 threshold 變數和模型結構。五個亞洲市場實證
- [ ] SSVS for Variance Equation — 將 SSVS 擴展到 variance equation（GARCH-X 的 variance side 加外生變數），目前 K433 只處理 mean equation
- [ ] Threshold GARCH with Bayesian Model Selection — 結合 2006+2013 方法：threshold GARCH + SSVS 同時選 regime 結構和變數子集

## 前沿文獻方向（2025-2026）

### 即刻可行動（不需新數據）
1. ★ ~~Window Size Sensitivity~~ → **K783 完成**：expanding window 以 QLIKE=0.529 勝 w=2000 的 0.560（DM=-3.23 Harvey PASS）。w=2000 不是最優。
   - [x] **K783b 完成**：最優 window 因資產而異。QQQ 偏好 504（DM=+3.59 PASS），GLD 偏好 3000，0050 偏好 1000，BTC 偏好 2000。**w=2000 仍是合理預設。**
   - [x] **K783c 完成**：regime-dependent。危機→w=2000，中波動→w=504，平靜→w=252。1/14 DM 通過 Harvey。w=504 是跨 regime 最佳折衷。
2. ★ ~~MF2-GARCH~~ → **K785 完成 NULL**：GJR baseline 仍勝（QLIKE 0.529），MF2-EWMA 0.533 (NS)，MF2-MEM 0.599（worse）。Expanding GJR 已隱式捕捉長期趨勢。
3. KAN-GARCH-MIDAS（結構化 NN 可能突破 ML ceiling）— J. Applied Economics 2025
4. VIX-Managed Portfolio 文獻引用整理 — Int. Rev. Financial Analysis 2024（支持 Paper 3）

### 需 5-min 數據（ETA 2026 Q2）
- [ ] HAR-PD (Path-Dependent) — arXiv:2503.00851
- [ ] Adaptive Multi-Factor HAR — FoFI 2026, Cinquetti et al.（287 個高頻因子）
- [ ] HAR + Wavelet Decomposition — ScienceDirect 2026
- [ ] HAR-GNN（Graph Neural Network）— ScienceDirect 2024
- [ ] Graph Signal Processing HAR — arXiv:2410.22706
- [ ] PatchTST-lite vs HAR-RV — MDPI 2025
- [ ] Neural Heteroscedasticity — Eng App AI 2025
- [ ] Intraday Commonality — JFE 2024

### 需 Options/Tick 數據（BLOCKED）
- [ ] Options-Driven Vol Forecasting — Quantitative Finance 2025
- [ ] Bespoke Realized Volatility — Patton & Zhang, J. Econometrics 2026（需 tick data）
- [ ] Vision Transformer for RV — arXiv:2511.03046（需 IV surface 圖像）

### ML-GARCH 混合
- [ ] GARCH-Informed NN (GINN) — arXiv:2410.00288
- [x] ★ ~~GARCH-GRU~~ → **K784 完成 NULL**：QLIKE 排 #1 但 vs GJR DM=-0.51 不顯著。ML 額外複雜度不帶來改善。
- [x] ~~HAR Directional Prediction~~ → **K787 完成**：67.9% 方向準確率(z=8.03)但無經濟價值（timing +33% vs B&H +58%）。VIX 對方向無用(49.6%)。
- [ ] **Probabilistic RV Quantile Forecasting** — arXiv:2508.15922（從 HAR/GARCH 點預測到條件分位數）
- [ ] Sentiment-Augmented GARCH-LSTM — Computational Economics 2025
- [ ] KAN for VIX Forecasting — Expert Systems with Applications 2025
- [ ] CNN-Transformer Hybrid — European J. Finance 2025
- [ ] GARCH-to-Neural — AAAI 2024
- [ ] ML Risk-Based Allocation — Scientific Reports 2025（LSTM + regime switching，Sharpe 1.38）

### Rough Volatility & Hurst
- [ ] ★ **Multivariate fBm for RV** — arXiv:2504.15985 (April 2025)。不同資產有不同 H，跨資產 mfBm 預測勝過單變量。即刻可做（不需日內數據）。
- [ ] ★ **Multivariate Rough Volatility Model** — arXiv:2412.14353 (Feb 2026)。多變量 fractional OU + GMM 估計。跨資產 rough vol 的正式框架。
- [ ] Time-Varying Hurst via EWMA — arXiv:2509.05820
- [ ] Adaptive Fractal Dynamics — Frontiers Applied Math 2025
- [ ] Non-Gaussian Rough Vol（α-stable increments）— arXiv:2507.15437

### Tail Risk & Conformal Prediction
- [ ] Regime-Weighted Conformal VaR (RWC) — arXiv:2602.03903 (2026)。控制非定態 portfolio VaR 超限率。regime-structured vol clustering。
- [ ] Conformal Predictive Portfolio Selection (CPPS) — arXiv:2410.16333。預測區間 → 選最佳投資組合。
- [ ] ★ **Proxy-Reliance Control in Conformal VaR** — arXiv:2603.22569 (2026)。校準 one-sided VaR 時控制 proxy 依賴。直接相關我們的 Patton (2011) proxy-robust 框架。
- [ ] **Online Conformal via Universal Portfolio** — arXiv:2602.03168 (2026)。在線 conformal prediction + portfolio theory 交叉。
- [ ] **KOWCPI (Kernel-Optimally-Weighted Conformal)** — arXiv:2405.16828。自適應權重 conformal prediction interval，適合波動率聚集。
- [ ] Risk Parity + Heavy-Tailed + Regime-Switching DCC — Paolella (2025, JTSA)

### 期貨避險方法論
- [ ] Quadratic Hedging under GARCH — Ma, J. Futures Markets 2026
- [ ] Copula-based GARCH Hedge — Hsu et al.
- [ ] Wild Bootstrap OHR — JRFM 2024
- [ ] Partial Cointegration Hedging — RQFA 2023
- [ ] Regime-Switching Correlation Hedging

### 其他
- [ ] Regime-aware In-Context Learning — arXiv:2603.10299（LLM vol forecasting）
- [ ] 「HAR ceiling」驗證 — Los Flamingos 2025
- [ ] Financial Innovation 2025 review — realized volatility forecasting 綜述
- [ ] RGARCH-CARR-SK（Realized GARCH + CARR + 高階動差）— 2025
- [ ] Multiplicative Volatility Factor (MVF) — ScienceDirect 2025, J. Econometrics
- [ ] VOLARE 平台（HAR/HAR-Q/MEM/AMEM 標準化比較框架）— arXiv:2602.19732
- [ ] Multi-Transformer Vol Forecast — Engineering App AI 2024

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

**Phase O~K(K507) 共 ~340 個實驗，詳見 `docs/research_archive/completed_phases_2026-03.md`。**
核心成果：GJR-X(VIX9D) best forecaster, MCS 5-model set, VIX sufficiency 32x, 50/50 irreducible, Prediction≠Application 4x。

### 最終工具指南（K426-K495, cross-OOS validated）
| 任務 | SPY | Other equity | Non-equity | Taiwan |
|------|-----|-------------|------------|--------|
| **Forecasting** | **GJR-X(VIX9D) ★★★** | GJR+HAR ensemble | GARCH(1,1) | GJR alone |
| **VaR** | **GJR-X(VIX)** | GJR-X(VIX) | GJR alone | GJR-SkewT |
| **VT Strategy** | 12/VIX | 12/VIX adapted | Asset-specific | 8.63/VIX |

**最終最佳模型**：GJR-GARCH-X(VIX9D) — Forecasting QLIKE -17.7%, VaR Trinity 3/3, delta CV=0.08 (ultra-stable)。日頻方向已完全飽和，下一突破需 5-min HAR-RV（ETA 2026-04-11）。

## 重大研究結論更新（2026-03-29 K687/K697/K700/K701）

**VT 策略是 drawdown insurance，不是 alpha generator。**
- K687：正確 lag 後，沒有 VT 策略在 Sharpe 上打敗 BH 50/50（0.545）
- K697：VIX 預測 vol（corr 0.57）但不預測 direction（corr 0.04）——daily alpha 理論不可能
- K701：weekly/monthly 也一樣（direction corr 全部<0.04）
- K688：VT 在 CRRA utility γ≥5 時勝出——drawdown protection 對風險厭惡投資人有價值
- K693：歷史 paper_trading 9935 筆修正 same-day→next-day return
- K700：Codex 審查防止 3 個 false breakthrough（37.5% false positive rate without review）

## Next Session Priorities（2026-03-31 起）

### P0: 時間敏感

| 項目 | 說明 | 截止日 |
|------|------|--------|
| **NFP 04/03 事後文章** | 非農數據發布後 1 天內發解讀文（K661 數據已備） | 04/04 |
| **HAR-RV 正式實驗** | 5-min 數據 ETA 04/11 達 60 天門檻 | 04/11 |
| **TSMC 營收 04/10** | 預告+解讀文 | 04/08, 04/11 |
| **TSMC 法說 04/16** | 預告+解讀文 | 04/14, 04/17 |

### P1: 高價值

**論文修正：**
- [ ] **Leverage-Direction**（K628 已瘦身 64→52p）：加入「VT is insurance」框架
- [ ] **Taiwan VT**：K636 修正 amplification（gamma vs vol level）、TX cost 已修正

**平台經營方向（基於 analytics：192 views, 3 users, 10 reactions）：**
- [x] **SEO 完成**：Google Search Console 驗證 + sitemap + 6 頁 metadata + FAQ/Article/Breadcrumb schema + admin noindex + /portfolio 公開路由 ✅ 2026-03-31
- [x] **分享按鈕**：LINE/Facebook/X/Twitter + 複製連結 ✅ 2026-03-31
- [x] **首頁預設「一般讀者」tab** ✅ 2026-03-31
- [ ] **加強入門內容**：「從零開始」是最熱門文章之一，應建立 /guide 頁面
- [ ] **減少學術文章比例，增加實務操作指南**：收藏(7)>按讚(3) = 讀者當工具書用
- [x] K705 GAP-03：StrategySelector CAGR 降級，突出 Sharpe/MDD ✅ 2026-03-31
- [x] **Umami Analytics** 上線（cloud.umami.is，免費方案） ✅ 2026-03-31
- [ ] **Umami API 自動化**：寫 scripts/analytics.py 包裝 Umami REST API，方便終端查看訪客數據（**2026-04-04 週五檢視數據後決定**）

### P2: 研究新方向

**高優先（有明確下一步）：**
- [ ] **HAR-RV 正式實驗**：K744 驗證數據 94% clean，K745 pipeline 通過。SPY 51 天（ETA 60 天 ~04/07），需 100+ OOS days ~05 月。到時重跑 HAR-RV vs HAR-ABS vs GJR 的完整比較
- [ ] **Paper 6: Crypto Fear Channel**：K746b 確認 BTC vol asymmetrically Granger-causes VIX。結合 coupling 增加 + tail dependence，可寫成「加密貨幣市場對傳統金融的波動率溢出」論文
- [ ] **Paper 5 正式撰寫**：草稿 31p 已完成。Codex 建議 J. Forecasting。需要：統一 pipeline（不只 VIX，含 HAR-RV/GARCH benchmark）、多重檢定控制、replication package

**中優先（新研究主題）：**
- [ ] **Robust VT 設計**：K743 的 floor(30%)/cap(90%) + EWMA 平滑 + 週頻 rebalance 組合。修正 Codex 找到的 bug 後重跑
- [ ] **VIX Regime 轉換預測**：K752 發現不同 era 的 VIX R² 差異大（0.24-0.64）。能否預測 VIX regime 何時轉換？
- [ ] **Drawdown Recovery 修正版**：K735 被 Codex 推翻（fake OOS + timing misalign）。修正方法論後重做
- [ ] **跨國 VIX sufficiency**：K752 證明 US 33 年成立。在其他市場（VSTOXX、VNKY、VIXTWN proxy）驗證？
- [ ] **Alternative data**：K750 Google Trends 是反應式。嘗試 Reddit/Twitter 情緒或 options flow
- [ ] **Intraday alpha**：5-min 數據就緒後，測試日內 VIX-equity lead-lag（K751 overnight 有 +0.45% R²）

**低優先（長期探索）：**
- [ ] **VT 與 ESG 整合**：ESG 評分高的公司是否有不同的 gamma？
- [ ] **Agent-Based Model 正式版**：K742 用簡化 Kyle's lambda。正式 ABM 可模擬異質投資人
- [ ] **因果推論**：用 DiD/RDD 分析 Fed 升息決議對 VIX regime 的因果影響
- [ ] **Climate vol**：極端天氣事件頻率增加是否改變 vol 動態？

### P3: 長期待辦

**研究：**
- [ ] Rough Volatility multivariate（需理論準備）
- [ ] Decision-focused policy learning（contextual bandit）
- [ ] 除權息季節研究（06 月）

**平台：**
- [ ] Feature gating（V0.7）
- [ ] API rate limiting（V0.9）
- [ ] Email/LINE 訂閱（W3.1）

## 重要事件日曆（當月+下月，每月更新覆蓋）
**最後更新：2026-03-26。下次更新：2026-04-01。**

### 美股事件
| 日期 | 事件 | 研究安排 | 文章安排 |
|------|------|---------|---------|
| **04/03 (五)** | **NFP 非農就業** | 就業數據與波動率關係 | 「非農報告前後該怎麼操作？」(general) |
| **04/09 (四)** | **GDP 第三估 + Personal Income** | GDP surprise 對 vol 影響 | 「GDP 數據出爐那天該注意什麼」(general) |
| **04/10 (五)** | **CPI 通膨數據** | CPI surprise vs option-implied（Codex event-surprise 建議） | 「通膨數據——歷史告訴我們市場怎麼反應」(general) |
| **04/28-29** | **FOMC 利率決議 + Powell 記者會** | FOMC 對 VIX/vol regime 影響 | 「Fed 決策對投資組合意味什麼」(general) |

### 台股事件
| 日期 | 事件 | 研究安排 | 文章安排 |
|------|------|---------|---------|
| **04/10 (五)** | **TSMC 3月營收公告**（每月10日前） | TSMC 營收 surprise 對 0050 vol | 「台積電營收公告前後台股怎麼走？」(general) |
| **04/16 (四)** | **TSMC Q1 法說會** | TSMC earnings 對 0050.TW vol | 「台積電法說前後台股波動」(general+research) |
| **04/17 (五)** | **中經院台灣經濟預測** | 經濟預測修正對台股 sentiment | 搭配法說會文章 |
| **06月~** | **台股除權息旺季開始** | 除權息對 vol/return 的系統性影響研究 | 「除權息季節該參加還是避開？」系列文章 |

### 事件執行原則
- 事件前 2-3 天發佈「預告」文章（一般讀者 + 研究各 1 篇）
- 事件後 1 天發佈「解讀」文章
- 研究實驗在事件前 1 週完成，結果寫入文章
- 用 CronCreate 設定 one-shot reminder 確保不遺漏
- **每月 1 日更新此日曆，覆蓋而非累積**

## 待深入研究主題

### 除權息研究方向（用戶指定）
- [ ] 除權息前後波動率是否系統性改變？（類似 K498 earnings 但用台股個股/ETF）
- [ ] 高股息 ETF（0056/00878/00919）除息日前後的價格行為
- [ ] 「填息率」與波動率的關係——填息快的股票 vol 是否較低？
- [ ] 除息日對 0050.TW 的 vol 影響（0050 成分股集中除息期間）

### SEC Filings 研究與文章方向（用戶提出）
美股的 10-K（年報）、10-Q（季報）、8-K（重大事件即時揭露）是重要的資訊來源和內容題材：

*文字探勘 (Text Mining)*
- [ ] SEC filing 語調分析：用 Loughran-McDonald 金融情緒詞典對 10-K/10-Q MD&A 段落做正負情緒打分，看情緒變化是否預測後續 vol/return
- [ ] 10-K 可讀性（Fog Index / 文件長度）與後續 vol 的關係
- [ ] 8-K filing 文字 surprise：用 TF-IDF 或 embedding 計算 8-K 與前次 filing 的文字差異度
- [ ] Risk factor section 的年度變化：新增風險因子 vs 刪除風險因子 → 對 vol 的預測力

*情緒 (Sentiment)*
- [ ] Management tone（管理層語調）：法說會逐字稿 vs 10-K 書面語調的差異
- [ ] Forward-looking statements 的情緒：MD&A 中「expect」「believe」「risk」的頻率變化趨勢
- [ ] 跨公司情緒傳染：SPY 前 10 大成分股的 filing sentiment 彙總 → 是否預測 index vol？

*財務 (Financial)*
- [ ] 10-K/10-Q filing 前後 SPY vol 是否有系統性模式？
- [ ] 8-K filing（unexpected events）對個股和 index vol 的 surprise 效果
- [ ] Accruals quality（應計品質）vs 後續 vol：低品質 earnings → 高未來 vol？
- [ ] 財務比率的年度變化（debt/equity, current ratio）vs 後續 vol

*管理 (Governance & Management)*
- [ ] CEO/CFO turnover 的 8-K 揭露 → 對 vol 的即時和延遲影響
- [ ] 審計意見變更（going concern, material weakness）→ vol spike 預測
- [ ] 內部人交易揭露（Form 4）與後續 vol/return 的關係
- [ ] TSMC 20-F（外國公司年報）filing 對 TSM/0050.TW 的影響

*台灣重大訊息（MOPS 公開資訊觀測站）*
- [ ] MOPS 重大訊息公告：台灣上市櫃公司的即時揭露，包括營收公告、董事會決議、私募、合併、訴訟等
- [ ] 台股重大訊息公告頻率/內容 vs 後續 vol/return
- [ ] 0050 成分股重大訊息的彙總 sentiment → 是否預測 0050 vol？
- [ ] 法說會逐字稿語調分析

*文章方向（一般讀者）：*
- [ ] 「10-K、10-Q、8-K 是什麼？散戶為什麼該關心美股年報」(general 教育文)
- [ ] 「財報季前後的波動規律——數據告訴你什麼時候最危險」(general)
- [ ] 「如何從 SEC filing 讀出公司的真實風險」(general 教學文)
- [ ] 「CEO 換人了——股價會怎樣？8-K 告訴你的事」(general)
- [ ] 「年報越厚越危險？文件可讀性與股價波動的關係」(general)

### 經濟政治不確定性 & 搜尋趨勢（用戶提出，持續議題）
過去研究：G14 Google Trends (partial r sig but 反轉)、J3 (IS r=0.634 but VT null)、K446 GPR (reversed causality)、K473 (OOS null)。
這些主題作為 vol research 已被 VIX sufficiency 限制，但作為讀者內容和市場解讀仍然重要：

*定期文章（每月至少 1 篇）：*
- [ ] 「本月 Google 搜尋趨勢告訴你什麼？」
- [ ] 「經濟政策不確定性指數（EPU）最新動態」
- [ ] 「地緣政治風險現在有多高？」
- [ ] 「恐懼與貪婪指數解讀」

*研究更新（當重大事件發生時）：*
- [ ] 特定事件的 Google Trends spike → VIX 反應速度和幅度分析（event study）
- [ ] EPU/GPR 在 tariff/sanction/election 期間的特殊行為
- [ ] 台灣選舉/兩岸關係事件 → VIXTWN/0050 vol 反應（需更長 VIXTWN 數據）

### 成交量作為波動率預測因子（用戶提出）
**文獻基礎**：Lamoureux & Lastrapes (1990), Clark (1973) MDH, Tauchen & Pitts (1983)

**過去研究**：K113 null, K135 OOS null, K136 BTC 有效, K418 Taiwan null, K527 OOS 失敗（MDH = contemporaneous）

#### ⚠️ K519 上架暫停（K521 data alignment bug）
K519-K521 + K527 完成結果：見 archive。
**結論**：上架暫停——需要找到在 5AM-9AM 之間可執行的交易機制才能重啟。

#### 台指期貨 Overnight Gap Strategy（K515 延伸，高優先）
- [ ] K515 發現 overnight gap alpha 真實（SPY-conditioned 10.73bp/day, t=4.06）但 ETF TX 18.55bp 致命（K625 更正）
- [ ] **台指期貨（TX futures）TX cost 只有 ~2-3bp** → 可能可行！
- [ ] 需要：台指期貨歷史日頻數據（TAIFEX 或 yfinance TWF=F?）
- [ ] 測試：buy TX futures at close, sell at open, SPY-conditioned
- [ ] 如果 Net Sharpe > 0.5 + cross-OOS 4/5 → 第一個可能上架的新策略

## Codex 論文審查記錄

### Codex 第6次審查：Taiwan VT 論文（2026-03-27）
1. ⚠️ 4.6x amplification 用 10 個股票樣本太小，機制解釋過強
2. ⚠️ Opening auction "remarkably efficient" 語氣太強
3. ⚠️ TZ alpha 用不可交易的 c2c headline，o2o Sharpe 低於 Harvey
4. ⚠️ Table 3 策略比較混用不同期間——not apples-to-apples
5. ⚠️ 29 switches/year × 0.1855%/switch — 需修正論文中的 0.3% 引用
6. 語氣過於 promotional → 需 tone down

### Codex 第6次審查：Leverage-Direction 論文（2026-03-27）
1. ⚠️ TZ arbitrage 在 intro 說 "tradable alpha" Sharpe 1.61，但 appendix 承認 78% 不可捕捉
2. ⚠️ gamma>0.10 model selection rule 看似 post-hoc（12 cases 太少）
3. ⚠️ Proposition 1 的 rank correlation 接近 mechanical
4. 🔴 日期不一致：data section 說 2017-2025 但引用 2026-03 驗證
5. 🔴 gamma window 先說 "non-overlapping" 後說 "504-day stepped by 63 days"（矛盾）
6. 裁判最可能批評：heavily searched design overstates OOS results

### Codex 審查：VT-Trend-Following 論文（2026-03-27）
1. ⚠️ "almost entirely independent of trend following" 語氣過強
2. ⚠️ gamma "mechanical explanation" 過於因果（N=22）
3. ⚠️ "irreducible" / "VT≠TF" 的 trend strategy 比較缺表格
4. 🔴 L164 "mechanically zero" vs Table 1 報非零 Δalpha（矛盾）
5. 🔴 Table 3 M5 描述含 MOM+BAB 但 β_MOM 空白
6. 🔴 L352 說 EWT 改善但表格是 EWJ（text/table mismatch）

#### MEM 模型文獻（2026-03-31 搜尋，配合用戶提出方向）
- [ ] **基礎 MEM**：Engle & Gallo (2006) 原始 MEM。非負值序列（RV, volume）的條件期望×隨機擾動。[提出: 用戶 + 文獻]
- [ ] **AMEM（Asymmetric MEM）**：加入不對稱效果（正負衝擊不同影響）。VOLARE 平台已實作 [提出: 文獻]
- [ ] **DMEM（Doubly MEM）**：長短期雙成分（Spline-MEM, Component-MEM, MEM-MIDAS）。ScienceDirect 2023 [提出: 文獻]
- [ ] **Vector MEM**：多變量 MEM（Cipollini, Engle & Gallo）。跨資產 vol 聯合建模 [提出: 文獻]
- [ ] **AMEM-MV**：分解 RV 為 base + meaningful volatility events 成分。2025 [提出: 文獻]

#### Gemini 建議（2026-03-31）[提出: Gemini 2.5 Pro]
- [ ] **Wasserstein Volatility Drift (WVD)**：用 2-Wasserstein 距離測量日內 RV 分布漂移。假說：WVD 領先 VIX regime shift 1-3 天。需 5-min 數據（ETA 04/11）[提出: Gemini]
- [ ] **Gamma-Trap 零售回饋迴路**：0DTE option flow → MM hedging → vol pin/explosion。假說：NRGE 顯著負值時 realized-implied gap 縮小 >20%。需 option flow 數據（BLOCKED）[提出: Gemini]
- [ ] **Transfer Entropy VT Budgeting (TE-VT)**：用 Fed liquidity → VIX 的 transfer entropy 動態調整 VT 保險。假說：TE-VT Sortino +15% vs static γ=4.5。FRED 數據可得 [提出: Gemini]

#### 用戶提出方向（2026-03-31 追加）
- [ ] **K770 修正版：統一 forecast target**：MEM/HAR 預測 |r| 但 GARCH 預測 σ。需統一到同一 target（close-to-close RV = intraday + overnight）。Hansen & Lunde (2005) 提出最優加權方案。[提出: 用戶]
- [ ] **Overnight volatility component**：隔夜波動約佔全日 20%（Hansen & Lunde 2005）。加入隔夜 r² 到 HAR/MEM 作為額外 regressor。文獻：ScienceDirect 2014 "Overnight information flow and RV forecasting"。[提出: 用戶]

### Hansen & Lunde (2005) Gold Standard 比較（等 5-min 數據就緒）
- [ ] **K779（ETA ~04/07）**：用 Hansen & Lunde 最優加權 RV_total = w₁×RV_intraday + w₂×r²_overnight 作為「真實 σ²」proxy，所有模型（GARCH/MEM/HAR）都跟 RV_total 比。這是學術最高標準。需 5-min 數據 ≥60 天。[提出: 用戶]
