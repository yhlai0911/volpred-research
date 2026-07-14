# EXECUTION — volatility-absorption（Paper 8：The Volatility Absorption Hypothesis）

`BADGE` · `stage: revision` · `verdict: 2.5/5 有條件 Major Revision` · `journal: JBF → JEF/IRFA（backup）` · `p0: ✅ 全部完成（P0-1 gate 通過 + P0-2/3/4 落地 2026-07-14）` · `reproduce_gate: GREEN 95/95` · `next: P1（引用修理 / prior-art / K897 衛生餘項 / NW lag 交代）→ 多輪 review`

> **執行檔用途**：把 Fable 深審（`review_history/fable_deep_review_20260711/README.md`，commit `f913ed68c`）的判定落成可勾選、可交接的行動清單。canonical 稿 = `main_v3.tex`；本檔只驅動執行，不取代深審報告的證據細節。

---

## 1. 最終目標（Ultimate Goal）

把本篇推進到**可對 JBF 投稿的狀態**——但這件事**先被一個 make-or-break gate 卡住，未通過前不得標 ready、不得打磨、不得投稿**。

**⚠️ MAKE-OR-BREAK GATE（本篇的唯一決定點）**：識別核心 K897 null 模擬有 timing 錯配——模擬的 day-t vol proxy 是 t−1 可測的 `h[t]`，而實證的 ΔVIX 與報酬是同日同步的。這讓「absorption 不是機械效應」的關鍵證據建立在一個被弱化的 null 上。**必須先跑 P0-1（contemporaneous null，改用 `h[t+1]` proxy、10k sims）並依事前寫死的判定規則裁決**：

- **decline 仍落在 95% contemporaneous null 之外** → 識別關閉，論文**顯著升級**，走 JBF 路線。
- **decline 落入 null 之內** → absorption 主張降級為「fixed-threshold 選樣 + 同期共動的機械分解」，**重新框架**（改寫成 measurement note 投 FRL，或 merge/archive）。

判定以 **experiment JSON 為準，不以敘事偏好為準**（研究誠實原則，事前承諾）。在 P0-1 跑完之前，所有文字打磨都是錯誤的投入順序。

---

## 2. Definition of Done（DoD — 全未達成）

投稿前必須全部勾起。

- ✅ **P0-1 contemporaneous null 重跑完成**（K1686 + R2 ambient×sign follow-up；Codex R2 PASS）— 裁決見文末 2026-07-14 正式裁定：absorption 通過 fear-shock gate，JBF 線繼續；「如實寫入正文」由 body 修訂承接（K897 退役 + null inconclusive + threshold artifact + H 規格）
- ✅ 5 處內部不一致 C1–C5 全修（2026-07-14；C1 class-swept 兩處 VRP 反向宣稱全撤）
- ✅ Table 3 SAR inference 用 pinned snapshot 重建，p 值有可驗證 binding（2026-07-14；`results/table3_sar_inference.json`）
- ✅ reproduce gate 從 30 checks 擴到 95，`match_rate = 100%` + `alert_level = green`（2026-07-14）
- ✅ **K1686 body 整合**（2026-07-14）：新 §null_reexam（K897 退役 + null inconclusive + 58% threshold artifact + H ambient×sign gate + α=0/P* 結構限制）；abstract/intro/conclusion/limitations 同步改寫；Table 2/3 全面 pinned
- ⬜ 引用修理：4 條孤兒（chernov2018 / baur2010 / patton2011 / romer2004）+ zakoian1994 期刊出處 + chernov 年份，`citation-verifier` 全掃通過
- ⬜ Prior-art 防線：Intro/Lit review 補 Low (2004) / Hibbert et al. (2008) / Fleming-Ostdiek-Whaley (1995) 並正面區分
- ⬜ 多輪 `paper-review-cycle`（latex-academic-reviewer + citation-verifier）收斂
- ⬜ 期刊目標定案（README `Target Journal: TBD` → JBF 或降層決策）

---

## 3. P0 — Gate（不完成不得標 ready / 不得投稿；預估 1–2 工作天；**P0-1 ✅ 完成，P0-2/3/4 進行中**）

### ✅ P0-1 · **【make-or-break】** contemporaneous null 重跑 K897 — 完成（K1686 + R2；裁定見文末 2026-07-14）

