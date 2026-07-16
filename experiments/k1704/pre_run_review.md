# FAIL

審查快照：HEAD `3d5c8949e5030ca6977add407f25775f28adeba5`。未讀取或採信未追蹤 results/cache。

阻斷 findings：

1. **跨 proxy 評分 ledger 不一致。** `evaluate_target()` 每次依各 target 的正值與各自 calibrated forecasts 重新建立 `common` mask；六個 target 因此可能使用不同日期，違反 README 宣稱的共同 ledger，也無法把排名差異純粹歸因於 proxy 選擇。[K1704.py:528](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/K1704/K1704.py:528)、[K1704.py:674](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/K1704/K1704.py:674)、[README.md:18](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/K1704/README.md:18)。應先建立並固定六個 target × 三模型共用的 OOS 日期 mask，記錄日期/hash，再交給所有 QLIKE、DM、MCS。

2. **快取沒有對當前 raw bytes 做失效驗證。** cache load 路徑沒有接收 `source_dir`，也不重新列舉或雜湊 raw files；`source_byte_inventory_sha256` 只是再次雜湊 cache 內自帶的 `source_sha256`。raw 檔被修改、替換或刪除仍可正常產生結果，與 README 的 fail-closed/byte-pinned 宣稱不符。[K1704.py:301](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/K1704/K1704.py:301)、[K1704.py:357](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/K1704/K1704.py:357)、[K1704.py:649](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/K1704/K1704.py:649)、[README.md:29](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/K1704/README.md:29)。

3. **README 已提出未經本次 rerun／認證支撐的精確科學結論。** HEAD 沒有 tracked results 或 `review_verdict.json`，但 README 已宣稱 winner、MCS singleton、DM 數字與最終分類；這些正是題目要求不得採信的 pre-review outputs。[README.md:57](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/K1704/README.md:57)。rerun 與認證前應移除或明標為未驗證 provisional output。

高嚴重度：

4. **評分會靜默刪除失敗 forecast。** 非有限 forecast 被 `common` mask 排除，沒有要求預期 OOS 全覆蓋、各 target 樣本數相同，也未輸出實際評分日期或 ledger hash；模型故障可能偽裝成較小樣本。[K1704.py:528](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/K1704/K1704.py:528)。

5. **沒有 K1704 專屬測試。** 至少缺少：08:45/13:45 精確端點與稀疏日的 1/5/10 分鐘 grid；HAR/GJR refit與非 refit origin 對齊；修改 `actual[t:]` 不影響 `t` 權重／尺度；raw mutation 使 cache fail closed；六 target 共用 ledger；MCS 收到同長度、同日期、有限 loss matrix。[K1704.py:97](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/K1704/K1704.py:97)、[K1704.py:374](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/K1704/K1704.py:374)、[K1704.py:406](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/K1704/K1704.py:406)。

中嚴重度：

6. **Consensus 有 self-inclusion circularity。** 各 proxy 的可靠度 residual 是相對於包含它自己的同日 cross-proxy median，且 1/5/10-minute RV 共用相同 ticks，inverse-MSE 權重不能視為獨立 measurement-error precision；共同錯誤也無法被識別。[K1704.py:478](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/K1704/K1704.py:478)。這不構成 lookahead，但應明確列為限制，最好增加 leave-one-proxy-out sensitivity。

7. **DM 被標成 HLN，但 canonical helper 實際是 Newey–West HAC DM，沒有 HLN small-sample correction。** helper 使用正確 actual/predicted QLIKE、正確 loss-difference sign，且 h=1 至少 lag 1；問題是輸出名稱與 README 方法標籤過度描述。[K1704.py:545](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/K1704/K1704.py:545)、[K1704.py:561](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/K1704/K1704.py:561)。

其餘核心路徑靜態檢查正常：HAR/EWMA/GJR、scale calibration 與 consensus 權重均為 past-only；TAIFEX active-contract/session 建構未見 TX1 roll-gap 污染；MCS 使用 repo implementation、1,000 reps、seed 42；JSON 寫入為解析驗證後原子替換；README 也適當限制 causal、trading 與 latent-variance claims。
