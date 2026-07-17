# K1684 E2 — own-market realized-target forecast-tail-divergence cross-OOS gate

- **Experiment ID**: `k1684_e2` ｜ **Status**: completed — **待 Codex review**（本 agent 不自行宣稱 paper-ready）
- **執行日期**: 2026-07-18（台灣時間）｜ **Seed**: `20260718`（HAR/GJR refit、bootstrap、Z1 MC、擾動 draw 全同一顆）
- **父實驗**: `experiments/k1684`（R3, E1, H2_UNSUPPORTED）、`experiments/k1698`、K850/K854
- **三件套**: `README.md`（本檔）+ `k1684_e2.py` + `k1684_e2_results.json`；圖 4 張 + `test_k1684_e2.py`（8 tests）+ `data/`
- **資料**: `data/gspc_ohlc_2000_2026.csv`（^GSPC, 6662 日）、`data/n225_ohlc_2000_2026.csv`（^N225, 6488 日），yfinance auto_adjust=False

---

## 0. 裁決

> ## **H2_UNSUPPORTED**（誠實 null；不是 H2_REJECTED，也不是模型等價證明）
> 「HAR-RV 的 QLIKE 大勝 GJR、但尾部覆蓋大敗」這個 forecast-tail-divergence（K850/K854 headline）
> **在 own-market S&P 500 與 Nikkei 225、OOS n>5,000、公平（calibration-neutral + 無偏 proxy）比較下無法建立**。

E2 相對 E1 前進了兩步：(1) 樣本從 own-market n=450 拉到 **n=5,412 / 5,238**、跨 5 個時間分段 + 高/低波 regime；
(2) 把「HAR 看似大勝」的來源**定量拆解**成 **calibration-to-biased-proxy artifact**（E1 cross-asset 錯配的**同標的細緻版**）。

| 命題需要的 | K1684 E2 實測 |
|---|---|
| **腿 1**：HAR 在 own realized measure 上 QLIKE **公平地**贏 GJR、Harvey \|t\|>3 | **立不起來。** 無偏 co² proxy 上兩市場都**偏 GJR**（SPX t=+1.82、N225 t=+1.31，皆不顯著）。HAR 的「大勝」只出現在它訓練的效率 range proxy（GK/RS，raw t=−5.6/−5.1），對稱 bias 校正後 SPX 崩到 \|t\|<3、且 raw 跨 proxy **符號翻轉**（GK 偏 HAR、co² 偏 GJR）。 |
| **腿 2**：HAR 家族 VaR/ES 失敗、GJR 過關、且 rescue 救不回 | **不成立（甚至相反）。** 1% 下**只有 HAR+histsim 過 trinity、GJR 一格都沒過**。尾部失敗由**參數 overlay（Normal/CF/t 在兩模型都低估尾部，Z1 都拒絕）**驅動，換 empirical(histsim) overlay 兩模型都改善 → 對稱的 parametric-tail artifact，非 HAR 專有 divergence。 |

**兩條腿都不成立 → H2_UNSUPPORTED。** 但這是 **n≥2,500 尺度下 range-based realized measure** 的結論：真 5-min RV
（Oxford-Man 已停站、官方網域 dead，n≥2500 尺度不可得）下 HAR 的資訊優勢可能更大（K849 用 TX 5-min RV 得 t=−11）。
因此是 **UNSUPPORTED 不是 REJECTED**。

---

## 1. 開工前必讀（逐一記錄）

1. **`docs/error_log.md` §G**（Lookahead / DM-HAC / MDD 硬規則）+ K445/K547 lookahead 前例 → 本實驗
   明確 lag（`<= i-1` 資訊預測第 i 日）、DM 用 canonical HAC bandwidth（非 h−1）、加機械 lookahead 稽核 + 擾動測試。
2. **knowledge K1684（item 56144649）+ K1698（d11978f7）**：E1 是 forecast-tail-divergence 的誠實 null，
   致命點 = 用 TX 期貨 RV 冒充 own-market、配 0050 r²（cross-asset），且 own-market 腿只有 n=450、\|t\|=2.10 未過 Harvey；
   knowledge 明寫「**E2 必須在市場自己的 realized measure 上以 n≥2,500、cross-OOS 與 block-bootstrap sensitivity 再驗證**」。
