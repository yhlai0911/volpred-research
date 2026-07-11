---
audience: research
description: "2026-07-12 更正：K1025 v3 修復 FEVD 軸序、控制 VIX 持續性並重做 OOS。原公開文章 v1 的 90.11% 連動、−76.89pp 淨接收與尾部放大 8.5 倍均撤回。"
experiment_refs:
  - K1025
  - K865
  - K746
  - K639
---

[提出: 用戶, 執行: Codex]

> **2026-07-12 研究更正**：原公開文章使用的 K1025 v1 Diebold-Yilmaz 結果切錯
> `statsmodels` FEVD 陣列軸序，v1 的 90.11% 總連動與 −76.89pp BTC 淨接收量均無效。
> v1 分位數迴歸也未控制 VIX 自身持續性，所稱「右尾放大 8.5 倍」在正確控制後消失。
> 本文已用 K1025 v3 的 pinned snapshot 與重跑 JSON 全面改寫。非對稱 Granger 段落不經
> FEVD 或分位數迴歸，暫時保留為一項獨立的預測關聯結果。

## 摘要

K1025 v3 使用 2015-02-02 至 2026-04-08 的 2,812 個交易日，重新估計 BTC、SPY 與 VIX
的波動連動。排序不變的 generalized FEVD 顯示總連動為 19.52%，BTC 淨值僅 −0.95pp；
原公開文章 v1 的 90.11% 與 −76.89pp 來自 FEVD 取軸錯誤。分位數迴歸加入 VIX 前一期後，BTC 波動在
VIX 95% 分位的係數為 +0.42，95% bootstrap 區間跨過零。OOS 比較也未見 BTC_RV 改善
VIX 預測：全期 MSE 惡化 0.32%，DM t=−0.99，Clark-West t=−0.12。

## 更正原因

`statsmodels` 的 `FEVD.decomp` shape 是 `(變數, horizon, shock)`。舊程式使用
`decomp[-1]`，取到最後一個變數跨 horizon 的表，再把 horizon 誤認成資產。陣列仍是二維，
下游算術不會報錯；純 iid 高斯雜訊也能被同一誤切製造出約 67% 的假連動。

v3 改用 `decomp[:, -1, :]`，另以 Koop-Pesaran-Potter / Pesaran-Shin generalized FEVD
作主估計。機械 gate 將 iid placebo 上限設為 5%；四個固定 seed 的實測值約 0.3% 至 0.7%。
同類 FEVD 軸序錯誤也曾影響 K865，因此本次修正同時保留 clean-tree 掃描，禁止未標記的
`.decomp[-1]` 再進入出貨程式。

![K1025 v1 舊圖：下跌與上漲波動的 Granger 預測關聯；圖內沿用檢定名稱「因果性」，不代表結構性因果](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/grouped_bar_69ba75.png)

![K1025 v3：generalized FEVD、rolling 連動、分位數迴歸與 OOS 檢定](experiments/k1025/k1025_v3_results.png)

## 方法與數據

| 項目 | K1025 v3 設定 |
|---|---|
| 數據 | pinned `spy_btc_usd_vix_2015-2026.csv`，`auto_adjust=False` adjusted close |
| 期間 / 樣本 | 2015-02-02 至 2026-04-08；N=2,812 |
| 報酬 | SPY 與 BTC 均用 log return；先移除價格缺值再計算報酬 |
| 波動代理 | 20 日 rolling standard deviation，年化乘上 √252；VIX 用 level |
| FEVD | VAR AIC grid 1 至 5、horizon 10；generalized FEVD 為主，兩種 Cholesky 排序為敏感度 |
| Rolling | 252 日視窗、step 5、VAR maxlags 5；512 個窗口 |
| 分位數迴歸 | `VIX_t ~ BTC_RV_{t-1} + VIX_{t-1}`；moving-block bootstrap B=1,000、block 15、seed 42 |
| OOS | 2019-01-01 起；rolling train 756；AR(1) 至 AR(22) 用共同 `hold_back=22` 比 AIC，選 p=3 |
| 預測檢定 | Newey-West HAC DM 與 nested-model Clark-West；另報 bandwidth sensitivity |

三條 VAR 序列的 ADF p-value 均低於 0.001，因此 FEVD 主規格使用 levels。FEVD 的 VAR lag
grid 保留 paper 原設定 maxlags 5；brief 中「grid 延到 22」指 OOS AutoReg，不能拿來改動
FEVD 的預設規格。

## 發現一：總連動降到 19.52%，BTC 淨方向接近零

