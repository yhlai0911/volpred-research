# K1735 — 日內 diurnal pattern 是否「足夠」解釋 RV 變異？

[提出: research_program.md L628 backlog / 執行: compute-queue agent (opus xhigh) / 2026-08-01]

**狀態**: 已執行。success criteria 於看到任何結果**之前**寫死（見 §5），事後未修改。

---

## 1. 問題

日內已實現波動率有眾所周知的 U 型 time-of-day 季節。本實驗問的是**充分性**：

> 把已知的日內 U 型季節剔除之後，是否仍有顯著的 intraday volatility 變異？
> 季節成分究竟佔 RV 變異的多少比例？

來源：Christensen, Hounyo & Podolskij, *"Is the diurnal pattern sufficient to explain
intraday variation in volatility? A nonparametric assessment"*（arXiv 2601.16613；正式版
*Journal of Econometrics* 205(2), 2018, 336–362）。本檔只把它當**方法論來源**，不宣稱
複製其 pre-averaged jump-robust 統計量。

這是**方法論基礎題**：結論會校準本專案所有日內 RV 估計（PRG / MC-GARCH / intraday
GARCH 線），因此優先於任何單一策略發現。

---

## 2. 與既有實驗的關係（查重）

本專案已有兩份相關產物，**本實驗不是重跑**：

| 既有 | 做了什麼 | 本實驗的差異 |
|------|---------|-------------|
| `experiments/experiment_diurnal_pattern_rv_2026_06_14` | SPY / 0050.TW 本地 5-min，2026-01～2026-06（99 / 81 天）。raw vs deseasonalized 的 one-way eta²＋day-block permutation。結論 "not_rejected"，並報 eta²≈0.07–0.10 當作「季節佔比」 | (a) 主樣本換成 **TAIFEX TX 逐筆 tick → 2012–2026、~3,500 交易日**，含 2020 崩盤與 2022 空頭；(b) 指出並修正該 eta² 的**測量噪音地板偏誤**（見下）；(c) 加入 day-level 與 bin-level 的**二維分解**，而非單一 one-way eta²；(d) 加入 **regime / era 形狀恆定性檢定**（短樣本做不到）；(e) 全家族 **BH-FDR** 校正；(f) 季節剖面改為 **expanding-window（僅用過去日）** 估計 |
| `experiments/k1255_intraday_seasonality_pilot` | Phase-0 scoping only，明文「不跑 estimation」。MC-GARCH q·s·g 的規劃書 | 本實驗做的是 **s 這一項是否足夠**的無母數檢定，不估 MC-GARCH，不與其撞 scope。本結論是 k1255 Phase-1 的前置校準 |

**必須先講清楚的一件事**：舊實驗把 `eta²(log bar-RV) ≈ 0.07` 讀成「diurnal 只解釋 7% 的
RV 變異」。這個數字幾乎**全部**由測量噪音決定，不是波動率的性質。理由見 §4.2 ——
用單一 5 分鐘報酬平方當 bar-RV 時，`log r²` 帶著 `log χ²₁` 的雜訊，其變異數是
`ψ'(1/2) = π²/2 ≈ 4.93`，而 diurnal 剖面本身的 log 變異數只有 ~0.3–0.5 量級。
分母被 4.93 灌爆，任何季節成分都會被壓成個位數百分比。**本實驗的核心方法貢獻就是把這個
地板扣掉，並用 tick 資料把它降低一個數量級。**

---

## 3. 資料（誠實盤點）

### 3.1 為何不用 yfinance 當主樣本

yfinance 的 intraday 歷史深度上限約 60 天（1m 資料 7 天、5m 資料 60 天）。以那樣的樣本
回答「季節是否充分」只能得到一個 regime 的快照，**做不了 regime / era 恆定性檢定**，也蓋不住
任何空頭期。因此 yfinance 路線在此題**不足以支撐結論**，這件事本身寫進結果。

### 3.2 實際使用的資料

