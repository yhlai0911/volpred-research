本輪認證：**FAIL**。

NULL 本身不像是由 estimator bug 製造；round-1 的主要修復也沒有回歸。但 round-2 的 R2-B、R2-D 尚未真正完成，因此現在不能寫入 `knowledge.json`。

## Blocking defects

1. **DCOT head completeness 有具體反例。**

`MAX_DCOT_HEAD_GAP_DAYS = 8` 無法偵測月初漏掉第一份週報。以 GOLD 2024-10 為例，原始報告日為 1、8、15、22、29 日；刪除 10/1 後：

- `nweeks = 4`
- head gap = 7
- interior gap = 7
- tail gap = 2
- `dcot_complete = True`

我直接用目前的 `monthly_coverage()` 重現了這個結果。這反駁了 `K1694.py:98-106, 392-400, 484-488`、results completeness disclosure 及 `README.md:81-85` 所稱「head / middle / tail 任一漏週都會形成約 14 天 gap」。

現有測試只注入 interior gap（`test_K1694.py:167-182`），因此 31 gates 全過並不能守住這個缺陷。需要依 CFTC 預期報告日／假日調整 calendar 驗證，並加入 head、tail negative cases；單純把 head threshold 降低會誤殺合法假日月份。

2. **RV 規則仍不能證明下載 reached both ends。**

規則只有月度 `ndays`，沒有第一與最後實際價格日期。若所有商品共同少掉月末 1–5 個 weekdays：

- business-day shortfall 仍 ≤ 5；
- cross-sectional shortfall = 0；
- 該月會被判定 complete。

因此 cross-sectional max 在共同截斷時確實會失效，而 business-day anchor 只會擋下超過五天的共同截斷。目前 cache 中除了 2026-07，沒有共同 shortfall ≥3 的可疑月份，但共同少 1–2 天究竟是正常假日還是截斷，現有 artifact 無法證明。

若要繼續宣稱「完整月份」及 “reached both ends”，cache 必須保存並檢查實際首末觀測日期，搭配適當交易日曆；否則必須收斂完整性宣稱並提供 frozen cache 的獨立 endpoint 證據。

3. **R2-B 仍有直接的 absence wording。**

雖然總 verdict 已改為 NOT SUPPORTED，以下位置仍寫成效果不存在：

- `README.md:32,72`：「這個時序安排下沒有關聯」
- `K1694.py:23,794,1150,1239`
- `K1694_results.json` 的 spec4 reading：“no association survives this timing arrangement”

這與同一 artifact 所說「estimators cannot establish absence」矛盾。應統一改成「此時序安排下未獲得關聯的支持」／“an association is not supported under this timing arrangement”。

另有一處報告範圍不一致：README 稱 `3276/3276` estimation rows 都有 within-month overlap，但 `data_provenance.fcm_avail_inside_outcome_month_rows` 是 3278，因為 `K1694.py:1170-1171` 計算的是 `panel` 而非 `frame`。應修正欄位 scope 或從 estimation frame 計算。

## 已確認完成的部分

- R2-A 的 compute path 正確：spec4 使用真正的 t−2 DCOT controls、自有 `build_lagged_frame()`，以及 t−1 PIT volatility label。
- t−2 DCOT 在正常 Tuesday-as-of／Friday-publication 節奏下有充足緩衝。t−1 RV 在月底收盤後計算、供下月使用，也沒有一般發布落差；但 yfinance cache 仍不是經核實的 PIT vintage。
- R2-C 的 OI guard 確實位於 regression production path。pre-log finite/positive mask 是關鍵；後置 finite sweep主要是冗餘防禦。
- `_within_ols()` 與 entity-FE `PanelOLS` 相同；真實 3276-row sample 的 recorded difference 為 \(7.05\times10^{-19}\)。bootstrap 共用包含 `t` 的 `SPEC1_RHS`，stationary bootstrap 實作與 headline naming 正確。
- Provenance 一致：on-disk script、spec entrypoint、results code trace 都是 `2c84e12…`；result bytes 與 canonical identity 都是 `538fedb8…`。
- NULL 不像由 dynamic controls 製造。唯讀重算的 interaction coefficient保持正值：
  - full：`+3.0553e-04`
  - 移除 dynamic/OI controls：`+2.5945e-04`
  - 移除 `dlog_oi`：`+3.9576e-04`
  - 只保留 `dlog_oi` control：`+1.9927e-04`

T=149 下 Nickell bias 值得列為限制，但不足以合理解釋這種穩定正號。有效時間自由度不必硬估一個缺乏唯一依據的數字；現有 ACF 與「遠低於 149」的披露是適當的。

因此，我認證的是 FAIL：先修正上述 completeness false guarantees、absence wording 與 scope mismatch，加入能重現 head/common-truncation 反例的 gates，再重跑全部 artifacts。

VERDICT: FAIL
