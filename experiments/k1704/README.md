# K1704：偏誤波動代理的逐時點共識評估

## Data & Methodology

- 方法類型：實證、一步樣本外 forecast-comparison diagnostic；不作因果或交易績效宣稱。
- 資料來源：本機 TAIFEX `TX` 全合約逐筆資料。每個交易日依全日成交量選最高的月合約，避免直接使用 `TX1` 的機械轉倉跳空。
- 期間與樣本：腳本會從 canonical inventory 重建；預期全樣本 2012-01-02 至 2026-07-14、3,548 個交易日。正式數字以 `K1704_results.json` 為準。
- 同質口徑：只用 08:45–13:45 日盤。1/5/10 分鐘 RV 都把第一筆 session price 作為格點左端、再接各 bar close，完整涵蓋開盤 interval；不把日夜盤休市缺口或跨合約價差算入 RV。
- 代理變數：理想目標是不可觀察的日盤 integrated variance。可觀察代理為 1/5/10 分鐘 RV、Parkinson range 與日盤 open-to-close 報酬平方。高頻 RV 受微結構雜訊影響；range 受跳躍與價格離散影響；單日報酬平方極吵。任何一個都不被當作真值。

## 動機與差異化

K1057 顯示 HAR-RV 與 GJR 在各自 native target 上的排名會翻轉；K1072 在短 SPY 樣本比較 5 分鐘 RV 與 noise-robust realized measures。K1704 的增量是使用長期台指期逐筆資料，在每個 forecast origin 僅以過去 500 日估計各 proxy 的 log-bias 與相對 consensus residual，再建立 consensus-weighted heuristic target。它不能識別共同偏誤或宣稱是最適 measurement-error 權重，但能直接檢定 HAR/GJR 排名是否依賴單一不可靠目標。

## 預註冊設計

1. 先把 raw 檔鎖到 canonical 5 分鐘 RV 已驗證的日期集合（較新的未驗證 raw 檔列入 excluded audit），再用既有 collector 的 header normalization 與 completed-day active-contract rule，另算含 session-open 左端點的 1/5/10 分鐘 RV、Parkinson 與日報酬平方。快取另存 collector 原本的 close-only 5 分鐘口徑，用來逐日驗證 active contract、canonical RV 與 signed day return；該欄不作模型 target。
2. HAR-RV5、GJR-GARCH(1,1) 與 EWMA 使用相同日期 ledger。HAR feature 與 EWMA 在程式中明確 `shift(1)`；GJR origin `t` 只使用到 `t-1`。因三者 native scale 不同，每個 target/origin 另用至少 252 組、最多 500 組 past-only actual/forecast ratio 做乘法尺度校準。
3. 每個 origin 的 proxy bias/weight 只使用 `[t-500,t)`；每個 proxy 的可靠度 residual 以不包含自己的 leave-one-proxy-out median 為中心。當日 proxy 只能作評分 target，不能進權重估計。
4. 先固定五個 raw proxies、consensus target 皆為正值，且三個 raw 模型能以截至 `t-1` 的可用資訊產生預測的單一 OOS origin ledger；原始輸入缺日造成的不可預測 origin 會在 calibration 前明確排除並按模型計數，之後任何 calibrated forecast 缺口都 fail closed。六個 target 在完全相同日期上報 actual/predicted QLIKE、Spearman、repo canonical Newey-West HAC DM（h=1）及 stationary-bootstrap MCS（seed=42、1,000 reps）；實際值非正的日期在模型 feature、consensus calibration 與共同評估 ledger 都視為缺值，不得 clip 成極小正數。
5. `PROXY_ROBUST_STATISTICAL_RANKING`：所有 raw/consensus QLIKE winner 相同，且每個 target 的 MCS 都是相同 singleton。`PROXY_DEPENDENT_STATISTICAL_RANKING`：至少兩個 target 有不同 singleton MCS winner。其他情況一律 `INCONCLUSIVE_RANKING_SENSITIVITY`。點排名差異不能單獨觸發結論。

## 防錯規則

- Lookahead：HAR/EWMA 明確 lag；GJR refit/filter 與 proxy weights 全部 past-only。
- QLIKE：只用 `actual/predicted - log(actual/predicted) - 1`。
- DM：只用 repo canonical automatic-bandwidth Newey-West HAC；不可誤稱 HLN small-sample correction，也不可用 h=1→lag 0 的 local helper。
- 隨機程序：MCS seed 固定為 42。
- 輸出：結果 JSON 先寫 temp、解析驗證後 `os.replace`；每個 raw tick 檔、raw byte-inventory、canonical CSV、proxy cache、collector／實驗／MCS／evaluation code 皆記 SHA-256。從 cache 重跑時仍逐檔重新讀取當前 raw bytes 並核對 size/SHA-256；檔案缺失、替換或修改一律 fail closed。快取內另保存 extraction-function builder hash；純 forecast code 修正不會冒充 raw cache 改變。
- 誠實性：proxy consensus 仍不是真正 latent variance；null/inconclusive 不升格。

## 文獻

1. Corsi (2009), *Journal of Financial Econometrics*, 7, 174–196. doi:10.1093/jjfinec/nbp001.
2. Hansen and Lunde (2006), *Journal of Business & Economic Statistics*, 24, 127–161. doi:10.1198/073500106000000071.
3. Patton (2011), *Journal of Econometrics*, 160, 246–256. doi:10.1016/j.jeconom.2010.03.034.
4. Hansen, Lunde and Nason (2011), *Econometrica*, 79, 453–497. doi:10.3982/ECTA5771.
5. Liu, Patton and Sheppard (2015), *Journal of Econometrics*, 187, 293–311. doi:10.1016/j.jeconom.2015.02.008.

## 重跑

首次由 raw tick 重建 proxy cache：

```bash
uv run python experiments/k1704/K1704.py \
  --canonical-rv /Users/yhlai0911/volpred-research/data/intraday/taifex_5min_rv.csv \
  --rebuild-proxies --workers 6
```

之後可直接使用已 pin 的 `K1704_daily_proxies.csv`：

```bash
uv run python experiments/k1704/K1704.py \
  --canonical-rv /Users/yhlai0911/volpred-research/data/intraday/taifex_5min_rv.csv
```

## 恢復狀態（尚未形成科學結論）

額度中斷前曾生成一份未經 primary-path pre-run review 的 provisional cache／results；該結果不採信。2026-07-16 primary review 在正式 rerun 前攔下共同 ledger、raw-byte cache 驗證與 forecast coverage 問題。只有修正通過 delta review、重新執行、再完成 post-run review 與 certification 後，本節才可改寫為正式結果。

即使後續得到一致排名，也只能解釋為「模型排名對這組已觀察 proxy 的選擇穩健」。Leave-one-proxy-out residual centre 只移除直接 self-inclusion；1/5/10 分鐘 RV 共用 ticks，相關 measurement error 與共同偏誤仍無法識別，因此 consensus 不是 latent integrated variance。