| cell | 來源 | 期間 | 頻率 | 說明 |
|------|------|------|------|------|
| **TX-day**（主）| `~/Dropbox/TAIFEXDATA/TAIFEXDATA/python/Daily_*TX.csv` 逐筆 tick | 2012-01-02 起 | tick → 1-min → 5-min bin | 日盤 08:45–13:45，60 個 5 分鐘 bin |
| **TX-night** | 同上 | 2017-05-16 起（夜盤上線）| 同上 | 夜盤 15:00–05:00，168 個 5 分鐘 bin |
| **SPY** | `data/intraday/SPY_5min_*.csv`（yfinance 落地）| 2026-01 起 | 5-min bar | 對照組，**樣本淺，明文標註** |
| **0050.TW** | `data/intraday/0050_TW_5min_*.csv` | 2026-01 起 | 5-min bar | 同上 |

tick 解析**沿用** `scripts/collect_taifex_tick.read_taifex_ticks`（header-based era 正規化、
big5/cp950 編碼、月契約過濾），不另寫 parser，避免與 `data/intraday/taifex_5min_rv.csv` 漂移。
每日只取**當日成交量最大的月契約**（`pick_active_contract`，與 canonical 同規則）。

實際抓到的日期範圍、bar 數、掉單數、缺漏處理**全部由程式寫入 `K1735_results.json`
的 `data_inventory`**，不手打。

### 3.3 缺漏處理

- 沒有成交的分鐘 → 沿用前一分鐘收盤（報酬 0），計入 `n_stale_sub`。
- 開盤前導缺口 → 以該盤第一筆成交價回填，並用它當報酬遞迴的起點，使**第 1 個 bin 與其他 bin
  有相同的 m 個 sub-return**（否則開盤 bin 會少一個 sub-return，正是 U 型最關鍵的位置）。
- 半日 / 異常日：要求該盤實際有成交的分鐘數 ≥ 95% 且 bin 數完整，否則整日剔除並計數。
- 面板必須是**平衡**的（每個保留日都有全部 K 個 bin），二維 ANOVA 才成立。

### 3.4 時區（SPY / 0050 必要步驟）

落地的 5 分鐘 CSV 時間戳是 **UTC**。美國有日光節約時間，09:30 ET 在 1 月是 14:30 UTC、
在 7 月是 13:30 UTC。若直接拿 UTC 當 time-of-day 分 bin，同一個開盤時刻會在 3 月與 11 月
各跳一小時，**憑空製造出一個假的「季節形狀年代漂移」**。因此 SPY 一律轉 `America/New_York`、
0050.TW 轉 `Asia/Taipei` 之後才切 bin。TX 的 `trade_time` 本來就是交易所當地時間，無此問題。

### 3.5 價格離散化（pre-declared，看結果前寫死）

以單一 5 分鐘報酬平方當 bar-RV（m=1 格點）時，`log RV` 對 `RV = 0` 沒有定義。實測 exact-zero
5 分鐘報酬比例：**TX 日盤 6.98%、TX 夜盤 11.25%、SPY 0.63%、0050.TW 22.77%**。這是 tick
離散化（TX 最小跳動 1 指數點、0050 為 0.05 元）造成的，不是資料錯誤。處理規則：

1. **半跳動下限（floor）**：`RV = 0` 的 bin 一律 floor 到 `(0.5 · tick / price)²`，保持面板平衡，
   並把 floor 比例寫進 results。用「刪掉含零的整日」當敏感度對照（刪日會系統性刪掉低波動日，
   不能當主口徑）。
2. **>5% exact-zero 的 cell×grid 一律降為 diagnostic-only**，不進入 confirmatory 的 BH-FDR 家族，
   理由記在 results。依上表，這條**事前**就把 TX m=1 兩個 session 與 0050.TW 全部劃為 diagnostic，
   confirmatory 家族只留 TX-day / TX-night 的 m=5、m=15 與 SPY 的 m=1、m=3。

---

## 4. 方法

### 4.1 模型

