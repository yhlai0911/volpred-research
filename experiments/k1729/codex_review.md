# K1729 研究誠實審查

## 審查對象

本審查僅針對下列凍結檔案，未修改其任何 byte：

- `experiments/k1729/README.md`（SHA-256 `b79f45132bad62cb77ae913d2e70949c8c4a4246daed1374f7909abec6fbb2e1`）
- `experiments/k1729/k1729.py`（SHA-256 `d3e5691b23ae7168fbfaca875beaf7849702502768c1550e6db6e22745d624f0`）
- `experiments/k1729/k1729_results.json`（SHA-256 `e883953f10c2249217c1d269338fed4ced67f034b62ed7b0cd515fa0dac4240e`）

我從 `k1729_results.json:201` 讀到的 `code_sha256` 是 `d3e5691b23ae7168fbfaca875beaf7849702502768c1550e6db6e22745d624f0`；它與目前凍結的 `k1729.py` byte hash 完全一致。資料檔實測 SHA-256 亦與 `k1729_results.json:14` 的 `ce62b9c521a20fb23ccb8819addbee0341c2426de7edc167986b57f1d8dd86bb` 一致。

審查另唯讀參照主 repo 的 canonical `src/volpred/stats/model_evaluation.py`、`src/volpred/evaluation/metrics.py`、資料 CSV，以及與 README 選約論證直接相關的 `scripts/collect_taifex_tick.py`。未重跑整個實驗；只做 hash、資料列數／日期／零值、結果算術與 bandwidth 的小型 sanity check。

## Gate 1 — Lookahead bias：FAIL

### HAR lag 與 rolling training window 本身正確

- `k1729.py:101-112` 先做 `lagged = x.shift(1)`，再於 lagged series 上計算 5 日與 22 日 rolling mean。因此 origin `t` 的三個 regressor 分別只含 `x[t-1]`、`x[t-5..t-1]`、`x[t-22..t-1]`，不含 `x[t]`。
- `k1729.py:129-140` 對 origin `t` 使用 `valid[lo:t]`、`X[lo:t]`、`y[lo:t]`；Python slice 上界 `t` 不包含 `t`，所以最後一個 training pair 是 `s=t-1`。該 pair 的 `X_s` 又只使用 `<=s-1` 的資料。README `:87-90` 對這部分的敘述成立。
- `k1729.py:158-172` 是把 origin `t` 已形成的 forecast 與 `actual[t]` 做 forecast evaluation，沒有 same-day regressor 或 same-day signal 乘上 same-day target 的路徑。

### Blocking：target day 的 active contract 是用 origin 後的成交量 ex post 選出

- README 把 origin 定為 day `t` 08:45 開盤前（`README.md:74-83`；結果檔亦見 `k1729_results.json:193`）。
- 實驗直接載入 canonical CSV（`k1729.py:204-205`），再把同一列 day `t` 的 `rv_5min` / `r2` 當成 `y_t`（`k1729.py:216,230-244`）。結果檔明載合約規則是 `same_day_max_total_volume`（`k1729_results.json:13-16`）。
- 產生該 CSV 的 collector 在 `scripts/collect_taifex_tick.py:231-236` 對整個 file frame 的每一合約加總 `volume` 後取 `idxmax()`；`process_tick_file()` 在 `:298-306` 先以這個全檔總量選出合約，之後才從所選合約計算 day-session metrics。故 day `t` 的 target contract choice 使用 day `t` 08:45–13:45 的成交量；這些成交量在 08:45-on-`t` origin 尚未 realized。
- README `:78-83` 只論證「day `t-1` 選約所用的夜盤資訊在 day `t` 08:45 前已實現」。即使完整接受這段夜盤時序論證，它也只能使 `X_t` 所依賴的 day `t-1` row 合法，不能使 `y_t` 的 same-day total-volume selector 合法。對 `y_t` 而言，未來的 day-session volume 仍參與決定要評分哪一張合約。
- 小型資料檢查顯示 OOS 期間有 127 列 `is_roll=True`。缺陷不只是一個抽象命名問題：在換月附近，ex-post total-volume rule 可能改變被選中的 target contract。即使兩模型共用同一個 ex-post target、沒有直接偏袒任一模型，這仍是 forecast origin 當下不可固定的 estimand，無法通過本專案「無 lookahead」硬門檻。

因此，本 gate 不能因 feature lag 正確而通過。凍結結果至多比較「事後依當日總量選出的 active-contract series」上的兩模型，不能證明 08:45 時點可實作的 next-session forecast comparison。

## Gate 2 — Baseline 公平性：PASS（不抵銷 Gate 1）

- 兩組 regressors 都呼叫同一個 `har_features()`（`k1729.py:223-227`），所以 HAR(d/w/m) 結構與 lag 慣例相同。
- `feat_ok` 同時要求兩邊 features 有效（`k1729.py:228`）；對每個 target，兩模型收到完全相同的 `tr_valid`（`:233-244`），因此 training target ledger 相同。
- 兩模型皆呼叫同一個 `rolling_oos()`（`k1729.py:239-241`）：相同 1000-row window、每個 origin 重新 OLS、相同 minimum-observation gate、相同 in-sample target support 與相同 insanity fallback（`:129-155`）。
- filter 判斷只依各模型自己的 `pred` 與兩者共用的 `ytr` support（`k1729.py:141-145`）。所以結果檔的 7 vs 0（`k1729_results.json:34-47`）及 12 vs 0（`:88-101`）是不同模型 forecast path 觸發同一規則的結果，不是程式對 HAR-RV5 與 HAR-DAILY 寫了不對稱分支。
- 評分 ledger 明確同時要求兩模型 forecast finite（`k1729.py:158-165`），不存在各自挑有利日期的情況。

## Gate 3 — DM 檢定正確性：PASS

