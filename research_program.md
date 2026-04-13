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
- **★★★ Cornish-Fisher Rolling VaR (K1034)**：CF-Rolling 6/6 Trinity PASS（Normal 0/6, Student-t 1/6）。用 rolling 偏態/峰態修正 quantile，無需假設特定分配。**目前最佳 VaR 方法**
- **★★ EVT-GPD VaR (K1035)**：GJR-EVT rescues GJR（0/4→4/4 Trinity PASS），但 A4f 本身已 4/4 不需 EVT。EVT 是 weak model 的補救工具，非 strong model 的加分項
- **VaR 方法排名（K1034+K1035 綜合）**：CF-Rolling ≥ EVT > Student-t >> Normal
- **★★ Multi-Horizon VaR (K1039)**：A4f+CF-Rolling h=1,5 均 100% Trinity PASS。h=10 降為 75%（小樣本）。**√h scaling = proper h-step**（pass rate 相同）→ 實務不需 h-step 公式。Normal 隨 horizon 增加改善（CLT）
- **Copula-based VaR**（多資產聯合尾部風險）
- Monte Carlo VaR（GARCH 路徑模擬）
- [x] **★★ A4f + CF-Rolling 結合 (K1036)**：2×3 factorial 完成。CF-Rolling 是 VaR 王者——GJR+CF = A4f+CF = 6/6 Trinity PASS。A4f 對 Student-t 有巨大改善（1/6→5/6），但 CF-Rolling 使模型選擇對 VaR 無關。A4f 的真正價值在 QLIKE 預測精度

### 面向 C: 投資策略
- Volatility Targeting（12/VIX, EWMA VT, Hybrid VT）
- Multi-asset portfolio（40/30/30, Conditional TLT）
- 報酬預測（Excess Fear Signal [Gemini], VRP timing）
- DCA + VT：**K59 DCA 用 24/VIX**，**K70 DCA 50/50 幾乎不需 VT（防禦階層）**
- Covered Call：**K72 XYLD + VT 不改善 50/50**
- **VaR-targeting**（K44: rescaled σ-targeting，非新 alpha 但提供直觀風險選擇框架）
- **VT alpha = trend following**（K46→K53→K79: r=0.564, N=22, threshold-robust）⚠️ **K1044 修正**：13 資產 panel ρ=-0.209 (NS)，gamma-VT alpha 相關不可重現。Gamma 決定 VT 機制但不決定效果
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
- [x] Gemini 審查 → gemini_review_v1.md（3 weaknesses: TX tax、linear scaling、TSMC endogeneity）
- [ ] `/latex-academic-reviewer` 全面審查
- [ ] 修正 Gemini 指出的 3 弱點

**第三篇：Is Volatility Targeting Just Trend Following?**
- `paper/vt-trend-following/main.tex`（29 頁）
- 目標：Journal of Portfolio Management 或 Financial Analysts Journal
- 核心貢獻：分解 VT 的 alpha 來源（K46→K53→K79: r=0.564, VT alpha = trend following）
- [x] `/latex-academic-reviewer` 全面審查 → review_v2.tex（5H/12M/6L）
  - HIGH: 樣本期間不一致、BAB proxy（SPLV→AQR）、MDD 只有 5 美股、1.4% 數字不可驗證、需引用 K687/K697/K688
  - K687 分析：**不矛盾**——VT 打敗 BH(SPY) 但打不過 BH(50/50)，支持 insurance 論述
- [ ] 修正 review_v2 的 5 HIGH
- [ ] Gemini 審查
- [ ] `/citation-verifier` 引用驗證

**未來可能的第四篇：VIX Sufficient Statistic**
- 23+ 個指標全被 VIX 吸收的 comprehensive study
- 適合 Journal of Financial Economics 或 Review of Financial Studies
- 需要更多跨市場驗證（目前只有 US + Taiwan）

**第九篇：Multiplicative GARCH-X with VIX**
- `paper/garch-x-vix/main.tex`（31 頁，3 contributions）
- 目標：Journal of Empirical Finance 或 Journal of Forecasting
- 狀態：✅ 初稿完成（2026-04-10）
- 核心實驗：K988/K988b（17 規格比較）、K994（跨資產）、K995（VaR/ES）、K997（本地 fear index）、K998（VRP 預測 null）
- 核心發現：A4f（VIX², free ω）DM t=4.48 vs GJR，勝所有 GARCH-MIDAS
- [x] 初稿撰寫（31 頁，24 references）
- [ ] `/latex-academic-reviewer` 全面審查
- [ ] `/citation-verifier` 引用驗證
- [ ] Codex adversarial review
- [ ] 補充 robustness（refit frequency sensitivity、sub-period analysis）
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
- [ ] 台灣 5-min 數據 HAR-RV（0050.TW 47 天，ETA 2026 Q2）
- [ ] **金融股早期預警系統**：K757 發現 Fubon→TSMC Granger (F=6.11)。可建立金融股壓力指標作為 TSMC vol 早期預警
- [x] ~~K1059: TSMC → 0050.TW ETF event study~~ — NULL at T+0 but A4f advantage concentrated in event window (DM t=2.50)
- [x] ~~K1060: Individual Taiwan stock EAV~~ — **★★ 重大發現**：T+0 ratio=0.936 (NULL) but T+1 ratio=1.466 (p=0.034). Taiwan 盤後公告 → vol shock 在 T+1。解開 K1059 謎題。
- [ ] **K1061**: Extend to full TWSE 50 constituents (N≥50 for binomial power)
- [ ] **K1062**: Re-run K1059 on 0050.TW with **T+1 event window** to confirm ETF-level EAV
- [ ] **K1063**: Scrape actual announcement timestamps (盤中 vs 盤後) for cleaner T+0/T+1 classification
- [ ] **K1064**: Test whether `TW_EAV_factor` (sector-conditional, T+1) can serve as exogenous regressor in A4f family (K1058 NS may be due to un-conditioned EAV)
- [ ] ★ **台股財報公告日 × 波動率研究** [提出: 用戶, 2026-04-12]（原始研究方向，上述 K1059-K1064 為子實驗）：
  - **數據**：`財報公告日.txt`（Big5 編碼），2,411 家公司、158,674 筆、1986-2025、97% 有公告日。TSMC 96 筆。欄位：公司代碼/簡稱/財報期間(YYYYMM)/公告日(YYYY/MM/DD)
  - **方向 1（個股層級）**：Earnings Announcement Volatility (EAV) — 公告日前後 [-5,+5] 天的異常波動率，分析 early/on-time/late filer 的差異
  - **方向 2（TSMC → 0050.TW）**：TSMC 佔 0050.TW 50% 權重。TSMC 財報公告是否驅動 0050.TW 異常波動？公告日 VT 策略應否調整？
  - **方向 3（聚集效應）**：多家公司同日公告時（如財報季密集期），0050.TW/TAIEX 波動率是否顯著上升？與 K1050（SPY 盈餘季均勻改善）對照
  - **方向 4（A4f 台灣擴展）**：結合 K1058（A4f 0050.TW DM NS）——A4f 在台股財報日附近是否表現更好/更差？VIX 是否捕捉台股 earnings uncertainty？
  - **方向 5（學術貢獻）**：台股 40 年 earnings announcement 數據 + VT 策略 = 獨特切入角度，可能成為 Paper 2（Taiwan VT）的重要補充
  - **注意**：需要 TAIEX/0050.TW 個股日頻價格配合（yfinance 可取 2003 年後）

