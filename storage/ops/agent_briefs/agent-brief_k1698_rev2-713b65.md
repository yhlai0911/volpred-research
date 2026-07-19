# K1698 重跑 rev2 — 修 contract-selection lookahead + 夜盤邊界實驗證 + equivalence 檢定

**Model**: opus / xhigh (per model_router)
**Task id**: `assign_42306eaa` (P2, experiment)
**Worktree（你唯一可寫的地方）**: `.claude/worktrees/dispatch-slot-2-c5cafe39-k1698`
**parent_task_id**: `dreaming_orphaned_experiment_k1698`

## 0. 開工前必讀（照順序）

1. `AGENTS.md` §研究誠實原則 —— 特別是 **#11 Lookahead bias 是最高風險**
2. `docs/error_log.md`
3. `.claude/skills/autonomous-research/references/experiment-preamble.md`
4. `experiments/k1698/README.md` + `k1698.py` + `k1698_results.json`
5. 相關前作 K1684 / K854 的 README（本實驗聲稱復現它們的世界）

## 1. 背景

K1698（FTD E1 v2 — scale re-calibration gating，K1684 的 compliant rerun）於 2026-07-17 經
codex gpt-5.6-sol (reasoning=high) 獨立二審判 **FAIL**。依 K1259 規則**不得寫入 knowledge.json**。

## 2. 先講公道話 —— 這些 blocker 是**真的修好了，不要重做**

數字全部可從 JSON 逐項對上、無 K1016 式反向宣稱：
- leg1 t=+1.4694 / p=0.1424 / n=436
- own-target bridge −5.2522 vs primary −2.0642 (p=0.0396)
- 校正因子 std(z)=1.20290 / MZ=1.21091 / HL=1.07465
- placebo GJRf-a OOS=1.11910 / IS=0.99346
- 1% VaR trinity：HAR+CF 14/450（Kupiec p=0.000 FAIL）vs bridge 17/450；GJR+CF 2/450 PASS
  但 c_emp=0.799 [0.63,1.02] 屬**過度保守型** PASS
- K854 bridge 11/14 格相符
- K1684 的 n=377 縮樣已修（改 declared drop 3 cells，n=450）
- atomic write（tmp→json.load→os.replace）已到位
- GATE_RULES 寫在 `k1698.py:170`，`decide_gate_v2()` 確實檢查 leg-2

**別把時間花在重新驗證上面這些。**

## 3. FAIL 的 7 條理由（問題全在「數字 → 結論」與兩個號稱已解的 blocker）

1. **lookahead 未解（致命）**：active contract 依**整份日檔成交量**選出
   （`k1698.py:328` `v[dl==d].sum()`），含 13:30-13:45 的 tick。因此號稱「13:30 可得」的 RV
   predictor **用了視窗收盤後 15 分鐘的合約選擇資訊** —— 直接推翻 README「資訊集建構上不相交」
   的宣稱，並打在所有「新舊 RV 差 → divergence 是 artifact」結論的根上。
2. **60 天邊界 audit 是空驗證**：`rv_window_boundary_audit` 取的是**最早 60 個交易日**（2017-01，
   夜盤上線前），JSON 內 12 筆 checks 的 `night_pm_in_window` / `night_am_in_window` 全是 `None`，
   而 `None` 不會令 `ok=False`；`night_pm_stamped_before_file_date` 更根本沒併進 `all_ok`。
   而 OOS(2023-24) 全在夜盤時代 → blocker 2 的機械證明**並不存在**。
3. **accepting the null**：t=+1.469 (p=0.142) 只是「未證明 HAR 勝」，卻被寫成 H2_REJECTED +
   「divergence 是 construction artifact」。要立此論需 **equivalence / noninferiority 檢定**；
   −5.25→−2.06 是描述性比較，未對兩套 paired loss differential 之差做正式檢定。
4. **「完全復現 K1684/K854 的世界」與 JSON 的 11/14 相矛盾**：只有 HAR/RGL cells 逐格復現，
   差的 3 格全是 GJR 家族（10→9、3→2、9→7）。
5. **「差全部來自 RV 重建」無分項 ablation**：新 RV 同時改了 active contract／gap／alignment／
   連續 path 四件事，故「RV 建構吃掉最多」「殘餘 1.075 = composition/basis」皆**未識別**。
