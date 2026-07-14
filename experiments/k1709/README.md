# K1709 — Spot BTC/ETH ETF 淨流入衝擊對已實現波動率的預測力

**Verdict: NULL** — 現貨 BTC/ETH ETF 的每日淨申購/贖回金額，在 HAR-RV 基準之上**沒有**增量的樣本外波動率預測力。

| 項目 | 內容 |
|---|---|
| 期間 | BTC 2024-01-11 → 2026-07-13（642 flow obs）；ETH 2024-07-23 → 2026-07-13（504 flow obs） |
| 樣本（迴歸面板） | BTC h=1 n=621 / h=5 n=618；ETH h=1 n=483 / h=5 n=480 |
| 樣本外原點 | BTC 371（2025-01-24 起）；ETH 233（burn-in 敏感度下 283） |
| 主要檢定 | 10 個 DM 檢定，**0 個**通過 Harvey \|t\|>3 |
| 全部檢定 | 46 個 DM 檢定，1 個穿過 Harvey 且方向有利於 flow → Holm 校正後 p=0.0736，**且 Clark-West 不確認** |
| 執行 | `uv run python experiments/k1709/k1709.py`（seed=1709） |
| 測試 | `uv run --extra dev python -m pytest experiments/k1709/test_k1709.py -q` → 23 passed |

---

## 1. 研究問題與正交性宣告

**問題**：控制既有波動率動態（HAR-RV）後，spot ETF 的**每日淨流入**是否對 BTC/ETH 的 t+1 / t+5 已實現波動率仍有增量預測力？

**正交性宣告（重要）**：本研究**不是**「ETF 化改變交易時鐘 / 時段結構」那條線。那條線已有 Pastorek & Albrecht (2026) 的 ETF settlement-clock 研究覆蓋（他們用 failures-to-deliver 看結算時點的微結構效應）。本研究的 treatment 是**資金流（flow）本身**——美元計價的申購減贖回淨額——作為波動率的預測變數。兩者不重疊。

**四個假說**（各自獨立檢定、各自報告）：

| 假說 | 內容 | 結果 |
|---|---|---|
| H1 | flow shock 絕對值預測 t+1 RV 上升（大額申購/贖回都是流動性衝擊） | **NULL** |
| H2 | 負向 flow（贖回）效果不對稱地大於正向 | **NULL** |
| H3 | 週五 flow 預測週末（Sat/Sun）RV——ETF 只在美股交易日運作、BTC 24/7 | **NULL** |
| H4 | BTC ETF flow 外溢預測 ETH RV（控制 ETH 自身 flow 後） | **NULL** |

---

## 2. 資料

### 2.1 ETF 淨流入 — Farside Investors

真實的 creation/redemption 淨額（**不是**成交量代理），單位 $M。

| | BTC | ETH |
|---|---|---|
| 來源 | `farside.co.uk/bitcoin-etf-flow-all-data/` | `farside.co.uk/ethereum-etf-flow-all-data/` |
| 觀測數 | 642 | 504 |
| 期間 | 2024-01-11 → 2026-07-13 | 2024-07-23 → 2026-07-13 |
| 淨流負值佔比 | 40.0% | 47.8% |
| 淨流均值 / 標準差 | +79.6 / 341.9 $M | — |
| 淨流範圍 | −1,113.7 → +1,373.8 $M | — |

**解析陷阱（全部處理，見 `_parse_money`）**：
- **負數寫成括號**：`(95.1)` = **−95.1**（贖回）。不轉換 → 贖回被當申購 → H2 直接做廢。
- **千分位逗號**：`(27,332)` = −27332.0。
- **`-` / `–` = 無資料 → NaN，`0.0` = 真實零流入 → 0.0**。兩者不可混為一談。
- BTC 表尾 `Total` 列（各檔累計，非日期）必須丟棄。
- ETH 表是 **multi-index header**（發行商 / ticker / Fee）且有 **`Seed` 列**（種子資金，非日常 flow）→ 都丟。

**解析器自我驗證（關鍵）**：本研究**不假設**解析正確，而是機械驗證——重算「各檔基金 flow 之和」並與 Farside 自己的 `Total` 欄比對。
> **max |Total − Σfunds| = 0.0 $M**（BTC 2.3e-13、ETH 1.1e-13，浮點誤差級）

若括號/逗號/dash 有任一處理錯誤，這個殘差會立刻爆開。殘差為 0 + 負值佔比 40%/47.8%（贖回確實是負數）→ 解析正確。殘差 > $1M 時程式直接 raise，不會靜默前進。

