# 論文優化 Sprint Handoff（2026-07-13，compact 前寫）

**用途**：compact + 切 Fable 後讀此檔無縫接續。任務 = 完成 13 篇論文深審 P0（`docs/paper_execution_master.md` 為總入口，各篇 `paper/<name>/EXECUTION.md` 為單篇規格）。

## 已完成並 commit（可 git log 驗證，勿重做）
- vt-insurance-cost：P1 citation 全清理 + Figure 1 + bootstrap CI + gate 9/9 strict green（478d4006e 等；P0=DONE，只剩 FRL 格式 gate + 投稿時序）
- vt-trend-following：Table 5 嵌合體全表 rebind K1695 canonical + 6 處 prose + fig2 重生（4360ecfaa）
- leverage-direction：P0 四項全落地（K1592 prespec 小節+表、K1591 雙軌、K1256 HM rebind、26/14-asset 裁掉）（46f1766c3）
- taiwan-vt：TWII γ 0.272→canonical 0.105/5.31 全文替換 + 跨國敘事反轉 + rolling rebind（6562076b6，owner sign-off 已取得）
- vt-crowding-abm：P0-2+P0-3 誠實補報（K1471 gate 真相表、RR_TF 惡化補報、footprint-scale scope、family ordering 撤回、abstract 洩漏修）（5ff463529）。剩 P0-4（reproduce.py K1471 擴充）+ P0-5（機械修正批次，清單在 EXECUTION.md）
- volatility-absorption：K1686 gating = ABSORPTION NOT SUPPORTED → 裁定重框 FRL 方法論短文（9b1260cfa，pipeline 已更新）；body 重寫待做
- forecast-tail-divergence：K1698 gating = H2_REJECTED → 裁定 FRL/JoF 短文（5ff463529，pipeline 已更新）；短文 outline 待做

## 下一個主線程重寫任務：prg-periodic-garch P0（最需要 Fable 高智能）
canonical tex = `paper/prg-periodic-garch/main.tex`（637 行，單體，非 \input）。完整規格見 `paper/prg-periodic-garch/EXECUTION.md` P0 段。

### P0-1（gate blocker）：K880 SPY 數字 errata
- 已找到 canonical：SPY overnight-known DM = **5.064**（`experiments/k880/k880_results.json` .cross_market_comparison.spy_k880.DM_t_PRGExt_vs_GJR）；舊稿值 t=6.00
- **NOT FOUND（需先考古）**：SPY VaR 1% breach canonical（深審說 1.32%/p=0.195）與 MCS canonical（PRG-only survives）的 source JSON + jq path 尚未定位。k880_results.json 無此欄位，需掃 k880v2/k880b/k1544。
- **接續第一步**：派 Opus subagent（prg-recon）只讀考古，產 `paper/prg-periodic-garch/review_history/fable_deep_review_20260711/P0-1_errata_map.md`（逐行對照：main.tex 行號/現值/canonical/source jq path + reproduce.py assertion + snapshot 檢查）。主線程據表機械改。

### P0-2（敘事核心）：K1544 雙時點框架重寫
- 證據已齊：close-time strict PRG 對 GJR **無優勢**（K1699 六市場 0/6 Harvey：SPY +0.74/QQQ +2.28/GLD −0.44/EEM −0.54/0050 −0.32/TAIFEX −0.49）；open-time coherent PRG **六市場全勝** fair GJR-X（K1544：4/6 過 3.0，SPY 2.12/QQQ 2.97 marginal）
- 重寫：§5.1 兩 convention 分報 + timing flip 升 headline + canonical +5 DM 標 timing artifact + abstract/intro/conclusion 對齊 + 三實驗（K1544/K880/K1699）information-set 表
- K1699 完整結果在 `experiments/k1699/`（README + per_market_table.md + results.json）

### P0-3：K1544 編號碰撞治理 — 已由 8b6f3170c 部分完成（term-spread→K1696，PRG 保留 K1544）

## 剩餘 Tier 3（prg 後）
- garch-x-vix：解凍 + Table 3 canonical 重生（K1685 garchx OOS = GO 已完成）+ r1_response_queue 落地。EXECUTION.md 有規格
- vix-sufficiency：DM 全篇 HAC 重算（K1655 class）+ K732/K736 落地
- eav-universal-magnitude：magnitude ordering 降級 sign universality
- btc-gas-negative：markdown→LaTeX + reproduce 建置 + 標題絕對化改
- crypto-fear-channel：K1025_v3 已 succeeded；body generalized FEVD 重建 + headline 重寫（Codex 語義複核前禁 ready 標記）

## 環境注意
- 論文 .tex 重寫一律主線程（CLAUDE.md）；考古/機械/實驗派 Opus subagent（省 Fable）
- 非 ASCII commit message 走 `git commit -F <檔>`
- 工作區當前乾淨，HEAD = 5ff463529
- 背景有 hourly-dispatch + worktree agent 在跑，不碰 experiments/ 以外它們的檔

## 接續提示詞（compact 後貼）
讀 `storage/ops/paper_sprint_handoff.md`。繼續論文 P0 sprint：先派一個 Opus subagent 做 prg-recon 考古（產 P0-1_errata_map.md，定位 SPY VaR/MCS canonical source），同時主線程（Fable）開始讀 prg main.tex §5 準備 P0-2 雙時點重寫。prg 完成後依 handoff「剩餘 Tier 3」順序繼續。每篇完成後更新 EXECUTION.md 進度日誌 + commit。
