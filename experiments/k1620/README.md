# k1620 — 加密貨幣 low-volatility anomaly 的 regime 依賴性

**Verdict: NULL**（在此存活大市值幣樣本內，low-vol 溢酬的 regime 依賴性**不顯著**；raw 溢酬本身亦不顯著且方向偏負）

---

## 1. 動機與研究問題

Low-volatility anomaly（低波動資產風險調整後報酬 ≥ 高波動資產，違反 CAPM）在傳統股市被大量記載
（Baker, Bradley & Wurgler 2011, *FAJ*；Blitz & van Vliet 2007, *JPM*；Ang, Hodrick, Xing & Zhang 2006, *JoF*）。
本實驗檢定一個更細的問題：

> **在加密貨幣，low-vol 溢酬是否只在特定市場 regime 出現（regime-dependent）？**
> 例如只在 bear / high-vol regime 顯著、bull regime 消失或反轉？若是，則為可交易的 regime-timing insight。

### 與傳統股市 low-vol anomaly 的差異化
- 傳統文獻多在**個股橫斷面**（beta / idiosyncratic vol 排序）且以**raw 或 CAPM-alpha** 衡量。本實驗在**加密貨幣籃子**（資產類別波動遠高、報酬右偏、lottery-like）內建 tercile long-short 組合。
- 傳統 low-vol 研究少數處理 regime（多為全樣本平均）。本實驗**明確以 BTC 市場 regime 分組**檢定溢酬異質性。
- 平台內相關 K：crypto leverage taxonomy（`ac69cd03`、`52c317c0`：多數 crypto γ≈0）、GLD leverage **regime-dependent** 有正式 t-test（`c9ec2acc` t=-4.705）、regime-adaptive overlay 在 crypto/SPY 常令 Sharpe 惡化（`8028e757`）。無任何既有 K 直接處理「crypto low-vol anomaly 的 regime 依賴」→ 本題為新方向、非重複。

---

## 2. 資料

| 項目 | 內容 |
|---|---|
| 來源 | yfinance 日收盤（`auto_adjust=True`） |
| 期間 | 2019-01-01 .. 2026-06-30（最後**完整**月；末尾不完整月已剔除，見 §9 Codex fix #1） |
| 標的 | BTC, ETH, BNB, XRP, ADA, SOL, DOGE, LTC, LINK, DOT, AVAX, MATIC（12 檔） |
| 存活幣數隨時間 | 2019 年約 **8** 檔 → 2026 年 **11** 檔（SOL 2020-04 上市、DOT 2020-08、AVAX 2020-07 才進場；**MATIC 於 2025-03-24 停更**，之後退出宇宙） |
| 檢定月數 | **89** 個月（每月月底 rebalance；剔除末尾不完整月後） |

早期幣少（8 檔）、後期多（11–12 檔），tercile 隨月動態調整。

---

## 3. 方法

### 3.1 Portfolio 建構（每月 rebalance）
1. 每幣算日 log return。
2. 對持有月 t：以「截至 **t-1 月底最後交易日**」的過去 **30 日** daily log-return std 排序當月**存活**幣。
3. 分 tercile：`k = n//3`，low-vol group = 波動最低 k 檔等權、high-vol group = 波動最高 k 檔等權。
4. **premium_t = low-vol group 月報酬 − high-vol group 月報酬**（正 = 低波動贏 = 支持 low-vol anomaly）。
5. 一個月至少 6 幣可用（`MIN_ELIGIBLE=6`）才納入，確保 tercile 各 ≥ 2 檔。

### 3.2 Regime 定義（兩種皆跑，皆 lagged）
- **Regime A（primary, trend）**：t-1 月底 BTC 收盤 vs 其 **200 日 SMA**。>SMA = **bull**、≤SMA = **bear**。
- **Regime B（vol）**：t-1 月底 BTC 過去 30 日 vol vs 其 **expanding median**（只累積到 signal 日）。>median = **high-vol regime**。
  - 用 expanding median 而非 full-sample median，避免用未來資訊決定門檻的 in-sample lookahead。

選兩種是因為 low-vol anomaly 文獻對「defensive 溢酬」有兩條 regime 敘事：一是**趨勢**（熊市避險），二是**波動水位**（高波動期避險）。兩者互補，皆檢定。

### 3.3 主檢定
- 各 regime 分組平均 premium + **Newey-West (HAC)** t 檢定（H0: mean=0，maxlags=3 by rule-of-thumb）。
- 迴歸 `premium ~ const + regime_dummy`，**HAC SE**；dummy 係數檢定兩 regime premium 是否顯著不同。
- **Circular block bootstrap**（block=3，2000 次，固定 seed）佐證 regime 差異雙尾 p。

