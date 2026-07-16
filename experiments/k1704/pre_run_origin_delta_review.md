# FAIL

Blocker：eligibility 目前依賴「raw forecast 輸出是否有效」，不是「截至 t−1 的輸入是否足以形成 forecast」。

- [K1704.py:643](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/k1704/K1704.py:643) 直接以 `isfinite(raw_forecast) & (raw_forecast > 0)` 決定 forecastability。任何 estimator/numerical regression 產生的 NaN、Inf 或非正值，都會在第 650 行被移出 ledger，而非 fail closed。因此兩階段 ledger 仍可掩蓋真正的 raw forecast failure，並形成 model-output-conditioned selection。
- [K1704.py:834](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/k1704/K1704.py:834) 已先完成全部 calibration，直到第 846 行才建立 eligibility，與 [README.md:20](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/k1704/README.md:20) 所稱「calibration 前明確排除」不符。這本身未引入 lookahead，但沒有真正 predeclare ledger。
- [test_K1704.py:111](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/k1704/test_K1704.py:111) 只把 raw forecast 本身設成 NaN，並期待它被排除；沒有建立 lagged RV input 缺失，因此無法證明排除原因是事前 input unavailability。反而固定了上述會吞掉 estimator failure 的行為。第 136–143 行對 eligibility 內 calibrated gap 的 fail-closed 測試則正確。

最小修法：

1. 由各模型的 lagged input/features 產生獨立的 `forecastable_from_t_minus_1` mask；eligibility 只能使用這些 mask、OOS 與六 targets positivity。
2. 對 mask 判定 forecastable 的 origin，另行驗證 raw forecast 必須有限且正值；違反即 `RuntimeError`，不可縮 ledger。
3. 在 calibration 呼叫之前建立並凍結 eligibility。
4. 測試加入兩個不同案例：
   - `rv_5min[t-1]` 缺失造成 HAR input mask 為 false，origin 可排除；
   - input mask 為 true 但強制 raw forecast 為 NaN，必須 fail closed。
5. audit 的各模型排除數應從 input-availability mask 計算；最好另記排除 indices/dates 或其 hash，使 24 個 HAR 排除日期可核驗。

現有實作確實讓六 targets／三 models 使用同一個最終 `common_mask`，且 eligibility 內 calibrated gap 會失敗；但上述 blocker 必須在正式 rerun 前修正。未讀取或解讀現有 `K1704_results.json`。測試因唯讀環境沒有可寫暫存/cache 目錄而無法執行；這不是測試失敗。