**論文**：第二篇 `paper/taiwan-vt/main.tex`（34 頁）涵蓋台灣 VT + TZ 資訊傳遞

## Codex/Gemini/用戶建議（統一區）

### Codex 第 7 次建議：從預測轉向策略（2026-03-27）[提出: Codex GPT-5.4]
**核心洞見**：瓶頸不是預測 RV，而是判斷何時 forecast 值得交易。
- [ ] **Conditional Dispersion Trade**：預測 correlation risk premium mispricing → index vs sector options。需 sector ETF options data。
（已完成項目見 archive：K730 Cross-Asset Vol Momentum, K763 Regime-Switched Carry Filter, K760 Alt Risk Premia Rotation, K762 Action-First ML）

### Codex 第 8 次建議（2026-03-31）[提出: Codex GPT-5.4]
**5/5 全 NULL**。詳見 `docs/research_archive/completed_session_2026-04-01.md`。
核心結論：VIX-based 風險管理工具無法改善 50/50 baseline。連續調整 >> binary 切換。

### Codex 第 5 次建議（2026-03-26）[提出: Codex]
- [x] ~~Decision-focused policy learning~~ → **K798 NULL**。DM 全 NS。12/VIX irreducible #7。
- [x] ~~Two-clock decomposition~~ → **K791 NULL**。隔夜/盤中分解不改善預測。
- [ ] **Options surface state variables**：⚠️ BLOCKED: 需 options 歷史數據
- [ ] **Dispersion / correlation-regime trading**：sector dispersion, correlation breakdown trades
- [x] ~~Event-surprise strategies~~ → **K801 NULL**。|ΔVIX|>2σ 多餘，12/VIX 自帶 shock guard。#8 irreducible。

Codex 優先排序：(1) Decision-focused policy (2) Overnight/intraday decomposition (3) Dispersion trading

### Gemini 第 2 次建議（2026-03-31，行為金融 + 方法論 + 實務工具）[提出: Gemini]
- [ ] **Retail Reflexivity & Gamma-Driven Skew**：0DTE 散戶 flow 導致 delta-hedging 連鎖反應，可能打破 VIX sufficiency。量化 "Volatility Gap"（VIX-implied vs flow-induced realized move）。⚠️ BLOCKED: 需 order flow 數據
- [ ] **Path Signatures for Rough Volatility**：用 rough path theory 的 signature transform 編碼日內價格路徑的幾何特性，捕捉 HAR 遺漏的路徑依賴性。需 5-min 數據（ETA 04/11）
- [x] ~~Convexity-Adjusted Insurance Premium Tool~~ → **K811 完成 混合結果**（⚠️ Codex 2 HIGH: VVIX pre-2012 + cost calc mislabel）。VoV-cond 方向可信（減少保險費、smooth 優於 binary），但 40% 數字需 K811v2 修正。

### Gemini 第 1 次建議（2026-03-26，台灣特色 + 免費數據）[提出: Gemini]
- [x] ~~Taiwan Price Limit Latent Volatility~~ → **K790v2 完成 NULL**：>5% 天數僅 0.9%，GJR asymmetry 已捕捉。DM 全 NS。
- [x] ~~FRED STLFSI4 Macro Stress Regime~~ → **K795 完成 NULL**（⚠️ Codex 2 HIGH：pre-2004 GLD + DM 實作錯誤，數字不可靠但方向正確）。Binary Sharpe 0.466 vs 0.313 但 DM 未通過。VIX sufficiency #24（方向確認，精確統計待 K795v2）。
- [x] ~~VIX→Taiwan Vol Spillover Strategy~~ → **K817 完成 NULL**。Spillover 存在（r=0.376）但 OTC return 不可交易（77-93% alpha 在隔夜 gap）。DM 全 NS。8.63/VIX 仍最佳。
- [ ] **TXO Put-Call Ratio Mean-Reversion**：台指選擇權 P/C ratio 作為散戶恐慌指標，極端值做反向操作。Data: TAIFEX 網站
- [x] ~~EWT vs 0050.TW Vol Arbitrage Spread~~ → **K792 完成**：Granger YES (F=28.4) 但方向反（高 ratio → vol 下降）。Trading 虧損。Mean reversion 陷阱。

### 用戶提出方向
- [x] ~~什麼是好的交易策略？~~ → **K793 完成**：8 維度評估 6 策略。BH 50/50 #1 (75.4), Risk Parity #2 (73.7), Piecewise #3 (54.0，唯一正 stress)。單一 Sharpe 遺漏大量 tradeoffs。
- [x] **HAR-RV with 5-day RV** [提出: 用戶, 2026-03-31] → **K782 完成**：GJR-GARCH multi-step 在 5d/22d/66d 全勝 HAR。日頻 squared returns 做的 RV 不足以讓 HAR 發揮優勢——需等 5-min 數據。
- [x] ~~MEM（Multiplicative Error Model）~~ [提出: 用戶] → **K805 完成**：AMEM-r² 數值最佳（QLIKE 1.4689 vs GJR 1.4824）但 DM=-2.19 未通過 Harvey t>3.0。非對稱性（leverage）比模型類別更重要。MEM 不提供超過 GJR 的統計顯著改善。
- [x] ~~K501/K818: SSVS for Return Prediction~~ [提出: 用戶] → **K818 完成 NULL for SPY**。OOS R²=-1.47%（EMH barrier）。SSVS 選出 HYG(0.93)+VIX_change(0.78)。台灣 hit 62.1% 但 c2c gap artifact。SSVS 更適合 vol 非 return。
- [ ] Return prediction → trading strategy pipeline：如果方向準確度 > 55% → 可做 long/short 策略
- [ ] 跨資產 return prediction：SPY、0050.TW、QQQ
- [x] ~~K502/K812v2: US→Taiwan Lead-Lag Strategy~~ [提出: 用戶] → **K812v2 完成 乾淨 NULL**。OtC direction accuracy 50.2%（硬幣），lead-lag beta t=-0.25 (NS)。C2C Sharpe 3.51 → OtC -0.17（100% 信號在隔夜 gap）。方向正式關閉。
- [x] ~~K503/K810: VIX Mean-Reversion Strategy~~ [提出: 用戶] → **K810 完成 NULL**。12/VIX 本身就是 MR 交易。顯式 MR 策略增加 vol 和 MDD，得不償失。VIX spike 93.5% 回復但短期 NS。50/50 不可動搖 #10。
- 策略上架前必須：Cross-OOS ≥ 5 periods、3 年回測、Net Sharpe (after TX) > 0
- **不要輕易上架**——交易策略必須多次確認（cross-OOS + out-of-sample + sensitivity），避免上架後發現是錯誤