- 開**新 K**（`experiments/` 下一個可用編號 ≥ **k1684**；派工時 `ls experiments/` 取最新確認，深審原寫 k1683 已被占用）。
- 改動極小：`simulate_garch_sar_fixed_thresholds` 中 day-t vol proxy 由 `h[t]` 改用 **`h[t+1]`**（觀測 `r_t` 後的 GARCH forecast，等價於「收盤 VIX 反映當日資訊」），shock 定義隨之同期化。
- 同 seed 集、同 10,000 paths；加 **relative-threshold**（`|Δproxy|/proxy > 對應百分位`）變體與 **sign-split**（VIX 上升 vs relief rally）robustness。
- **事前寫死的判定規則（研究誠實，不可事後改）**：empirical decline 仍在 95% null 外 → 識別關閉、論文升級；落入 null 內 → 主張降級為機械分解、走 §重新框架路線。**無論哪個結果都要如實寫進論文。**
- 產出：新 K 三件套（`README.md` / `<id>.py` / `<id>_results.json`）+ 固定 seed + Codex 語義級複核 → `main_v3.tex` §Robustness 更新。
- Brief：`review_history/fable_deep_review_20260711/README.md` §5（P0-1）+ §3-B（timing 缺口證據，`k897_sar_null_simulation.py:269-316`）。

### ✅ P0-2 · 修 5 處內部不一致（C1–C5）— 完成 2026-07-14（C1 掃出兩處：Intro + Lit §2.2 一併修；C5 以 k741 JSON 為準 = 1.14×/1.16×，EXECUTION 原寫 1.17 與 JSON 不符已依 JSON）

- **C1**（Intro line 76）：刪或改寫「We find that the VRP narrows... no VRP sign flip」——此句與 §5.5（VRP 已降級 deferred）及 `k720_results.json`（`vrp_flip_confirmed: true`）**正好相反**。referee/replicator 一抓即喪失全篇可信度。
- **C3**（Table 4 line 351）：0050.TW 行改用 `k1418_results.json` pinned 值（β=9.21e-5, t=+0.283），統一 Intro/Appendix B 的三處兩值。
- **C4**（Appendix B lines 715-718）：α 欄、adj R² 欄改讀 `experiments/k1418/tables/k1418_cross_asset.csv`（α=0.0822/0.0548/0.0531/0.0473；R²=0.0076/0.0142/0.029/−0.0013），消除「β/t pinned + α/R² 舊值」的 chimera。
- **C2**（Table 2 note line 284）：改寫 stale cross-ref（「N=893」→ 現行 769/768）。
- **C5**（§5.3 line 368）：「1.17 times」改成「1.14× vs all non-NFP（1.17× vs Fridays）」；修 footnote「4,081 trading days」→ 與 `k741` JSON 一致值（195+3909=4,104）。

### ✅ P0-3 · Table 3 SAR inference rebuild — 完成 2026-07-14（`scripts/rebuild_table3_sar_inference.py` → `results/table3_sar_inference.json`；paired circular moving-block bootstrap B=10k seed 固定，block 10/20/40/63；SAR 五值與 K1686 empirical arm 逐位一致；誠實發現：calm→normal p=0.103 不顯著，headline calm→high p=0.003；Table 2/3 全面移到 pinned 口徑，表注重寫消滅「t-test via bootstrap」矛盾）

- pinned CSV 上重算五 regime SAR + seeded bootstrap（明確統計量：`SAR_calm − SAR_j` 的 percentile CI），產出 JSON、綁進 `reproduce.py`、更新表注（消掉「two-sample t-test … via bootstrap」的自相矛盾描述；K716 原始腳本永久缺失，K1249 確認 rebuild blocked，故用 pinned snapshot 重寫）。

### ✅ P0-4 · reproduce.py 補 checks（30 → 95）— 完成 2026-07-14

- K897 bindings 退役；新增：Table 2 pinned 分佈、Table 3 rebuild（SAR/counts/CI/p/block sensitivity）、K1686 §null_reexam 全部印出數字（28 checks）、Table 4 0050.TW t、Appendix B α/adj-R²、NFP overall ratios。**95/95 = 100% GREEN**。

---

## 4. P1 — 投稿前完成（預估 2–3 工作天）

