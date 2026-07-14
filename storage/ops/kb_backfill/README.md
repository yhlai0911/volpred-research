# 知識庫補登稽核：136 個對 dedup 隱形的已完成實驗

**執行**：2026-07-14（hourly-17 dispatch，task `kb_backfill_unrecorded_experiments`）
**觸發**：`scripts/reproduce_check.py` 新增的 `KNOWLEDGE_UNRECORDED` 維度 — 1,252 個有 `*_results.json` 的實驗中，136 個（約 11%）在 `storage/memory/knowledge.json` 完全查無條目，因此對選題查重與 dedup gate 是隱形的。

**本目錄只產提案，不寫 canonical。** `knowledge.json` 的寫入由主線程驗證後執行（CLAUDE.md 硬規：agent 不得寫知識庫）。

## 產出物

| 檔案 | 內容 |
|---|---|
| `proposed_entries.json` | 136 筆提案 entry（本次唯一交付物） |
| `unrecorded.json` | 稽核當下的 136 個實驗清單（凍結快照） |
| `shards/shard_0*.json` | 10 個 subagent 的原始提案分片 |
| `merge_proposals.py` | 合併 + 機械驗證腳本（可重跑） |

`item_id`（實驗目錄名 sha1 前 8 碼）與 `created_at` 由 `merge_proposals.py` 從 artifact 機械推導，**不由 agent 填寫** —— 減少捏造面。`created_at` 有 81 筆取自 artifact 內的日期欄位，55 筆退回檔案 mtime（`created_at_source` 欄位標示來源）。

## 統計

- 總筆數 **136**（覆蓋率 136/136，無遺漏、無重複）
- `needs_human: true` **29 筆**（21%）—— artifact 缺明確 verdict / 統計量，或本身就不該當研究發現收錄
- confidence：≥0.8 有 77 筆、0.5–0.79 有 42 筆、<0.5 有 17 筆

**verdict 分佈**：NULL 49、CONDITIONAL_PASS 30、DOCUMENTED_NEGATIVE 15、INCONCLUSIVE 14、UNVERIFIED 13、PASS 9、FAIL 6。

NULL + DOCUMENTED_NEGATIVE + FAIL 合計 70 筆，超過一半。**這正是知識庫最缺、也最該補的部分** —— 失敗與 null 結果沒進庫，系統就會一再重跑同一個死胡同。

**category 分佈**：vol_prediction 56、market_context 15、cross_asset 14、research_methodology 12、data_property 12、vt_strategy 11、experiment_result 7、model_behavior 5、strategy 3、literature 1。

## 驗證

`merge_proposals.py` 對每一筆機械檢查：evidence 路徑真實存在（不存在的一律剔除）、content 必須提及該 K-id、category/verdict 在白名單內、`needs_human` 必附 `gap`、`item_id` 不與既有 2,509 筆 knowledge entry 碰撞。結果：**validation OK**，1 個警告（k1607 引用了一個 README 承諾但從未產出的 `codex_review.md`，該路徑已剔除）。

隨機抽驗 5 筆逐字對照 artifact，數字全數吻合：

- K1325：HAR QLIKE 0.264861→0.265、RW 0.374551→0.375、DM-HLN t 0.882689→0.88 ✓
- K1331：n_obs 3,090 ✓
- K1523：TWII H1 t=-2.8659→-2.87、H2 t=-2.7085→-2.71 ✓
- K1699：SPY t_stat 0.7414→+0.74、QQQ 2.2819→+2.28、n=1,823 ✓
- K1458：加法恆等式 SPY 2020-03 −0.0843+0.1220=+0.0377 ✓

## 不可靠 / 不宜直接收錄的案例（誠實清單）

### 1. 研究誠實紅線：README 宣稱與結果檔矛盾

**K1523**（realized kurtosis）—— README 寫「TWII: H1 PASS (t=-3.14), H2 PASS (t=-3.15)」，但 `k1523_results.json` 實際是 H1 t=-2.87、H2 t=-2.71，逐項 `supported=false`，頂層 `verdict="NULL"`。**README 說 PASS，機器說 NULL**，且兩個數字都剛好被寫成越過 |t|≥3 門檻。疑似 K1520→K1523 worktree salvage 時 README 未同步。提案條目一律以 results.json 為準，並在 content 內明白點出落差。**建議主線程直接修正該 README。**