### Bayesian Subset Selection 方法論（用戶指定，2026-03-26）
- [ ] K433: **Bayesian SSVS for ARX-GARCH** — So, Chen, Liu (2006) JRSS-C, 55(2), 201-224. Latent binary indicator δ_i + MCMC 從 2^(p+q) 子集空間搜索最優外生變數組合。比 K113 逐一測試更有力。**進行中**
- [x] ~~K431/K813: Smooth Transition GARCH~~ → **K813 完成 NS**。In-sample LR=252 強烈顯著但 OOS DM=-0.11 NS。11 參數不優於 5 參數 GJR。結構發現：低 VIX 高 leverage(0.50)/低 persistence(0.39)，高 VIX 相反。QLIKE ceiling 持續。
- [x] ~~K432/K814: Bayesian MCMC GARCH~~ → **K814 完成**（⚠️ Codex 3 HIGH：P(γ>0) 是先驗 tautology、OOS h[0] leak、ESS/Geweke 錯誤）。框架有價值但數字不可靠。需 K814v2 修正 prior + 初始化 + 診斷。
- [ ] Bayesian Subset Selection for TARMA — Chen, Liu, Gerlach (2011) Computational Statistics, 26, 1-30. 擴展 SSVS 到 threshold + MA terms，16M+ 可能子集
- [ ] Threshold Variable Selection for Asymmetric SV — Chen, Liu, So (2013) Computational Statistics, 28, 2415-2447. Combined threshold variable Z_t = Σω_i Z_i，同時選 threshold 變數和模型結構。五個亞洲市場實證
- [x] ~~SSVS for Variance Equation~~ → **K821 完成 NULL**。0/8 外生變數 PIP>0.5。GJR variance equation 自足。VIX_level PIP=0.039。與 K484 internal（4/5 PIP=1.0）形成鮮明對比。
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
- [x] ~~GARCH-Informed NN (GINN)~~ → **K816v2 完成 NULL**。修正 GJR state propagation 後 DM=2.96→0.64（完全 NS）。GJR baseline 改善 8.56%，DM 是 artifact。**ML ceiling 第 6 次確認**。
- [x] ★ ~~GARCH-GRU~~ → **K784 完成 NULL**：QLIKE 排 #1 但 vs GJR DM=-0.51 不顯著。ML 額外複雜度不帶來改善。
- [x] ~~HAR Directional Prediction~~ → **K787 完成**：67.9% 方向準確率(z=8.03)但無經濟價值（timing +33% vs B&H +58%）。VIX 對方向無用(49.6%)。
- [ ] **Probabilistic RV Quantile Forecasting** — arXiv:2508.15922（從 HAR/GARCH 點預測到條件分位數）
- [ ] Sentiment-Augmented GARCH-LSTM — Computational Economics 2025
- [ ] KAN for VIX Forecasting — Expert Systems with Applications 2025
- [ ] CNN-Transformer Hybrid — European J. Finance 2025
- [ ] GARCH-to-Neural — AAAI 2024
- [ ] ML Risk-Based Allocation — Scientific Reports 2025（LSTM + regime switching，Sharpe 1.38）

### Rough Volatility & Hurst
- [x] ~~Multivariate fBm for RV~~ → **K806 完成 NULL**（⚠️ Codex 1 HIGH: 0050.TW 未清洗，跨資產 H 不可信；SPY 自身結果可信）。自身 H(t) 改善 NS (DM=-0.09)。5 資產全 rough (H<<0.5)。日頻 variogram 不夠精確。
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

### 新發現（2026-04-01 文獻搜尋）
- [ ] **Transfer Learning for New Issues Vol** — arXiv:2503.12648 (March 2025)。多源遷移學習預測數據稀少資產（新 IPO/分割股）的波動率。實務導向工具。

### Score-Driven (GAS) Models
- [x] ~~GAS-t vs GARCH on equity~~ → **K1038/K437 完成 NULL**。4 資產全 NS（SPY DM t=-0.99, QQQ t=-0.30）。Score-driven robustification 不改善 QLIKE。但 VaR violation rate 稍低（內建 Student-t）。結論：US equity 上 downweighting 大 shock 反而失資訊
- [ ] **K1129 (NEW 2026-04-13, user 提)**: 測 commodity/electricity markets 上 GAS-t 是否真有優勢（Creal-Koopman-Lucas 文獻主張）。USO/GLD/UNG/BTC × GJR baseline。equity null ≠ commodity null，需獨立驗證

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
| **VaR** | **GJR + Student-t ★★★** | GJR + Student-t | GJR + Student-t | GJR + Student-t |
| **VT Strategy** | 12/VIX（#9 irreducible） | 12/VIX adapted | Asset-specific | 8.63/VIX |

**★★★ K799-K804 最終結論（2026-04-01）：**
- **預測選模型**：GJR-GARCH（QLIKE #1，DM vs GARCH t=-3.25 Harvey PASS）
- **風險管理選分配**：Student-t/Skewed-t（VaR Trinity PASS，df=5-8 for equity）
- **兩個維度獨立選擇** — 預測精度和風險管理是正交問題
- K804 跨資產驗證：equity/commodity 3/4 PASS，BTC 例外（右偏需不同分配）
- K800 conformal 是 artifact（Codex 抓到），K802 分配修正才是正解
- K799：六層評估發現 GJR QLIKE #1 但 VaR Normal FAIL（1.79%）。MCS 含全部 5 模型。
- K800：Conformal heuristic 看似修復（0.80%）→ K800v2 推翻（artifact，Codex 抓到）
- **K802：正確解法 = GJR + Skewed-t/Student-t 分配**。QLIKE 不變 + VaR 1.20% Trinity PASS。
- **結論**：預測選模型（GJR），風險管理選分配（Skewed-t）。兩個維度獨立。
- 待驗證：跨資產 + 整合進 Paper 1/5

**K801**：Event-Surprise VIX Shock Guard — NULL（12/VIX 本身即 shock-guard）

## 重大研究結論（持續更新）

