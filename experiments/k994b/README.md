# K994b: Cross-Asset Validation with Tau-Alignment Fix

**[提出: Paper 9 alignment audit follow-up, 執行: Codex]**

## 動機

`experiments/paper9_a4f_alignment_audit/README.md` 確認 `K994` 的 A4f recursion 沿用了 `K1056` 同型問題：

- 原寫法：`u_{t-1} = r_{t-1} / sqrt(tau_t)`
- 修正後：`u_{t-1} = r_{t-1} / sqrt(tau_{t-1})`

K994 的主題是 **4 資產 cross-asset validation**，不是單一市場的 robustness check。  
因此 K994b 的目標是用相同資產組合重跑：

- `QQQ`
- `EEM`
- `GLD`
- `0050.TW`

並與 `K994` 原始結果逐資產比較，確認：

1. A4f 是否仍在 4 個資產上方向性優於 GJR
2. `QQQ-only significant` 的原結論是否仍成立
3. tau-alignment 修正對各資產 QLIKE / DM 幅度的影響有多大

## 本輪完成內容

- 建立 [k994b.py](./k994b.py)
- 改成使用本地 snapshot：
  - `paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv`
  - `paper/garch-x-vix/data/gld_vix_gvz_2000-2026.csv`
  - `paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv`
- 修正 in-sample / filter / OOS forecast 的 `tau_prev` 對齊
- 新增 `comparison_to_k994` 輸出區塊，逐資產對照原實驗
- 改寫輸出檔名為 `k994b_*`
- 已準備給 `compute_queue` 執行

## 狀態

**Status: queued for compute worker**

此任務依專案規則屬 heavy compute，不在 hourly fire 直接全量執行。  
本輪完成標準是：

1. 腳本可執行
2. 比較邏輯已寫好
3. compute queue job 已入列

待 compute worker 跑完後，下一輪 follow-up 應檢查：

- `k994b_results.json`
- `comparison_to_k994`
- `QQQ` 是否仍為唯一 Harvey 門檻顯著資產
- 是否有任何 asset 出現 direction flip
- 是否需要修 Paper 9 / cross-asset 敘述口徑

## 預期輸出

| 檔案 | 說明 |
|---|---|
| `k994b.py` | 修正 tau-alignment 的完整 cross-asset refit 腳本 |
| `k994b_results.json` | compute 完成後產生 |
| `comparison_to_k994` | results.json 內逐資產比較區塊 |

## Follow-up brief

compute 完成後應優先回答：

- `QQQ / EEM / GLD / 0050.TW` 是否仍全部方向性優於 GJR
- `QQQ-only significant` 是否維持，或有新增/消失的 Harvey 顯著資產
- `A4f vs A4` 是否仍在所有資產上不顯著
- 修正後 magnitudes 與 `K994` 相差是否足以改變原 README / article 敘述
