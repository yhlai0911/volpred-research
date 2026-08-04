# 論文指南

## 論文列表
- **第一篇**：`paper/leverage-direction/main.tex`（44 頁，Leverage Direction Matters，目標 JBF）
- **第二篇**：`paper/taiwan-vt/main_v3.tex`（50 頁，`\input{body_v3}`；Taiwan VT + TZ Information Transmission，目標 PBFJ）— 舊 `main.tex`/`body.tex` 單體版已封存 `paper/taiwan-vt/_superseded/`（2026-07-05 版本分岔 reconcile；canonical TSMC γ=0.052/t=3.98 常數均值 K892，非舊 body 的零均值 0.039/0.87）
- **第三篇**：`paper/vt-trend-following/main.tex`（24 頁，Is VT Just Trend Following?，目標待定）
- **第四篇**：`paper/vix-sufficiency/main_v2.tex`（39 頁，Can Anything Beat VIX?，目標 J. Forecasting）
- **第五篇**：`paper/volatility-absorption/main_v2.tex`（Volatility Absorption）
- **第六篇**：`paper/vt-crowding-abm/main.tex`（VT Crowding ABM）
- **第七篇**：`paper/vt-insurance-cost/main.tex`（VT Insurance Cost）
- **第八篇**：`paper/prg-periodic-garch/main.tex`（PRG Periodic GARCH）
- **第九篇**：`paper/garch-x-vix/main.tex`（45 頁，Multiplicative GARCH-X with VIX，目標 J. Empirical Finance 或 J. Forecasting）
- 編譯：`cd paper/<name> && /Library/TeX/texbin/xelatex -interaction=nonstopmode main.tex`（跑兩次解引用）
- 作者：Yi-Hao Lai (Da-Yeh University) + VolPred Research System
- 論文頁 `/paper` 讀 Supabase `papers` table（metadata）；**前端靜態 PDF 目錄由 `config/project_targets.json` 的 `paper_public_dir` 決定**（目前是 `frontend-v2-fix/public/paper/`，由 Zeabur CDN serve）

## Canonical manuscript 宣告（2026-08-04 起，機械唯一來源）

**哪一個 `main*.tex` 是這篇論文，由 `paper/<id>/canonical.json` 宣告，不由任何程式推論。**
唯一 resolver = `volpred.ops.papers.resolve_canonical_manuscript`；PDF 一律由宣告的 tex
同 stem 推導（`main_v3.tex` → `main_v3.pdf`），所以 tex 與 pdf 不可能各指一版。未宣告
或宣告的檔不存在 → fail closed 並印出補救指令，**不退回猜測**。

上面的頁數是 2026-08-04 從各篇 canonical PDF 實測的值，不是歷史記載值。

為什麼要這樣：同一個 class 連三次讓過期的 `main_v*` 產物流到讀者端
（2026-06-11 leverage-direction、2026-07-19 vt-trend-following、2026-08-04
leverage-direction 再犯）。前兩次都只是把「怎麼猜」換一種猜法。細節見
`docs/error_log.md` class M 與 `paper/leverage-direction/_archived/README.md`。

尚未宣告（證據矛盾，需裁定；在裁定前它們會 fail closed 而非被猜）：
`vix-sufficiency`、`volatility-absorption`、`vt-trend-following`、
`eav-universal-magnitude`、`forecast-tail-divergence`。

## 版本命名規則
- `main.tex` / `body.tex` = 原版（不動）
- `main_v2.tex` / `body_v2.tex` = 修正版
- `review_v1.tex` = 審查報告
- `v1_to_v2_diff.tex` = 差異對照

## PDF slug 對照
- leverage-direction → `leverage-direction-matters.pdf`
- taiwan-vt → `taiwan-vt-tz-arbitrage.pdf`
- vt-trend-following → `vt-trend-following.pdf`
- volatility-absorption → `volatility-absorption.pdf`
- vix-sufficiency → `vix-sufficiency.pdf`
- vt-crowding-abm → `vt-crowding-abm.pdf`
- vt-insurance-cost → `vt-insurance-cost.pdf`
- prg-periodic-garch → `prg-periodic-garch.pdf`
- garch-x-vix → `garch-x-vix.pdf`

## Paper Review & Revision Workflow

論文完成或大改版後的正式審查流程：

1. **Codex 整體審查**: `/codex:rescue "Review paper/<name>/main.tex for top-tier journal submission bugs"` → 結構性問題清單
2. **LaTeX 學術審查**: `/latex-academic-reviewer` → 版面、方程式、符號一致性、邏輯流暢
3. **引用驗證**: `/citation-verifier` → DOI、作者名、期刊名、引用格式
4. **根據報告修正** → 重新編譯 PDF → 重複審查直到問題清零
5. **最終 PDF**: `xelatex -interaction=nonstopmode main.tex`（跑兩次解引用）

## 論文更新後同步網頁

每次論文 PDF 更新後必須同步平台：
1. 編譯 PDF: `cd paper/<name> && /Library/TeX/texbin/xelatex -interaction=nonstopmode main.tex`
2. 標準流程：`uv run volpred ops paper-update --paper-id <paper_id>`
3. `paper-update` 會自動更新 metadata、上傳 PDF，並同步到 active frontend 的 configured `paper_public_dir`
4. 只有在前端程式碼或部署環境有變動時才 redeploy；單純 PDF / metadata 更新通常不需 redeploy