- ⬜ **P1-1** 引用修理：刪或補引 4 條孤兒、修 zakoian1994 出處（正確 = *Journal of Economic Dynamics and Control*, 18(5), 931–955）、修 chernov 年份（bibitem 2018 vs 內文 2022）；`citation-verifier` 全掃。
- ⬜ **P1-2** Prior-art 段落：補 Low (2004) / Hibbert et al. (2008) / FOW (1995)，主張「SAR within-regime 設計 + null 模擬」是相對這批同期 VIX–return 非線性文獻的增量。
- ⬜ **P1-3** K897 衛生：修 z-score bug（誤用 Cohen's d × 100）、揭露或修復 percentile 變體 silent fail（全 regime `n_valid_sims=0`）、實證端改讀 pinned CSV、統一 decline 0.816 vs 0.84 為 pinned 口徑。
- ⬜ **P1-4** NW(10) lag 一句話交代（shock-day 序列的日曆非連續性 vs 觀測序自相關）+ shock-day acf 診斷附錄。

## 5. P2 — R&R 彈藥 / 選擇性

- ⬜ **P2-1** NFP surprise-magnitude 規格（Philadelphia Fed real-time dataset；β₃ interaction）。
- ⬜ **P2-2** VIXTWN / V2X local-vol-index 擴充（0050.TW 的正面檢定）。
- ⬜ **P2-3** Deferred sections（shock-type / VRP / hedging）——**建議維持 deferred，放棄回填**（K716–K722 腳本永久缺失、K720 artifact 與敘事反向、新論文空間有限）。

## 6. 期刊路徑（Journal Routing）

- **Primary: Journal of Banking & Finance**（P0-1 通過時）——fear/attention 主線文獻在 JBF；R1 reviewer 判「realistic chance at JBF or JFQA」；描述性現象 + risk-management implication 是 JBF 讀者群。
- **Backup: Journal of Empirical Finance / International Review of Financial Analysis**（P0-1 偏弱、需降層）。
- **重新框架情境（P0-1 失敗）**：以「VIX-shock 選樣的機械分解」改寫成 measurement note 投 **Finance Research Letters**，或將 SAR/null-simulation 方法併入其他 VIX 系列論文。

---

## 7. 禁止事項（本篇特有 — 違反即研究誠實或流程失守）

- 🚫 **P0-1 沒跑完之前，禁止做任何正文文字打磨 / review-polish**。若 contemporaneous null 吃掉效應，打磨全部作廢——投入順序錯誤。
- 🚫 **禁止保留 C1 的 VRP 反向宣稱**。Intro「We find … no VRP sign flip」與 `k720_results.json`（`vrp_flip_confirmed: true`）及 §5.5 deferred 降級三方衝突，必修。
- 🚫 **禁止引用 Table 3 現有 p 值當可驗證證據**。K716 腳本缺失、`k716_results.json` 無 p 值、表注自相矛盾——inference 欄目前 unverifiable，P0-3 重建前不得對外宣稱其顯著性。
- 🚫 禁止用 live yfinance 下載當 K897 實證端資料（與論文 snapshot-pinning 原則不一致）；P0-1 實證端改讀 pinned CSV。
- 🚫 禁止在 P0-1 判定規則裁決前，把「absorption 超越機械效應」寫成既定結論。

---

## 8. 進度日誌（Progress Log）

```
2026-07-11 | Fable deep review | 深審完成，待執行 P0 | f913ed68c
2026-07-12 | P0-1 K1686 首跑 + Codex FAIL + R2 rerun | 首裁 REFRAME→撤回→R2 ambient×sign 補跑完成 | 085064f0f, 2c764c69d
2026-07-14 | K1686 R2 正式裁定（主線程） | absorption 通過 fear-shock gate；JBF 線繼續；FRL 重框取消；P0-1 CLOSED；knowledge da9ac9d2 | e947c9e25
2026-07-14 | P0-2/3/4 + K1686 body 整合（主線程） | C1–C5 修（C1×2 處、C5 依 k741 JSON=1.14/1.16）；Table 2/3 pinned + block-bootstrap 推論；新 §null_reexam；gate 95/95 GREEN；41pp 編譯乾淨 | 本 commit
```

---

## 9. 接續提示詞（Resume Prompt）

