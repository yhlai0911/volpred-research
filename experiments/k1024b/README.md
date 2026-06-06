# K1024b: A4f Refit Frequency Sensitivity with Tau-Alignment Fix

**[提出: Paper 9 alignment audit follow-up, 執行: Codex]**

## 動機

`experiments/paper9_a4f_alignment_audit/README.md` 確認 `K1024` 的 A4f recursion 沿用了 `K1056` 同型問題：

- 原寫法：`u_{t-1} = r_{t-1} / sqrt(tau_t)`
- 修正後：`u_{t-1} = r_{t-1} / sqrt(tau_{t-1})`

K1024 的主題不是單一 full-OOS 比較，而是 **refit frequency sensitivity**。  
因此 K1024b 的目標是重跑原本 5 個 refit 頻率：

- 5d
- 21d
- 63d
- 126d
- 252d

並與 `K1024` 原始結果逐頻率比較，確認：

1. A4f 是否仍在所有頻率勝過 GJR
2. 63-day refit 的結論是否仍穩健
3. tau-alignment 修正對 QLIKE / DM 幅度的影響有多大

## 本輪完成內容

- 建立 [k1024b.py](./k1024b.py)
- 改成使用本地 snapshot：`paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv`
- 修正 in-sample / filter / OOS forecast 的 `tau_prev` 對齊
- 新增 `comparison_to_k1024` 輸出區塊，逐 refit 頻率對照原實驗
- 改寫輸出檔名為 `k1024b_*`
- 已準備給 `compute_queue` 執行

## 狀態

**Status: queued for compute worker**

此任務依專案規則屬 heavy compute，不在 hourly fire 直接全量執行。  
本輪完成標準是：

1. 腳本可執行
2. 比較邏輯已寫好
3. compute queue job 已入列

待 compute worker 跑完後，下一輪 follow-up 應檢查：

- `k1024b_results.json`
- 63d 主結論是否保留
- `comparison_to_k1024.freq_63`
- 5 個頻率中有無 direction flip
- 是否需要修 Paper 9 / footnote 口徑

## 預期輸出

| 檔案 | 說明 |
|---|---|
| `k1024b.py` | 修正 tau-alignment 的完整 refit 腳本 |
| `k1024b_results.json` | compute 完成後產生 |
| `k1024b_qlike_vs_frequency.png` | compute 完成後產生 |
| `k1024b_dm_vs_frequency.png` | compute 完成後產生 |
| `k1024b_runtime_vs_frequency.png` | compute 完成後產生 |

## Follow-up brief

compute 完成後應優先回答：

- `freq_63` 的 A4f vs GJR 是否仍為 Paper 9 robustness PASS
- `A4f advantage all frequencies` 是否仍成立
- A4f QLIKE spread 是否仍然極小
- 修正後 magnitudes 與 `K1024` 相差是否足以改變原 README / article 敘述
