# K1378 — 修正後的廣義疫情窗排除檢驗

> **狀態：2026-07-15 已重新計算並通過 pre-run 獨立 code review。** 舊 K1378 使用反向
> QLIKE、在 `h=1` 退化成 iid 的 local DM、fit/OOS 不一致的 A4f normalization，以及未鎖
> hash 且已有重複日期的輸入；舊數字與舊敘事均失效。本次結果只修正 K1378 自己的廣義窗口
> sensitivity claim。K1393 仍是 Paper 9 的窄窗口（2020-02-01 至 2020-06-30）canonical
> evidence，本實驗不得覆寫已提交論文的 K1393 表格。

## 1. 問題與結論

K1378 問的是：A4f 相對 GJR-GARCH 的樣本外 QLIKE 優勢，是否只是由 2020-03-01 至
2021-06-30 的廣義 COVID 窗口驅動？

答案是否定的。排除該窗口後，A4f 的平均 QLIKE 為 1.4083，GJR 為 1.4808；以
`A4f loss − GJR loss` 定義差額，Bartlett-HAC DM t = −5.603（p = 2.49e−08，lag 12），
通過專案的 `|t| > 3` 報告門檻。COVID 窗口本身 t = −1.344（p = 0.180），未通過門檻；
因此證據支持「優勢可在疫情窗外觀察到」，不支持「優勢特別來自疫情」。

## 2. 資料與可重現性

- 來源：`experiments/k1685/data/k1685_spy_vix_snapshot.csv`
- 完整快照 SHA-256：`eee7f9c62ce3ed3ee68d2bffeb3c9386fb8a6343e1a053379cfc89058518e3fb`
- 固定分析終點：2026-05-18；分析 slice SHA-256：
  `c74fb12f046513fd705f9dc0c301a8fd726454f6509ca4e754e0689204a60e65`
- 資料期：2000-01-04 至 2026-05-18，共 6,632 筆完整 SPY/VIX 日資料
- OOS forecast dates：2019-01-02 至 2026-05-18，共 1,854 筆
- 共同有效評分樣本：1,852 筆；因 `r² <= 1e-16` 排除 2022-08-11、2023-07-21
- 程式 SHA-256：`dd143a220cffa3ee27c3df54bfee564809733aaf9ea4a801ed1d38cbe030bf21`
- seed：42（本估計本身為確定性 multistart；保留 seed 作 provenance）

loader 會 fail closed 驗證快照 hash、必要欄位、唯一且嚴格遞增日期。所有 1,854 筆兩模型
forecast 也必須 finite 且大於零，否則不寫 results。

## 3. 方法

- 模型：A4f（`tau_t = theta0 + theta1 * VIX²_{t-1}`）對 GJR-GARCH(1,1)
- Rolling estimation：W = 2,000；每 63 日 refit，共 30 次
- 資訊集：day-t forecast 僅用 `r_{t-1}` 與 `VIX_{t-1}`
- A4f normalization：fit 與 OOS 都使用由 `VIX_{t-1}` 預先決定的 `tau_t`，即
  `u_{t-1} = r_{t-1} / sqrt(tau_t)`
- Loss：以日平方 log return 為 proxy 的 actual-first Patton QLIKE：
  `actual/predicted - log(actual/predicted) - 1`
- 推論：`volpred.stats.model_evaluation.dm_test`；每個 period 個別用
  `max(1, min(ceil(h^(1/3) n^(1/3)), n//4))` 選 Bartlett Newey-West lag
- 方向：DM t < 0 代表 A4f loss 較低；DM t > 0 代表 GJR loss 較低
- 報告門檻：`|t| > 3`，winner 另依 sign 判斷；不能用 `abs(t)` 反推模型方向
- COVID 排除只作用於 scoring。疫情後的 trailing estimation window 仍可能含疫情觀察值，
  這不是「把 COVID 從模型估計資料刪除」的 counterfactual。

每個 period 另保存 loss-differential ACF(1–5)、canonical lag、lag 0/1/5/10/canonical/20
sensitivity，以及正確 HLN small-sample factor作非主要診斷。

## 4. 結果