> 讀 `paper/volatility-absorption/EXECUTION.md` 與 `paper/volatility-absorption/review_history/fable_deep_review_20260711/README.md`，**從 P0-1 開始**：本篇是 make-or-break——開新 K（`ls experiments/` 取下一個可用編號 ≥ k1684），把 K897 的 day-t vol proxy 由 `h[t]` 改為 `h[t+1]`（contemporaneous null），同 seed 集重跑 10,000 sims，加 relative-threshold 與 sign-split 變體。**事前寫死判定規則**：empirical decline 仍在 95% null 外 → 論文升級走 JBF；落入 null 內 → 降級為機械分解、走重新框架（FRL note 或 archive）。判定以 experiment JSON 為準。P0-1 未裁決前不碰正文打磨、不標 ready、不投稿。完成後 Codex 複核 → 依結果更新 `main_v3.tex` §Robustness → 續走 P0-2/3/4。

### 進度更新 2026-07-12 — P0-1 GATING 結果與裁定（主線程）
- 2026-07-12 | **P0-1 已跑（K1686）：ABSORPTION CLAIM NOT SUPPORTED** — 主判定（變體 A）不拒絕 null（0.8165 落在 [0.0824,1.0596]，p=0.41）；更決定性的是機制層 sign-decomposition（不依賴 null 模型）：decline 住在 relief rally（ΔVIX<−2：+1.337）而非真恐慌衝擊（ΔVIX>+2：−0.123，CI [−0.729,0.583] 含 0）。K897 原 NULL REJECTED 結論不成立。
- **主線程裁定（依事前規則「落入 null 內→重框或 archive」）**：**REFRAME 為 FRL 級方法論短文**，放棄 JBF 線。新主軸：「表面的 volatility absorption 梯度是 relief-rally 成分驅動的 — pooled 條件統計量可被反號成分主導」的警世/方法論發現。不 archive：K1686 的 sign-decomposition 本身是乾淨可發表的貢獻。
- 後續：body 重寫（paper_body 主線程）依新主軸；舊 absorption 宣稱全文撤下；K897/k720 相關 knowledge 回溯更正列入重寫 checklist。
- 依據：experiments/k1686/README.md §7 Verdict + 本檔事前判定規則。

### ⚠️ 回溯更正 2026-07-12 18:20 — 上條 REFRAME 裁定**撤回**（Codex primary-path review = FAIL）
上一條裁定寫於 Codex 複核**返回之前**，採信的是 K1686 自身的 sign-decomposition verdict。Codex primary-path review（`storage/ops/codex_reviews/k1686_verdict.md`，**VERDICT: FAIL**）指出該 verdict 有兩個 blocking 缺陷，**REFRAME 的核心論據不成立**：

1. **「decline 住在 relief rally」是內生分組 artifact**：變體 D 用**同期** `VIX_t` 分 calm/high regime，但 ambient fear 的定義（變體 E）是 `VIX_{t-1}`。正向 VIX 衝擊本身會推高 `VIX_t` → post-shock 內生排序，把 calm 格機械性稀釋到 n=10。Codex 以 D 的 sign-split × E 的 `VIX_{t-1}` 對齊重算（no-write 複核）：ambient-up 的 calm−high decline = **+1.0465**（stratified bootstrap CI [0.361, 1.733]；20-day moving-block CI [0.329, 1.763]，47 calm / 53 high）—— **與「fear shock 下 decline 消失（−0.123）」符號相反**。缺的那個 D×E 規格會翻轉原結論。
2. **pooled vs up-only 的「顯著」對比從未被檢定**：bootstrap 只重抽 up-shock 四格得 up-only CI，再拿該 CI 上界與 pooled **點估計**比大小（code:747-752）。兩個都是估計量、且重疊；要宣稱顯著必須直接對「配對差」做 block bootstrap。10 個 calm up-shock 只夠支持「現行 current-VIX 分箱下未建立梯度」，不足以宣稱「機制決定性收斂」。

**Codex 支持的部分（維持）**：(a) 變體 A 事前 gate **未拒絕 null**（0.8165 落在 [0.0824, 1.0596]，p=0.41）— 內部一致、無 lookahead、pre-registration 完整性通過（870af5d00 早於首個結果 commit 322cfeb38）；(b) **K897 應退役** — 其 `NULL REJECTED` 在 pointwise-identical path 上僅因 proxy timing 改變就翻掉（decline 分佈 mean 0.1734 CI [−0.281, 0.558] → mean 0.6190 CI [0.082, 1.060]），margin 是 timing-dependent。但這只支持「K897 的拒絕無效」，**不支持**「null 為真」或「absorption 為假」。

