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
- **風險管理（VaR + ES 都是必做，不可只做 VaR）**：VaR 1%+5%: Trinity test (Kupiec+CC+Basel)。ES: Acerbi-Szekely (2014) Z-test + Fissler-Ziegel (2016) joint VaR-ES scoring。**ES 不是選做——Basel III 已要求 ES 取代 VaR 作為主要風控指標。**
- **經濟性**：Sharpe (Harvey t>3), MDD (bootstrap p<0.001), Calmar, Sortino, CRRA utility, CE return, Net Sharpe (after TX), Turnover
- **跨模型**：CCS Score, FDR audit, Cross-OOS 5 periods, Weight StdΔw
- 每個實驗必須 re-estimate each window（no lookahead）

### 多變量資產配置方法（多資產實驗必做）
**多變量模型（DCC/BEKK/Copula）做資產配置時，必須比較以下 5 種方法：**

| # | 方法 | 目標函數 | 說明 |
|---|------|---------|------|
| 1 | **Static Baseline** | 等權（50/50 或 1/N） | 無需估計，benchmark |
| 2 | **Min-Variance** | $\min w'\Sigma_t w$ | 只需 $\Sigma$，不需 $E[r]$ |
| 3 | **Min-CVaR** | $\min \text{CVaR}_{\alpha}(w'r)$ | 考慮尾部風險（用模擬或歷史） |
| 4 | **Max CRRA Utility** | $\max E[W^{1-\gamma}/(1-\gamma)]$，$\gamma=5$ | 考慮投資人風險偏好 |
| 5 | **Risk Parity** | $w_i \propto 1/\sigma_i$ | 等風險貢獻 |

**評估規則**：
- 必須計算 **turnover** 和 **Net Sharpe**（扣除假設 10bps 單邊交易成本）
- 動態方法的 signal 必須 `shift(1)`（防 lookahead）
- IS 和 OOS **分開報告**
- 如果 dynamic gross Sharpe 勝但 net Sharpe 輸 → turnover 太高，不可宣稱優勝

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
- **DCC-GARCH** → **K915 完成**：SPY-GLD 相關性 -0.64~+0.58（高度動態），DCC 預測 21d corr r=0.88-0.90。但 portfolio NULL：DCC Min-Var 不勝 50/50（DM t=-1.73 NS，turnover 太高）。Static 1/3 each 反而最佳（Sharpe 0.811）。50/50 irreducible #11
  - **K916: MF-GJR on BTC** → Harvey FAIL。VIX 彈性 θ₁=1.06（SPY 的 31%）。BTC-ETF 後 θ₁ 反降。BTC gamma=0.10 正向。1% VaR 全 FAIL（極端尾部）。MF-GJR 跨資產邊界：equity ✅ crypto ❌
- **BEKK-GARCH** → **K918 完成**：SPY-GLD 無 cross-spillover（LR p=0.112, a12=-0.009, a21=0.001）。獨立性=分散化。50/50 irreducible #12
- **Copula-GARCH** → **K920/K921/K922/K923 完成 ★★**：
  - K920: Student-t copula 最佳，λ=0.14 但危機解耦（GFC λ=0.007, COVID ρ=-0.15）。50/50 moat = 危機條件獨立
  - K921: Time-varying copula (Patton 2006) AIC -143.6 勝靜態。但預警 1/3 only。VIX 驅動 λ
  - K922: SPY-0050.TW ρ=0.219（2.3x GLD）但 λ=0.078（半）。COVID 放大 λ=0.364。GLD 一致保護 vs 0050 不可預測
  - K923: Copula hedge NULL——SPY-GLD r=0.058 太低，HE<3%。Copula hedging 需 r>0.90 的避險配對
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
- **50/50 SPY/GLD 不可動搖**（K2/K16/K19/K24/K54/K63/K64/K89 — 10+ 次驗證 + K534 理論解釋 + **K846 根本解釋：三重護城河** = 分散化(r=0.057) + 再平衡溢酬(54bps/yr) + 黃金危機alpha。VT alpha ≈ 再平衡溢酬 → 打平已是最好結果）
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
- **市場微結構**：K862 完成（CS spread US 有增量 t=3.68，台股無效）。可延伸：order flow imbalance（需 tick 數據）
- **網絡/傳染模型**：K907/K910 完成。TCI 與 VIX 正交（r=0.001），是全新風險維度但非交易信號（K910 NULL）
- **因果推論**：K856 完成 NULL（Fed DiD/RDD 4 方法全 NS）。可延伸：其他政策事件
- **Agent-Based Simulation**：K827/K864 完成。VT 擁擠臨界點 30-50%，異質性讓擁擠更嚴重（K864）
- **加密 DeFi**：AMM 池的 impermanent loss 與波動率的關係、DeFi yield 策略的風險管理
- **氣候金融**：K861 完成（油價代理，非對稱性 t=5.82 但逆向 Granger 更強）。需直接氣候數據延伸
- **行為金融**：K860 完成 ★★（PT λ=1.52 翻轉 VT 評價）。可延伸：status quo bias + complexity aversion
- **跨學科方法**：K863 完成 NULL（物理相變全輸 VIX，#25）。可延伸：生態學 regime shift detection

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
- [ ] `/latex-academic-reviewer` 全面審查
- [ ] 修正 Gemini 指出的 3 弱點（TX tax、linear scaling、TSMC endogeneity，見 gemini_review_v1.md）

**第三篇：Is Volatility Targeting Just Trend Following?**
- `paper/vt-trend-following/main.tex`（29 頁）
- 目標：Journal of Portfolio Management 或 Financial Analysts Journal
- 核心貢獻：分解 VT 的 alpha 來源（K46→K53→K79: r=0.564, VT alpha = trend following）
- [ ] 修正 review_v2 的 5 HIGH（見 review_v2.tex）
- [ ] Gemini 審查
- [ ] `/citation-verifier` 引用驗證

**第四篇：The True Cost of Volatility Targeting — Insurance Premium Decomposition**
- `paper/vt-insurance-cost/` (FRL target)
- 目標：Finance Research Letters（< 2500 words, $200 submission fee）
- 核心貢獻：首次將 VT 保險費分解為 opportunity cost (91%) + direct cost (9%)
- 基於：K811v2 + K846 (rebalancing premium)
- 文獻缺口：Moreira & Muir (2017), Harvey et al. (2018) 都沒做 cost decomposition
- 狀態：**v1.2 submission-ready**（學術審查 + 引用驗證 + Codex adversarial 全通過）

**第五篇：When Volatility Targeting Crowds — Quantifying the Tipping Point via ABM**
- `paper/vt-crowding-abm/` (FRL target)
- 核心貢獻：ABM 量化 VT 擁擠臨界點 50-70%（K827v3 修正流動性混淆後）
- 基於：K827 → K827v2（敏感度）→ K827v3（固定流動性，Codex 致命缺陷修正）
- 狀態：**v1.2 submission-ready**（Codex 3H 修正：流動性隔離 + 量化非發現 + 敏感度驗證）

**第六篇：Periodic Realized GARCH (PRG)**
- `paper/prg-periodic-garch/main.tex`（14 頁）
- 目標：Finance Research Letters 或 Asia-Pacific Financial Markets
- 核心貢獻：單一 GARCH 遞迴 + session-specific 參數，DM t=-4.15~-6.63 Harvey PASS
- 基於：K874→K874c 系列 + TAIFEX tick data
- 狀態：Supabase 已上架，working

**第七篇：Volatility Absorption Hypothesis**
- `paper/volatility-absorption/main_v2.tex`（39 頁）
- 目標：Journal of Financial Economics
- 核心貢獻：恐慌對 realized return 的邊際影響隨 VIX 上升而遞減（SAR 從 3.16 降到 2.32）
- 基於：VIX regime × shock type 交叉分析
- 狀態：Supabase 已上架，working

**第八篇：VIX Sufficiency — Can Anything Beat VIX?**
- `paper/vix-sufficiency/main_v2.tex`（39 頁）
- 目標：Journal of Forecasting
- 核心貢獻：11 個 signal family 全部 OOS 無法勝過 VIX，Holm-Bonferroni 校正後仍成立
- 基於：32 次 VIX sufficiency 確認 + cross-era 驗證
- 狀態：Supabase 已上架，working

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
- [x] 金融股早期預警系統 → K887 完成（Harvey PASS 但策略 overlay NS）

**論文**：第二篇 `paper/taiwan-vt/main.tex`（34 頁）涵蓋台灣 VT + TZ 資訊傳遞

## Codex/Gemini/用戶建議（統一區）

### Codex/Gemini/用戶建議（開放方向）
→ 完成項目見 archive
- [ ] **Conditional Dispersion Trade**（Codex #7）：⚠️ BLOCKED 需 sector ETF options
- [ ] **Options surface state variables**（Codex #5）：⚠️ BLOCKED 需 options 歷史數據
- [ ] **Dispersion / correlation-regime trading**（Codex #5）
- [ ] **Retail Reflexivity & Gamma-Driven Skew**（Gemini #2）：⚠️ BLOCKED 需 order flow 數據
- [ ] **Path Signatures for Rough Volatility**（Gemini #2）：需 5-min 數據（可用 TAIFEX tick）
- [ ] **TXO Put-Call Ratio Mean-Reversion**（Gemini #1）：TAIFEX 網站數據
- [ ] 跨資產 return prediction：SPY、0050.TW、QQQ
- 策略上架前必須：Cross-OOS ≥ 5 periods、3 年回測、Net Sharpe (after TX) > 0
- **不要輕易上架**——交易策略必須多次確認（cross-OOS + out-of-sample + sensitivity），避免上架後發現是錯誤

### Bayesian Subset Selection 方法論（用戶指定，2026-03-26）
- [x] K433 Bayesian SSVS → K924 NULL（10 變數全 PIP<0.5，SPY return 不可預測）
- [ ] Bayesian Subset Selection for TARMA — Chen, Liu, Gerlach (2011) Computational Statistics, 26, 1-30
- [ ] Threshold Variable Selection for Asymmetric SV — Chen, Liu, So (2013) Computational Statistics, 28, 2415-2447
- [ ] Threshold GARCH with Bayesian Model Selection — 結合 2006+2013 方法

## 前沿文獻方向（2025-2026）

### 即刻可行動（不需新數據）
- [ ] VIX-Managed Portfolio 文獻引用整理 — Int. Rev. Financial Analysis 2024（支持 Paper 3）

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
- [ ] **Probabilistic RV Quantile Forecasting** — arXiv:2508.15922（從 HAR/GARCH 點預測到條件分位數）
- [ ] Sentiment-Augmented GARCH-LSTM — Computational Economics 2025
- [ ] KAN for VIX Forecasting — Expert Systems with Applications 2025
- [ ] CNN-Transformer Hybrid — European J. Finance 2025
- [ ] GARCH-to-Neural — AAAI 2024
- [ ] ML Risk-Based Allocation — Scientific Reports 2025（LSTM + regime switching，Sharpe 1.38）

### Rough Volatility & Hurst
- [ ] ★ **Multivariate Rough Volatility Model** — arXiv:2412.14353 (Feb 2026)。多變量 fractional OU + GMM 估計。跨資產 rough vol 的正式框架。
- [x] Time-Varying Hurst → K936 NULL（日頻無效）
- [ ] Adaptive Fractal Dynamics — Frontiers Applied Math 2025
- [ ] Non-Gaussian Rough Vol — arXiv:2507.15437

### Tail Risk & Conformal Prediction
- [ ] Regime-Weighted Conformal VaR (RWC) — arXiv:2602.03903 (2026)
- [ ] Conformal Predictive Portfolio Selection (CPPS) — arXiv:2410.16333
- [ ] **Online Conformal via Universal Portfolio** — arXiv:2602.03168 (2026)
- [ ] **KOWCPI (Kernel-Optimally-Weighted Conformal)** — arXiv:2405.16828。自適應權重 conformal prediction interval，適合波動率聚集。
- [ ] Risk Parity + Heavy-Tailed + Regime-Switching DCC — Paolella (2025, JTSA)

### 台股期貨夜盤策略（用戶提出 2026-04-03）
→ 8 實驗詳見 `docs/research_archive/completed_session_2026-04-03.md`
- 核心發現：K844（TX VT 空頭全勝）、K847（gap 61% 可交易）、K849（HAR-RV 勝 GJR on RV target）、K852（RealGARCH 橋接悖論）

### 期貨避險方法論
- [ ] Quadratic Hedging under GARCH — Ma, J. Futures Markets 2026
- [ ] Copula-based GARCH Hedge — Hsu et al.
- [ ] Wild Bootstrap OHR — JRFM 2024
- [ ] Partial Cointegration Hedging — RQFA 2023
- [ ] Regime-Switching Correlation Hedging

### Codex 第 9 次建議（2026-04-03）[提出: Codex GPT-5.4]
→ 完成項目見 `docs/research_archive/completed_session_2026-04-03.md`
- [ ] **K833 衍生：Real Options P&L Validation**：⚠️ BLOCKED 需 OptionMetrics
- [ ] **K831: SPY 5-Min RV Horse Race**：SPY 55 天已收集，~04/07 達 60 天門檻
- [ ] **K832: Jump Decomposition**：需 5-min 數據

### 衍生方向（TAIFEX K847-K849 系列）
→ 完成項目（K906/K850/K852/K851/K852b）見 knowledge.json
- [ ] **K849 衍生：HAR-RV-Night 成分分析**：夜盤 vol 57%，分開 RV_night/RV_day 做 regressors
- [ ] **K847 衍生：Paper 2 更新（高優先）**：加入 K844/K847/K848-K852 發現
- [ ] **K906 衍生：HAR-RV + Overnight Adjustment**：Hansen & Lunde (2005) RV_total。等 252+ OOS 天（~2026-11 月）
- [ ] **K851 衍生：Day/Night Continuous Decomposition**：分開 C_day 和 C_night 做 regressors

### 衍生方向（2026-04-03 session）
→ 完成項目見 `docs/research_archive/completed_session_2026-04-03.md`

### 新發現（2026-04-01 文獻搜尋）
- [ ] **Transfer Learning for New Issues Vol** — arXiv:2503.12648 (March 2025)。多源遷移學習預測數據稀少資產（新 IPO/分割股）的波動率。實務導向工具。

### Gemini G3 + CARR + ML + Hedging（2026-04-06 完成）
→ 15 實驗詳見 `docs/research_archive/completed_session_2026-04-06.md`
- 核心發現：K935(YZ CARR ★)、K938(跨資產 ★★)、K941(CAViaR ★)、K942(13/13 ★★)、K943(h=5 ★★)
- VIX sufficiency 從 6 新角度確認。ML(MLP/KAN)全敗。QH≈MV。GARCH 遞迴不可替代

### 其他
- [ ] Regime-aware In-Context Learning — arXiv:2603.10299（LLM vol forecasting）
- [ ] 「HAR ceiling」驗證 — Los Flamingos 2025
- [ ] Financial Innovation 2025 review — realized volatility forecasting 綜述
- [ ] RGARCH-CARR-SK（Realized GARCH + CARR + 高階動差）— 2025
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
→ 內容產出規則（文章類型/數量/圖表/發佈節奏）見 `CLAUDE.md`「每日文章產出要求」段。
- 所有議題標注發起者（Gemini/Codex/Claude/用戶）
- 具體發現存 `research_findings.md`（加入 embedding）
- Claude 應定期讀取平台摘要（analytics / questions），把讀者回饋與高分會員問題納入研究來源

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

### 最終工具指南（K426-K908, cross-OOS validated）
| 任務 | SPY | Other equity | Non-equity | Taiwan |
|------|-----|-------------|------------|--------|
| **Forecasting (日頻 r²)** | **MF-GJR(VIX) ★★★** (K889: -6.6% QLIKE, 5/5 cross-OOS) | MF-GJR(VIX) (K889: QQQ -5.2%) | GARCH(1,1) | GJR alone (MF-GJR NS for 0050.TW) |
| **Forecasting (5-min RV)** | HAR-RV (K906 preliminary, 需隔夜調整) | HAR-RV (未測) | HAR-RV (未測) | **HAR-RV ★★★** (K849: DM t=-11.14 勝 GJR on RV target) |
| **VaR (complete)** | **MF-GJR + HistSim ★★★** (K908: 1% Trinity PASS, universal) | MF-GJR + HistSim (K908: QQQ Trinity PASS) | GJR + any (K829 GLD all PASS) | **MF-GJR + Student-t ★★★** (K908: 1% Trinity PASS, df~4.7-6.6) |
| **VT Strategy** | 12/VIX（#9 irreducible） | 12/VIX adapted | Asset-specific | 8.63/VIX |

**★★★ 最終結論（K799-K908, K988 更新）：MF-GJR + HistSim = Complete Solution**
- **預測**：MF-GJR(VIX)（K889: -6.6% QLIKE, 5/5 cross-OOS Harvey PASS）
  - **K988 規格優化**：τ=VIX² + free ω + τ_t 分母 → DM t=+4.48（最佳規格）。模型本質是 Multiplicative GARCH-X，不是 GARCH-MIDAS（賴教授指正）
- **風險管理**：HistSim（K908: 3/3 資產 1%+5% Trinity PASS = universal solution）
- **兩個維度獨立優化**。預測精度和風險管理是正交問題（K799 發現）
- 待驗證：更多跨資產 + 整合進 Paper 1/5 + K988 規格的 VaR/ES 驗證

## 重大研究結論
→ VT = drawdown insurance（K687/K697/K700/K701）、50/50 不可動搖（K846 三重護城河）、MF-GJR+HistSim 最佳方案（K908）。詳見 CLAUDE.md「重要研究結論」。

## Next Session Priorities（2026-03-31 起）

### P0: 時間敏感

| 項目 | 說明 | 截止日 |
|------|------|--------|
| **TSMC 營收 04/10** | 預告+解讀文 | 04/08, 04/11 |
| **HAR-RV 正式實驗** | 5-min 數據 ETA 04/11 達 60 天門檻 | 04/11 |
| **TSMC 法說 04/16** | 預告+解讀文 | 04/14, 04/17 |
| **FOMC 04/28-29** | 預告文 04/26，事後解讀 04/30 | 04/26, 04/30 |
| **GDP Q1 Advance 04/30** | 搭配 FOMC 解讀 | 04/28 預告 |

### P1: 高價值

**論文修正：**
- [ ] **Leverage-Direction**（K628 已瘦身 64→52p）：加入「VT is insurance」框架
- [ ] **Taiwan VT**：K636 修正 amplification（gamma vs vol level）、TX cost 已修正

**平台經營方向：**
- [ ] **加強入門內容**：「從零開始」是最熱門文章之一，應建立 /guide 頁面
- [ ] **減少學術文章比例，增加實務操作指南**：收藏(7)>按讚(3) = 讀者當工具書用
- [ ] **Umami API 自動化**：寫 scripts/analytics.py 包裝 Umami REST API

### P2: 研究新方向

**高優先（有明確下一步）：**
- [ ] **★ Paper: Multiplicative GARCH-X(VIX) — 規格比較與 VRP 解釋**（K988 發現）：
  - **核心發現**：K988 比較 11 個 model 規格。A4f（VIX² + free ω）冠軍，DM t=+4.48 vs GJR
  - **關鍵結論**：(1) τ=VIX² 最佳（維度一致 variance↔variance）(2) τ_t 分母 > τ_{t-1}（修正 K889 bug 後翻轉）(3) GARCH-MIDAS 不比單一 lag VIX 好 (4) free ω 改善 VIX² 模型
  - **理論框架**：σ²=τ×g 不是 long/short-run 分解，而是 source decomposition（外生 VIX level × 內生 GARCH dynamics）。E(g)=1 約束下 τ 自動校正 VRP → g 反映 VRP 偏離動態
  - **K988 已完成的規格（11 個）**：
    - A1 K889-original（estimation τ_t / OOS τ_{t-1} 不一致）
    - A2 consistent_tau_t（log-exp τ, τ_t 分母, ω 約束）
    - A3 consistent_tau_t1（log-exp τ, τ_{t-1} 分母, ω 約束）
    - A4 vix_squared（τ=θ₀+θ₁VIX², τ_t 分母, ω 約束）★ 第 2 名
    - A5 vix_level（exp(θ₀+θ₁VIX), τ_t 分母, ω 約束）
    - A2f free_omega（log-exp τ, τ_t 分母, ω 自由）
    - A4f vix2_free_omega（VIX², τ_t 分母, ω 自由）★★★ 冠軍 DM t=+4.48
    - B1-B3 GARCH-MIDAS rolling window K=22/65/125
    - B0 GJR benchmark
  - **K988b 待補做的規格**：
    - [ ] **A3f**（τ_{t-1} 分母 + free ω）：完整交叉比較需要
    - [ ] **方案 B：sample mean 標準化**：ũ_t = u_t / √(mean(r²/τ))，使 E(ũ²)=1 後再跑 GARCH，保持 ω=1-α-γ/2-β 但不假設 E(VRP)=0。A2n（log-exp）和 A4n（VIX²）
    - [ ] **GARCH-MIDAS fixed-span（月頻 τ）**：τ_t 在月內不變，由 MIDAS 加權過去 K 個月的月均 VIX 驅動。原論文最基本的版本，K=6/12/24 月
    - [ ] **VRP 驗證**：計算獨立 VRP = VIX² - realized_var，驗證 g 與 VRP 的 Spearman 相關
  - **後續研究待做**：
    - [x] 跨資產驗證（K994：QQQ DM t=-3.71 PASS，EEM/GLD/0050.TW 不顯著，需本地 fear index）
    - [ ] VaR/ES 評估（Trinity test + Acerbi-Szekely ES backtest）
    - [ ] 正式推導 E(g)=1 的自洽框架（τ 校正 VRP → g 反映 VRP 偏離）
    - [ ] Codex 審 free omega 代碼
    - [ ] 與 Conrad & Loch (2015)、Engle & Rangel (2008) 比較
  - **論文定位**：可單獨一篇（J. Empirical Finance / J. Forecasting），或作為 Paper 5 的核心 section
- [ ] **HAR-RV 正式實驗**：K744 驗證數據 94% clean，K745 pipeline 通過。SPY 51 天（ETA 60 天 ~04/07），需 100+ OOS days ~05 月。到時重跑 HAR-RV vs HAR-ABS vs GJR 的完整比較
- [ ] **Paper 6: Crypto Fear Channel**：K746b + **K855 悖論發現**：BTC-ETF 後 Granger 弱化（p=0.32）但 shock 傳導放大 2.5x。機構化讓 channel 從「線性可預測」變成「事件驅動非線性」。BTC 已非分散化工具（corr>0.3 佔 76% 時間）。論文角度：「institutional adoption amplified shock transmission but destroyed linear predictability」
- [ ] **Paper 5 正式撰寫**：草稿 31p 已完成。Codex 建議 J. Forecasting。需要：統一 pipeline（不只 VIX，含 HAR-RV/GARCH benchmark）、多重檢定控制、replication package

**中優先（新研究主題）：**
- [ ] **VIX Regime 轉換預測**：K752 發現不同 era 的 VIX R² 差異大（0.24-0.64）
- [ ] **跨國 VIX sufficiency**：在 VSTOXX、VNKY、VIXTWN proxy 驗證
- [ ] **Alternative data**：K750 Google Trends 是反應式。嘗試 Reddit/Twitter 情緒或 options flow
- [ ] **Intraday alpha**：5-min 數據就緒後，測試日內 VIX-equity lead-lag（K751 overnight 有 +0.45% R²）

**低優先（長期探索）：**
- [ ] **VT 與 ESG 整合**：ESG 評分高的公司是否有不同的 gamma？
- [ ] **Agent-Based Model 正式版**：正式 ABM 可模擬異質投資人
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
**最後更新：2026-04-06。下次更新：2026-05-01。**

### 美股事件（4 月）
| 日期 | 事件 | 研究安排 | 文章安排 |
|------|------|---------|---------|
| **04/10 (五)** | **CPI 通膨數據** | CPI surprise vs option-implied | 04/08 預告 |
| **04/28-29** | **FOMC 利率決議 + Powell 記者會** | FOMC 對 VIX/vol regime 影響 | 04/26 預告 |
| **04/30 (四)** | **GDP Q1 Advance Estimate** | GDP surprise | 搭配 FOMC 解讀 |

### 美股事件（5 月）
| 日期 | 事件 | 研究安排 | 文章安排 |
|------|------|---------|---------|
| **05/01 (五)** | **NFP 非農就業（4月）** | 就業-vol 關係 | 預告+解讀 |
| **05/13 (三)** | **CPI 通膨數據（4月）** | CPI surprise | 預告+解讀 |
| **05/29 (五)** | **GDP Q1 Second Estimate** | GDP 修正 | 搭配文章 |
| **06/09-10** | **FOMC 利率決議** | Fed 政策路徑 | 預告+解讀 |

### 台股事件（4 月）
| 日期 | 事件 | 研究安排 | 文章安排 | 狀態 |
|------|------|---------|---------|------|
| **04/10 (五)** | **TSMC 3月營收公告**（每月10日前） | TSMC 營收 surprise 對 0050 vol | 「台積電營收公告前後台股怎麼走？」(general) | ⚠️ 04/08 預告 |
| **04/16 (四)** | **TSMC Q1 法說會**（Q1 rev ~$35.2B, +38% YoY） | TSMC earnings 對 0050.TW vol | 「台積電法說前後台股波動」(general+research) | 04/14 預告 |
| **04/17 (五)** | **中經院台灣經濟預測** | 經濟預測修正對台股 sentiment | 搭配法說會文章 | |

### 台股事件（5 月）
| 日期 | 事件 | 研究安排 | 文章安排 |
|------|------|---------|---------|
| **05/10 前** | **TSMC 4月營收公告** | 營收 surprise | 預告+解讀 |
| **06月~** | **台股除權息旺季開始** | 除權息對 vol/return 的系統性影響研究 | 「除權息季節該參加還是避開？」系列文章 |

### 事件執行原則
- 事件前 2-3 天發佈「預告」文章（一般讀者 + 研究各 1 篇）
- 事件後 1 天發佈「解讀」文章
- 研究實驗在事件前 1 週完成，結果寫入文章
- 用 CronCreate 設定 one-shot reminder 確保不遺漏
- **每月 1 日更新此日曆，覆蓋而非累積**

## 待深入研究主題
→ 各主題的完整細項清單見 `docs/research_archive/detailed_research_topics.md`

### 除權息（用戶指定）→ K917 NULL，剩 2 個未完成
### SEC Filings（用戶提出）→ 4 類 ×4-5 項 + 5 篇文章方向，待啟動
### 經濟政治不確定性 & 搜尋趨勢（用戶提出）→ VIX sufficiency 限制，作為內容題材
### 成交量（用戶提出）→ 多 null（K113/K135/K418/K527）。TX overnight gap 待測（t=4.06）

## Codex 論文審查記錄
→ 詳見 `docs/research_archive/codex_paper_reviews.md`

#### MEM 模型文獻（5 項：基礎/AMEM/DMEM/Vector/AMEM-MV）→ 詳見 archive
#### Gemini 建議（3 項：WVD 需 5-min / Gamma-Trap BLOCKED / TE-VT 可行）→ 詳見 archive
#### 用戶方向（2 項：統一 forecast target / Overnight vol component）→ 詳見 archive

### Hansen & Lunde (2005) Gold Standard 比較（等 5-min 數據就緒）
- [ ] **K779（ETA ~04/07）**：用 Hansen & Lunde 最優加權 RV_total = w₁×RV_intraday + w₂×r²_overnight 作為「真實 σ²」proxy，所有模型（GARCH/MEM/HAR）都跟 RV_total 比。這是學術最高標準。需 5-min 數據 ≥60 天。[提出: 用戶]
