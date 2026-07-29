# K1736 收件審查 — round 2（主線程數值核實 + 獨立敵意程式碼審查）

- **收件人**：hourly-dispatch slot-1（job 5738de9c5aa5470db484b65b881147f0）
- **審查時間**：2026-07-30（台灣時間）
- **被審 commit**：`0974370d9`（worktree `dispatch-slot-1-e9403ded-k1736`）
- **上游 compute job**：`agent-brief_k1736-36bc4e`（exit 0、`result_artifact_exists=true`、`validation_ok=true`）
- **被審宣稱**：`verdict_block.verdict = NULL_DEGENERATE`

本輪不是重跑實驗，而是回答一個問題：**results JSON 裡的每個 headline 數字，是不是真的從
64 個 univariate cells / 32 個 multivariate rows / 35 個 OOS cells 算出來的，還是寫死的。**
方法是把 `verdict_block` 的每一個計數器丟掉，只吃原始 cells 重算一次，再跟宣稱對帳。

---

## A. 交付物完整性

| 項目 | 結果 |
|---|---|
| 實驗三件套（README / .py / _results.json） | ✅ 齊 |
| 圖表 | ✅ 2 張（degeneracy_and_tstats、slope_level_and_targets） |
| 凍結資料 | ✅ `data/` 6 個 CSV，sha256 全數列於 `reproduce_spec.json` |
| `reproduce_spec.json` | ✅ schema v1，entrypoint sha256 = `ab037e14…`，`network=deny`，seed 宣告 numpy=42 |
| `scripts/experiment_gates.py run` | ✅ **PASS** — 4 項 experiment-integrity gates 全過 |

---

## B. 數值核實：`verdict_block` 每一個計數器獨立重算

全部從 `univariate_cells` / `multivariate_incremental` / `out_of_sample` 原始列重算，
**逐項對得上，零筆不符**：

| 宣稱 | 宣稱值 | 重算值 | 對帳 |
|---|---|---|---|
| `n_cells_tested` | 64 | 64 | ✅ |
| `n_cells_abs_t_hac_gt_3` | 6 | 6 | ✅ |
| `n_slope_cells_surviving`（排除 vts 控制項後） | 3 | 3 | ✅ |
| `n_slope_cells_surviving_at_6_to_12_month_horizons` | 0 | 0 | ✅ |
| `max_abs_t_hac_over_slope_cells_at_H_126_252` | 1.1162 | 1.1162（`srp_slope_6m`\|`fwd_mdd`\|126） | ✅ |
| `max_abs_incremental_t_at_H_126_252` | 2.15 | 2.15（`rn_slope_3m`\|`fwd_mdd`\|252） | ✅ |
| `best_oos_r2_over_slope_cells_at_H_126_252` | 0.000257 | 0.000257 | ✅ |
| `n_slope_oos_cells_with_positive_r2_and_cw_p_lt_05` | 2 | 2（皆在 H=21） | ✅ |
| `n_slope_oos_cells_positive_at_6_to_12_month_horizons` | 0 | 0 | ✅ |
| `n_joint_survivors` | 0 | 0（長 horizon 無任何 cell 同時過 RW+Hodrick） | ✅ |

**重要的口徑澄清（初次對帳曾出現落差，查明是定義而非錯誤）**：`signal_kind` 有四類 ——
`level`（skew_level / srp_30d）、`slope_model_extrapolated`、`slope_physical_only`、
`variance_term_structure_control`（vts_3m / vts_6m）。`verdict_block` 的「slope」一律**不含**
variance term-structure 控制項。用含控制項的定義重算會得到 6 而非 3、max|t|=2.11 而非 1.12。
JSON 的口徑是對的（控制項本來就不是被檢定的偏度訊號），但這個口徑只寫在
`construction.signal_families` 裡，`verdict_block` 本身沒複述 —— 引用時務必留意。

---

## C. 重疊觀測與標準誤：宣稱 vs 實作

