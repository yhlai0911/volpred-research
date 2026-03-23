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
- **MF2-GARCH**（Conrad & Engle 2025: 短期 GJR + 長期乘法誤差模型）— 測試中
- 混頻模型（GARCH-MIDAS: 結合日頻 vol + 月頻總經變數）
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

### Phase O: VaR 方法論擴展（2026-03-16 啟動）
**動機**：Student-t(df=5) 是固定分配假設，CF-VaR 用殘差的實際 skew/kurtosis 自適應修正分位數。
- [x] O1: CF-VaR 跨資產驗證——5/5 資產 1% VaR 通過 Kupiec（SPY 0.9%, QQQ 0.7%, GLD 0.8%, TLT 1.2%, EEM 0.9%）。唯一在 1% 和 5% 都通過的方法
- [x] O2: EVT-VaR (POT+GPD) 失敗——28 violations (1.9%, p=0.003)，比 Student-t 還差。GPD 在 rolling window 不穩定
- [x] O3: CF-VaR 整合進 risk_forecast.py（SPY CF 3.42% vs Student-t 2.67%）
- [x] O6: MIDAS Hyperbolic null result（+0.00% vs GJR, 4 assets）
- [x] O7: Taiwan 0050.TW CF-VaR — w=504 best (p=0.88), w=2000 發散 (kurt=545, need winsorization)
- [x] O8: ★★ Skewed Student-t 6/6 通過 Kupiec — 唯一全通過的方法。CF-VaR 5/6 (QQQ fail)。最終排名：Skewed-t > CF-VaR > Student-t(5) > Normal
- [x] O9: Skewed-t 整合進 risk_forecast.py — SPY skewt 3.14% vs CF 3.42% vs t 2.67%
- [x] O11: VaR-based position sizing — ⚠️ 原報告 Sharpe 1.98 有 same-day timing bias（Q10 修正）。Lagged: 12/VIX 0.96 vs VaR 0.88 (DM p=0.62 NS)。12/VIX 優勢在簡單性而非 Sharpe
- [x] O12: Distribution 不影響 QLIKE (+0.057%, p=0.56 NS) — GARCH eq→QLIKE, dist→VaR，獨立可優化
- [x] O13: GED VaR fail (≈Student-t) — 確認偏態是 VaR 關鍵，不只是厚尾
- [x] O14: Acerbi-Szekely ES backtest — 三種分配全 pass (p>0.45)。Skewed-t Z1/Z2 最小（最佳 ES）
- [x] O15: CAViaR (Engle-Manganelli 2004) 自建 — SAV spec 與 Skewed-t 統計等效 (DM p=0.35)。IG 失敗，AD 有 clustering
- [x] O16: ★ Fissler-Ziegel joint loss 揭示 coverage vs efficiency trade-off — FZ 排名與 Kupiec 相反（Normal best FZ, Skewed-t best coverage）
- [x] O17: Gamma 不預測殘差偏態 (ρ=0.45, p=0.26) — VaR 分配選擇和 VT 策略是正交問題
- [x] Realized GARCH 自建 (Hansen et al. 2012) — QML 估計, pilot -18% QLIKE。Blocked 等 252+ 天 5-min 數據
- [x] N120: VIXTWN 數據源+收集腳本 — 免費 3-4 月 (TAIFEX), corr(VIXTWN,VIX)=0.90, ratio=1.39
- [x] O18: Portfolio VaR — HistSim 唯一通過 Kupiec (p=0.58)，Copula 不需要
- [x] O19-O32: FHS VaR, BTC VaR (Normal best), ETH/SOL, commodity/sector, final leaderboard
- [x] Trinity test (5% VaR): FHS 7/7 > Skewed-t 6/7 (GLD clustering)
- [x] Codex peer review: 10 flaws → P3-P5 robustness checks (multi-quantile, subsample, bootstrap)
- [x] O10: VaR 方法論已寫入論文（精簡版 in body.tex Section 4.4）

### Phase P: 自建模型 + 策略 + QLIKE 天花板（2026-03-17）
**動機**：Phase O 收斂後，(1) 回應 Codex 批評 (2) 自建非套件模型 (3) 策略改善探索
- [x] P1: DD-aware VT — null result（Sharpe -0.002）
- [x] P2: Custom EWMA vs arch GJR — 套件 vs 自建差異僅 0.2%
- [x] P3-P5: Codex 回應——multi-quantile (Skewed-t 3/3), subsample (all pass), bootstrap (98% stable)
- [x] P10-P12: MA200 trend filter Sharpe 2.41 但 Harvey NS (t=0.89, p=0.37)
- [x] P13: ★ Gamma→skewness 顯著 (ρ=-0.636, p=0.026)，修正 O17
- [x] P14-P15: GARCH-MIDAS(INDPRO) OOS p=0.001 是 period-specific（full sample NS）
- [x] P18: 跨資產 GARCH-MIDAS — 4 資產全部 DM NS。GJR 仍是 Occam winner
- [x] P19: Bootstrap gamma→skewness CI [-0.87, -0.13] 不含零（穩健）
- [x] P20: VRP=f(gamma) 方向正確但 N=4 不足
- [x] P21-P22: CARR 自建——Parkinson -3.6%（overnight bias），Yang-Zhang 修正後等效
- [x] P23: Credit spread + yield curve in GARCH-MIDAS — θ≈0，無改善
- [x] P25: Codex Crisis Gold Overlay 失敗（-0.03 Sharpe）
- [x] P26-P27: MIDAS nowcasting——naive scaling R²=0.786（mechanical），Beta weighting overfit
- [x] ★★ QLIKE ceiling: 4 模型×4 macro 變數×3 資產全部 DM NS → GJR 定義日頻下界
- [x] 4 自建模型：Realized GARCH, CAViaR, GARCH-MIDAS, CARR
- [x] Codex + Gemini 各 2 次 AI 協作審查
- [x] P29: JPY carry trade signal — null result (chi2 p=0.64)
- [x] P30: VIX half-life 22 days (AR(1) ρ=0.969)
- [x] P31-P33: ★ MS-GARCH 自建（第 5 個）——in-sample +2.25% 但 OOS -0.01% (QLIKE ceiling 5th confirmation)
- [x] P34-P43: ★★ Vol regime duration + backwardation 策略
  - Weibull shape<1（regime duration 不可預測，decreasing hazard）
  - VIX backwardation 預測 regime onset (3.39x lift, p≈0)
  - Incremental beyond VIX level (low VIX 5.1x lift)
  - ★ Passes Harvey threshold (t=4.31>3) for SPY+QQQ
  - BUT subsample unstable: 2015-2019 drives the result (t=4.42★), crisis NS
  - Mechanism: backwardation days avg return -0.66%, Sharpe -3.91
- [x] 論文整合 Phase O+P：4 處 body.tex 更新（Codex 5 建議中 4 已實現）
- [x] 論文 VaR 方法論已寫入（Section 4.4 精簡版 + complexity ceiling table）。Backwardation 已在 P46 killed，不寫入
- [ ] 5-min 數據累積到 252+ 天後重測 Realized GARCH

### Phase Q: 跨市場 VT + 多變量模型（2026-03-17 啟動）
**動機**：Phase O+P 收斂後，擴展到 (1) 跨市場策略 (2) 多變量建模 (3) 3+ 資產組合優化
- [x] Q1: ★ 12/VIX 台灣擴展——8.63/VIX（=12/(VIX×1.39)）**修正後 Sharpe 0.69**（月度再平衡, lagged, TX 0.585%）, MDD -15.3%（vs B&H -37.6%）。MDD 顯著，Sharpe NS
  - 跨市場驗證：VT 核心價值是 drawdown protection 不是 return enhancement
  - Q_sharpe_reconciliation: Q1 原報 1.16（遺漏 TX + daily rebal）, Q7 報 0.612（daily rebal + TX）, R14 報 1.32（same-day bias）→ 統一後 0.69
  - 月度再平衡 + 0.585% TX 是實務正確規格
- [x] Q3: ★★ DCC-GARCH(1,1) SPY-GLD 自建（第 6 個自建模型）
  - a=0.032, b=0.955, 半衰期 15 天, ρ 範圍 [-0.63, +0.46]
  - 關鍵理論發現：2 資產 RP 權重與 ρ 無關（解析結果，非實證）
  - DCC 不改善配置 (DM p=0.19)，但改善 VaR (Kupiec pass vs naive fail)
  - 3+ 資產 RP 才需要 DCC（ρ 不再消去）