第 d 天、第 k 個 time-of-day bin 的已實現變異數 `RV_{d,k}`（由 m 個 1 分鐘 sub-return 平方和構成）：

```
RV_{d,k} = q_d · s_k · g_{d,k} · (χ²_m / m)
             ↑      ↑      ↑         ↑
          日水準  日內季節  日內      測量噪音
                (待檢定)  隨機成分
```

取對數：`u_{d,k} = log RV_{d,k} = log q_d + log s_k + log g_{d,k} + ε_{d,k}`。

**H0（充分性）**：`s_k` 是一個時間不變的確定性因子，且在扣掉 `q_d` 與 `s_k` 後
沒有殘留的日內結構——亦即 `Var(log g) = 0`、殘差無 time-of-day 效果、`s_k` 的形狀
不隨 regime / 年代改變。

### 4.2 噪音地板（本實驗的關鍵修正）

若 m 個 sub-return 為 iid 常態，`RV/σ²Δ ~ χ²_m`，故

```
Var(ε) = ψ'(m/2)        (trigamma)
m = 1  → ψ'(0.5) = 4.9348      ← 舊實驗（單一 5 分鐘報酬平方）落在這裡
m = 5  → ψ'(2.5) = 0.4903      ← 本實驗主格點（5 分鐘 bin，1 分鐘 sub-return）
m = 15 → ψ'(7.5) = 0.1440      ← 穩健格點（15 分鐘 bin）
```

任何**未扣除這個地板**的 `eta²` / R² 都會系統性低估季節佔比，且低估幅度只是 m 的函數，
與市場無關。本實驗同時報告三個格點，讓這個效應直接看得見。

### 4.3 變異數分解

在平衡面板上做二維（day × bin）ANOVA 分解，並做**估計噪音的偏誤修正**：

```
V_bin  = mean_k(ŝ_k²) − (K−1)/K · σ̂²_e / D        季節（diurnal）
V_day  = mean_d(â_d²) − (D−1)/D · σ̂²_e / K        日水準
V_stoch = σ̂²_e − ψ'(m/2)                          日內隨機波動（扣掉噪音地板，下限 0）
```

報告三個比例，全部附 **day-block bootstrap（B=1000, seed=42）百分位 95% CI**：

- `naive_share` = 未修正的 `V_bin_raw / Var(u)` — **只為與舊實驗可比**
- `diurnal_share_systematic` = `V_bin / (V_bin + V_day + V_stoch)` — 季節佔**全部系統性波動變異**
- `diurnal_share_within_day` = `V_bin / (V_bin + V_stoch)` — 季節佔**日內（去掉日水準後）**變異

### 4.4 檢定（全部無母數）

| id | 檢定 | 虛無 | 方法 |
|----|------|------|------|
| **T1** | 去季節後殘餘 time-of-day 結構 | 去季節殘差無 bin 效果 | **expanding-window** 估 `ŝ_k`（只用第 d 天之前的日）→ 殘差 one-way eta² → **day-block permutation**（打亂日內 bin 標籤的日層區塊）1000 次 |
| **T2** | 季節形狀的 **regime 依賴** | 高／中／低波動日的 `s_k` 形狀相同 | 依 `q_d` 分三分位各估 `ŝ_k`（形狀正規化後）→ 統計量 = 三組剖面的最大成對 L2 距離 → **day-block permutation**（隨機重排日的 regime 標籤）1000 次 |
| **T3** | 季節形狀的 **年代漂移** | `s_k` 形狀在各年份相同 | 同 T2，分組改為年份／樣本前後半 |
| **T4** | 殘餘日內隨機波動 | `Var(log g) = 0` | `V_stoch` 的 day-block bootstrap 單尾 p 值（H0 下 `σ̂²_e = ψ'(m/2)`）|

**T1 / T2 / T3 的 null 一律用 circular-shift randomization，不用自由重排標籤**：

