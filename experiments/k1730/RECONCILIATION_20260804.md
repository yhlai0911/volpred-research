# K1730 lineage 裁決（2026-08-04，main thread：k1730_v2_adopt_reconcile_recertify_20260802）

## 裁決：authoritative baseline = v2 lineage（cd931fbf）

| | v2（本 suite） | v1-source F3 復核 |
|---|---|---|
| results md5 | `cd931fbff53c0e9c3210cecb26ea3fbf` | `d0d25fe2b49eeca9ac7d8ab5dc7d0419` |
| 代碼 | 補救版（對 codex_review_v1 FAIL 的 REMEDIATION_v2；與 v1 差 461 行） | v1 原版（k1731 worktree 內） |
| MCMC 設定 | n_burnin=15000、n_chains=4 | n_burnin=10000、n_chains=2 |
| multistart 診斷 | basin concentration 0.867–0.92、feasible-optimum ≥0.967 | mean_convergence_rate 0.509 |
| 完成時間 | 2026-07-19 16:04Z | 2026-07-21 10:11Z（K1731-F3 跨臂數字復核用途） |

## 一致性與差異（兩份 production JSON 逐項比對，2026-08-04）

- **性質結論一致**：coverage 不足（0.8521 vs 0.8501 @90%）、Kupiec 拒絕、增量價值 NULL 敘事同向。
- **邊界 DM cell 會跨 0.05 漂移**：vs GEV-HAR p 0.0311↔0.0460、vs HAR-QR p 0.0512↔0.0757 ——
  **任何被引用的數字必須只出自 cd931fbf**，不可混引兩版。
- d0d25fe2 降級為 **cross-check 收據**：它以較弱設定與 v1 代碼獨立重跑得到同向結論，
  是 robustness 佐證，不是 canonical 數字來源。

## 已知待辦（不在本文件掩蓋）

1. 本 suite 原 `reproduce_spec.json` 為手寫、entrypoint sha 與 v2 代碼不符（K1708 drift 類）——
   已把 `finalize_experiment` 接進 entrypoint，**由 compute queue 重跑（~3.7h, seed 42）在
   run-time 重生 spec**，並以重跑結果對 cd931fbf 驗證數值同一性。
2. knowledge 現行 K1730 條目引用 d0d25fe2 為 production 定案 —— 重跑落地後需寫
   research_correction 更正 provenance（authoritative=cd931fbf lineage 的重跑驗證版）。
3. 認證：Codex 額度鎖至 8/8 → 依 2026-08-04 K1714/K1735 先例走雙 fallback 審查，
   primary 補驗併入 `codex_primary_reverify_k1714_k1735_20260808`。
4. `codex_review_v1.md`（FAIL）與 `REMEDIATION_v2.md` 全程保留 —— FAIL 軌跡是 suite 的一部分。
