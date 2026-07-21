# K1729 修復：target 端 ex-post 選約 lookahead + nested-DM gate

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Task id**: `assign_c441604e` (P2, starved 89.4h)
**Worktree / cwd**: `.claude/worktrees/dispatch-slot-1-30aeb902-taifexrv`（已存在，branch `wt/dispatch-slot-1-30aeb902-taifexrv`，凍結狀態已 commit 於 `6eeaafe71`）

## 狀態

K1729 被 Codex 二審判 **FAIL**。裁決全文：
- `experiments/k1729/review_verdict.json`
- `experiments/k1729/codex_review.md`

**不要重跑整個實驗。** 主線程已獨立驗證：數字 bit-identical 重現、DM 正確（bandwidth=14，
非 K1655 退化）、baseline 對稱、no-filter 敏感度宣稱為真（|t| 反而升到 3.867/3.456）。
**只修下面兩道牆。**

## 牆 1 — BLOCKING：target 端 ex-post 選約 lookahead

collector 的 `pick_active_contract()` 對 day t 的**整檔**（日盤＋夜盤）volume 加總取 idxmax，
才用選中的合約算 day-session metrics
（`scripts/collect_taifex_tick.py:231-236` → `:302-304`）。

該總量包含 day t 08:45-13:45 的日盤量 —— 在 README 宣稱的「08:45-on-t」forecast origin
**尚未發生**。故 target `y_t` 的 estimand 無法事前固定。

README:74-83 只論證了 t-1 列選約合法（那使 `X_t` 合法，論證正確且成立），**對 target 側
完全沒有論證** → 屬未揭露，非已 scope 的限制。連帶 README:22 與 :166-169 的營運結論
（「08:45 可實作的增益 → 這條資料線值得維護」）超出證據。

**嚴重度（誠實記載）**：缺陷在 target 側、兩模型共用同一 common ledger，幾乎確定不會翻轉
headline（+14.70% / +3.37%）。但 PASS 門檻是「無 lookahead ＋ 射程不超過證據」，
**不是「大概不會翻轉」**。

### REPAIR PATH（便宜；**不需要**重跑 35.9GB raw tick）

- **(a)** 把 ex-post 選約寫成明確 caveat（README + `results.json` 的 `caveats`）
- **(b)** 用 canonical CSV（`data/intraday/taifex_5min_rv.csv` 已有 `contract` / `is_roll` 欄）
  量化模糊集：OOS 期間約 127 個 `is_roll` 列。把這些日子從 ledger 剔除後**重跑 DM** ——
  若判定存活，宣稱就是用**證據**恢復而非斷言；若不存活，**結論必須降級**
- **(c)** 依 (b) 的實測結果重新 scope README §7 的營運結論
- **(d)** 改完 code → sha 漂移 → gate 會自動再擋一次 → **重新派 Codex 審查、重產
  `review_verdict.json`**（**禁止手改裁決檔**）
- **(e)** PASS 後才 merge（`bash scripts/merge_worktree.sh dispatch-slot-1-30aeb902-taifexrv`，
  主線程須先 cd 回主 repo），merge 成功後才由**主線程**寫 knowledge.json（**agent 禁寫**）

## 牆 2 — BLOCKING：nested-DM gate（修好牆 1 仍會擋 merge）

`uv run python scripts/experiment_gates.py run --path experiments/k1729` 目前 FAIL：

```
[nested-dm-misuse] experiments/k1729/k1729.py (primary_raw_dm)
→ nested-model null 下的 raw DM/HLN 不是有效推論。squared-error 用 Clark-West (2007)；
  QLIKE/pinball 用 general-loss / recursive-bootstrap，並把 THAT 接進 verdict。
  若 DM 只是診斷用，寫明 `nested-dm: diagnostic-only` 並移出 claim sink。
  Owner: scripts/tests/test_nested_dm_misuse_ratchet.py
```

**主線程的判讀（供參考，不是結論）**：K1729 比的是 HAR-RV5（regressor = 5-min RV）
vs HAR-DAILY（regressor = 日開收報酬平方）。兩者 HAR(d/w/m) 結構相同但 **regressor 來源不同**，
誰都不是誰的零約束/線性限制 → **非巢套**。DM 正是為非巢套比較設計；Clark-West 才是巢套用的。
故這很可能是 ratchet 的 pattern-match false positive，而非真缺陷。

**官方豁免路徑（存在且有先例，勿自造後門）**：
`storage/ops/nested_dm_misuse_baseline.json` 的 `reviewed_nonnested` 名單。

先例（2026-07-13 審裁，audit: `docs/governance/2026-07/nested_dm_fp_narrowing_audit.md`）：
- `experiments/K1049/K1049.py` — 「三個模型 HAR-RV / GJR-GARCH / A4f-VIX² 互為不同族，無零約束關係」
- `experiments/k1100b/k1100b.py` — 「邊際同為 A4f-ASYM，差異只在 DCC vs t-copula vs Clayton 的
  相依結構（非巢狀族）」

條目 schema：`{site, reason, dm_pairs, adjudicated_at, audit}`

**你要做的**：以與上述先例**同等的嚴謹度**審裁 K1729 是否真非巢套（寫清 `reason` / `dm_pairs`），
若是則登錄 `reviewed_nonnested`；若判定其實有巢套關係，則依 gate 指示改用 Clark-West 或
recursive-bootstrap，並把**那個**檢定接進 verdict sink。

主線程刻意不代為登錄：實驗此刻是 FAIL 狀態、code 還要改，**先豁免等於搶跑**。

## NON-BLOCKING（順手修，不單獨構成 FAIL）

- README:163 把 21 個 `day_return==0` 日寫成 target-B 的 ledger 排除，但 21 是**全檔期間總數**；
  OOS 實際只排除 14 日（2550-2536），其餘 7 日在 OOS 起點前。樣本敘述應區分 full-file 與
  OOS exclusions
- README:131-132,147 的 no-filter 敏感度宣稱無法從三件套稽核（主線程已另行驗證為真）。
  建議把該敏感度路徑收進 `k1729.py` 並把數字寫進 `results.json`，讓宣稱可從三件套自證
- README:8,147 所稱「Codex pre-run review」不是凍結後的 final audit，**不可用來取代裁決**

## 成功判準

1. `scripts/experiment_gates.py run --path experiments/k1729` 綠燈
2. `results.json` 含 (b) 的剔除 roll 日重跑 DM 實測數字 + caveats
3. README §7 營運結論的射程與證據相符
4. 新的 Codex `review_verdict.json` 判 PASS

## 禁令

禁 force push、禁 `--no-verify`、禁假數字、agent 禁寫 knowledge.json（K1259）。
**PASS 前不得 merge。**