| FEVD 估計 | Total connectedness | BTC net（TO − FROM） |
|---|---:|---:|
| Generalized KPPS（主結果） | **19.52%** | **−0.95pp** |
| Cholesky {BTC, SPY, VIX} | 12.57% | +10.55pp |
| Cholesky {VIX, SPY, BTC} | 16.69% | −8.11pp |
| 舊版誤切，同一個 VAR fit | 66.79% | 無有效解讀 |
| 原公開文章 v1 報告值 | 90.11% | −76.89pp |

只更換 Cholesky 排序，BTC net 就從 +10.55pp 翻成 −8.11pp，擺盪 18.66pp。Generalized
FEVD 在變數重排後的 total gap 只有 5.6×10⁻¹²pp，通過排序不變性檢查。主規格下 BTC_RV
的預測誤差變異有 89.3% 來自自身；VIX shock 解釋 6.2%。BTC 在三變數系統中較接近外圍
資產，−0.95pp 的 net 值不足以支撐「強烈淨接收者」敘事。

方向判讀還有一個限制。Levels VAR 在 lag 1、2、5、10、22 的 BTC net 都為負，範圍為
−0.95pp 至 −4.96pp；改用一階差分後，BTC net 翻成 +1.92pp。排序問題獲得處理後，
levels/differences 的轉換選擇仍會改變方向，結論只能寫到「主規格略偏接收」。

## 發現二：連動性會隨市場狀態變化

252 日 rolling generalized TCI 共 512 個窗口。平靜期 2017 至 2019 的平均為 20.76%，
COVID 視窗 2020-02 至 2020-06 升至 36.16%。全期平均 22.75%，最低 6.29%，最高
47.02%；峰值日期為 2021-02-24。危機期連動上升的現象在修正後仍看得到，峰值卻不在
本文定義的 COVID 視窗內，故不能再把最高點直接貼上 COVID 標籤。

BTC 在 72.5% 的 rolling 窗口中 net 為負。比例支持「多數窗口偏接收」的描述，仍有
27.5% 的窗口方向相反。兩種 Cholesky 排序只在 43.8% 的窗口同意 BTC net 正負號，
進一步排除用單一 Cholesky 排序下方向結論的做法。

## 發現三：控制 VIX 持續性後，尾部放大消失

| 分位數 τ | 未控制 VIX lag：BTC_RV 係數 [95% CI] | 加入 VIX lag：[95% CI] |
|---:|---:|---:|
| 0.05 | −2.81 [−3.85, −1.93] | −0.33 [−0.63, −0.02] |
| 0.25 | −1.51 [−3.75, +2.08] | −0.20 [−0.33, −0.03] |
| 0.50 | +2.59 [−0.80, +7.43] | −0.18 [−0.31, −0.07] |
| 0.75 | +8.23 [+1.76, +14.89] | −0.02 [−0.21, +0.23] |
| 0.95 | +16.29 [+0.76, +24.69] | **+0.42 [−0.61, +1.14]** |

原公開文章 v1 未控制 VIX lag，低分位負、右尾正的形狀會出現。加入 `VIX_{t-1}` 後，95% 分位的
係數縮到 +0.42，bootstrap 區間跨零；低尾與高尾也未同時顯著。舊文章所稱「右尾放大
8.5 倍」是 v1 數字，不通過存活測試，已撤回。係數縮水與 VIX 自身持續性解釋一致，目前沒有 BTC_RV
提供增量尾部資訊的證據。

## 發現四：OOS 未見預測改善

| 子期間 | n | MSE 改善率 | DM t | Clark-West t |
|---|---:|---:|---:|---:|
| Full OOS | 1,826 | −0.32% | −0.99 | −0.12 |
| 2019 | 252 | −0.02% | −0.20 | −0.11 |
| 2020 | 253 | −0.07% | −0.09 | +0.28 |
| 2021–2022 | 503 | −0.49% | −0.82 | +0.21 |
| 2023–2026 | 818 | −0.53% | −2.75 | −2.55 |

AR(p)+BTC_RV 在所有列的 MSE 都略高於純 AR(p)。Full OOS 的 DM 與 Clark-West 統計量
均未達各自門檻；2023 至 2026 的絕對值雖較大，也未通過專案採用的嚴格 |t|>3 規則。
適當結論是「目前未見改善證據」。統計檢定未拒絕等預測力，無法證明 BTC 的增量資訊
精確等於零。

