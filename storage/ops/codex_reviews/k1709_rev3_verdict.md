REVIEWED_COMMIT: f3f9d3034b1a5cc4c42cacae1528178e798d08d1
VERDICT: FAIL

## BLOCKING DEFECTS

1. `render_readme.py:710-714` / `README.md:232` — 最終「Does say」摘要仍宣稱「No robust incremental predictive evidence was found」，未限定為 `UNCONDITIONAL`。`k1709.py:1039-1052` 實際只授權 OOS 樣本上的平均 QLIKE loss differential；跨 regime 正負互抵的條件式效果並未檢定。README 第 38 行的遠端 blanket disclaimer 不足以保護這個刻意可獨立引用的摘要。

2. `k1709.py:1843-1845,1987-2020` / `render_readme.py:701-743` — rev3 宣稱所有 claim sentences 都只由 `build_verdict_basis()` 產生，但 renderer 仍是第二個 claim 作者，且完全位於 `--relabel` invariant 之外。`test_k1709.py:804-844` 只驗證 renderer 所需 keys，未驗證 claim parity。這使同一類 overclaim 可在 invariant 全綠時復發。

3. `k1709.py:2673-2681,2712-2713,2728` — standalone 圖表仍輸出 `GW z`、`Giacomini-White on QLIKE`、`Giacomini-White z` 與 `power of the GW gate`，正是 rev2 判定不可接受的無限定 nomenclature。程式只實作 unconditional GW/DM special case；README 第 38 行也無法限定獨立流通的 PNG。Fig. 3/4 自 `c97d690c` 後未重建，且與 `README.md:224-225` 的「unconditional GW/DM」描述矛盾。

4. `k1709.py:2586,2605` — rev3 抽出 `build_verdict_basis()` 後，`main()` 仍引用已不在其 scope 的 `margin_pct` 與 `claim`。預設執行路徑會在寫出 JSON 後先於第 2586 行拋出 `NameError`；第 2605 行也同樣不可達且未定義。Frozen estimates 未受影響，但 rev3 並非可成功結束的 relabel-only refactor。

## REVIEW

### 1. Claim surface

`gw_unconditional_dm()` 的新 docstring、`README.md:30-42` 與 `k1709_results.json:8924-8953` 已正確限縮為 unconditional average-loss inference，也明確承認 conditional/state-dependent predictive ability 未檢定。

但最終摘要和圖表仍保留無限定說法，因此 frozen claim surface 尚未完全收斂。研究問題本身可以廣泛發問；結論句與 standalone 圖表標籤則必須就地限定。

此外，靜態閱讀發現上述兩個未定義名稱；不需、也沒有重跑 vendor study 即可確定。

### 2. Numbers

沒有任何研究數字移動。

我遞迴比較 `c97d690c` 與 frozen rev3 JSON 的每個非字串 leaf，包含 2,248 floats、1,361 ints、768 booleans、6 nulls，共 4,383 個；path、型別與值的差異數為 0。README 的估計表格也未改變。

五個受審檔案雖位於後來的 worktree HEAD `4e9a4c207`，但其 bytes 與 `f3f9d303` 完全相同。唯一新增的 executable numeric literal 是 `k1709.py:2016` 的 `indent=2`，只是 JSON 排版，不是資料、估計或門檻。

需精確指出：`--relabel` 所稱「byte-identical」實際是 parsed-value equality，不是 raw-byte/hash comparison。這次實際 artefact 的數值確實未動，但 guard 的描述比實作更強。

### 3. rev2 四個 non-blocking items

1. Bound monotonicity：未修、未揭露。`k1709.py:1174-1185` 仍以「`z(m) is increasing in m`」進行 binary search，未驗證完整 rejection set。Frozen bounds 在 rev2 已另行確認有效，所以仍列 non-blocking。

2. Fig. 2 event-day shift：未修、未揭露。`k1709.py:2635-2655` 使用 panel 中已 lagged 的 `z`，卻標示 `0 = flow date`；day zero 實際晚 raw flow date 一天。不餵入推論。

3. Live-rerun invariance promise：未修。`render_readme.py:669-679` / `README.md:213` 仍保證 h=1 statistics、verdict、counts 與 bound「stay put」。新增觀察或 vendor revision 都可能改變它們；這也直接牴觸 `k1709.py:1847-1850` 新增的 later-sample 警語。