- **HAC bandwidth**：宣稱 `lag = max(H, ceil(H^(1/3) n^(1/3)))`。逐 cell 檢查
  **64/64 皆滿足 `hac_lag >= H`**，無一例外。
- **`t_hac == beta / se_hac`**：64/64 誤差 < 0.02。沒有一個 t 是獨立寫進去的。
- **Hodrick 1B 的 scope 限制被真的執行了**：宣稱「Hodrick 1B 只對
  sum-of-one-period-returns 目標有定義，對 max-drawdown 這種 path functional 沒有」。
  逐 cell 檢查 **零違規** —— 32 個 `fwd_ret` cell 全部有 Hodrick SE，32 個 `fwd_mdd` cell
  全部沒有。這是本輪最值得肯定的一點：**它在該給不出數字的地方留白，而不是硬擠一個數字出來。**
  代價是 §D 的 6 個 `|t|>3` 存活 cell 全在 `fwd_mdd`，只有 HAC + 非重疊兩種重疊處理。
- **多重檢定單調性**：`p_holm_within_family >= p_hac` 與 `p_holm_global >= p_hac`
  **64/64 成立**（調整後 p 不可能小於原始 p，這是最容易被寫錯的地方之一）。
- **Romano–Wolf**：B=2000、seed=42、circular block bootstrap、block length = family 內最大
  horizon（252）、每 replicate 只有 19–34 個 block —— block 數少是資料本身的獨立性上限，
  README §9.3 已如實列為局限。

---

## D. NULL 是真的沒訊號，不是 bug

三項反證檢查：

1. **不是 all-NaN / 樣本崩掉**：64 個 cell 的 `beta`/`se_hac`/`t_hac`/`r2` 零個 NaN；
   `n_overlapping_obs` 落在 4356–8335，三個 family 的樣本數各自成群
   （A_long 7926–8335 / C_mid 4724–5018 / B_short 4356–4650），與各自的資料起始日一致。
2. **ESS 合理**：每個 cell 的 `effective_sample_size` 都在 `n/H` 的 0.3–3.0 倍內，
   沒有一個 cell 用重疊樣本冒充獨立樣本。H=252 的 ESS 只有 31.5，
   **這正是 README §9.2「power-limited NULL」的量化依據** —— 長 horizon 找不到訊號，
   有多少是真的沒有、有多少是檢定力不足，這份資料分不開，不可宣稱為「精確估計出的零」。
3. **確實有東西通過門檻，只是不含偏度**：6 個 `|t_hac|>3` 的 cell 全在 `fwd_mdd`，
   其中 t 最大的兩個（`vts_6m` t=-4.43 holm_global=0.00064、`vts_3m` t=-3.78
   holm_global=0.0098）**是變異數期限結構控制項，不是偏度訊號**。
   一份會把所有東西都算成 NULL 的壞 pipeline 不會長這樣。

## E. 退化判定（D1）站得住腳

| 訊號 | corr vs SKEW level | level 解釋的 R² | 判定 |
|---|---|---|---|
| `ts_realized`（純實際偏度斜率） | 0.0965 | 0.0093 | 不退化 |
| `rn_slope_3m` | −0.9266 | 0.8585 | **退化** |
| `rn_slope_6m` | −0.9440 | 0.8911 | **退化** |
| `srp_slope_6m` | −0.9326 | 0.8698 | **退化** |

門檻 |corr| > 0.9 被一致套用。旁證：multivariate 表的
`r2_slope_explained_by_controls` 最大值 0.9798、VIF 最大 49.6 —— 與退化診斷互相印證。
退化的**成因也有解析解**：CBOE 只在 30 天到期發布 `^SKEW`，沒有免費的 SKEW3M/SKEW6M，
所以 `ζ(T)` 是用 `ζ30 · sqrt(30/T) · (VIX/VIX_T)³` 外推的；
JSON 的 `analytic_note_iid_only_slope` 自己算給你看：純 iid sqrt-scaling 的斜率與 level
相關係數**恰為 1.0**，唯一能打破這個恆等式的只有觀測得到的 VIX/VIX_T 比值 —— 而它顯然不夠。

