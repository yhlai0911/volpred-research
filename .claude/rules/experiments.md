---
paths:
  - "experiments/**/*"
  - "research_program.md"
  - "docs/error_log.md"
  # 2026-04-20 加：查 knowledge 即為「實驗前查相似 K」階段，規則此刻 load
  # 才能在設計實驗前提醒 lookahead / seed / 文獻先於主題 等防錯規則。
  - "storage/memory/knowledge.json"
  - "storage/memory/experiment_experiences.json"
---

# Experiments / Research Rules

- 任何 `experiments/` 任務都要先讀 `docs/error_log.md`，再決定是否開跑。
- 每個實驗都必須落在 `experiments/<experiment_id>/`，包含 README、腳本、結果 JSON；圖表、references、data 視需要補上。
- 非純探索主題，先做 knowledge search + 文獻搜尋，再開始設計。
- Lookahead 是最高優先風險：
  - `signal from t-1, return at t`
  - 代碼裡要有明確 `signal.shift(1)` 或等效 lag
  - Forward-label target（例如 `fwd_*`, 未來 H 日 RV/variance/return）不可只檢查 feature lag；OOS/expanding/rolling refit 的訓練列必須滿足 `target_end < forecast_origin`，等價於 row `j` 的 label window `j + H < i`，否則訓練尾端會看見預測日或之後的 realized return。
  - 多 horizon forward-label 實驗不可共用同一個 DM/HAC/HLN horizon；每個 target 的 inference horizon 必須等於該 target 的 H。
- 所有隨機程序都要固定 seed。
- 策略與風險管理比較遵守 `research_program.md` 的公平比較、VaR+ES、Harvey / Patton 規則。
- Worktree agent 的產出/共享狀態禁忌與合併流程 → 唯一 owner `.claude/rules/worktree.md`（規則本體）+ error_log §C；本檔不重述。
- 完成實驗後先做 Codex code review，再寫 knowledge / experience / article。
  - **Codex CLI 故障 diagnostic 順序**（2026-04-28 教訓寫入；2026-04-26/27 兩 entries 因順序錯誤花 4 天才修）。Codex error 時**先**這 5 步，不直接懷疑 plugin 版本：
    1. `codex --version` — 看 CLI binary 真正版本（**不**是 `~/.claude/plugins/cache/openai-codex/codex/<x>/` 目錄名，後者是 marketplace plugin 版號）
    2. `codex login status` — 確認 auth mode（ChatGPT account vs API key 接受不同 model whitelist）
    3. `cat ~/.codex/config.toml` 看 `model =` 欄位
    4. **暫時移除** `model = ` line → CLI auto-pick default → smoke test `codex exec --skip-git-repo-check "echo TEST"`
    5. 若 default model PASS 就改回 config 鎖定（2026-07-10 起 canonical = `model = "gpt-5.6-sol"` + `model_reasoning_effort = "ultra"`，CLI 0.144.1 smoke 驗證）；若 default 仍 fail 才考慮 CLI 升級（`npm install -g @openai/codex@latest --include=optional`）
    6. **改 config 的 model 後必跑 smoke**（2026-07-10 incident：config 指到已裝 CLI 不支援的 model → API 400 → 全平台 codex 流程（review gate / lazypack / paper review）靜默失敗數小時；改 config 與升級 CLI 必須同一動作內驗證）
  - **Fallback**：上述 diagnostic 全 fail 仍無法恢復 Codex 時，改派 `feature-dev:code-reviewer` subagent 做 independent fresh-context review（K1259 / K1261 / K1262 已走過此 path）。Knowledge entry 必註明 reviewer source（`Codex review` vs `code-reviewer subagent fallback`）。Bar 不變：CONDITIONAL PASS 以上才寫 knowledge.json。
  - **Codex 已於 2026-04-28 21:58 CST production-path 端到端驗證恢復**（`docs/error_log.md` RESOLVED entry；session `019dd462`，task `task-moioyr49-g0dg9v`）— primary path 是 Codex review，不是 fallback。
  - **Subagent fallback PASS ≠ primary-path Codex PASS**（2026-04-29 K1259 教訓）：subagent 走過 PASS-with-caveats 後若 Codex 恢復可用，**必須**用 primary-path Codex 二次驗證 — 不可只靠 subagent verdict 標 closure。K1259 案例：subagent v1 PASS 標「provenance-clean」，1 天後 Codex v2 在同份 code 找到 12 個 residual non-DM rows（`statistical_tests`/`stat_test`/`welch`/`vs_zero` patterns 全 keyed via `t_stat` 欄位，落在原 audit subset 之外）。Closure 才能立。
  - **Audit methodology hard rule**（2026-04-29 K1259 v2 教訓）：任何 ledger / dataset / output JSON 的 quality audit **必須 re-walk full population**，不可只 sample suspect subset。子集 audit 把 false negative 限在子集外的盲區（K1259 v1 只 audit `t`/`stat`-keyed rows，漏看 `t_stat` priority-5 keyed 的 12 residuals）。Audit doc 須明記：(a) 掃描範圍（全 population 或 subset criteria）、(b) blind-spot 分析（子集外有什麼可能漏掉）、(c) verification 方法（jq / hash / row-count invariant 等可驗證的 evidence）。
  - **K1259 process gate**（2026-05-17 T3）：`src/volpred/memory/system.py:_append_to_index` 現強制 enforce knowledge.json provenance — `verdict == "PASS"` 必須帶 `experiment_id`/`experiment_ids`/`k_id`/`experiment_path`(任一非空) **且** 帶 reviewer 欄位（`reviewer`/`reviewer_source`/`codex_review`/...任一非空）；`verdict == "CONDITIONAL_PASS"` 只需 provenance，不需 reviewer。NULL/FAIL/MIXED/無 verdict 不 gated。Validator: `src/volpred/memory/provenance.py`. CI invariant: `scripts/validate_knowledge_provenance.py`（baseline 284；超過代表有人用 jq/Edit 繞過 Python writer）。測試: `tests/test_knowledge_provenance.py`（19 tests）。手動 jq/Edit 不會被 Python validator 攔截 — 走 CI script 才會發現。

