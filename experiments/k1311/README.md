# K1311 — VIXTWN/VIX ratio 252-day readiness gate（Q6）

**Status**: Scaffold + local data-readiness diagnostic  
**Date**: 2026-05-25  
**Seed**: 42

## 動機

`research_program.md` 把「VIXTWN 數據累積到 252 天後驗證 ratio 穩定性（Q6）」列為開放議題。這題也不是從零開始：

- `K1181` 建立了早期基準：`VIXTWN/VIX ratio = 1.3906`
- `K1308` 用 119 天樣本做了中期更新，得到 `UNSTABLE`，指出 ratio 不是固定結構常數

因此 K1311 的角色不是重做 `K1308`，而是把 Q6 正式整理成一個 **252-day gate**：

1. 本地 `VIXTWN` 樣本目前累積到多少天  
2. 距離 252 天門檻還差多少  
3. 到達 252 天後，正式穩定性驗證應如何執行與報告

## 研究問題

當 `VIXTWN` 累積到約一個交易年（252 天）後，`VIXTWN/VIX` ratio 是否會收斂到穩定分布，還是會延續 `K1308` 已觀察到的顯著時變性？

## 與既有實驗的差異化

1. `K1181` 是早期 paper-sourcing / baseline 驗證
2. `K1308` 是 119 天中期更新，已經給出 `UNSTABLE` 的方向性證據
3. `K1311` 不再新增半成熟結論；它固定 **252-day readiness** 與後續正式檢定設計

## 相關先驗知識

- `K1181`: `ratio = 1.3906`
- `K1308`: 119 天更新後 `mean=1.5737`, `CV=0.204`, `UNSTABLE`
- `research_program.md` 已把 ratio 視為 Paper 2 的一個樣本期敏感數字，不能當普適常數

## 資料來源

- `data/vixtwn/vixtwn_daily.csv`
  - 本地 VIXTWN 日資料唯一來源
- `paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv`
  - 含 `vix_close`，供 ratio 對照用

## 當前診斷目標

這一輪只回答：

1. `vixtwn_daily.csv` 目前有多少有效交易日？
2. 以 252 天為正式 gate，完成度是多少？
3. 目前階段是否適合再做新一輪完整穩定性論述？

## 正式 252-day 驗證計畫

當樣本達到 `>=252` 天後，正式版應至少包含：

1. 全期 ratio 統計：mean / median / std / CV / quantiles
2. rolling 視窗穩定性：30d / 60d / 90d
3. time trend：OLS / 更穩健的結構變動檢查
4. 與 `K1181` / `K1308` 的樣本期對照
5. 明確報告：
   - 是否仍能把 ratio 視為固定轉換常數
   - 若不能，Paper / article 應如何改口徑

## Lookahead 政策

本題是描述統計與穩定性檢查，不涉及交易訊號與報酬乘積，無傳統 lookahead 問題；但所有比較必須嚴格標明樣本截止日，避免用未來樣本修飾早期敘述。

## 成功標準

1. 建立 `experiments/k1311/` 三件套
2. 把本地 `VIXTWN` 天數、起訖日期、距 252 還差多少寫入結果 JSON
3. 明確區分：
   - readiness diagnostic
   - future full 252-day validation
4. 若未達 252 天，要誠實回報 `NOT_READY_BELOW_252D_GATE`

## 當前預期結論

在 `K1308` 已指出 119 天樣本不穩定的前提下，`K1311` 這輪預期只會得到：

- 尚未滿 252 天
- 暫不新增正式結論
- 保留 `K1308` 作為最新中期證據