4. Vendor vintage not archived：未修，但已在 `k1709.py:1847-1853` 明確承認。README 仍未完整揭露，且 `README.md:213` 所稱僅靠 RV `date_max` 就能讓每個數字「always be traced」仍過強；日期上限不是 Farside point-in-time snapshot。

### 4. Nested-DM ratchet

Auditor 的 two-role model 是錯的。GW (2006) Sec. 3.4 明確定義 fixed-memory forecasting methods 的 unconditional test：以 HAC 標準化平均 loss differential、標準常態參考分布，且統計量與 DM 一致；conditional test 才需要 instrument vector、矩陣 covariance、Wald 與 chi-square。參見 [Giacomini and White (2006), Sec. 3.4](https://www.eco.uc3m.es/~jgonzalo/teaching/PhdTimeSeries/GiacominiWhite.pdf)。

因此不應把科學文字改回模糊的「GW gate」來取悅 lexical scanner。真正需要的是第三角色，例如 `primary_unconditional_dm_fixed_memory`。

但這不能成為自填 marker。Ratchet 接受第三角色前，至少必須要求：

- Pair/cell-level、versioned machine-readable manifest，而非 file-level escape hatch；逐一列出 nested relation、loss、horizon、claim scope 與 gate sink。
- 每個 claim-bearing cell 的 runtime provenance 證明整個 forecasting method 都是固定上限記憶：base/aug 使用相同 fixed window、complete-case mask、training dates、embargo；任何 upstream feature estimator 也不得 expanding。
- Statistic provenance：paired unadjusted loss differential、HAC estimator/bandwidth、finite positive LRV、normal reference及明確的 unconditional average-loss estimand。
- Gate wiring 證明只有通過上述證據的 records 可 `feeds_gate=true`；`bounded_memory=True` 或註解不可自我認證。
- Reader-facing claims 必須就地寫明 unconditional，並揭露 regime-offsetting conditional effects 未被排除。
- Repo 外部的獨立 adjudication receipt，綁定檔案 SHA、cell manifest hash 與 reviewer；任何 bytes 漂移即失效。
- Adversarial fixtures：偽 marker、mixed fixed/expanding cells、fixed final regression 但 expanding preprocessing、conditional wording、以及 file-level marker 洗白其他 cells，都必須繼續 FAIL。

目前 `test_k1709.py:486` 要求 `diagnostic_with_cw_primary` 本身也是錯誤角色；同檔 `:493-495` 明確顯示 GW/DM object 才 feeds gate，而 Clark-West 為 false。這個第 62 項失敗不是 K1709 統計設計的新反證，但在 auditor 的獨立修正完成、ratchet 與 experiment test 同步轉綠前，仍應 operationally 阻擋 merge。

### 5. Renderer hardcoded prose

(a) 是 blocking defect。第 38 行的 blanket disclaimer 在完整線性閱讀下提供背景，但不能替代最終「Does say」摘要的就地限定。

(b) `Does not say` 應新增獨立 bullet：conditional/state-dependent predictive ability 未檢定；跨 regime 互抵的效果不被排除。

(c) 雙作者且只有一方受 invariant 保護，本身就是 merge 前必須關閉的設計缺陷。Summary、limitations 與圖表標籤應由同一 canonical claim object 渲染，並新增 frozen-render parity regression test；單獨補 line 710 的一個字不足以修復此設計。

## SHA256

32e2896f9b2b9de0f58a0eb23e513c144b23970577c40c87dbf8def182bfe07b  experiments/k1709/k1709.py
2ad0d450c53906fc5c29a1e33d592792a79bfe73eade35cc14487a934aa5b0dc  experiments/k1709/render_readme.py
3716836db76488defbc0ccd151a98a9d8cad228cf93b19435fe9591ca94c2509  experiments/k1709/README.md
787baf5136c282f8810c07cbf983dc20560c5b090fad589db3f64ad64413389f  experiments/k1709/k1709_results.json
94ed7c3fe352b74027c52bd40d6e1aa1dc921a638edc9d5ce8fbd91df7f996f9  experiments/k1709/test_k1709.py