### 1. VT 策略本質 — drawdown insurance 不是 alpha generator（2026-03-29 K687/K697/K700/K701）
- K687：正確 lag 後，沒有 VT 策略在 Sharpe 上打敗 BH 50/50（0.545）
- K697：VIX 預測 vol（corr 0.57）但不預測 direction（corr 0.04）——daily alpha 理論不可能
- K701：weekly/monthly 也一樣（direction corr 全部<0.04）
- K688：VT 在 CRRA utility γ≥5 時勝出——drawdown protection 對風險厭惡投資人有價值
- K693：歷史 paper_trading 9935 筆修正 same-day→next-day return
- K700：Codex 審查防止 3 個 false breakthrough（37.5% false positive rate without review）

### 2. 50/50 SPY/GLD 不可動搖
K2/K16/K19/K24/K54/K63/K64/K89 共 **8 次獨立驗證**（見 line 191）+ K534 理論解釋（correlation dynamics 不可預測）。任何新策略的 Sharpe 門檻 = 50/50 Sharpe 0.545，打不過就不上架。

### 3. Smooth-weight 設計原則（最可靠）
**連續權重策略（12/VIX、Risk Parity、Piecewise VT）幾乎不受 signal lag 的影響。** 機制：每天權重變化 <5%，即使 lag 方向錯也無害；反觀 binary regime-switch 策略 lag 錯一天 Sharpe 可差 0.5+。教訓來自 K679（VIX Percentile Sharpe 1.68→lag 修正後 0.355，100% artifact）和 K618/K621/K698 共 4 次 lag bug。**設計新策略優先 smooth-weight，避免 binary switch**。

### 4. Proxy-robust 模型比較（Patton 2011 標準）
- GARCH/GJR：原生 target σ²（r² 是無偏估計）
- MEM：原生 target |r| 或 r²（r² 直接可比 GARCH）
- HAR-RV：原生 target 5-min RV
- **跨模型必做 QLIKE on r²**（詳見行為準則「模型比較公平性標準」段）
- K782 教訓：Proxy 比模型更重要——HAR 在 |r| target DM=-15.45（K530）但在 r² target 全輸 GJR

### 5. 風險管理必做 VaR + ES 雙指標
不能只做 VaR——VaR 無法反映尾部形狀。必須用 Fissler-Ziegel (2016) joint score 同時評估兩者。詳見「經濟顯著性評估」段和 K1041/K1092 DCC-A4f 實驗。

### 6. Paper 2 firm-selection 路線完整 dead-end（2026-04-13 K1067 系列 7 實驗）
**A4f-EAV 在 Taiwan equity 有 pooled-level signal，但 cross-sectional heterogeneity 不可用 observable firm characteristics 預測。**
- K1067 (TSMC null) → K1067b (UMC +39%) → K1067c (MediaTek 反方向 monotonicity FAIL)
- K1103 (τ-lag bug-fix STABLE) → K1104 (N=24 fabless p=0.039)
- K1106b (cherry-pick p=0.004) → **K1109 (pre-reg N=31 BH-adj p=0.278 REJECTED)**
- **K1113 (firm-level 6 covariates 全 5/5 FAIL, CV R²=-0.66)**
- → 任何 observable firm characteristic（market cap, beta, sector dummy, earnings CV, momentum）都不能預測 EAV 增益
- → 需要 **private data**（retail flow, governance opacity, analyst dispersion 細節）才能 firm-select
- **Paper 2 final**: pooled A4f-EAV + cluster SE by firm 當 default，不寫 Tier 規則
- **教訓 E052/E053**: pre-registration 2-commit audit trail 救一個 cherry-pick artefact

### 7. Paper 3 copula-GARCH 不可推廣（2026-04-13 K1100 系列 6 實驗 + K1115）
**Lai 2024 PRS copula edge 是 TAIFEX 市場 microstructure 特有現象，不是通用 methodology。** E055 三條件全 REJECTED：
- (a) Near-collinear ρ>0.95: K1100f SPY-ES (corr=0.97) 也 NULL（portfolio variance degenerates as ρ→1）
- (b) Tail-dependent: K1100b 5 pairs 含 SPY-QQQ λ_L=0.589 全 NULL（aggregation 把 tail dep 平均化）
- (c) Single-asset path-dependent: K1115 SPY VaR breach clustering NULL（GARCH-t 已 absorb clustering）
- **K1100g_d1/d2 chain**: 「找到 anchor → OOS 推翻」3 級 correction（E059 LRT-vs-DM divergence trap）
- **Paper 3 status**: 待用戶決策（A reframe negative paper / B TAIFEX microstructure / C abandon）
- **教訓 E055/E056/E060**: pivot depth L1-L4，當前需 L4 framing change

### 8. Paper 4 Universal IV Sufficiency Compendium（2026-04-13 NEW，10 實驗 × 5 asset class × 2 application）
**no public alt-data source improves over native implied volatility for vol prediction or portfolio allocation.**
- **Forecasting NULL**: K473 (Trends VAR) + K750 (Trends weekly) + K789 (Trends overlay) + K504 (STLFSI4) + K1116 (EPU+NFCI+STLFSI on SPY) + K1098 (VIXTWN on 0050.TW) + K1118 (GLD/TLT/BTC native IV sufficient) = 7 evidence
- **Allocation NULL**: K1121 (4 alt-data strategies vs 50/50 baseline, bootstrap p>0.16) = 1 evidence
- **K1116b verified**: TLT M4 NFCI 唯一 positive (+3.74) 是 publication-delay artifact，corrected → +1.96 NS。Universal NULL 統一無例外
- **Active harm pattern**: SPY M4 NFCI 修正後從 -3.00 → -3.61，alt-data 不只 silent 是 actively harmful
- **Paper 4 status**: 主線程寫作 priority 1，建議標題 "Universal Sufficiency of Native Implied Volatility for Weekly Realized Volatility Prediction: A 10-Experiment Compendium"
- **教訓 E061/E062**: knowledge-base precheck 救重複實驗 + FRED publication delay (NFCI shift(5), EPU shift(2)) 必查

### 10. Taiwan microstructure findings（2026-04-13 K1124+K1125+K1128）
**TAIFEX OFI 對 diffusive vol 和 jump 方向相反（Cont-Tankov decomposition 實證）**
- K1124：|OFI| ↑ → 下一 5-min RV ↓ (反 US 市場直覺，Taiwan mean-revert after unwind)
- K1125：|OFI| ↑ → jump 機率 ↑ (DM t=+2.82, sell-side asymmetric)
- K1128：High-VIX tertile DM t=+3.59 超 Harvey，但 COVID OOS 超出 IS 範圍 (E064 教訓)
- 合：Cont-Tankov (2004) decomposition 在 TAIFEX 實證成立，diffusive 主導解釋 K1124 total RV 降
- **Paper Taiwan microstructure** candidate（US vs Taiwan 對比、sell-side asymmetry）
- Triple-gate 擋住 K1124/K1125/K1128 各自 null，但 meta-finding (decomposition + regime) 可寫

