審查結論：目前不應寫入 `knowledge.json` 或合併。全程唯讀，未修改任何檔案。

必修缺陷：

1. `prev_close` 定義錯誤，須修正後重跑全部結果  
   [K1720.py:127](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-87c7269d-k1720/experiments/K1720/K1720.py:127) 先排除非 7-bar sessions，之後才在 [K1720.py:153](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-87c7269d-k1720/experiments/K1720/K1720.py:153) 執行 `day_close.shift(1)`。因此半日市後至少 8 個完整交易日使用的是更早完整交易日的收盤，而非真正 prior-session close；`r_intra` 跨越多個 sessions，並污染後續 expanding event thresholds。這不是 lookahead，但屬 predictor 與結果數值錯誤。

2. H1 的序列相關處理不足  
   [K1720.py:169](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-87c7269d-k1720/experiments/K1720/K1720.py:169) 的普通 percentile bootstrap 與 [K1720.py:204](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-87c7269d-k1720/experiments/K1720/K1720.py:204) 的 Welch test 未處理日資料的 volatility clustering。若要稱 H1 為「robust」，應加入 HAC event-dummy inference 及 block/stationary bootstrap，或把 H1 降格為純描述統計。H1b/H2 的 HAC 規格本身合理。

3. NULL 被過度解讀  
   H1b 係數仍為正，QQQ/SPX 的 HAC p 值分別約 0.135/0.126。這支持「控制 rest-of-day volatility 後未檢出顯著增量關聯」，不支持 [README.md:138](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-87c7269d-k1720/experiments/K1720/README.md:138) 的「~fully explained」，也不支持 [K1720.py:361](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-87c7269d-k1720/experiments/K1720/K1720.py:361)／results JSON rationale 的「is absorbed」。H1b 是有用的 conditional-association control，但不能 uniquely identify LETF flow 或有效吸收機制。

4. Multiple testing 與 replication 聲明不當  
   [README.md:116](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-87c7269d-k1720/experiments/K1720/README.md:116) 稱 QQQ/SPY 為 independent replication，但兩者同期間且高度共享市場因子。[README.md:129](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-87c7269d-k1720/experiments/K1720/README.md:129) 對 6 bars × 2 complexes 的 nominal p-values 未做 multiplicity adjustment；14:30 結果只能標為 exploratory，不能據此宣稱可靠 peak 或「opposite of prediction」。

5. 樣本 provenance 不一致  
   實際分析期間是 2023-08-29 至 2026-07-24、719 sessions；[README.md:51](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-87c7269d-k1720/experiments/K1720/README.md:51)、[README.md:169](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-87c7269d-k1720/experiments/K1720/README.md:169) 與 [K1720_results.json:323](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-87c7269d-k1720/experiments/K1720/K1720_results.json:323) 的「約 2 年／約 500 sessions」錯誤，應改為近 3 年／719 sessions，並重新表述 power limitation。

通過項目：15:30 predictor 與 15:30–16:00 outcome 報酬區間不重疊；event threshold 的 `shift(1)` 正確；AUM 僅作 static cross-sectional constant；seed 固定為 42。經濟量級亦精確重算一致：係數 TQQQ=6、SQQQ=12、SSO=2；QQQ 為 $5.0667B／199.58%，SPX 為 $221.96M／3.6855%。

修正 predictor、重跑 artifact 並收斂聲明後，`NULL` 可保留，但應表述為「在此解析度與規格下未檢出 sharp joint mechanism」，不能表述為機制已被否證或流量已證明被有效吸收。

VERDICT: FAIL
