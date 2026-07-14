# K1695 exposure-matched 更正 — 交接給主線程

- **Agent job**：`agent-brief_k1695_correction-c841cc`（P1）
- **Commit**：`bdf6b451f`（只動 `experiments/k1695/`）
- **完成時間**：2026-07-15 06:18 台灣時間
- **狀態**：實驗更正**已完成並 commit**；**認證（certification）未完成** — 見下方「未竟事項」

## 主線程要逐條核對的數字（不要採信本文，自己重算）

重跑指令（讀 pinned snapshot，不連網，約 40 秒）：
```bash
uv run python experiments/k1695/k1695.py
uv run --extra dev python -m pytest experiments/k1695/test_k1695.py -q   # 19 passed
uv run python scripts/experiment_gates.py run --path experiments/k1695   # PASS
```

| 項目 | inception-aware | common (2012–2026) |
|---|---:|---:|
| raw 平均 ΔMDD（**保留，未刪**） | +27.50 pp（13/13 正） | +12.61 pp（13/13 正） |
| **同曝險平均 ΔMDD** | **+4.96 pp（12/13 正）** | **−0.87 pp（7/13 正）** |
| VT/BH 實現波動比 | 0.52–0.66（13/13 mismatch） | 0.61–0.68（13/13 mismatch） |
| circular-shift null p（同曝險） | **0.212** | **0.559** |
| circular-shift null p（**raw**） | **0.039（拒絕！）** | 0.106 |
| Holm 存活市場數（α=0.10） | 0 / 13 | 0 / 13 |
| 不看 VIX 的常數減碼策略：raw ΔMDD | +16.20 pp（13/13 正） | +10.68 pp（13/13 正） |
| 同上：同曝險 ΔMDD | −0.06 pp | +0.01 pp |

- 同曝險 joint-bootstrap 90% CI = **[−7.02, +3.59]**（含 0）；raw CI = [+4.22, +19.30]，
  **與 2026-07-12 已發表數字逐位吻合** → 差異來自口徑不是 bug。
- `decision.kill_triggered = true`、`claim_status = "retracted"`。
- JSON 路徑：`$.inference.circular_shift_null.{common_period,inception_aware}`、
  `$.inference.no_timing_reference`、`$.samples.*.summary.average_exposure_matched_delta_mdd_pp`、
  `$.samples.*.rows[*].exposure`。

## ⚠️ raw null 會拒絕 —— 這一點務必看懂再改論文

inception 的 **raw** ΔMDD 對照相位 null 是 **p=0.039，在 α=0.10 下拒絕**。這是**唯一**能被拿來
救回原結論的數字，所以我把機制**量出來**而不是繞過：

> 觀察到的相位，在它自己權重路徑的**全部 231 個相位**中，實現波動**排名第 1（最低）**
> （common 是 2/170）。VIX 確實能預測波動 → 12/VIX **真的會**在動盪月份減碼。
> 但那是**降低風險**，而 raw MDD gap 獎勵的正是降低風險。
> **降風險 ≠ 同風險下回撤更淺** —— 後者才是被撤回的那項 contribution 主張的東西。

寫論文/文章時**不可**寫成「12/VIX 什麼都沒做」。正確說法是：**它確實降了風險（顯著），
但它沒有提供超出降風險本身的 drawdown protection（不顯著）。**

## 結論的強度邊界（不可超譯，兩個方向都不行）

- ✅ raw 13/13 是 exposure artifact（常數減碼策略複製 85%/59%，同曝險 gap ≈ 0）
- ✅ common 樣本同曝險 gap 與無擇時 null 無法區分
- ❌ **不可說「擇時有害」** — 點估計為負但落在 null 正中央 = 沒偵測到效果 ≠ 偵測到負效果
- ❌ **不可說 inception 的 +4.96 pp 已被推翻** — p=0.212 不顯著，但它也沒被否證；來自 2008 單一危機

## 未竟事項（主線程接手）

1. **認證未完成（blocker）**：**沒有** `review_verdict.json`。
   - primary-path Codex review 逾時（Bash tool 10 分鐘上限），已 enqueue 到 compute_queue：
     `compute-tmp-k1695-codex-review-job-sh-1784066358`，輸出將落在
     `experiments/k1695/codex_review_20260715.md`（**不在 claim surface，不會讓 sha 漂移**），
     prompt 存於 `storage/ops/k1695_codex_review_prompt.txt`。
   - 本班改跑 fresh-context reviewer 取得同步裁決 → **CONDITIONAL_PASS**，2 個 blocking defect
     （B1 raw-null 被我灌強成「被吃掉」；B2 inception 位移群用 union span 餵給 INDA/MCHI
     沒交易過的月份）**都已修並重跑**。因為 code 在審後又改，**sha 已漂移 → 必須重審一輪**。
   - Codex 收稿後：`uv run python scripts/experiment_gates.py verdict-template --path experiments/k1695
     --out experiments/k1695/review_verdict.json` → 由 reviewer 填 verdict。
   - **K1259 教訓**：subagent PASS ≠ primary-path Codex PASS，closure 要 Codex 二次驗證。
2. **knowledge.json 更正 K1695 條目** — 主線程驗過 + Codex 審過才寫（agent 禁寫）。
3. **paper `vt-trend-following`**：Table 5 需加同曝險欄位；第三項 contribution（international
   drawdown protection）依上述強度邊界**撤回或改寫**（不可寫成「擇時有害」）。
   解除 `storage/paper_pipeline_status.json` 的 blocker。
4. **feed 回溯更正**：`next_tasks` 的 `feed_correction_k1695_exposure_artifact`。
5. **MDD ratchet baseline**（`storage/ops/mdd_scale_artifact_baseline.json`，屬主線程 scope）：
   k1695 的 6 個站點已修好 4 個（`_summary`／`joint_mdd_bootstrap`／`run_experiment`／`main`
   由 RAW_COMPARISON → NORMALIZED），可從 baseline 退休並移入 `retired`。
   剩 2 個（`compute_metrics` 單序列、一個舊 bootstrap 測試）維持凍結。
6. **同 bug class 的真正根因仍在**（驗證文件 §3 已指出）：`compare_max_drawdown` 會亮旗，
   但**沒有機械 gate 強制實驗必須用它**。K1265b / K1702 / K1695 三次同根因 → 已達 3-strike。
   建議把「實驗若比較 ≥2 條序列的 MDD，必須呼叫 canonical helper」升級成 runtime gate
   （目前 ratchet 只擋 AST 層的新增站點，擋不住「用了 helper 但不看 exposure_mismatch」）。
