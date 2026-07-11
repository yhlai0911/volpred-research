# EXECUTION — garch-x-vix

> **BADGE** · verdict `2.5/5` · stage `revision`（**從未投稿**）· journal `IJF → JEF → JoF` · **p0 = 1 empirical gate closed / 3** · dod `1/7`
> 依據：`review_history/fable_deep_review_20260711/README.md`（Fable 深審 2.5/5）· `docs/paper_portfolio_review_20260711.md` · `storage/paper_pipeline_status.json`
> 最後更新：2026-07-12（K1685 關閉 P0-2 empirical gate；P0-1/P0-3 未執行）

---

## 最終目標

把 garch-x-vix 從「手稿層不可投」狀態，經一輪 P0 修訂推進到 **International Journal of Forecasting（IJF）可投稿**。

**核心貢獻（保留、不稀釋）**：當外生變數本身即日頻（VIX）時，GARCH-MIDAS 的混頻 Beta-polynomial 機械是冗餘的；最簡單的日頻乘法規格 **A4f**（τ_t = θ₀+θ₁·VIX²_{t-1}，free ω）點估計最優、與最短 lag MIDAS（B1, K=22）**統計不可區分**、顯著勝過長 lag MIDAS。MCS 誠實框架（α=0.10 全 17 模型存活；賣點是簡約而非「唯一最優」）是本篇最值得保留的資產。

**期刊順序（已裁定，老闆授權自主 — memory `feedback_paper_autonomy_optimize_acceptance`）**：
1. **IJF（primary）** — 貢獻形態是 forecast-evaluation 型（QLIKE/DM/MCS 橫評 + 簡約論 + VaR/ES scorecard），MCS「不可區分」的誠實結論在 IJF 是加分；replication package（pinned snapshot + reproduce.py）符合 IJF replication 友善傳統。
2. **JEF（Journal of Empirical Finance，secondary）** — IJF 被拒後改寫目標，屆時把 VRP 雙通道敘事升級為主線。
3. **JoF（Journal of Forecasting，backup）**。

> **關鍵裁定（寫進本檔以免再被誤導）**：pipeline blocker 寫「A4f errata awaiting owner sign-off」，此為 **假等待點**。`storage/paper_pipeline_status.json` 2026-07-10 更正記錄（owner Telegram msg 331/340）確認**本論文從未投稿任何期刊**，「body frozen until R1 reviewer response」的前提為偽——沒有 reviewer 會來。errata 是「已投稿/已發表文獻的更正機制」，套在未投稿手稿上是範疇錯誤。**正確動作 = 立即解凍、直接修稿**，不等任何 sign-off。

---

## 當前狀態

**Verdict 2.5 / 5（現狀 NO-GO；完成 P0 後預估 4/5，IJF 有實質錄取機會）。**

- **實驗層健全** ✅：canonical 統計機械（`compute_mcs_dm.py`、K1393、K994/K997 走 `volpred.stats.model_evaluation.dm_test`）全部使用正確 n^(1/3) 級 HAC bandwidth，**不在** 2026-07-11 DM-HAC 凍結 backlog（139 站點）內；VaR 表（K995）、VRP 相關（K988b）、殘差診斷（K1045）、敏感度（K1003）逐格抽查全數吻合。
- **手稿層不健全** ❌：Table 3 的 C1=3.49 無任何來源（canonical 1.995，Harvey 由 Yes 翻 No）、A3f/B2 兩處 Harvey 質性標錯、headline 4.03 來源宣稱為偽（main.tex:723 稱出自 `mcs_dm_results.json`，該檔實存 4.148）、§5.9 宣稱測六個 macro 變數但 K1001 只跑兩個、`acerbi2019` 是嵌合引用、pairwise DM 表同表混兩套符號慣例。全是 referee 一眼可見、無需重跑即可抓到的問題。
- **Pipeline 卡住的真正根因** = 上述假前提（body frozen until R1，reviewer 不存在）。解法不是等 sign-off，是解凍後把整份修正 queue 落地。
- **Reproduce gate**（`reproduce_report.json` 2026-07-09）：match_rate 85.7% / **yellow**，唯一 mismatch 就是 4.03 vs 4.148 + `readme_status_mismatch`；P0-1 落地後預期轉 **green**。
- **P0-2 empirical risk 已由 K1685 關閉（2026-07-12）**：K1393-faithful、pinned SPY/VIX snapshot、OOS 延至 2026-07-10（n=1,890），A4f vs GJR canonical DM t=+3.9656；symmetric 12-start t=+3.0098，只高 Harvey 門檻 0.0098，lag-10 sensitivity=2.9901。故 headline 以 `GO_WITH_FRAGILITY_DISCLOSURE` 存活，不得寫成廣泛穩健。K1393 legacy anchor t=3.602900965 精確重現；60-refit parameter audit 與 Codex review PASS。舊 paper CSV 的 10 個重複日期使 K1391 reversal 另受資料污染，須修 collector、不可手改資料。手稿 endpoint/sensitivity 綁定仍屬 P0-1。

