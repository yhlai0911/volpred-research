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

### 一個附帶發現：v2 的 90.11% 無法由 pinned 版本重現

在 v3 的 pinned panel 與同一個 full-sample VAR fit 上故意重現誤切，得到 **66.79%**，
不是舊稿的 90.11%。這不能單獨識別差距究竟來自 live-data vintage、混用 simple/log return，
或其他舊流程漂移；但足以證明 90.11% 沒有可重現的 pinned 證據鏈。v3 因此只讀
`paper/crypto-fear-channel/data/spy_btc_usd_vix_2015-2026.csv`，禁 live fetch。

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
| 6 | FEVD VAR `maxlags=5`；OOS AR grid 到 10 | FEVD VAR 保留 paper 預設 `maxlags=5`；OOS AR grid 延到 22，且候選用共同 `hold_back=22` 比 AIC |
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

### 1. Total connectedness：90.11% → 19.52%（修正前後）

| 估計式 | Total connectedness | BTC net (TO − FROM) |
|---|---|---|
| **Generalized KPPS（主結果）** | **19.52%** | **−0.95pp（近中性、略偏 receiver）** |
| Cholesky {BTC, SPY, VIX} | 12.57% | **+10.55pp（net transmitter）** |
| Cholesky {VIX, SPY, BTC} | 16.69% | **−8.11pp（net receiver）** |
| *v2 誤切（同一個 VAR fit）* | *66.79%* | *—* |
| *v2 論文報告值* | *90.11%* | *−76.89pp* |

Lag sensitivity（generalized）：lag 1 → 21.1%、lag 2 → 19.3%、lag 5 → **19.5%**、
lag 10 → 20.0%、lag 22 → 24.5%。主規格保留 brief 與 paper 的 VAR `maxlags=5`；
「AR grid 延到 22」只適用 OOS AutoReg，不得偷換 FEVD 規格。levels VAR 的 BTC net 在所有 lag
皆為負（−0.95 ~ −4.96pp）。

其他 robustness：一階差分 11.09%（BTC net **+1.92pp，方向翻正**）、calendar alignment 19.37%、
paper window（= 全樣本）19.52%。因此 BTC 淨方向對 lag/alignment 穩健，但對 levels/differences
轉換不穩健，不宜下結構性方向宣稱。

### 2. Cholesky 排序會讓 BTC net 的**正負號翻轉** — 這是本次最重要的方法論發現

- 全樣本：{BTC,SPY,VIX} → **+10.55pp（傳遞者）**；{VIX,SPY,BTC} → **−8.11pp（接收者）**。
  **同一份資料、同一個 horizon，只換排序，結論相反。** 淨額擺盪 18.66pp。
- Rolling 512 個窗口：兩種 Cholesky 排序對 BTC net **符號只有 43.8% 一致**。
- Generalized FEVD 的 total connectedness 在變數重排下位移 **0.000pp**（order-invariant by construction）。

→ **任何建立在 Cholesky 上的 net-direction claim 都沒有證據力。** Generalized FEVD 解決排序
問題，但主結果只有 −0.95pp、且一階差分會翻號；它也不能救回原稿的強方向敘事。

### 3. 修正後的故事其實更好：連動性是**時變**的

| | Generalized total connectedness |
|---|---|
| 平靜期（2017–2019）平均 | **20.76%** |
| COVID（2020-02 ~ 06）平均 | **36.16%** |
| 全期 rolling 平均 | 22.75%（sd 8.79） |
| 全期最低 / 最高 | 6.29% / **47.02%（2021-02-24）** |

v2 那個 90% 的假指數**在危機與平靜期幾乎不動**（誤切後天生就黏在高檔）——
「危機與平靜一樣連動」這個賣點本身就是 artifact。修正後 COVID 期間連動性約為
平靜期的 1.74 倍；全期峰值則落在 2021-02-24，不能把峰值誤寫成 COVID 視窗內。

### 4. BTC 淨方向：全樣本近中性，不能再支撐強方向敘事

- Generalized 全樣本 net = **−0.95pp**，rolling 512 窗口中 **72.5%** 為淨接收者；這是
  「多數窗口偏 receiver」，不是「始終 receiver」。
