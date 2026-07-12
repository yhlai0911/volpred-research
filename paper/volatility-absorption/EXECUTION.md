# EXECUTION — volatility-absorption（Paper 8：The Volatility Absorption Hypothesis）

`BADGE` · `stage: revision` · `verdict: 2.5/5 有條件 Major Revision` · `journal: JBF → JEF/IRFA（backup）` · `p0: TODO` · `gate: OPEN（P0-1 未跑）`

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

投稿前必須全部勾起；目前 P0 未執行，全部 ⬜。

- ⬜ **P0-1 contemporaneous null 重跑完成**，事前判定規則已裁決並如實寫入正文（升級敘事 or 重新框架，二者之一）
- ⬜ 5 處內部不一致 C1–C5 全修（含 C1：Intro 一句與自家 artifact `k720`（`vrp_flip_confirmed: true`）反向的 VRP 宣稱）
- ⬜ Table 3 SAR inference 用 pinned snapshot 重建，p 值有可驗證 binding（消除「t-test via bootstrap」的混亂表注）
- ⬜ reproduce gate 從 30 checks 擴到 ~40，重跑 `match_rate ≥ 0.95` + `alert_level = green`
- ⬜ 引用修理：4 條孤兒（chernov2018 / baur2010 / patton2011 / romer2004）+ zakoian1994 期刊出處 + chernov 年份，`citation-verifier` 全掃通過
- ⬜ Prior-art 防線：Intro/Lit review 補 Low (2004) / Hibbert et al. (2008) / Fleming-Ostdiek-Whaley (1995) 並正面區分
- ⬜ 多輪 `paper-review-cycle`（latex-academic-reviewer + citation-verifier）收斂
- ⬜ 期刊目標定案（README `Target Journal: TBD` → JBF 或降層決策）

---

## 3. P0 — Gate（不完成不得標 ready / 不得投稿；預估 1–2 工作天；**全 ⬜ TODO，尚未執行**）

### ⬜ P0-1 · **【make-or-break】** contemporaneous null 重跑 K897

- 開**新 K**（`experiments/` 下一個可用編號 ≥ **k1684**；派工時 `ls experiments/` 取最新確認，深審原寫 k1683 已被占用）。
- 改動極小：`simulate_garch_sar_fixed_thresholds` 中 day-t vol proxy 由 `h[t]` 改用 **`h[t+1]`**（觀測 `r_t` 後的 GARCH forecast，等價於「收盤 VIX 反映當日資訊」），shock 定義隨之同期化。
- 同 seed 集、同 10,000 paths；加 **relative-threshold**（`|Δproxy|/proxy > 對應百分位`）變體與 **sign-split**（VIX 上升 vs relief rally）robustness。
- **事前寫死的判定規則（研究誠實，不可事後改）**：empirical decline 仍在 95% null 外 → 識別關閉、論文升級；落入 null 內 → 主張降級為機械分解、走 §重新框架路線。**無論哪個結果都要如實寫進論文。**
- 產出：新 K 三件套（`README.md` / `<id>.py` / `<id>_results.json`）+ 固定 seed + Codex 語義級複核 → `main_v3.tex` §Robustness 更新。
- Brief：`review_history/fable_deep_review_20260711/README.md` §5（P0-1）+ §3-B（timing 缺口證據，`k897_sar_null_simulation.py:269-316`）。

### ⬜ P0-2 · 修 5 處內部不一致（C1–C5）

- **C1**（Intro line 76）：刪或改寫「We find that the VRP narrows... no VRP sign flip」——此句與 §5.5（VRP 已降級 deferred）及 `k720_results.json`（`vrp_flip_confirmed: true`）**正好相反**。referee/replicator 一抓即喪失全篇可信度。
- **C3**（Table 4 line 351）：0050.TW 行改用 `k1418_results.json` pinned 值（β=9.21e-5, t=+0.283），統一 Intro/Appendix B 的三處兩值。
- **C4**（Appendix B lines 715-718）：α 欄、adj R² 欄改讀 `experiments/k1418/tables/k1418_cross_asset.csv`（α=0.0822/0.0548/0.0531/0.0473；R²=0.0076/0.0142/0.029/−0.0013），消除「β/t pinned + α/R² 舊值」的 chimera。
- **C2**（Table 2 note line 284）：改寫 stale cross-ref（「N=893」→ 現行 769/768）。
- **C5**（§5.3 line 368）：「1.17 times」改成「1.14× vs all non-NFP（1.17× vs Fridays）」；修 footnote「4,081 trading days」→ 與 `k741` JSON 一致值（195+3909=4,104）。

### ⬜ P0-3 · Table 3 SAR inference rebuild

- pinned CSV 上重算五 regime SAR + seeded bootstrap（明確統計量：`SAR_calm − SAR_j` 的 percentile CI），產出 JSON、綁進 `reproduce.py`、更新表注（消掉「two-sample t-test … via bootstrap」的自相矛盾描述；K716 原始腳本永久缺失，K1249 確認 rebuild blocked，故用 pinned snapshot 重寫）。

### ⬜ P0-4 · reproduce.py 補 checks（30 → ~40）

- 新增 binding：Table 4 0050.TW t、Appendix B α/R²（讀 k1418 CSV）、NFP overall ratio/p、Table 3 新 p 值。重跑 `reproduce_report.json` 綠。

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
```

---

## 9. 接續提示詞（Resume Prompt）

> 讀 `paper/volatility-absorption/EXECUTION.md` 與 `paper/volatility-absorption/review_history/fable_deep_review_20260711/README.md`，**從 P0-1 開始**：本篇是 make-or-break——開新 K（`ls experiments/` 取下一個可用編號 ≥ k1684），把 K897 的 day-t vol proxy 由 `h[t]` 改為 `h[t+1]`（contemporaneous null），同 seed 集重跑 10,000 sims，加 relative-threshold 與 sign-split 變體。**事前寫死判定規則**：empirical decline 仍在 95% null 外 → 論文升級走 JBF；落入 null 內 → 降級為機械分解、走重新框架（FRL note 或 archive）。判定以 experiment JSON 為準。P0-1 未裁決前不碰正文打磨、不標 ready、不投稿。完成後 Codex 複核 → 依結果更新 `main_v3.tex` §Robustness → 續走 P0-2/3/4。

### 進度更新 2026-07-12 — P0-1 GATING 結果與裁定（主線程）
- 2026-07-12 | **P0-1 已跑（K1686）：ABSORPTION CLAIM NOT SUPPORTED** — 主判定（變體 A）不拒絕 null（0.8165 落在 [0.0824,1.0596]，p=0.41）；更決定性的是機制層 sign-decomposition（不依賴 null 模型）：decline 住在 relief rally（ΔVIX<−2：+1.337）而非真恐慌衝擊（ΔVIX>+2：−0.123，CI [−0.729,0.583] 含 0）。K897 原 NULL REJECTED 結論不成立。
- **主線程裁定（依事前規則「落入 null 內→重框或 archive」）**：**REFRAME 為 FRL 級方法論短文**，放棄 JBF 線。新主軸：「表面的 volatility absorption 梯度是 relief-rally 成分驅動的 — pooled 條件統計量可被反號成分主導」的警世/方法論發現。不 archive：K1686 的 sign-decomposition 本身是乾淨可發表的貢獻。
- 後續：body 重寫（paper_body 主線程）依新主軸；舊 absorption 宣稱全文撤下；K897/k720 相關 knowledge 回溯更正列入重寫 checklist。
- 依據：experiments/k1686/README.md §7 Verdict + 本檔事前判定規則。
