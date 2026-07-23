# K1380 分階段重跑：修正反向 QLIKE 後重算 Paper 9 SPA / White RC

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Task id**: `k1380_rerun_staged_correct_qlike` (P2, starved 90.9h)
**Worktree / cwd**: `.claude/worktrees/dispatch-slot-1-375ba0e3-k1380`（已建好，branch `wt/dispatch-slot-1-375ba0e3-k1380`，從 main 開）

## 背景（必讀，決定這次做什麼）

K1380 於 2026-07-16 的結論（SPA p=1.000、White RC A4f t=-0.272、GJR mean QLIKE 623.7 最低 →
「多重檢定校正後無任何 VIX-augmented spec 勝過 GJR」）是 **loss function bug 的產物，已作廢，
禁止寫入 Paper 9**。

根因：`k1380.py` 的 `qlike()` 把比值寫反成 σ̂²/r²（應為 r²/σ̂²）。反向式非 proxy-robust ——
在 r²=σ²χ²₁ 下 E[1/r²] 發散，期望值由 σ̂²→0 最小化，機械性獎勵低估波動率；GJR 因不吃 VIX
spike、預測值最低而必然勝出。

2026-07-17 數值驗證（400k draws，預測=c·σ²_true）：robust loss 在 c=1 最小（1.271）；反向
loss 隨 c 遞減（c=1: 559,680 → c=0.02: 11,195）。

三項佐證：
1. mean QLIKE ~620-740 vs 同 proxy 同 OOS 同 n=1852 的 K1379 之 ~1.4，量級差 400x，loss max 4.1e8
2. A4f vs GJR 在此 t=-0.272，K1379 同樣本 t=-4.37 (p=1.3e-5) —— 微小 r² 日的噪音吃掉訊號，
   SPA 不拒絕是 power artifact
3. A5/C2/C3 被以「數值發散」排除，但它們正是預測值最高、被反向 loss 懲罰最重的 spec，
   排除理由需重判

**bug 已修**（`k1380.py:647`，2026-07-17）；舊成果已歸檔 `experiments/k1380/*_INVALID_20260716.*`；
完整記載見 `experiments/k1380/README.md`（**開工第一件事就是讀完它**）。

## 為什麼必須分階段

單體 `k1380.py` 上次跑 2h54m 後 timeout（parent job
`compute-k1380-paper-9-white-rc-hansen-spa-test-17-spec-multiple-test-1779189466`, exit -1），
compute_queue 已依 split contract **拒絕原樣重派**。

舊的 `k1380_spa_from_cache.py` 是死路 —— 快取的是錯 loss，且 x-log(x)-1 非單射，無法算術還原，
OOS 預測必須重新 fit。

## 你要做的

### 1. 重構 `k1380.py` 支援 `--stage`

三個 stage，每段單一 artifact、有 success criterion、timeout 各 ≤5400s（短於 parent）：

| stage | 內容 | artifact |
|---|---|---|
| `forecasts_a` | A-series 10 spec + B0 benchmark | forecast matrix（**存 σ̂² 本身，不是 loss**）|
| `forecasts_midas` | B1-B3, C1-C3 | forecast matrix（同上）|
| `spa` | 從 forecast matrix 算 QLIKE + Hansen SPA + White RC | results json |

**存 σ̂² 而非 loss 是硬要求** —— 這樣未來換 loss 不必重 fit。

### 2. 逐段 enqueue（你自己下，不要跑）

```
--timeout-parent-job-id compute-k1380-paper-9-white-rc-hansen-spa-test-17-spec-multiple-test-1779189466 \
--split-stage <forecasts_a|forecasts_midas|spa>
```

`spa` 段依賴前兩段的 artifact，enqueue 時在 brief 寫明前置。

### 3. SANITY GATE（**不過就停，不准往下**）

新 mean QLIKE **必須落在 ~1.4 量級**（對照 K1379：A4f 1.400 / GJR 1.480）。
若仍是數百量級 → 還有 units/定義問題，**不得往下寫論文**，改開 debug task 並在 results.json
記下實測值與你的診斷。

### 4. A5/C2/C3 重新判定

在正確 loss 下重新判定是否真發散，**不可沿用舊排除清單**。判定理由寫進 README。

### 5. 論文段落（只有數字過 gate 後才做）

數字過 `agent-result-verification` 後，**最後一段的 compute followup** 才寫 Paper 9 body 的
Multiple Testing 子節（`main.tex` 已有 `\subsection{Multiple Testing Considerations}` 佔位
~line 813，現況僅 Bonferroni 兩句）→ 擴成 SPA/RC 結果表 + 排除 spec 註記 + 經濟詮釋，
過 `finance-paper-quality` claim-evidence gate。

### 6. 結論兩個方向都可發表

撐住 A4f>GJR 就照實寫；推翻也照實寫並同步修 MCS/DM 段落措辭。**禁誇大禁粉飾。**

### 7. 禁令

- **knowledge.json 由主線程寫，agent 禁寫**（K1259）
- 禁 force push、禁 `--no-verify`、禁假數字
- 實驗代碼跑之前：確認 `signal.shift(1)` lag 在代碼裡、baseline 用同樣 lag；
  結果好得不像真的 = 90% 有 bug

### 8. 合併前 gate

`uv run python scripts/experiment_gates.py run --path experiments/k1380` 必須綠燈。

## Lookahead sanity check

這條線的價值在於「Paper 9 的多重檢定結論到底是什麼」。上一版結論之所以要作廢，正是因為
loss 寫反讓「預測愈低愈贏」。**你重跑出來的任何結論，先問自己：這個排名是不是又被某個
機械性偏好驅動的？** mean QLIKE 量級是最便宜的照妖鏡，先看它。

## supersedes

parent task `paper9_c3_multiple_testing_subsection_k1380`（已標 failed —— 其 description 引用的
「誠實結論」即為本 bug 產物）。
