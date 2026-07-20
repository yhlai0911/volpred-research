# K741/K904 NFP canonical branch: multiplicity disclosure + Codex certification (unblock merge)

**Model**: claude-opus-4-8 / xhigh (per model_router)
**Parent task**: assign_1238781f (收件 followup)
**Worktree (你的 cwd)**: `.claude/worktrees/dispatch-slot-1-5741c175-k741`，branch `k741-nfp-canonical`，tip `a713e41ce`（**未合併 main**）

## 背景（主線程已核實，勿重做）

slot-3 的重複派工已自行 revert，其獨立複製結論與本 branch **逐格一致**。主線程於 2026-07-20 12:0x
直接比對 `experiments/k741/k741_nfp_event_study_canonical_results.json` 與 slot-3 摘要，確認：

| 項目 | canonical JSON | slot-3 獨立複製 | 一致 |
|---|---|---|---|
| n_nfp / n_non_nfp | 194 / 3890 | 194 / 3890 | ✓ |
| ratio_vs_all | 1.16307 | 1.1631 | ✓ |
| p_vs_all (Student) | 0.05056 | 0.0506 | ✓ |
| p_vs_friday (Student) | 0.03432 | 0.0343 | ✓ |
| Low/Med/Elev/High ratio | 1.305 / 1.230 / 1.186 / 0.936 | 1.31 / 1.23 / 1.19 / 0.94 | ✓ |
| wilcoxon_p_vs_all | 0.000639 | 0.00064 | ✓ |

`main_v3.tex` 的 tab:nfp 與內文也已與 canonical JSON 逐位對齊（p=0.051 / 0.034，四個 regime
0.009 / 0.027 / 0.253 / 0.731，n=63/76/27/28），敘事已誠實降級（bootstrap 區間含 0、不宣稱 regime contrast）。
**這些不需要你再驗一次。** sign_flipped = false。

## 你要做的事（依序，順序不可換）

### 1. Student vs Welch：明確選定並揭露
`k741_nfp_event_study*.py` 目前呼叫 `stats.ttest_ind` 的 `equal_var=True` 預設（Student's）。
主線程確認 branch 已刪掉 main_v3.tex 裡「Welch's t-test」的錯誤標籤，但**兩者跨 5% 邊界**：
overall p 在 Student 下 0.0506、Welch 下 0.0394。這是 referee 必問的點。

- 選定一個並在論文明說是哪一個（建議：n=194 vs 3890、離散度不等 → **Welch 更正確**；但這會把
  overall 從「marginal at 10%」變成「clears 5%」，敘事要跟著改，不可只改數字）。
- 無論選哪個，**table note 要揭露另一個變體的 overall p 值**（0.051 / 0.039）。
- 程式碼要顯式寫出 `equal_var=`，不可靠預設。

### 2. 多重比較揭露（uncovered gap，submission blocker）
tab:nfp 報四個 regime 檢定，全篇 **零** Holm/Bonferroni/multiplicity 字樣。修正後敘事比修正前
更依賴 regime-level 顯著性（Low 從 0.069 → 0.009），referee 幾乎必問。

- 在 tab:nfp 的 tablenotes 加一句：四個 regime 檢定未做多重比較校正，並報 Holm 校正後結果。
- **Holm 結果依 §1 的選擇而異**（Student：Low 存活，adj p≈0.036；Welch：無一存活，最小 adj p≈0.104）。
  照你在 §1 的選擇如實報，**不得挑對自己有利的那個**。
- 若 Welch 下無一存活 → §4.x 內文對 regime 顯著性的措辭要同步降級。

### 3. 重跑驗證
- `paper/volatility-absorption/reproduce.py` gate（branch 先前 123/123）
- xelatex 編譯（先前 rc=0, 43 頁）
- `pytest`（先前 81 passed，含 test_nfp_official_release_dates / test_event_dates / test_cpi_t0_official_release_dates）
三者任一 fail → 修到 green 才進 §4。

### 4. Codex 審查認證（**這一步是 merge 的唯一 blocker**）
`scripts/merge_worktree.sh` 已對本 worktree ABORT，原因：`experiments/k741` 與 `experiments/k904`
都沒有 `review_verdict.json`。認證的 sha256 綁定「審查當下的位元組」，所以**必須在 §1-3 全部改完
之後才做**，否則你一改檔案 hash 就對不上、gate 會再擋。

對 k741 與 k904 各做一次：
```bash
uv run python scripts/experiment_gates.py verdict-template --path experiments/k741 --out experiments/k741/review_verdict.json
```
然後讓 **Codex**（`codex exec`）讀 frozen 的實驗內容並填寫裁決。禁止你自己代筆或轉述裁決；
`reviewed_sha256` 必須列出 claim surface 每個檔（*.py、README.md、*_results.json、reader-facing 圖）
在審查當下的 sha256。Codex 給 FAIL → **不要**硬填 PASS，如實記錄並在 result artifact 標明。

Codex 審查重點請明確交代給它：
- canonical 曆 vs first-Friday proxy 的 2×2 factorial 拆解是否站得住
- window leak（2009-12 殘留）與 backward holiday match（nd-1 → 事件被記到印出前一個 session）是否真的修乾淨
- §1 的 Student/Welch 選擇與 §2 的 Holm 揭露是否誠實、有無挑選有利結果
- 結論是否與 JSON 逐位一致

### 5. Commit（在 worktree 內，branch k741-nfp-canonical）
commit message 要寫清楚改了什麼、為什麼。**不要自己 merge 回 main** — merge 由收件的 fire 走
正式 `scripts/merge_worktree.sh` 做。

## Result artifact（必寫）

`experiments/k741/k741_cert_merge_summary.json`，至少含：

```json
{
  "test_variant_chosen": "welch|student",
  "test_variant_rationale": "...",
  "overall_p_student": 0.0506, "overall_p_welch": 0.0394,
  "holm_adjusted": {"Low": ..., "Medium": ..., "Elevated": ..., "High": ...},
  "holm_survivors": ["..."],
  "narrative_downgraded": true/false,
  "reproduce_gate": "N/N", "xelatex_rc": 0, "pytest": "N passed",
  "codex_verdict_k741": "PASS|FAIL", "codex_verdict_k904": "PASS|FAIL",
  "verdict_files": ["experiments/k741/review_verdict.json", "experiments/k904/review_verdict.json"],
  "commits": ["..."],
  "merge_blockers_remaining": []
}
```

## 誠實紀律

研究誠實 > 一切。禁止假數字、禁止代筆 Codex 裁決、禁止為了讓 merge 過而挑有利的檢定。
若 Welch + Holm 的結論是「regime-level 顯著性撐不住」，那就如實寫進論文並降級敘事 —— 那才是正確產出。