---

## 完成定義（DoD）— 全部未達成

- [ ] **P0-1** 落地：Table 3 由 canonical `mcs_dm_results.json` 全表重生（C1→1.995 No、A3f→3.018 Yes、B2→3.066 Yes、計數 10/16→11/16）；4.03→4.148 全文統一；macro 段、符號慣例、引用、措辭全部修正
- [x] **P0-2 empirical gate**：K1393-faithful spec 延長 OOS 覆核完成；headline 以 `GO_WITH_FRAGILITY_DISCLOSURE` 存活。手稿 endpoint / optimizer-HAC sensitivity 綁定併入尚未完成的 P0-1。
- [ ] **P0-3** 落地：replication package 除雷完成，狀態行改「revision, not submitted」
- [ ] `reproduce.py` exit 0 且 `reproduce_report.json` match_rate ≥ 95% / **alert green**
- [ ] `/citation-verifier` 重跑 **0 MAJOR**（含 acerbi2019 修正 + 新增文獻卷期驗證）
- [ ] IJF `journal-review` compliance gate 通過（author = Yi-Hao Lai only；無 volpred / AI / LLM 字樣）
- [ ] `uv run volpred ops paper-update --paper-id garch-x-vix` 同步 + 線上驗證

---

## P0 — 投稿前必做（預估 2 個工作 sprint；全部 ⬜ TODO）

### ⬜ P0-1 — 解凍 + canonical rebind（純手稿 + metadata，估 1–2 天主線程）

撤銷「body frozen until R1」（前提為偽）。把 `r1_response_queue.md` Q1–Q5 + v7 P1–P3 一次落地 `main.tex`：

- ⬜ **Table 3 全表由 pinned `mcs_dm_results.json` 重生**：C1 3.49→**1.995（Harvey No）**、A3f 2.92→**3.018（Yes）**、B2 2.99→**3.066（Yes）**、「10 of 16 |t|>3」→**11 of 16**（成員變動：C1 出、A3f+B2 進）、A1/A3f rank 對調修正
- ⬜ **4.03 → 4.148 全文同步**（下游 lines 52/80/723/776/905）；資料節加 vintage 聲明（「所有數字出自 2026-04-19 pinned yfinance snapshot，隨附 replication package」）
- ⬜ **§5.9 macro 段改寫為兩變數實況** + t=4.77 重標為「A4f vs GJR」（非「vs best macro」）
- ⬜ **`acerbi2019` → `acerbi2014`（Risk 27(11):76–81）**；Z1/Z2 正確出處為 Acerbi & Szekely 2014（可另引 Du & Escanciano 2017 MS 63(4):940–958）
- ⬜ **"statistically non-inferior" → "not statistically distinguishable"**（main.tex:806, 813）
- ⬜ **g_t / g-proxy 全文統一**：採 §3.4 雙通道誠實敘事——「E[g]=1 類規格下 g_t 追蹤 VRP（ρ≈0.80）；推薦的 A4f 因 free ω 吸收平均 VRP 水位，其 g_t 與 VRP 近乎正交（ρ=−0.017），兩者共同構成 VRP 修正的雙通道證據（θ₁ 通道 + E[g] 通道，Prop 2）」。§4.2/§6/abstract/conclusion 四處同一命名 + 同一數字
- ⬜ **五之七 → 雙門檻並列**（Harvey |t|>3 與 Bonferroni 2.95）；conclusion 對齊自家 caveat（main.tex:911）
- ⬜ **pairwise DM 表符號慣例統一**（同表勿混「positive = first better」與翻正慣例）
- ⬜ **2.5× → 重算**（audit_2026-06-10 Q5：JSON 比值 ≈7.6×，投稿前實算取代）
- ⬜ **GJR QLIKE 三值統一**（Table 3 −8.273 / Table 4 SPY −8.277 / canonical −8.2710）
- ⬜ **n 對照 footnote**（1825/1824/1828/1852/1866 五版本散落各表，加統一說明）

**驗證 gate**：xelatex 重編譯無誤 + `reproduce.py` match_rate ≥ 95% **green** + `paper-update` 同步線上驗證。

### ✅ P0-2 — 延長 OOS faithful-spec 覆核（K1685；empirical gate complete）

以 K1393 的 K988-faithful A4f spec、新 pinned snapshot，OOS 延到最新資料（≥2026-06），full QLIKE kernel + canonical DM。

- ✅ 完整 OOS canonical Harvey gate 仍過：3-start t=+3.9656；12-start t=+3.0098。
- ✅ 未翻轉，但屬門檻脆弱：lag-10=2.9901、anchor multistart<3；裁決 `GO_WITH_FRAGILITY_DISCLOSURE`。
- ⬜ 手稿資料節更新至 2026-07-10，並寫入 optimizer/HAC sensitivity（與 P0-1 canonical rebind 一起由主線程修改 `.tex`）。

