# 論文數字舊帳復現稽核（Provenance Sweep）— 2026-07-10

**起因**：telegram-312 老闆點名「為什麼會有找不到復現程式/資料/結果的狀況？能復現不是最高原則？」+ telegram-321「額度恢復後立刻排程解決」。實際查 quota 仍有 81.6% remaining → 不等 7/12，本輪直接開工。

**任務**：對 `paper/*/` 每個實證數字，抽查能否追溯到活的 `experiments/<id>/results.json` 或論文自帶 JSON；重點掃 2026-05-17 provenance gate 上線前寫入、N-series 知識條目支撐的表格。**禁造假湊舊值**；能重估就重估，不能就標記等 sign-off。

**方法**：逐篇跑 / 讀 `paper/<id>/reproduce_report.json`，統計 matched / untraceable / mismatch，逐一判定每個 mismatch 是「真漂移」「skip-live artifact」還是「extractor 抓不到」。

---

## 稽核總表（7 篇有 reproduce 基建）

| 論文 | report 時間 | total | untraceable | mismatch | gate | 判定 |
|---|---|---|---|---|---|---|
| **garch-x-vix** | 2026-04-20（已重跑刷新） | 13 | 0 | 12→實為 **1 真** | 🔴 red | **1 真 stale**（A4f 4.03 vs JSON 4.148）+ 5 within-tol artifact + 6 null-check |
| **taiwan-vt** | 2026-07-06 | 155 | **23** | 0 | 🟡 pass_with_untraceable | 23 個無 JSON（含 N121 pre-gate γ） |
| **vix-sufficiency** | — | 100 | 2 | 0 | 🟢 green | 2 個 minor untraceable |
| leverage-direction | — | 194 | 0 | 0 | 🟢 green | 23 NOTE = yfinance vintage drift within tol（benign） |
| eav-universal-magnitude | — | — | 0 | 0 | 🟢 green | pass |
| prg-periodic-garch | — | — | 0 | 0 | 🟢 green | pass |
| volatility-absorption | — | 30 | 0 | 0 | 🟢 green | pass |

---

## 🔴 Finding 1（真問題，已處置）— garch-x-vix A4f DM t 數字與宣稱來源不符

- **症狀**：main.tex 全篇用 `A4f vs GJR DM t = 4.03`（摘要、Table 1 main_results、Finding 3「3.81→4.03」、Sec 穩健性 line 525/543），且 **line 723 明確宣稱「$t=4.03$ 來自 `mcs_dm_results.json`」**。
- **但** `mcs_dm_results.json#a4f_pairwise_dm.B0_GJR_vs_A4f_vix2_free_omega.t_stat = 4.148384`（差 2.9% > tol 1%）。
- **性質**：與 telegram-312 的 Paper2 γ 案同類 — 論文引用的數字與其宣稱的 JSON 來源對不上。屬 2026-05-17 gate 上線前的舊帳（report 原始時間 2026-04-20）。
- **處置**：`compute_mcs_dm.py` live 重運算已 enqueue（compute_queue id `compute-garch-x-vix-a4f-...`）。live 值出來後判定：
  - 若 live ≈ 4.148 → main.tex 4.03 為 stale，需全篇 errata 更新並確認 harvey `|t|>3` 敘述不變（4.148 仍 >3，結論方向不變）。
  - 若 live ≈ 4.03 → 是 `mcs_dm_results.json` stored 值 stale，需重寫 JSON。
  - **禁湊值**；errata 清單交主線程 sign-off（followup task_type=paper_review 已排）。
- **5 個 within-tol「mismatch」非問題**：QQQ 3.71 vs 3.7081（0.05%<3%）、GLD-GVZ 3.17 vs 3.173（0.10%<7%）、GLD-dual 3.39 vs 3.3854（0.14%<12%）、0050.TW 1.44 vs 1.4388（0.08%<15%）、VRP ρ 0.80 vs 0.8008（0.11%<5%）—— 全在容差內，只因 `--skip-live` 模式 live_value=null 才被標 mismatch。live 重跑會自動清掉。
- **6 個 null-check**（K1085 GLD+GVZ、K1088 USO+OVX、K1098 0050.TW ×3、four-market count）：paper_value 與 stored 皆 null = check extractor 在 main.tex/JSON 都抓不到 → 需修 check config 或確認這些數字是否仍在現行 main.tex（可能改版後移除）。→ batch 3。

## 🟡 Finding 2（無 JSON 來源，排 followup batch）— taiwan-vt 23 untraceable

主要缺口（`untraceable_summary.dominant_gaps`）：
1. Table 1 summary stats（TWII mean/std/skew/kurt）無 JSON
2. Table 4 VT 策略 Sharpe（BH/EWMA/GARCH/GJR）無 JSON
3. Table 5 common-period 值無專屬 JSON
4. **Table 2 個股 γ（鴻海/聯發科/0056.TW）僅靠 N121 averages** ← N-series，2026-05-17 gate 前
5. Sec 6 macro correlations、Sec 4.5 TSMC VT Sharpe 無 JSON
6. Appendix TZ（c2c Sharpe、TW+JP blend）無 JSON
7. Sec 3 TWD/USD 檢定無 JSON

report 內建 critical 建議：統一所有 0050/TSMC γ 到單一 estimation（現況混 full-sample / rolling / w=2000）；為 Table 1/4/5 建 dedicated experiment JSON。→ batch 2（規模較大，多步，單獨排 task）。

## 🟢 Finding 3（clean）
leverage-direction / eav-universal-magnitude / prg-periodic-garch / volatility-absorption / vix-sufficiency 基本乾淨（vix-sufficiency 2 minor untraceable 併 batch 4）。

---

## 批次計畫（跨論文分批，每批 ≤50min）

- **Batch 1（本輪 2026-07-10 完成）**：garch-x-vix 深度稽核 + live 重運算 enqueue ✅；5 artifact + 6 null 分類釐清 ✅
- **Batch 2**：taiwan-vt 23 untraceable — 建 Table 1/4/5 dedicated JSON + 統一 γ estimation（followup task 已建）
- **Batch 3**：garch-x-vix 6 null-check extractor config 修復 + 確認數字仍在現行 main.tex
- **Batch 4**：vix-sufficiency 2 untraceable + garch-x-vix live 結果 reconcile errata sign-off

**研究誠實聲明**：本稽核未修改任何論文數字或 JSON 值；所有 mismatch 皆分類為「真 stale（待 live 判定）/ within-tol artifact / extractor 缺口」，無湊值。真 stale 項待 live 重運算 + 主線程 sign-off 後才動 manuscript。
