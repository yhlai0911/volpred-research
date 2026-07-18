# K1731 arm B 拆段 3／3：修正 SSVS ES + 標記 superseded 產物（bounded）

**Model**: claude-opus-4-8 / xhigh (per model_router)
**Parent**: `agent-brief_k1731_armB-f3e688`（原 timeout job）→ 拆段1 `k1731-armB-split-verification`（已完成，verdict=**needs_fix**）
**Worktree（唯一工作目錄）**: `.claude/worktrees/dispatch-slot-1-bd00f90a-k1731`
**Stage**: `esfix`

---

## 0. 先讀（不要跳過）

- `experiments/k1731/k1731_armB_verification.json` — 拆段 1 的驗收報告，`blocking_issues` 就是你這一段的工作範圍（B1/B2/B3）。
- `experiments/k1731/README.md` §3.1 / §3.5 / §9 — 你會改到的段落。
- `.claude/rules/experiments.md` — 特別是 verdict 凍結順序（**先凍 bytes 再 review**，審完再動 code 會讓 sha 漂移）。

**本段只做 B1 + B2，並為 B3 準備好凍結前狀態。B3 的 verdict 產生 + Codex 對凍結 bytes 重審 + merge 屬於下一段（task `assign_67f56b79`），你不要合併 worktree、不要跑 merge_worktree.sh。**

---

## 1. B1（high）— SSVS expected shortfall 算錯物件

**現況**（`experiments/k1731/k1731_gevreg_midas_ssvs_returns.py:227-237`）：
ES 取「每個 posterior draw 在**自己那個 component 的 p-quantile** 上的 ES」再 `np.nanmean`。
但 SSVS 的 VaR 是**反轉 posterior mixture CDF**得到的**單一共同門檻**（`k1730_models.py:727-761`）。
mixture 的 ES_p ≠ 各 component ES_p 的平均 → **報出來的 ES 不是「超過所報 VaR 的尾部期望」**，
§3.1 的 SSVS ES p-value 0.0145 與 §3.5 的推論都建立在這個不一致物件上。
Codex 已逐行確認**只有 GEVReg-MIDAS-SSVS 這一個模型受影響**（GEV-HAR / Gaussian-MIDAS / Empirical / GARCH-t 的 ES 路徑都正確，HAR-QR 誠實標 n/a）——所以修正範圍就是這一個模型，不要順手改別人。

**正確做法**：ES 必須對**共同門檻** Q（就是那個已經算出來的 mixture 反轉分位數）取尾部期望：

    ES_p = E[L | L > Q] = (1/(1-p)) * mean_over_draws( 各 draw 在門檻 Q 以上的 partial tail contribution )

亦即：先取得 mixture 反轉出來的 Q，再對**同一組 draw**求「超過 Q 的部分」的貢獻後平均，而非讓每個 draw 用自己的分位數。
實作可用 (a) 各 component 在任意門檻 Q 以上的 partial expectation，或 (b) 直接對已用於分位數反轉的 predictive draws 取尾部均值 —— 兩者擇一，選你能證明數值正確的那個。

**必附數值證明**（不接受「我改好了」）：構造一個**刻意異質**的小型 mixture（例如兩個 component、σ 或 ξ 差很大），
用大量 Monte Carlo 抽樣得到「真值」ES，比對 (i) 舊的 component-wise 平均、(ii) 你的新算法。
新算法要收斂到 MC 真值、舊算法要看得出偏差。把這個檢查寫成 `experiments/k1731/k1731_es_mixture_check.py`，
結果存進本段 artifact。**這是本段最重要的一件事** —— 沒有它，這次修正跟上一版一樣只是宣稱。

**重跑**：posterior draws **沒有持久化**（我已確認：script 內只有 in-memory `ssvs["param_draws"]`，
目錄裡無 .npz/.npy）。所以拆段 1 說「不必重跑、draws 已存」是**錯的**，不要照抄。
正確路徑 = 修好 code 後**重跑 corrected-spec production run**（`--exclude-ip --garch-origin-lag 1` 那組，
即產出 `..._results_corrected.json` 的同一組旗標；確切指令看 README §9 + `run_corrected.log` 開頭）。
上次該 run 實測 **1189s**，seed 42 決定性，budget 內綽綽有餘。

**重跑後強制回歸檢查**（防止你不小心動到別的東西）：
新 artifact 的**所有非-SSVS-ES 數字**必須與 `k1731_gevreg_midas_ssvs_returns_results_corrected.json` 完全一致
（pinball / tail pinball / DM t,p / PIP / Kupiec / Christoffersen / DQ / 經濟價值 / 描述統計 全部）。
**唯一允許變動的是 GEVReg-MIDAS-SSVS 的 ES 相關欄位**。有任何其他欄位漂移 → 停下來報告，不要自行合理化。
把 diff 清單（欄位路徑 → 舊值 → 新值）寫進 artifact。