3. **`experiments/k1684/README.md`（E1 R3）**：學到 (a) realized measure 不可分 session 漏 boundary jump；
   (b) placebo/correction pool 必與主模型**對稱**（symmetric refinement 硬規則）；(c) Trinity=Kupiec+Christoffersen CC+Basel；
   (d) 父檔 `var_backtest` 在零違規回 p=1 的 bug；(e) Basel 1% canonical / 5% 自訂需明示。E2 全部沿用/重犯防護。
4. **`.claude/rules/experiments.md` §Methodology 硬規則**：QLIKE actual/predicted、arch target 對齊、VaR/ES Basel 口徑、
   pooled-MLE multistart、DM HAC lag、raw MDD scale artifact、symmetric refinement — 逐條對照設計。
5. **experiment-preamble（研究誠實 13 條 + 方法論 8 標準）**：null 如實報告、不過度宣稱、seed 固定、三件套齊。

## 2. 文獻（≥3，如何支撐設計）

| 文獻 | 用途 / 如何支撐 E2 設計 |
|---|---|
| **Corsi (2009, J. Financial Econometrics)** — HAR-RV | log-HAR（日/週=5/月=22）規格；HAR 輸入=落後已實現測度。E2 的 HAR-RV 直接採此。 |
| **Patton (2011, J. Econometrics)** — Volatility forecast comparison using imperfect proxies | **核心公平性依據**：QLIKE 在**條件無偏** proxy 下對兩模型給一致排序；proxy 有偏會偏袒「校準到該偏誤的模型」。→ E2 以無偏 co² 為主裁 + 對稱 bias 校正，並警覺 co² QLIKE 的 near-zero 病態。 |
| **Garman & Klass (1980); Parkinson (1980); Rogers & Satchell (1991)** — range-based variance estimators | 平滑、高效率的日內變異數估計量（比 r² 有效率 5–7×），但在**離散價格下系統性向下偏**。→ E2 用 GK(primary)/PK/RS 當 own realized measure，並明確處理其向下偏誤（見 §5 公平性）。 |
| **Molnár (2016, Physica A); Todorova & Souček (2014); Martens & van Dijk (2007)** — range-based / realized-range HAR | 支撐「HAR 可用 range-based realized measure 而非只用 5-min RV」；也記錄 range 估計量的離散偏誤。→ 合理化在 5-min RV 不可得（n≥2500）時改用 GK。 |
| **Diebold & Mariano (1995); Harvey, Leybourne & Newbold (1997); Harvey, Liu & Zhu (2016)** | DM 檢定、HLN 小樣本修正因子、\|t\|>3 多重檢定門檻。→ E2 用 canonical `dm_test`（Newey-West，bandwidth=⌈h^⅓n^⅓⌉）+ HLN 修正 + \|t\|>3。 |
| **Kupiec (1995); Christoffersen (1998); Acerbi & Székely (2014); Fissler & Ziegel (2016) / Patton, Ziegel & Chen (2019)** | VaR POF、CC 條件覆蓋、ES 的 Z1、(VaR,ES) 的 FZ0 joint scoring。→ E2 腿 2 的完整 backtest 套件。 |

---

## 3. 設計（own-market，apples-to-apples）

- **標的 / forecast object**：^GSPC（primary）、^N225（external validity）的 **open-to-close（交易時段）報酬與其
  1-day-ahead 條件變異數**。指數無隔夜連續交易 → 交易時段變異數是自然的 own-market realized target，也對應
  高頻 5-min RV 捕捉的量。**forecast 與所有 realized target 都是同一標的、同一報酬定義**（無 cross-asset plug-in）。
- **Realized measure（同一標的自身 OHLC）**：GK=Garman–Klass（primary，最有效率）、PK=Parkinson、RS=Rogers–Satchell
  （皆平滑但離散價格下向下偏）、**co²=平方 open-to-close 報酬（Patton 無偏 proxy，但吵）**。
- **模型（同一資訊集、同一 refit cadence，對稱）**：
  - HAR-RV：log-HAR（Corsi 2009），輸入=落後 GK，expanding window，每 22 交易日 refit，log-normal retransform（+0.5s²）。
  - GJR-GARCH(1,1)-t：arch MLE，expanding window，每 22 交易日 refit，refit 之間固定參數逐日 forward-filter。
  - 初始訓練 1,250 日（~2000–2004 burn-in），OOS 從 2004-12 / 2005-02 起。