OOS 選模也修了一個容易漏掉的細節。`AutoReg` 若不指定共同 `hold_back`，AR(p) 候選會
各自刪掉 p 筆，AIC 比較的是不同樣本。本輪尚未定稿的初版 v3 因此選到 grid 上界 p=22；
v2 JSON 原本是 p=10，兩者都不是最終 v3 規格。固定 942 筆共同 IS 樣本後，AIC 選 p=3；
上表已用 p=3 全數重算。

## 哪些舊結論仍可保留

K1025 v1 與 v2 的非對稱 Granger 結果不依賴 FEVD 軸序，也不使用本文修正的分位數迴歸規格。
BTC 下跌波動對 VIX 在 lag 1 至 5 為 5/5 顯著，BTC 上漲波動則為 0/5。該結果仍可作為
「下跌波動含有領先資訊」的證據，不能延伸成結構性因果，也不能推導出 OOS 可交易性。
K639 與 K746 系列提供相關的 lead-lag 與非對稱背景；K865 記錄同一 FEVD bug class 的
另一個回溯更正。

上方非對稱圖來自 v1 `k1025_results.json`（前三個下跌波動 F 值約 18.96、14.79、10.18）。
v2 重跑的對應值為 21.78、19.57、13.11，仍維持 5/5 對 0/5 的方向模式。圖內「Granger
因果性」是檢定慣用名稱；本文只把它解讀成 lagged predictive association。

舊文的 BTC-SPY regime correlation 圖與數字未納入 K1025 v3 重跑，本次更新不再用它們
支撐核心結論。完整 pinned rerun 若要恢復該段，須另產生對應 results JSON。

## 實務意義

1. BTC_RV 不適合直接當成 VIX 預測模型的增量因子。現有 OOS 誤差沒有改善，最好的子期間
   也未通過嚴格統計門檻。
2. 壓力測試可以保留 BTC 與股市波動在危機期連動上升的情境，但 19.52% 的全樣本 TCI
   與時變 rolling 路徑應取代舊版固定在 90% 附近的圖像。
3. BTC 的 net direction 接近零且對資料轉換敏感。資產配置或風控報告不應再寫成
   「BTC 是強烈淨接收者」。
4. 論文中的 FEVD、QR、摘要、結論與期刊定位都要依 v3 重寫；本次文章更正不等於論文已
   通過投稿 gate。

## 限制與下一步

- RV(20) 是日資料代理，沒有使用高頻 realized volatility。
- 三變數系統未納入美元、利率、ETF flows 或 crypto-native volatility index。
- Generalized FEVD 交換了排序依賴與非正交 shock 的取捨，net 值不宜作結構性因果解讀。
- FEVD 主規格的 AIC 在 maxlags=5 邊界；lag sensitivity 已列到 22，一階差分方向翻轉仍是
  必須保留的警示。
- K1025b 的 QQQ/VXN 對稱驗證仍使用舊 FEVD 路徑，需按 v3 規格重跑後才能恢復跨市場論證。

## 復現路徑

- 實驗說明：`experiments/k1025/README.md`
- Canonical script：`experiments/k1025/k1025_v3.py`
- 結構化結果：`experiments/k1025/k1025_v3_results.json`
- 結果圖：`experiments/k1025/k1025_v3_results.png`
- 機械 gate：`scripts/tests/test_fevd_shape.py`

測試命令：

```bash
uv run --extra dev python -m pytest \
  scripts/tests/test_fevd_shape.py \
  scripts/tests/test_dm_hac_lag_ratchet.py -q
```

目前結果為 24 tests passed。舊 `k1025_results.json`（v1）與 `k1025_v2_results.json`
原地保留作 audit trail；`experiments/k1025/README.md` 與 v3 JSON 的 `supersedes` 欄已明確
標示舊 FEVD 數字失效。

## 結論

K1025 v3 保留下跌波動的 Granger 非對稱背景，也撤回兩個核心強宣稱。修正後的總連動為
19.52%，BTC net 僅 −0.95pp；控制 VIX 持續性後，右尾係數不顯著；OOS 未見 BTC_RV
改善 VIX 預測。可防守的研究敘事集中在危機期連動升高與 BTC 的系統外圍性，淨方向與
尾部放大都沒有足夠證據承擔原稿的因果故事。

*數據來源：paper-local pinned snapshot（SPY、BTC-USD、VIX adjusted close），期間
2015-02-02 至 2026-04-08，N=2,812。主要證據來源：K1025 v3 results JSON；非對稱
Granger 圖來自 v1，方向模式另以 K1025 v2 results JSON 對照。*