### 2.2 價格與 RV — yfinance（BTC-USD / ETH-USD，24/7）

三個 RV 代理，**主用 Garman-Klass**：

| 代理 | 涵蓋 | 角色 |
|---|---|---|
| **Garman-Klass**（OHLC range-based） | 全樣本 1,138 日 | **主要** |
| 真實 hourly RV（24 根小時 log return 平方和） | 2024-07-15 起 722/721 日 | 穩健性 |
| r²（日 close-to-close 報酬平方） | 全樣本 | 穩健性 |

**為何 GK 是誠實的主要選擇**：日資料只有 OHLC，本研究**沒有假裝有 5 分鐘 RV**。GK 假設「無隔夜跳空」——對股票不成立，但**對 24/7 的加密貨幣正好成立**，這使 GK 在此處比在股市更合適。且 GK 與真實 hourly RV 的 log 相關達 **0.90（BTC）/ 0.90（ETH）**，代理品質有實證支撐。

**偏誤方向**：range-based 估計量在有跳躍時會低估、在微結構噪音下會高估；三個代理結論一致（見 §5.2）已涵蓋此疑慮。

---

## 3. 方法論

### 3.1 資訊集與 lookahead（最高風險）

Farside 的當日 flow 在**美股盤後（約 21:00 UTC）**才公佈。因此：

> **預測原點 = 結束 UTC 日 t 的 00:00 UTC**
> - `flow_t` 已知（21:00 UTC 公佈 < 24:00 UTC）✓
> - `RV_t`（完整 UTC 日）已知（該 UTC 日剛收完）✓
> - 目標 `RV_{t+1..t+h}` **完全在未來** ✓

實作上所有預測變數都經過一行**顯式 `.shift(pub_lag)`**（`build_panel`），且由 `assert_no_lookahead()` 從資料本身反推驗證。

**日曆對齊規則**：flow 日 t（美股交易日）→ 目標為 crypto **日曆日** t+1（h=1）或 t+1..t+5 平均（h=5）。因 BTC 24/7，週五 flow 的 t+1 自然落在**週六**——H3 正是靠這個。

**`assert_no_lookahead` 檢查兩個相反方向的失效**（這是本研究抓到真 bug 的地方）：
1. `gap < pub_lag` → **lookahead**（看見未來）
2. `gap > pub_lag` → **misalignment**：日曆有洞時 `.shift()` 是按**列位置**位移而非按**日曆日**，「t+1」會悄悄變成 t+2

原本只檢查 `gap >= 1` 的不等式**會漏掉第 2 種**——而它真的發生了（見 §6.1）。現在斷言 `gap == pub_lag` 精確相等。

### 3.2 反向因果 / 內生性

**Flow 追報酬、波動也驅動 flow**，所以只跑 `RV_{t+1} ~ flow_t` 的 OLS 是廢的。本研究實測確認這個威脅是真的：

> corr(flow_t, 同日報酬_t) = **+0.386（BTC）** / +0.217（ETH）

因此：
- **Baseline 是 HAR-RV**（RV_d / RV_w / RV_m，Corsi 2009），研究問題是「flow 在 HAR **之上**是否有增量」。
- 控制變數含同期 `ret_t`、`|ret_t|`。
- **結論強度由樣本外決定**：expanding window、QLIKE loss、Diebold-Mariano 檢定。in-sample 係數只供解讀。

### 3.3 巢狀模型 → DM **與** Clark-West 並用

HAR ⊂ HAR+flow 是**巢狀（nested）**比較，而 DM 檢定在巢狀情形下分布是非標準的。本研究因此**同時**跑：
- **DM**（canonical `volpred.stats.model_evaluation.dm_test`，HAC bandwidth = `ceil(h^(1/3)·n^(1/3))`，**不是**退化的 `h-1`）
- **Clark-West (2007)**（專為巢狀比較設計）

這一點在下面救了我們一次：唯一穿過 Harvey 的 cell 被 Clark-West 否決（§5.4）。

### 3.4 訓練列的 forward-label 約束

h=5 的目標視窗重疊。依 `.claude/rules/experiments.md` L20，訓練列必須滿足 **`target_end < forecast_origin`**——用**實際日期**強制（`y_end_date < origins[i]`），不是用 index 算術。否則訓練尾端會看見預測日之後的 realized return。

### 3.5 多重檢定

