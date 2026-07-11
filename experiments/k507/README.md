# k507 — 動態 SPY/GLD 配置能否打敗靜態 50/50 + 12/VIX

- Experiment ID: `k507`
- Status: **null（4 個動態配置法全部沒通過門檻）** — 結論在 2026-07-11 重跑後維持
- Created At: 2026-04-16
- 被論文引用：`paper/vt-trend-following`（Discussion 的支撐實驗，用來說明「50/50 這一層也是不可再壓縮的」）

## 問題描述

VT（12/VIX）解決的是「曝險大小」；本實驗問的是上一層：**資產之間的權重**要不要動態調整？
四個候選：VIX-based、momentum、inverse-vol（風險平價）、以及三者的 combined。

## 方法

- 資料：SPY + GLD，2005-01-03 至 2026-07-10（yfinance，5,413 個交易日）
- Benchmark：靜態 50/50 + 12/VIX 波動率目標化；月頻再平衡；交易成本 0.05%/次
- 過關門檻（三者皆須通過）：Sharpe 改善 + cross-OOS 5 段中贏 4 段 + Harvey t > 3.0
- 檢定：DM test（QLIKE / 策略損失），HAC bandwidth 用 canonical

## 結論

**沒有任何一個動態配置法過關。**

| 策略 | Sharpe | DM t | DM p |
|---|---|---|---|
| static 50/50（benchmark） | 0.932 | — | — |
| vix_dynamic | 0.960 | -0.414 | 0.679 |
| momentum | 0.897 | 0.068 | 0.946 |
| inv_vol（最佳候選） | 0.994 | -0.071 | 0.944 |
| combined | 0.943 | -0.182 | 0.855 |

inv_vol 的 Sharpe 名目上比 benchmark 高（0.994 vs 0.932），但 DM 完全不顯著（p=0.94），
離 Harvey t>3.0 的門檻極遠 —— 這個差距和雜訊分不開。

這與 DCC-GARCH 的解析結果一致：**兩資產**的風險平價權重與相關係數無關，
所以 50/50 已經幾乎榨乾了分散化利益，沒有留下讓動態配置發揮的空間。
零售投資人的建議維持：靜態 50/50 + 12/VIX。

## 2026-07-11 附記：DM 檢定改用 canonical HAC bandwidth

K1655 發現一個 bug class：自寫的 local DM 只在 `h > 1` 才做 HAC 修正，於是 h=1 時**完全不做 HAC**。
本實驗的 `diebold_mariano_test` 屬於暴露站點，已換成 canonical `volpred.stats.model_evaluation.dm_test`
並輸出 loss differential 的自相關。

- **HAC 遺漏在此實驗不實質**：四組 loss differential 的 acf(1) 都在 ±0.06 以內
  （vix_dynamic -0.055、momentum -0.024、inv_vol -0.059、combined -0.017），
  幾乎沒有序列相關，所以有沒有做 HAC 對標準誤影響很小。
- **誠實的口徑限制**：本次重跑順帶把 yfinance 樣本從 2026-03-26 延長到 2026-07-10，
  因此**新舊統計量的差異不能純歸因於 HAC 修正**（Sharpe 也跟著動了：benchmark 0.947→0.932）。
  能斷言的是「以當前樣本、正確的 HAC 之下，四個策略依然全部不顯著」，
  而不是「HAC 修正讓 t 值變成 X」。要做純 HAC 歸因，請看同批的 k621（樣本釘死、可乾淨對照）。
- 結論方向不變：null 依舊是 null，論文引用的「動態配置過不了 Harvey 門檻」不需回溯更正。

站點已從 `storage/ops/dm_hac_lag_baseline.json` 的 sites 移入 retired。

## 參考

- 相關：K1655（DM HAC lag bug class 全量掃描）、k621（同批重跑，純 HAC 對照組）
- 論文：`paper/vt-trend-following`
