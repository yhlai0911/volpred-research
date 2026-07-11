# K1025: Crypto Fear Channel — BTC Vol Spillover to Equity

> **v3 (2026-07-12) 是 canonical。`k1025_v2_results.json` 與 `k1025_results.json` 的所有
> Diebold-Yilmaz 數字 SUPERSEDED — 它們建立在一個 FEVD 取軸 bug 上（見 §v3）。
> 兩份舊 JSON 依「永遠修流程，不修資料」原則原地保留，未手改。**

## 動機

Paper 10（crypto-fear-channel）核心實證素材。K639 確認 BTC→SPY Granger causality，
K746b 確認 BTC vol asymmetrically Granger-cause VIX。本實驗提供完整溢出效應框架。

---

# v3 — FEVD 修正重跑（2026-07-12）

## 為什麼要 v3：v2 的致命 bug

`k1025_v2.py:366-368`：

```python
decomp = fevd.decomp          # 註解寫 (horizon, n_vars, n_vars)
spillover_matrix = decomp[-1] # 以為取 h=10 的 FEVD 矩陣
```

statsmodels 的 `FEVD.decomp` 實際 shape 是 **`(n_vars, horizon, n_vars)`**
（axis 0 = 被分解的變數 i、axis 1 = horizon 步、axis 2 = 衝擊來源 j；
本次實測 statsmodels 0.14.6 `decomp.sum(axis=2) == 1` 驗證軸序）。

所以 `decomp[-1]` 取到的是**最後一個變數（VIX）跨 horizon 的 `(horizon, n)` 表**，
下游把前 3 列當成 3×3 矩陣讀 —— **horizon 步被當成資產**。

**這個失敗是安靜的**：陣列仍是 2-D、算術照跑、輸出仍像百分比。而且誤切後的「對角線」
不再是自身變異，幾乎所有質量都落到 off-diagonal，於是指數天生就高且不動 ——
v2 的 total spillover 90.11% 幾乎是個數學恆等式。**同一段公式餵 iid 高斯雜訊也算得出
~67%**（本次實測，見 `scripts/tests/test_fevd_shape.py`）。

論文 §5.3 / §6.1（全文唯一的 robustness 節）整段建立在這個假數字上。

### 一個附帶發現：v2 的 90.11% 根本不可復現

用 v2 **自己的設定**（一階差分、252d rolling、step 5、maxlags=5、同一個誤切）
在 pinned snapshot 上重跑，得到的是 **67.63%（sd=1.28，512 windows）**，不是 90.11%。
差距來自 v2 從 **live yfinance 抓資料且未 pin snapshot**（`auto_adjust=True`，SPY 用 simple return）。

也就是說：**v2 的旗艦數字連「帶著自己的 bug」都復現不出來** —— 這本身就是 data-pinning
不是可選項的證據。v3 只讀 `paper/crypto-fear-channel/data/spy_btc_usd_vix_2015-2026.csv`，
禁 live fetch。

### 第二個 bug：週一被系統性刪掉（在審查者的診斷腳本裡）

深審附的 `dy_corrected_diagnostic.py` 用 `df["spy_adj_close"].pct_change().dropna()`。
snapshot 是 **calendar index**（BTC 天天有價、SPY/VIX 只有交易日 → 週末列是 NaN）。
在這種 index 上直接 `pct_change()`，**週一的前一個 calendar 列是週日 = NaN → 週一報酬 = NaN**，
接著 `dropna()` 就把週一幾乎砍光。

實測（pandas 3.0.1、本 snapshot）：**543 個週一 → 只剩 12 個**，SPY 報酬 2,904 → 2,285 列。
~19% 樣本損失，而且**集中在唯一承載週末新聞的那個交易日**。

v3 的 `build_panel()` 因此**先對價格 dropna，再取報酬**。

## v3 的修正清單

