# 論文指南

## 論文列表
- **第一篇**：`paper/leverage-direction/main.tex`（60 頁，Leverage Direction Matters，目標 JBF）
- **第二篇**：`paper/taiwan-vt/main.tex`（34 頁，Taiwan VT + TZ Information Transmission，目標 PBFJ）
- **第三篇**：`paper/vt-trend-following/main.tex`（24 頁，Is VT Just Trend Following?，目標待定）
- **第四篇**：`paper/vix-sufficiency/main_v2.tex`（39 頁，Can Anything Beat VIX?，目標 J. Forecasting）
- **第五篇**：`paper/volatility-absorption/main_v2.tex`（Volatility Absorption）
- **第六篇**：`paper/vt-crowding-abm/main.tex`（VT Crowding ABM）
- **第七篇**：`paper/vt-insurance-cost/main.tex`（VT Insurance Cost）
- **第八篇**：`paper/prg-periodic-garch/main.tex`（PRG Periodic GARCH）
- **第九篇**：`paper/garch-x-vix/main.tex`（31 頁，Multiplicative GARCH-X with VIX，目標 J. Empirical Finance 或 J. Forecasting）
- 編譯：`cd paper/<name> && /Library/TeX/texbin/xelatex -interaction=nonstopmode main.tex`（跑兩次解引用）
- 作者：Yi-Hao Lai (Da-Yeh University) + VolPred Research System
- 論文頁 `/paper` 讀 Supabase `papers` table（metadata）；**PDF 放前端 `frontend-v2-fix/public/paper/`**（由 Zeabur CDN serve，不走 Supabase Storage）

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