- **Harvey (2016)** 門檻：新宣稱需 **|t| > 3**。
- 主家族 10 個 DM 檢定 → Holm 校正。
- **更嚴格**：本研究另建 **full-family 校正**——把**所有 46 個** DM 檢定（主家族 + RV 代理 + 發布時差 + burn-in 敏感度 + flow 變換 + 門檻 sweep）一起 Holm 校正。理由：穩健性套件若不納入校正，就變成免費的多重比較樂透。
- 門檻**不隨便定**：主用**連續 z-score**（flow ÷ 滾動 20 flow-day 標準差，**嚴格前向**）；門檻版另做 |z| ∈ {1.0, 1.5, 2.0, 2.5} **全部報告**。
- Seed 固定 = 1709。

---

## 4. Related Work（與本研究的差異）

| 文獻 | 發現 | 與本研究的差異 |
|---|---|---|
| **Ben-David, Franzoni & Moussawi (2018)**, *J. Finance* 73(6), 2471–2535. DOI 10.1111/jofi.12727 | ETF 持股比重高的股票有顯著較高的非基本面波動；流動性衝擊經由 creation/redemption 套利機制傳導至標的 | 這是我們假說的**理論依據**（所以本假說 ex-ante 合理）。但他們是**股票橫斷面持股**效應，經由「一籃子標的」的套利傳導。Crypto 只有**單一標的**、現貨市場 24/7 且遠深於 ETF、**沒有籃子套利傳染管道**。我們的 null 很可能正是因為該管道在 crypto 不存在。 |
| **Coval & Stafford (2007)**, *JFE* 86(2), 479–512. | 基金大額進出造成機械式價格壓力（fire sales/purchases），flow-driven trades 可預測 | 價格壓力是**第一動差（level）**效應。我們問的是 flow 是否帶有**條件變異數**的增量資訊。且 spot BTC ETF 的申贖是對著極深的 24/7 市場，沒有 fire-sale 約束機制。 |
| **Warther (1995)**, *JFE* 39(2–3), 209–235. | 總體報酬與**非預期** flow 強相關，與**預期** flow 無關 | **方法論警告，我們據此加做穩健性**：若只用原始淨流，null 可能只是「用錯變換」的假象。因此我們另測 signed / squared / **gross churn** / **AR(5) 非預期成分** 四種變換（§5.3）。 |
| **Mazur & Polyzos (2025)**, *J. Alternative Investments* 27(4), 110–. SSRN 5452994 | Spot BTC ETF 淨流是 BTC **價格**的強預測子 | **最近的鄰居，也是我們貢獻的支點**。他們做的是**第一動差（價格 / 報酬）**、in-sample；我們做**第二動差（波動率）**、樣本外、有 HAR 基準與 DM/CW 巢狀檢定。**兩者合起來的訊息是：flow 看得見地推動價格，卻對波動率預測毫無貢獻。** |
| **Babalos, Bouri & Gupta (2025)**, *QREF* 102, 102006. DOI 10.1016/j.qref.2025.102006 | Spot BTC ETF **推出事件**後，BTC/XRP 波動率**下降**（stabilization hypothesis） | 他們測的是**推出當成一次性事件 dummy**（GARCH in-sample event study），不是**每日 flow 序列**。他們的 stabilization 結論與我們的 null **一致**：若 ETF 化是抑制而非激化波動，flow 的日內變異不帶邊際 RV 訊號是自洽的。 |
| **Corsi (2009)**, *J. Financial Econometrics* 7(2), 174–196. | HAR-RV：日/週/月波動率階層串聯，簡單卻能複製長記憶 | 我們的 **baseline 本體**。 |
| **Liu, Patton & Sheppard (2015)**, *J. Econometrics* 187(1), 293–311. DOI 10.1016/j.jeconom.2015.02.008 | ~400 個估計量、31 個資產、5 個資產類別：幾乎沒有東西能穩定打敗樸素的 5 分鐘 RV | **我們 null 可信度的最佳辯護**：簡單基準極難擊敗是這個文獻的常態，不是我們設計失能。 |
| **Brauneis & Sahiner (2026)**, *Asia-Pacific Financial Markets* 33(1), 379–411. DOI 10.1007/s10690-024-09510-6 | AI 產生的新聞情緒 vs HAR + ML：**「加入情緒並未改善 HAR 的預測準確度」**；且 ML 對多數幣種贏 HAR，**唯獨 Bitcoin 例外**（HAR 仍具競爭力） | **形狀完全相同的已發表 NULL**——外生、合理、動機充分的預測子在 crypto RV 上打不贏 HAR，而且**對 BTC 最難打敗**。**差異**：他們的外生變數是**軟性新聞情緒**；我們的是**硬性、機構級、美元計價的實際申贖金額**——先驗上是強得多的候選，因此我們的 null 是**更緊的拒絕**。 |
| **Pastorek & Albrecht (2026)**, MENDELU WP 109/2026. | ETF 的股票式結算時鐘疊加在 24/7 crypto 上；FTD 強度的非預期上升**並未**提高當日現貨波動 | **這就是我們正交性宣告要排除的那條線**（settlement / trading-clock 微結構）。我們研究 flow 量級作為預測子，他們研究結算時點微結構。不重疊。且他們的 null 也是佐證：ETF 管線變數是弱的波動預測子。 |