### 11. GAS compendium: 8+ assets 全 null（2026-04-13 K437/K1038/K1129）
**Generalized Autoregressive Score (Creal-Koopman-Lucas 2008) 不是通用替代品**
- K437/K1038：equity 4 assets NS
- K1129：USO/GLD/UNG/BTC 4 assets triple-gate FAIL；**BTC DM t=-4.58 Harvey 反向**（score-driven 在 crypto extreme regime 反 hurt）
- Hafner-Wang (2023) commodity GAS claim 在 2021-2026 OOS 未重現
- **不單獨 paper**，併入 Paper 4 vix-sufficiency 作「alt-model NULL」第三類（alt-data forecasting + alt-data allocation + alt-model）
- 通則：score-driven downweight 大 shock 在含極端 events 的期間反向傷害（K1038 equity + K1129 BTC 共同 pattern）
- H4 VaR violation rate 低是「分配假設好」不是「vol predict 好」——兩個不同 task

### 23. Paper 2 two-level mechanism 浮現：between-market 用 institutional + within-market 用 analyst（2026-04-14 K1167）
**K1166 within-market analyst 確認後，K1167 用 institutional ownership 解 cross-market puzzle**
- 4-market institutions_pct ranking: TW 0.247 < EU 0.416 < JP 0.425 < US 0.750 **完全匹配** 2-cluster split
- Spearman ρ(institutions_pct, θ_rel)=+0.80 p=0.20 (N=4 限制 power) — 優於 analyst ρ=+0.40
- Per-stock joint panel: log_analyst β=+1.14e-3 t=+2.71 (PASS); institutions_pct β=-2.73e-3 t=-0.93 (NS)
- **Two-level mechanism**:
  - **Between-market** retail-vs-institutional → cluster split
  - **Within-market** analyst coverage → per-stock θ_EAV_i
  - Institutions_pct **不 subsume** analyst — 兩通道互補
- EU-vs-JP gap (0.14 vs 0.39) institutions_pct 也未完全解釋 (EU 0.416 ≈ JP 0.425) — 殘差留 K1170 press-concentration
- N=4 preliminary, K1165 升 P1 補 N≥8 markets
- **E071**: yfinance major_holders 0.2+ 結構踩坑教訓

### 22. Paper 2 mechanism 翻轉再翻轉：per-stock refit CONFIRMED within-market（2026-04-14 K1166）
**K1164 REJECTED 純粹是 σ² tautology artifact，移除後 analyst hypothesis 在 within-market 層級成立**
- K1166: 110 stocks per-stock θ_EAV_i refit (no shared pooling) + Engle-Ghysels-Sohn (2013) E[g]=1 normalization
- Pooled Spearman ρ(log_analyst, θ_EAV_i) = +0.241, p=0.012 (vs K1164 ρ=+0.40 p=0.60)
- US 獨市場 ρ=+0.575 p=0.001 PASS Harvey
- Panel OLS coef log_analyst β=+9.68e-4 t=+3.56 p=0.0006 **PASS Harvey 3.0**
- 全 4 markets ρ>0 無反向；JP 100% |t|>2 80% Harvey
- Per-stock vs pooled-shared θ_EAV ratio 6-16x（EGS normalization 差異），ordering 保留
- **Mechanism verdict**:
  - K1153 within-market analyst hypothesis **CONFIRMED**
  - cross-market 4-market rank inversion (EU 21 analysts > JP 14.5 但 EU LOW JP HIGH cluster) **仍 open puzzle**
- **E070 教訓**: shared-coef pooled spec 評估個股 mechanism 必踩 σ² tautology；per-stock refit + EGS E[g]=1 才是 ground truth
- K1167 升級 P2 (retail-vs-institutional 解 cross-market puzzle)
- K1169 NEW P1：Paper 2 §5 主線程改寫（K1164 降為 tautology demonstration, K1166 升為 main mechanism test）

### 21. Paper 2 mechanism 仍 OPEN：analyst hypothesis 也被推翻（2026-04-14 K1164）→ 已被 K1166 翻轉
**K1153 後第二次推翻——cluster mechanism 尚未找到**
- K1164 檢驗 analyst coverage × media density 假說 (K1153 §5.4 提出)
- 4-market analyst median: TW 7.5 / EU 21.0 / JP 14.5 / US 32.5
- 假設預測順序 TW<EU<JP<US，但實際 EU(21) > JP(14.5) 且 cluster 反轉 (EU LOW vs JP HIGH) — **rank-ordering inversion**
- Cross-market Spearman ρ=+0.40 p=0.60 無 power
- Panel coef β=-0.149 但是 σ² tautology artifact (θ_rel=θ_EAV/σ² 機械 rank-inverse)，**不可採信**
- **Mechanism question remains OPEN**：K1153 §5.4 必須改寫為「analyst hypothesis tested in K1164 also rejected」
- 衍生 K1165 (N≥8 markets), K1166 (per-stock θ_EAV refit 移除 tautology), K1167 (retail-vs-institutional ownership proxy via 13F/MOF/ECB/FISC)

### 20. Paper 2 四市場 + 雙 cluster taxonomy（2026-04-14 K1153 EU）
**EU 加入四市場全 PASS，但 K1152 quarterly hypothesis 被推翻**
- EU (DAX+CAC+FTSE, N=18 due yfinance earnings 稀疏) pooled θ_EAV = +4.07e-5, bootstrap t=+4.19 PASS
- Placebo +14.77σ p=0/60；3 EAV-def monotonic, drop-5×5 stable
- **Four-market direction universal confirmed** (TW+US+JP+EU all PASS + placebo p=0)
- **θ_rel cluster**: TW 0.167 / EU 0.137 / JP 0.388 / US 0.586
- EU 是純季報但 θ_rel 落 TW cluster → **K1152 quarterly-cadence hypothesis REJECTED**
- 新假說：media concentration × analyst coverage 密度（US 季報媒體報導 + I/B/E/S coverage 最密）
- Paper 2 narrative: "four independent markets + refined two-cluster θ_rel taxonomy; quarterly cadence 不是 cluster 主因"
- 衍生 K1163 (EU local filings 改 N=30), K1164 (analyst coverage + media mechanism test)