- **評估**：QLIKE（主）+ canonical DM/HAC + HLN(1997) 修正 + \|t\|>3；VaR 1%/5% 的 Kupiec(POF)+Christoffersen(CC joint)
  +Basel traffic light（1% canonical 250 天；5% **自訂 α-scaled，非 canonical Basel，已明示**）；ES 的 Acerbi–Székely Z1；
  FZ0 joint scoring + FZ0 的 DM。VaR overlay = {Normal, Cornish–Fisher, HistSim, Student-t}，**對兩模型對稱套用**
  （E1 symmetric-refinement 教訓）。mu 假設 0（日 equity VaR 慣例）。

## 4. Lookahead mechanical audit（通過）

- **明確 lag**：預測第 i 日只用特徵 `X[i]`（由 `<= i-1` 的已實現測度算出）；HAR 訓練配對 `(X[j], logRV[j])` 的
  最後 j = origin−1 < i（等價 `signal from t-1 → return at t`，滿足 `target_end < forecast_origin`）；GJR 的
  1-step 條件變異數 `h_i = ω + (α+γ·1{ε_{i-1}<0})ε²_{i-1} + β h_{i-1}` 只用 `<= i-1`。realized target 只進評估、
  絕不進特徵。
- **擾動測試**：把 probe 之後的**未來** RV 與報酬全部污染（×(1+5U)、+N(0,0.05)），重跑 HAR/GJR，驗證 probe 之前
  的預測**逐點不變**（`atol=0`）。SPX / N225 皆 **passed=True**（`lookahead_audit.passed`）。
- 對稱 bias 校正 `recalibrate` 亦 lag-safe（k_t 只用 `[oos_start, i)` 的已實現），有 regression test 鎖住。

## 5. 腿 1：QLIKE / DM（raw vs 對稱 bias 校正，neg t = HAR 較優）— **公平性是 E2 的核心防線**

**為什麼要對稱 bias 校正**：GK/PK/RS 是**向下偏**的估計量（離散價格）。因 HAR **訓練在 GK 上**會吃到同樣偏誤、
GJR 不會（GJR 目標 ≈ 真變異數 ≈ co²）。Patton(2011)：QLIKE 只在**無偏** proxy 下才對兩模型公平；有偏 proxy 會系統性
偏袒「校準到該偏誤的模型」。calib 均值印證：`mean(GK)=7.9e-5 < mean(co²)=1.1e-4`，且 `mean(HAR_fc)≈GK`、`mean(GJR_fc)≈co²`。
→ 對**每個 proxy** 同時報 RAW 與「兩模型皆做 lag-safe 對稱乘法 bias 校正」後的 QLIKE/DM。

| 標的 | 目標 | raw HLN t | raw Harvey? | recal HLN t | recal Harvey? |
|---|---|---|---|---|---|
| **SPX** (n=5,412) | **GK** | −5.58 | ✅ HAR | **−1.70** | ❌ |
| | PK | −2.85 | ❌ | −1.40 | ❌ |
| | RS | −5.10 | ✅ HAR | −1.31 | ❌ |
| | **co² (無偏)** | **+1.82** | ❌（偏 GJR） | −0.68 | ❌ |
| **N225** (n=5,238) | **GK** | −3.66 | ✅ HAR | **−3.09** | ✅ HAR |
| | PK | −1.73 | ❌ | −2.08 | ❌ |
| | RS | −3.97 | ✅ HAR | −3.10 | ✅ HAR |
| | **co² (無偏)** | **+1.31** | ❌（偏 GJR） | −0.39 | ❌ |

**判讀**：
- **RAW 跨 proxy 符號翻轉**（兩市場 `raw_sign_flip=True`）：HAR 只在它訓練的效率 range proxy 贏、換到無偏 co² 就翻成偏 GJR
  —— 這正是 E1 cross-asset target-mismatch 的**同標的細緻版**（proxy-choice 驅動而非跨資產）。