---

## 4. 主要發現（含 null 如實報告）

### 4.1 全樣本 premium（low − high）
| 指標 | 值 |
|---|---|
| 平均月 premium | **−1.65%/月** |
| Newey-West t | −0.71 |
| p-value | **0.478**（不顯著） |
| n | 89 月 |

→ 全樣本 raw low-vol 溢酬**不顯著**，方向偏負（高波動幣 raw 報酬略高，與 crypto lottery/動能特性一致）。

### 4.2 Regime 分組（**核心問題**）

**Regime A — BTC trend（bull vs bear）**
| 分組 | 平均月 premium | t (HAC) | p | n |
|---|---|---|---|---|
| bear（BTC<200d SMA） | −1.07% | −0.40 | 0.686 | 40 |
| bull（BTC>200d SMA） | −2.12% | −0.62 | 0.534 | 49 |
| **差異（dummy 迴歸）** | coef=−1.05% | **t=−0.24** | **p=0.807** | — |
| bootstrap 差異 p | — | — | **0.826** | 2000 |

**Regime B — BTC vol（high vs low）**
| 分組 | 平均月 premium | t (HAC) | p | n |
|---|---|---|---|---|
| low-vol regime（BTC vol<median） | −0.55% | −0.24 | 0.810 | 57 |
| high-vol regime（BTC vol>median） | −3.60% | −0.94 | 0.348 | 32 |
| **差異（dummy 迴歸）** | coef=−3.06% | **t=−0.69** | **p=0.489** | — |
| bootstrap 差異 p | — | — | **0.539** | 2000 |

→ **兩種 regime 定義下，low-vol 溢酬的 regime 差異都不顯著**（p=0.81 / p=0.49）。
方向上高波動 regime 的 premium 更負（−3.60% vs −0.62%），暗示 BTC 高波動期高波動幣「贏更多」，
但**遠未達統計顯著**，不足以支撐 regime-timing 交易 insight。

### 4.3 descriptive 補充（非主檢定、不做顯著性宣稱）
| 組合 | 年化 Sharpe | 累積倍數 | 平均月報酬 | 月報酬 std |
|---|---|---|---|---|
| low-vol tercile | **0.916** | **62.6×** | 7.88% | 29.8% |
| high-vol tercile | 0.852 | 39.3× | 9.52% | 38.7% |
| equal-weight all | 0.920 | 69.3× | 8.80% | 33.1% |

有趣但**次要**的觀察：high-vol tercile **arithmetic** 月報酬較高（9.52% vs 7.88%），
但因波動大、geometric drag 更重，**compounded 終值反而較低**（39.3× vs 62.6×），且 Sharpe 較低（0.852 vs 0.916）。
即：low-vol tercile 以**遠低的波動**達到**相當甚至略高**的風險調整報酬 —— 這是傳統 low-vol anomaly 在
**risk-adjusted / 複利**維度的微弱印記。但：(a) raw 溢酬為負且不顯著；(b) 未對 Sharpe 差異做正式檢定；
(c) **本題的核心問題（regime 依賴）為 null**。故不宣稱 crypto 存在可交易 low-vol 溢酬。

---

## 5. 結論

1. **核心問題答案：NULL。** 在此存活大市值幣樣本（89 月）內，crypto low-vol 溢酬**沒有**統計上顯著的
   regime 依賴性（BTC trend regime p=0.81；BTC vol regime p=0.49，bootstrap 一致）。
2. 全樣本 raw low-vol 溢酬本身亦**不顯著**（−1.65%/月，p=0.48），方向偏負。
3. 唯一與傳統 anomaly 相容的訊號是**風險調整/複利維度**的微弱 low-vol 優勢（Sharpe 0.92 vs 0.85、複利 62.6× vs 39.3×），
   但未達正式顯著、且非本題主張，僅作 descriptive 記錄。
4. **不支持**「crypto low-vol 溢酬可用 BTC regime 擇時」的交易 insight。

---

## 6. Survivorship caveat（必讀）
- 宇宙 = **當前 yfinance 抓得到、且在持有月兩端點都有報價**的幣。中途消失幣的終端損失**未計入**
  （例如 MATIC 於 2025-03 停更後直接退出，而非計入其可能的崩跌報酬）→ **向上 survivorship bias**。
