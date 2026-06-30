---
name: Paper Portfolio Tier Decisions (2026-04-27 user-authorized autonomous)
description: 用戶 2026-04-27 授權主線程自主決定所有 paper 優化路徑；按 NotebookLM 評估 + 獨立 Opus 判斷分 A/B/C/D tier；2026-04-27 evening: P6 已升 ready_for_submission, P9 已 submitted under review
type: project
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---
# Paper Portfolio Tier Decisions (2026-04-27)

用戶 2026-04-27 明示「所有學術論文的優化全部由你決定」。撤銷之前的「不擅自啟動 paper rewrite」保守姿態。

**Why（背景）**：用戶 2026-04-27 提供 NotebookLM + 獨立 Opus 評估，揭露 9 篇 paper 中至少 P5/P8/P9 有 reviewer 一定打的方法論問題（ABM 臨界點是設計出來的、NSI 套套邏輯、VoV 過度配適 2020 COVID）。我之前 v2 review 給 P5 4.4★ + 預測 FRL 85-90% accept 是 single-paper agent 視角的盲點，必須降到 3.5-3.8★ + 40-50%。

**How to apply**：未來 session 看到 paper status 不再以 reproduce gate GREEN 為投稿 ready 信號；改用本 tier 分類為 source of truth。**讀本 memory 前必先 cross-check `research_program.md` Paper Portfolio Status 表（最新狀態 source of truth）— memory 是 snapshot，可能 stale；尤其 paper status 變動（promote/submit/withdrawal）的最新 fact 看 research_program**。

## ⚠️ Reality check (2026-04-27 evening update)

**當前實際分布**（與 memory 創建時 morning snapshot 已不同）：
- 1 篇 **submitted under review** (P9 garch-x-vix, R1 pending since ~2026-04-19, errata_pending.md shelf-ready)
- 1 篇 **ready_for_submission** (P6 prg-periodic-garch, 2026-04-27 evening 升 stage; supabase status 同步; SUBMISSION_READY.md + send-alert df592119 已發 user 等 confirm 投稿; 6/6 gate PASS + reproduce 22/22 100% green)
- 7 篇 **working**（P1/P2/P3/P4ins/P5/P7/P8/P10）

修正錯誤判斷標準（仍適用）：
- ❌ reproduce gate GREEN ≠ submit-ready（只是 numerical reproducibility 下限）
- ❌ single-paper latex agent 4★ ≠ submit-ready（agent 視角窄，看不到 fairness / cross-paper / 設計性問題）
- ❌ Alert 4d05236b（2026-04-26 寄出的「4 papers READY 等 confirm 投稿」）框架錯誤 — 那 4 篇都還在 working

**正確投稿 gate**：須同時滿足
1. latex ≥ 4★（含 cross-paper meta-eval）
2. citation 0 MAJOR + ≤3 MED
3. cross-paper meta-eval verdict = "no fundamental issue"
4. NotebookLM-style 獨立 reviewer 評估接受率 ≥ 50%
5. 無 critical fairness issue（如 P6 PRG 讀 2 次 vs GJR 1 次）
6. 無方法論套套邏輯（如 P5 ABM 設計性、P8 NSI 套套）

**P6 是首篇通過 6-criteria gate** 的 case study（v1→v2→v3→v4→v4.1 五輪迭代 + K1260 fair-info GJR-X benchmark + reproduce 22 checks 100% match）。其他 working papers 沿此 pattern。

## Tier 分類（A/B/C/D）— priority sorting

### Tier A — 距離 submit-ready 最近

| Paper | 當前狀態 | 下一步 |
|---|---|---|
| **P9 GARCH-X with VIX** | ✅ submitted under review (R1 pending) | **wait R1 reviewer response**；errata_pending.md shelf-ready (1 SPY +2.9% drift, 4 metrics <0.15% noise)；R1 收到後 prep response document |
| **P6 PRG (prg-periodic-garch)** | ✅ ready_for_submission (2026-04-27) | 等用戶 confirm 投稿 FRL → status `submitted`；或維持 ready + 每月 continuous review loop（per paper-stage-classifier skill）|

**Tier A 行動已 exhausted** — 兩篇都到等待狀態（P9 等 reviewer / P6 等用戶 confirm）。

### Tier B — 需 fundamental refactor 才考慮投