### 2. artifact 內建 overclaim

**K759**（FSI lead-lag）—— JSON 自己宣稱 `dm_test_significant: true`，依據是 DM t=2.237, p=0.0253。這**過不了本專案現行的 Harvey |t|≥3 發現門檻**。若原封不動收錄，就等於把一個假陽性寫進後續研究會引用的基礎。已標 UNVERIFIED + needs_human，要求依現行標準重新裁決。

**K833**（CBOE IV straddle）—— Sharpe 3.4–3.7，無 baseline 顯著性檢定、無審查紀錄。依 CLAUDE.md「Sharpe 遠高於 baseline 時先懷疑 bug」，標 needs_human 要求人工複查代碼而非採信。

**K841** —— MDD 跨不同曝險直接比較（S1 年化波動 8.6% vs S0 19.7%），未做 exposure-matched 對照，觸及 `mdd_scale_artifact` 規則。

### 3. 本來就不是研究發現（治理紀錄，不應計為新知識）

K1330（SUPERSEDED_BY_K1439）、K1350（provenance 稽核，Codex 明說「不應寫成新發現」）、K1352、K1353（K1344 NULL 的重複任務關閉紀錄，artifact 自己就寫 `knowledge_write: skipped_duplicate_null_receipt`）。

這 4 筆的價值是**告訴 dispatcher 別再派這題**，不是提供實證結論。主線程收錄時應考慮以 `research_methodology` / 非 citable 類別標記，避免被誤引為實證證據。**K1353 尤其要先確認 K1344 是否已有條目，否則會重複計入。**

### 4. 從未執行（scaffold only）

K1268b（缺付費日內 SPY 資料源，results 欄位全 null）、K1291（`status: scaffold_only_not_run`）。收錄價值 = 防止有人再搭一次同樣的 scaffold。

### 5. BLOCKED_ON_DATA（做了可行性稽核，零統計量）

K1438、K1480、K1483、K1486、K1489、K1311。這些是資料 gap 盤點，不是實驗。建議以「data gap 記錄」形式收錄以防重複派工。

### 6. 只跑了 smoke test，正式版從未執行

K1254（RL pilot，README 明說 smoke test「draws NO research verdict」）、K1535（verdict 字面就是 `SMOKE_PENDING_FULL_RUN`）。

### 7. 空白 README（結論只存在於 JSON）

K825、K829、K830、K834、K836、K838、K839、K775、K781、K842、K845、K847 —— README.md 全是「待補充」樣板，結論 100% 從 results.json 反推。數字本身多半扎實，但這些實驗**看起來像未完成**，是它們當初沒進知識庫的可能主因之一。

## 給主線程的 followup

1. 驗證提案 → 寫入 `knowledge.json`（29 筆 needs_human 建議逐筆裁決，其餘 107 筆可批次收）
2. `uv run python scripts/build_knowledge_index.py update`
3. 重跑 `daily_checkup` 確認 `KNOWLEDGE_UNRECORDED` 歸零
4. **修 K1523 的 README**（研究誠實紅線，與數據矛盾）
5. **重新裁決 K759**（artifact 內建的 overclaim）

## 根因觀察（不只補資料，要修流程）

136 筆隱形實驗不是單一疏漏，是三個結構性缺口疊加：

- **實驗完成 → 知識庫寫入沒有機械 gate**。寫 knowledge.json 靠人/agent 記得做，忘了就永久隱形。`KNOWLEDGE_UNRECORDED` 維度是事後偵測，但沒有事前強制。
- **空白 README 沒有被任何關卡擋下**。12 個實驗留著「待補充」樣板就結案了。
- **治理紀錄（dedup closure / 可行性稽核）與實證實驗共用 `experiments/` 目錄結構**，導致 dedup 掃描分不清「這題做過了」與「這題被判定重複」。

補登只解決存量。**存量清完後，若不在實驗收尾流程加一道機械 gate（無 knowledge entry 或 README 未填 → 實驗不得標記完成），這個洞會以同樣速度再長回來。**