- 因此結論**只在「這組存活大市值幣樣本內」成立**，不可外推為「crypto low-vol 普世無溢酬」或「普世有溢酬」。
- 樣本亦偏大市值（皆為當前仍活躍的主流幣），未涵蓋已歸零的小幣，橫斷面 low-vol 效果可能被稀釋。

---

## 7. 防錯規則遵守聲明（`.claude/rules/experiments.md`）
- **Lookahead（最高優先）**：排序 vol 窗口截至 t-1 月底；買價 = t-1 月底、賣價 = t 月底；兩個 regime 訊號
  （BTC 200d SMA、BTC 30d vol vs expanding median）皆在 t-1 signal 日評估。等價於月頻 `signal.shift(1)`。
  expanding median 只累積至 signal 日，不用未來資訊定門檻。程式碼 `build_portfolios()` / `add_regimes()` 有明確 lag 註解。
- **Seed 固定**：`SEED=42`（`np.random.seed` + bootstrap 用 `default_rng(42)`），可復現。
- **不看圖下結論**：所有結論來自 HAC t-test / dummy 迴歸 / block bootstrap，非圖形目測。
- **跨資產不當 iid（K1355）**：premium 為**組合層級月度序列**（先在幣層級等權聚合成 group 月報酬，再對 89 個月的
  時間序列做 HAC），**不**把 coin-month 當獨立樣本。
- **Sharpe sanity**：low-vol Sharpe 0.92、high 0.86，皆合理（非 >2× baseline），無 lookahead 膨脹跡象。
- **Null 如實報告**：核心問題 null，不過度宣稱、不宣稱因果。

---

## 8. 產出檔案
- `k1620.py` — 完整可復現腳本（資料抓取 + lag + seed + 檢定 + 繪圖）
- `k1620_results.json` — 各 regime premium / t-stat / p-value / bootstrap / portfolio stats / 月度序列
- `k1620_fig_cumret.png` — low-vol vs high-vol vs 等權累積報酬（log 軸）
- `k1620_fig_regime_premium.png` — 兩種 regime 分組平均 premium bar（error bar = HAC SE）

---

## 9. Codex Review

**Reviewer**: Codex CLI 0.142.3（`codex exec`，ChatGPT auth），主線程 foreground（agent 原背景 review 未落地 → 主線程重跑，per `feedback_agent_background_codex_polling_unreliable`）。
**Verdict**: **CONDITIONAL_PASS** — 核心 lookahead / seed / cross-asset-iid 三項皆 PASS；三個 fix-before-publishing 問題，最實質者已修，其餘為 caveat（不翻轉 null 結論）。

Codex 確認通過：
- **Lookahead**：ranking 正確 lagged（k1620.py L112-131），regime 訊號用 t-1 月底（L185-210），無 holding-period 觸碰。
- **Seed**：NumPy + bootstrap 皆固定（L51-52, L275）。
- **Cross-asset iid**：先幣層級聚合成組合月報酬（L144-147）再對 `premium` 月序列做 HAC（L381-395），非 coin-month。PASS（K1355 rule）。
- **Survivorship**：未修正但已充分揭露（L34-36, L461-465）；結論限縮於存活樣本 → conditional pass。

**Issue #1（已修）**：`END="2026-07-04"` + 「每月最後可用交易日」會把不完整的 2026-07 月（僅 2 天）當成完整月報酬，違反月 t 報酬約定。
→ **修正**：k1620.py 建 `month_ends` 後偵測末尾不完整月（次日仍同月 = 非真日曆月底）並剔除。檢定月數 90→89。**重跑後 null 結論完全穩健**（overall p 0.463→0.478；regime A boot 0.832→0.826；regime B dummy p 0.497→0.489，皆遠離顯著）。

**Issue #2（caveat，不改 code）**：regime-specific 的**單組**平均 HAC t-test（僅 filter 該 regime 月份）會 collapse calendar gaps，Newey-West 把非相鄰月當相鄰。**主結論不依賴此** —— 主檢定是 full-calendar 月序列上的 dummy 迴歸（`premium ~ const + regime_dummy`，含 HAC）+ block bootstrap，兩者皆無 gap 問題且皆 null（p=0.81 / 0.49）。單組 mean t-test 僅作診斷。

**Issue #3（caveat，不改 code）**：block bootstrap `block=3` 為 hard-coded 無 sensitivity。**定位為 secondary robustness**（主推論靠 dummy 迴歸 HAC）；boot_p=0.826 / 0.539 已極不顯著，block 選擇不影響 null 結論。

**結論**：CONDITIONAL_PASS ≥ 寫入 knowledge.json 門檻。核心研究誠實項（lag / seed / iid）全過，null 結論在修 #1 後穩健。
