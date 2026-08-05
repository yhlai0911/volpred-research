# nfp_20260807_t2 — 非農前最後兩個交易日的 VIX 路徑

狀態：**結論為 `NULL_FAILURE_TO_DETECT`**；analysis class =
`descriptive_event_study_with_HAC_inference`。這份 evidence package 服務事件內容槽
`NFP_US_2026_08_07 / T-2`。

姊妹研究 `nfp_20260807_t7` 測的是整個事件前週，結論同為 `NULL_FAILURE_TO_DETECT`：

> window: T-7 close -> T-1 close (six returns)
> relation: this study shortens the window to the final two sessions to test the dilution explanation for the sibling's null

也就是說，本研究存在的理由是一個具體的可否證假說：六日平均把只發生在最後 48 小時的
移動稀釋掉了。把窗口縮到最後兩個交易日，如果稀釋說成立，效果應該浮現。

## 問題

> Does the pre-NFP VIX ramp live in the final two sessions (T-3 close -> T-1 close), i.e. in the part of the week a T-2 reader can still act on?

窗口定義：

> VIX close at T-3 trading days -> VIX close at T-1 (two returns)

這不是非農當日反應研究，也不是交易策略；條件變數只使用 T-2 讀者在寫作當下
已經看得到的收盤。

## 資料與 information set

- VIX：Yahoo Finance ^VIX daily close, pinned local snapshot，requested start 2010-01-01，
  as-of 2026-08-04，有效 4,172 列；無有效收盤而移除的列：2026-06-19、2026-07-03。
- 事件日曆：FRED/ALFRED release dates API, release id 50 (Employment Situation)，選取規則 = earliest release-id-50 entry in each calendar month；
  snapshot 取得時間 2026-08-05T00:13:44Z。用官方 release 日期而非
  「每月第一個週五」proxy，是承接既有 knowledge：該 proxy 會錯配並翻轉方向性結論。
- 樣本：191 次可對上交易日的公布日，
  2010-02-05 至 2026-07-02。
- 兩個 input snapshot 位於 `data/`，由 `reproduce_spec.json` 逐檔綁 sha256，
  正常重跑 `network=deny`，不受來源後續回補或修訂影響。
- 隨機性：seeds = []，無 bootstrap／Monte Carlo／抽樣。

## 方法

推論之前先處理兩件事。

**1. exact interval overlap。** 控制窗與排除算式：

> all two-return VIX windows whose return intervals do not overlap an NFP T-3->T-1 interval
> event intervals i-2..i-1; control intervals k+1..k+2; exclude i-4 <= k <= i-2

逐段 interval 驗證而非整段近似，留下 3,597 個控制窗。

**2. overlapping outcomes 不是 iid。** 控制窗是 daily rolling 兩日變化，彼此大量重疊，
把它們當獨立樣本會低估標準誤。primary test 因此改為：

> method: OLS event indicator with Newey-West HAC covariance
> reason: rolling two-return control outcomes overlap and are not iid

primary lag = 22。

## 結果

### 描述統計

mean／median／sd／mean abs 四欄的單位皆為「窗口內 VIX 百分比變化」，不是 VIX 指數點；
n 是窗口個數，share up 是窗口中變化為正的比例。

| | n | mean | median | sd | share up | mean abs |
|---|---|---|---|---|---|---|
| 事件窗（T-3→T-1） | 191 | -0.17% | -1.92% | 10.82% | 41.9% | 8.13% |
| 控制窗 | 3,597 | +0.72% | -0.47% | 11.39% | 47.2% | 7.67% |

### Primary inference

事件指標效果 -0.89 pp（HAC se 0.84，
t = -1.06，p = 0.288，
95% CI [-2.53, +0.75]；n = 3,788，
其中事件 191、控制 3,597）。

**點估計是負的**：非農前最後兩個交易日的 VIX，平均比同長度的非事件窗**低**約
0.89 個百分點。但 CI 涵蓋 0，且上界達
0.75 pp —— 資料無法區分「小幅下滑」「無效果」與「小幅上升」。
稀釋假說沒有得到支持：把窗口縮短並沒有讓效果浮現。

### 穩健性

HAC lag sensitivity：

| lag | effect | HAC se | t | p | 95% CI |
|---|---|---|---|---|---|
| 6 | -0.89 pp | 0.82 | -1.08 | 0.278 | [-2.50, +0.72] |
| 22 | -0.89 pp | 0.84 | -1.06 | 0.288 | [-2.53, +0.75] |
| 60 | -0.89 pp | 0.86 | -1.04 | 0.298 | [-2.57, +0.79] |

三個 lag 的結論一致（p 介於 0.278 與
0.298），效果點估計不隨 lag 改變 ——
lag 只影響標準誤。

release-clean control（controls additionally dropped when either of their two returns is a release-day return）：丟掉
193 個控制窗後效果 -0.82 pp，
p = 0.331，CI [-2.47, +0.83]。同樣不顯著。

naive iid 參照（reported only to show what an unadjusted test would have claimed）：Welch p = 0.271，
Mann–Whitney p = 0.094。Mann–Whitney 的 0.094
正是把重疊窗誤當獨立樣本會買到的「接近顯著」—— 保留它是為了顯示未修正檢定會宣稱什麼，
不承載任何結論。

### 週內分解

> same 191-ish releases, week split into its early four returns and its final two returns; per-return means make the halves comparable