**novelty 查核**：文獻搜尋**未發現**任何論文測試我們的確切問題（ETF flow → crypto RV，控制 HAR，樣本外）。既有 spot BTC ETF flow 研究一律做**報酬 / 價格發現**；既有 ETF↔crypto 波動研究用**推出事件 dummy** 而非 flow 序列。

---

## 5. 結果

### 5.1 主要結果 — H1 / H2 全 NULL

HAR+ctrl baseline 的樣本內 R²：BTC h=1 0.202 / h=5 0.307；ETH h=1 0.180 / h=5 0.177（基準本身運作正常）。

**樣本外（QLIKE，越低越好；DM t 為負 = flow 較優；Harvey 門檻 |t|>3）**：

| 資產 | h | 規格 | n_oos | QLIKE base → +flow | 改善 | DM t | Clark-West t |
|---|---|---|---|---|---|---|---|
| BTC | 1 | H1 \|flow\| | 371 | 0.5448 → 0.5449 | **−0.01%** | 0.048 | −1.681 |
| BTC | 1 | H2 asym | 371 | 0.5448 → 0.5457 | **−0.17%** | 0.330 | 0.122 |
| BTC | 5 | H1 \|flow\| | 368 | 0.2533 → 0.2536 | **−0.10%** | 0.159 | 1.128 |
| BTC | 5 | H2 asym | 368 | 0.2533 → 0.2562 | **−1.15%** | 2.193 | 0.574 |
| ETH | 1 | H1 \|flow\| | 233 | 0.5218 → 0.5237 | **−0.36%** | 0.521 | −0.245 |
| ETH | 1 | H2 asym | 233 | 0.5218 → 0.5239 | **−0.40%** | 0.537 | −0.873 |
| ETH | 5 | H1 \|flow\| | 230 | 0.2733 → 0.2730 | +0.08% | −0.162 | −0.191 |
| ETH | 5 | H2 asym | 230 | 0.2733 → 0.2736 | **−0.12%** | 0.233 | −0.470 |

**加入 flow 幾乎一律讓 QLIKE 變差**（8 個中 7 個惡化）。樣本內 |t| 從未超過 1.6，且**符號隨 horizon 反轉**（BTC h=1 為 −0.488、h=5 為 +0.484）——這是雜訊的特徵，不是被壓抑的訊號。

**H3（週末缺口）**：週五 flow → 週末 RV。BTC n=123 個週五，|z| 係數 t=**−0.279**；ETH n=95，t=**+0.287**。NULL。

**H4（BTC→ETH 外溢）**：控制 ETH 自身 flow 後，BTC flow 對 ETH RV：樣本內 t=−0.131（h=1）/ −0.406（h=5）；樣本外 DM t=−0.417 / +1.407。NULL。

### 5.2 RV 代理穩健性

| 資產 | 代理 | DM t |
|---|---|---|
| BTC | Parkinson | 0.455 |
| BTC | r² | −0.517 |
| BTC | **hourly 真實 RV** | 0.570 |
| ETH | Parkinson | 0.787 |
| ETH | r² | **−3.192** ← 見 §5.4 |
| ETH | **hourly 真實 RV** | 0.733 |

### 5.3 Flow 變換穩健性（Warther 1995）

**這一節是 null 的關鍵防線**：若 flow 真帶波動資訊，它至少該在四種變換之一現身。

| 變換 | BTC DM t | ETH DM t |
|---|---|---|
| signed z（有方向） | −0.274 | 0.364 |
| squared z（凸性） | 0.933 | −0.420 |
| **gross churn**（Σ\|各檔 flow\|，對淨額相消免疫） | 0.065 | −0.272 |
| **unexpected z**（AR(5) 殘差，非預期成分） | −0.863 | 1.123 |

