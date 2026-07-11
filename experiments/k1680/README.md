# K1680：地理型 investor attention 與公司波動風險

> 驗證狀態：2026-07-11 已完成 pre-run Codex review、正式執行、cache-only 重跑與 results JSON 數字稽核。Verdict 為 **RETROSPECTIVE_NULL**；這不是 genuine OOS 或因果證據。

## Data & Methodology

- **方法論類型**：empirical proxy pilot；不是因果識別，也不是原論文的完整 replication。
- **主資料**：`experiments/k1588/data/prices_long.csv` 的 adjusted yfinance OHLCV 與 `hq_county_geocodes.csv` 的 HQ 州。固定六檔為 AAPL（CA）、AMZN（WA）、BAC（NC）、CVX（TX）、AIG（NY）、ABBV（IL），價格期約 2018-01-02 至 2026-06-29；實際起訖與筆數由執行後 results 記錄。
- **注意力資料**：Google Trends／pytrends 週頻。每次 payload 固定同時放入 `"<TICKER> stock"` 與 `"SPY stock"`，分別查 HQ 州 `US-XX` 與全美 `US`。SPY 只作同一 payload 的 normalization anchor，不是替代 attention proxy。
- **官方 sanity arm**：Harvard Dataverse DOI `10.7910/DVN/94UPDQ` 的官方 `DatasetDemo.dta`（dataset 9554950、file 9554951、MD5 `e31f2f677d4fa6f4ab62a712b199a48e`）。只做 `GSearch` 對 `SameState`、news、local-news、volatility interactions 的簡潔方向性 sanity regression；不與 K1680 主 OOS 樣本拼接，也不冒充本實驗的新資料。
- **頻率**：週頻、週五對齊。Google 的週起始 timestamp 移至同一週週五；日 OHLCV 聚合至 `W-FRI`。
- **代理變數限制**：Google Trends 0–100 指數是相對、抽樣且經 Google normalization 的搜尋強度，不是投資人帳戶或交易流。`log((ticker+0.5)/(SPY+0.5))` 只提高跨 HQ 州／US payload 的可比性。US series 是 national attention，不能宣稱為精確排除 HQ 州後的 nonlocal attention。

## Motivation and differentiation

Mengoli, Pagano, and Pattitoni 的 geography-of-attention 機制指出，地方投資人對 HQ 州公司資訊的處理優勢可能使 local attention 先於波動、spread 與更廣泛的 attention。本題與一般「Google Trends 能不能預測波動」不同：候選訊號是 HQ 州相對全美的 spatial attention shock，且 baseline 已控制 national attention。

過去相近結果提醒本題採保守 gate：K192／K473 的一般 Google Trends 在 IS 看似有效但 OOS 失敗；`research_google_trends_vol` 明定 pytrends 失敗時不得用 VIX／價格替代；K1487 的 coarse GDELT theme attention 沒有穩健 OOS RV 增益；K1588 提供 HQ 地理映射與固定 OHLCV snapshot。

## Signal timing and lookahead policy

對每檔股票先建 52 週 rolling z-score（至少 26 週）：

```text
local_z(t)    = z52[log((HQ-state ticker search + .5)/(HQ-state SPY search + .5))]
national_z(t) = z52[log((US ticker search + .5)/(US SPY search + .5))]
local_excess(t) = local_z(t) - national_z(t)
```

程式碼明寫 `signal = raw_signal.shift(1)`：第 t 週 target 不會使用同週 attention。價格 target 的 lag-1／4／13 也全部先 shift；每個 forecast 只使用 forecast date 前的 expanding training sample。

但 Google Trends 是在本次執行時一次回溯下載完整五年窗；雖然同一 payload 的 ticker／SPY 比率會消掉共同的 0–100 尺度，Google 的歷史抽樣與修訂 vintage 無法重建。因此後續 expanding 評估只能稱 **retrospective pseudo-OOS diagnostic**，不能聲稱「當時可得資訊」或 genuine real-time OOS。

Google／pytrends 失敗或六檔任一檔未滿 156 週時，主假說標為 `NULL_DATA_LIMITATION`，不允許 VIX、volume、returns、Wikipedia、GDELT 或其他價格衍生量補成 attention。K1680 不呼叫 GDELT；Dataverse sanity arm 也不會被拿來補主 time series。

## Targets and models

四個 weekly target：

1. `rv`：close-to-close log return squared 的週合計。
2. `gap`：`log(Open_t / Close_{t-1})^2` 的週合計。
3. `corwin_schultz`：由日 high/low 計算的 Corwin–Schultz spread proxy，週平均。
4. `national_attention`：全美 ticker/SPY attention ratio 的 rolling z-score。

RV 與 gap 使用 log specification；Corwin–Schultz 合法的 0 spread 保留，使用 `log1p`，避免 EPS-log 讓 0 週變成極端值。baseline 是 target 自身 lag-1／4／13，加上 lagged national attention；nested challenger 再加入 lagged local-excess signal。`national_attention` baseline 是自身 lag-1／4／13，challenger 加入 lagged HQ-state local attention。每檔至少 156 週作初始估計，其後逐週 expanding pseudo-OOS refit；pooled inference 只保留六檔都有 forecast 的共同日期，逐週 assert firm count = 6，且共同 evaluation 不得少於 52 週。