### 18. Paper 2 relative-magnitude verdict: 方向 universal + 量級 market-specific（2026-04-13 K1152）
**Scale-adjusted θ_rel 仍顯著差異：quarterly vs mixed reporting cluster**
- K1145/K1147/K1150 三市場 absolute θ_EAV 差 3× — 只是 scale artifact 還是真 magnitude 差異？
- θ_rel = θ_EAV / avg_σ²: TW 0.1673 [0.109, 0.247] / US 0.5862 [0.395, 0.859] / JP 0.3875 [0.354, 0.482]
- avg_σ² 三市場近乎相同 (3.26e-4 ~ 3.80e-4) — scaling 沒校正差異
- Wald H0 (equal θ_rel): χ²(2)=29.19, p≈4.6e-7 bootstrap p=0.000 — 決定性 reject
- CI overlap: TW∩US=F, TW∩JP=F, US∩JP=T → quarterly cluster (US+JP) vs mixed (TW)
- **Paper 2 narrative 雙層修正**: "方向 universal（三市場均顯著正向）+ 量級 market-specific（quarterly reporting institutional density 主導）"
- 衍生 K1153 EU 4th market, K1156 TW 季報 sub-sample converge test

### 19. Paper 2 binary-sufficient universality 跨市場確認（2026-04-13 K1157）
**JP 完美複製 US K1151 — 三市場 binary EAV 全 PASS，US+JP continuous 全 NS**
- JP TOPIX N=30 同 panel 同 design：binary θ=+1.25e-4 boot t=+13.03 PASS vs continuous θ=+4.76e-6 boot t=+1.32 NS, ΔAIC=-2551 strongly favors binary
- Placebo z=+1.53 p=0.067 跟 US K1151 (+1.60) 量級一致
- Drop-5 sign-flip when removing SoftBank (outlier-driven main-spec signal)
- **Universality verdict**: 三市場 binary PASS + 兩市場 continuous NS replication
- Paper 2 narrative 升級：「Announcement-day long-run variance channel reflects information-processing friction (attention/IV crush/scheduled hedging), not scaling with market-aggregated EPS surprise magnitude — universal across US and JP」
- 衍生 K1162 (analyst-coverage-high sub-sample mechanism test)

### 17. Paper 2 mechanism narrowing: binary sufficient, surprise size 無關（2026-04-13 K1151）
**Continuous EAV surprise spec 全面失效 — 機制非 surprise-size driven**
- US S&P 500 N=30 (K1147 cache) 同 panel: continuous |Surprise%| z-score winsor p99 取代 binary EAV
- Binary θ=+1.72e-4 boot t=+4.49 p=0.000 (K1147 confirmed) vs Continuous θ=+5.26e-6 boot t=+1.11 p=0.413
- Placebo continuous z=+1.60 p=0.10 (跟 null 無法區別)
- **ΔAIC binary - continuous = -5479** (binary 嚴格更佳)
- **Mechanism evidence**: announcement-day vol clustering 跟 surprise size 無關 → 解釋為 attention-based vol spike 或 IV crush 一致性 resolve，非 information-shock-magnitude 驅動
- Paper 2 narrative 微調：「effect characterised by announcement-day information-processing friction rather than surprise-magnitude-scaled information shock」
- 衍生 K1157 (JP universality verification), K1161 (options IV crush as alt continuous regressor)

### 16. Paper 2 三市場全 PASS：true global volatility regularity（2026-04-13 K1150）
**TW + US + JP 三市場全 universal-magnitude PASS — 真 cross-market regularity 確認**
- JP TOPIX top-30 pooled θ_EAV = +1.413e-4，bootstrap (n=150) t=+11.99，95% CI [+1.29e-4, +1.76e-4]
- Placebo 60 reps: 觀測值 = +38.6σ from null mean，p=0/60 decisive
- 3 EAV-def monotonic shrinkage 同 K1145 TW pattern
- Drop-5 × 5 seeds θ ∈ [+1.34e-4, +1.47e-4]，全部 t > 18
- **Three-market table**: TW (+6.36e-5, t=+5.24, +13.6σ) / US (+1.91e-4, t=+4.50, +70.7σ) / JP (+1.41e-4, t=+11.99, +38.6σ)
- Magnitude ratio US/TW=3.0, JP/TW=2.2, JP/US=0.74 — 同 1e-4 量級
- JP 高 t (+11.99) 觸發 Rule #5 self-challenge: TOPIX top-30 同質性 > S&P 500 (NVDA/TSLA outlier 不存在)，所有 150 bootstrap draws 嚴格 >0，三層一致可接受
- **Paper 2 final narrative**: "Three independent equity markets, 5 robustness layers each, magnitudes differ ~3× but direction uniformly positive — global volatility regularity where GARCH-MIDAS τ component absorbs market-wide announcement-day variance premium invisible at firm level but robust at panel level"
- K1146 主線程改稿升 P1; 衍生 K1153 EU + K1156 cover-fig

### 15. Paper 2 cross-market 升級：global volatility regularity（2026-04-13 K1147）
**TW K1145 + US K1147 雙市場全 PASS — universal regularity 確認**
- US S&P 500 top-30 pooled θ_EAV = +1.91e-4，bootstrap t=+4.50，95% CI [+1.29e-4, +2.80e-4]
- Placebo 60 reps: 觀測值 = +70.7σ from null mean，p=0/60 (比 K1145 +13.6σ 強 5×)
- 3 EAV-def: 1d 峰 +1.91e-4 / 3d +7.7e-5 / 5d +8.3e-5 — US conference call 同日集中釋出
- TW (+6.36e-5) vs US (+1.91e-4) 方向 match，量級比 3.0 (US 大型股 σ² 規模較大 + 季報密度)
- **Paper 2 升級 narrative**: "Two independent equity markets (TW N=31 + US N=30), 5 robustness layers each, consistent with global volatility regularity where GARCH-MIDAS τ component absorbs market-wide announcement-day variance premium invisible at firm level but robust at panel level"
- 衍生 K1150 (TOPIX 第三市場), K1151 (continuous surprise), K1152 (relative-magnitude), K1153 (EU)

### 14. Paper 2 SAVED：universal-magnitude pooled effect（2026-04-13 K1145）
**Pooled MLE 揭露 firm-level idiosyncratic SE 掩蓋的 universal signal**
- N=31 K1109 pre-reg stocks pooled A4f-EAV，shared θ_EAV，stock-FE on (m_i, GJR_i)
- **Pooled θ_EAV = +6.36e-5**
- Cluster bootstrap (n=150) **t=+5.24** primary inference (Hessian Wald t=14.14 may inflate)
- Bootstrap 95% CI [+4.13e-5, +9.38e-5] excludes 0
- Placebo permutation 60 reps mean=+1.36e-6 ≈0; observed = +13.6σ from null mean; one-sided p=0/60
- 三 EAV-def (1d/3d/5d) θ 線性遞減 +6.4e-5 / +3.8e-5 / +1.7e-5 符合 smear-over-days 物理直覺
- Drop-5 stocks × 5 seeds θ ∈ [+6.21e-5, +7.96e-5], t ∈ [+12.17, +14.12]
- vs single-stock K1109: mean θ=+4.64e-5 SE=1.15e-4 (t=0.40 NS); pooled SE=1.21e-5 (9.5x reduction)
- Codex review passed
- **Paper 2 narrative pivot**: 從 dual-NULL 改為 "EAV is universal-magnitude population-level constant, invisible at firm level due to large idiosyncratic SE"
- **E069**: pooled panel reveals signal hidden by firm-level noise floor — 對 dual-NULL 假設前必跑 pooled spec
- 衍生 K1146 (paper rewrite, main thread), K1147 (US S&P validation), K1148 (continuous surprise EAV), K1149 (PCA factor competition)

