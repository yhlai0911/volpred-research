# K1679-rev2 — H.8 deposit flight 對 KRE forward RV/DSV

**Codex verdict: CONDITIONAL_PASS.** 真正 point-in-time（PIT）的 H.8
small-minus-large deposit-flight 訊號，沒有帶來穩健的 KRE forward-volatility
增量預測力；內部結果標記為 `safe_null`。這裡的 NULL 只表示「未能擊敗既有
HAR + SPY RV + VIX baseline」，不表示 deposit flight 對銀行風險沒有經濟關係。

## 研究問題與資料

本實驗是 K1679、K1679-rev 兩次 FAIL 後的第三版修訂，檢驗公開 H.8
小型銀行相對大型銀行的存款流失，能否預測 KRE 未來 5/21 交易日的 Parkinson
realized variance（RV）與 downside semivariance（DSV）。這是實證預測檢驗，不是
因果識別。

| 資料 | 來源與處理 |
|---|---|
| 小型銀行存款 | FRED/ALFRED `DPSSCBW027SBOG`，週頻 |
| 大型銀行存款 | FRED/ALFRED `DPSLCBW027SBOG`，週頻 |
| 價格與控制 | yfinance adjusted KRE/XLF/SPY 與 `^VIX` |
| 真 PIT origin | ALFRED `output_type=4` 的正式 initial-release 日期 |
| 真 PIT snapshot | ALFRED `output_type=1` 完整分頁 revision history；每個 release 日取當時有效 revision |

真 PIT modelling sample 為 2012-08-27 起；H=5 到 2026-07-02，OOS
2020-12-14 起、1,393 筆；H=21 到 2026-06-09，OOS 2020-12-01 起、
1,386 筆。ALFRED archive 前的舊觀測只作 release 當時可見的 trailing history，
不充當 forecast origin。

## 方法

- 訊號：`-z(log-growth_N(small) - log-growth_N(large))`，N=4/13 週，
  trailing 52-week z-score；高值代表小型銀行相對存款流失。
- Baseline：`1 + HAR(d,w,m) + SPY 21d RV + VIX`；augmented model 只多一個
  deposit-flight predictor。
- OOS：60% initial window、expanding refit。forecast origin `i` 的訓練列 `j`
  強制 `j + H < i`，即 forward target end 嚴格早於 forecast origin。
- 每格各自使用 target horizon `H` 作 NW-HAC lag；DM 採 HLN small-sample
  correction，`d = loss_aug - loss_base`，所以正 t 表示 deposit model 較差。
- Clark-West (2007)：nested MSPE adjustment、raw unfloored forecasts、單尾
  upper-tail；全部 8 個 primary cells 均實跑。DM 與 CW 分別在 m=8 family 做
  Bonferroni 與 BH。
- Primary loss：RV 用 canonical QLIKE；DSV 用 MSE。另保留 unfloored MSE
  sensitivity。
- Moving-block bootstrap：2,000 reps，`block=max(10,H)`；所有隨機程序
  `seed=42`。

## 三修與救援修正

1. **真 PIT vintage。** 孤兒 agent 版本只讀 ALFRED 首頁 100,000 列，實際
   API count 為 281,186 / 274,847；結果只含 2004–2009 observation dates，
   merge 後生成標準差 0 的假 PIT。rev2 最終版完整抓 3 pages/series，要求
   received count 等於 API count，並用 `output_type=4` 定義 genuine release
   origins、`output_type=1` 重建 release-day snapshot。
2. **CW 跑真正 hit 與全 8 格。** K1679-rev 的
   `dep_flight_13w·rv·H5` 根本沒跑 CW；本版每個 primary cell 都有單尾 CW，
   並額外校正 CW 的 m=8 搜尋。
3. **verdict 納入方向與 Bonferroni。** 正 DM t 是 augmented model 變差。
   因此 first-release-only 的顯著格列為 `documented_negative`，不再誤稱
   FDR-only artifact。若不同格同時有校正後正、負證據，程式回
   `mixed_documented`，不讓單一方向蓋掉另一方向。

另外新增 fail-closed construct gates：pagination 完整、open-ended ALFRED
window 正確解析、release lag 合理、訊號至少 100 筆/20 個 unique、標準差大於
`1e-6`、交易日 signal age 不超過 45 天。最終真 PIT 有 725 個 weekly values，
13w 訊號 std=1.198、725 unique；交易日 age 9–23 天，SVB peak=3.967。

## 結果

| Vintage | 結論 | 最強 primary cell | DM t / raw p | Bonf / BH | CW t / 單尾 p |
|---|---|---|---:|---:|---:|
| current revised | `safe_null` | 4w·DSV·H5 | +1.775 / .0761 | .609 / .340 | -1.794 / .964 |
| first-release-only sensitivity | `documented_negative` | 13w·RV·H5 | +2.772 / .00565 | .0452 / .0452 | -0.281 / .611 |
| true PIT snapshot | `safe_null` | 13w·DSV·H5 | +1.946 / .0518 | .414 / .319 | -2.019 / .978 |

first-release-only 的 13w·RV·H5 令 QLIKE **惡化 3.72%**，且 DM 通過
Bonferroni；這是「訊號傷害 forecast」的 negative finding，不是預測成功。
真 PIT 的 8 個 DM t 全為正，但沒有 raw p<.05、BH/Bonferroni rejection、
Harvey |t|>3 或 CW rejection；最強格也只是未校正 p=.0518。unfloored DSV/MSE
sensitivity 同樣沒有顯示增量改善。

所以可採用的窄結論是：**公開且按當時 vintage 重建的 H.8 size-cohort
deposit-flight，沒有穩健改善 KRE 5/21 日 RV/DSV 預測。**

## 限制

- 真 PIT archive 只從 2012-08 開始，不能用同一 vintage discipline 覆蓋 2008
  GFC；因此不宣稱跨 GFC regime 的 universal null。
- H.8 size cohort 不是 regional-bank 或 uninsured-deposit bank-level panel；結論
  不外推到 FFIEC bank-level、proprietary 或 intraday flow data。
- RV 使用免費資料可重建的 Parkinson variance，不是 5-minute total RV。
- CW 的 HLN/t calibration 是保守延伸；JSON 同時保留 raw 與 HLN statistics。

## 重現與檔案

```bash
uv run python experiments/K1679-rev2/K1679-rev2.py
```

需要 `.env.local` 的 `FRED_API_KEY` 與 live yfinance。Heavy rerun 由正式
compute queue 完成；結果檔採 temp-write、parse validation、`os.replace`。

- `K1679-rev2.py`：資料、PIT reconstruction、OOS 與 inference 全流程
- `K1679-rev2_results.json`：三 vintage、所有 cells 與 audit gates
- `K1679-rev2_fig_pit_vs_current.png`：訊號與 primary DM grid
- `CODEX_REVIEW.md`：獨立 code/result review 與具體行號

方法參考：Diebold & Mariano (1995)；Harvey, Leybourne & Newbold (1997)；
Clark & West (2007)；Harvey, Liu & Zhu (2016)。ALFRED API 規格見
`fred/series/observations` 與 `fred/series/vintagedates` 官方文件。