## 實驗完整性 gate（收工前自檢）

```bash
uv run python scripts/experiment_gates.py run --path experiments/<kid>
```

跑下面所有 methodology 硬規則裡**已經機械化**的那幾條（nested-DM 推論、DM 的 HAC 落後期、
Cholesky-FEVD 排序假象、MDD scale artifact），scope 只看你這個 K，已凍結的 legacy debt 不會算到你頭上。

**這是自檢，不是你的責任上限** — enforcement owner 是 compute_queue 的 agent runner：它在標 completed
之前會對 `--result-artifact` 所在的 experiments/ 目錄跑同一支，不過就標 failed 走 triage。你自己的
`test_kXXXX.py` 全綠只證明「它照你想的跑」，證明不了「沒違反 repo 早就用代價換來的規矩」——
K1709 就是自帶測試全過、ratchet 抓得到卻從沒被執行到，一整份 xhigh 實驗白做
（`docs/error_log.md` 2026-07-14）。

## 審查認證：實驗進 main 的唯一門票（2026-07-14）

實驗要合併進 main，`experiments/<kid>/` 必須有一份 **`review_verdict.json`**，且它 pin 住的
sha256 就是**現在這份 bytes**。merge 路徑會擋（`scripts/merge_worktree.sh` → `experiment_gates.py certify`）。

**裁決檔一律由 gate 產生，不要用手抄**（2026-07-14 補；schema 曾有三份副本 → 必漂移）：

```bash
uv run python scripts/experiment_gates.py verdict-template \
  --path experiments/<kid> --out experiments/<kid>/review_verdict.json
```