**這是本實驗最誠實的地方，也是它的天花板**：D1 判 `FAIL_degenerate` 不是「找不到訊號」，
而是「在只有 30 天 RN skew 的免費資料下，這個問題根本問不出來」。README §11 因此列出
重開此題的前提（需要真正的多到期 RN skew）。引用本結果時**不可**簡化成
「偏度期限結構無效」，正確表述是「用 30 天 SKEW 外推出的期限結構斜率與 level 無法區分，
而唯一非退化的實際偏度斜率在 6–12 個月 horizon 上檢定力不足以下結論」。

---

## F. 上一輪 Codex 審查（實驗 agent 自跑，README §10）

實驗 agent 完成後自行跑了一輪 Codex primary-path 有界審查，判 FAIL，兩個 blocking defect 皆已修：

1. **POSITIVE gate 可拼裝不相關證據** — 原本 IS / OOS / incremental 三腿可以來自不同 cell。
   已改為 §5.6 的 joint gate（同一 (signal, target, horizon) 三元組同時過三關，缺腿 fail closed）。
   對現行結論無影響（三腿本來就都是空的），但這段程式正是「資料換個樣子就會誤宣稱 POSITIVE」
   的機器，必須是對的。
2. **Hodrick 1B 的 `w_t` 建在 `dropna()` 之後的壓縮陣列上** — `^SKEW` 有 0.878% 的 NYSE session
   缺報價，壓縮後 `w_t` 往回加的是「前 H 個**有值的**列」而非「前 H 個**交易日**」。
   已改吃 calendar-indexed series。修正後 Hodrick t 幾乎不動
   （例：`skew_level`\|`fwd_ret`\|252 由 −0.4256 → −0.4260）。缺陷是真的，對結論無實質影響。

Codex 另指出原 lookahead audit 偏 tautological，已擴充為 5 項檢查。
`methodology.lookahead_audit.all_passed = true`，8 個訊號逐一驗證
`regressor(t) == raw_signal(t-1)`，並獨立重算 `fwd_ret_252` / `fwd_mdd_252`
與驗證 OOS 訓練切點 `j + H <= i`。

**該輪自審是有界的（只聚焦 4 個高風險實作），不是完整 claim-surface 認證**，
且是實驗 agent 自己派的 —— 故本輪另跑一次獨立敵意審查，見 §G。

---

## G. 本輪獨立敵意程式碼審查

派一個獨立 agent（opus，指令是**敵意審查**：預設要找出「這個 NULL 是 bug 造成的」），
不准改檔、不准看 README 推論、必須引用行號。**判 PASS_WITH_NOTES**，並在凍結資料上
**重跑得到 byte-identical 的科學 payload**（剔除 `code_trace` / `runtime_seconds` / `runtime_env` 後）。

五個軸的結論：

