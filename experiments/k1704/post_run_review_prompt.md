你是 K1704 的 independent primary-path post-run reviewer。唯讀審查 frozen commit
89644f548adac795ed28e4d336bc74ad6bc13585，工作目錄是
/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704。

必讀：AGENTS.md、docs/error_log.md 索引中實驗相關規則、
.claude/skills/autonomous-research/SKILL.md、experiments/k1704/README.md、K1704.py、
test_K1704.py、K1704_charts.py、K1704_results.json、三份 pre-run review artifacts，及
experiment_gates.py 生成的 review_verdict.json template。不要修改任何檔案。

請做完整 claim-surface review，不要只看 README：

1. Lookahead / origin：HAR、EWMA、GJR、proxy bias/weights、model scale calibration 是否全為
   `t-1` 或更早；input-based eligibility 是否會掩蓋 estimator failure；六 targets / 三模型
   是否使用同一 2,016-date ledger。
2. Data provenance：cache 的 3,548 raw files 是否逐檔 size/SHA-256 reverified；byte inventory、
   cache、canonical RV、collector/experiment/MCS/evaluation hashes是否可核；額外 2026-07-15
   raw file 是否只被 audit 排除而未偷改 ledger。
3. Statistics：QLIKE 公式、repo Newey-West HAC DM、Harvey |t|>3 screen、HLN stationary-
   bootstrap MCS seed=42/1,000 reps 是否正確標示；verdict rule 是否真由六個 singleton MCS
   與 point winners支持；early/late split 是否誠實，尤其 early p=0.093 的門檻敏感性。
4. Independent recomputation：從 JSON 重算 ledger hash、各 target QLIKE 排名、MCS sets、
   consensus relative improvements、split sample counts；檢查所有數值有限、JSON 無 NaN。
   可執行唯讀測試；若 sandbox 無 writable temp/cache，請把它辨識為環境限制而非 PASS 證據。
5. Artifact / prose：README 的期間、n、hash、t-stat、限制是否逐項吻合結果；圖表數字、標籤、
   尺度及註解是否吻合；不得把 observed-proxy robustness 升格成 latent-IV 最優或因果結論。
6. Gate：確認 `review_verdict.json` 的 6 個 reviewed_sha256 對 frozen bytes 全吻合；任何 hash
   漂移、方法 blocker、數字不一致或過度宣稱都必須 FAIL。

輸出到標準輸出，第一行必須恰為 `# PASS` 或 `# FAIL`，接著寫完整 review evidence。
最後附一個 `VERDICT_JSON` fenced block，內容必須是 `review_verdict.json` template 的完整 JSON：
PASS 時 reviewer=`codex/gpt-5 independent K1704 post-run review`、reviewed_commit=上述 frozen SHA、
review_artifact=`post_run_review.md`、blocking_defects=[]，reviewed_at 使用實際 ISO8601；FAIL 時
verdict=FAIL 並列 blockers。不要採用 template 裡的 FILL 值，也不要改 reviewed_sha256。