| # | v2 | v3 |
|---|---|---|
| 1 | `decomp[-1]`（取到變數軸） | `decomp[:, -1, :]` + shape assert |
| 2 | 只有 Cholesky FEVD（order-dependent） | **KPPS generalized FEVD 為主**（order-invariant）+ 兩種 Cholesky 排序當 sensitivity |
| 3 | live yfinance fetch（`auto_adjust=True`） | **pinned snapshot CSV**（`auto_adjust=False` → `*_adj_close`），禁 live fetch |
| 4 | SPY simple return + BTC log return（混用） | **兩者皆 log return** |
| 5 | calendar-index 上 `pct_change()` → 刪掉 95% 的週一 | 先 dropna 價格再取 log return |
| 6 | VAR lag grid `maxlags=5` | **`maxlags=22`**（AIC 選；並報 lag sensitivity） |
| 7 | QR 無控制變數 + iid bootstrap | **加 lagged-VIX 控制**（quantile-Granger）+ **moving-block bootstrap** |
| 8 | DM 未報 HAC bandwidth；巢狀比較只用 raw DM | canonical `volpred.stats.dm_test`（HAC）+ **Clark-West**（巢狀模型必需） |
| 9 | `from_btc` / `to_btc` 標籤互換 | row = FROM（接收）、col = TO（傳遞），NET = TO − FROM |

## 數據

- **來源**：`paper/crypto-fear-channel/data/spy_btc_usd_vix_2015-2026.csv`（pinned，`auto_adjust=False`）
- **期間**：2015-02-02 ~ 2026-04-08，**N = 2,812**（與論文一致）
- **變數**：BTC_RV(20)、SPY_RV(20)（皆 log return，年化 ×√252）、VIX level
- **ADF**：三序列皆在 1% 下拒絕單根（BTC_RV −5.07 / SPY_RV −5.53 / VIX −5.71）→ VAR 用 levels
- **Seed**：42（bootstrap 與所有抽樣）

## 主要結果

### 1. Total connectedness：90.11% → 24.48%（修正前後）

| 估計式 | Total connectedness | BTC net (TO − FROM) |
|---|---|---|
| **Generalized KPPS（主結果）** | **24.48%** | **−4.96pp（net receiver）** |
| Cholesky {BTC, SPY, VIX} | 17.02% | **+6.79pp（net transmitter）** |
| Cholesky {VIX, SPY, BTC} | 23.33% | **−10.28pp（net receiver）** |
| *v2 誤切（同一個 VAR fit）* | *66.76%* | *—* |
| *v2 論文報告值* | *90.11%* | *−76.89pp* |

Lag sensitivity（generalized）：lag 1 → 21.1%、lag 2 → 19.3%、lag 5 → **19.5%**、
lag 10 → 20.0%、lag 22 (AIC) → 24.5%。BTC net 在**所有** lag 都是負的（−0.95 ~ −4.96pp）。

> 深審預期的 18–22% 落在 lag ≤ 10 的區間（lag 5 = 19.5%）；AIC 在 maxlags=22 選到 22
> 把它推到 24.5%。**兩者都如實報告，沒有挑對自己有利的那個。**

其他 robustness：一階差分 15.20%、calendar alignment 23.99%、paper window（= 全樣本）24.48%。

### 2. Cholesky 排序會讓 BTC net 的**正負號翻轉** — 這是本次最重要的方法論發現

- 全樣本：{BTC,SPY,VIX} → **+6.79pp（傳遞者）**；{VIX,SPY,BTC} → **−10.28pp（接收者）**。
  **同一份資料、同一個 horizon，只換排序，結論相反。** 淨額擺盪 17.07pp。
- Rolling 523 個窗口：兩種 Cholesky 排序對 BTC net **符號只有 48.4% 一致** —— **比丟銅板還差。**
- Generalized FEVD 的 total connectedness 在變數重排下位移 **0.000pp**（order-invariant by construction）。

→ **任何建立在 Cholesky 上的 net-direction claim 都沒有證據力。** 論文的方向性敘事
必須（且現在確實）由 generalized FEVD 承擔。

### 3. 修正後的故事其實更好：連動性是**時變**的

| | Generalized total connectedness |
|---|---|
| 平靜期（2017–2019）平均 | **20.77%** |
| COVID（2020-02 ~ 06）平均 | **38.19%** |
| 全期 rolling 平均 | 23.27%（sd 9.11） |
| 全期最低 / 最高 | 6.48% / **50.75%（2020-11-24）** |

v2 那個 90% 的假指數**在危機與平靜期幾乎不動**（誤切後天生就黏在高檔）——
「危機與平靜一樣連動」這個賣點本身就是 artifact。修正後 COVID 期間連動性
**接近平靜期的兩倍**，這才是真正可寫的故事。