- [x] Q4: 3-asset DCC-ERC — DCC 統計改善 vol (p=0.023) 但經濟意義微小 (Sharpe +0.006)。Inverse-vol 足夠。DCC 的 catch-22：diversified portfolio = low corr = DCC 不重要
- [x] Q5: Taiwan 8.63/VIX 整合進 daily_update.py — 4 策略 paper trading (VIX=23.5 → 37% 0050.TW)
- [x] Q7: Taiwan K/VIX sensitivity — Sharpe 與 K 完全無關（數學恆等式）。Calibration leakage impossible。K 只決定風險水平
- [x] Q8: ★★★ VT Recovery Paradox 解決方案
  - VT 在 6/7 大跌中 recovery 比 B&H 慢（confirmed）
  - 3/5 re-entry 機制通過 Harvey (Bonferroni t>3.3):
    - VIX Velocity t=5.86, Momentum 50MA t=4.00, VIX Percentile t=3.45
  - 全部通過 1000 placebo tests (p=0.000)
  - 推薦 Momentum Overlay: DD>15% + SPY>50MA → 18/VIX (Sharpe +0.16)
  - 但僅在 SPY 上測試，需跨資產驗證
- [x] Q9: ★ Momentum Overlay 跨資產失敗——0/4 assets pass Harvey, overlay 惡化 MDD (-1.98% avg)
  - QQQ: signal fires 太少 (5.9%), EEM: always-on (46%), 0050.TW: degenerate (64%)
  - SPY V-shaped recovery 是特例，不可推廣
  - Q8 降級為 SPY-only finding
- [x] Q10: ★★★ VRP 分解 + Same-Day Timing Bias 發現
  - VRP timing 6 策略全部 NS vs 12/VIX（VIX 已包含完整 VRP）
  - 關鍵方法論修正：same-day VIX_t→r_t 膨脹 Sharpe +1.0（ρ=+0.65）
  - 12/VIX lagged Sharpe ≈ 0.81-0.96（非 1.80-1.98）
  - GARCH VT bias 極小（+0.09），因 σ_t 只依賴歷史數據
  - O11 修正：12/VIX vs VaR 比率 2.04x→1.08x (DM p=0.62 NS)
  - 論文 body.tex 已修正
- [x] Q11: CDaR optimization null result — K=12 已在 CDaR/Calmar 最佳區間 (K=10.5-11.5)。嚴格單調 tradeoff，無 free lunch
- [x] Q12: ★ FDR Audit — 30/32 positive findings survive BH-FDR (q=0.05)。53 null vs 34 positive (ratio 1.6:1)。研究誠信確認。5 項定性風險已識別修正
- [x] Codex + Gemini 第 3 次 AI 協作審查：共識 pivot to writing, complexity ceiling narrative
- [x] Q13: Copula-GARCH tail dependence
  - SPY-GLD: lower tail dep ≈ 0（GLD 不與 SPY 同崩 → 分散有效），upper tail dep 0.27（QE 同漲）
  - SPY-QQQ: lower tail dep 0.82（極高！危機時幾乎完全相關）
  - Copula 對分散組合無用，對集中組合（SPY+QQQ）才重要
  - 第 7 個自建模型：Gaussian/Student-t/Clayton/Gumbel/Frank copula
- [x] Q14: SPY-QQQ tail dep 對 40/30/30 的實際影響
  - VaR 低估僅 2%（1% level）、8%（0.1% level）→ GLD 30% 稀釋效果
  - Tail-dep-aware 策略 Sharpe +0.05-0.07，但 inverse-vol 不用 copula 就能達到
  - 結構性 insight：40/30/30 = 70% US equity + 30% GLD
  - Copula 只對 stress test 有用，不改變投資決策
  - ★ Phase Q Complexity Ceiling 第 7 次確認
- [x] Q15: VVIX 預測 VaR violations — null result。AUC=0.44（比隨機差）。VIX/GARCH ratio 仍是唯一有效指標 (AUC=0.76)。Complexity ceiling 第 8 次確認
- [x] Q16: ★ VIX transport coefficient — timing alpha 跨資產不可靠（0/7 consistently positive）。MDD improvement 普遍有效 (10-16% for all 7 assets)。Best predictor: corr(asset_ret, ΔV IX), r=0.54。IWM paradox: VIX positively predicts IWM (mean reversion)
- [x] Q17: Commodity + Crypto ceiling test
  - BTC-USD: ceiling confirmed (DM p=0.28) despite gamma=0.117（noise 太高）
  - USO: borderline (QLIKE p=0.006 但 MSE p=0.134, +0.12% only)
  - ★ BTC 需要 Skewed-t VaR（正偏態 0.464，Normal/Student-t 都 fail）
  - Cross-asset ceiling: 6/7 confirmed (SPY/QQQ/GLD/TLT/EEM/BTC), USO borderline
- [x] Q18: BTC 正偏態策略——正偏態 regime-dependent (55% positive)，非結構性。BTC VT(15%): MDD -84%→-42% (p=0.003)，Sharpe NS (t=1.45)。Coskewness=-0.61（惡化組合）
- [x] Q19: ★ Gamma-mechanism 邊界條件（12 資產定義性測試）
  - 跨所有資產：ρ=-0.448, p=0.14 (NS) → gamma 不是 universal predictor
  - 純 equity (N=6, VIX corr<-0.4)：ρ=0.886, p=0.019 → equity 內仍成立
  - VIX correlation 是更好的跨資產 predictor
  - MDD improvement 是 universal mechanical effect（ρ=0.944 with vol level）
  - Gamma stability concern: SPY 0.33→0.20 declining
  - 修正命題：gamma predicts within homogeneous equities only
- [x] Q20: ★ Gamma decline 是 cyclical 非 structural（3yr trend p=0.41）
  - VT 完全不依賴 gamma（ρ=-0.029, p=0.96）
  - GJR 在所有 gamma 水平都贏 GARCH
  - MC: gamma=0 → VT MDD improvement +0.386, 100% sims positive
  - Open question "gamma decline 影響 VT?" → **正式回答：不會**
- [x] Q21: ★ 最佳零售投資組合——50/50 SPY/GLD + 12/VIX + SHY
  - Sharpe 0.826, Calmar 0.77, MDD -15.5%（vs SPY B&H -34.1%）
  - 添加 QQQ 有害（tail dep λ_L=0.82 → one bet）
  - GLD 價值在分散化非報酬（zero tail dep confirmed）
  - Decision tree: 零計算→VIX Step Rule; 月度→50/50 12/VIX; 低風險→60/40
  - COVID: -8.9% vs B&H -33.8%
- [x] Q22: Complexity Ceiling Score (CCS) — 31 模型評分，52% 提供零/負價值。最優 4 參數系統: GJR + FHS + 12/VIX
- **Phase Q 結論**: Complexity Ceiling 完全確認（9 維度, 6/7 資產類別, 31 模型）。日頻策略空間 saturated。VT 唯一可靠價值 = mechanical MDD reduction

### Phase R: Beyond VT — GARCH 應用擴展（2026-03-17 啟動）
**動機**：Phase Q 確認 VT/VaR 策略空間飽和，探索 GARCH 在其他投資決策的價值
- [x] R1: GARCH persistence 預測宏觀經濟 — null result。VIX 已包含所有 vol persistence 信息
- [x] R2: ★ VIX/GARCH ratio timing for short straddles
  - Ratio>1.5: +77% alpha per trade, MDD -51%→-5%, t=13.68
  - Monotonic regime relationship (ρ=0.138, p=5e-10)
  - 全部 robustness 通過（bootstrap, block bootstrap, trimmed, tx cost）
  - ⚠️ CRITICAL CAVEAT: simulation-based (BS-approximated daily), 需真實 options 數據驗證
  - GARCH 在 VT/VaR 之外首次發現有價值的應用
- [x] R3: Factor VT (Moreira-Muir 2017) — null result。6 FF factors 全部 Harvey NS (max t=1.64 UMD)。GARCH vs RV22 無差異。Post-publication decay + 近年 factor premium 消失。MDD 改善仍 robust (5/6)
- [x] R4: Gamma-momentum switch — null result。Gamma 在 ETF 層級太穩定（SPY: 2 changes/10yr），退化為固定 label。理論優美但實證無效
- [x] R5: ★ Weekly straddle simulation — all thresholds pass Harvey t>3
  - Always-sell Sharpe 2.43 (margin), ratio>1.3 Sharpe 3.02, ratio>1.5 Sharpe 3.32
  - MDD: -54% (always) → -28% (ratio>1.5)
  - Monthly straddles FAIL（tail risk -136%）
  - Ratio>1.3 sweet spot: 185 trades/8yr, Sharpe 3.0
  - ⚠️ 仍是 simulation (BS approx)，需真實 options 數據最終驗證
