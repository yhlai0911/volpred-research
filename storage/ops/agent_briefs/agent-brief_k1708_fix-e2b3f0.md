# K1708 修正 job：兩個 estimation-consistency BLOCKER + 三處文件不一致

**Model**: opus / xhigh (per model_router, experiment lane)
**Parent**: k1708_collect_fullrun_20260717（收件裁決 = Codex REQUEST_CHANGES，未 merge）
**Worktree**: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-8dda242d-k1708`
**主檔**: `experiments/k1708/K1708.py`（~69KB）、`test_k1708.py`、`README.md`

## 背景（讀完再動手）

K1708（state-space HAR vs 固定 HAR，QLIKE / MCS / Clark-West）全樣本已跑完，verdict=NULL。
2026-07-17 收件審查結論：

- **研究誠實度高**：零假數字（ledger 2,273 列 12 位小數重算全中）、verdict 由 `derive_verdict` 機械推導非硬編、
  code/data sha256 trace 相符、15 測試全過、換 CW 的方向對作者不利仍照實交 NULL、低波動 regime 有
  p=0.001 的顯著結果但作者**沒有**撈進 claim。**這份工作不是要重做，是要修。**
- **但 Codex primary review = REQUEST_CHANGES**：兩個 challenger 模型**沒有按其宣稱的規格估計**，
  因此 NULL 結論目前不可信 —— 不是「NULL 是錯的」，是「還不知道修正後是不是 NULL」。

## 必修 1（BLOCKER）— `HAR_KF_DISC` 用內層驗證前的 stale σ² 跑外層 OOS

- 位置：`K1708.py:895` `select_discount`；:901 `_init_state(..., val_start)`；:915 `return best, sigma2`；
  消費端 :1283, :1288。
- 事實：refit origin = `rp` 時，δ 由 `[rp-252, rp)` 選出，但 σ² 只看 `< rp-252` 的資料，之後原樣交給 OOS filter。
  Codex 唯讀重算：stale/full-training σ² 比率 0.9766–1.0356。
- 為何致命：σ² 同時決定 Kalman gain、predictive variance、與 `exp(mu + var/2)` 的 Jensen 修正。
  benchmark `HAR_FIXED` 每日更新 σ²，challenger 不更新 → **不對稱**。而 `HAR_KF_DISC` 的 QLIKE 優勢只有
  0.160492 vs 0.161432（極薄）→ 這個不對稱完全可能翻轉結論。
- 修法：δ 選完後，**在完整訓練集 `[:rp]` 重估 σ²** 再交給 OOS filter。δ 的選擇本身仍只能用 `< rp` 資料
  （不可引入 look-ahead —— 這點原作是對的，別修壞）。

## 必修 2（BLOCKER）— `HAR_KF_MLE` 估計與 production forecast 用不同 initial state

- 位置：`K1708.py:1281`（`_init_state(X, y, rp)` → `kalman_mle(X[:rp], ..., beta0, P0)`, :1284-1285）
  vs `forecast_kalman(..., first_origin, mle_by_origin)`（:1321）內部固定 `_init_state(..., init_upto)`（:846），
  所有 refit 都回到 `first_origin=1250` 的 state。
- 事實：Codex 唯讀重播 rp=2006 —— stored params 在 MLE initial state 下精確重現 loglik −1666.2722；
  換成 production initial state 為 −1667.3197，該 origin 預測均值差 0.00239 log units。**兩個 filter 不是同一個模型。**
- 為何致命：results 的 `HAR_KF_MLE` QLIKE/MSE/CW 不是由其報告的 likelihood-optimal filter 產生。
- 修法：讓 estimation 與 production 用**同一個** initial state（擇一並在 README 寫明理由）。修完要加測試把這條釘死。

## 必修 3 — GW 邊界降級未實作（README §12 自己承諾卻沒做）

- 事實（tuning.log 10 次 refit 全掃）：`HAR_KF_MLE` `at_lower_bound: true` **10/10**（q_diag 最小 4.248e-18，貼死下界）；
  `HAR_KF_DISC` δ=1.0 選中 **3/10**。已達 README §12（:219-224）自訂的「普遍」門檻。
- 但 `gw_vs_roll_finite_memory` 這個**欄位名本身在斷言 finite memory**，而 `gw_vs_roll_note`（:1113-1117）
  仍寫 "This is the admissible conditional test in this design"，**零邊界 caveat** —— 被自家 tuning log 推翻。
- 修法：欄位改名 / 加註為診斷（如 `gw_vs_roll_diagnostic_boundary_degraded`），`gw_vs_roll_note` 寫明 tuning log 的邊界事實。
- 註：GW 從未進入 `derive_verdict`（只吃 CW），且 gw_vs_roll 無檢定在 5% 拒絕（最小 p=0.057）→ **結論不受影響**，
  但這是未兌現的自我承諾，必須補。

## 必修 4 — README §11「結果」是空 placeholder

全樣本已跑完（quick_mode=false, 1731.6s），README §11 仍是「（待正式 run 完成後填入…）」。
**修完 BLOCKER、重跑之後**填入實際數字，含：低波動 regime `HAR_S_BM` CW t=3.232 p=0.001 的**誠實揭露**
+ 多重比較說明（6 個 regime 檢定）+ 為何不進 verdict（全樣本治理、該模型全樣本 QLIKE 反而更差 0.1641 vs 0.1614）。

## 必修 5 — README:183 的 MC size 措辭誇大

宣稱單尾 5% 拒絕率「≈ 名目值」，實測 **0.075**（reps=200, SE≈0.015，1.6 SE，統計上不顯著但略為 liberal）。
改為據實陳述，並註明此偏差方向**有利於 state-space** → 故 NULL 結論更保守。

## 建議（非必修）

- `phi_near_unit_root` 門檻 0.999（:727）建議放寬至 0.99 或併看 σ²_η —— 2024-04-29 refit 的
  `HAR_S_BM` φ=0.9923 + σ²_η=2.27e-06 實質已是退化解，現行門檻讓「0/10 近單位根」讀起來比實情樂觀。
- MAJOR（Codex）：`_init_state`（:807）向量 KF 初始化把同一訓練資料用兩次（OLS 後 filter 從 row 0 再更新一次），
  非 diffuse 也非正確 conditional init；README:242 自己承認了。δ=1 時影響不會快速消失。
  現有測試只驗 δ=1 比 δ=.9「較平滑」（test_k1708.py:195），沒驗與 restricted expanding HAR 的等價性。
  **若時間允許**一併修並補等價性測試；若不修，README 要明確標為已知限制。
- MINOR（Codex）：`src/volpred/stats/mcs.py:98` 實際是 T_max variant（`np.max(t_stats)`, :184）卻標成 T_R
  （HLN 定義 T_R = max_{i,j}|t_ij|）。仍是論文允許的 coherent variant，不改結果（本次五模型全保留），
  但**命名要正確**。注意這是 canonical 共用檔，改名要掃 call sites。

## 交付要求

1. 修完 BLOCKER 1+2 → **補測試把兩條釘死**（stale σ²、estimation/production init 一致性）→ 15+N 測試全過。
2. **重跑全樣本**（`uv run python experiments/k1708/K1708.py`，約 29 分鐘）→ 產出新的
   `experiments/k1708/K1708_results.json`（`quick_mode` 必須是 false）。
   注意 `--quick` 寫的是 `K1708_results.quick.json`，不會佔正式路徑。
3. **verdict 據實記錄**：修正後是 NULL 就是 NULL，是 CONDITIONAL_PASS 就是 CONDITIONAL_PASS。
   **禁止**為了讓修正「有價值」而美化。NULL 有文獻先例，據實記錄不粉飾。
   `supported_unreachable=true` 的事前設定（只有 TAIFEX 一個合格市場，SPY/QQQ 無 admissible local RV）
   維持不變 —— 那是事前寫死的，不是事後放寬。
4. 修必修 3/4/5 的文件與欄位。
5. **在 worktree 內 commit**（原 agent 從未 commit，experiments/k1708/ 目前 untracked）。**禁 force push / --no-verify**。
6. 產出 `experiments/k1708/K1708_results.json` 作為 result artifact。

**不要** merge worktree（收件班會走正式 `scripts/merge_worktree.sh`）、**不要**寫 knowledge.json、**不要**動 next_tasks.json。
