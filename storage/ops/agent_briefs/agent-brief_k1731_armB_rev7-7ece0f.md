# K1731 arm B — rev7 bounded remediation（回應 Codex rev6 FAIL）

**Model**: claude-opus-4-8 / xhigh (per model_router)
**Worktree (你的 cwd)**: `.claude/worktrees/dispatch-slot-1-bd00f90a-k1731`
**上游裁決**: `storage/ops/codex_reviews/k1731_armB_rev6_verdict.md`（canonical repo 裡；先完整讀完）

rev6 得到 `VERDICT: FAIL`，freeze manifest 全部 hash 相符 —— 也就是**這是對目前 bytes 的裁決，不是沿用舊輪**。
B2/B3/B4/B6/B7 + 四項 structural check 全 PASS，**不要動它們**。你的 scope 只有下列 4 條 blocking issues，
逐條做完、逐條自我驗證，然後重新 freeze。**這是收斂輪，不是重做輪。**

主線程已對 4 條 blocking issue 逐一 bytes 核對，確認全部屬實（不是 Codex 誤判），不要再花時間辯論其成立性。

## 必守邊界（違反即本輪作廢）

- ❌ **不得改動任何 estimated number**。rev6 structural check 1 已證實 rev5 primary artifact / estimation
  script / models / scoring 四者 hash 自 round 5 起未動 —— 這個性質必須在 rev7 之後仍成立
  （estimation script 只准改 docstring 文字，見 B5；改完 hash 會變，這是預期內，但**任何 estimate 不得移動**：
  改完必跑 `k1731_regression_check.py` 證明 leaf values 不變）。
- ❌ **不得手改 primary JSON**。B1b 必須改 canonical generator `k1731_finalize_report.py` 再由 finalizer 重生。
- ❌ 不得合併 worktree、不得寫 `knowledge.json`、不得發文章、不得動 `next_tasks.json`。
- ❌ 不得跳過 freeze。做完必產出新 manifest（見最後一節）。
- ❌ 不得為了讓 detector 通過而放寬 detector（B4 是要它**抓到** K1731，不是繞過）。

## Blocking issue 1 — README §3.2 的 “bounds” / “95% CI” 措辭（B1a）

現況（已核對）：
- `experiments/k1731/README.md:188` 標題仍為 `### 3.2 Diebold-Mariano — bounds, not just p-values`
- `README.md:195` 表格欄位標 `95% CI (% of benchmark loss)`，且 nested 那列
  `**SSVS vs GEV-HAR** ... **[−0.74, +4.41]**` 仍是粗體呈現。

問題：SSVS vs GEV-HAR 是 **nested** 比較（arm B 的 GEV-HAR 由 macro coefficient mask 歸零而來，是限制模型），
raw DM + HAC 在 nested null 下沒有主張的常態極限（West 1996；Clark–McCracken 2001），
expanding window 也讓 Giacomini–White (2006) 的 fixed-memory 架構不適用。沒有常態極限 → 那個區間不是有效的 95% CI。

要做：
- §3.2 標題移除 “bounds” 推論措辭。
- 表格欄位改成明確的 diagnostic 措辭（例如 `HAC diagnostic interval (% of benchmark loss；非 95% coverage 保證)`）。
- nested 那一列必須就地標註它不具 coverage 保證；取消把它當結論的粗體強調（其他非 nested 列若要保留 CI 語義，
  必須在同段說明「僅非 nested 比較適用」）。
- 全 README 掃一遍 `bound` / `CI` / `信賴區間` 的殘留推論措辭，一併收斂。

## Blocking issue 2 — primary JSON `cross_arm_comparison` 仍有無 caveat 的 OOS 推論（B1b）

現況（已核對，`k1731_gevreg_midas_ssvs_returns_results_corrected_rev5.json` 的 `cross_arm_comparison`）：
- `what_cannot_be_said` 仍寫 arm A 的 `t=+2.13 (p=0.033)` 並斷言 macro model「in arm A it **demonstrably does not**」。
- `correct_reading` 仍把兩臂寫成已證明的 OOS null（"fails to improve OOS tail forecasts in BOTH arms"），
  沒有 nested-DM caveat，也沒提 arm A 全部數字來自 quick mode。

問題：arm A 用的是同一個 mask + expanding window + raw DM，屬同一缺陷類 —— 它的 `t=+2.13` 同樣不能當作
「證明不改善」的推論基礎，只能當方向性 diagnostic。

要做：
- 修 canonical generator `experiments/k1731/k1731_finalize_report.py`，讓 `cross_arm_comparison` 的敘事：
  (a) 把 arm A raw DM 降級為 **diagnostic direction**，移除 “demonstrably” 等已證明措辭；
  (b) 明確加上 nested / expanding-window / arm-A-quick-mode 三項 caveat；
  (c) `correct_reading` 改成「兩臂都**沒有觀察到** OOS 改善，且兩臂的檢定都不足以支持強 null 主張」這一層。