- v2 宣稱 −76.89pp → 修正後 −0.95pp，量級幾乎消失；一階差分 robustness 更翻成 +1.92pp。
- Generalized FEVD 表顯示 BTC_RV 的預測誤差變異 **89.3% 來自自身**（VIX 解釋 6.2%），
  SPY_RV 則有 **30.2% 來自 VIX** 衝擊。可防守的描述是 BTC 大致處於系統外圍，
  不是把極小的 net 值包裝成穩固的因果方向。

### 5. QR sign reversal：**加控制後陣亡**（null result）

VIX_t ~ BTC_RV_{t−1}（+ VIX_{t−1}）；moving-block bootstrap（B=1,000、block=15=⌈n^(1/3)⌉、seed 42；
未收斂 draw 明確排除，各分位成功率 99.7%–100%）：

| τ | 無控制 β [95% CI] | **加 VIX_{t−1} 控制 β [95% CI]** |
|---|---|---|
| 0.05 | −2.81 [−3.85, −1.93] **SIG** | −0.33 [−0.63, −0.02] SIG |
| 0.25 | −1.51 [−3.75, +2.08] ns | −0.20 [−0.33, −0.03] SIG |
| 0.50 | +2.59 [−0.80, +7.43] ns | −0.18 [−0.31, −0.07] SIG |
| 0.75 | +8.23 [+1.76, +14.89] **SIG** | −0.02 [−0.21, +0.23] **ns** |
| 0.95 | +16.29 [+0.76, +24.69] **SIG** | **+0.42 [−0.61, +1.14] ns** |

**判定：sign reversal 不存活。** 控制 VIX 自身持續性後：

- 右尾（τ=0.95）的 β 從 +16.29 掉到 **+0.42 且不顯著** —— 論文的
  「β(0.95)/β(0.50) = 8.5 倍尾部放大」**整個消失**。
- 殘存的是一個**小而一致為負**的偏效應（τ=0.05/0.25/0.50 皆顯著負），
  與原本的「高 VIX 時 BTC 波動放大恐慌」敘事**方向相反**。
- 係數大幅縮小與「原規格主要吸收 VIX 自身 persistence」一致；目前沒有證據可把原係數
  解讀為 BTC → VIX 的增量尾部資訊。

### 6. OOS 預測：未見 BTC 帶來增量改善

AR(p) vs AR(p) + BTC_RV_{t−1}，IS ≤ 2018-12-31、OOS ≥ 2019-01-01、rolling 756。
AR(1)…AR(22) 用共同 `hold_back=22` 的 942 筆 IS 樣本比較 AIC，選得 **p=3**；若讓每個 p
各自使用不同樣本，AIC 會機械性選到 grid 上界，舊版 p=22 即屬此錯誤。

| 子期間 | n | ΔMSE | acf₁(d) | HAC lag | DM t | **Clark-West t** |
|---|---|---|---|---|---|---|
| full OOS | 1,826 | −0.32% | −0.135 | 13 | −0.99 | −0.12 |
| 2019 | 252 | −0.02% | +0.024 | 7 | −0.20 | −0.11 |
| 2020 (COVID) | 253 | −0.07% | −0.161 | 7 | −0.09 | +0.28 |
| 2021–2022 | 503 | −0.49% | +0.030 | 8 | −0.82 | +0.21 |
| 2023–2026 | 818 | −0.53% | −0.008 | 10 | −2.75 | −2.55 |

- HAC bandwidth = `max(h−1, ⌈h^(1/3)·n^(1/3)⌉)`，用 canonical `volpred.stats.model_evaluation.dm_test`。
  腳本內有 runtime assert 釘死自寫 HAC 與 canonical 數值一致（見 `hac_tstat`）。
- **巢狀模型必須報 Clark-West**（`docs/error_log.md` 2026-07-11 / K1681：AR+BTC 是 AR 的巢狀擴張，
  raw DM 在虛無假設下系統性懲罰大模型，用它「證明沒有預測力」是把偏誤當證據）。
  這次 **CW 也全數未達門檻**（full OOS −0.12，單尾 5% 門檻為 1.645）。因此目前
  **沒有 BTC_RV 改善 VIX 預測的證據**；這不等於證明增量資訊精確為零。