**驗證 gate：PASS**。`experiments/k1685/` 三件套 + pinned data / figures / parameter audit 齊全；seed=42；Codex primary + 兩位 fresh-context reviewers PASS；knowledge item `7d2e411b`（confidence=.84）。
（對應收件 task：`k1685_collect_orphaned_results`；原 compute job 因 orphan-process timeout 被標 failed，特殊 provenance 見 K1685 README。）

### ⬜ P0-3 — Replication package 除雷（修流程不修資料）

- ⬜ 修 `k994.py` 的符號判斷邏輯並**重生** k994 JSON（`direction` 欄「gjr_better」實為 A4f better，系統性標反）——改產生邏輯，不 sed 改欄位
- ⬜ `results/README.md` VaR 綁定由不存在的 `k988_results.json → var_backtest` 改指 **K995**
- ⬜ STOXX50E/FEZ 快照釘住 + 加入 reproduce bindings（K1144 重跑 drift −16.9%/−9.7%，快照從未按 SF2 行動項釘住）
- ⬜ `README.md` / `experiments.md` / `research_program.md` 狀態行改「**revision, not submitted**」

**驗證 gate**：`reproduce.py` 含新 bindings 全綠；`grep` 全 repo 無殘留 "under review" / "submitted"。

---

## P1 — 投稿包強化（與 P0 平行可做，非 gate blocker）

- **文獻補強與劃界**：§2 加 Kanniainen-Lin-Yang (2014 JBF)、Blair-Poon-Taylor (2001 JoE)、Amado-Teräsvirta (2013 JoE)、HEAVY/Realized GARCH 一段劃界；刪「the most comprehensive specification comparison to date」→ 改「a systematic comparison of 17 specifications」。→ `/citation-verifier` 全跑一輪（`citation_check.md` 已是 2026-04-10 舊版）。
- **K1066 OC-proxy robustness 併入**：`r1_prep/robustness_oc_proxy.tex` 已 shelf-ready（A4f_oc vs GJR_oc DM t=+4.04，5/5 子期），直接回應 Limitations 的 proxy-sensitivity；未投稿就不必留「shelf」。
- **VRP 節重寫為雙通道敘事**（§3.4）——把弱點變賣點。
- **abstract 重寫**：4.148、雙門檻跨資產計數、g-proxy 措辭、刪 "passes none (scorecard 1/4)" 混淆並列。

---

## 禁止事項（本篇特有）

- ⛔ **別再等 A4f errata owner sign-off** — 論文從未投稿，「body frozen until R1」前提為偽；pipeline blocker 是假等待點，直接修稿。
- ⛔ **Table 3 C1=3.49 是無來源數字**（canonical 1.995，Harvey 翻轉）——必修，不可沿用舊值；任何 uniqueness / 計數宣稱必回 current `mcs_dm_results.json` 重驗（K1416 教訓）。
- ⛔ **§5.9 macro 段勿再宣稱六變數** — K1001 只跑**兩個** macro；t=4.77 是「A4f vs GJR」不是「vs best macro」（張冠李戴 + 統計量誤標 = 研究誠實層級問題）。
- ⛔ **`acerbi2019` 是嵌合引用**（標題屬 Du & Escanciano 2017 MS，作者/卷期/DOI 皆錯位）——改 `acerbi2014`(Risk)，不可沿用。
- ⛔ **不手改 JSON 湊數字**（修 `k994.py` 符號判斷邏輯，不 sed / Edit `direction` 欄）——修流程不修資料。
- ⛔ **不混 vintage**：4.03 是 drafting vintage，全文統一 canonical 4.148（2026-04-19 pinned snapshot）；GW 段落勿一半新一半舊。
- ⛔ **不整檔讀** `feed.json` / `knowledge.json`（用 grep/jq/單檔）。

---

## 進度日誌

```
2026-07-11 | Fable deep review | 深審完成，待執行 P0 | f913ed68c
```

---

## 接續提示詞

讀 `paper/garch-x-vix/EXECUTION.md` 後，從 **P0-1** 開始：解凍（撤銷 body-frozen 假前提，A4f errata sign-off 是不存在的等待點，論文從未投稿）→ 把 `r1_response_queue.md` Q1–Q5 + `review_history/v7` P1–P3 一次落地 `main.tex`，**首要動作 = Table 3 全表由 canonical `mcs_dm_results.json` 重生**（C1 3.49→1.995 No、A3f→3.018 Yes、B2→3.066 Yes、10/16→11/16、4.03→4.148 全文同步），完整清單見上方 P0-1。落地後 xelatex 重編譯 + `reproduce.py` 轉 green + `paper-update` 同步。修訂在主線程進行（不丟 background agent 改 .tex，paper-workflow 硬規則）；每項改動的來源數字先讀 `mcs_dm_results.json` 驗證再寫，不臆造。P0-2（延長 OOS 覆核）是獨立 compute job（next_tasks `fable0711_garchx_k1393_oos`），可與 P0-1/P0-3 平行。