| 軸 | 結果 | 關鍵證據 |
|---|---|---|
| 1. Lookahead | OK | 四條會讓 regressor 碰到 target 的路徑（univariate L726 / multivariate L805-806 / subperiod L960 / OOS L1041）全部走 `.shift(1)`；Romano–Wolf 重用 cells 存好的 `_x`（L786-788→L882），沒有 call site 繞過 lag。`forward_drawdown` L378-394 用 `range(n - horizon)` 排除截斷窗口，`np.maximum.accumulate` 在 t 重置峰值。SKEW 缺報價的列**直接丟棄**，不在迴歸路徑上 ffill |
| 2. 重疊觀測 | OK | `canonical_hac_lag` L527-536，64/64 cell 的 lag ≥ H；`n//4` 上限（L550）從未觸發。Hodrick scope 限制在 L745-746 用 `if base == "fwd_ret"` 真的擋住。`nonoverlapping_phases` L639-676 以壓縮列前進 H，跨越的 session 數 ≥ H，故分期保守互斥。OOS 的 Clark–West 用 origin 單位的重疊 `ceil(H/STEP)`，35/35 cell 的 `cw_lag ≥ h_origin` |
| 3. 多重檢定 | OK | block index 每個 replicate **抽一次**（L892）給 family 內所有 cell 共用（L893-896）—— common row index 宣稱屬實。seed 固定（L889，`SEED=42`）。stepdown L898-909 為正確的降冪 / remaining-max / 單調 Romano–Wolf |
| 4. 退化判定完整性 | OK | L335-348 對 4 個 `SIGNAL_KIND` 以 slope 開頭的訊號套 \|corr\|>0.90。`FAIL_degenerate` 只由 model-extrapolated 子集驅動（L1142-1146），`ts_realized` 被排除並另外呈現 —— 對「risk-neutral slope constructions」的宣稱而言是正確的 scope。**不是壞掉的樣本**：無 all-NaN 欄、n 隨各序列起始日精確遞減、且 pipeline 確實吐得出 6/64 個 \|t\|>3，不是把全部算成 null |
| 5. 造假 | **ISSUE ×1** | 見下 |

### 本輪發現的三個缺陷（皆已當班修正）

**ISSUE-1（造假，已修）** — `K1736.py:353-359`
`analytic_note_iid_only_slope.corr_with_skew_level = 1.0` 是**寫死的、沒算過的，而且正負號是錯的**。
`skew_level` 就是 `zeta30` 本身（L265），而 iid-only 斜率 = `zeta30·(√(30/T) − 1)`，
T=93 時乘數為 **−0.432038**（負數），故相關係數是 **−1.0** 不是 +1.0。
**修法**：不改成正確常數，而是**把序列建出來實測**（新增 `multiplier_at_T_93` / `corr_source` / `n=8356`）。
`|corr| = 1` 的退化結論不受影響，但「沒人算過的數字」正是錯誤數字能存活過審查的原因，
不可以只改常數了事。

**ISSUE-2（驗證表演，已修）** — `K1736.py:465-481`
lookahead audit 的第 3 項檢查是**恆真的**：`last_train_row + H = (i − H − 1) + H = i − 1`，
所以 `if last_train_row + H > i` 化簡成 `i − 1 > i`，**永遠不可能成立**。
它無條件 pass，對偵測 OOS lookahead 的檢定力是 **0**。實際的 OOS 迴圈（L1047-1063）獨立讀過是對的，
所以沒有真的 bias —— 但 JSON 印出 `passed: true` 等於誇大了被驗證的東西。
**修法**：改成量測本身 —— 從最後一列訓練資料**自己的日期**沿 **SPY session 日曆**往前走 H 個 session，
斷言該窗口在 origin 日期當天或之前關閉。這個檢查獨立於它所稽核的列運算，
迴圈若有 off-by-one 或正負號錯誤現在會浮出來。
修正後：`n_origins_probed = 666`，`min_gap_sessions_between_window_close_and_origin = 1`
（最緊的情況下窗口在 origin 前 1 個 session 關閉 —— 貼齊但不越界），仍 `passed: true`。

**ISSUE-3（死碼 / docstring 誇大，已修）** — `K1736.py:455-456`
迴圈體末尾的 `if date + pd.Timedelta(days=1) > signals.index[-1]: continue` 是 no-op；
且 L440-441 的註解宣稱檢查 (2) 會驗「target 不得在自己的 origin 日期之前可觀測」，實際上它只驗
t−1 regressor 恆等式。JSON 的 `name` 欄位本身是準確的，故無錯誤數字外流。**修法**：刪 no-op、改正註解。

### 修正後的重跑對帳