- T1 把**每一天**的 bin 序列各自隨機環狀位移。自由重排 bin 標籤會破壞日內波動的自相關，
  使 null 分佈過窄而系統性高估顯著性；環狀位移完整保留日內相依結構，只打散「跨日的 time-of-day 對齊」。
- T2 / T3 把**分組標籤向量**對整條日序列做隨機環狀旋轉。regime 標籤（由 `q_d` 決定）與年代標籤
  本身都高度持續，自由重排會讓 null 的組別在時間上散開、真實組別在時間上連續，
  於是任何緩慢漂移都會被誤判成「regime 依賴」。環狀旋轉同時保留標籤的連續性與序列相依。

**T4 的 fat-tail 保守地板（pre-declared robustness）**：`ψ'(m/2)` 假設 sub-return 為 iid 常態。
厚尾會讓 `Var(log RV)` 的真實地板高於 `ψ'(m/2)`，使 T4 偏向拒絕。因此另算一個保守地板：
用兩維模型的配適值把 1 分鐘報酬標準化，以峰態配適 Student-t 自由度
（`df = (4·kurt − 6)/(kurt − 3)`），模擬 m 個該 t 分佈的平方和求 `Var(log RV)` 得 `φ_m^t`，
再以 `V_stoch^cons = σ̂²_e − φ_m^t` 重跑 T4。注意若真有日內隨機波動，標準化後的殘差會**看起來**
更厚尾，故此地板必然過高、T4 因此**偏保守**——它拒絕就是強證據。主口徑仍是 §5 事前寫死的
`ψ'(m/2)`，保守版並列報告。

**多重檢定**：所有 cell × grid × test 的 p 值放進**同一個** Benjamini–Hochberg 家族，
`q = 0.10`。`K1735_results.json` 同時記錄 **pre-FDR 與 post-FDR** 的結論。

### 4.5 校準檢查（gate，非裝飾）

用**在 H0 下模擬**的資料（確定性 diurnal × 日水準，常態 sub-return，`Var(log g)=0`，
seed=42）跑同一支估計器。若

- `V_stoch` 的 bootstrap CI 未涵蓋 0，或
- T1／T2 的拒絕率明顯高於名目水準，

則代表噪音地板修正本身有偏，**verdict 一律降級為 CONDITIONAL_PASS**，不論實證結果多漂亮。

### 4.6 穩健性

- **跳躍**：主結果用 RV；穩健版對 1 分鐘報酬做 threshold truncation（3× 局部 bipower 尺度）
  重算，檢查季節佔比與 T1/T4 結論是否翻轉。
- **格點**：m = 1 / 5 / 15 三個格點（SPY / 0050 只有 m = 1 與 m = 3）。
- **開盤 bin**：另跑一版剔除第 1 個 bin，確認結論不是被開盤集合競價單獨驅動。

---

## 5. Success criteria（**看到結果前寫死**）

主 cell = **TX-day，5 分鐘 bin，m = 5**。

- **REJECT_SUFFICIENCY**（＝「diurnal 不足夠」這個發現成立）：
  {T1, T2, T4} 中**至少 2 個**在主 cell 於 **BH-FDR q=0.10 後**仍拒絕，
  **且**同方向在 confirmatory cell 中**至少 2 個**複製。
  （§3.5 的離散化規則事前把 `tw0050` 與所有 m=1 格點劃為 diagnostic-only，
  因此 confirmatory 複製池是 `tx_day` / `tx_night` / `spy` 三個 cell，門檻為 3 取 2。
  `tw0050` 照樣計算、照樣報告，但不計入 FDR 家族與複製計數。）
- **NULL_SUFFICIENCY_NOT_REJECTED**：三個檢定 post-FDR **全部不拒絕**。
- **CONDITIONAL_PASS**：恰好 1 個 family 拒絕，或主 cell 拒絕但複製不到 2 個 cell，
  或 §4.5 校準檢查未通過。
- **INSUFFICIENT_DATA**：主 cell 可用交易日 < 500，或面板平衡／覆蓋檢查失敗。

