VERDICT: FAIL

reviewed_sha256:
  K1715.py: 133c6f81bc966241f801e387af75a7fb246d2c5836affb748ab769c3e608a9a3
  K1715_results.json: d622e1eba1cd7cb907cb73a51120747eb4af89fc0f796e3f29266947dc0dec17
  reproduce_spec.json: 6e583d5989028c686b668f35e0a739956bdf250ba3bd1946d7d5f0b5321aeb2e

## Science — PASS

- `K1715.py:227-285,844-863` 的預測狀態先於 `y[t]` 更新，且每個 OOS block 僅用 `y[:a0]` 估參數；未發現 lookahead。
- Student-t VaR/ES 映射、Kupiec、Christoffersen、McNeil-Frey、Acerbi-Szekely Z2、pinball 與 FZ0 實作內部一致（`K1715.py:578-763,895-920`）。
- `/head_to_head/{0.01,0.025,0.05}/GAS-t_vs_GARCH-t/fz0_dm/dm_stat` 分別為 `2.3919`、`1.7776`、`1.4268`，均未達 Harvey `|t|>3`；mean loss difference 均略偏 GARCH。NULL／未證明 score-driven 有優勢的結論成立，且 README 正確標為 fail-to-reject，不是等價性結論。
- 四模型共同 undercoverage 與因果機制未識別的限制均由 results 支持。

## Min-NLL / BFGS guard — BLOCKING

Guard 演算法本身正確，選擇也可由輸出稽核：

- `K1715.py:466-475` 依有限且較低的 NLL 選 BFGS 或 NM；`K1715.py:494-520` 再選最低 guarded survivor。
- 268/268 refits 都是 `accepted_method="BFGS"`；`accepted_nll == bfgs_nll`，且 `guarded_polish_gain == nm_nll - accepted_nll >= 0`，未發現欄位不一致。

但 primary results 內的說明與實作、實測結果矛盾：

1. `K1715.py:812-815,1281-1284`（輸出至 `/per_model/*/convergence_summary/note`、`/design/convergence_note`）宣稱 raw BFGS `gtol` failure 會使 guard fallback 至 NM。實作根本不檢查 `res_bfgs.success`；結果亦顯示 `bfgs_success=false` 268/268，卻仍接受 BFGS 268/268。
2. `K1715.py:1286-1287` 宣稱小 `guarded_polish_gain` 表示「already stationary」。若 guard 採用 NM，該值會依建構等於零，因此不能單獨支持 stationary；這也與 `K1715.py:543-546` 的正確警告自相矛盾。

修正時須明確寫成「solver success/status 與 min-NLL 選擇相互獨立」，移除 small gain 單獨證明 stationary 的推論，並一起重生 results/spec/README。

## Reconciliation — BLOCKING

- README 的樣本數、日期、67 次 refit、coverage、DM、loss means、persistence、收斂摘要及 `arch` cross-validation 數字均可追溯至 `K1715_results.json`，未發現數值漂移。
- Snapshot 比較算術已獨立確認：9,456 archived、10,532 new、9,176 common、280 archived-only、1,356 new-only；7,483 個共同數值 leaves bit-identical，無 ranking flip。
- 但 `snapshot_repro_report.md:65-70` 說 optimizer diagnostics 不是實驗所報告的 findings；README 卻在 `README.md:118,170-191` 明確報告並用 `mean_persistence`、`boundary_rate`、梯度、polish gain、multistart reproduction 支持估計可信度。此完整性聲明不成立。
- `snapshot_repro_report.md:279-291` 又宣稱 on-disk verdict「NOT stale」且是有效 round-2 review；它沒有審過本次三個 SHA 所代表的 bytes。這段 review lineage 必須更正。

## Spec provenance — PASS

- `K1715.py:1317-1331` 在 runtime 呼叫 canonical `finalize_experiment()`。
- `src/volpred/research/reproduce_spec.py:313-341` 用同一次 trace 產生 results `code_trace` 與 spec `entrypoint`；兩者皆為 `133c6f81…`、64,544 bytes，與 disk 一致。
- Input snapshot 亦正確 pin 為 SHA-256 `d5dae218deed40ea38969fb295c72a84f9e3711a6bf2837ea473bf7093174fec`、170,960 bytes。
- 先前「事後手寫 spec」的 provenance 缺陷已對本次 bytes 關閉。

## Comparator closeout — BLOCKING

`science()` 沒有涵蓋所有實際報告的 findings，因此 comparator 對其聲稱的契約仍 fail-open：

- `compare_to_archived.py:57-64,109-119` 一律排除 `/fit_log/`、`/convergence_summary/`、`optimizer_success_rate`、`boundary_rate`、`mean_persistence`。
- 這些欄位已在 `README.md:118,170-191` 被正式報告並用於支持 estimator validity。
- 具體反例：刪除 `/per_model/GJR-t/convergence_summary/multistart_reproduce_frac/min`（README 第 190 行報為 `0.33`），comparator 仍於 `compare_to_archived.py:231-235,314` 回傳 exit 0、`verdicts_reproduced=true`。
- 因此現有「刪 diagnostic leaf 仍綠燈」negative control 實際證明了分類漏洞。
- 280 個舊 `nm_to_bfgs_improve` pointers 確實全數映射到新 `guarded_polish_gain`，且 280/280 bit-identical；目前 pair 沒有實際遺失值，但這不能修復 fail-open predicate。

修正時應建立明確的 published-claim surface，至少加入 README 所引用的收斂欄位，並新增刪除 README-reported convergence value 必須失敗的測試。

## Residuals — NON_BLOCKING

- `build_readme.py::_assert_convergence_schema()` 無 repo-level test：本次 artifacts 一致，故非阻擋；仍應補測試。
- New-only science pointer 只報告、不使 gate 失敗：本次 `only_new_science=0`，故非阻擋。
- `K1715.py:114-115` 與 spec comparison reason 仍只寫 verdict “moves”，漏寫 “vanishes”：屬語意不足但非反向錯誤。
- NM NLL 為 infinity、BFGS 有限時可能輸出非標準 JSON `Infinity`；本次 268 筆皆有限，屬 robustness residual。

## Blocking defects

1. 修正 results 內錯誤的 BFGS-failure/fallback 與 small-gain/stationarity 說明，並重生 linked artifacts。
2. 修正 comparator claim-surface，使 README 已報告的收斂 finding 消失時必須 fail。
3. 更正 `snapshot_repro_report.md:279-291` 的 stale-verdict／round-2 lineage。

寫入狀態：未能建立 `storage/ops/codex_reviews/k1715_recert3_verdict.md`；目前 sandbox 為 read-only，指定檔案寫入遭系統拒絕。
