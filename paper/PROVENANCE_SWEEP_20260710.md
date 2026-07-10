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
- **Batch 2**：taiwan-vt 23 untraceable — 建 Table 1/4/5 dedicated JSON + 統一 γ estimation
  - **2a Table 1 summary stats（2026-07-10 04:xx hourly 完成 ⚠️ NOT_REPRODUCIBLE）**：`experiments/paper2_table1_summary_stats_provenance/`。從 pinned 快照重現 TWII/0050/SPY/TSMC 的 mean/std/skew/kurt → **僅 matched 3/16**。核心：(1) 只有 mean 部分對上，skew/kurt 系統性不符（0050+TSMC skew 翻號）；(2) **發現資料 bug — `data/0050_..._2008-2026.csv` 的 `0050_tw_adj_close` 欄損毀**（2013-12-31→2014-01-02 split-adj 斷點 −138.9%，剔後 kurt 仍 17.8）；(3) TSMC mean 0.051 無法重現（子期間 0.092-0.119，暗示用 pre-2008 較長期間）。→ **escalate owner sign-off**（取回原始 vintage OR 乾淨資料重估發 errata），未改任何論文數字。knowledge item d0c521d8，reviewer=code-reviewer subagent（Codex 額度用盡至 7/11）。
  - **2b 剩餘子項（2026-07-10 05:xx Codex 完成，部分可追溯 + 明確 sign-off 清單）**：`experiments/paper2_taiwan_vt_provenance_batch2b/` 建 dedicated governance artefact，讀現有 K1175/K1176/K1180/K1182/K892/K896/K900/K515/K516 與 `paper2_sec45_*` / `paper2_sec3_twd_usd_test` / `paper2_taiwan_indiv_rolling_gamma` JSON，逐項對 `body_v3.tex` 現行數字分類。結果：Table 3/5 VT、Table 4 TZ 多數現行數字已可由 dedicated JSON 追溯；VIX Granger F=58.8、TSMC VT Sharpe/52.5% variance share、BCI null/OOS Sharpe 可追溯。仍需 sign-off / 新實驗：TWII γ 0.272/3.18、legacy 個股 rolling γ rows、TWD/USD p=0.08（重跑約 0.87）、Appendix TZ -8.91bp 與 CI [0.65,2.24]、import-growth G12 values（knowledge-only）、ex-TSMC Sharpe range、skewed-t eta/lambda。**未修改任何論文數字**；所有 manuscript rewrite 仍需主線程 paper revision + owner sign-off。
- **Batch 3（2026-07-10 05:xx hourly 完成 ✅）**：garch-x-vix 6 null-check「extractor 缺口」實為**誤判** — 原 audit 用錯 jq 欄位名（`paper_value`/`stored_source_value` 在 K1085/K1088/K1098/four-market 這組 entry 不存在，它們用 `expected_value`）→ 誤讀成兩側皆 null。真 root cause = **`reproduce.py` 在 `--skip-live` 模式把 live-dependent check 標 `mismatch`（應 `skipped`）**，導致 match_rate 7.7% false-RED。修法（統一 root cause，非逐 check patch）：(1) `compare_three_way` 在無 live 時 fall back 到 paper↔stored provenance 判定（skip-live 的本義）；(2) `compare_expected_vs_live`（純 live-only check）標 `status="skipped"` 排除出 match_rate；(3) 條件用 `not live_mode` 而非 `skip_live`，一併修好 default 模式讀空 cache 的同 bug（code-reviewer subagent 抓到的 collateral finding）。結果：skip-live 與 default 皆 **85.7% yellow**，6 skipped、唯一 divergence = A4f（4.03 vs 4.148，已在 Finding 1 escalate 的 errata，非本 batch scope）。**未修改任何論文數字或 JSON 值**；Codex 兩次超時 → code-reviewer subagent review PASS（無 masking real mismatch）。
- **Batch 4a（2026-07-10 12:xx hourly 完成 ✅ reconcile，NO body edit）**：garch-x-vix A4f errata reconcile。
  - **確認**：`main.tex` A4f DM t=4.03（14 處）+ Finding 3 A4 constr.=3.81 皆為 K997/K1085 起稿凍結 yfinance 值；canonical `mcs_dm_results.json#B0_GJR_vs_A4f=4.148`（A4 constr.=3.841）；差 +2.9% 為**已記載的 yfinance 回溯調整 drift**（非抄錯），Harvey |t|>3 質性不變。
  - **reproduce gate 85.7% yellow 是誠實訊號**：`reproduce.py` `expected=4.030379`（忠實代表 main.tex）vs live 4.148 的 divergence，正是 gate 正確標示 `errata_pending.md` 已揭露的 drift；**不可**靠改 submitted 論文數字或改 `expected` 硬轉 green（本輪一度誤改 main.tex 4.03→4.15 + reproduce.py expected→4.148 使 report 100% green，發現違反 submitted-paper 政策後**全數回退、零淨變更**，見 error_log 2026-07-10）。
  - **決策**：遵守 `errata_pending.md` + README 明文「No paper body edit required pre-reviewer-response」；SF1/K1378 caveat（A4f 優勢在 2019-2026 r² proxy 不顯著）使 DM t framing 待 R1 決定 → **不動 body**。是否提前套用 errata 到公開版 = submitted-paper policy 決策，**escalate owner sign-off（email 已送）**。
- **Batch 4b（未做）**：vix-sufficiency 2 untraceable — 排下一輪。

**研究誠實聲明**：本稽核未修改任何論文數字或 JSON 值；所有 mismatch 皆分類為「真 stale（待 live 判定）/ within-tol artifact / extractor 缺口」，無湊值。真 stale 項待 live 重運算 + 主線程 sign-off 後才動 manuscript。
