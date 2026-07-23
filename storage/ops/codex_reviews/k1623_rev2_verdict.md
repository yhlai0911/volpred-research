VERDICT: FAIL

1. [OK] 撤回是否乾淨

三項舊宣稱在 README 中僅以「舊說法／撤回內容」出現，沒有被當作現行結論：

- 識別結論明確降為描述性殘餘持續性，且明說不拒絕 Diebold-Inoue：[README.md:11](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:11>)、[README.md:212](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:212>)、[README.md:302](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:302>)。
- 「不可交易」只出現在撤回表；現行結論是「不表態」：[README.md:27](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:27>)、[README.md:306](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:306>)。
- 「多處顯著更差」只作為被撤回的原文，現行說法是 1 個 nominal、BH 後 0 個：[README.md:251](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:251>)。
- 現有圖標題只寫 apparent long memory、Bai-Perron breaks 或 OOS QLIKE，沒有上述三項識別／交易宣稱：[k1623.py:685](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623.py:685>)。

2. [BLOCKER] 數字沒有全部對上

DM 明細與計數本身正確。我由 40 列明細重計得到：

- QLIKE：nominal/BH/Bonferroni = 8/7/3。
- MSE：2/0/0。
- focal QLIKE：1/0/0；focal MSE：0/0/0。
- ARFIMA sign reversal：3。

這與 [k1623_rev2_results.json:2057](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2_results.json:2057>) 及 README 表格 [README.md:242](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:242>) 一致。

但有兩個實質錯誤：

- README 三處把 TW0050 最大相對偏差寫成 `2.51e-3`：[README.md:95](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:95>)、[README.md:106](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:106>)、[README.md:319](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:319>)；權威欄位實際是 `0.005259349489457132`，即約 `5.26e-3`：[k1623_rev2_results.json:31](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2_results.json:31>)。JSON 自己的文字欄位也硬寫錯成 `2.5e-3`：[k1623_rev2_results.json:54](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2_results.json:54>)。
- README 宣稱「QLIKE 下 HAR 是 5 資產冠軍或並列最佳」：[README.md:35](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:35>)。但 JSON 的全模型 winner 是 VIX=`AR1`、N225=`ARFIMA`，只有三資產為 HAR：[k1623_rev2_results.json:118](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2_results.json:118>)、[k1623_rev2_results.json:278](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2_results.json:278>)。正確的較窄說法是「HAR 對 ARFIMA 在 4/5 資產有較低 QLIKE」。

另外，「每一個 README 數字都可在 rev2 JSON 對上」也不成立：[README.md:335](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:335>)。raw d/ACF/break 表仍只在第一輪 JSON；MC 數字則在另一份 MC JSON。

3. [MINOR] HAC 正確；family 揭露大致一致但「nested」不精確

- 確實 import 並呼叫 canonical `dm_test`：[k1623_rev2.py:82](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2.py:82>)、[k1623_rev2.py:366](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2.py:366>)。
- canonical 函式使用 Bartlett-weighted Newey-West，bandwidth `ceil(h^(1/3)n^(1/3))`；n=749、h=1 得 10：[model_evaluation.py:89](</Users/yhlai0911/volpred-research/src/volpred/stats/model_evaluation.py:89>)。
- BH monotonic adjustment及 Bonferroni 實作正確：[k1623_rev2.py:226](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2.py:226>)。
- `FOCAL` 與 within-loss family 都固定寫在 code，沒有依結果動態選 family：[k1623_rev2.py:89](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2.py:89>)、[k1623_rev2.py:406](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2.py:406>)。

小問題是「五個 nested 集合」不嚴格：QLIKE-20 與 MSE-20 彼此 disjoint，pooled-40 是兩者聯集；只有各 focal-10 分別是其 within-loss-20 子集。README 隨後有正確說明子集／聯集，因此屬措辭問題，不影響修正值：[README.md:152](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:152>)。

4. [OK] loss reversal 的主要敘述強度可接受

README 有清楚區分 point-estimate 排序與統計推論，並明說不是「ARFIMA 在 MSE 打敗 HAR」：[README.md:232](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:232>)。

四個 MSE winner 的改善為：

- SPY 11.12%
- TW0050 16.41%
- QQQ 12.58%
- N225 10.86%

所以寫成整數百分比範圍「11–16%」是正常 rounding，不算誤述；明細見 [k1623_rev2_results.json:2020](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2_results.json:2020>)。

ARFIMA/MSE p 值實際 min/max 為 `0.2653633`、`0.9744301`，故 `[0.2654, 0.9744]` 正確：[k1623_rev2_results.json:2162](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2_results.json:2162>)。

