# K1812 修復 child — block-permutation + README 更正 + 重跑重審（split of agent-brief_k1812_bab_vol）

**Model**: claude-opus-4-8 / xhigh (per model_router)
**Pool task**: K1726 · **Registry k_id**: k1812
**Parent job**: agent-brief_k1812_bab_vol-f55e3c（timeout；已由收件 fire 重跑修復 provenance 漂移，results/spec 現 pin 4b2f8bf3）
**Worktree/cwd**: 本 job 的 cwd（.claude/worktrees/dispatch-slot-2-dc4437b8-k1812）

## 背景（已完成，勿重做）
- 實驗本體（BAB 條件於前期已實現波動，JFE 2025 波動之謎複現）compute 已完成，資料快取於 `experiments/k1812/data/`（82 tickers + market/riskfree/中間 JSON），**離線可重跑，勿重抓 yfinance**。
- 收件 fire 已用磁碟 code(4b2f8bf3) 重跑 → results.json + reproduce_spec.json 現自洽（disk/spec/results code_trace 三方 sha 皆 4b2f8bf3 MATCH），重跑數字與先前 archived 逐位相同（無邏輯漂移）。**故 defect (a) provenance 漂移已解，勿再處理。**

## 必修（Codex round-1 FAIL 的兩條 blocking defect）

### Defect B — 主顯著性檢定未保留時間相依（HARD）
`k1812.py:~527` 的 `sharpe_difference_permutation` 對月份作 **i.i.d. label permutation**，破壞 regime persistence／序列相依，程式自身亦承認可能低估 p（見 `k1812.py:~889` 註解）。HAC regression 只檢定 mean 差、非 Sharpe 差，不能替代。
- **修法**：把 Sharpe 差的主判準改為**保留時間結構**的檢定 —— block/circular-shift permutation 或 stationary bootstrap（保留 regime 連續段）。固定 seed=42、reps≥10000。i.i.d. 版可保留為對照但不得作 primary。
- 重新計算後**如實報告新 p**；結論方向預期仍 NULL（p 原本 0.115 已不顯著，保留 persistence 通常使 p 更大）。conclusion / one_line / README 措辭全部對齊新 primary p，禁止 overclaim。

### Defect C — README 不實審查敘事（HARD）
`README.md:~132–166` 宣稱多輪 Codex review（實際 round-1 才剛做且為 FAIL），且若干初版診斷數字未存於 results.json。
- **修法**：刪除／更正所有不實的「多輪 Codex review」聲稱；移除或補正任何未留存於 results.json 的歷史數字。README 每個關鍵數字必須能程式化對上現行 k1812_results.json。

## 收尾（本 job 內完成）
1. 任何 code 變更後，用 `volpred.research.reproduce_spec.finalize_experiment`（或等效）**同步重產 results.json + reproduce_spec.json**，確保 code/spec/results sha 三方一致（勿手改單邊）。
2. 跑 `uv run python experiments/k1812/test_k1812.py`（或 pytest），須全過。
3. 跑 `uv run python scripts/check_experiment_artifacts.py check --path experiments/k1812`（在 worktree 內）須不再 BLOCKED（knowledge 條目由主線程寫，該項可忽略）。
4. **Codex round-2 二審**（透過 codex 共用 runtime，讀現行 bytes）：驗 defect B/C 已正確落地、無新不一致、結論無 overclaim。
5. 用 `scripts/experiment_gates.py verdict-template --path experiments/k1812` 產模板，填 `verdict`（須 PASS 才算過）、`reviewer`、`reviewed_at`、`blocking_defects`，寫 `experiments/k1812/review_verdict.json`。
6. **禁止**：寫 storage/memory/knowledge.json（K1259，主線程專屬）；merge worktree（由收件 fire 做）；改 experiments/k1812/ 以外的檔；重抓 yfinance。

## 成功條件（result-artifact）
`experiments/k1812/review_verdict.json` 存在且 `verdict=PASS`、`blocking_defects=[]`，且 artifacts gate 對 k1812 不再因 provenance/spec BLOCKED。
