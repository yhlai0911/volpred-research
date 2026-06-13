# K1489: GPR Acts vs Threats 波動率預測可行性審查

## 研究問題

任務池題目是：

> GPR 日頻 Acts vs Threats 分解對 vol 的不對稱預測  
> Caldara-Iacoviello GPRD 拆 GPRA/GPRT 入 HAR-RV，檢定對 SPY/GLD/XLE/ITA 不同 horizon 預測力。

這題的價值在於它不是重跑 K446 的 aggregate GPR，而是把官方日頻 GPR 拆成：

- `GPRD_ACT`: realized geopolitical acts
- `GPRD_THREAT`: threats / risk narrative

然後檢查兩者是否對不同資產的 realized volatility 有不對稱預測力。

## 文獻與既有知識

- Caldara and Iacoviello (2022), American Economic Review, "Measuring Geopolitical Risk": GPR index 的主要來源，並明確指出 threat 與 realized adverse events 都是 GPR 後果的重要來源。
- IMF Global Financial Stability Report, April 2025, Chapter 2: 重大 geopolitical events 可能壓低股價、推升 sovereign risk premium，且會透過金融與貿易鏈外溢。
- Dai, Dai, and Zhou (2024), GJR-GARCH-MIDAS geopolitical risk and agricultural volatility: 支持把 geopolitical risk 當成 volatility driver 測試，但仍需嚴格 OOS 與正式檢定。

本地既有 K：

- `K100`: generic geopolitical proxies 對 vol 的增量很弱。
- `K446`: broad daily GPR 對 SPY volatility 的 OOS 增量弱，且有 reversed causality 訊號。

因此本題若要成立，必須靠 Acts/Threats 分解與跨資產差異，而不是只重複「GPR 對 SPY」。

## 本輪實際完成內容

本輪先做資料與可重現性 audit，而不是硬跑回歸。

原因是目前 sandbox 不能解析外部 DNS：

- 官方 GPR daily XLS 下載失敗
- yfinance 下載 SPY 測試失敗

本地資料也不完整：

- 找得到 SPY/GLD/VIX 的部分 paper snapshot
- 找不到 XLE/ITA close price snapshot
- 找不到 canonical raw `GPRD/GPRD_ACT/GPRD_THREAT` 檔

因此完整 HAR-RV 實證目前是 `BLOCKED_ON_DATA`。

## 防錯規則

- 不用 K446 results 反推或重建 raw GPR daily series。
- 不手造 XLE/ITA 價格。
- 所有未來預測式設計必須 `signal.shift(1)` 或等效 lag。
- bootstrap / random sampling 必須固定 seed，本設計預設 `seed=42`。

## 解鎖條件

至少需要兩個 canonical local artifacts：

1. `experiments/k1489/data/gpr_daily_recent.csv`

欄位：

- `date`
- `GPRD`
- `GPRD_ACT`
- `GPRD_THREAT`

2. `experiments/k1489/data/prices_spy_gld_xle_ita_vix.csv`

欄位：

- `date`
- `spy_close`
- `gld_close`
- `xle_close`
- `ita_close`
- `vix_close`

有了這兩份 pinned data 後，下一輪才能誠實跑：

1. HAR-RV baseline
2. HAR-RV + VIX
3. HAR-RV + ACT + THREAT
4. HAR-RV + VIX + ACT + THREAT
5. horizon 1/5/22 的 DM + bootstrap 比較

## 檔案

- `k1489.py`
- `k1489_results.json`
