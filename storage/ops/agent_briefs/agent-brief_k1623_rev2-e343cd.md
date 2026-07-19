# K1623 修復 rev2 — 撤回 long-memory 識別宣稱 + 補 MSE DM 與多重比較

**Model**: opus / xhigh (per model_router)
**Task id**: `assign_5aa9d5f5` (P2, experiment)
**Worktree（你唯一可寫的地方）**: `.claude/worktrees/dispatch-slot-2-c5cafe39-k1623`
**parent_task_id**: `dreaming_orphaned_experiment_k1623`

## 0. 開工前必讀（照順序）

1. `AGENTS.md` §研究誠實原則（13 條，尤其 #10 承認局限、#13 推翻舊結論必回溯更正）
2. `docs/error_log.md`
3. `.claude/skills/autonomous-research/references/experiment-preamble.md`
4. `experiments/k1623/README.md` + `experiments/k1623/k1623.py` + `experiments/k1623/k1623_results.json`

## 1. 背景

K1623 於 2026-07-17 孤兒收尾時經 codex gpt-5.6-sol (reasoning=high) 獨立二審判 **FAIL**。
依 K1259 規則**不得寫入 knowledge.json**，結論必須**撤回**而非收編。本 task 是它的修復出口。

**關鍵**：算術本身全部一致 —— 問題不在計算，在**「宣稱」超過了「證據」**。所以這不是重跑實驗，
是**改寫論述 + 補上該做而沒做的檢定**。不要推倒重來，不要「順便」擴充範圍。

## 2. FAIL 的 7 條理由（逐條都要有回應）

1. **識別宣稱不成立**：至多 5（permissive 15）個 deterministic Bai-Perron mean break，扣不掉
   Diebold-Inoue 所設想的隨機／密集 regime shift。故「純 level-shift 假象假說被拒絕、確有真
   long-memory 成分」**無識別定理支撐**。且 demeaned d̂ 的 SE 直接沿用 raw ELW 漸近 SE，
   未計入「斷點是估計出來的」generated-regressor 不確定性。
2. **結論隨 loss function 反轉且未揭露**：DM **只跑了 QLIKE**，而 ARFIMA 的 MSE 在 5 資產中有
   4 個低於 HAR（SPY 0.889 / TW0050 0.836 / QQQ 0.874 / N225 0.891，低 11-16%）。
   README §4 宣稱報 QLIKE+MSE 兩個 loss，**實際只對 QLIKE 做檢定**，MSE 方向相反且完全未提。
3. **「不可交易」純屬修辭**：無任何交易策略／成本／效用測試。
4. **README §3「多處反而顯著更差」不實**：10 個 ARFIMA/BreakHAR 比較中僅 1 個顯著
   （QQQ t=+2.47, p=0.0137），且對 5 個檢定做 Bonferroni 即不顯著；20 個 DM 比較**全無多重比較修正**。
5. **描述與程式碼不符**：§4 稱 BreakRobustHAR「只用最近 latest-break 之後樣本 refit」，但
   `k1623.py:471` `wstart = max(0, min(brk_start, i-22-60))` 在斷點太近時**刻意把窗口推回斷點之前**，
   無斷點時 fallback 到 trailing 750。
6. **ELW 方法描述不實**：§4/§9 headline 稱 ELW 為「Shimotsu-Phillips 可估非平穩 d」，但 code 只做
   sample-mean demeaning（非 SP 的 unknown-mean μ̂(d) 加權）；`FD_MAXK=2000` 對 n=2,565-4,655
   **實際 binding**，對 d̂=0.723 的 VIX（d>0.5，樣本平均在非平穩區不是有效 level 估計）影響最大。
7. **VIX cap binding**：permissive 斷點選到上限 15/15，故夾擠上界 20.3% **不構成上界**。

## 3. 可保留的描述性事實（不依賴已崩的識別宣稱 —— 這些不要動）

- 扣掉 BIC 斷點後 ELW d̂ 仍 0.46-0.65；扣掉 10-15 個 permissive 斷點後仍 0.19-0.58
  （殘餘低頻持續性未消失 —— 這是**描述**，不是識別）
- OOS n=749/資產；HAR 在 QLIKE 上是 5 資產冠軍或並列最佳
- BreakHAR vs HAR 10 個比較全部不顯著（最小 p=0.0946）

## 4. 要做的（依序）

