# K1731 F3 — arm A 數字用 production run 重核（parent task: `k1731_F3_armA_production_recheck`）

**Model**: opus / xhigh (per model_router)
**工作目錄**: `.claude/worktrees/dispatch-slot-1-bd00f90a-k1731`（已註冊的 linked worktree，只在此寫入）

## 0. 先讀這段：你接手的狀態跟 brief 原本寫的不一樣

本任務原始的 followup brief 寫於 2026-07-21 09:09，當時 arm A 的 production run 還沒跑。之後發生兩件事，
**都已完成，不要重做**：

1. **production run 已經落地且合格**。`experiments/k1730/k1730_gevreg_midas_ssvs_results.json`
   （2026-07-21 18:11 寫入，`started_utc=2026-07-21T09:15:09Z`）：
   - `quick_mode = false` ✅
   - `config = {n_starts: 30, n_draws: 40000, n_burnin: 10000, thin: 10, n_chains: 2, n_pred_draws: 500}` ✅
   - md5 = `d0d25fe2b49eeca9ac7d8ab5dc7d0419`，已**不再**等於 quickmode 檔的
     `af6167c936d435c5c9ce13cddefea3db` ✅（舊 production 檔曾經是 quickmode 複本，這是本任務的起因）

   → brief 第 (1) 項「驗 production 合格」**已由本班主線程驗完**，你只要引用，不必重跑那支 60 分鐘的 job。

2. **跨臂 DM t=+2.13 的 nested-DM 缺陷已裁決**。見
   `experiments/k1730/K1730_NESTED_DM_ADJUDICATION.md`（2026-07-21 17:21）：該 DM 統計量在
   nested + pinball loss + recursive 估計下**沒有漸近常態極限、不是檢定**，已 **RETRACTED as inference，
   改標 diagnostic-only**，與 arm B 同處理。實質結論（macro 對週 RV 區間預測無增量價值）存活，
   但改靠 descriptive loss ordering + permutation diagnostic 支撐，不靠 DM p-value。
   該文件明寫：**K1731 側的修補由本任務擁有**（scope owner 分工）。

   → brief 第 (3) 項的「能校正就校正，不能就撤回」**已裁決為撤回**。你的工作是把這個裁決**落到 K1731 的 README**，
   不是重新辯論一次。

## 1. 你要做的事

工作面是 `experiments/k1731/README.md`。

### (a) 逐項重核 arm A 數字
用 production JSON 重核 README 中 **§3.3b / §5.3 / §6** 以及任何其他引用 arm A 的數字。每一個數字三選一：
- 與 production 一致 → 保留，並把出處標成 production artifact（含 md5 或 `started_utc`，讓後人可驗）
- 與 production 不一致 → **改成 production 數字**，並在該處註明「原數字出自 quick mode，已更正」
- production JSON 裡查無此數 → **標出處不明並移除該宣稱**，不要臆測、不要用 quickmode 數字補位

### (b) 落實 nested-DM 撤回
README 現有多處把 arm A 的 `t = +2.13, p = 0.0334` 當作推論證據（至少 line 338、636-645 一帶，自己再全文 grep 一次）。
依 §0.2 的裁決改寫：標為 **diagnostic-only、非檢定**，實質方向性結論保留但改述其證據基礎。
**禁止硬撐**，也禁止反向誇大成「因此結論無效」——裁決文說得很清楚：結論存活，支撐換了。

### (c) 清掉 quick-mode provenance 的殘留敘述
README 多處（§5.3、§7b、line 128-129、352、359、600、688）說「arm A 的 artifact 是 quick mode，所以這些數字只能當方向」。
production 落地後這個 caveat **對已重核的數字不再成立**——逐處改寫成現況。
line 688 那條「A completed arm A production run」的待辦，若已滿足就標成已滿足並指向 artifact。

### (d) 成功判準（自己驗，做不到就說做不到）
1. README 內**不存在**未標出處的 arm A 數字
2. 每個跨臂宣稱：要嘛有 production 支撐、要嘛已撤回並標明
3. `t=+2.13` 全文不再以推論語氣出現
4. 產出 `experiments/k1731/F3_armA_production_recheck.md`：一張表列出每個重核過的數字
   （README 位置 / 原值 / production 值 / 判定 / 出處），這是本任務的可稽核交付物

## 2. 硬規則

- **研究誠實 > 一切**。數字對不上就寫對不上；不要為了讓 README 好看而挑數字。
- 不得把 quickmode 檔的數字當 production 用。
- 不要 force-remove worktree，不要 `--no-verify`，不要 force push。
- 不要自己寫 `knowledge.json`（K1259 教訓）。
- 完成前跑 `uv run python scripts/experiment_gates.py`（或該 worktree 內對應路徑）確認 gate 狀態；
  若 nested-dm 檢測仍對 `experiments/k1730/k1730_gevreg_midas_ssvs.py:141-144` 報 FAIL，那是 **K1730 腳本的既有除籍項**，
  已由 `K1730_NESTED_DM_ADJUDICATION.md` 裁決，**不要為了讓 gate 變綠而去改那支腳本或弱化 gate** —— 在交付物裡註明即可。

## 3. 交付

- `experiments/k1731/README.md`（修訂）
- `experiments/k1731/F3_armA_production_recheck.md`（重核表，= result artifact）
- worktree 內 commit（訊息說明改了什麼、為什麼）