- 再由 finalizer 重生 artifact（**不要手改 JSON**），並確認 `is_primary` / `do_not_cite` / `superseded_*`
  provenance invariant 仍成立（rev6 structural check 3 的性質）。
- 跑 `k1731_regression_check.py` 證明只有 narrative 欄位變動、estimates 全部不動。

## Blocking issue 3 — estimation source module docstring 的 attribution 殘留（B5）

現況（已核對）：`k1731_gevreg_midas_ssvs_returns.py:4-5` 仍寫
`Arm B holds the entire engine fixed` —— 與 README 已揭露的三項未控制差異（macro set / GARCH information set /
estimation mode）直接衝突。

要做：
- 改成不宣稱同一 engine 的措辭（Codex 建議：`reuses the same model implementation while these settings differ`），
  並就地列出那三項差異。
- README 的 “six things” 硬編號與其自然列舉數量不一致 → 移除硬編號，改為 `enumerated shared constructs`。
- **只准改註解/docstring 文字**，一行程式碼都不准動；改完跑 regression check 證明數字不動。

## Blocking issue 4 — nested-DM detector 的 false negative（Added finding, BLOCKING）

現況（Codex 實跑 detector channels 確認）：explicit nested regex=0、base/augmented prose=0、nested AST=0、
raw-DM AST=3、`scan_file(...)` 回 `None`。根因：`scripts/audit_nested_dm_misuse.py` 的 AST detector 只認得
paired identifiers（base/aug、baseline/augmented、restricted/unrestricted）與 subset construction，
**沒有 coefficient-slice-zero mask channel**；沒有 nesting evidence 時 `scan_file` 在 raw-DM 分類前就 return
（見 detector:204 `_nested_ast_evidence`、detector:2553）。

所以 K1731 的 gate PASS 是 false negative，193-site baseline 至少少算一處，其他 mask-based sites 的漏算數未知。

要做：
1. 新增 **coefficient-mask nesting AST channel**，至少涵蓋「對 coefficient array/slice 指派為零，
   而後以 restriction / active / mask argument 傳入 fit」這個 pattern（K1731 的 `:163` 就是實例）。
2. 加 **positive test（K1731 這個 pattern 必須被抓到）+ negative test（不可把一般 slice 指派誤報）**，
   放在 detector 既有的測試位置（先找 repo 內既有測試檔慣例，沒有就依 repo 慣例新建）。
3. **重新掃描全 repo**，更新 frozen baseline，並在輸出/報告中明確記錄新舊 site 數差異
   （少算了幾處、分別在哪 —— 這是本輪對外最有價值的產出，不要只寫 total）。
4. 確認 K1731 **不再**得到 false-negative clearance。

⚠️ detector 是 repo-level 工具（`scripts/` 底下），不是 K1731 私有 —— 改它會影響其他 site 的 gate 結果。
若重掃後有其他 site 由 PASS 翻 FAIL，**不要順手修別人的 site**，只要在 report 列出清單交回主線程排工。

## 完成後必做（本輪出口）

1. 全部 4 條做完後跑：`k1731_regression_check.py`、`k1731_armB_verification.py`、`k1731_es_mixture_check.py`，
   三者都要通過，並把輸出摘要寫進 report。
2. README §10 追加 **Round 6 disposition**（逐條寫 B1a/B1b/B5/detector 怎麼處理、哪些 rev6 PASS 項未動）。
3. 產出新 freeze manifest `storage/ops/codex_reviews/k1731_armB_rev7_freeze.txt`
   （格式照 `k1731_armB_rev6_freeze.txt`：標頭四行註解 + `sha256  filename`，scope 同一目錄，
   檔案清單與 rev6 一致；若因 finalizer 重生而有檔名變動，在標頭註明）。
4. 產出結果檔 `experiments/k1731/k1731_armB_rev7_remediation.json`，內容至少含：
   `{blocking_issues: [{id, what_changed, files, self_verification, evidence}], regression_check: {...},
     detector: {old_site_count, new_site_count, newly_flagged_sites: [...], k1731_now_flagged: true},
     freeze_manifest: "storage/ops/codex_reviews/k1731_armB_rev7_freeze.txt", ready_for_codex_round7: true|false}`
   —— `ready_for_codex_round7` 必須誠實：任一條沒收斂就填 false 並說明。
5. **停在這裡**。不合併 worktree、不寫 knowledge、不動任務池。下一輪由主線程送 Codex round 7。

誠實 > 一切：做不到的條目寫做不到，不要用措辭讓它看起來過了。rev6 就是因為「prose 修了大半、
表格與 primary narrative 沒跟上」才被判 FAIL —— 這次要的是**同一句話在 README / JSON / docstring 三處一致**。