| Paper | 主要問題 | 必修方向 |
|---|---|---|
| **P5 vt-crowding-abm** | ABM 70% 崩盤閾值是 λ/γ 參數的數學結果，不是 emergent finding | rewrite 框架：從「發現臨界點」改為「參數敏感度分析 + crowding cost magnitude bounding」；補「非 VT 策略也有的 crowding」對照組 |
| **P4ins True Cost of VT** | 新穎性低（Moreira-Muir 已隱含此機制） | 考慮與 P7/P8 合并為更完整論文投較高期刊 |
| **P7 Can Anything Beat VIX** | 「VIX 很難被打敗」共識已存在（Christoffersen-Jacobs 2004 / Liu et al. 2019） | 暫 hold，等 portfolio 整合決策 |

### Tier C — 暫 hold（method 問題嚴重）

| Paper | Critical issue | 必先處理 |
|---|---|---|
| **P8 Volatility Absorption** | NSI 套套邏輯：`|r|/VIX` 對 `VIX` 迴歸 = 機械性負相關（數學必然）。JFE <5% accept | 重做 method：Patell test 或 GARCH event study 或補外生事件 NFP surprise；目標期刊改 JFM / JoEF |
| **P1 leverage-direction** | N=22 截面樣本太小 + γ vs TSMOM 內生性（同一報酬序列估計） | 補理論機制 + 擴 N；JBF 30-40% |
| **P2 taiwan-vt** | N=9 個股 + 排除 0056.TW 選擇性偏差，5 倍放大 CI [2.8, 8.1] 寬到不可用 | 擴 sample 含 0056.TW；PBFJ 40-50% |
| **P3 vt-trend-following** | Target journal 不明 | 先確認 target journal，再評估 method gap |

### Tier D — In-progress

| Paper | Status |
|---|---|
| **P10 crypto-fear-channel** | body drafting 中（Codex 04-24 wake handles Gap A-F：claim-to-JSON / k1025.py / lit review 15-20 DOIs / outline reconcile / data snapshot） |

## Cross-paper portfolio risks（NotebookLM 抓到的）

- 9 篇 same dataset (SPY/GLD/TLT/VIX) 高度重疊 → reviewer 懷疑「一篇切九份」
- 結論都收斂「12/VIX 法則夠用」 → 同主題不同角度疲勞
- Self-citation working paper 比例需控制（< 30% target）

## 不再做的 anti-pattern

- ❌ 看到 reproduce gate GREEN 就 ping 用戶投稿（feedback_paper_multi_round_review 已記）
- ❌ 採信 single-paper latex review 給的 ★ 評分（feedback_paper_cross_paper_meta_eval 已記）
- ❌ 同期間多 papers 同時投稿（增加 portfolio overlap 暴露）
- ❌ 不 cross-check research_program.md 就採信 memory 內 paper status（本 memory 2026-04-27 morning vs evening 已 drift；canonical 看 research_program.md inline doc）

## 排程順序（更新 2026-04-27 evening）

**Tier A 已 exhausted**（P9 wait reviewer, P6 wait user confirm）— 兩篇都進等待狀態，主線程沒有 actionable 推進空間。

主線程下一波 effort 投放選項：
1. **P5 ABM framing 重寫評估**（Tier B 最高 ROI，fundamental refactor 工程約 1-2 週；起點：先做 parameter sensitivity analysis ablation）
2. **P10 Codex 進度 check**（Tier D，body drafting 應該已有 Codex 04-24 wake 後續產出可審）
3. **P4ins / P7 portfolio 整合決策**（Tier B 中等 ROI，需思考論文間 narrative consolidation）
4. **P8 method replacement 評估**（Tier C critical issue，但工程量大；考慮目標期刊降級 JFM/JoEF 後評估）

按 ROI/effort：1 > 2 > 3 > 4。建議下個 cron heartbeat 啟動 P5 ABM ablation experiment（experiment-runner 派 worktree agent，跑 sensitivity analysis 不直接 rewrite paper）。

## 教訓 reference

- 2026-04-27 morning: P5 v2 round 採信 latex agent 4.4★ → NotebookLM 揭露 ABM 設計性 → 撤回到 3.5-3.8★。教訓：每輪 review 必加 cross-paper meta-eval（本 memory + feedback_paper_cross_paper_meta_eval）
- 2026-04-26 alert 4d05236b ping 投稿方向錯誤：不該採直接投稿 framing，應採 review-cycle framing
- 2026-04-27 evening: P6 v1→v4.1 五輪迭代 + K1260 GJR-X fair-info benchmark experiment 是首篇通過 6-criteria gate 的 case study，可作其他 paper 的 template
- **2026-04-27 evening: 本 memory drift 案例** — morning 創建時誤標 P9 為「working Tier A 最接近可直投」，實際 P9 早在 ~2026-04-19 已 submitted under review。教訓：memory 是 snapshot，paper status 看 research_program.md 為準
