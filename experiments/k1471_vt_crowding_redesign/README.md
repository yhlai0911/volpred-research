# K1471: VT-crowding ABM resimulation redesign（vt-crowding-abm v5 blocking fixes）

- **提出**: 主線程（task `experiment_vt_crowding_resimulation_2026_06_11`）
- **類型**: 模擬實驗（methodology redesign + rerun；非實證）
- **日期**: 2026-06-11
- **狀態**: 重設計 code + 單元測試 + M=50 smoke 完成；M=500 full run 已 enqueue compute_queue
- **前置**: K827v3（VT 基線）→ K1261（Phase 1 TF/MR/NC）→ K1262（strategy-spec OAT）→ K1262b（λ/γ OAT）
- **觸發**: `paper/vt-crowding-abm/review_history/audit_2026-06-10/audit_findings.json` — v5_independent Codex + Antigravity 雙 REJECT，5 HIGH 全為 methodology 重設計需求

## 動機：5 HIGH blocking issues → 5 項重設計

| # | v5 blocking issue | K1471 重設計 |
|---|---|---|
| (a) | P5-style detector「先知 70%」循環校準（calibrated to the standalone VT benchmark） | **外生 sup-Wald 斷點檢定**：對每 (cell, treatment) 的 sim-level Sharpe-vs-φ 曲線做 supremum-Wald 單斷點結構檢定（Andrews 1993 風格），p-value 由 label-permutation null（B=999, fixed seed）；斷點不確定性由 path-level bootstrap（B=500, fixed seed）→ frequency dist + 80% interval。舊 drop>{30/50/70}% 規則降級為 descriptive robustness grid，非 calibration anchor |
| (b) | NoiseControl 固定 0.5 權重幾乎零流量 = strawman falsifier | **Active control（RR_VT / RR_TF / RR_MR）**：coherent-block 隨機方向再平衡 agent。\|Δw\| 分佈（lognormal，mean/std matched）與再平衡頻率 match 同 cell×adoption 下對應 treatment 的實測 turnover（兩階段：stage 1 跑 treatments 記 turnover，stage 2 跑 matched controls）。方向 ±1 等機率、由獨立 RNG stream（seed+10000019），不讀任何 price/vix 歷史 → 與價格/波動正交 by construction。舊 NoiseControl 降為 sanity check |
| (c) | iid pooled 1.26M-day bootstrap CI 低估 SE + 「×500 sims」double counting | **CI 統一 path-level bootstrap**：所有 headline CI（Sharpe / kurtosis / MDD）= M 條 sim-level 統計量的 percentile bootstrap（B=2000, fixed seed）。pooled kurtosis 僅 cell1 報告，用 two-level circular block bootstrap（path 重抽 × path 內 42-day blocks，B=300, fixed seed） |
| (d) | cell1 閾值不可再現（M=500 vs M=200 跳 20%→70%）、grid 太疏無 CI | **cell1 grid 加密**：{10,30,**40**,50,**60**,70,100}%；cells 2–5 = {10,30,**50**,70,100}%。每個 threshold 報 path-level bootstrap CI（斷點 frequency dist + 80% interval）；full run M=500 |
| (e) | cell3 MR baseline Sharpe=−5.56，null 被翻轉計入 MR≤VT 支持證據 | **Applicability gate**：最低 adoption mean Sharpe < −0.5（外生 floor，分析前設定）→ detector 回報 `not_applicable_saturated_loss`，不強行宣稱斷點、不計入 ranking 證據 |

## 設計不變項（與 K827v3/K1261/K1262/K1262b 完全相同）

- Market microstructure：N=1000 agents（200 noise 固定 + 800 BH/strategy 池）、N_DAYS=2520、VIX feedback（γ）、Kyle price impact（λ）、noise trader std=0.02 — **verbatim**，重設計差異只來自 detector / control / CI
- OAT cells：cell1 baseline（λ=0.005, γ=200）、cell2 λ_low、cell3 λ_high、cell4 γ_low、cell5 γ_high
- Lookahead 防護：VT 讀 `vix_series[t-1]`；TF/MR signal 用 `returns[t-window:t]`（不含 t）；RR_* 不讀任何價格歷史
- Seeds：sim seeds 沿用 K1262b formula + deterministic treatment offset（RR_* 用 7,000,003 / 7,100,003 / 7,200,003 offset 確保與 matched treatment 不重疊）；permutation / threshold bootstrap / CI bootstrap / block bootstrap 各有固定 base seed；字串 hash 用 `zlib.crc32`（非 Python `hash()`，避免 per-process randomization 破壞再現性）

## Treatments（7）

| Treatment | 角色 |
|---|---|
| VT_baseline / TF / MR | 3 個 strategy treatments（K1262b 原樣） |
| RR_VT / RR_TF / RR_MR | 3 個 matched active controls（新，(b)） |
| NoiseControl | legacy sanity check（降級，非 falsifiability anchor） |

## 規模

| Run | M | Total sims | 實測/預估 runtime |
|---|---|---|---|
| smoke | 50 | 9,450（7 treatments × 27 adoption-cells × 50） | 見 `k1471_smoke_results.json` `runtime_seconds` |
| full | 500 | 94,500 | 預估 60–90 min（K1262b 基準 0.028 s/sim × 8 workers + matched-control 兩階段 + block bootstrap） |

## 檔案

- `k1471_vt_crowding_redesign.py` — 主 script（`--n-sims`, `--tag`, `--cells`）
- `test_detector_unit.py` — detector 單元 sanity（合成 break / flat / saturated / determinism / RR turnover matching）— **6/6 PASS**
- `k1471_smoke_results.json` + `k1471_smoke_threshold_table.md` — M=50 smoke（pipeline 驗證用，**不作推論**）
- `k1471_full_results.json` + `k1471_full_threshold_table.md` — M=500（compute_queue 產出）
- `smoke_stdout.log` — smoke 執行 log

## 成功標準

1. ✅ Detector 單元測試：合成 break 正確定位、flat curve p>0.05 無 false positive、saturated regime 正確 gate、固定 seed 完全 deterministic
2. ✅ Smoke M=50 全 pipeline 跑通（兩階段 + detector + bootstrap CI + block bootstrap）
3. Full M=500：每 (cell, treatment) 有外生 threshold + p-value + bootstrap interval；RR_* 對照組可區分「策略方向性 feedback」vs「任意大型協同流量」
4. 不改 `paper/*.tex`、不寫 knowledge.json（主線程 post-review 處理）

## Caveats

1. Smoke M=50 的 detector 輸出僅驗 code path，閾值數字不可引用（power 不足）
2. RR_* 的 \|Δw\| lognormal 經 clip 後實際分佈略窄於 target（單元測試顯示 mean match 至 ~0.2%）
3. 兩階段設計使 RR_* 的 matched turnover params 來自同 run 的 treatment 實測 — 這是 by-design（control matched to measured footprint），非 leakage：turnover stats 是 treatment 的 ensemble 統計量，不進入 RR 的逐日決策資訊集
4. Permutation test 假設 exchangeability under null（同分佈跨 adoption groups）— 對 mean-shift alternative 是 standard；variance 也隨 adoption 變的情況下 sup-Wald 用 Welch-type denominator 部分緩解
