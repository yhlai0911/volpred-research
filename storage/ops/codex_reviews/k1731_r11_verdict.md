VERDICT: FAIL

無法寫入 `storage/ops/codex_reviews/k1731_r11_verdict.md`：目前 workspace 是 read-only，唯一寫檔嘗試遭 sandbox 拒絕。

審查結論：

- Claim surface — BLOCKING
  - ES 使用 iid bootstrap，未處理時序相依：`experiments/k1730/k1730_scoring.py:166-188`。
  - ES family 未做 multiplicity correction；Holm 後 GEV-HAR、GARCH-t、SSVS 的 95% p 值皆為 `0.062`，不支持 `README.md:419-420,441-446` 的全面 rejection。
  - Frozen F1 aggregate 說 Route 1 未跑：`k1731_f1_nested_inference_results.json:107-109,207-212`，但 README 報告未凍結的 rolling 結果：`README.md:1191-1204`。
  - Source docstrings 仍錯稱兩臂只差 target／arm A 是 quick mode：`k1731_data.py:3-5,27-34`、`k1731_gevreg_midas_ssvs_returns.py:10-19`。

- Rev12 scope — PASS
  - 兩個 diff 僅加入 `root` threading 與 `relative_to(root)`；call sites 保持雙參數，未改 detection、verdict 或 threshold。

- Freeze coverage — BLOCKING
  - 漏凍結四個 `f1/*.json`、corrected regression baseline、實際執行的 k1730 data/model/scoring scripts、DQ implementation 與多個資料輸入。
  - 43/43 hash integrity 成立，但不是完整 claim dependency surface。

- Residual divergence — PASS
  - `audit_nested_dm_misuse.py` 與 main 的差異僅為註解、docstring 和 formatting；偵測邏輯等價，不污染 K1731 claim。