### 13. Paper 2 dual-NULL 確認（2026-04-13 K1114→K1140）→ 被 K1145 推翻
**Cross-sectional + temporal θ_EAV heterogeneity 雙 NULL**（已過時 — 見 §14 K1145）
- K1114 rolling 2-yr A4f-EAV on TSMC/UMC/MediaTek 報 3/9 BH-PASS (UMC trend t=3.06, MediaTek t=4.51, TSMC regime KS p=0.009)
- K1140 三層 robustness 重檢：(1) Newey-West HAC L=5/24/48; (2) Spearman block-permutation; (3) Block-bootstrap block=24 gold standard
- 結果：HAC L=24 後 1/9 倖存 (MediaTek t=4.33)，block-boot 後 0/9 PASS — K1114 全為 96% overlap artifact
- K1067 三檔 mean pattern 真實但 within-sample artifact，無 systematic 來源
- Paper 2 contribution 定位轉為 rigorous null：「after N=31 sector ANOVA + 5 covariates + rolling HAC + block-boot, no systematic θ_EAV heterogeneity survives MTCorrection」
- **E068**：HAC alone 對 high-overlap rolling 不夠，必加 block-bootstrap 第二門

### 12. Universal robust-method NULL：非 score-driven 也失敗（2026-04-13 K1136）
**「alt-model NULL」擴張到 score-driven + non-score-driven 兩家族**
- K1136 fair-test 設計：M3 GARCH-MIDAS-X vs M1 GJR-N on r²（close²-native 公平）；M4 HAR-RV-X vs M5 HAR-RV on Parkinson（within HAR-family control, 孤立 VIX marginal）
- **Fair Test #1 (MIDAS)**: 0/4 PASS, DM t=1.23/0.94/0.62/-0.32
- **Fair Test #2 (HAR-within)**: 0/4 PASS, DM t=1.65/-0.88/0.74/0.52, GLD 反向
- **命名升級**：Paper 4 從 "GAS-specific fail" 升為 "Universal robust-method NULL across score-driven AND non-score-driven"
- 證據合計：8 unique assets × 4 proxies × {GAS/MIDAS/HAR-X} = 一致 NULL
- **Meta-lesson (E066)**：首次跑 M4 看到 Parkinson t=2.5~13 誤判為 breakthrough，實為 model-target mismatch 造成的 mechanical win；加入 M5 within-family control 才揭穿
- 亦修 VIX monthly-lag double-shift bug（`monthly.shift(1)` + "latest ≤ d" 重複 shift）

### 9. 防 in-sample data mining 的雙重門檻（2026-04-13 K1100g_d1/K1115/K1116 教訓）
**LRT 顯著 + DM-HLN<2 = overfit 警訊**（E059）：
- LRT 用全樣本 likelihood 易 overfit residual variance → χ² 易顯著
- DM-HLN test forecast accuracy improvement，prospective fit assessment
- 兩者 divergence > 1.5 → 必做 OOS 才能 publish
- K1100g_d1 in-sample LRT χ²=12.48 p=0.0004 → K1100g_d2 OOS LRT 0.00 p=1.00（推翻）
- K1115 IS Kupiec p~0.92 grid fit → OOS p<0.01 同 pattern
- K1116 M5 IS QLIKE -2.84 → OOS +59.9（24× degradation）
- **規則**：Paper-publishable finding 在啟動文章 agent 前必做 OOS PASS

## Next Session Priorities（2026-04-13 update）

### P0: 用戶決策待回（不可繼續挖同 direction）
- **Paper 3 strategic decision** (A negative paper / B TAIFEX microstructure / C abandon)
- **Paper 4 main thread 啟動寫作** (compendium 10 實驗 ready)
- **TSMC 法說 04/16** 事件文章準備（04/17 截止）

### P1: 高價值新方向（避免 Paper 2/3/alt-data 死局重蹈）
- 面向 G NLP sentiment（用真新聞 headlines + FinBERT，非 Google Trends）
- 面向 G market microstructure（OFI from existing TAIFEX tick）
- 面向 I7 Taiwan cross-border hedging
- Paper 6 crypto fear 完稿 (K639/K746b/K1025 素材齊備)

## Next Session Priorities（2026-03-31 起）

### P0: 時間敏感

| 項目 | 說明 | 截止日 |
|------|------|--------|
| **HAR-RV 正式實驗** | 5-min 數據 ETA 04/11 達 60 天門檻 | 04/11 |
| **TSMC 營收 04/10 解讀** | 營收公告後解讀文 | 04/11 |
| **TSMC 法說 04/16** | 預告+解讀文 | 04/14, 04/17 |
| **FOMC 04/28-29** | 預告文 04/26，事後解讀 04/30 | 04/26, 04/30 |

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
- [x] **★ Paper: Multiplicative GARCH-X(VIX) — 規格比較與 VRP 解釋**（K988 發現，初稿 31p 完成 2026-04-10）：
  - **核心發現**：K988/K988b 比較 17 個規格。A4f（VIX² + free ω）冠軍 DM t=+4.48 vs GJR。τ=VIX² 最佳（維度一致）。GARCH-MIDAS 不優於單 lag。
  - **已完成**：跨資產（K994 QQQ/K997 GLD PASS）、VaR/ES（K995 scorecard 3/4）、Codex 審查（K999）、VRP 驗證（K998 NULL）。初稿 31 頁完成。
  - **論文待做**：E(g)=1 理論推導、Conrad & Loch 比較、Student-t df 聯合估計
- [ ] **HAR-RV 正式實驗**：K744 驗證數據 94% clean，K745 pipeline 通過。SPY 51 天（ETA 60 天 ~04/07），需 100+ OOS days ~05 月。到時重跑 HAR-RV vs HAR-ABS vs GJR 的完整比較
- [ ] **Paper 6: Crypto Fear Channel**：K746b 確認 BTC vol asymmetrically Granger-causes VIX。結合 coupling 增加 + tail dependence，可寫成「加密貨幣市場對傳統金融的波動率溢出」論文
- [ ] **Paper 5 正式撰寫**：草稿 31p 已完成。Codex 建議 J. Forecasting。需要：統一 pipeline（不只 VIX，含 HAR-RV/GARCH benchmark）、多重檢定控制、replication package

