# 2026-08-02 — NFP T-7 資訊集、重疊對照組與讀者結論更正

**Class**：F（Timestamp / provenance / information set），兼 G（DM-HAC / 方法論）。  
**Task**：`assign_706482a8`。  
**狀態**：`contained`。研究與讀者面已止血並回讀；尚待 exact-path Git adoption、post-commit CI parity 與 orphan reaper 證明孤兒已正式退役，才可改為 `root_cause_fixed_and_verified`。

## 1. 證據化症狀

2026-07-31 producer 在 `experiments/nfp_20260807_t7/` 留下未受 Git 擁有的結果、事件表與圖，orphan reaper 超過 TTL 後持續 held。已發佈文章 `mile_84e3be0a` 使用：

- 2026-07-30 VIX 17.09 作為「T-7」條件水位；
- 過寬 exclusion 所得 controls n=1,485，並以 iid Welch p=0.342 推論；
- 僅有事件日描述統計，沒有事件日對照組與正式檢定，卻延伸出「不確定性解除／反應穩定」。

當前 canonical result 與 runtime trace 回讀證明，研究的第七個交易日資訊集應是 2026-07-29 VIX 20.6599998474；2026-07-30 是最新 snapshot，但對這個研究角色是 trading-day T-6。舊結論因此必須撤回，不能只更換數字。

## 2. 根因層級

1. **詞彙／資訊集契約**：event scheduler 的 `T-7` 是發佈前七個日曆日的文章階段；實驗 feature 的 `T-7` 是往前數第七個交易日收盤。舊 producer 與文章把兩個同名、不同 domain concept 合併，又把更新的 T-6 snapshot 當成 T-7 feature。
2. **方法論**：rolling control windows 相互重疊，iid Welch 的獨立性假設不成立；對照組 exclusion 也與文章宣稱的 exact-overlap interval contract 不同。
3. **產物擁有權**：原 producer 沒有在同一個 Git-owned transaction 中交付 code、pinned inputs、results、spec 與 review receipt，令研究只能來自無主字節。

## 3. 底層重構

- 建立 network-free canonical entrypoint `experiments/nfp_20260807_t7/nfp_20260807_t7.py`，將 VIX snapshot-through 與 target T-7 as-of 分成兩個明確欄位。
- 重建 exact-overlap controls，對重疊日報酬差使用 Newey–West HAC，並保留 lag 6/22/60 sensitivity 與 regime-wise Holm correction。
- 以 `finalize_experiment()` 在同一次 run 產生 result + `reproduce_spec.json`，綁定 code/input/result hashes。在第二次方法更正前，先以 `preserve_gate_blob.py` 完整保留上一版 entrypoint，避免事後重建證據。
- 舊 `nfp_t7_*` 三件產物只作 read-only forensic evidence，每件以固定 SHA-256 受 regression test 保護；舊 generator wrapper 被呼叫時會主動委派 pinned canonical entrypoint，只改寫 canonical results/events/controls/figure/spec。只有 wrapper 內的 `LEGACY_SOURCE_UNVERIFIED` 原生產者文字是 inert，wrapper 不會復活舊演算法或覆寫 legacy artifacts。
- 文章更正只走 canonical `publish_draft.py --update --sync-supabase` gateway，不手改線上資料庫。四筆 errata action 依次修正 HAC/provenance、series identity、information set 與結尾殘留舊水位。

## 4. 回歸驗證

- canonical T-7 current state：2026-07-29，VIX 20.66，regime 20–25；最新 2026-07-30 snapshot 被明確標示為 T-6。
- event n=191；exact-overlap control n=2,062；mean difference +0.830pp；HAC(22) p=0.583，95% CI [-2.137, +3.798]；四個 regime 經 Holm 後最小 p=0.659。結論限定為「未偵測到」，不宣稱效果等於零。
- entrypoint SHA-256 `02a1f78de18f1e4360e9b40de0d0faa2764aca3d299f5a4bea3d6ae3ac3d86eb`；result SHA-256 `2ea19edac3549f1f58fbedf7ff15d8fa487ceffba6f1d5327b6ab51208e9254f`，runtime trace identity 一致。
- legacy result/events/figure SHA-256 分別為 `7658a1610c200840f76699e62e1d38d574930f3956710647e1398b2e1991a315`、`be020d5230a61c6b9b56b5bd817a1cca0d2f8fb07b0560a6554ea18f716a70d3`、`266ca0f29518c43d3fd6bc0ef041e7c6572eb64b2e30533d0adb53c5ed54a728`。
- focused regression suite 172 passed；strict artifact/result-identity gate PASS；4 methodology gates PASS；Ruff PASS；article-series drift=0；anti-AI gate PASS。

## 5. 讀者面與下游 acknowledgement

`https://volpred.zeabur.app/v3/reports/mile_84e3be0a` 實際 HTTP 200 回讀，可見新標題、7 月 29 日 VIX 20.66、「沒有事件日對照組」與 T-7 起點水位限定；不再出現「7/30 還有七個交易日」、事件日穩定推論，也不再以 VIX 17 作結尾。Mirror 與 Supabase sync 均回報 ok，feed-sync 已 acknowledgement。

## 結案條件

本 entry 不因「線上已改」就宣稱完成。只有下列全部回讀後才能改為 `root_cause_fixed_and_verified`：

1. exact-path locked commit 將 code、pinned inputs、results/spec、tests、draft/feed/series 與本記錄作為同一可稽核變更集落地；
2. committed tree 上的 CI-parity regression、artifact gate、methodology gate 與 reproduce check 全綠；
3. `reap_orphan_deliverables.py --json` 回讀 `experiments/nfp_20260807_t7` 不再 held；
4. task-pool completion receipt 將 `assign_706482a8` 結束為 succeeded，且不藉由刪除產物或復活 legacy runner 收尾。