它會把 claim surface 全部 pin 好，reviewer 只填 `verdict` / `reviewer` / `reviewed_at` /
`reviewed_commit` / `review_artifact` / `blocking_defects`。**派 Codex 審查的 brief 引用這行命令，
不要在 brief 裡重述欄位名** —— 2026-07-14 K1709 rev2 就是 brief 手寫 schema 寫成
`final_verdict` / `claim_surface_sha256`（且只 pin 2 個檔、gate 要 5 個），一輪 30 分鐘 xhigh 審查
若判 PASS 會認證不到任何東西。那次判 FAIL 才沒出事。

Claim surface = `*.py` + `README.md` + `*_results.json`（README 也算：**overclaim 是透過 README 抵達人類的**）。

三個入口全部關上：**沒裁決**擋、**FAIL**擋、**PASS 但審完又改了 code**（sha 漂移）也擋。

第三條是最容易被忽略的一條，也是這條規則存在的理由。2026-07-14 Codex 判 K1709 `k1709.py`
@`e42b0885` FAIL，agent 隨後把兩個 CRITICAL 都修掉了 —— 於是 repo 裡留著一份「對著已不存在的
檔案說 FAIL」的裁決。照著它擋，會擋掉已經修好的版本，並教會 agent「把 review 檔刪掉就過了」；
忽略它，就是 K1709 的原罪重演（有人說「我修好了」就放行）。**裁決只值它當下審的那個快照。**

推論：**agent 自己叫 Codex 來審是安全的** —— 審完再動 code，sha 就對不上，gate 自動再擋一次。
所以流程是「凍結 → 審 → 寫裁決 → 不要再動」；真要改，就重審，**不要手改裁決檔**。

## Methodology 硬規則

### 套件限制 ≠ 模型無效
套件（arch, statsmodels, rugarch 等）在某些 spec 上收斂失敗 / 不支援時，**不可推論模型本身無效**。需自己寫 MLE（通常 scipy.optimize.minimize + analytic gradient）重估。套件 fail 常是 numerical/parameterization 問題，不是模型問題。**K1213 教訓**：用戶研究經驗多次遇到套件限制被誤讀為「模型失敗」。

### `arch` forecast alignment 必須 target 對齊
用 `arch` 做 one-step OOS loss evaluation 時，不可把 default origin-aligned `h.1` forecast 和 same-index realized variance / squared return 直接相比。必須用 `forecast(..., align='target')`，或明確把 origin-aligned forecast shift 到 target return date 後，才計算 QLIKE / MSE / DM tests。**K445 教訓**：same-index 比較 origin-aligned forecasts 會產生 lookahead / off-by-one 風險，不能支撐 production claim。

### QLIKE / DM pointwise loss 必須用 actual over predicted
Variance-forecast QLIKE 的 canonical 方向是 `actual / predicted - log(actual / predicted) - 1`。實驗與 review 不可手寫 `predicted / actual` 反向 QLIKE，也不可在 DM pointwise loss 另開自訂公式；優先用 `volpred.stats.model_evaluation.qlike_pointwise()` 或 `volpred.evaluation.metrics.qlike()`。**K783c 教訓**：反向 QLIKE 會改變 loss asymmetry，並把 DM tests 建在錯誤 pointwise losses 上。

### VaR / ES 的 Basel 與 Student-t 口徑必須明示
VaR / ES 實驗或文章若寫 `Basel` / traffic-light，必須說清楚是標準 250-day count rule、exact-binomial sample-size rule，或自訂 500-day / rate threshold；自訂規則不可包裝成 canonical Basel。GARCH-style Student-t / skewed-t VaR 若用 standardized residual sigma，quantile 必須做 unit-variance scaling（Student-t: `sqrt((df - 2) / df)`），除非模型另有自由 scale parameter 且已報告。**K802 教訓**：rate-based green/yellow threshold 與 raw `t.ppf()` 會把 VaR/ES 結論推成錯誤的 Trinity PASS。

### Retrofit 後 uniqueness claims 必須重驗 current result table
任何「唯一 significant pair」「only Harvey-significant」「唯一通過」等 uniqueness framing，在 HLN / HAC / multiple-testing retrofit 或結果表重算後，必須回到 current results JSON / table 重新驗證；不可只沿用舊 README、舊 motivation、舊文章敘事。若只想談最強或最可見 pair，必須明確寫成 strongest / most visible，不可寫成 only。**K1416 教訓**：Paper3_E2 HLN retrofit 後 `TW0050-HSI` 也變 Harvey-significant，舊的 `TW0050-N225` 唯一敘事必須同步降級。