6. **JSON limitation #7 自相矛盾**：寫「>=100-start GJR/RGL」與 top-level `rgl_multistart=40` 衝突
   （README 本身寫對）。
7. **無獨立 review receipt**：`k1698/` 目錄內無 referee report/receipt，README §2 的
   「primary-path review PASS」無機械證據。

## 4. 要做的（**順序有依賴，別跳**）

1. **修 contract-selection lookahead**（先做，這步不做後面全部無意義）：
   合約選擇只能用 **13:30 前可得資訊** —— 前一日 volume，或不含當日 13:30 後 tick 的 rolling 規則。
   明確寫下你採用的規則與理由，然後**重跑 RV predictor**。
2. **修 `rv_window_boundary_audit`**：
   - 抽樣必須涵蓋**夜盤時代**與 **OOS 期（2023-24）**，不是最早 60 天
   - `None` 必須令 `ok=False`（缺值不是通過）
   - `night_pm_stamped_before_file_date` 併進 `all_ok`
   - 修完後這個 audit 要能**真的**證明 blocker 2，否則照實說它沒被證明
3. **四層分項 ablation**（無 lookahead 重跑後才做）：active contract / gap / alignment / 連續 path
   逐項開關，才能講「哪一項吃掉多少」。做不完就照實說哪幾層做了、哪幾層沒做。
4. **H2 改用 equivalence / noninferiority 檢定**（TOST 或等價的 paired-loss 版本），
   **不可拿 p=0.142 當「divergence 是 artifact」的證據**。若 equivalence 也不成立，
   就照實寫「既未證明 HAR 勝，也未證明兩者等價」—— null result 如實報告。
5. **修 limitation #7 與 `rgl_multistart` 的矛盾**（以 code 實際值為準）。
6. **把 review receipt 落成檔案**：`experiments/k1698/review_receipt_rev2.json`，
   含 reviewer、model、時間、verdict、逐條 blocker 的處置。
7. **寫 `experiments/k1698/k1698_rev2_results.json`**（本 task 的 result artifact）。

## 5. Heavy compute 紀律

你**已經在 detached compute worker 裡**（不受 hourly fire 的 50min cap 限制），
所以 GARCH MLE / multistart / 全期重跑可以**直接在本 worktree 內跑**，不必再往 compute_queue 遞。
但請控制規模：
- multistart 用 code 現有設定，不要無理由加大
- 固定 seed
- 長跑前先在**小樣本子集**驗證 pipeline 正確（尤其 lookahead 修正後的 contract 選擇）
- 若某一層 ablation 明顯跑不完，**寧可少做一層並如實記錄**，也不要交出半成品數字

## 6. 硬規則

- **禁止寫 `storage/memory/knowledge.json`**（K1259）。產出只進 `experiments/k1698/`。
- 禁止修改 `storage/reports/feed.json`、`storage/memory/*.json`、Supabase / Mirror sync。
- Lookahead 是本 task 的**主題**：任何新寫的 predictor 都要在 code 裡有明確的 lag/資訊集註解。
- **不可 accepting the null**。p>0.05 不等於「沒有差異」。
- 數字全部來自實際計算，禁止估算或沿用舊值充當新結果。

## 7. 成功標準（缺一不可）

1. contract selection **不再使用 13:30 後資訊**，且 code 內有明確註解與規則說明
2. `rv_window_boundary_audit` 涵蓋夜盤期 + OOS 期，`None` 令 `ok=False`，
   `night_pm_stamped_before_file_date` 併進 `all_ok`
3. H2 有正式 equivalence/noninferiority 檢定結果（不論結論方向）
4. `experiments/k1698/k1698_rev2_results.json` + `review_receipt_rev2.json` 存在
5. README 更新：11/14 復現的實情、ablation 做到哪一層、limitation #7 修正
6. worktree 內 `git commit`（**必做** —— 沒 commit 等於工作遺失）
7. 最終回覆：lookahead 修正後數字變了多少、H2 結論是否改變、哪些 blocker 仍未解

## 8. 可保留素材（修完才談短文，本輪不要寫文章）

common-target vs own-target ranking 分歧、RV 建構敏感性、校正機器對 GJR placebo 同樣有效的
否定結果、c_emp 作 ex-post calibration 診斷。