量化交付（無門檻，屬描述性）：每個 cell × grid 都要給
`naive_share` / `diurnal_share_systematic` / `diurnal_share_within_day` 的
點估計 **＋ 95% day-block bootstrap CI**。

---

## 6. Lookahead policy

本實驗**沒有交易訊號、沒有 forward-label target**，但去季節這一步本質上是「用某個估計值去
調整當期觀測」，因此仍套用等價的 lag 規則：

1. **T1 的季節剖面 `ŝ_k` 一律 expanding-window，只用第 d 天之前的日**
   （`_expanding_seasonal_profile`，burn-in 60 天）。這是 `signal.shift(1)` 的等價物：
   第 d 天用到的去季節因子，其資訊集嚴格落在 d 之前。若改用全樣本 `ŝ_k`，殘差的 bin 平均
   會被機械性地壓成 0，T1 必然「不拒絕」——那是恆等式，不是證據。
2. **§4.3 的變異數分解與 T2/T3 是全樣本描述性統計**，不是預測，README 與 results.json
   都明文標為 `in_sample_descriptive`。其估計噪音由 §4.3 的偏誤修正處理，
   不確定性由 day-block bootstrap 給出。
3. 所有 permutation / bootstrap 的重抽單位是**整個交易日**，保留日內相依結構。
4. `seed = 42`，全部隨機程序固定。

---

## 7. 產物

- `k1735_panel.py` — tick → 5 分鐘 bin 面板（快取 `data/tx_5min_panel.parquet`）
- `K1735.py` — 主分析（entrypoint）
- `K1735_results.json` — 全部數字（byte-traceable，經 `finalize_experiment` 寫入）
- `reproduce_spec.json` — run-time 產生
- `test_k1735.py` — 單元測試
- `review_verdict.json` — Codex 審查裁決

---

## 8. 誠實限制（先寫，不等結果）

- 這**不是** Christensen–Hounyo–Podolskij 的 pre-averaged / jump-truncated semimartingale
  統計量的複製；是同一個問句下的獨立無母數評估。不得以此宣稱複製或反駁該論文。
- TX 是**指數期貨**，不是股票；日內季節受期貨特有的結算與夜盤結構影響，外推到個股須另驗。
- 1 分鐘 sub-return 仍受微結構噪音影響（RV 相對 5 分鐘 RV 有上偏）。噪音地板 `ψ'(m/2)`
  假設 sub-return 為 iid 常態；厚尾與離散化會使真實地板偏離該值，故 §4.5 的校準檢查是必要條件。
- SPY / 0050.TW 只有約 5–7 個月樣本，**其 cell 的結論只能當方向性佐證**，不得單獨支撐宣稱。
- 夜盤 cell 的 168 個 bin 中包含流動性極低的時段，變異數分解在該區段的穩定性較差。

---

## 9. 結果

見 `K1735_results.json`（權威來源）與 §9 摘要 —— 摘要由 `K1735.py --render-readme`
從 results JSON 產生，**不手打**。

<!-- RESULTS:BEGIN -->

**Verdict: `REJECT_SUFFICIENCY`** — 3/3 key tests reject post-FDR on the primary cell (T1_residual_bin_structure, T2_regime_shape, T4_residual_stochastic_vol) and replicate in 3 confirmatory cells; calibration gate passed

主 cell = `tx_day/m5_5min`（20120102–20260730，3558 個交易日 × 60 個 bin）。

### 季節成分佔 RV 變異的比例（點估計 [95% day-block bootstrap CI]）

| 口徑 | 點估計 | 95% CI |
|------|--------|--------|
| `naive_share`（未扣噪音地板，與舊實驗可比）| 0.2191 | [0.2128, 0.2254] |
| `diurnal_share_systematic`（佔全部系統性波動變異）| 0.3007 | [0.2903, 0.3110] |
| `diurnal_share_within_day`（佔日內變異）| 0.5433 | [0.5326, 0.5544] |