1. **補跑 MSE 的 DM 檢定**（5 資產 × 對照組），並對**全部 20 個 DM 比較**做多重比較修正
   （BH FDR 與 Bonferroni 兩者都報，明講用哪個下結論）。把 loss 反轉寫進結果表 —— 這是本輪最重要的產出。
2. **改寫 `experiments/k1623/README.md`**，撤回三個宣稱：
   - (a)「真 long memory 成分存在」的 **identification** 宣稱 → 改為「BIC/permissive 斷點扣除後
     d̂ 仍為正，此為**描述性殘餘持續性**，不構成對 Diebold-Inoue level-shift 假說的拒絕」
   - (b)「不可交易」→ 刪除，或明講「本實驗未做任何交易/成本/效用測試，故不對可交易性表態」
   - (c)「多處反而顯著更差」→ 改為「20 個比較中僅 1 個名目顯著，多重比較修正後無一顯著」
3. **修正 ELW 方法描述**：明寫是 sample-mean demeaning 而非 Shimotsu-Phillips μ̂(d)；
   揭露 FD_MAXK binding 與其對 VIX 的影響；揭露 VIX permissive cap 15/15 binding、上界不成立。
4. **修正 BreakRobustHAR 描述**使其與 `k1623.py:471` 實際行為一致。二擇一並在 README 說明選了哪個：
   (i) 改描述對齊 code（較省，且不動已驗證數字）；或 (ii) 改 code 對齊描述並重跑。
   **推薦 (i)** —— 本輪目的是修「宣稱 vs 證據」，改 code 會讓所有數字失效、超出 scope。
5. **demeaned d̂ 的 SE**：至少在 README limitation 明講「未計入斷點估計的 generated-regressor
   不確定性，故報告的 SE 為下界」。若時間允許，補一個 residual-block bootstrap 的 d̂ SE 作為 sanity。
6. **寫 `experiments/k1623/k1623_rev2_results.json`**（本 task 的 result artifact）：含
   MSE DM 全表、BH/Bonferroni 調整後 p、每條撤回宣稱的 before/after 對照、以及一個
   `retracted_claims` 陣列明列撤回了什麼、依據是什麼。
7. **記一條 error_log**：§9 記載前一輪 codex（gpt-5.5）判「no CRITICAL/HIGH」與本輪 gpt-5.6-sol
   直接衝突 —— 前輪 review 未捕捉上述問題。這是 **reviewer 可靠度**的教訓，寫進 `docs/error_log.md`
   （worktree 內改，主線程 merge 時帶進去）。

## 5. 硬規則

- **禁止寫 `storage/memory/knowledge.json`**（K1259）。本輪產出只進 `experiments/k1623/` 與 `docs/error_log.md`。
- 禁止修改 `storage/reports/feed.json`、`storage/memory/*.json`、Supabase / Mirror sync。
- 隨機程序固定 seed。Lookahead：`signal.shift(1)` 慣例不可破。
- **Null / 反向結果如實報告**。MSE 方向相反就照實寫，不要用措辭圓場。
- 不要擴充 scope：不要加新資產、新模型、新樣本期。

## 6. 成功標準（缺一不可）

1. `experiments/k1623/k1623_rev2_results.json` 存在，含 MSE DM 全表 + 多重比較修正後 p 值 + `retracted_claims`
2. `experiments/k1623/README.md` 三條宣稱已撤回改寫，且 §4 方法描述與 `k1623.py` 實際行為一致
3. 所有數字可從 JSON 逐項對上，無任何 README 宣稱在 JSON 找不到依據
4. worktree 內 `git commit`（**必做** —— 沒 commit 等於工作遺失）
5. 最終回覆給出：改了哪些檔、MSE DM 的結論、撤回了哪幾條、還有哪些 limitation 沒解

## 7. Lookahead / 後續

修完後這個 K 有一個**可發佈 angle**（撤回識別宣稱後仍成立）：
「同一組預測、同一批模型，換一個 loss function 結論就反轉：QLIKE 說樸素 HAR 贏遍 5 個資產，
MSE 說 ARFIMA 在 4/5 資產低 11-16%」—— 純描述性、可從 JSON 直接驗證的方法論教訓（呼應 K1016）。
**不要在本輪寫文章**，只要在 README 末尾留一段 `## 可發佈 angle` 說明素材已備妥即可。
