# K1679-rev2 Codex review

**Review verdict: CONDITIONAL_PASS.** 可採用的結論是：current-vintage 與 genuine
PIT 均未顯示 H.8 deposit-flight 對 KRE forward RV/DSV 的穩健增量預測力。
first-release-only sensitivity 則是 `documented_negative`（加入訊號顯著變差），
不能稱為 FDR artifact。NULL 僅指「沒有 robust forecast improvement」，不等同證明
兩模型完全相等。

## 審查發現與修復

救援 branch `e8525e1f7` 起初應判 **FAIL**：ALFRED wide query 的 API count 為
281,186 / 274,847，但程式各只讀 100,000 列，兩系列因此只到 2009-07-08；
223 個假 signal rows 又共用 2012-08-18 available date，`merge_asof` 將其變成
std=0 的常數。舊 `safe_null` 是浮點噪音，不可採信。

最終版已修成：

- `K1679-rev2.py:231-341`：output_type=1 依 API `count` 完整 pagination；少頁、
  row-count mismatch 或 `9999-12-31` open-ended sentinel 解析錯誤均 fail closed。
- `K1679-rev2.py:414-443`：snapshot 同時檢查
  `realtime_start <= R <= realtime_end`，不只取最新 start。
- `K1679-rev2.py:446-548`：output_type=4 定義正式 release origins；output_type=1
  只供當日 revision snapshot。history-only archive backfill 不會成為 forecast origin；
  兩個訊號另有 n / nunique / std hard gates。
- `K1679-rev2.py:551-568,1141-1162,1212-1226`：只 backward as-of merge，並檢查
  signal age、非負時間差、最大 45 天與 trading-panel 非退化。

最終 JSON 證據：兩系列各 3 pages，received count 完全等於 API count；
observation date 到 2026-07-01。true PIT 有 725 個 weekly values，13w std=1.198、
725 unique、as-of 2012-08-15 至 2026-07-01；交易日 age 9–23 天，
current-vs-PIT correlation=0.886，SVB peak=3.967。退化紅旗已消失。

## 指定項目 checklist

| 項目 | 結論 | 程式證據 |
|---|---|---|
| 真 ALFRED PIT | PASS | pagination `:231-341`；release origin + revision snapshot `:446-548` |
| Clark-West (2007) | PASS | adjusted MSPE 公式 `:611-627`；單尾 upper-tail/HAC-H/HLN `:632-651`；全 8 格 `:909-915` |
| unfloored sensitivity | PASS | raw forecasts與 MSE sensitivity `:817-819,866-892` |
| forward-label embargo | PASS | target 是 `(t,t+H]` `:702-703,788-792`；訓練尾列 `j=i-H-1` 且 assertion `:706-765` |
| horizon-specific inference | PASS | 每格 `H` 傳入 DM/CW `:845-892`；JSON 全部 `hac_lag==H` |
| seed / bootstrap | PASS | seed=42 `:100-102`；2,000 reps、`block=max(10,H)` `:655-675,860-863` |
| DM/HLN/HAC | PASS | Bartlett NW `:575-584`；HLN factor與 two-sided t p-value `:587-608` |
| m=8 multiple testing | PASS | DM Bonf/BH `:927-939`；CW 單尾 p 的獨立 Bonf/BH family `:940-958` |
| sign-aware verdict | PASS | positive DM = hurts；Bonf negative / CW-positive / mixed precedence `:965-1019` |
| atomic result write | PASS | temp → JSON parse → `os.replace` `:1364-1368` |

CW adjusted loss differential、單尾方向與 nested-model用途正確。HLN/t calibration 不是
Clark-West 原始的 asymptotic-normal呈現，而是此專案既定的保守 small-sample extension；
JSON 同時留 raw 與 HLN statistics。這不會把最終 NULL 翻成 positive finding。

## 結果獨立核對

主線不採信 agent summary，直接讀最終 JSON 並重算所有 adjustment：

- 三個 vintage 各 8 個 primary cells；每格 DM/CW lag 等於自身 H。
- 每格 bootstrap `block=max(10,H)`、2,000 reps；每格 embargo audit 均 true。
- DM 與 CW 的 Bonferroni、BH q 值以 m=8 重算後逐格相符。
- current：`safe_null`；最強格 DM t=+1.775，Bonf=.609。
- first-release-only：`documented_negative`；13w·RV·H5 QLIKE 惡化 3.72%，
  DM t=+2.772、p=.00565、Bonf=BH=.0452；CW t=-0.281、單尾 p=.611。
- true PIT：`safe_null`；最強 13w·DSV·H5 DM t=+1.946、p=.0518、
  Bonf=.414、BH=.319；CW t=-2.019、單尾 p=.978。8 格皆無 raw p<.05、
  Harvey |t|>3、DM/CW multiplicity rejection 或 forecast improvement。
- unfloored DSV/MSE sensitivity 沒有產生相反方向的顯著改善。

驗證另含：mocked two-page pagination + open-ended/gapped realtime-window test、
synthetic release-origin/PIT non-degeneracy test、`py_compile`、`git diff --check`、
最終 artifact assertion script。兩次 compute-queue jobs 均 exit 0；最後一輪 stderr 空。

## 條件與結論邊界

CONDITIONAL_PASS 的條件不是程式殘留 bug，而是證據範圍：真 PIT 自 2012-08 才有，
無法同規格覆蓋 2008 GFC；H.8 size cohort 也不是 bank-level uninsured deposits。
因此可寫入知識的是狹義 forecast NULL，不可外推成 universal、causal 或 bank-level
deposit-run NULL。

VERDICT: CONDITIONAL_PASS