**新完成（2026-04-10）：**
- [x] **K1013: Bayesian SSVS GARCH-X Variable Selection** — NULL，所有 PIP<0.01。GJR persistence=0.956 已捕捉殘差方差。不矛盾 K988（joint MLE vs 殘差修正不同機制）
- [x] **K1014: HAR-PD Path-Dependent Features** — Path features 惡化 HAR（multicollinearity trap）。vix_gap 唯一顯著（t=7.27）。HAR 仍是 QLIKE(r²) 最強。衍生：HAR+vix_gap 簡約模型
- [x] **K1015: VIX9D+VIX3M Dual-Factor A4f — NULL**。θ₂=0，退化為單因子。DM t=-0.298 (Dual) / t=-1.333 (Slope) 全 NS。VIX9D 完全吸收 VIX3M。VIX sufficiency #30
- [x] **K1016: HAR+vix_gap — In-Sample Overfit**。vix_gap IS t=18.43 但 OOS QLIKE(r²) 惡化（1.831 vs HAR 1.616）。|r| MSE 改善（DM=-2.869 未達 Harvey）。86.5% 時間 VIX>realized 導致系統性高估。教科書級過擬合
- [x] **K1019: MS(2)-GJR ★ — Regime Dynamics Real**。MS-GJR 顯著勝 GJR（DM t=-3.20 PASS）但輸 A4f-VIX9D（DM t=+2.75 NS）。Calm: γ=0.60; Crisis: pure β=0.83。Regime prob 與 VIX 弱相關 r=0.225。衍生：MS-A4f 結合兩者

- [x] **K1016b: HAR+vix_gap corrected**。|vix_gap| DM t=-4.20***、vix_gap² DM t=-5.57*** 顯著勝 HAR，但 A4f 仍稱霸（DM t=+7.11***）。線性 vix_gap ≡ VIX level
- [x] **K1020: MS(2)-A4f NULL**。結合 regime+VIX 反而惡化。VIX 已包含 regime info
- [x] **K1021: A4f df joint ★**。df≈8.5，QLIKE 不變但 VaR 從失敗→通過。Paper 9 建議 df=8
- [x] **K1022: A4f 跨資產 6/6 QLIKE 改善**。Student-t 下 DM 個別未達 Harvey 但 VaR 6/6 PASS
- [x] **K1023: E(g)=1 理論框架 ★★**。VRP auto-correction 證明非 relabeling
- [x] **K1024: Refit insensitive ★**。QLIKE spread 0.021%，63d 最佳
- [x] **K1025: Crypto Fear Channel ★★★**。BTC down-vol→VIX asymmetric
- [x] **K1026: Conformal VaR ★★**。92% pass rate vs parametric 58-83%。不是 K800 artifact
- [x] **K1027: Drawdown Recovery K735 修正** — K735 rho=-0.49 確認為 artifact（IS=0.00, OOS=-0.14）。VIX reactive not predictive。Protection overlay 不如 12/VIX
- [x] **K1028: DCC-A4f Multivariate** — DCC-A4f 勝 DCC-GJR（DM t=2.58）但 DCC≈CCC（SPY-QQQ 相關太穩定）。A4f 共用 VIX 因子=隱式 common factor

- [x] **K1029: 金融股早期預警 MIXED**。Granger F=18.98 存活 VIX 控制，但 GARCH-X 反而惡化。VT overlay +1.5%。Regime indicator 非 predictor
- [x] **K1030: ★★ Sub-Period 7/7 全勝**。QLIKE +4.8~8.1%，平均 6.52%。非 COVID 驅動。Paper 9 robustness 完備

**中優先（新研究主題）：**
- [ ] **K1016b: HAR+vix_gap 修正版**：修正 M4/M5 bug，重新評估 vix_gap 在正確 QLIKE 下的效果
- [x] **K1018: Robust VT**：Sharpe 0.594 vs baseline 0.575（DM t=-1.47 ns）≈ BH 50/50。不上架。Sensitivity PASS 但 alpha 不顯著。VT=insurance confirmed
- [x] **K1019: VIX Regime 轉換預測** — NULL。Naive persistence F1=0.91 unbeatable。12/VIX smooth weight 已內建 regime 資訊。Regime-switching 反而更差（Sharpe 0.882 vs 0.918）
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
**最後更新：2026-04-10。下次更新：2026-05-01。**

### 美股事件
| 日期 | 事件 | 研究安排 | 文章安排 |
|------|------|---------|---------|
| **04/28-29** | **FOMC 利率決議 + Powell 記者會** | FOMC 對 VIX/vol regime 影響 | 預告 04/26，解讀 04/30 |
| **05/02 (五)** | **NFP 非農就業（4 月）** | 就業 vs vol | 預告 04/30，解讀 05/03 |
| **05/13 (二)** | **CPI 通膨數據（4 月）** | CPI surprise | 預告 05/11，解讀 05/14 |
| **05/29 (四)** | **GDP 第二估（Q1）** | GDP vs vol | 預告 05/27，解讀 05/30 |

### 台股事件
| 日期 | 事件 | 研究安排 | 文章安排 |
|------|------|---------|---------|
| **04/16 (四)** | **TSMC Q1 法說會** | TSMC earnings 對 0050.TW vol | 預告 04/14，解讀 04/17 |
| **04/17 (五)** | **中經院台灣經濟預測** | 經濟預測修正對台股 sentiment | 搭配法說會文章 |
| **05/10 前** | **TSMC 4月營收公告** | TSMC 營收 surprise | 預告 05/08，解讀 05/11 |
| **06月~** | **台股除權息旺季開始** | 除權息對 vol/return | 系列文章 |

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

### SEC Filings / EPU / Google Trends 研究方向
→ 完整項目清單見 `docs/research_archive/detailed_research_topics.md`
- SEC Filings（10-K/10-Q/8-K 文字探勘、情緒、財務、管理、MOPS）：長期方向，待數據取得
- EPU/GPR：VIX sufficiency 限制下作為內容題材（每月至少 1 篇市場解讀）

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
→ 完整審查詳見 `docs/research_archive/codex_paper_reviews.md`

## 其他研究方向（詳細版）
→ MEM 文獻、Gemini/用戶建議（WVD/TE-VT/K770 修正版/Overnight component）、Hansen & Lunde Gold Standard 比較 → 見 `docs/research_archive/detailed_research_topics.md`