## Inference and success criteria

- **主檢定**：Clark–West (2007) one-sided nested-MSPE test。先在每個共同日期對六檔的 adjusted loss difference 取平均，再對每個 target 做 HAC(4)；恰好四個 target p-value 以 Holm 校正。這是 retrospective diagnostic 的統計 gate，不是 real-time forecast gate。
- **Harvey gate**：target 只有在 OOS MSE 改善為正、Clark–West t ≥ 3 且 Holm p < 0.05 時算通過。
- 至少一個 target 通過時標 `RETROSPECTIVE_CONDITIONAL_DIAGNOSTIC`；RV／gap／Corwin–Schultz 三個風險 target至少兩個通過時標 `RETROSPECTIVE_STRONG_DIAGNOSTIC`；否則為 `RETROSPECTIVE_NULL`。任何一種都不得改寫成 genuine OOS pass。
- **描述性診斷**：RV／gap 額外報 QLIKE 與 DM；spread／national attention 報 squared-error DM。nested model 的 retrospective gate 只看 Clark–West，QLIKE/DM 不進 verdict。
- 六檔低於 preamble 的一般 cross-sectional N≥7 門檻，因此即使通過也只叫 pilot，不得宣稱普遍地理效應或因果 local-information advantage。

## Verified results

Google Trends 12 個 payload（6 firms × HQ state/US）皆完成，週頻資料為 2021-06-27 至 2026-06-28；程式保存每個 cache 的 SHA-256。風險 target 的六檔共同 retrospective evaluation 為 80 週，national-attention target 為 68 週。

| Target | model-scale MSE 改善 | CW t | Holm p | 描述性 loss 改善 | Gate |
|---|---:|---:|---:|---:|---|
| RV | +0.798% | 1.880 | 0.120 | QLIKE -0.395% | FAIL |
| Gap variance | -0.922% | -1.318 | 0.906 | QLIKE -1.188% | FAIL |
| Corwin–Schultz spread | -0.138% | 0.850 | 0.396 | squared error -0.099% | FAIL |
| National attention | +0.533% | 1.669 | 0.143 | squared error +0.533% | FAIL |

因此 **0/4** target 通過預註冊的 Clark–West one-sided + Holm + Harvey t≥3 retrospective gate。RV 在 model-scale MSE 有小幅點估改善，但 proxy-robust QLIKE 方向相反，且多重檢定後不顯著；不能挑有利 metric 宣稱成功。

官方 RCFS demo sanity arm 有 10,400 rows（4 匿名 firms、50 states、52 weeks），同州平均搜尋量為其他州的 1.452 倍。`LocalNewsPaper` 的同週係數為 +8.673（clustered p=0.0016），但這個四公司 demo 不足以重建論文的跨週 LocalSearch/NonLocalSearch series；錯誤的動態聚合已在 pre-run review 階段明確停用。

結論範圍很窄：在這 6 檔、這次 current-vintage Trends 回溯資料與本 proxy 定義下，沒有證據支持 HQ 州相對全美 attention 對次週 RV、gap、CS spread 或全美 attention 提供穩健增量。不可外推成所有 geographic attention 無效。

## Reproducibility and outputs

固定 `seed=42`。執行：

```bash
uv run python experiments/k1680/K1680.py
```

已產出：

- `K1680.py`
- `K1680_results.json`（以同目錄暫存檔寫入、重新 `json.load` 驗證，再 `os.replace`）
- `K1680_geographic_attention.png`
- `README.md`
- `data/` 下官方 Dataverse cache 與逐 ticker／geo 的 Google Trends cache；每個實際輸入的 byte size 與 SHA-256 都寫入 results provenance。

`K1680_results.json` 可由 cache-only 重跑得到完全相同的 verdict、CW/Holm、loss 與 RCFS sanity 數字；圖檔已通過 PNG decode。任何未來 data limitation 仍會產生誠實的狀態 results／圖，不會用替代 proxy 虛構 attention。

## References

- Mengoli, S., Pagano, M., & Pattitoni, P. (2025). “The Geography of Investor Attention.” *Review of Corporate Finance Studies*, 14(3), 752–803. DOI: 10.1093/rcfs/cfae016. Replication demo: DOI 10.7910/DVN/94UPDQ.
- Da, Z., Engelberg, J., & Gao, P. (2011). “In Search of Attention.” *Journal of Finance*, 66(5), 1461–1499.
- Clark, T. E., & West, K. D. (2007). “Approximately Normal Tests for Equal Predictive Accuracy in Nested Models.” *Journal of Econometrics*, 138(1), 291–311.
- Corwin, S. A., & Schultz, P. (2012). “A Simple Way to Estimate Bid-Ask Spreads from Daily High and Low Prices.” *Journal of Finance*, 67(2), 719–760.
- Patton, A. J. (2011). “Volatility Forecast Comparison Using Imperfect Volatility Proxies.” *Journal of Econometrics*, 160(1), 246–256.
