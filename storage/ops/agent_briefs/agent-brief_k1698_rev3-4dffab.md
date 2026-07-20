# K1698 rev3 bounded remediation — Codex round 3 FAIL 的逐條修復

**Model**: opus / xhigh (per model_router)
**Worktree**: `.claude/worktrees/dispatch-slot-2-c5cafe39-k1698`（你的 cwd 就是這裡）
**Task id**: `k1698_rev3_remediation`
**來源判決**: `storage/ops/codex_reviews/k1698_rev2b_verdict.md` → VERDICT: FAIL（round 3）
**硬規則**: 此 worktree **禁止 merge**，直到 round 4 PASS。

## 共同根因（先讀懂再動手）

rev2b 的修正多半只落在 README 與 canonical q1/q2 欄位，**PRIMARY JSON（`k1698_rev2_results.json`）的頂層敘述層沒跟著改**；而那些字串是 `k1698.py` 結果組裝區 hard-code 的 —— 所以**改 JSON 沒用、重跑會再生**。

**修法必須落在生成器（`k1698.py`）再重跑。禁止直接手改 JSON。** 這是本輪最重要的約束：上一輪就是因為手改 JSON 才會 round 3 再 FAIL。

## 逐條 blocker（8 條，全部要修）

1. **CRITICAL-1** — PRIMARY JSON 仍主張已作廢的 non-invariant loss-level margin。invariant 計算本身是對的，錯在頂層宣稱。
2. **MAJOR-2** — mask 與輸出已修，但 README 仍寫「三天改變」，實際是**兩天**。
3. **MAJOR-4** — PRIMARY JSON `honest_reading` 仍寫 q2 有 formal support（`|t|=3.13>3`），未帶 bandwidth flip / post-hoc / multiplicity 三個 caveat（`results.json:124`）。這等於把 rev2b 宣稱已移除的推論放回去。
4. **MAJOR-5** — 只有 q2 有 `PREREGISTRATION_STATUS: POST_HOC`；q1 equivalence 與 `rv_ablation` 在 PRIMARY JSON 無此欄位，且 generated `limitations` 無全域 post-hoc/multiplicity 揭露。
5. **MINOR-6** — PRIMARY JSON `what_the_route_prose_over_reads` 仍是「~14% of benchmark loss」與舊的「below 20%」grid 措辭，與 canonical q1 的 `delta_min_at_5pct` 精確門檻矛盾（`results.json:123`）。
6. **STILL-OPEN-7** — `review_receipt_rev2.json` 與 `review_verdict.json` **都不存在**，但 README:56 與 `results.json:12` 都宣稱有。repo merge gate 本來就要求 `review_verdict.json`。
7. **新 MAJOR — 生成器殘留**：`k1698.py:3154`、`:3238` 的結果組裝區仍 hard-code 舊 rev2 字串，重跑會重現 false loss-level margin、14%/20% 措辭與 q2 overclaim。
8. **新 MINOR — runtime drift**：README 寫約 260 秒，frozen receipt 與 JSON 是 **288.8 秒**。

## PASS 的部分 —— 不要動

- MAJOR-3（active-contract stamp / evidence-based classification / anywhere-abort）
- STILL-OPEN-3（route label 修訂透明、原字串保留兩份、`route_label_amended=true`）
- headline gate 與 FRL/JoF short-note route 的措辭誠實，`GATE_REASON` 已明說 HAR 優越與等價**皆未成立**

改動要 bounded：只碰上列 8 條所需的最小面，不要順手重構。

## 驗收（缺一不可）

1. 全部 8 條逐條給 **before/after + 檔案:行號證據**
2. 改完在 worktree 內**重跑**產生新 JSON（不是手改），確認殘留字串消失 —— 明確 grep 驗證「14%」「below 20%」「三天」「loss-level margin」等舊字串已不再出現在生成物
3. 產出 `review_verdict.json`（用 `scripts/experiment_gates.py verdict-template`）
4. 修 README 的 runtime 數字與 receipt 宣稱，使其與實際 frozen receipt 一致（不存在的檔案就不要宣稱存在）

## 產出

把本輪結果寫成 `experiments/k1698/k1698_rev3_remediation.json`，內含：
- `blockers`: 8 條，每條 `{id, status: fixed|not_applicable, before, after, evidence: ["file:line", ...]}`
- `rerun`: `{command, exit_code, runtime_sec, output_json_path}`
- `residual_string_scan`: grep 驗證結果（舊字串 zero hit 的證據）
- `review_verdict_path`
- `unresolved`: 任何你沒能修掉的，誠實列出並說明原因（**寧可誠實留白，不可假裝修好** —— 這是第三輪 FAIL，再假修會直接被 round 4 抓到）

## 禁令

- ❌ 不要寫 `knowledge.json`（K1259：agent 禁自寫，由主線程寫）
- ❌ 不要 merge worktree、不要 `git push`
- ❌ 不要手改 JSON 生成物來「達成」驗收
- ❌ 不要編造數字。任何數字都要能指回檔案:行號或重跑輸出