「統計上無法區分」只能解讀為這些 DM 檢定未拒絕 equal predictive accuracy，不能解讀成已通過 equivalence test；目前上下文有把它寫成 null，而非實質等價，尚可接受。

5. [BLOCKER] reproduction_guard 限制寫得清楚，但 README 又作了相反宣稱

`scope_and_limits` 對四個 aggregate functionals、無逐期 forecast vector、TW0050 排除等限制揭露充分：[k1623_rev2_results.json:49](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2_results.json:49>)。README 的限定段也正確：[README.md:180](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:180>)。

但後文仍出現兩句對 TW0050 為假的無限定宣稱：

- 「故所有數字不變」：[README.md:134](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:134>)。
- `k1623.py` 未修改「故所有預測值不變」：[README.md:327](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:327>)。

同一份 code 不代表同一份輸入資料會產生相同 forecasts；TW0050 已明確 n=4263→4264。因此撤回「same forecasts」的修復沒有貫徹到全文。

6. [OK] data vintage pin 正確套用全部資產

`pin_vintage` 取第一輪 artifact 的完整 end date，使用 `date <= end`，沒有月級截斷或 `< end` off-by-one：[k1623_rev2.py:258](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2.py:258>)。

主迴圈對 `K.ASSETS` 的五個資產都先呼叫 pin，再進 OOS：[k1623_rev2.py:320](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2.py:320>)。pin dates 與第一輪 artifact 一致：[k1623_rev2_results.json:56](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2_results.json:56>)。TW0050 的歷史列修訂不是 pin 漏做。

7. [BLOCKER] MC scope 誠實，但凍結 source、README、results 三者不一致，且 attribution 仍錯

DGP 只能支撐「ARFIMA + 固定 deterministic breaks」條件下的模擬不確定性；程式也明確否認它能解決 Diebold-Inoue 識別：[k1623_rev2_mc.py:31](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2_mc.py:31>)。因此沒有把 MC 當成識別問題已解決。

但凍結 artifacts 有嚴重版本漂移：

- 現行 MC code 已承認 Arm-A 的 total bias 不能全歸因於 break estimation，真正 contrast 應是 A−B：[k1623_rev2_mc.py:141](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2_mc.py:141>)。
- 凍結 MC JSON 卻仍保留舊欄位與舊結論，把 `−0.085` 至 `−0.027` 全歸因於重新估斷點：[k1623_rev2_mc_results.json:159](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2_mc_results.json:159>)、[k1623_rev2_mc_results.json:179](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2_mc_results.json:179>)。
- README §6.4 也仍重複這個舊 attribution：[README.md:287](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:287>)，但 §9 又聲稱已改成 A−B `−0.056` 至 `−0.020`：[README.md:354](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:354>)。
- MC JSON 還宣稱 break dates 有 substantial uncertainty，但凍結 JSON 只記 break count、沒有比較日期：[k1623_rev2_mc_results.json:180](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2_mc_results.json:180>)。現行 code 自己也承認該日期宣稱不受支撐：[k1623_rev2_mc.py:237](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2_mc.py:237>)。

此外，Arm B 仍以 `piecewise_demean` 從模擬資料估各段均值，而不是使用已知 implanted level，因此它不是純粹「ELW alone」；它只 oracle 化 break locations，未消除所有 mean-structure generated-regressor uncertainty：[k1623_rev2_mc.py:118](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/k1623_rev2_mc.py:118>)。

8. [BLOCKER] 新增貢獻中有未支撐的 uniqueness 宣稱

四點的狀態是：

- (a) QLIKE/MSE 同時 DM 與排序反轉：有計算支撐。
- (b) break-demean 顆粒度敏感度：有描述性計算支撐。
- (c) MC：只有 model-conditional 支撐，且 frozen result/README attribution 仍錯，不能按目前文字成立。
- (d) single-loss 方法論教訓：本資料可作為一個實例，但不是「獨有」。

README 宣稱四點是「仍然獨有的貢獻」：[README.md:56](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:56>)，後面卻明說 §6.3 是既有 K1016 教訓的「又一個實例」：[README.md:66](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/README.md:66>)。這直接否定至少第 (d) 點的 uniqueness。所述查核也只有 knowledge.json 與 README grep，不能支撐一般性學術 uniqueness。

本次 FAIL 的核心不是 DM 算術，而是凍結宣稱仍超出／違反證據：TW0050 偏差數字寫錯、仍宣稱所有 forecasts 不變、MC 將 total Arm-A bias 錯歸因於 break estimation、MC source/results 不一致，以及「獨有貢獻」未被證成。
