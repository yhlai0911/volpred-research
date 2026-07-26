# Errata 草稿 — 線上文章 `mile_35eef830`（proxy → 官方日曆取代）

> **狀態：草稿。** 本檔只在 worktree 內產出，供 K528 官方日曆分支
> （`k528-nfp-official-dates`）merge + certify 後的收尾 fire 實際 publish。
> 主線程本輪（round-7）不 publish、不改 `storage/reports/feed.json`。

## 為什麼要補這則 errata（N3）

文章 `mile_35eef830`（〈6 月非農爆冷 5.7 萬，SPY 卻只動 0.13%〉）目前的 `errata`
欄位**只記了 2026-07-18 的事件日更正**（K1442：6 月 NFP 發布日 7/3 → 7/2、T-1 → T+0），
**沒有揭露**文章正文所引用的一整組**proxy 期核心統計量**（254 次公布、NFP vs 週五 1.17 倍、
VIX 高低體制 2.17 倍、相關係數 0.45/0.38 等）已被 **K528 官方 BLS 日曆重跑**取代。
round-6 收件審查把這記為 N3：現有 errata 的「文中已有可見說明」宣稱，比 artifact 裡實際
存在的內容更寬。這則草稿補上 proxy → official 的取代說明與逐項數字更正。

## Errata 更新摘要（擬填入 `errata.update_summary` / `update_history[].summary`）

```
Estimand supersession (K528 official-calendar rerun). 本文核心統計量原出自以「每月第一個週五」
proxy 推導 NFP 發布日的舊版 k528 樣本（254 次公布）。改用官方 BLS Employment Situation 日曆
重跑後，樣本更正為 253 場有效發布（254 場官方發布中，6 場逢 Good Friday 順延到下週一 session、
1 場 2005-01-07 因事件視窗緩衝排除），核心數字同步更新：NFP vs 非 NFP 週五由 1.17 倍更正為
1.189 倍（nominal p=0.0209、n=237 場在週五 session 交易的 NFP；此結果於 6 檢定的 confirmatory
family 通過 Holm 校正 p=0.0417，但對全部 22 個推論輸出的 Holm 校正 p=0.375 不成立，故僅能宣稱
nominal 顯著、confirmatory-family Holm-robust）；NFP vs 全體交易日由 1.10 倍更正為 1.108 倍
（p=0.1121，仍未達顯著）；VIX 高低體制差由 2.17 倍更正為約 2.0 倍（高體制平均絕對報酬 1.13%、
低體制 0.56%，中位切點 16.69，兩組 128/125，p≈0，仍極為顯著）；事前 VIX 對就業日波動的相關
係數由 0.45/0.38 更正為 Pearson 0.44 / Spearman 0.35。文章的**方向性結論不變**：NFP 事件本身
不構成系統性減碼 SPY 的理由，真正牽動就業日波動的是進場當下的 VIX 體制。所有更正僅為 estimand
與樣本口徑更新，不改變上述定性結論。來源：experiments/k528（NFP event study on SPY，官方日曆版）。
```

## 逐項數字更正（擬填入 `errata.content_replacements`）

供收尾 fire 逐條套用；`from` 取自現行 body，`to` 為官方重跑值。

| # | from（proxy，現行 body） | to（official，K528 重跑） |
|---|---|---|
| 1 | `總共 254 次 NFP 公布日` | `總共 253 場有效發布（官方 BLS 日曆 254 場中，6 場逢 Good Friday 順延到下週一 session、1 場因事件視窗緩衝排除）` |
| 2 | `這 254 個 NFP 交易日` | `這 253 個 NFP 交易日` |
| 3 | `那 254 次 NFP 日裡` | `那 253 場有效發布裡` |
| 4 | `NFP 當日波動是這個基準的 1.17 倍` | `NFP 當日波動是這個基準的 1.189 倍`（並補一句：`此為 n=237 場在週五 session 交易的 NFP；nominal 顯著、6 檢定 confirmatory family 通過 Holm，但對全部 22 個推論輸出的 Holm 不成立`） |
| 5 | `差距顯著但不算誇張（1.17 倍）` | `差距顯著但不算誇張（1.189 倍，nominal p=0.0209）` |
| 6 | `對週五基準是 1.17 倍、達到顯著水準` | `對週五基準是 1.189 倍、nominal 顯著（confirmatory-family Holm-robust）` |
| 7 | `這個放大效果（1.10 倍）` / `對全體交易日基準是 1.10 倍` | `這個放大效果（1.108 倍）` / `對全體交易日基準是 1.108 倍` |
| 8 | `分界點是歷史中位數 16.71` / `貼在歷史分界線 16.71` | `分界點是歷史中位數 16.69` / `貼在歷史分界線 16.69` |
| 9 | `VIX 高於中位數的 127 次 NFP，SPY 當日平均絕對報酬是 1.15%；VIX 低於中位數的 127 次，只有 0.53%。兩者相差 2.17 倍` | `VIX 高於中位數的 128 場，SPY 當日平均絕對報酬是 1.13%；VIX 低於中位數的 125 場，只有 0.56%。兩者相差約 2.0 倍` |
| 10 | `高低體制差 2.17 倍` | `高低體制差約 2.0 倍` |
| 11 | `相關係數落在 0.45 左右（換另一種排序算法也給出一致的 0.38）` | `相關係數落在 0.44 左右（Pearson；Spearman 排序法給出 0.35）` |
| 12 | `254 場歷史樣本`（出現 2 次） | `253 場歷史樣本` |
| 13 | 出處段 `共 254 次 NFP 公布日，資料源為 yfinance` | `共 253 場有效發布（官方 BLS Employment Situation 日曆），資料源為 yfinance` |

> **注意**：7/1 VIX 收 16.59 相對更正後的切點 16.69 仍在下緣、仍歸「低 VIX 體制」，
> 因此 7/2 這場實例的敘事（低體制、弱數字、只動 0.13%）**不需更動**。圖片（regime / baseline /
> 懶人包）內嵌的是 proxy 數據，屬後續重製工作，errata 需保留一句「圖表仍為初版數據，正在重新產製」。

## 說明（給收尾 fire / collector）

1. **這是草稿，不是已發佈的 errata。** 主線程本輪不碰 `feed.json`；publish 必須在
   `k528-nfp-official-dates` 分支 **merge 進 main 且 certify 通過後**進行，屆時官方數字才是
   canonical，此 errata 的「取代」宣稱才成立。
2. Publish 走正式流程（`feed-publisher` / admin errata 機制），**不手改 JSON**；`update_action`
   建議用 `estimand_supersession`，與既有的 `event_date_correction`（K1442）並存於 `update_history`。
3. 所有 `to` 值都可回溯到 `experiments/k528/k528_nfp_event_study_results.json`（官方日曆版）：
   `sample.total_nfp_events=253`、`sample.nfp_days_on_friday=237`（在週五 session 交易數）、
   `sample.nfp_releases_dated_friday=243`（發布日在週五數）、
   `main_results.vol_ratio_vs_friday=1.18899`、`main_results.vol_ratio_vs_all=1.10778`、
   `statistical_tests.B_nfp_vs_friday.p_value=0.020854`、`multiplicity.headline_friday_test`、
   `regime_analysis`（median 16.69、high 0.0113 / low 0.0056、n_high 128 / n_low 125）、
   `statistical_tests.E_vix_predictive`（pearson_r 0.4404 / spearman_rho 0.3455）。
4. 定性結論（NFP 不構成系統性減碼理由、驅動源是 VIX 體制）在 proxy 與 official 兩版一致，
   errata 只更新口徑與數字，不改標題與結論走向。