### 4. BTC 淨方向：net receiver，但幅度只有 v2 宣稱的 1/15

- Generalized 全樣本 net = **−4.96pp**（接收者），rolling 523 窗口中 **69.2%** 為淨接收者。
- v2 宣稱 −76.89pp → 修正後 −4.96pp。**方向（接收者）存活，量級崩掉 15 倍。**
- Generalized FEVD 表顯示 BTC_RV 的預測誤差變異 **88.1% 來自自身**（VIX 只解釋 8.7%），
  而 SPY_RV **44.0% 來自 VIX** 的衝擊 —— 真正的 hub 是 VIX↔SPY，BTC 大體上是**外圍、自成一格**的資產。

### 5. QR sign reversal：**加控制後陣亡**（null result）

VIX_t ~ BTC_RV_{t−1}（+ VIX_{t−1}）；moving-block bootstrap（B=500、block=15=⌈n^(1/3)⌉、seed 42）：

| τ | 無控制 β [95% CI] | **加 VIX_{t−1} 控制 β [95% CI]** |
|---|---|---|
| 0.05 | −2.81 [−3.80, −1.93] **SIG** | −0.33 [−0.62, −0.02] SIG |
| 0.25 | −1.51 [−3.82, +1.99] ns | −0.20 [−0.33, −0.03] SIG |
| 0.50 | +2.59 [−0.72, +7.47] ns | −0.18 [−0.31, −0.06] SIG |
| 0.75 | +8.23 [+1.35, +14.95] **SIG** | −0.02 [−0.22, +0.23] **ns** |
| 0.95 | +16.29 [+0.34, +24.38] **SIG** | **+0.42 [−0.64, +1.11] ns** |

**判定：sign reversal 不存活。** 控制 VIX 自身持續性後：

- 右尾（τ=0.95）的 β 從 +16.29 掉到 **+0.42 且不顯著** —— 論文的
  「β(0.95)/β(0.50) = 8.5 倍尾部放大」**整個消失**。
- 殘存的是一個**小而一致為負**的偏效應（τ=0.05/0.25/0.50 皆顯著負），
  與原本的「高 VIX 時 BTC 波動放大恐慌」敘事**方向相反**。
- 原本的 β 大部分是在撿 VIX 自身的 persistence（BTC_RV 與 VIX level 同向共動），
  不是 BTC → VIX 的增量資訊。

### 6. OOS 預測：null 確認，且這次站得住腳

AR(p) vs AR(p) + BTC_RV_{t−1}，IS ≤ 2018-12-31、OOS ≥ 2019-01-01、rolling 756、AIC 選 p=22。

| 子期間 | n | ΔMSE | acf₁(d) | HAC lag | DM t | **Clark-West t** |
|---|---|---|---|---|---|---|
| full OOS | 1,826 | −0.11% | −0.153 | 13 | −0.48 | +0.52 |
| 2019 | 252 | −0.04% | +0.215 | 7 | −0.81 | −0.75 |
| 2020 (COVID) | 253 | +0.27% | −0.196 | 7 | +0.53 | +0.85 |
| 2021–2022 | 503 | −0.27% | +0.053 | 8 | −0.50 | +0.56 |
| 2023–2026 | 818 | −0.47% | +0.008 | 10 | −2.36 | −2.02 |

- HAC bandwidth = `max(h−1, ⌈h^(1/3)·n^(1/3)⌉)`，用 canonical `volpred.stats.model_evaluation.dm_test`。
  腳本內有 runtime assert 釘死自寫 HAC 與 canonical 數值一致（見 `hac_tstat`）。
- **巢狀模型必須報 Clark-West**（`docs/error_log.md` 2026-07-11 / K1681：AR+BTC 是 AR 的巢狀擴張，
  raw DM 在虛無假設下系統性懲罰大模型，用它「證明沒有預測力」是把偏誤當證據）。
  這次 **CW 也全數不顯著**（full OOS +0.52，遠低於單尾 5% 的 1.645）——
  所以「BTC_RV 對 VIX 沒有增量預測資訊」的 null **不是 raw-DM 偏誤造成的假象，是真的**。