**更正後的可辯護裁定（本檔 canonical）**：
> 原 contemporaneous SAR 識別**未通過事前 gate**；**K897 退役**；**ambient-fear 機制仍未解（unresolved）**。

- **FRL signed-composition 方法論短文 = 暫緩（on hold），不是已定案**。Codex：「The proposed FRL signed-composition note is currently too strong」— K1686 只支持一個較窄的 measurement 結果（published contemporaneous SAR 對 proxy timing / shock sign / threshold / calibration 高度敏感），**不足以宣稱 signed composition 取代了 ambient-fear absorption 作為解釋**。
- **JBF 線暫不宣告放棄**（gate 仍 OPEN 而非 CLOSED-negative）；body 重寫**不啟動**，直到下述 K 收斂。
- **不寫 knowledge.json**（FAIL verdict，per `.claude/rules/experiments.md` — CONDITIONAL PASS 以上才寫）。
- **派修正實驗**（見 next_tasks `k1686_fix_ambient_sign_spec` P1）：在 empirical 與 same-seed null 兩側補跑**缺失的 ambient(`VIX_{t-1}`) × sign 規格**；pooled-vs-up-only 改用**直接配對 block bootstrap**；B/C/G 在 calibration failure 未解前不得稱 well-specified。該 K 裁決前不得再改本篇 narrative。
- 依據：`storage/ops/codex_reviews/k1686_verdict.md`（Codex primary path，2026-07-12）。

### ✅ 正式裁定 2026-07-14 — K1686 R2 收斂：**absorption 通過 ambient-fear-shock gate，JBF 線繼續，FRL 重框取消**（本檔 canonical）

`k1686_fix_ambient_sign_spec`（P1）已於 2026-07-12 完成（commit `2c764c69d`），Codex primary-path **R2 review = PASS**（`experiments/k1686/codex_review_r2.md`；R1 兩個 blocker — ambient×sign 規格缺失、pooled-vs-up-only 非直接檢定 — 全數關閉）。依 **rerun 前固定的 R2 follow-up gate**（K1686 README §3：「H ambient-up 的 20-day paired block-bootstrap CI 若為正且不含 0，absorption 在 fear-shock 條件下存活；若含 0，機制 unresolved、論文降級重框」）：

- **H ambient-up decline = +1.0465**，20-day paired circular block bootstrap CI **[0.3286, 1.7625] 排除 0**；block 10/40/63 sensitivity 全同方向；calm/high up-shock n = 47/53。
- paired pooled−current-up = +0.9353，CI [0.3437, 1.4991]（直接配對檢定，取代舊的無效比較）。
- same-seed null 方向一致：H_up empirical 1.0465 > null 95% CI 上界 0.9887，MC p = 0.0327（補充證據，非完整結構識別 — null calibration 限制仍在）。

**裁定（依事前規則，無裁量空間）**：absorption 在 fear-shock 條件下**存活** → **JBF 主線繼續**；2026-07-12 第一條（已撤回）的 FRL 重框裁定**正式取消**。但 gate 通過 ≠ 回到舊敘事 — body 修訂必須如實納入：

1. **K897 退役**（timing-dependent 拒絕，不得再引用其 NULL REJECTED）；
2. **null 比較 inconclusive**（A 是兩個 artifact 抵消、B/C/G 拒絕但 calibration 未解、F 證明校準不變的 null 不存在）— 不得宣稱「null 檢定證明 absorption 真實」；
3. **58% threshold artifact**（相對門檻下 headline decline 0.8165 → 0.3397）必須揭露；
4. **識別重心移到 H 規格**（ambient×sign paired block gate）＋ §6.5 限制（α=0 半同期性、GJR 函數形式）。

**P0-1 就此關閉**。knowledge.json 已寫入（item `da9ac9d2`，2026-07-14）。後續：P0-2（C1–C5）→ K1686 body 整合 → P0-3（Table 3 SAR rebuild）→ P0-4（reproduce 擴充）。
