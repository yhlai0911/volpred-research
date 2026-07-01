# _archived — leverage-direction 舊 revision lines

**封存時間**: 2026-07-01 台灣時間 10:15（hourly-10 dispatch, task `email-12380-abb6a4` 老闆 email 授權「立刻用 Codex 對比裁定 canonical」）

## Canonical 裁定

**Canonical manuscript**: `paper/leverage-direction/main.tex` + `body.tex` + `tables_main.tex` + `tables_supplement.tex` + `supplementary.tex` + `supplementary_content.tex`

這是 Stage 1.2/1.3/1.4 single-contribution revision 主線，也是 `paper/leverage-direction/reproduce.py` v12 current layout 認定的 canonical。

## 為何封存這些檔

`main_v3.tex + body_v3.tex` 與 `main_v2.tex + body_v2.tex` 是舊 revision branches：

- **v3 line**（`main_v3.tex` 680 行）：Stage 1.2 之前的舊主文，含 two-contribution framing 與更多旁支材料（VaR compliance、market timing、HAR paradox、time-zone、commodity extension）— 這些已在 Stage 1.2 (34610e4fd) 收斂為 single-contribution + Stage 1.3 (200d40a94) 把旁支 offload 到 `supplementary.tex` / `supplementary_content.tex`。
- **v2 line**（`main_v2.tex` + `body_v2.tex`）：更舊的 v1→v2 diff 產物（4 月）。
- **`tables.tex` + `table_nulls.tex`**：v3/v2 line 的 `\input` 依賴（main_v3.tex L57/L60）。canonical 使用 `tables_main.tex`。

## Codex verdict（2026-07-01 codex exec）

> canonical = `main.tex + body.tex`
> v3_obsolete = true
> v3_unique_content_still_needed = []
> recommendation: v3 有些旁支 prose 已在 Stage 1.2-1.4 刻意 drop / demote，無需 manual merge 即可封存。

原始 verdict 存於 dispatch commit message + task_pool_claim.py complete 的 result field。

## 歷史紀錄（不改）

以下 markdown 檔仍有 `body_v3.tex` / `main_v3.tex` 提及，但**是歷史事件描述**（K1256 3-spec disambig / K1198 errata 等 April 2026 fix），保留原文不改：
- `paper/leverage-direction/README.md` L47, L55
- `paper/leverage-direction/errata_pending.md` L21
- `paper/leverage-direction/reframing_decision_20260701.md` L22
- `paper/leverage-direction/review_history/*` 全套 review artifacts 保留原路徑引用

## 恢復方式

若日後需回滾（極少數場景）：
```bash
cd paper/leverage-direction
git mv _archived/*.tex .
```

或直接 `git log` 找封存 commit 反向。

## paper-update code 邏輯

`src/volpred/ops/papers.py`:
- Line 251/253 用固定 candidates list `[paper_dir / "main_vN.tex", ...]`：v3/v2 檔 moved to `_archived/` 後不再存在，`paper_dir / "main_v3.tex"` 自動不匹配。
- Line 500 `sorted(paper_root.iterdir())` + Line 504 `startswith("_")` filter：`_archived/` 目錄自動被 skip（不會被當成新 paper）。
- Line 508 `paper_dir.glob("*.tex")` non-recursive：`_archived/*.tex` 不會被 mtime pick 抓到。

**結論**：封存 v3/v2 到 `_archived/` 子目錄後，code 完全不需要改；mtime-based canonical pick 也不會誤選。