| 評分期 | n | A4f QLIKE | GJR QLIKE | DM t | p | HAC lag | `|t|>3` winner |
|---|---:|---:|---:|---:|---:|---:|---|
| 全 OOS | 1,852 | 1.399812 | 1.479503 | −4.370 | 1.31e−05 | 13 | A4f |
| 疫情前 | 292 | 1.507945 | 1.576680 | −2.640 | 0.00873 | 7 | none |
| 廣義 COVID 窗口 | 337 | 1.361748 | 1.473725 | −1.344 | 0.1798 | 7 | none |
| 疫情後 | 1,223 | 1.384483 | 1.457894 | −4.922 | 9.74e−07 | 11 | A4f |
| 排除廣義 COVID 窗口 | 1,515 | 1.408279 | 1.480788 | −5.603 | 2.49e−08 | 12 | A4f |

全期 lag sensitivity 的 t 從 lag 0 的 −4.232 到 lag 20 的 −4.504；排除疫情窗則從
−5.052 到 −5.783，方向與 `|t|>3` 判讀均未改變。全期 ACF(1) = −0.0228、排除疫情窗
ACF(1) = −0.0546；舊 iid implementation 在這次資料上的量化影響不大，但方法上仍不可接受。

主要 verdict 是 `A4F_ROBUST_OUTSIDE_BROAD_COVID_WINDOW`。較細分結果顯示顯著性主要出現在
疫情後，而不是 COVID 窗口本身；pre-COVID 的 conventional p < 0.05 仍未達專案較嚴格的
`|t| > 3` 報告門檻。

## 5. 舊結果為何失效

本次同時修正：

1. QLIKE 由錯誤的 `predicted/actual` 改為 `actual/predicted`。
2. 移除 `h=1` 時零 autocovariance 的 local DM，改用 canonical Bartlett-HAC DM。
3. A4f OOS recursion 改為與 fit 一致的 contemporaneous predetermined `tau_t`。
4. 改用 hash-pinned、unique-date input 並固定分析終點。
5. optimizer 只接受 success、finite 且 A4f feasible 的解；所有 starts 失敗即中止。
6. arrays 與 JSON 均採同目錄 temporary file、驗證後 `os.replace`。

因為這些修正是聯合發生，新舊結果差異不能歸因於其中單一項。舊文章所稱「拿掉 COVID
後複雜模型仍未翻身」與「只看 COVID 也未站上風」不可再使用；前者被新結果直接推翻，後者
則只能說 COVID-only 差異沒有通過門檻。

## 6. 限制

- 日平方報酬是噪音很高的 latent variance proxy；Patton 的 robustness 是在 conditional
  unbiasedness 等條件下的 expected-loss 性質，不保證每個有限樣本。
- 這是單一資產、單一資料 vintage、單一模型對與預先指定廣義窗口的 sensitivity analysis。
- 五個 period 共用資料並非五個獨立 confirmatory tests；細分結果應視為診斷，不作額外的
  多重檢定式 overclaim。
- Scoring-only exclusion 不能回答「若模型從未看過 COVID 資料」的 counterfactual。

## 7. 產物

- `k1378.py`：唯一計算入口
- `k1378_results.json`：完整 metadata、period inference、repair audit trail
- `k1378_losses_a4f.npy`、`k1378_losses_gjr.npy`：逐日 actual-first QLIKE
- `k1378_valid_mask.npy`、`k1378_no_covid_mask.npy`：共同評分與日期 masks
- `k1378_plot.py`：result-driven、hash-verified、atomic 圖表生成器
- `k1378_dm_subperiods.png`：五個 period 的 HAC-DM 圖
- `storage/drafts/assets/k1378_loss_gap_rolling.png`：文章用 63 日 rolling loss-gap 圖
- `storage/drafts/assets/k1378_period_gap_bars.png`：文章用五期 mean loss-gap 圖

## 8. 參考文獻

- Patton, A. J. (2011), *Journal of Econometrics*, 160(1), 246–256.
  DOI: 10.1016/j.jeconom.2010.03.034
- Diebold, F. X. and Mariano, R. S. (1995), *JBES*, 13(3), 253–263.
  DOI: 10.1080/07350015.1995.10524599
- Newey, W. K. and West, K. D. (1987), *Econometrica*, 55(3), 703–708.
  DOI: 10.2307/1913610
- Harvey, D., Leybourne, S. and Newbold, P. (1997), *International Journal of
  Forecasting*, 13(2), 281–291. DOI: 10.1016/S0169-2070(96)00719-4