| 半段 | n returns | mean | mean per return | share up |
|---|---|---|---|---|
| 前段 T-7→T-3 | 4 | +1.78% | +0.44% | 47.6% |
| 後段 T-3→T-1 | 2 | -0.17% | -0.09% | 41.9% |
| 全週 T-7→T-1 | 6 | +1.63% | +0.27% | 44.5% |

兩個半段的每 return 平均符號相反。**這是純描述性分解，前段從未被檢定過**：
本研究唯一經過 HAC 推論的窗口是後段（primary test），姊妹研究測的是全週
T-7 close -> T-1 close (six returns)，也不是前段。因此「前段有效果、後段沒有」不是本 package 能支持的說法 ——
符號差異在這裡只是待檢定的觀察，不是結果。

### 事件日與衰退

> event_day = VIX close T-1 -> T-0; next_day = VIX close T-0 -> T+1

未修正的無條件平均：事件日
-1.30%（share up 31.9%），
隔日 +3.30%（share up 62.8%）。
這兩個數字本身不可讀作事件效果：

> NFP releases are almost all Fridays, so the unconditional means above are confounded with weekday seasonality; these regressions add weekday fixed effects and HAC standard errors

加入 weekday 固定效果與 HAC 後：

- 事件日 vs 一般日：-0.75 pp，
  p = 0.285，CI [-2.13, +0.63] —— 不顯著。
- 隔日 vs 一般日：+1.92 pp，
  p = 0.049，CI [+0.01, +3.83]。

隔日那條是本研究**唯一**名目上跨過 0.05 的檢定，而且只是勉強跨過
（p = 0.049，CI 下界 0.01 pp 幾乎貼著 0）。
它沒有經過多重比較修正，也不是本研究的 primary question。**不應該被當成發現報導**；
它至多是一個值得另一個預先登記的研究去測的方向。

### regime 條件切分

| VIX regime | n event | 事件窗 mean | 控制窗 mean | HAC effect | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| <15 | 67 | +2.29% | +2.06% | +0.23 pp | [-2.01, +2.47] | 0.841 | 0.926 |
| 15-20 | 66 | -0.85% | +1.41% | -2.26 pp | [-4.71, +0.19] | 0.071 | 0.283 |
| 20-25 | 30 | +0.64% | -1.62% | +2.26 pp | [-3.79, +8.32] | 0.463 | 0.926 |
| >=25 | 28 | -5.32% | -1.89% | -3.43 pp | [-7.47, +0.60] | 0.096 | 0.287 |

四個 regime cell 全部在 Holm 修正後不顯著（最小 p_holm = 0.283）。
未修正的 p 有兩格落在 0.1 以下，而它們的 95% CI 都涵蓋 0 ——
這正是為什麼要修正，也是為什麼 CI 欄不能省。

### 圖：`nfp_20260807_t2_window.png`

左 panel 是事件窗與控制窗的分佈疊圖；右 panel 是兩段事件前 per-return 平均，
外加公佈當天。

**右 panel 第三根長條需要一個 README 層級的更正**：它標為「T-0 當天」，取自
-1.30%，也就是上一節那個**未修正、混淆於星期效果**的
無條件平均。它有三個問題，圖上都沒有標示：(1) 它不屬於「公佈前」，而是公佈當天；
(2) 它是本圖最高的長條並因此決定 y 軸尺度，但同一個量在加入 weekday 固定效果後只剩
-0.75 pp（p = 0.285，不顯著）；
(3) 它沒有誤差線。**不要把這根長條讀成「非農當天 VIX 平均下跌
1.30%」的發現** —— 本 package 的裁決是
`NULL_FAILURE_TO_DETECT`，圖中沒有任何一根長條代表已被證實的效果：第一根從未被檢定
（見上節），另兩根的檢定都不顯著。

## 對目標事件的意涵

目標：2026-08-07 公布，內容槽 `T-2`，
條件收盤 2026-08-04（交易日標籤 T-3），
VIX = 16.5，落在 regime `15-20`。

該 regime 的歷史 cell（n = 66）給出 HAC 效果
-2.26 pp，95% CI
[-4.71, +0.19]（涵蓋 0），
p = 0.071，Holm 修正後 0.283。
**這是描述性條件比較，不是預測**：
可寫的結論是「歷史上這個波動水位下，非農前最後兩天沒有可辨識的系統性 VIX 上行」，
不是「這次會下跌 2.26 個百分點」。

## 限制

1. Failure to reject is not evidence that the event effect is exactly zero.
2. Daily closes do not identify intraday announcement reactions; a ramp that starts and ends inside the T-1 session is invisible here.
3. VIX only: nothing here establishes effects for rates, FX, single stocks or the options term structure.
4. Regime cells are conditioned on a realised VIX level, so they are descriptive comparisons, not a causal decomposition.
5. HAC lag choice is finite-sample judgment; lags 6, 22 and 60 are reported.

## 重現

```bash
uv run python experiments/nfp_20260807_t2/nfp_20260807_t2.py
```

`reproduce_spec.json` 綁定 entrypoint sha256 `97a21197a109…`
（28,302 bytes）、兩個 input snapshot 與五個 output；
`reproduce_commit.json` 記錄本次 generation identity。執行環境：
Python 3.12.10／numpy 2.4.3／pandas 3.0.1／scipy 1.17.1，
runtime 0.226 秒。

本檔由 `render_readme.py` 從 `nfp_20260807_t2_results.json` 生成，數字未經人工轉抄。