- [x] R6: Cross-asset straddle timing
  - Naive VIX-as-IV for QQQ/GLD 有根本缺陷（IV mismatch ±4pp）
  - 修正後（simulated IV）: SPY/QQQ/GLD 全部 pass Harvey t>3
  - Timing signal: SPY genuine (p=0.014), GLD genuine (p=0.008), QQQ NS (p=0.10)
  - ⚠️ 2024-2025 subsample degradation, GARCH overestimates vol ~30%
  - 需要真實 VXN/GVZ 數據做最終驗證
- [x] R7: GARCH risk budgeting vs RV22 — null result。Sharpe +0.021 (p=0.748)。GARCH 唯一優勢在危機偵測（提前 ~1 月）但不持久。Simple inverse-RV sufficient
- [x] R8: ★ Extended OOS 2025-2026Q1 驗證——所有核心發現確認
  - GJR vs GARCH: DM=4.82 (p<0.0001), gap widens 0.40%→0.56%
  - GLD gamma 100% negative, strengthening (-0.089)
  - VT MDD -43%, Sharpe NS
  - Iran/Hormuz crisis: VT auto-reduce to 58%
- [x] R9: 5-min pilot analysis — 42 天數據乾淨，microstructure noise 極小，HAR-RV 需 60+ 天（ETA 2026-04-14）
  - RV 比 daily r^2 noise 低 10.5x
  - 有趣發現：用 RV 做 truth 時 plain GARCH 贏 GJR（待 60 天驗證）
- [x] R10: GINN (GARCH-Informed NN) — QLIKE ceiling HOLDS。+1.15% 是 proxy mismatch artifact（Parkinson vs r²）。r² proxy: DM p=0.935。第 3 次 NN 失敗。PINN 也無法突破 ceiling
- [x] R11: ★ Proxy sensitivity — GJR>GARCH IS proxy-robust。42 天 reversal 是 small-sample artifact（turbulent period + range-bias）。Full sample (N=563): GJR wins under ALL 4 proxies。HMSE (scale-invariant) 也確認
- [x] R12: VXEEM vs VIX for Taiwan — VIX 顯著優於 VXEEM（Spearman 0.595 vs 0.459, Z=16.2）。原因：0050.TW ~50% TSMC → 美國科技情緒 > 新興市場風險。Stick with 8.63/VIX
- [x] R13: FOMC-VIX pattern — null result。123 meetings 全部 6 tests fail Harvey。Pattern 已退化（2010-14 有效→2020-25 反轉）。P45 是 subsample-specific
- [x] R14: TWD/USD 匯率風險 — FX costs -18% Sharpe on SPY-in-TWD，但危機時 USD 升值提供 cushion (+15% in 2022)。8.63/VIX on 0050.TW (修正後 Sharpe 0.69, 原報 1.32 含 same-day bias) 優於 12/VIX on SPY-in-TWD (0.67)。不建議避險
- [x] R15: ★ Sharpe reconciliation — 0050.TW 8.63/VIX 正確 Sharpe 0.69（monthly, lagged, TX 0.585%）
  - Q1=1.16（遺漏 TX + arithmetic Sharpe）
  - R14=1.32（same-day timing bias）
  - Q7=0.612（daily rebal with TX 過度消耗）
  - K-invariance 確認：pure case Sharpe 0.85 for all K
- **Phase R 結論**: 15 experiments。2 positive (straddle weekly), 3 robustness (proxy/OOS/Sharpe reconciliation), 10 null。GARCH 3 應用領域：vol forecast + VaR + VRP timing。Complexity ceiling 跨域確認
- [ ] R16: HAR-RV 正式 OOS 測試（等 60+ 天 5-min 數據，ETA 2026-04）
- [ ] R17: 用真實 options 數據（CBOE VXN/GVZ）驗證 straddle timing
- [ ] Q6: VIXTWN ratio 穩定性（等數據累積到 252 天驗證）

### Phase S: Narrative-GARCH + 新方向探索（2026-03-17 啟動）
**動機**：Phase R 飽和後，Gemini 建議 3 個全新方向（Narrative GARCH, Climate Vol, Network Topology）
- [x] S1: ★ Narrative-GARCH pilot — GARCH params robust across narratives (KW p=0.645)
  - 但 VIX/GARCH ratio 在地緣政治危機顯著更高 (+36%, p=0.025)
  - Narrative 價值不在 conditioning GARCH，而在預測 VIX-GARCH gap (excess fear)
  - 下一步：narrative-conditioned Excess Fear Signal
- [x] S2: Narrative Excess Fear Signal — REJECTED。No variant passes Harvey t>3
  - Best: Z>2.0 unconditional t=2.57（14 episodes, Bonferroni p=0.21）
  - 驚喜：Monetary Anti-Signal（升息期 VIX 高 → 負報酬 t=-5.0）
  - Narrative 價值是告訴你排除哪些信號（monetary），不是放大哪些
- [x] S3: ★ Volatility Network Topology pilot
  - Hub 不固定：QQQ(2021,22,25) / SPY(2023,24) / TLT(2020-COVID)
  - 2024 fragmentation: hub corr 0.80→0.33, meta-corr=-0.003（結構完全重組）
  - BTC integration 非單調（COVID 0.95, 2024 -0.18）
  - 靜態相關假設危險——network 每年重組
  - Implication: VIX-centric 不完整，QQQ-driven contagion 同樣重要
- [x] S4: Rate-hike regime VT filter — null result。More conservatism = worse Sharpe (0.565→0.269)。VT 已透過 VIX 自動調整，overlay 移除太多正報酬天
- [x] S5: VIX seasonality — Monday +1.91% (t=5.38), Friday -0.87% (t=-3.04)。統計上真實且穩定，但經濟上不可利用（R²=1.4%，所有 DOW-adjusted 策略都更差）
- **Phase S 結論**: 5 experiments，descriptive insights 有學術價值（VIX overshoot、network fragmentation、monetary anti-signal）

