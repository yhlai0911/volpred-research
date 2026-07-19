# k528 NFP 官方日曆修正 — Codex 二審 + review_verdict.json

**Model**: claude-opus-4-8 / xhigh (per model_router)
**父任務**: `assign_ae004ae2`（P1）
**前一段 job**: `agent-brief_k528_nfp-e245d0`（修正本身，已完成）
**工作目錄**（git worktree, branch `k528-nfp-official-dates`）：
`/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp`

## 為什麼有這個 job

k528 NFP 事件研究原本用「每月第一個週五」proxy 當 NFP 公布日，實測約 20% 是錯的。
修正已完成：改用 BLS 官方發布日曆（ALFRED / FRED release id 50，fail-closed 無 fallback），
全樣本重跑，並產出線上文章 `mile_35eef830` 的 18 條更正替換清單（**尚未套用**）。

`merge_worktree.sh` 的 review-certification gate 擋住合併，理由正確：
「An experiment may only enter main carrying a review verdict that is bound to the bytes it reviewed.」
本 job 的**唯一產出**就是那份裁決檔。

## 主線程已完成的驗證（不必重做，但可挑戰）

- `uv run pytest tests/test_nfp_official_release_dates.py -q` → **42 passed**
  （含 `TestK528UsesOfficialCalendar` 與 `TestProxyMutationIsCaught`，後者實測 proxy 日曆餵給 guard 會被拒、
  幻影日 2025-10-03 也被抓；9 passed）
- 18 條替換字串的每個數字都能在 `k528_nfp_event_study_results.json` 找到來源，已逐個核對：
  1.08 / 0.828% / 0.764% / 1.15 / p=0.057 / 2.04 / 1.11% / 0.54% / 0.44 / 0.34 / 16.69 / 0.042 / 253 / 127 / 126
- 線上文章 `mile_35eef830` 未被更正過、無第二篇更正文，18 條替換各恰好命中 1 次
- `get_first_friday` 在 k528 內只剩 docstring 提及（k661 仍在用，但已由 pending task `assign_23b2a961` 覆蓋，不屬本 job 範圍）

## 你要做的事

用 `codex exec`（GPT-5.x）對**凍結的** experiment bytes 做獨立二審。**review-only，不要改任何被審的檔案**。

需審範圍（相對工作目錄）：
- `experiments/k528/k528_nfp_event_study.py`（主腳本，含 before/after audit 段）
- `experiments/k528/k528_nfp_official_dates_results.json`（前後對照 + 替換清單）
- `experiments/k528/build_article_correction.py`（文章更正計畫，dry-run/`--apply`）
- `experiments/k528/README.md`
- `tests/test_nfp_official_release_dates.py`
- `src/volpred/data/event_dates.py`
- `git diff e9c9efedd..af2fad356`

逐項給 PASS/FAIL：

1. **日期來源真的 fail-closed** — 取不到官方日曆必須 raise，不得靜默回退 proxy；
   `get_first_friday()` 是否真的整條移除（k528 範圍內）。
2. **audit 段的 proxy 重建是否誠實** — README 宣稱 proxy 側 median/win_rate 是從 archive 逐事件資料重建、
   且先驗證重建平均能重現 archive 平均。確認程式碼真的這樣做、對不上會 **raise 而非 warn 後繼續**。
3. **統計判定是否成立** — `vol_ratio_vs_friday` 由 p=0.0335 → p=0.0571 判 CONCLUSION_FLIPPED 合理；
   但 `regime_ratio` 也被標 CONCLUSION_FLIPPED（仍極顯著 p=8e-9，只是中位數移動 10.7%）——
   **這個 verdict 標籤是否誤導？** 同時檢查 Welch t / Mann-Whitney / regime 分組實作
   （127 vs 126 切點處理、單雙尾、相關係數 p 值）。
4. **文章更正清單的正確性** — 18 條 to-字串裡每個數字是否都有結果檔來源且四捨五入一致，有無憑空數字。
5. **隱藏的 lookahead / 樣本選擇問題** — VIX 中位數切點用**全樣本**中位數（in-sample），
   卻用於「事前可判斷」的敘事；更正後的文章文字是否誤述這一點。
6. 其他任何 blocking issue。

## 產出（唯一 artifact）

```bash
uv run python scripts/experiment_gates.py verdict-template \
  --path experiments/k528 --out experiments/k528/review_verdict.json
```

**先產骨架，不要手抄**。再讓 Codex 讀凍結的 bytes 後填入：
`kid` / `verdict`(PASS|FAIL) / `reviewer` / `reviewed_at` / `review_artifact` / `reviewed_sha256`。
claim surface 的每個檔（`*.py`、`README.md`、`*_results.json`、reader-facing 圖）都要列 sha256（**審查當下**的）。
Codex 的完整審查全文另存 `experiments/k528/codex_review_official_dates.md` 並由 `review_artifact` 指向它。

**verdict 由 Codex 決定，不是由你決定。** 判 FAIL 就照實寫 FAIL 並列出 blocking issues —
FAIL 的裁決同樣是合法且必要的產出（K1709 就是被判 FAIL 卻仍 merge，害 CI 連紅 4 次）。
判 FAIL 時**不要**自行修 code 再重審；留給 followup 決定怎麼處理。