- **loss differential 的 acf₁ = −0.153（負值）**。依 `.claude/rules/experiments.md`：負自協方差會**縮小**
  標準誤，補 HAC 後 |t| 會**變大**（不是變小）。實測 bandwidth 0 → |t|=0.29，13 → 0.48，30 → 0.57。
  即使用最寬的 bandwidth 也遠低於 Harvey |t| > 3.0。結論不因 bandwidth 選擇而變。

## 機械 gate

`scripts/tests/test_fevd_shape.py`（**擴充既有檔，未新開第二層** — 見下方「與 brief 的偏離」）：

- iid 高斯雜訊 3 變數 VAR 餵進 **k1025_v3 出貨的** `generalized_fevd` / `cholesky_fevd` /
  `connectedness` → total connectedness 必須 < 15%（實測 ~0.4%）。
- 非空過守衛：刻意連通的 BTC→SPY→VIX chain 必須 > 20%。
- **KPPS order-invariance**：變數重排後 total 與 net 必須逐位一致（1e-8）；
  同一測試的鑑別半邊要求 **Cholesky 必須真的移動**（相關 innovation DGP 下 net 擺盪 ~91pp），
  否則 invariance 測試是空過的。
- **解析錨點**：residual covariance 對角時 KPPS 必須等於 Cholesky。
- AST clean-tree 掃描 `.decomp[-1]`；v3 為了量化 v2 的錯誤而**故意**重現 bug 的那一行
  以 `# fevd-bug-reproduction:` 標記豁免，並有另一個測試確保這個豁免標記
  **只出現在 k1025_v3.py**（不得用來把誤切數字偷渡回 production）。

`uv run --extra dev python -m pytest scripts/tests/test_fevd_shape.py scripts/tests/test_dm_hac_lag_ratchet.py -q`
→ **24 passed**。

## 與任務 brief 的偏離（一項，刻意）

Brief 要求新建 `scripts/tests/test_fevd_iid_placebo.py`。**沒有照做** ——
`scripts/tests/test_fevd_shape.py` 在同一天（2026-07-11）已因 k865 的同一個 bug 建立，
其 docstring 與 `docs/error_log.md` 都明寫：

> 「機械 gate（**唯一 enforcement owner，anti-stacking 勿再加第二層**）」
> "Per anti-stacking this is the single enforcement owner for the FEVD axis-order concern.
> **Do not add a second watchdog -- extend this file.**"

新建一個 placebo 檔會是同一個 concern 的第二個 watchdog，直接違反 CLAUDE.md 的
anti-stacking 條款。因此把 brief 要求的 placebo（**加強版**：測 v3 出貨的函式本體、
涵蓋既有 gate 完全沒碰的 KPPS generalized 路徑與 order-invariance）**收編進既有 owner 檔**。
保護力嚴格大於獨立新檔，且維持一個 concern 一個 owner。

## 對 crypto-fear-channel 論文的意涵

| 支柱 | 判定 |
|---|---|
| §5.3 / §6.1 Diebold-Yilmaz（90.11% total、−76.89 net） | **全數作廢**，須以 generalized FEVD 重寫（24.48% / −4.96pp） |
| 「BTC 是 fear amplifier 不是 originator」（淨接收者） | **方向存活**（generalized −4.96pp、69.2% 窗口為接收者），但量級縮 15 倍，且**不能**用 Cholesky 佐證（符號隨排序翻轉） |
| QR 尾部放大 8.5 倍（sign reversal） | **陣亡**。控制 lagged VIX 後右尾 β = +0.42 (ns)；殘存的是小而負的偏效應 |
| 非對稱 Granger（跌 > 漲） | 未受本次 bug 影響（不經 FEVD），維持有效 |
| OOS 預測 null | **更強**：raw DM 與 Clark-West **雙雙**不顯著 → null 不是巢狀偏誤的假象 |
| **新增可寫素材** | 連動性**時變**（COVID 38.2% vs 平靜 20.8%）；VIX↔SPY 才是 hub，BTC_RV 88.1% 變異來自自身 |

**總評**：論文骨架仍在，但**兩根支柱各斷一根半**。原本的「crypto fear channel」= 
「BTC 波動在尾部放大股市恐慌」這個因果放大敘事，在加控制後**沒有證據支撐**。
可救的方向是把論文重新定位成 **時變連動性 + BTC 的外圍性（peripheral asset）**：
BTC 大體自成一格（88.1% own-variance），只在危機期被拉進系統（COVID 連動性翻倍），
且始終是淨接收者而非傳遞者 —— 這是個**誠實、可防守、且與 K7/K356 的 SPY-hub 前作一致**的故事，
但它比原稿的宣稱**弱得多**，需要重新評估目標期刊（JIMFIM → 可能得降到 FRL 短文）。