- `k1729.py:167-168` 的 canonical `qlike()` 只用來報告平均 QLIKE；送進 DM 的則是 `:169-172` 明確逐日建立的 `l_rv5`、`l_daily` arrays，不是兩個已平均純量。
- pointwise formula 是 `actual/predicted - log(actual/predicted) - 1`（`k1729.py:170-171`），與 canonical `src/volpred/evaluation/metrics.py:17-30` 完全一致，方向為 lower is better。
- 這是 one-step-ahead day-session forecast，`dm_test(..., h=1)`（`k1729.py:172`）適切。
- 直接閱讀 canonical `src/volpred/stats/model_evaluation.py:89-117`：loss differential 定義為 `loss1-loss2`（`:93`）；bandwidth 是 `max(1, min(ceil(h^(1/3)*n^(1/3)), n//4))`（`:101`）；並真的在 lags 1 到 `max_lag` 加入 Bartlett-weighted autocovariances（`:102-107`）。所以 `h=1` 不會退化成 lag 0。四個 ledger 的 `n` 代入後皆為 bandwidth 14，與 `k1729_results.json:61,79,115,133` 一致。
- 因為 `loss1=l_rv5`、`loss2=l_daily`，negative t 確實代表 HAR-RV5 loss 較低。`k1729.py:179-182` 的 verdict 分支、results `:58-65,112-119,130-137` 與 README `:102-109,114-121` 的正負號及 Harvey `|t|>3` 判讀一致。
- 小型算術 check 顯示四格的 QLIKE difference、改善百分比、由 t statistic 算出的 two-sided p-value 與 JSON 均逐浮點值一致。

## Gate 4 — 結論射程：FAIL（Gate 1 的直接後果）

要求特別檢查的四項 caveat，本身都有誠實揭露：

- HAR-DAILY 的 `day_return` 仍由 tick collector 算出，且未端到端測試外部日頻 feed：`README.md:171-176`、`k1729_results.json:198`。
- README 明確否認「外部廉價日頻資料可逐位元替代 tick pipeline」：`README.md:173-176`。
- 2017+ `daily_r2` 的 `|t|=2.921<3` 被列為 NULL，沒有升格：`README.md:112-122`；results 的 `harvey_significant=false`、`verdict=NULL` 見 `k1729_results.json:121-137`。
- 兩個 target 都是 noisy proxy 且沒有中立第三 proxy：`README.md:178-180`、`k1729_results.json:194-196`。

但 README `:22` 與 `:166-169` 進一步將 frozen result 解讀為「08:45 可用的 intraday predictive gain，因此資料線值得維護」。由於 Gate 1 顯示 day `t` 的 target contract 是用 origin 後 day-session volume 選出，這項營運結論超過目前證據。上述四個 scope caveat 無法補救未揭露的 ex-post target selection。因此本 gate 隨 Gate 1 一併失敗；不是文字風格問題，而是結論所依賴的 forecast estimand 不可在聲稱的 origin 固定。

## Gate 5 — 造假／一致性：主要產生路徑 PASS；另有非 blocking 記載問題

- `k1729.py` 沒有寫死 README/JSON 的 QLIKE、DM、樣本數或 verdict 數字。payload 由 data、rolling forecasts、`evaluate()` 與 canonical DM 實作組成（`k1729.py:204-346`），最後經 temporary JSON re-parse 後原子替換（`:348-353`）。
- results 的 `code_sha256` 與凍結 code bytes 相符；source CSV hash 亦相符。seed 42 在 code `:84,90` 與 results `:5` 一致；此 OLS/DM 路徑本身也沒有隨機抽樣。
- 小型 data sanity check 得到 3,550 rows、日期唯一且遞增、`rv_5min == rv_day`、row 1000 日期為 2016-01-20、OOS `rv_5min<=0` 為 2 日、OOS `r2<=0` 為 14 日。這與 2,550 forecasts、2,548 / 2,536 test observations（`k1729_results.json:35,51,89,105`）一致。
- 由於依指示未重跑完整 rolling OLS，本審查不宣稱獨立重現每一個 forecast；但 frozen code/data hash、非硬編碼產生路徑、樣本 ledger 算術與結果衍生欄位均自洽。沒有發現捏造主要數字的證據。
- 唯一會改變裁決的 code/README 不一致，是 Gate 1 的 origin 論證漏掉 target-day total-volume selection；已列為 blocking defect。

## Blocking defects

1. **Ex-post target-contract selection lookahead**：在 08:45-on-day-`t` origin，`y_t` 的合約由 day `t` 全檔總量選出，而該總量包含尚未發生的 day `t` 08:45–13:45 volume。README 只證明 day `t-1` 資訊可得，沒有使 day `t` target selector 成為 ex ante。這直接違反 PASS 所要求的「無 lookahead」，也使「可營運、值得維護」的成本結論超出證據。

## Non-blocking observations

- README `:131-132,147` 聲稱做過 no-filter sensitivity check，但 frozen `k1729.py` 與 `k1729_results.json` 沒有保存該路徑或數字，故本審查無法從三件套稽核這項輔助主張。主結果程式仍可稽核，因此此點單獨不構成 FAIL。
- README `:163` 把 21 個 `day_return==0` 日寫成 target-B ledger 排除；results `:164-189` 的 21 是全資料期間總數。OOS 2,550 forecasts 到 2,536 test observations 實際只排除 14 日，其餘 7 日在 OOS 起點前。這不改變任何已報 score 或 verdict，但樣本敘述應區分 full-file 與 OOS exclusions。
- README `:8,147` 所稱的「Codex pre-run review」不是本文件的 frozen-artifact final audit，不能取代本次裁決；此為審查 provenance 說明，不是模型缺陷。

FINAL VERDICT: FAIL