- **對稱 bias 校正後**：SPX 全崩到 \|t\|<3；HAR 的「大勝」被證實**大半是 calibration-to-biased-proxy artifact**。
- **無偏 co² proxy（最乾淨的公平單一檢定，Patton 2011）**：兩市場 HAR 都**沒贏** GJR（皆略偏 GJR、不顯著）。
- **N225 caveat（誠實揭露）**：recal 後 GK/RS 仍 Harvey-顯著偏 HAR（t≈−3.1，bootstrap CI 排除 0），
  即乘法校正只修 level、未修對 GK 噪音結構的高階校準，HAR 對 GK 仍有殘餘優勢 —— 但**該優勢不轉移到無偏 co²**
  （t=−0.39）。**主裁以無偏 proxy 為準 → leg 1 仍不成立**；此點列為待 Codex review 的爭點（見 §8）。

## 6. 腿 2：VaR / ES（1% / 5%，對稱 overlay）

**SPX 1% VaR（摘錄）**：

| Cell | 違規率 | Kupiec p | CC p | Basel | Trinity | ES Z1 p | 經驗 c [95% CI] |
|---|---|---|---|---|---|---|---|
| HAR+Normal | 3.53% | 0.000 | 0.000 | yellow | ❌ | 0.001 | **1.53 [1.42,1.59]** |
| HAR+Student-t | 2.79% | 0.000 | 0.000 | green | ❌ | 0.005 | — |
| **HAR+HistSim** | **1.11%** | **0.426** | **0.672** | green | **✅ PASS** | 0.619 | — |
| GJR+Normal | 1.88% | 0.000 | 0.000 | yellow | ❌ | 0.001 | — |
| GJR+Student-t | 1.50% | 0.001 | 0.002 | yellow | ❌ | 0.003 | 1.16 [1.09,1.25] |
| GJR+HistSim | 1.32% | 0.026 | 0.052 | green | ❌ | 0.690 | — |

- **1% 下唯一過 trinity 的是 HAR+HistSim（HAR！），GJR 一格都沒過** → 「HAR 敗 / GJR 過」的 divergence **相反**。
- **尾部失敗的真來源是參數 overlay**：Normal/CF/t 在**兩個模型**都低估尾部（Z1 p≈0.001–0.005 全拒絕、經驗 c>1），
  換 empirical HistSim 後**兩模型都改善**（Z1 p≈0.6–0.7 不拒絕）。這是 E1 symmetric-refinement 教訓的重演：
  尾部問題是 parametric-tail 問題，**對稱地**打在兩模型上，不是 HAR 專有。
- **5% VaR**：GJR 家族 Normal/HistSim/t 三格過 trinity、HAR 只有 HistSim 過 → GJR 在 5% 較穩，但這仍是 overlay 效應
  （HAR 參數 overlay 過度違規），非「QLIKE 贏但尾部敗」的乾淨 divergence。
- **FZ0 joint DM（1%，neg=HAR 較優）**：SPX {Normal +4.41, HistSim −2.12, Student-t +2.95}；N225 {+3.45, −0.42, +2.34}
  → 同樣是 overlay-dependent（參數 overlay 偏 GJR、histsim 偏 HAR），無一致 divergence。

## 7. 穩健性

- **跨 OOS 時間分段（recal-GK QLIKE DM t）**：SPX {2005-08:+0.83, 09-12:−1.04, 13-16:+0.68, 17-20:−1.37, 21-26:−2.07}
  —— **無一段 Harvey-顯著、符號隨期間變**。N225 {−2.69, +0.32, −1.59, −0.72, −4.03} —— 只有 2021-26 顯著。HAR 的 QLIKE 邊際不穩定。
- **Regime split（high/low vol，lag-safe 用落後 GK 相對 expanding median）**：SPX 低波 DM t=−3.97（HAR 顯著、平靜期）、
  高波 +1.53（stress 反偏 GJR）；N225 低波 −3.32、高波 −1.31。**HAR 的 recal-GK 邊際集中在平靜期，stress 消失/反轉**。
  1% VaR：stress 下 HAR+Normal 違規率（SPX 4.09% / N225 3.45%）遠高於 GJR+t（1.62% / 1.83%）—— 但這是 overlay 不對稱比較。
- **Block / stationary bootstrap（recal-GK loss diff，B=2000，seed 固定）**：SPX mean=−0.014，95% CI **[−0.031, +0.002]（含 0）**；
  N225 mean=−0.040，CI **[−0.065, −0.014]（排除 0，偏 HAR）** —— 與 §5 一致：SPX null、N225 效率-proxy 邊際存活但無偏 proxy 不支持。