## 局限性

- **AIC 在 maxlags=22 選到邊界值 22**；把 grid 放寬到 30/40 時 AIC 收在 **lag 25**（BIC/HQIC 皆 21）。
  Lag sensitivity 顯示 total 在 19–25% 間、BTC net 恆負，結論不因此改變，但 grid 是**接近 binding** 的。
- Rolling window 用 `maxlags=5`（非 22）：200 obs 的窗口配 22 lags → 每方程 67 參數，
  過度配適不可行。這是**刻意的 deviation**，已記錄。
- RV(20) 是粗糙的波動率代理（未用高頻 RV）。
- BTC 週末報酬在 primary alignment 下被折進週一（Fri→Mon），與 SPY 同慣例；
  v2 的 calendar alignment（丟掉週末）當 robustness，結果差異 < 0.5pp。
- 三變數系統；未納入 DXY / 利率 / 其他 crypto，遺漏變數可能吸收部分連動性。
- Generalized FEVD 的 row normalization 是 DY(2012) 標準做法，但 KPPS 的 shock 非正交，
  「淨傳遞」的結構性因果解讀仍需審慎（這是 GFEVD 的已知代價，換來 order-invariance）。

## 檔案

- `k1025_v3.py` — **canonical** 實驗腳本
- `k1025_v3_results.json` — 結構化結果（含 generalized FEVD 矩陣、兩種 Cholesky sensitivity、
  rolling 523 窗口序列、QR 兩規格 + bootstrap CI、subsample DM + CW + HAC lag）
- `k1025_v3_results.png` — 六格圖表
- `k1025_v2.py` / `k1025_v2_results.json` — **SUPERSEDED**（FEVD bug；JSON 原地保留未改）
- `k1025.py` / `k1025_results.json` — **SUPERSEDED**（同 bug）

## 參考文獻

- Diebold & Yilmaz (2012) — Better to Give than to Receive: Predictive Directional Measurement of Volatility Spillovers
- Koop, Pesaran & Potter (1996) — Impulse Response Analysis in Nonlinear Multivariate Models
- Pesaran & Shin (1998) — Generalized Impulse Response Analysis in Linear Multivariate Models
- Clark & West (2007) — Approximately Normal Tests for Equal Predictive Accuracy in Nested Models
- Künsch (1989) — The Jackknife and the Bootstrap for General Stationary Observations
- Koenker & Bassett (1978) — Regression Quantiles
- Harvey, Leybourne & Newbold (2016) — Testing threshold

---

# v2 (2026-05-22) — SUPERSEDED

> **v2 的 Diebold-Yilmaz 結果全數作廢**（FEVD 取軸 bug，見 §v3）。
> QR 結果亦已被 v3 推翻（加控制後 sign reversal 陣亡）。
> 以下保留原始記錄供追溯。

Independent Codex/GPT-5.4 review（`review_history/v5_independent/`）發現 3 個 BLOCKING，v2 修正：

1. **BLOCKING 1 — QR predictor lag**：BTC_RV_t（同日）→ BTC_RV_{t−1}（lagged）+ 1000 次 bootstrap。
   *（v3 註：bootstrap 是 iid resample，對持續性序列會低估 SE → v3 改 moving-block。）*
2. **BLOCKING 2 — Granger lag selection**：min-p-value → VAR-AIC（maxlags=5）+ Bonferroni。
3. **BLOCKING 3 — OOS split**：IS/OOS overlap 修正（'2018-12-31' / '2019-01-01'），rolling 756。
4. **MAJOR 3 — Log returns**：BTC 改 log return。*（v3 註：SPY 仍是 simple return，v2 未統一。）*

v1 原始結論（Granger / 非對稱性 / EWMA correlation / 結構性變化）見 git history。
其中**非對稱 Granger**（BTC 下跌波動 → VIX 顯著、上漲不顯著）與 **EWMA 危機相關性上升**
不經 FEVD，未受 bug 影響。