### Pooled-MLE 必 100+ multistart
所有 pooled / cross-entity MLE（多資產共用參數、多國 panel 估計）必須跑 **≥100 個 random init** + LR test 選 basin + 檢查 log-likelihood 分佈。**K1213→K1216b/K1216c 教訓**：9/9 markets all fragile 時才發現 single-start artifact，fix 後參數 magnitude 變化 5-10x。

### 跨資產 pooled inference 不可把 asset-day 當 iid
多資產 forecast / strategy 檢定若把同一日期的多個資產樣本串成 pooled array，**不得**直接把 stacked asset-day DM / t-test 當 primary publication claim。除非已明確實作並揭露 cluster-robust / panel HAC，否則預設做法是先按日期聚合 cross-asset loss differential，再對日期序列做 HAC / DM；stacked asset-day 結果只能放 diagnostic。**K1355 教訓**：同日跨資產 loss differential 有共同市場 shock，直接串接會低估標準誤並誇大顯著性。

### 修訂型總經資料的 OOS 必須用 real-time vintage，且不得在首次發布日前評分
FRED / 主計總處這類序列，**「今天下載的歷史」≠「當時看得到的歷史」**。兩個獨立陷阱都要擋：
(a) **回溯修訂** — 指數的歷史值會隨新資料與模型重估而改；用 final vintage 做 OOS 等於偷看未來。
(b) **首次發布日** — 很多指數的早期歷史是事後 **backcast** 出來的，當時世界上根本沒有這個數字。
做法：查該序列的 first ALFRED release date，**禁止在該日前的 origin 評分**，並用 vintage API 取每個
forecast origin 當時有效的 vintage 重建特徵。做不到就必須把結果全面改稱 **final-vintage pseudo-OOS**，
撤回 real-time predictive claim，不可包裝成 PIT。
**K1655 教訓**（2026-07-11 Codex primary-path re-verify FAIL）：NFCI 2011 才公開、OOS 從 2004 起 →
343/1131 個預測原點早於指數存在；README 宣稱「rigorous PIT」但實際是 back-stamp 今日修訂後歷史。

### DM 的 HAC 落後期不可只用 `h-1`；先量 acf 再決定
`lag = h-1` 只涵蓋**最適預測下重疊視窗**造成的 MA(h-1)。一旦比較的是**誤設模型 vs 基準**、或預測子高度持續
（NFCI / VIX / 任何慢變總經指標），loss differential 的自相關會遠超 h-1。**h=1 時 `h-1 = 0` 等於完全不做
HAC** — 這個退化行為要當場警覺。硬規則：`lag = max(h-1, repo canonical bandwidth)`，canonical =
`volpred.stats.model_evaluation.dm_test` 的 `ceil(h^(1/3)·n^(1/3))`；並報 lag sensitivity。
**不要自寫 local DM/HLN 實作蓋掉 canonical** — canonical 存在就用它，要另寫必須以它為下限/對照。
**K1655 教訓**：local `hln_dm` 用 `lag=h-1`，h=1→lag=0，loss differential acf(1)=0.68 → |t| 灌水；
修正後 60 個 DM cell 的 Harvey-significant 由 26 掉到 18。腳本裡的 helper 欄位其實一直存著正確答案，
只是沒人拿它當主檢定 — **真正的失效點是「哪個變體餵給對外結論」，不是「程式碼裡有沒有 h-1」**。

**遺漏 HAC 是雙向誤設，不是單向灌水**（2026-07-11 k621 實測補強）：正自相關會放大標準誤（修正後 |t| 變小），
但**負自協方差會縮小標準誤（修正後 |t| 變大，原本不顯著的有可能翻成顯著）**。k621 的 MF2-vs-GJR MSE
loss differential acf(1)=-0.18，補上 HAC 後 |t| 由 2.26 **升到** 3.64（p 0.0237→0.0003）。
所以稽核暴露站點時**先讀 loss differential 的 acf 再判斷方向**，
**不可預設「本來就 null 所以安全」而跳過重跑**。

