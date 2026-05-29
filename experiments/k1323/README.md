# K1323: VIXTWN 數據累積到 252 天後驗證 ratio 穩定性（Q6）

**Date:** 2026-05-29  
**Status:** COMPLETE  
**Type:** readiness update / source-freshness audit

## 問題

`research_program.md` 把 Q6 定義為：

> VIXTWN 數據累積到 252 天後，重新驗證 `VIXTWN / VIX` ratio 是否穩定。

到 `K1321` 為止，我們已知道兩件事：

1. 252-day gate 其實還沒到
2. 在未達 gate 的中期樣本裡，ratio 已經明顯不穩定

`K1323` 的目的不是硬做一年結論，而是更新到 2026-05-29 這一刻，回答兩個更務實的問題：

1. `VIXTWN` 本身到底累積到幾天了？
2. 目前 gate 卡的是 `VIXTWN` 不足，還是配對用的本地 `VIX` snapshot 也已過期？

## 方法

### Primary local gate

沿用 `K1321` 的本地口徑：

- `data/vixtwn/vixtwn_daily.csv`
- `paper/taiwan-vt/data/...spy_vix_2008-2026.csv` 內的 `vix_close`
- 去重規則：`sort by date -> drop_duplicates(date, keep="first")`
- 對齊規則：date-label intersection

這條線的好處是和 `K1321` 完全可比；壞處是本地 `VIX` source 可能已 stale。

### Freshness audit

額外拉一份 **experiment-scoped** `^VIX` yfinance snapshot：

- 只存進 `experiments/k1323/data/vix_yfinance_snapshot.csv`
- 不回寫 shared `storage/` 或 `paper/` canonical data
- 目的只是檢查：如果把 `VIX` 補到和 `VIXTWN` 同樣新，結論會不會翻轉

## 主要發現

### 1. 252-day gate 仍未達

- `VIXTWN` unique days = `116`
- progress = `46.0%`
- days remaining to 252 = `136`

所以這一題目前**還不能誠實宣稱完成「一年穩定性驗證」**。

### 2. 舊本地 VIX pairing source 已經 stale

- `VIXTWN` 已到 `2026-05-28`
- local `vix_close` 只到 `2026-05-19`
- 因此 primary local gate 只能形成 `108` 天交集

也就是說，現在不只 `VIXTWN` 不足 252 天，連配對用的 shared local `VIX` snapshot 也落後了。

### 3. 就算補上 fresh VIX，ratio 仍然不穩定

Primary local gate：

- overlap `n = 108`
- mean ratio = `1.5182`
- CV = `0.1851`

Fresh VIX audit：

- overlap `n = 115`
- mean ratio = `1.5527`
- CV = `0.1968`

兩條線都比 `K1181` baseline 明顯更高：

- `K1181 mean = 1.3906`
- 而且 time trend 仍顯著為正

所以 source freshness 問題**不是** instability 的唯一來源；補新 VIX 之後，結論沒有變穩，反而更強。

## 對 K1321 的更新

`K1321`（2026-05-26）：

- overlap `n = 111`
- mean = `1.5326`
- CV = `0.1896`

`K1323` 說明：

- 若沿用 stale local VIX source，尾端交集甚至縮到 `108`
- 若用 fresh yfinance `^VIX` 補齊到 `2026-05-28`，交集變 `115`
- 但 ratio instability 方向完全沒變

所以 K1323 的貢獻不是翻案，而是把 **「252-day gate 尚未達成」** 和 **「配對 VIX source freshness 也要被 audit」** 這兩件事分開。

## 結論

1. Q6 正式 252-day 驗證 **仍未 ready**
2. 目前 shared local `VIX` pairing source 已 stale 到 `2026-05-19`
3. 但即使用 fresh `^VIX` 補到 `2026-05-28`，ratio 仍高於 `K1181` baseline、CV 偏高、trend 顯著
4. 因此在目前資料下，最誠實結論仍是：

> **NOT_READY_AND_UNSTABLE**

## 產物

- `k1323.py`
- `k1323_results.json`
- `k1323_ratio_paths.png`
- `data/vix_yfinance_snapshot.csv`