**0/8 通過**，最大 |DM t| = 1.12。→ 這個 null 是關於**資料**的陳述，不是關於我們選了哪個變換。

### 5.4 唯一的異常 cell — 誠實處理

**46 個 DM 檢定中有 1 個穿過 Harvey 且方向有利於 flow**：`ETH / h=1 / r² 代理`，DM t = **−3.192**。

一份不誠實的報告會把它拉去當標題。實際上它是**假陽性**，有三個獨立理由：

1. **Clark-West（巢狀模型的正確檢定）不確認**：同一 cell 的 CW t = **1.378**（遠低於門檻）。DM 在巢狀比較下分布非標準——這正是我們兩個都跑的原因。
2. **同資產同 horizon 的兩個「更好」代理指向相反方向**：GK t=+0.787、hourly 真實 RV t=+0.733（都偏向 baseline）。**只有最吵的代理翻掉**——r² 的 QLIKE 水準是 2.97，對比 hourly RV 的 0.39（約 7 倍雜訊；r² 是 χ²(1) 代理，安靜日會逼近零而讓 QLIKE 的 −log 項爆開）。
3. **多重檢定**：全家族 46 個檢定的 **Holm 校正後 p = 0.0736 > 0.05**。

→ **不改變 NULL 判定。** 完整記錄在 `k1709_results.json` 的 `full_family_multiple_testing.discrepant_cells`。

### 5.5 其他穩健性

- **發布時差 T+1（保守）**：假設 flow_t 要到 t+1 日終才可用 → 4 個檢定，DM t ∈ [−0.248, 1.202]。NULL。
- **門檻 sweep**：|z| ≥ {1.0, 1.5, 2.0, 2.5} × 2 資產 × 2 horizon = 16 個檢定，**0 個**通過 Harvey。
- **ETH burn-in 敏感度**：主規格（INITIAL_TRAIN=250）只給 ETH 233 個樣本外原點，低於 preamble 的 252 日門檻。改用 200 → 樣本外 283/280 個原點（**達標**），DM t = 0.612 / −1.136，**判定不變**。

### 5.6 樣本外涵蓋空頭（非只在多頭測）

樣本外自 **2025-01-24** 起，涵蓋：

| | 樣本外最大回撤 | 最糟單日 | 回撤 ≤ −20% 的天數 |
|---|---|---|---|
| BTC | **−53.06%** | −15.23% | 279 |
| ETH | **−67.61%** | −16.27% | 430 |

這是一個貨真價實的空頭市場，不是只在多頭區間測試。

---

## 6. 這個 NULL 為什麼可信（而不是 bug）

一個壞掉的 merge、錯位的 shift、或死掉的迴歸子，都會產生**和市場效率長得一模一樣的 null**。因此我們機械驗證：

### 6.1 我們真的抓到並修掉了一個對齊 bug

Codex 對抗性審查發現：yfinance 的日資料**缺了 2026-07-13**，且**包含當天還沒收完的 partial bar**。後果嚴重——`.shift(1)` 是按**列位置**位移，不是按**日曆日**；一旦日曆有洞，「t+1」目標會悄悄變成 **t+2**，而原本 `gap >= 1` 的不等式斷言**看不出來**。

**結構性修正（不是 patch）**：
1. 丟掉尚未收完的當前 UTC 日（partial bar 的 High/Low 還沒張開完 → 系統性低估 GK 變異數）。
2. RV 重新索引到**完整日曆**——缺失日變 NaN 並自然退出面板，而不是壓縮時間軸。
3. 斷言收緊為 **`gap == pub_lag` 精確相等**，把靜默錯位變成大聲失敗。

修正後判定**不變**（NULL），但這個 bug 本來就該被抓到，而不是被平均掉。

### 6.2 Power test — 管線能不能找到真的存在的訊號？

`test_power_injected_signal_is_detected`：**植入**一條真正驅動次日 RV 的合成 flow（log RV_{t+1} = 持續性基底 + 1.2·|z_t|），要求管線把它找回來。

> 結果：**DM t < −3.0、QLIKE 改善 > 0、Clark-West t > 1.645** → **成功復原**

若 merge、`.shift(1)`、樣本外切分或 DM 符號慣例有任何一項錯誤，這條植入訊號會被摧毀——而那正是同時會偽造出 null 的失效模式。

### 6.3 Placebo test — 管線會不會無中生有？