**README**：§3.1 / §3.5 更新為新的 SSVS ES 數字，並在該處明寫一句「舊版 ES 為 component-wise 平均、與所報 VaR 不同物件，已於 rev3 修正」。
若新 ES p-value 讓結論翻轉（例如原本 reject 變不 reject），**照實寫，不要修飾** —— 結論翻轉是結果，不是失敗。

## 2. B2（high）— 兩份 production artifact，缺陷那份佔著預設檔名

`k1731_gevreg_midas_ssvs_returns_results.json`（原始 spec：IP cross-vintage YoY 汙染 + GARCH 資訊集不對稱）
沒有任何 in-file 標記說明它已被取代，而且它佔的是最短、最像預設的路徑 —— 下游（文章／論文／knowledge.json／跨 arm 比較）
按直覺路徑取檔就會拿到有缺陷的那份。這正是 README §5.3 在 arm A 抓到的同一種災難，arm B 自己又犯了一次。

**修法（fix the process, not the data）**：由 `k1731_finalize_report.py` 寫入，**禁止手改 JSON**。
在原始 artifact 頂層加：

    "superseded_by": "<本段重跑後產生的 canonical 檔名>",
    "superseded_reason": "IP cross-vintage YoY corruption; GARCH information-set asymmetry",
    "do_not_cite": true

並在 README §9 註明：原始 artifact 僅為比較保留、**且無法用現版 script 逐位元重現**
（現版會多寫 `specification` block；原版由 rev2 之前、已不存在於 tree 的 code 產生）。
同時給本段新產出的 canonical artifact 一個明確的 `is_primary: true` 之類正向標記，讓「哪份才是正主」不需要靠檔名猜。

## 3. B3 準備（本段**不做**判定，只交出可凍結狀態）

不要自己寫 `review_verdict.json`，也不要跑 `experiment_gates.py verdict-template`。
你只要確保：code 與 artifact 在你交件時是**最終狀態**（下一段會先凍 bytes 再送 Codex 重審）。
在 artifact 裡列出「下一段該凍哪些檔」清單。

## 4. 非阻斷但要留紀錄（不要在本段修）

拆段 1 另有兩條 non-blocking 發現，**寫進 artifact 的 `deferred` 欄位**即可，不要擴大戰線：
- `scripts/var_backtest_trinity.py:196-209` DQ test 在反轉前加 ridge，使 singular 分支不可達（K1731 未觸發：breach 57-92 / 14-51，設計矩陣滿秩）→ 屬共用 helper backlog。
- DM 未套 Harvey-Leybourne-Newbold 小樣本乘子且未揭露，且 artifact 的 `harvey_significant` 欄位其實是 |t|>3 的多重檢定規則、名稱誤導 → n=967 下數值可忽略，屬揭露瑕疵。

## 5. 產出契約

**唯一 result artifact**：`experiments/k1731/k1731_armB_esfix.json`，至少含：

- `stage: "esfix"`, `parent_verification_artifact`, `experiment_id: "k1731"`
- `b1`: 修正說明 + `k1731_es_mixture_check.py` 的 MC 對照結果（舊算法偏差、新算法誤差）+ 新舊 SSVS ES 數字 + ES backtest p-value 新值 + 結論是否翻轉
- `rerun`: 指令、runtime、seed、log 路徑
- `regression_check`: `identical: true/false` + 允許變動欄位清單 + 任何非預期漂移
- `b2`: finalize_report 的改法 + 兩份 artifact 最終的標記狀態 + 新 canonical 檔名
- `files_to_freeze`: 下一段要凍結的檔案清單
- `deferred`: 上面兩條
- `verdict`: `ready_for_verdict_gate` | `needs_more_work`（誠實填；翻轉結論不等於 needs_more_work）

**成功判準**：mixture ES 有 MC 數值證明、重跑通過回歸檢查、兩份 artifact 都有明確 primary/superseded 標記、README 已同步。

## 6. 邊界（硬規則）

- **禁止** 合併 worktree、跑 `merge_worktree.sh`、force-remove worktree、寫 knowledge.json。
- **禁止** 動 K1730（arm A）任何檔案。
- **禁止** 為了讓 p-value 好看而調參數／換 spec。研究誠實 > 一切。
- 若時間不夠完成「patch + 重跑 + 回歸檢查」，**先把 patch 與 MC 證明做完並誠實交出 `verdict: needs_more_work` + 精確的重跑指令**，不要在被 kill 的邊緣硬跑。
