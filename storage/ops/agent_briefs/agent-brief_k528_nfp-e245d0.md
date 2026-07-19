# k528 NFP 事件日污染修復 + 線上文章更正

**Model**: opus / xhigh (per model_router)
**Task id**: `assign_ae004ae2` (P1, starved 6.5h)
**Worktree（你的唯一可寫範圍）**: `.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp`（branch `k528-nfp-official-dates`）

## 背景

`experiments/k528/k528_nfp_event_study.py` 用 `get_first_friday()` 當 NFP 發布日的 proxy。全樣本實測（2005-02~2026-03，254 筆，FRED 官方涵蓋完整、無外插）：

| 項目 | 筆數 |
|---|---|
| 與官方日期相符 | 201 |
| **proxy 錯誤（該日根本無發布）** | **53（20.9%）** |
| 官方發布被完全漏掉 | 52 |
| 幻影月份（2025-10） | 1 |

偏誤是**系統性偏早**（35 早 / 13 晚）：28 筆剛好早 7 天（BLS 因參考週改在第二個週五）、12 筆晚 3-4 天（假日提前）。**不是隨機噪音，是結構性錯位** —— 這決定了你不能假設「平均會抵銷」。

**衝擊面**：線上文章 `mile_35eef830` 正文的所有主要數字 —— 1.10 倍、1.17 倍、**2.17 倍體制差**、相關係數 **0.45**、分界值 **16.71**、254 次樣本 —— 全部出自 k528。

來源：`event_article_nfp_2026_07_03_t1` 修正報告 §7（已合併，commit 8dfb83806）。parent task `assign_358decfa`。

## 要做的事（依序，不可跳步）

### (1) 換官方日曆，全樣本重跑
`k528_nfp_event_study.py` 改用 `volpred.data.event_dates.nfp_release_dates`（`src/volpred/data/event_dates.py:133`）。**fail closed** —— 官方日期取不到就 raise，絕不 silently 回退 proxy。禁止保留任何 `get_first_friday()` 呼叫路徑。

### (2) 逐項對照，判斷結論是否翻轉
對 **2.17 倍體制差 / 相關係數 0.45 / 分界值 16.71 / 1.10 倍 / 1.17 倍 / 樣本數** 每一項做 before-after 對照表。

⚠️ **教訓（硬性）**：**平均值可能幾乎不動，而中位數與勝率翻轉**。不可只看平均 —— 每項都要同時報 mean / median / 勝率 / 樣本數 / 顯著性。明確標記每項是「數值微調」還是「結論翻轉 / 失去顯著性」。

### (3) 若核心論點變動 → in-place 更正線上文章
用**既有**的 `src/volpred/publisher/article_correction.py`（**唯一入口**，all-or-nothing、每個替換必須恰好命中一次）。

🚫 **禁發第二篇更正文**。🚫 禁自己寫替換邏輯。若某個替換沒有恰好命中一次 → 停下來回報，不要 force。

### (4) 補 regression + mutation test
- 官方日曆 regression test：釘住 k528 用的是官方日期、樣本數與官方一致
- **mutation test：還原成 `get_first_friday()` proxy 必須讓測試轉紅**（否則這個 gate 是假的）

### (5) 產出結果檔
`experiments/k528/k528_nfp_official_dates_results.json`，須含：before/after 每項指標對照、樣本數變化、翻轉判定、文章更正的替換清單與命中數。

## 紀律

- **只在你的 worktree 內寫檔**。禁碰 canonical checkout、禁 `git push`、禁 `--no-verify`、禁 force。
- **真實數字，禁編造**。任何無法取得的數字寫 null 並說明，不要填猜測值。
- 研究誠實 > 一切：如果修正後結論其實**沒有**實質改變，就誠實這樣寫 —— 那也是有價值的結果，不要為了「有交代」硬找變化。
- 完成後 commit 在你的 branch 上（**不要 merge**，合併由後續 fire 走正式 `merge_worktree.sh`）。