**本條已機械化（2026-07-11 class sweep）**，這段散文現在只是 pointer：
- **Enforcement owner**（唯一，anti-stacking 勿再加第二層）：`scripts/tests/test_dm_hac_lag_ratchet.py`
  — 新寫的 local DM 若用 `range(1, h)` 當 HAC 迴圈，CI 直接 FAIL。
- **稽核器**：`uv run python scripts/audit_dm_hac_lag.py`（全量 AST 掃 `experiments/**`，分類 bandwidth 規則）。
- **凍結 backlog**：`storage/ops/dm_hac_lag_baseline.json`（139 站點，**只准變少**；修好一個就從 baseline 移除）。
- **全量掃描結果**：`docs/governance/2026-07/dm_hac_lag_class_sweep.md`（含盲區分析與實質性 caveat）。

### Raw max drawdown 不可跨「不同曝險」比較（scale artifact）

**Raw MDD 不是 scale-invariant。** 曝險只有 benchmark 1/4 的策略，回撤機械性偏淺 —— 那叫**少冒險**，
不叫**會擇時**。任何人把部位等比例縮小都能複製整個「改善」。

**硬規則**：兩序列的**實現波動差 > 20%** 時，raw MDD 的差異**不可單獨報告**，更不可當成風險管理
有效的證據。必須同時報**曝險匹配的 MDD gap**（把 benchmark 用常數 λ 縮放到與策略相同的實現波動）。

**但 gap > 0 是必要、不充分條件 —— 這是最容易再犯的一步。** 正的 exposure-matched gap **不能**證明
擇時能力：把策略設計成**時機完全相反**（動盪時加槓桿），它一樣拿得到正 gap。因為匹配「無條件波動」
沒有匹配到**波動的路徑** —— 離散權重把風險集中成爆發，而回撤是持續失血累積的。
**唯一誠實的判準是 gap 對照它自己的相位隨機化 null（circular-shift randomization），不是對照 0。**

**Calmar 不算佐證**（K1265 三個 spec 的 Calmar 全部改善，仍然沒通過檢定）。
**`MDD ÷ 波動` 也不是真正的不變量**（財富複利 → MDD 對槓桿非一次齊次；同一條路徑在不同 λ 下比率會動）。

**本條已機械化，這段散文只是 pointer**：
- **Enforcement owner**（唯一，anti-stacking 勿加第二層）：`scripts/tests/test_mdd_scale_artifact_ratchet.py`
- **Runtime 規則本體**：`volpred.stats.drawdown.compare_max_drawdown` / `assert_drawdown_comparison_is_fair`
  （>20% 波動差就 flag / raise，並算出 exposure-matched gap）
- **稽核器**：`uv run python scripts/audit_mdd_scale_artifact.py --violations-only`
- **凍結 backlog**：`storage/ops/mdd_scale_artifact_baseline.json`（455 sites，**只准變少**）
- **全量掃描報告**：`docs/governance/2026-07/raw_mdd_claim_class_sweep.md`
- **證據**：K1702 §5.4（因子動物園 raw 5/6 → vol-normalized 1/6）、K1265b（SPY VIX-managed：
  raw「50–62% 改善」→ 同風險口徑只剩 9.8–22.1pp，且 Holm 校正後 0/3 存活）

### 跨市場比較必 symmetric refinement
若 benchmark 用 canonical spec（e.g. DEV refined EM）、alternative 用 unrefined EM-only，得到的係數差是 **asymmetric artifact 不是真效應**。必須**兩邊同步 refine** 或**兩邊同 EM-only**。**K1216b ρ=-0.071 教訓**：asymmetric refinement 下 spurious 負相關；K1216c 全 refine 後 ρ=+0.379 與 canonical +0.441 indistinguishable（null）。