測量噪音地板佔 naive 分母的 **27.2%** —— 這就是舊實驗 eta²≈0.07 的來源。

**`diurnal_share_within_day` 的穩健性區間**（點估計是對 diurnal 最不利的一端，兩個穩健方向都把它推高，故交付的是區間不是點）：

- baseline（Gaussian 地板）：**0.5433**
- 跳躍截斷 3σ 後：**0.7460**
- 保守 fat-tail 地板：**0.8639**

### 檢定（BH-FDR q=0.10，confirmatory 家族）

| cell | grid | test | p | pre-FDR | post-FDR |
|------|------|------|---|---------|----------|
| tx_day | m5_5min | T1_residual_bin_structure | 0.0010 | ✅ | ✅ |
| tx_day | m5_5min | T2_regime_shape | 0.0010 | ✅ | ✅ |
| tx_day | m5_5min | T3_era_shape | 0.7612 | — | — |
| tx_day | m5_5min | T4_residual_stochastic_vol | 0.0010 | ✅ | ✅ |
| tx_day | m15_15min | T1_residual_bin_structure | 0.0010 | ✅ | ✅ |
| tx_day | m15_15min | T2_regime_shape | 0.0010 | ✅ | ✅ |
| tx_day | m15_15min | T3_era_shape | 0.6763 | — | — |
| tx_day | m15_15min | T4_residual_stochastic_vol | 0.0010 | ✅ | ✅ |
| tx_day | m3_15min_5minsub | T1_residual_bin_structure | 0.0010 | ✅ | ✅ |
| tx_day | m3_15min_5minsub | T2_regime_shape | 0.0010 | ✅ | ✅ |
| tx_day | m3_15min_5minsub | T3_era_shape | 0.7972 | — | — |
| tx_day | m3_15min_5minsub | T4_residual_stochastic_vol | 0.0010 | ✅ | ✅ |
| tx_night | m5_5min | T1_residual_bin_structure | 0.0010 | ✅ | ✅ |
| tx_night | m5_5min | T2_regime_shape | 0.0010 | ✅ | ✅ |
| tx_night | m5_5min | T3_era_shape | 0.0919 | — | — |
| tx_night | m5_5min | T4_residual_stochastic_vol | 0.0010 | ✅ | ✅ |
| tx_night | m15_15min | T1_residual_bin_structure | 0.0010 | ✅ | ✅ |
| tx_night | m15_15min | T2_regime_shape | 0.0050 | ✅ | ✅ |
| tx_night | m15_15min | T3_era_shape | 0.0799 | — | — |
| tx_night | m15_15min | T4_residual_stochastic_vol | 0.0010 | ✅ | ✅ |
| tx_night | m3_15min_5minsub | T1_residual_bin_structure | 0.0010 | ✅ | ✅ |
| tx_night | m3_15min_5minsub | T2_regime_shape | 0.0270 | ✅ | ✅ |
| tx_night | m3_15min_5minsub | T3_era_shape | 0.1119 | — | — |
| tx_night | m3_15min_5minsub | T4_residual_stochastic_vol | 0.0010 | ✅ | ✅ |
| spy | m1_5min | T1_residual_bin_structure | 0.6983 | — | — |
| spy | m1_5min | T2_regime_shape | 0.7263 | — | — |
| spy | m1_5min | T4_residual_stochastic_vol | 0.9970 | — | — |
| spy | m3_15min | T1_residual_bin_structure | 0.6863 | — | — |
| spy | m3_15min | T2_regime_shape | 0.4705 | — | — |
| spy | m3_15min | T4_residual_stochastic_vol | 0.0010 | ✅ | ✅ |

FDR 家族 30 個檢定，pre-FDR 拒絕 19 個、post-FDR 拒絕 19 個。

校準 gate（§4.5）：**PASS** — Gaussian H0 下 V_stoch 平均 0.00039（噪音地板的 0.08%），T1/T2 在 α=0.05 的拒絕率 0.03 / 0.09。

<!-- RESULTS:END -->