### Phase T: 自我修正 + Rough Volatility（2026-03-17 啟動）
**動機**：Codex 第4次審查指出多項宣稱過強，需 consolidation + 新方向探索
- [x] T1: BTC VaR Reconciliation — skewness regime-dependent (2020:-2.20, 2023:+0.84)。Normal 1% PASS 但 5% FAIL。Student-t(5) 跨 regime 最穩健。Q17 矛盾已解決
- [x] T2: ★★ |Skewness| predictor COLLAPSED at N=21 — rho=-0.87(N=12) → rho=-0.086(N=21, p=0.71)。完全不顯著。小樣本膨脹。Normal 17/21 PASS, CF 19/21 PASS。CF 略好但 mechanism 非 skewness。GLD/TLT/IEF failures 都是非股票類——需調查
- [x] T3: ★ Rough Volatility pilot — H=0.105 (variogram) 確認 roughness 但 R/S=0.88 DFA=0.99（方法依賴！Cont&Das 2022 部分成立）。QLIKE: GJR wins (DM p=0.80 NS) → ceiling holds。MSE(log): RFSV wins (p<0.001) → 不同 loss function 不同結論
- [x] T4: ★ GLD/TLT/IEF Normal failure 雙重機制——GLD: too many violations (2.0%, 厚尾 kurt=1.29, ARCH borderline)；TLT/IEF: too few violations (0.2%, 2022 regime vol 仍在 window)。failure 方向相反 → skewness 不可能預測。真正 predictor 是 vol regime stability
- [x] T5a: 台股 9 資產 gamma 比較——TAIEX 0.153 > 0050 0.087 > TSMC 0.039。ETF 分散化放大 gamma。SPY 0.230 >> all Taiwan
- [x] T5b: ★ VIX/SPY/FX → 台股 spillover——SPY(t)→tw50(t+1) r=0.376 極強！VIX Granger-causes tw50 vol (F=58.8)。TWD/USD 不顯著 (p=0.08)
- [x] T5c: GARCH-X(SPY overnight) for Taiwan vol — WORSE (+4.7%, DM p=0.019)。SPY→tw50 是報酬相關非 vol 相關。QLIKE ceiling 台股確認
- [x] T5d: SPY Overnight Momentum for Taiwan — SPY(t-1)>0 → long 0050.TW(t)。Full 2018-24 **c2c** Sharpe 1.82 (t=8.07)。⚠️ I8: o2o Sharpe 0.87 FAIL Harvey
- [x] T5e: T5d 驗證——TX cost 116 switches/yr, 0.3%→c2c Sharpe 1.79; 月頻 NS (0.92); 跨亞洲只有台股通過（時區差機制）。EWT control fail → alpha = timezone info gap
- [x] T5f: 5d SPY Momentum 最佳實務版——**c2c** net Sharpe 1.62 (TX 0.3%, 42 switches/yr), c2c Harvey t=3.25 PASS。⚠️ I8: o2o FAIL Harvey
- [x] T8: GLD FIGARCH long-memory — d=0.38 確認長記憶但 OOS 更差 (+0.44% NS)。EGARCH -1.18% best but NS。QLIKE ceiling 對 GLD 也成立
- [x] T9: VRP Regime Switching — null result。5 variants 全部 Harvey NS (max t=2.26)。VIX 已含完整 VRP。Q10 再次確認
- [x] T10: 台灣複合策略——5d SPY Mom c2c Harvey PASS (t=3.25)，⚠️ I8: o2o FAIL。Adaptive K (SPY up→K=12, down→K=6) Sharpe 1.97 零 TX 但 Harvey NS
- [x] T6: ★ Adaptive Window VaR — Fixed_504 和 EWMA(0.94) 7/7 (100%) vs Fixed_2000 5/7 (71%)。VaR 用短窗口更好（regime shift 問題）。但 QLIKE 仍偏好 w=2000。結論：vol forecast 和 VaR compliance 最佳窗口不同
- [x] T11: MOVE Index null result — MOVE→equities r<0.015, VIX/MOVE divergence NS (t=0.56), MOVE overlay NS。Bond vol 無 equity predictive power
- [x] T12: 5d SPY Mom 台股個股——c2c 4/10 PASS Harvey: 0056(3.44), 鴻海(3.40), 0050(3.25), 國泰金(3.06)。⚠️ I8: 全部 c2c，o2o 會大幅降低。ETF 比個股穩定
- [x] T13: VIX 期限結構——TS slope→|return| r=-0.457 極強 vol predictor！但 VT overlay NS (t=0.44)。12/VIX 已是 sufficient statistic。Backwardation (slope<-0.05) 是危機信號
- [x] T17: HAR-RV pilot (42 days, PRELIMINARY N=20) — H=0.071 from 5-min RV。HAR R²=0.095。等 60+ 天
- [x] T18: ★ VIX Regime Tail Correlation — SPY-QQQ 0.85→0.96 (crisis: 完全相關), SPY-GLD ≈0 (全 regime 穩定！), SPY-TLT -0.10→-0.48 (crisis 避險更強)。Portfolio vol ratio 1.07→0.60 in crisis
- [x] T19: ★★ TLT Hedge Structural Break — Pre-2022 corr=-0.42 → Post-2022 +0.09 (Fisher z=-13.58, p<0.0001)。Bond-equity 負相關已死。GLD 是唯一全天候避險
- [x] T20: VIX Mean Reversion Speed — 正常 half-life 10-15d, 危機 25-33d。長期趨勢微弱 (-0.21d/yr)。VT 策略穩健
- [x] T21: ★ Master VaR Panel — 7 assets × 5 methods × 3 alphas × 3 tests (105 cells)。Skewed-t #1 (76.2% Trinity 3/3)。Student-t/CF-VaR/FHS 並列 66.7%。Normal 57.1%。Codex 要求的統一框架完成
- [x] T22: GBM Vol — SPY-only 看似 crack (-13~21%) 但 **cross-asset 5×3=15 cells: 0/15 GBM 顯著贏, 5/15 GJR 贏, mean +7.1% worse**。2018-20 catastrophe +22%。FALSE ALARM。VIX non-linearity 是 SPY+period specific
- [x] T23: 自建 Piecewise VIX→Vol（第 8 個自建模型）— SPY -13.7% 但同 T22 不 generalizable。QLIKE CEILING 第 13 次確認，比之前更強
- [x] T31: VIX Velocity/Acceleration — level (AUC=0.867) >> velocity (0.490)。VIX level 已是最佳 predictor。第 8 種 VIX challenger 失敗
- [x] T32: ★★★ US→Japan Lead-Lag — ^N225 r=+0.419, 5d Mom Harvey t=3.69 PASS (c2c)！Taiwan+Japan 雙確認 time-zone information transmission。EWJ control FAIL。Universal Asia-Pacific law
- [x] T33: ★★★ Full Asia-Pacific test — 6/8 local markets PASS Harvey **on c2c** (HK 4.12, AUS 4.04, SGP 4.03, KOR 3.83, TW 3.75, JP 3.69)。All US-listed ETF controls FAIL。India/Indonesia FAIL
- [x] T34: Europe→US FAILS — EU(t-1)→SPY(t) r=-0.07 (negative!)。Need zero trading overlap for TZ arbitrage
- [x] T35: ★★★ TZ Arbitrage Full Robustness — Multi-OOS 5 periods all positive, combined t=4.47-4.60, Bootstrap CI [0.65, 2.24], Bonferroni PASS (all c2c)
- [x] **I8: ★★★ TZ timing bias 發現 — c2c Sharpe 含不可捕獲的隔夜跳空（78% alpha）。o2o Sharpe: TW 0.87, JP 0.78, 全部 FAIL Harvey t>3。TZ 結果從「可交易策略」降級為「信息傳遞通道的學術發現 + price discovery speed 量化」。3 個策略（taiwan_spy_momentum, tz_tw_jp_5050, global_vt_tz）面板已標記 inactive**
- **Phase T 結論（36+ experiments）**: (1) ★★★ Time-zone information transmission: c2c 6 markets PASS Harvey, 但 o2o FAIL（I8 timing bias）→ 學術發現非交易策略 (2) ★★ |Skewness| collapsed (3) ★★ TLT structural break (4) ★ VIX sufficient statistic (8+ challengers) (5) ★ GLD all-weather hedge + 2025 record +61.5% (6) ★ Master VaR Panel + adaptive window (7) QLIKE ceiling 13x confirmed (8) 50/50 SPY/GLD unbeatable (9) BTC is risk-on not hedge
- [x] T14: Credit Spread + Yield Curve — VIX R²=0.318, credit+yield 僅 +1.6%。Credit overlay WORSE (Sharpe 0.79 vs 0.88)。VIX 吸收所有財務指標信息
- [x] T15: Multi-step GJR——主進程 SPY: 1d -2.68, 5d -3.48, 22d -4.51。**但 cross-asset agent 推翻放大效應**：cleaner 重跑 SPY h=22 t=-0.32（減弱非放大）。0/6 assets 顯示 monotonic amplification。TLT GARCH 更好。EEM 延遲出現 (h=22 only t=-2.62)。**T15 降級為 SPY-specific 且 method-dependent，不寫入論文**
- [x] T16: TSMC→0050 vol spillover — 同步(r=0.885)但不 Granger-cause (p=0.28)。SPY vol 才是 leading indicator (F=19.74)
- **Phase T 結論（進行中）**: 17+ experiments。核心發現：(1) |Skewness| predictor COLLAPSED at N=21 (2) SPY Momentum for Taiwan: c2c Sharpe 高但 **o2o 0.87 FAIL Harvey (I8 timing bias)** → 信息傳遞發現非交易策略 (3) Rough Vol 不破 QLIKE ceiling (#12) (4) VaR 用短窗口(504)/EWMA 比 w=2000 好 (5) ★ VIX 是 sufficient statistic — MOVE, VRP, TS, credit, yield 全部被吸收 (6) 台股: ETF > 個股 for SPY momentum

### Phase U: 策略組合 + Panel 方法（2026-03-17 啟動）
**動機**：Phase T 完成 51 實驗 + meta-analysis，開始探索組合策略與跨資產方法
- [x] U2: TZ Arbitrage 組合策略（3 實驗）⚠️ **I8 降級：全部基於 biased c2c Sharpe**
  - A: TW Mom × VIX sizing → c2c Sharpe 1.37（**不建議**，VIX 砍好部位）
  - B: TW+JP 50/50 TZ → c2c Sharpe 1.81, t=4.86, MDD -11.9%（**o2o 會大幅降低**）
  - C: Global (US VT + TW TZ) → c2c Sharpe 1.61, t=4.31, MDD -8.4%（**50% 基於 biased TZ**）
  - TW-JP corr=0.484, TW-US VT corr=0.14（分散效益在信息層面成立）
  - **Supabase 面板已標記 inactive (is_active=False)**
- [x] U1: Panel GARCH-X — **null result（顯著更差）**。A(+QQQ) -3.75% NS, B(+4 assets) -8.31% p=0.022, C(ensemble) -5.24% p=0.010。更多變數=更多估計噪音。QLIKE ceiling 第 14 次確認
- [x] U3: GARCH-GRU 文獻分析 — 論文有 5 個致命方法論缺陷（22d window, no QLIKE, 3 corr>0.95 assets）。低優先級
- [x] U4: TZ Arbitrage lookback sensitivity — **10d 全面勝 5d (c2c basis)**  ⚠️ I8: 全部 c2c, o2o FAIL
  - TW: 10d c2c Sharpe 1.473 vs 5d 1.141 (+29%), c2c Harvey t=3.76 PASS, 29 sw/yr
  - JP: 10d c2c Sharpe 1.306 vs 5d 1.071 (+22%), c2c Harvey t=3.34 PASS, 28 sw/yr
  - 換手率少 38%, sub-period 全正 Sharpe。建議升級預設為 10d
- [x] U5: Feed 文章發佈——TZ combo 策略（mile_5facef47）
- [x] U6: daily_update.py 台股策略升級 5d→10d lookback
- [x] U7: Adaptive lookback null — 2-regime +0.15 SR 但 p=0.284 NS。TX costs 是瓶頸。Stick with fixed 10d
- [x] U8/K8: DeltaLag null — lead-lag is STATIC (lag=1, 93% stable). Granger F=418

### Phase J: 策略優化 + 新方向（2026-03-18 啟動）
**動機**：Phase I 完成 TZ timing bias 修正後，回到策略基本面
- [x] J1: ★ 月度策略錦標賽 (2010-2024) — 50/50 Static SPY/GLD Sharpe 0.810 (Harvey t=3.13) 是最難打敗的月度基準。Dual Momentum 完全失敗 (0.50)。VIX Regime 0.784 不顯著超越。12/VIX 唯一價值在 MDD (-11.5% vs -20.5%)。核心：分散化 > 信號擇時
- [x] J2: VIX Regime Portfolio null — 最佳(12,20) Sharpe 0.747 vs Static 0.716 (+0.031), DM 全 NS。子期間 2/4 不穩健。不上線
- [x] J3: Google Trends 情緒指標 — ★ partial r=0.634 (recession, controlling VIX) 但 VT overlay NS (DM p=0.47-0.80)。Weekly 頻率太慢，VIX 已即時反映。學術有趣（retail fear→vol channel）但不可交易。VIX sufficient statistic #11+
- [x] J4: Shiller CAPE ratio — 12m corr=-0.32 (R²=0.10) 有長期預測力，但 1m partial r=0.000（控制 VIX 後完全消失）。VT overlay 全 NS (DM p=0.23)。CAPE median crossing ~1次/16月太慢。Current ~37 (91st pctl) 但 >25 since 2015 = new normal。長期估值錨點，非 VT timing signal
- [x] J5: ★★ Range-based VT vs GARCH VT — Sharpe 無差異 (0/20 DM sig)，GJR 贏 MDD (5/5, -8.5% vs -12.7~17.7%)。機制：smooth weight path → MDD control。**但 J6 修正：GARCH MLE noise > EWMA smoothing**
- [x] J6: ★★★ EWMA(0.97) ≥ GARCH VT — Sharpe 0.828 vs 0.782 (5/5 assets, marginal t=2.14 NS)，MDD 12.3% ≈ 12.5% (p=0.73)。GJR rolling MLE 產生 parameter jumps (StdWeight 0.065 vs EWMA 0.019)。Optimal λ=0.97 (HL=23d)。**一行 Excel 公式取代 GARCH**
- [x] J7: ★★★ Smoothness hypothesis REFUTED — controlled test (mean_w fixed): ρ(StdΔw, MDD)=-0.007 (p=0.87)。真正機制：
  - **Crisis reactivity**：raw > smoothed（COVID: -13.2% vs -24.6%）
  - **Signal quality**：VIX forward-looking > GARCH/EWMA backward-looking
  - **Asset-dependent**：SPY/QQQ rough better (ρ=+1.00)，GLD smooth better (ρ=-0.98)
  - Signal roughness（快速反應）≠ Noise roughness（隨機擾動）
  - J5→J6→J7 完整修正弧：observation → deeper test → mechanism correction
- [x] J8: AAII Sentiment Survey — null（模擬數據，real 需 AAII 付費會員）。corr(spread,VIX)=-0.50 冗餘。Incremental R²=0.0001。VIX sufficient statistic #12+
- [x] J9: ★ EWMA(0.97) cross-OOS 5 期間驗證 — **部分修正 J6**。SPY pooled Sharpe tie (p=0.943)，但 GJR wins MDD 4-5/5 periods。COVID: GJR +51% Sharpe, -5pp MDD。50/50 pooled GJR better (+0.168)。EWMA TX advantage ~150bps/yr。結論：EWMA 是零售簡易替代，非 GARCH 取代品。GJR gamma 在危機中有真實價值
- [x] J10: ★★ 最佳再平衡頻率 — 12/VIX monthly net Sharpe 0.792（最佳！> daily 0.679）。TC 從 0.86%→0.14%/yr。EWMA weekly 最佳。Quarterly 太慢。Monthly VT beats B&H MDD 48%。零售推薦：12/VIX + monthly + 50/50 = 12 trades/yr
- [x] J13: Conditional VT 6 策略全 null — 12/VIX 是 VT 的 irreducible kernel。Asymmetric K/Floor/Mom/Cutoff/Percentile 全部無改善。Crisis regime Sharpe=2.20，hard cutoff 錯過反彈。Continuous proportional deleveraging 不可被 discrete regime switch 改善
- [x] J12: Asset-dependent VT — 無單一估計器稱霸。EWMA(0.97) best MDD 4/7 assets。Gamma-based rule ≈ random (43-57%)。Adaptive (GJR+EWMA97) best MDD -12.3% for 50/50
- [x] J14: PE/PB/DY 估值指標全 null。Free PE/PB 不可得。DY current 1.07% 歷史最低。All partial r < 0.06 controlling VIX。VIX sufficient statistic #13+
- [x] J15: 週頻/月頻 VT — 頻率統計上無差異 (p=0.68-0.82)。50/50 monthly Sharpe 0.837, MDD -10.5%。Net Sharpe: monthly 0.630 > daily 0.576。GARCH 週頻/月頻都收斂
- [x] J16: ★ 季頻/年頻 vol regime — 季度 vol 可預測 (VIX r=0.563)。但季度 VT MDD NOT significant (bootstrap 66.5%)。Monthly marginal (91.2%)。Daily strong (99.98%)。**月度 = MDD 保護最低有效頻率**。COVID smoking gun: quarterly -30.4% vs daily -13.5%
- [x] J17: VVIX tail-guard overlay [Gemini] — null。Partial r(VVIX,RV|VIX)=0.006 (p=0.70)。反轉：高 VVIX → VIX mean-reversion (r=-0.12) 非 spike。Best overlay DM p=0.99。VIX sufficient #14
- [x] J18: Correlation breakdown VT [Gemini] — null for strategy。SPY-GLD mean corr=+0.06（**57% 正！**）但 COVID -0.114（危機時才負）。Best overlay DM p=0.73 NS。大跌 (>2%) 信號無用。50/50 有效因為 crash-specific hedge 非 average negative corr
- [x] J19: FHS-VaR targeting [Gemini] — VaR violation 改善 (2.34→1.43%) 但 Sharpe +0.033 NS、MDD 2/6。Risk measurement 有用，VT strategy 無增量。學術：skewness-VaR corr r=-0.89~-0.95
- [x] J20: ★ df=5 kill test [Gemini] — df=5 Kupiec 7/11 (64%), **df=4 better 9/11 (82%)**，Skewed-t MLE best 10/11 (91%)。Asset-class clustering: equity ~5-10, bonds ~15, crypto ~3。Gemini partially right。結論：Skewed-t MLE 已最佳，固定 df 改 df=4
- [x] K1/J21: ★★ Options surface beyond VIX [Codex+Gemini] — SKEW ΔR²=0.00%（zero!），VVIX +0.75%，VIX3M +4% 但 VT NS (p=0.40)。SKEW overlay HURTS (p=0.02)。高 SKEW = fewer tail events（lagging indicator）。VIX sufficient statistic #15，涵蓋整個 options surface
- [ ] J22: 論文 framing [Codex] — criterion-dependent model selection，pre-register primary claims
### Phase K: Options Surface + Portfolio Science + 跨市場（2026-03-18 啟動）
**動機**：Phase J 飽和後，Codex+Gemini 建議轉向新信息集
- [x] K1: ★★ Options surface (SKEW/VVIX/VIX3M) — 整個 options surface 被 VIX 吸收。SKEW ΔR²=0。VIX sufficient #15
- [x] K2: ★★ Mean-variance optimization — 50/50 SPY/GLD net Sharpe #1 (0.893)，beats ALL optimizers (RP 0.889, MinVar 0.855, MaxSharpe 0.722, BL 0.693)。DeMiguel 1/N confirmed。60/40 SPY/TLT 崩壞 (2022-24 Sharpe=-0.098)。VT additive to all allocation methods (+7-10% MDD)。2 assets > 3 assets
- [x] K3: 台灣特有指標深度 — SPY magnitude 1.84x (t=8.08) 但 VT NS。TW50 leads TSMC vol。8.63/VIX 仍最佳
- [x] K4: ★★ Dynamic target vol — 固定 target Sharpe 數學上相同 (0.855)。6 dynamic 全 worse。Target = risk preference
- [x] K5: Drawdown sizing — Pure DD worse。Recovery-aware 更慢。Forward-looking > backward-looking
- [x] K6: ★★★ QLIKE ceiling meta-analysis (14 models × 3 assets) — CC-RV 22d #1 ALL assets。GARCH family spans 0.31%。8.7/14 in superior set。論文表格 ready
- [x] K7: ★★ Vol spillover Granger network — SPY hub (5/10yr)，TW50 in-degree=5 最受影響。BTC→SPY 新發現。高度不對稱 (10/14 one-way)
- [x] K8/U8: DeltaLag null — Lead-lag 是 STATIC (lag=1, 93% stable)。Granger F=418 單向。DeltaLag 概念不適用
- [x] K17: ★★ BTC Halving Momentum VT — Sharpe +19% (t=4.39 PASS Harvey)。但只 2 full cycles，declining returns。需 2028 確認
- [x] K18: ★★★ VIX-timed forex carry — AUD/JPY MDD -40%→-14% (p=0.001)。Own-vol 無效，VIX 是 universal risk appetite indicator
- [x] K19: 50/50 SPY/GLD confirmed vs carry combo。Carry 分散 marginal NS
- [x] K20: ★ 實務實施 $100K 11yr: Sharpe 1.186, MDD -10.5%, TX trivial $641
- [x] K21: Commodity VT null。Supply-driven vol orthogonal to VIX。Cross-asset map: equity ✓, carry ✓, commodity ✗
- [x] K22→K24: HYG portfolio Sharpe 0.972 (t=3.51) BUT FAILS cross-OOS (2/5)。GFC critical failure。50/50 confirmed 4th time
- [x] K23: Multi-period VT = mathematical non-issue（sqrt(h) cancels）。VIX = perfect 30d forward match
- [x] K25: ★ US VIX wins MDD 10/10 intl markets (universal signal). Local 22d RV marginal Sharpe +0.031 but worse MDD everywhere
- [x] K26: ★ 稅務影響——MDD 保護 tax-proof，Sharpe breakeven ~6%。Taiwan best jurisdiction
- [x] K27: Leverage null。Cap=1.0 correct, cap=0.8 better。VIX<12 rare (7%)
- [x] K28: ★★★ Behavioral bias——恐慌賣出損失 40% 財富。VT = behavioral protection system
- [x] K29: ★★ VT = MDD champion vs 7 alternatives (p=0.004)。Not Sharpe champion (RP 0.931 > VT 0.845)
- [x] K30: ★ Leveraged ETF VT——Sharpe invariant, vol decay cut 64%, MDD halved
- [x] K31: ★★ DCA+VT——MDD -5.4% (改善 62.5%)。VT+DCA 機制獨立
- [x] K32: ★★★ VT FAILS 全部 3 個 timing test (HM/TM/Merton)。VT ≠ market timing = volatility scaling
- [x] K33: MOVE bond VT mixed。Post-2022 MOVE > VIX for bonds (R²: 0.454 vs 0.285)
- [x] K34: Rough Vol multivariate NEGATIVE on daily (H~0.01 too noisy)。Need 5-min data
- [x] K35: VT seasonality null (ANOVA p=0.69, ρ=-0.957 = pure mechanical)
- [x] K36: ★★ VT hurts retirement (SWR 5.5%→4.0%)。50/50 B&H best for withdrawal
- [x] K37: ★ Inflation amplifies VT Sharpe penalty (46.5%)。MDD advantage preserved
- [x] K38: ★ 0DTE hasn't broken VT。VIX-SPY corr unchanged。VIX floor ~11→~13
- [x] K39: ★★★ VT Lifecycle Paradox——DCA+VT -55.9%。VT for lump sum only
- [x] K40: ★★ VT hurts endowments (0.44x B&H at 50yr)
- [x] K41: ★★★ NO crossover! VT = constant ~4%/yr insurance at ALL horizons。Investor-type-dependent not horizon-dependent。K39/K40 were framing errors
- [x] K141: ★★ MF2-GARCH (Conrad & Engle 2025 JAE, 第 9 自建模型) — SPY +0.03% NS, GLD +0.06% NS, **TLT +0.30% (p=0.0014)**。首次 ceiling crack for bonds。QLIKE ceiling 是 gamma-dependent：gamma>0.10→GJR 最優, gamma≈0→MF2 error correction 有增量
- [x] K142: XGBoost+HAR vs GJR — GJR 3/3 全勝 (SPY p=0.0001, TLT p=0.002)。第 4 次 ML 失敗。QLIKE ceiling #16。日頻 r² 信噪比太低
- [x] K143: ★ Multi-step vol forecast (h=1,5,22) — GJR 6/6 cells 最佳。QLIKE ceiling #17 擴展到多步。R² 在 h=5 達峰值 0.42（>h=1 的 0.33），多日加總平滑噪音
- [x] K144: MF2-GARCH cross-bond verification（修正 K141）— Joint QML 重估 6 債券/股票：GJR 5/6 勝，K141 的 TLT +0.30% 是 estimation artifact。Proper joint QML 下 MF2 無優勢。QLIKE ceiling 重新全面確認
- [x] K145: R² peak mechanism（延伸 K143）— SPY R² 在 h=5 達峰 0.211（h=1 為 0.160）。機制：信號方差 ∝ h¹（累積），噪音方差 ∝ h²（擴散更快）。SNR 在 h=5 最優。GLD R² 極低（peak 0.012），預測性幾乎為零。h>22 時 R² 歸零
- [x] K147: Execution Alpha (Almgren-Chriss, Gemini R4#4 提出) — $100M 最優清算。Daily proxy(1562d): GARCH vs RV20 僅 +0.0002 bps/trade (t=1.72 NS), vs EWMA +0.0009 bps (t=6.55)。Intraday(46d, preliminary): 差異 -0.0015 bps NS。GARCH execution alpha 存在但經濟意義微乎其微（$100M → $0.20/trade）。Vol forecast accuracy matters but execution is NOT a profitable application
- [x] K149: Regime-aware ICL (arXiv:2603.10299 啟發) — 0/48 cells 勝 GJR。K=100+uniform+VIX 最佳但仍 +0.36-0.55% 差於 GARCH。歷史類比存在(cosine sim 0.96)但 next-day r² 太嘈雜。**QLIKE ceiling #18 確認**。結論：GARCH autoregressive 結構 ≈ optimal E[r²|F_t] estimator，非參數方法無法超越
- [x] K148: Climate Volatility (跳躍式探索) — 氣候事件 vs 金融波動率。Event study 53% 顯著（同期相關），但 GARCH-X 0/5 assets 改善 QLIKE。Partial r|VIX: SPY 0.031, XLE 0.034 (FAIL Harvey)。唯一例外 USO t=3.73 PASS Harvey 但 ΔR²=0.0018（颶風→Gulf oil production 不完全被 VIX 捕獲）。32 事件小樣本。VIX sufficient #17
- [x] K151: Sectoral Vol-Dispersion (Gemini R5#4 Behavioral) — CSVD(speculative vs defensive ETF vol) = null。Partial r|VIX = 0.065，placebo 1000 random pairings 39th pctl (p=0.607)——不可區分於隨機。VT overlay Sharpe -0.056 (Harvey fail)。"Fragile calm" 方向相反（低 vol 持續非 spike）。GARCH-X +0.00% QLIKE。VIX sufficient statistic #18
- [x] K152: ★ Fiscal-Monetary Liquidity MS-GARCH (Gemini R5#1) — 結構假說確認：contraction persistence > expansion (3/3 assets, p<0.001)。但預測無效：0/3 QLIKE 改善，MS-GARCH SPY 顯著更差 (DM +2.64)。GARCH-X Net_Liq slope 0/58 fits 顯著。Partial r|VIX = -0.053 NS。「理論正確但實證無用」。VIX sufficient #20
- [x] K153: VIX-MOVE Vol-Spread VECM (Gemini R5#3) — VIX-MOVE 共整合確認 (EG p=0.0000, HL=34d)。但 ECT 與 VIX 83% 冗餘。GARCH-X with ECT 顯著更差 (DM t=2.47)。VIX Granger-causes MOVE (F=31.2) 但非反向 (F=0.017)——信息流: equity→bond vol。Post-2022 共整合崩壞 (p=0.177)。VT overlay Sharpe -0.073。VIX sufficient #21。與 T11 (MOVE null) 和 T19 (TLT break) 一致
- [x] K150: Amihud Fragility GARCH-X (Gemini R5#2) — GARCH-X(logAmihud) raw QLIKE 4/4 微幅改善 (-0.03~-0.32%) 但 0/4 DM 顯著 (max t=1.12)。"Fragility" 假說被推翻：高 Amihud + 低 vol → next-day vol 0.88x（更低，非更高）。Partial r|VIX mixed (-0.088 to +0.078)，mean -0.019。Amihud ratio 含 |return| 在分子 → 與 vol 內生。QLIKE ceiling #19
- [x] K154: Order Flow Imbalance (微結構探索) — MIXED。Lee-Ready OFI partial r|VIX = 0.11-0.18 (8/12 顯著)——挑戰 VIX sufficient，增量 R² 1-3%。但 GARCH-X walk-forward 0/6 DM 顯著 (best: SPY DM=-1.95, p=0.051 borderline)。Granger 雙向（vol 驅動 volume）。Extreme OFI 3-6x next-day vol（但是 vol clustering artifact）。Daily OFI proxy 太粗糙，與 Codex R6 預測一致
- [x] K155: ★ Information Entropy vol forecast (跨學科) — MIXED-POSITIVE。Shannon/ApEn 有統計顯著信號 beyond VIX：BTC partial r=0.114 (p<1e-11), SPY partial r=-0.070 (p=0.0002)。但 R² 增量 <1%。BTC 最受益（非高斯+多 regime）。SPY 負相關（高 entropy=有序市場=集中交易=更大波動，反直覺但合理）。VIX sufficient 有微小裂縫但經濟上仍成立
- [x] K156: ★★★ RV Decomposition Pilot (Codex R6#1, 46d PRELIMINARY) — Overnight gap 佔 47.4% daily var！BPV(continuous) ACF(1)=0.398 最可預測，jump 僅 2.3%（0/45 sig）。c2c r² vs 5-min RV corr=0.242（目標極嘈雜=QLIKE ceiling 根因）。GARCH 預測 BPV 最好(QLIKE -8.890)。**完美驗證 Codex R6 diagnosis：分解 risk target 是突破方向**。需 252+ 天正式驗證
- [x] K157: ★ Correlation Forecasting (Codex R6#4) — EWMA/DCC 顯著勝 Rolling 22d (MSE 改善 23-31%, DM p<0.01)。但 MinVar Sharpe 1.014 < 50/50 Sharpe 1.042。機制：equal-vol 資產 min-var weight ≈ 0.45 不隨 corr 變。Post-2022 SPY-TLT break: EWMA 3 步適應最快。**50/50 對 variance+correlation 模型選擇雙重 robust**。Codex R6#4 結論：correlation forecasting 也飽和
- [x] K158: Overnight Gap Variance Predictability (K156 延伸) — Overnight gap = 36.5% daily var (confirms K156)。Gap² ACF(1)=0.274。VIX² best predictor (in-sample R²=0.152)。Best OOS: naive_mean (R²=-0.006)。Monday gaps 1.57x larger (p=0.10)。結論：overnight gaps 透過 VIX 部分可預測但大部分不可預測成分仍在
- [x] K159: ★ Wavelet-GARCH Frequency Decomposition — **LOOK-AHEAD BIAS TRAP**。Full-series MODWT(db4): SPY -22.21% (DM p=0.0001) 看似突破 ceiling，但 Haar(NS p=0.63) 和 causal(+52.51% WORSE p=0.0009) 確認完全是前瞻偏誤。SWT/MODWT 非因果轉換在 OOS 使用未來數據。**重要方法論教訓：全序列轉換方法（wavelet/EMD/SSA）天然有 look-ahead bias。** QLIKE CEILING #20
- [x] K160: Volume-Volatility 關係（MDH 假說）— 同時期 r=0.31-0.43 確認 MDH。滯後 partial|VIX r<0.08。OOS: GLD -0.81% ★ (唯一顯著但極小), SPY/TLT NS。BTC volume 無預測力（p=0.53）。GARCH 自迴歸已吸收 volume 資訊。QLIKE ceiling #21
- [x] K161: VIX Term Structure Ratio — Simple r=-0.327 但 partial|VIX r=-0.040。OOS QLIKE -0.082% DM p=0.45 NS。倒掛期間反而更差。期限結構完全被 VIX level 吸收。VIX sufficient #22
- [x] K162: ★ VIX Regime → Return Prediction — VIX spike>15% 次日 +0.274% (t=2.30)，mean reversion 真實。但所有 timing 策略 vs B&H Harvey FAIL (max t=-2.38)。VIX>25 Sharpe 0.448 vs B&H 1.226。持倉太短(4-18%)錯過牛市。**VIX 價值在 risk sizing（VT）而非 return timing**
- [x] K163: ★★ CoVaR 系統性風險傳染 — QQQ/SPY 淨傳染源, EEM 淨受害者。★★ TLT CoVaR structural break（pre-2022 +0.548→post-2022 -0.281）**第三種方法驗證 T19**。GLD ΔCoVaR≈0（不受 SPY 傳染=全天候避險）。尾部事件 lift=4.5x 但 r=-0.057(p=0.09) 邊際
- [x] K164: Realized Dispersion（11 sector ETF）— 日頻 partial|VIX r=0.56 看似突破 VIX sufficient，但 K165 修正為 overlapping window artifact
- [x] K165: ★ 月頻 Dispersion（修正 K164）— **方法論教訓**：非重疊月頻 F p=0.49 NS, OOS DM p=0.66 NS。K164 的 r=0.56 是 rolling window 自相關膨脹。Dispersion 也被 VIX 吸收。VIX sufficient #23（日頻+月頻）
- [x] K166: Hurst Exponent Regime — SPY H=0.54（random walk），rolling 75% 時間 H>0.55（trending）。Trending regime 報酬+1.15%/月(t=3.23)但 r=0.098 p=0.16 NS。OOS 策略 ≈ B&H (t=-0.13)。描述性：市場多數時間 trending，但已反映在價格中
- [x] K167: VRP 跨資產結構 — SPY +3.7%, BTC -31.8%（crypto realized >> implied）。GLD VRP→ret r=0.084★ 最強。VRP 擇時全輸 B&H。跨資產排名 L/S NS (t=-0.36)。VRP = 恐慌溢價量化，非交易信號。Q10 cross-asset 確認
- [x] K168: ★ GARCH Vol-of-Vol — 反直覺：高 VoV violation 4.8% < 低 VoV 5.1%（GARCH 不穩定期反而保守）。Partial|VIX r=-0.105★。VoV-adjusted VaR 5.2%→5.0%（精確但微小）。SPY VoV 0.48 >> GLD 0.13。GARCH 的危險是自滿（低 VoV）而非不穩定
- [x] K169: ★★ Dynamic Volatility Network（12 assets, MST）— SPY hub 82% 時間，crisis 時 IWM(13%)/XLF 接管。★ TLT centrality partial|VIX r=0.159★（債券壓力→股市信號）。avg_corr partial|VIX r=-0.163★（反直覺：高相關→低 future vol）。Hub 轉移完美對應事件（COVID→XLF, Fed hike→IWM）。描述性框架有學術價值
- [x] K170: 財報季波動率效應 — SPY 財報季 RV ratio 0.89 NS (t=-0.88)。控制 VIX 後 t=-0.11。GARCH 殘差無差異。VT 調整 Harvey FAIL。結論：個股財報衝擊被 index 分散化完全吸收
- [x] K171: VPIN 近似（Gemini R7#4）— Simple r=0.128★ 但 partial|VIX r=-0.011 NS。跨 5 資產全部 NS。尾部 lift 2.8x 但可能 VIX 驅動。日頻 OHLCV proxy 無法捕捉微結構信號，需 tick data
- [x] K172: ★★ GLD 創新高後 50/50 穩定性 — GLD>40% 後 SPY 未來僅+2.9%。GLD 新高期 50/50 Sharpe 11.84 vs SPY -0.54。50/50 在 6/8 條件下勝 SPY。目前 GLD +40.8% 新高，歷史類似期 50/50 未來+8.3%（74%正）。**50/50 第 9 次驗證**
- [x] K173: ★ Tail Index（Hill estimator）— SPY α=2.71(厚尾), EEM 2.46(最厚), TLT 4.17(最薄)。★ Partial|VIX r=-0.083★ (p=0.014)——**控制 VIX 後仍有顯著尾部預測力**（微弱但真實）。極厚尾期 2.8x 尾部事件頻率。目前 α=2.14 (61th pctl)
- [x] K174-K175: CDB（Conditional Diversification Benefit）— K174 daily overlapping partial|VIX r=0.210★ 但 K175 非重疊月頻 r=0.110 (p=0.096 NS), OOS ΔR²=-0.016。Partial|corr r=0.045 NS（CDB=correlation 函數，無獨立資訊）。**第 3 次 overlapping artifact 教訓（K164/K174）**
- [x] K176: ★★ 台灣 CoVaR 傳染結構（7 資產）— **TSMC→0050 ΔCoVaR=-1.599，是 SPY→0050(-0.345) 的 4.6 倍**。0050-TSMC corr=0.893。0050 = TSMC 集中風險。中華電是淨傳染源（flight-to-cash）。鴻海是淨受害者（供應鏈）。台灣投資人必知
- [x] K177: ★★★ 台灣最佳避險組合 — **0050+GLD 50/50+VT(8.63/VIX)** 冠軍。COVID MDD -2.9%（B&H -28.6%），Fed升息 -6.6%（B&H -34.2%）。OOS Sharpe 2.370。三層保護：GLD零傳染+VT降曝險+月度再平衡。**台灣投資人完整操作手冊**
- **Phase K 統合（61+ 實驗）**：(1) ★★★ QLIKE ceiling 21x (2) ★★★ RV decomposition 確認 ceiling 根因 (3) ★★ VIX sufficient 21x (4) ★ Codex R6 驗證：variance+correlation+volume 都飽和 (5) 50/50 triple-robust (6) ★ Entropy 對 BTC 有效 (7) Overnight gap 大部分不可預測 (8) ★ Wavelet look-ahead bias trap (9) Volume = MDH，GARCH 已吸收
- [x] K4: ★★ Dynamic target vol — 所有固定 target Sharpe 完全相同 (0.855，數學必然：target 在 Sharpe 相消)。6 dynamic targets 全 underperform。VIX double-dipping harmful。Target = pure risk preference
- [x] K5: Drawdown-based sizing — Pure DD worse (-14.3% vs -13.0%)。VIX+DD marginal。Recovery-aware 更慢 (122d vs 82d)。Kelly terrible (-30.5%)。Forward-looking > backward-looking

- **Phase J 統合（20 實驗）**：(1) ★★★ EWMA(0.97) 零售最佳 default (2) ★★★ Smoothness 假說推翻 → crisis reactivity + signal quality (3) VIX sufficient statistic 13+ 次確認 (4) 50/50 static 最難打敗 (5) 12/VIX continuous = irreducible kernel (6) 月度再平衡 net Sharpe 最佳 (7) 無單一估計器跨資產稱霸

### 面向 G: 情緒與財務指標（2026-03-17 啟動）
**動機**：用戶指示——多元開放探索，只要資料能取得就該做做看
**核心問題**：這些指標能否改善台股/美股的波動率預測或 VT 策略？

**情緒指標（待測試資料可得性）：**
- [x] G3: CNN Fear & Greed Index — **null**。corr(FG,VIX)=-0.567，partial r(FG|VIX)=-0.063。VT overlay 全部 DM p>0.25。報酬預測 incremental R²≈0。VIX sufficient statistic 再次確認
- [x] G5: AAII/SKEW/credit spread/yield curve/VVIX — **全部 null**。控制 VIX 後 partial r <0.03。VIX sufficient statistic 10+ 指標確認
- [x] G9: ★ FRED 總經 sweep (42 變數) — STLFSI2 唯一有增量 (partial R²=16.5%, OOS R²=0.145)。但它是 VIX 增強版非實體經濟。實體指標全 NS
- [x] G10: GARCH-MIDAS(STLFSI) — QLIKE <1% 改善，VT 等效 12/VIX。正常市場 0 天觸發。QLIKE ceiling #15
- [x] G12: ★ 台灣 MIDAS 27 指標 sweep — 進口 YoY 唯一 OOS 顯著 (+5.6%, DM p=0.043)。台灣≠美國（VIX 覆蓋不完全）。景氣燈號/M2 全 null。水準指標 OOS 崩壞
- [x] Google Trends — J3 完成：partial r=0.634 但 VT overlay NS。Weekly 太慢。學術有趣但不可交易
- [x] G8: 台股 4 指標全 null — 外資買賣超是落後指標, PUT/CALL ratio 同日 r=0.41 是 artifact(lagged=0), 融資融券逆向惡化績效, 台積電 PE 被 AI 推翻
- [x] AAII Sentiment Survey — J8: null（模擬數據）。corr(spread,VIX)=-0.50 冗餘。Incremental R²=0.0001。Real data 需 AAII 付費會員
- [ ] VIX/VIX3M term structure（已有 T13 結果，可延伸）

**財務指標（待測試資料可得性）：**
- [ ] 台股/美股本益比 (PE)、股價淨值比 (PB)、殖利率
- [x] Shiller CAPE ratio — J4 完成：12m corr=-0.32 但月度 VT 無增量。估值指標太慢
- [ ] Credit spread (BAA-AAA)（已有 T14 結果，可延伸到台灣）
- [ ] 台灣公債殖利率曲線

**應用方向：**
1. 預測波動率（GARCH-X with sentiment exogenous）
2. 改善 VT 策略（情緒極端時調整配置）
3. 報酬預測（情緒反轉信號）
4. 台股特有指標（融資融券、三大法人）

### ★★★ 戰略轉向（Codex R6 2026-03-22 diagnosis）
**核心診斷：日頻 close-to-close variance + QLIKE 這條路已飽和。153+ 實驗確認 GARCH(1,1) 是這個目標的近最優解。**

突破方向（按 expected payoff 排序）：
1. **分解 risk target**：用 intraday data 把 daily variance 分解為 continuous var + jump intensity + overnight gap。各成分用不同模型。**需要 60+ 天 5-min data（SPY ETA 2026-04-11）**
2. **Option surface features**：完整短天期 options 的 left-tail slope, convexity, corridor variance, jump proxy——不只是 VIX 這個 scalar。Target 改為 overnight downside semivar / gap probability。**需要 options 數據**
3. **Covariance/correlation forecasting**：停止 squeeze univariate variance，轉向 dispersion trading / hedge optimization。我們有 DCC-GARCH (Q3-Q4) 基礎
4. **微結構 alpha**：TAQ/order book level data。Daily OFI proxy 可能不夠（K154 測試中）
5. **Heterogeneous-agent regime model**：ETF creation/redemption, option customer-dealer imbalance → crash regime prediction

**研究方向重新定位**：
- ✅ 繼續：5-min data 累積 + HAR-RV + risk decomposition pipeline
- ✅ 繼續：correlation/covariance modeling（擴展 DCC 到 dispersion trading）
- ⏸ 暫停：在 daily QLIKE 上堆積更多 null results（除非有全新信息源）
- ✅ 繼續：一般讀者文章、策略、論文、跳躍式探索

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