- **經驗 scale 因子 c**（VaR 太窄程度）+ bootstrap CI：SPX HAR+Normal c=1.53（需放大 σ 53% 才蓋得住尾部）vs GJR+t c=1.16。

## 8. 限制與待 Codex review 爭點

- **realized measure 是 range-based，不是真 5-min RV**（Oxford-Man 停站、n≥2500 尺度不可得）。故裁決是
  **UNSUPPORTED 不是 REJECTED**：真 HF RV 下 HAR 資訊優勢可能更大。
- **對稱乘法 bias 校正**只修 level、未修高階校準；是否應改用 expanding Mincer–Zarnowitz（截距+斜率）或
  Hansen–Lunde 全套？→ **待 Codex review 判定**。主裁另有無偏 co² proxy 佐證，不單靠校正。
- **N225 recal-GK/RS 仍 Harvey-顯著偏 HAR** 但無偏 co² 不支持 —— reviewer 需裁定「以無偏 proxy 為主裁」是否恰當。
- **co² QLIKE 的 near-zero-return 病態**（open≈close 但當日有波動 → QLIKE 爆大）：已用平滑 proxy 三角佐證，但 reviewer 可要求
  winsorize / 排除極端低 co² 日的 robustness。
- **open-to-close forecast object**：隔夜風險 out of scope（明示）。
- **建議 paper route**：**yes（有條件）**。這是一個 n>5,000、跨兩市場、方法論嚴謹的 own-market null，且把「apparent
  divergence」的來源拆成 cross-asset 錯配（E1）+ within-asset calibration artifact（E2）—— 適合 **FRL / Journal of
  Forecasting 方法論短文**（「forecast-tail divergence 是 realized-measure 建構與 proxy-bias 的產物，不是 HAR-vs-GARCH
  的穩健性質」）。**但需 Codex review 先裁定 §8 的 bias-校正口徑與 N225 caveat**，本 agent 不自行宣稱 paper-ready。

## 9. 復現

```bash
uv run python experiments/k1684_e2/k1684_e2.py                 # 全流程（~40s），寫 results.json + 4 圖
uv run --extra dev python -m pytest experiments/k1684_e2/test_k1684_e2.py -q   # 8 統計正確性 + lag-safety 測試
uv run python scripts/experiment_gates.py run --path experiments/k1684_e2      # methodology gate（PASS）
```

---

## COLLECTION NOTES（給收件 fire 的 followup）

- **本次結論一句話**：**H2_UNSUPPORTED** —— forecast-tail-divergence（HAR QLIKE 大勝 + 尾部大敗）在 own-market
  S&P 500 與 Nikkei 225、OOS n>5,000、公平比較下**無法建立**；HAR 的「大勝」大半是 **calibration-to-biased-proxy artifact**
  （E1 cross-asset 錯配的同標的細緻版），尾部失敗是**對稱的 parametric-overlay 問題**（非 HAR 專有）。
- **關鍵數字 3 個**：
  1. 無偏 co² proxy 上 HAR **沒贏** GJR（SPX DM t=+1.82、N225 +1.31，皆偏 GJR、不顯著）。
  2. SPX GK raw t=−5.58（HAR 顯著）→ 對稱 bias 校正後 **t=−1.70（不顯著）**；raw 跨 proxy 符號翻轉。
  3. 1% VaR：**只有 HAR+HistSim 過 trinity、GJR 零格過**；Normal/CF/t overlay 在兩模型 Z1 全拒絕（尾部低估對稱）。
- **待 Codex review 的爭點**：(a) 對稱**乘法** bias 校正 vs expanding Mincer–Zarnowitz 全套是否足夠；
  (b) N225 recal-GK/RS 仍 Harvey-顯著偏 HAR、但無偏 co² 不支持 —— 「以無偏 proxy 為主裁」是否恰當；
  (c) co² 的 near-zero QLIKE 病態是否需 winsorize robustness。
- **建議 paper route**：**yes（有條件）** —— FRL / Journal of Forecasting 方法論短文（forecast-tail divergence =
  realized-measure 建構 + proxy-bias 的產物）。**需 Codex review 通過並裁定上述爭點後**才由主線程決定是否走 narrative；
  本 agent 不自行宣稱 paper-ready，也不寫 knowledge.json（由主線程收）。