`test_placebo_scrambled_flow_is_not_detected`：同一套機器餵入純雜訊 flow → 要求 **|DM t| < 3**。通過。

### 6.4 其他機械驗證

- **解析器交叉驗證**：max |Total − Σfunds| = **0.0**（見 §2.1）。
- **突變測試**：把 AR(5) 的 lag 向量反轉 → `test_unexpected_flow_ar5_lag_ordering` **確實失敗**（測試有牙齒，不是裝飾）。
- **測試套件**：23 passed（解析陷阱 / z-score 嚴格前向 / 日曆對齊 / h=5 目標視窗 / power / placebo）。

> **結論：這個管線可證明地「找得到真訊號」且「不會無中生有」。因此 NULL 是關於資料的陳述。**

---

## 7. 結論（強度不超過證據）

**現貨 BTC/ETH ETF 的每日淨申購/贖回金額，在 HAR-RV 之上沒有可偵測的樣本外增量波動率預測力。**

這個結論在以下維度**一致成立**：2 個資產 × 2 個 horizon × 4 個假說 × 3 種 RV 代理 × 4 種 flow 變換 × 4 個門檻 × 2 種發布時差假設 = 46 個 DM 檢定，**0 個**在多重檢定校正後存活。

**如何解讀（機制）**：ETF flow 是**已經發生的交易**——當淨額被公佈時，市場已經吸收了它的價格衝擊。與 Mazur & Polyzos (2025) 併讀，訊息是清楚的：**flow 看得見地推動價格（第一動差），卻對波動率預測毫無貢獻（第二動差）**。這與 Ben-Rephael et al. (2012)「flow 是情緒/雜訊而非資訊」以及 Babalos et al. (2025) 的 stabilization 發現一致。

**這個結論不宣稱**：
- ✗ 不宣稱 ETF flow 對**報酬 / 價格**沒有預測力（我們沒測；文獻說有）。
- ✗ 不宣稱 ETF 化對 crypto 波動**結構**沒有影響（那是另一條線，見正交性宣告）。
- ✗ 不宣稱在**日內**頻率上 flow 無資訊（我們是日頻）。
- ✗ 不宣稱在**其他資產類別**（如股票 ETF）也成立。

---

## 8. 限制

1. **ETH 面板 n=483 < 500**（原始 flow 504 obs，扣掉 20 日 z-score burn-in 與目標日）。ETH 的結論強度弱於 BTC。BTC n=621 達標。
2. **RV 是日頻代理，不是 5 分鐘 RV**。我們**沒有假裝**有 5 分鐘資料。GK 與真實 hourly RV 相關 0.90，且三代理結論一致，但 range-based 估計量在跳躍下低估、在微結構噪音下高估。
3. **Hourly 真實 RV 只涵蓋 2024-07-15 起**（yfinance 1h 上限 730 天），BTC 樣本外僅 177 個原點。
4. **Farside 的公佈時點是推斷的**（美股盤後）。我們用保守的 T+1 穩健性檢定涵蓋此不確定性，結論不變。
5. **樣本期僅約 2.5 年**（spot ETF 2024-01 才存在），涵蓋一次完整多空循環但只有一次。
6. **NULL 不等於「效果為零」**，只等於「在此樣本、此頻率、此基準下偵測不到」。以本樣本規模，微小效果仍可能存在但無法辨識。

---

## 9. 檔案

| 檔案 | 內容 |
|---|---|
| `k1709.py` | 完整可重跑腳本（seed=1709，含資料診斷輸出、原子寫入 JSON） |
| `k1709_results.json` | 全部結果（`data_diagnostics` / 各假說係數與 t / OOS QLIKE / DM / CW / 門檻 sweep / flow 變換 / full-family 多重檢定 / `verdict`） |
| `test_k1709.py` | 23 個 regression gate（含 power / placebo / 日曆缺口 / 解析陷阱） |
| `fig1_flow_vs_rv.png` | flow 時序 + GK 波動率疊圖（BTC / ETH） |
| `fig2_event_window.png` | 大額 flow shock 前後 ±5 日的平均 log-RV path |
| `fig3_oos_qlike.png` | HAR vs HAR+flow 的樣本外 QLIKE 比較（標 DM t） |
| `fig4_threshold_sensitivity.png` | 門檻 sweep 的 DM t heatmap |

**重跑**：
```bash
uv run python experiments/k1709/k1709.py
uv run --extra dev python -m pytest experiments/k1709/test_k1709.py -q
```
