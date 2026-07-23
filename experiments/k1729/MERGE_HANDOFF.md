# K1729 — MERGE HANDOFF（給主線程；本 agent 不得跨的那一步）

**狀態**：修復完成、雙審 PASS、所有 gate 綠燈。**merge 只卡在一件事**：
`storage/memory/knowledge.json` 還沒有 k1729 的條目。

依 CLAUDE.md 與本任務 brief，**knowledge.json 只能由主線程寫（K1259，agent 禁寫）**，
所以本 agent 停在這裡，不自行寫入、也不用 exclusions 繞過。

## 已完成並驗證

| 檢查 | 結果 |
|---|---|
| `experiment_gates.py run --path experiments/k1729` | **PASS**（4 gates） |
| `experiment_gates.py certify`（merge-time） | **PASS**（sha 綁定現行 bytes） |
| `scripts/tests/test_nested_dm_misuse_ratchet.py` | **103 passed** |
| `test_experiment_gates.py` + `test_experiment_certification.py` | **38 passed** |
| reproduce_spec + 分析切片快照 | 已補（artifact gate 這項已清） |
| 重跑一致性 | 除 timestamp / 整檔 sha / 執行時列數（皆已列入 ignore_pointers）外**位元相同** |

## 審查（⚠️ fallback path，非 primary Codex）

Codex CLI 於 2026-07-21 14:33 回 usage limit（`try again at Jul 25th, 2026`），
依 `.claude/rules/experiments.md` 改走 fallback，**兩路獨立審查皆 PASS**：

1. fresh-context adversarial code-reviewer subagent（Claude Opus 4.8）
   → `experiments/k1729/independent_review_rev2.md`
   （手算結算日曆對照原始 CSV，並用 2 個 control 非模糊結算日反證未挑樣本）
2. agy / Antigravity（Gemini）→ `experiments/k1729/agy_review_rev2.md`
   （獨立重寫兩條事前慣例 + 第三條對照慣例；另對最終位元做確認 pass）

**依同規則 fallback PASS ≠ primary-path Codex PASS** —— Codex 額度恢復後
（>= 2026-07-25）須對這份 bytes 二次驗證才算 closure。
**寫 knowledge.json 時 `reviewer_source` 必須註明 fallback。**

## 主線程要做的（唯一剩餘步驟）

```bash
# 1. 數字一律 programmatic 取得，不要從 README 重打
uv run python -c "import json,pathlib; print(json.dumps(json.loads(pathlib.Path('experiments/k1729/k1729_results.json').read_text()), indent=2, ensure_ascii=False))"

# 2. 經 memory writer 寫入（會蓋 provenance 章）；verdict=PASS 需帶 experiment_id + reviewer 欄位

# 3. 然後 merge（務必先 cd 回主 repo，不可從 worktree 內觸發）
cd /Users/yhlai0911/volpred-research
bash scripts/merge_worktree.sh dispatch-slot-1-30aeb902-taifexrv
```

## 寫 knowledge 時該記什麼（數字由本檔程式化產出，可直接核對 results.json）

- **verdict**：`HAR_RV5_WINS_ROBUST_ACROSS_PROXIES`
  （已強化：需 full 與 ex-ante ledger 在兩個 target 都同判才給 `_ROBUST_ACROSS_PROXIES`）
- **主表**：target A `n=2548, improv=14.70%, DM t=-3.681, HAR_RV5_WINS`；target B `n=2536, improv=3.37%, DM t=-3.367, HAR_RV5_WINS`
- **ex-ante 選約 ledger（乾淨的那條）**：
  target A `n=2543, improv=14.70%, DM t=-3.671, HAR_RV5_WINS`；
  target B `n=2531, improv=3.39%, DM t=-3.370, HAR_RV5_WINS`
- **剔除全部換月日**：target A `n=2421, improv=14.66%, DM t=-3.584, HAR_RV5_WINS`；
  target B `n=2410, improv=3.48%, DM t=-3.665, HAR_RV5_WINS`
- **關閉 insanity filter**：target A `n=2541, improv=15.19%, DM t=-3.867, HAR_RV5_WINS`；
  target B `n=2524, improv=3.48%, DM t=-3.456, HAR_RV5_WINS`
- **選約事前可決定率**：2545/2550
  （99.80%），模糊集 5 天：
  2016-03-16, 2016-05-18, 2016-08-17, 2017-01-18, 2017-02-15
- **資料**：`data/intraday/taifex_5min_rv.csv` as-of `2026-07-16`；
  復現對照 `analysis_slice_sha256` = `2acdc69aa2103f4a...`

## 結論的射程（寫 knowledge 時不要放寬）

**撐得起**：08:45 開盤前預測當日日盤 RV 這個設定下，5 分鐘 RV 的 HAR 顯著優於
日頻報酬平方的同構 HAR，跨雙 proxy 且跨三條敏感度 ledger 穩健。

**撐不起**：「這條資料線值得維護」。那是成本效益判斷，需要維護成本、替代方案成本、
增益的經濟價值三個量 —— 本實驗一個都沒測。rev1 這樣寫被判 FAIL，已收回，**不要寫回去**。

**已揭露的殘餘限制**：ex-ante ledger 是條件式 estimand（篩選條件在 08:45 未知），
但篩選與模型無關、兩模型共用同一組日子，故不偏袒任一方。