重跑後與修正前的 results JSON 做全樹 diff（忽略 `created_at` / `runtime_seconds` / `runtime_env` / `code_trace`）：
**僅 9 處差異，全部落在上述兩個欄位群內**。64 個 univariate cells、32 個 multivariate rows、
35 個 OOS cells、整個 `verdict_block` **逐位元不變**。
`verdict = NULL_DEGENERATE` / `D1 = FAIL_degenerate` / `D2 = MIXED_OR_FAIL` 不動。
`lookahead_audit.all_passed = true`（5/5），`experiment_gates.py run` 仍 PASS。

### 審查者提出、本輪未動的觀察（不影響裁決，記錄供後續引用）

- **Romano–Wolf 的 studentisation（L886, L896）** 用原始樣本的 HAC SE 同時除觀測值與 bootstrap 統計量。
  若 block bootstrap 低估了真實 long-run variance，RW 的 p 值會偏 anti-conservative ——
  這只會讓存活者**更容易**出現，因此**不可能製造出一個 NULL**。方向對本結論安全。
- **本實驗最強的證據坐落在 H=21 的 `fwd_mdd`，而那不在假設範圍內**。該處有 3 個 slope cell
  + 2 個變異數期限結構控制項通過 RW（`rn_slope_6m|fwd_mdd|21` 的 21/21 個非重疊分期 \|t\|>3、
  t_mean = −4.38、OOS R² = +0.11、CW p < 0.001）。它被 L1212-1216 事前宣告的 `LONG_H={126,252}`
  規則排除在 POSITIVE gate 之外，且**有**列進 `verdict_block.surviving_cells`（沒有藏）。
  關鍵是：該 cell 的 slope multivariate incremental t ≈ 0（rn_slope_6m −0.258、srp_slope_6m −0.382），
  而 `vts_6m` 控制項帶 t = −2.24 / −3.03 —— **H=21 的結果是變異數期限結構，不是偏度**。
  這強化而非削弱 `NULL_DEGENERATE`。
- **重跑套件可用性**：以實驗目錄為 cwd 執行 `K1736.py` 會在 `finalize_experiment` →
  `reproduce_spec.trace_file` 崩潰（L1469-1476 的路徑相對 repo root 解析），**必須從 repo root 跑**。
  且 `finalize_experiment` 在崩潰點**之前**就寫出 results JSON，所以一次失敗的執行會覆蓋 canonical result。
  本輪審查 agent 就踩到了這個坑，已用 `git checkout --` 還原並經主線程以 sha256 驗證
  （`acf1fa3e…` 與 HEAD 一致、工作區乾淨）後才繼續。**這是下一個碰這份實驗的人最該先知道的事。**
- `GSPC.csv` 有抓取、有列入 reproduce_spec inputs 並雜湊，但**未進入任何訊號、目標或迴歸**；
  `RNG`（L84）是死碼；餵給 RW/Holm 的 `t_obs`/`p_unadj`（L886, L911）是 4dp/6dp 的四捨五入值
  而非原始浮點數 —— 影響微不足道，但記錄在案。

---

## H. 裁決

**PASS** — 見 `review_verdict.json`。

`NULL_DEGENERATE` 不是 bug 造成的：重跑逐位元一致、lookahead 五項檢查（其中一項本輪才被修成
真的有檢定力）全過、64 個 cell 的 HAC lag / t 一致性 / Holm 單調性零違規、
`verdict_block` 十個計數器獨立重算全部對上。三個缺陷都已當班修完，且都不動結論。

**引用本結果時的正確口徑**（不可簡化）：
> 在只有 CBOE 30 天 `^SKEW`（無免費 SKEW3M/SKEW6M）的資料條件下，用它外推出的偏度風險溢酬
> 期限結構斜率，與 SKEW level 在統計上無法區分（R² 0.86–0.89 被 level 解釋）；
> 唯一非退化的實際偏度斜率（`ts_realized`，corr 0.0965）在 6–12 個月 horizon 上
> **有效樣本數僅 31.5–64**，檢定力不足以支持任何方向的結論。
> 這是一個 **power-limited、且被資料可得性封頂的 NULL**，不是「偏度期限結構無預測力」的精確估計。