- **loss differential 的 acf₁ = −0.135（負值）**。依 `.claude/rules/experiments.md`：負自協方差會**縮小**
  標準誤，補 HAC 後 |t| 會**變大**（不是變小）。實測 bandwidth 0 → |t|=0.72，
  13 → 0.99，30 → 1.33；
  即使用最寬的 bandwidth 仍低於 Harvey |t| > 3.0。未見改善的判定不因 bandwidth 選擇而變。

## 機械 gate

`scripts/tests/test_fevd_shape.py`（**擴充既有檔，未新開第二層** — 見下方「與 brief 的偏離」）：

- iid 高斯雜訊 3 變數 VAR 餵進 **k1025_v3 出貨的** `generalized_fevd` / `cholesky_fevd` /
  `connectedness` → total connectedness 必須 < 5%（實測約 0.3%–0.7%）。
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
| §5.3 / §6.1 Diebold-Yilmaz（90.11% total、−76.89 net） | **全數作廢**，須以 generalized FEVD 重寫（19.52% / −0.95pp） |
| 「BTC 是 fear amplifier 不是 originator」（淨接收者） | **強方向敘事不存活**：levels generalized 僅 −0.95pp、72.5% rolling 窗偏 receiver；一階差分翻成 +1.92pp，Cholesky 也隨排序翻號 |
| QR 尾部放大 8.5 倍（sign reversal） | **陣亡**。控制 lagged VIX 後右尾 β = +0.42 (ns)；殘存的是小而負的偏效應 |
| 非對稱 Granger（跌 > 漲） | 未受本次 bug 影響（不經 FEVD），維持有效 |
| OOS 預測 | raw DM 與 Clark-West 都未達門檻；未拒絕等預測力，也未見 BTC 帶來改善的證據 |
| **新增可寫素材** | 連動性**時變**（COVID 36.2% vs 平靜 20.8%）；BTC_RV 89.3% 變異來自自身，呈外圍性 |

**總評**：論文骨架仍在，但**兩根支柱各斷一根半**。原本的「crypto fear channel」= 
「BTC 波動在尾部放大股市恐慌」這個因果放大敘事，在加控制後**沒有證據支撐**。
可救的方向是把論文重新定位成 **時變連動性 + BTC 的外圍性（peripheral asset）**：
BTC 大體自成一格（89.3% own-variance），COVID 視窗的連動性明顯高於平靜期；但 net 方向
接近零且對資料轉換敏感，不能再寫成「始終是淨接收者」。這比原稿宣稱弱得多，論文敘事與
目標期刊需由主線程重新決策。

## 局限性

- FEVD VAR 主規格保留 paper 預設 `maxlags=5`，AIC 選到邊界 5；lag 1–22 sensitivity 的
  total 為 19.27%–24.48%，levels 下 BTC net 皆負，但一階差分會翻正，方向不可過度解讀。
- Rolling window 保留 paper 的 252 日、`maxlags=5`；若用 22 lags，每方程有 67 個參數，
  對 252 筆視窗過度參數化。
- RV(20) 是粗糙的波動率代理（未用高頻 RV）。
- BTC 週末報酬在 primary alignment 下被折進週一（Fri→Mon），與 SPY 同慣例；
  v2 的 calendar alignment（丟掉週末）當 robustness，結果差異 < 0.5pp。
- 三變數系統；未納入 DXY / 利率 / 其他 crypto，遺漏變數可能吸收部分連動性。
- Generalized FEVD 的 row normalization 是 DY(2012) 標準做法，但 KPPS 的 shock 非正交，
  「淨傳遞」的結構性因果解讀仍需審慎（這是 GFEVD 的已知代價，換來 order-invariance）。

## 檔案

- `k1025_v3.py` — **canonical** 實驗腳本
- `k1025_v3_results.json` — 結構化結果（含 generalized FEVD 矩陣、兩種 Cholesky sensitivity、
  rolling 512 窗口序列、QR 兩規格 + bootstrap CI、subsample DM + CW + HAC lag）
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
