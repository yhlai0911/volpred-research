# EXECUTION — vt-crowding-abm

> **BADGE** · verdict `2/5`（底層 K1471 證據層 `4/5`）· stage `revision`（**finishing**；journal_target 未定）· journal `QF → JEBO`（FRL 快軌備選）· **p0 = DONE · v6_review = PASSED（2026-07-14）** · tier `1` · dod `7/9`
> 依據：`review_history/fable_deep_review_20260711/README.md`（Fable 深審 2/5）· `docs/paper_portfolio_review_20260711.md`（第一梯隊）· `storage/paper_pipeline_status.json`（stage=revision / blocker=finishing / journal_target=decide）
> 最後更新：2026-07-14（P0-1~P0-5 全數完成；下一 gate = v6 跨模型獨立 review）

---

## 最終目標

把 vt-crowding-abm 從「半改寫嫁接稿、內部矛盾、不利證據漏報」的不可投狀態，經**一輪 P0 純寫作修訂**收斂為 **VT-only** 論文，推進到 **Quantitative Finance（QF）可投稿**。本篇 P0 無需重跑任何模擬——底層 K1471 證據已扎實，缺口全在手稿接線層。

**核心貢獻（保留、收斂為 VT-only）**：

1. **VT monotone erosion**：canonical cell（λ=0.005, γ=200）Sharpe 0.510 @10% → −0.271 @100%，7 個 adoption 點 + path-bootstrap 95% CI，相鄰 CI 自 40% 起分離，sup-Wald 外生 detector 拒 flatness（5/5 cells，p=0.001）但不定位內部斷點。
2. **Matched-control 機制識別（本文最強、最有新意，應當第一貢獻寫）**：coherent-block turnover-matched 隨機方向對照 RR_VT——保留 footprint、抽掉方向——在 5/5 cells 零惡化（+0.080~+0.098），VT 同 cells 掉 −0.421~−0.899。此 counterfactual 在 VT crowding 文獻（Baltas 2019、ECB 2020、Barbon-Buraschi 類）無先例。
3. 「70%」誠實降級為 **descriptive level-crossing**（相對跌幅 >70%，3/5 cells）。

**期刊順序（已裁定，老闆授權自主 — memory `feedback_paper_autonomy_optimize_acceptance`）**：
1. **QF（primary）** — simulation/microstructure/crowding 的天然家；對「encoded mechanism 的量化 + 識別」framing 接受度高；不受 letter 長度限制，TF/MR gate 一節與 appendix 放得下；中等審稿速度。
2. **JEBO（secondary）** — mechanism-quantification ABM 傳統深；容忍 stylized model；缺點是審稿慢、對 baseline stylized facts 可能追打。
3. **FRL（快軌備選，現 target）** — 要壓到 letter 長度就必須 VT-only + 砍 appendix；速度與曝光優先時選。**注意 v4 的「90% 接受率」預測作廢，不要帶入錨定。**

> **關鍵裁定（寫進本檔以免再被誤導）**：
> - **收斂為 VT-only**。家族層（TF/MR）在 K1471 新框架下**證據真空**（見 P0-3），救它需在 viable 參數化下重跑整套 K1471（P2-1），會再拖 1–2 個月且結論未卜。TF/MR 素材**不丟**，誠實轉述為一節「cross-strategy extension：applicability gate 揭示 s=10 的 TF/MR 在模型內不可行」——這本身是有資訊量的方法論結果，並附 RR_TF 的 footprint-scale 發現。
> - **Tautology 天花板（agy blocking #1，不可修只可框）**：feedback loop 是 hardcoded（Eq. 1–2 + VT rule 閉環），不是 emergent。對 JBF/JFE 級是致命傷；對 QF/JEBO「computational laboratory 量化 encoded mechanism 的斜率與識別」是可接受 framing——**前提是把「量化 + 識別」講清楚、絕不暗示 emergence**。

---

## 當前狀態

**Verdict 2/5（現稿 NO-GO 投任何期刊；B1–B6 任一條足以 desk reject。底層 K1471 證據層 4/5）。**

- **實驗層扎實** ✅：K1471 redesign（2026-06-11，94,500 sims，runtime 1,756s）確實修好 v5 兩位獨立審稿人的實驗層 blocking——外生 sup-Wald detector、coherent-block active control、path-level bootstrap CI；抽驗的所有論文數字（VT 七點曲線 + CI、matched-control 5 cells 全欄、p 值、footprint match）與 `k1471_full_results.json` **完全吻合，無造假跡象**；Codex adversarial review **CONDITIONAL PASS**（9 findings，無計算/lookahead/seed bug）；單元測試 6/6 PASS；lookahead-safe（VT 讀 `vix_series[t-1]`）+ seed 政策完備。
- **手稿層不健全** ❌：`main.tex` 是**半改寫嫁接稿**——新 monotone-erosion 敘事（abstract、§3.1 前半、§3.2、Discussion、Conclusion）與舊 70% tipping-point 敘事（§3.1 後半、Figure 1、§3.4–§3.7）同稿互撞至少 5 處（§3.4「genuine structural break」直接對上 abstract「no internal break」）；v5 codex 指名的循環校準原文（L317）一字未刪。
- **研究誠實層問題（最高風險）** ❌：K1471 TF/MR **不利證據被漏報與錯報**——applicability gate 實際擋掉 TF 4/5 cells、MR 5/5 cells（論文只承認 2 個例外）；RR_TF 在 5/5 cells 顯著惡化（p=0.001）**整篇未報**→「footprint per se 無害」的識別主張其實是 **footprint-scale-dependent**。家族層主張在新框架下已無有效證據，結論卻照舊宣稱。
- **Pipeline 卡住的真正根因** = 半成品狀態掛了 30 天：narrative rewrite 標「pending review」但**沒有人接著派 v6 review round**（rewrite 只改頭尾，§3.4–§3.7 留待 polish 而 polish 從未發生）；`journal_target=decide` 無 target 就無 format gate 逼收斂；`reproduce.py` 未擴充到 K1471（reproduce gate 是 review 先決條件）→ 流程自鎖。
- **v4 GREEN PASS 應正式作廢**：v4 兩位「審稿人」是同模型 general-purpose subagent proxy（**本平台第三例**同模型自審假陽性，見 memory `project_papers_awaiting_submit_decision`）；v4 審的是已被 K1471 自己推翻的舊敘事；現稿內部一致性比 v4 當時更差。「90% 淨接受率」無任何效力。

---

## 完成定義（DoD）— 6/9（剩 v6 review / QF compliance / 最終同步）

- [x] **P0-1** 完成（d37775ac9 + 2026-07-14 主線程驗證）：全稿 tipping/structural-break/safe-zone 殘留僅剩合法否定式/歷史指涉用法
- [x] **P0-2** 完成（5ff463529 + 2026-07-14 主線程殘留清除）：VT-only 對齊——**conclusion 開頭「positive-feedback strategies as a class」與 §knife_edge 為已撤回 ordering 辯護的兩處漏網已改寫**；`grep 'TF/MR ≤ VT|as a class'` = 0
- [x] **P0-3** 完成（5ff463529，2026-07-14 驗證）：tab:tfmr_gate 在稿 + RR_TF erosion 補報 + 'per se' 殘留 3 處皆為 liquidity-attribution 合法用法
- [x] **P0-4** 完成（2026-07-14）：reproduce.py K1471 三表 binding（gate 173/173 green）+ 主線程 provenance class sweep（7 處印出型內部路徑全清，PDF 零洩漏）
- [x] **P0-5** 完成（2026-07-14 主線程）：§2 補 redesign-layer 描述（27×7×500 grid + coherent-block RR + deterministic disjoint seeds——**深審原要求的「CRN pairing 說明」經查證 K1471 README 不成立**（RR 用不重疊 offset），已改寫誠實版本）；Phase-1 14,000/10,500 口徑統一（VT slice 標明重用）；Bonferroni(35) 句補上；heterogeneous agents→agents of heterogeneous types ×3；Kyle 1315–1335；bib 字母排序；README metadata 更新。94,500 因式分解 / 52% 歸因 / φ=100% accounting 三項確認已由先前 pass 解決
- [x] `reproduce.py` exit 0 且 `reproduce_report.json` match_rate ≥ 95% / **alert green**（含 K1471 三張 headline 表）✅ 173/173 = 100% green（2026-07-14）
- [x] **v6 跨模型獨立 review** ✅ 0 blocking 達成（2026-07-14）：初審 BLOCKING(3B+1M+3m) → 全修（4217af920 + a74895380）→ 覆核 6/6 FIXED（B2 經 Codex 終驗 CONFIRM_FIXED；REVERIFY.md + 兩份 transcript 存證）
- [ ] QF `journal-review` compliance gate 通過（author = Yi-Hao Lai only；無 volpred / AI / LLM 字樣）
- [ ] `uv run volpred ops paper-update --paper-id vt-crowding-abm` 同步 + 線上驗證

---

## P0 — 投稿前必做（✅ 2026-07-14 全數完成；下方各節保留原規格與驗證 gate 記錄）

### ✅ P0-1 — 敘事單一化 pass（d37775ac9；2026-07-14 主線程 gate 驗證通過）

現稿新舊敘事同稿互撞至少 5 處，任何 referee 讀到 §3.4「genuine structural break」對上 abstract「identifies no internal break」就結束了。一次消除（行號以 2026-07-01 版 `main.tex` 為準）：

- ⬜ **L197** 刪「consistent with a phase-transition-like threshold」
- ⬜ **Figure 1 caption** 重寫（圖本身要重畫，見 P1-2）：刪「VT tipping point / empirical tipping zone / safe zone」紅綠區帶語言
- ⬜ **§3.4 全段重寫**：Welch 數字保留（audit 抽驗過，數字本身無誤），改為 pairwise 比較敘述，刪「genuine structural break」「tipping point between 30% and 50%」「distinctly larger structural break」等結構斷點語言
- ⬜ **§3.7** 三段式 threshold 句（「negligible below 30%, material at 50%, catastrophic at 70%」）改為 monotone 敘述
- ⬜ **§3.6** 刪「headline 70% VT threshold」「calibration is exact」——K1471 下 VT 的 sup-Wald split 落在 100%（grid artifact），70% 只是 descriptive level-crossing

**驗證 gate**：全稿 `grep -iE 'tipping|structural break|safe zone'` 無殘留（appendix continuity 註記除外）；abstract 與 §3 敘事單一化。

### ✅ P0-2 — scope 收斂 VT-only（5ff463529 + 2026-07-14 conclusion/knife-edge 殘留清除）

- ⬜ **Tables 3/4 + knife-edge §（17/17 robustness）移 appendix**，標「superseded Sharpe-only detector（K1261/K1262/K1262b）的歷史結果，僅作 continuity 參考」，或整段刪除——同一份稿不能一邊宣告該 detector 循環作廢、一邊拿它輸出當第二貢獻
- ⬜ **刪 L317** 循環校準句（v5 codex blocking #1 指名：「reproduces exactly the 70% threshold... the primary anchor」）
- ⬜ **title / abstract / conclusion 對齊 VT-only**；family-level（TF/MR）threshold ordering 第二貢獻**撤或降級**
- ⬜ TF/MR 素材誠實轉述為一節「**cross-strategy extension：applicability gate 揭示 s=10 的 TF/MR 在模型內不可行**」（含 P0-3 的 RR_TF footprint-scale 發現）

**驗證 gate**：conclusion 無任何以 superseded detector 為證據的 family-level ordering 主張；title/abstract/conclusion 三處 scope 一致。

### ✅ P0-3 — 誠實補報 K1471 TF/MR（5ff463529；2026-07-14 驗證）

L243 現宣稱 gate 只排除「RR_MR in cell3 + cell2-TF@φ=30%」，且承諾「TF/MR matched-control evidence reported in §3.5」——§3.5 內 RR_TF/RR_MR 數字**一個都沒有**。實況（`k1471_full_threshold_table.md`，已對 JSON 驗證）：

- ⬜ **gate 失效全表**：TF 在 cells 1/3/4/5 被 `not_applicable_saturated_loss` 擋（baseline Sharpe −0.82~−1.25），MR 在 5/5 cells 全擋（−0.69~−5.49）；TF 唯一存活的 cell2 是病態 regime（interpretation 文件判定不可引用，baseline −0.444、曲線劇烈非單調）
- ⬜ **修正 L243** 的錯誤 gate 敘述（實際擋掉的遠多於宣稱的 2 個例外）
- ⬜ **RR_TF 5/5 cells 顯著惡化補報**（p=0.001，threshold 40–70%，cell1 −0.037 → −0.307）——大型協同流量自我 impact 成本的直接證據（K1471 interpretation 文件已如此記載）
- ⬜ **無條件版本改 footprint-scale**：「erosion is identified to the systematic direction rather than to crowded flow **per se**」→「... rather than to crowded flow **at VT's footprint scale**」（VT footprint |Δw|≈0.004–0.008 無害；TF-scale |Δw|≈1.5 隨機方向也有實質侵蝕）
- ⬜ 補上 §3.5 承諾但缺席的 RR_TF/RR_MR 數字（或移除該承諾）

**驗證 gate**：正文含 TF/MR gate 失效全表 + RR_TF 惡化證據；全稿無「per se」無條件識別主張殘留。

### ✅ P0-4 — reproduce gate + provenance 修復（B5 + B6；2026-07-14 全數完成）

`reproduce.py`（4/28）只綁 k827v3/k1261/k1262，**零 K1471 覆蓋**——abstract、Table `tab:vt_monotone_curve`、Table `tab:matched_control_vt` 全在 gate 之外，違反平台硬規則。

- ✅ **reproduce.py 擴充 K1471 section**（2026-07-14）：三張 K1471 表逐欄 binding —— `tab:vt_monotone_curve`（VT 曲線 7 點 mean+CI+Δ）、`tab:matched_control_vt`（VT vs RR_VT 5 cells 全欄 + narrative）、`tab:tfmr_gate`（gate 5 cells×8 欄）+ abstract 因式分解（94,500=27×7×500）+ RR_TF footprint-scale erosion narrative。**gate: 173/173 = 100% green, exit 0**（`--skip-live` 與 live 皆同）。canonical path = `cells.<cell>.treatments.<treat>.per_adoption` / `cells.<cell>.detector.<treat>`。
- ✅ **caption binding 路徑修正（主線程 2026-07-14）**：L142 caption 的錯誤路徑 `treatment_results.VT_baseline.cell1` 已改為正解 `cells.cell1_baseline.treatments.VT_baseline.per_adoption`（降為 LaTeX comment）。
- ✅ **`\% source:` 洩漏修復 + class sweep（主線程 2026-07-14）**：不只 agent 點名的 L142/L214 — 全檔掃出**同類共 7 處**印出型內部路徑（k1471 caption×2、§3.5 gate 實作路徑、§4.1 footnote、fig caption 的 scripts/ 路徑、k1262/k1262b caption×3），全部改為「replication package」+ 路徑降 LaTeX comment。原 P0-4 gate 只掃 `k1471|source:` 小寫，會漏 k1262 的 `Source:` — class sweep 補上。
- **驗證 gate 全達成**：`reproduce.py` **173/173 = 100% green, exit 0**；`pdftotext main.pdf | grep -iE 'source:|experiments/k|scripts/|_results\.json|\.py|\.md'` 僅剩 3 筆 caption 正常學術用語「Source: <run 描述>」，**零內部路徑洩漏**；重編譯乾淨。

### ✅ P0-5 — 機械修正批次（2026-07-14 主線程全項落地；見 DoD P0-5 條）

- ⬜ **abstract 因式分解** 改 7 treatments × **27** 個 cell×adoption 組合 × 500 = 94,500（現「5 cells × 7 levels × 7 treatments × 500 = 122,500」≠ 94,500）
- ⬜ **§2.1 補 K1471 adoption grid 描述**（{10,30,40,50,60,70,100}%，cell1 七點、cells2–5 各五點；現 L103 誤寫 {0,10,20,30,50,70,100}%）+ **coherent-block RR 描述**（整個 block 同天同 sign 同 |Δw|，單次 rng draw 施加全體權重向量——非 per-agent 獨立，否則審稿人會用「聚合流量不協同」打掉識別）+ common-random-numbers seed pairing 說明
- ⬜ **52% 歸因方向修正**（0.13/0.25=52% 是 crowding 殘存份額，liquidity 份額 48%）或全文統一「approximately half」
- ⬜ **14,000 / 10,500 sims 口徑統一**（§2.4 L125 vs Table 3 caption；VT slice 是 K827v3 重用）
- ⬜ **φ=100% accounting 重定義**（L72 實為 800/1000=80%）
- ⬜ **「1,000 heterogeneous agents」→「heterogeneous types」**（Limitation 2 自承類內同質）
- ⬜ **多重檢定句**（35 個 detector runs；Bonferroni(35) 下 p=0.001 仍過、p=0.003 邊緣——一句話就能守住）
- ⬜ **Kyle (1985) 頁碼 1315–1336 → 1315–1335**；`thebibliography` 按字母序
- ⬜ **README metadata 更新**（現「FRL / 15 pages / 16 citations」→ 實際 32 頁 / 21 條 bib；狀態改 VT-only revision）

**驗證 gate**：xelatex 重編譯無誤；上列每項 `grep` 逐條確認。

---

## P1 — 投稿包強化（P0 完成後；部分平行，非 gate blocker）

- **P1-1 cell1 補 80%/90% adoption 點**（M=500，走 compute_queue）——關掉「(70%,100%] 是最寬 gap、最大邊際惡化定位不了」這個 referee 攻擊點（Codex HIGH #3 建議）。
- **P1-2 重生成兩張圖**：Figure 1 改為 K1471 monotone 曲線（無紅綠區帶）+ **新增 money plot：VT vs RR_VT 兩線 overlay（5 cells 小圖陣）**——這張圖就是論文的賣點視覺。
- **P1-3 v6 review round**：paper-review-cycle（latex-academic-reviewer + citation-verifier）+ **Codex adversarial（異模型，必要）**——v4 教訓：同模型自審 GREEN 無效力，跨模型獨立審查應為 stage-gate 硬條件。
- **P1-4 QF 期刊格式 pass**（journal-review skill，target QF）。

---

## P2 — 選配（投稿後或平行；非 gate blocker）— 全 ⬜ TODO

- ⬜ **P2-1 TF/MR viable 參數化重跑**（s∈{1,3}，K1262 表顯示 s=1 時 TF threshold 70% → baseline 應為正）套 K1471 框架——若成，family-level 是**第二篇論文**，不是本篇的附屬品。
- ⬜ **P2-2 Endogenous λ**（stress-dependent liquidity）——Limitation 1 自己點名的最高價值延伸，做了才有 **JEDC 入場券**。
- ⬜ **P2-3 λ 實證量級錨定段落**（對照 empirical price-impact 文獻）——現稿無任何 empirical moment 被 match（λ/γ/V̄/σ_f/κ 全 assumption-based，OAT ±50% sweep 是敏感度非校準）；對 QF/JEBO 這是幾乎確定會被要求的 calibration 補強。

---

## 禁止事項（本篇特有）

- ⛔ **v4「GREEN PASS」已作廢** — 同模型 subagent 自審假陽性**第三例**；不可引用其「90% 淨接受率」錨定，不可視任何 2026-06 前 GREEN 為現狀。
- ⛔ **K1471 TF/MR 不利證據必補報** — applicability gate 擋 TF 4/5 + MR 5/5、RR_TF 5/5 顯著惡化（p=0.001）；漏報 = 選擇性報告（研究誠實 § 不可讓步）。**別再漏**。
- ⛔ **「erosion 不是 crowded flow per se」的無條件版本禁用** — RR_TF 反例在檔；只可寫 **footprint-scale-dependent** 版本。
- ⛔ **家族層（TF/MR）ordering 主張不可用 superseded Sharpe-only detector 當證據** — 同稿不能一邊宣告 detector 循環作廢、一邊拿它輸出當第二貢獻。
- ⛔ **別推 JEDC / JBF / JFE** — tautology 天花板（hardcoded feedback loop 非 emergent）+ 無 empirical calibration 層構不到；JEDC 需 P2-2 endogenous λ 先完成。
- ⛔ **不派 background agent 改寫 `.tex`**（paper-workflow 硬規則，論文寫作與方法論決策留主線程）。
- ⛔ **每個改動數字先讀 `k1471_full_results.json` / `k1471_full_threshold_table.md` 驗證再寫，不臆造**；任何 uniqueness / 計數宣稱必回 current results 重驗（K1416 教訓）。
- ⛔ **provenance 用行首 `%` LaTeX comment，不可用 `\%`**（`\%` 會印字面 repo 路徑到投稿 PDF）。
- ⛔ **不整檔讀** `feed.json` / `knowledge.json`（用 grep / jq / 單檔）。

---

## 進度日誌

```
2026-07-11 | Fable deep review | 深審完成，待執行 P0 | f913ed68c
```

---

## 接續提示詞

讀 `paper/vt-crowding-abm/EXECUTION.md` 後，從 **P0-1** 開始：**敘事單一化 pass**——現稿是新（monotone-erosion）舊（70% tipping-point）雙敘事嫁接稿，同稿互撞至少 5 處，首要動作 = 消除 split-brain（刪 L197 phase-transition 句、§3.4 全段重寫刪 structural break 語言、Figure 1 caption 去紅綠區帶、§3.7 三段式 threshold、§3.6 headline 70%/calibration is exact），完整清單見上方 P0-1。與 P0-1 同批必做：**P0-3 誠實補報 K1471 TF/MR**（gate 失效全表 + RR_TF 5/5 惡化 p=0.001 + footprint-scale caveat「not crowded flow at VT's footprint scale」+ 修 L243 錯誤 gate 敘述）與 **P0-2 scope 收斂 VT-only**（Tables 3/4 + knife-edge 移 appendix、刪 L317 循環校準句、family-level 撤/降級）。本篇 P0 是**純寫作工作量，無需重跑任何模擬**。每項改動的來源數字先讀 `k1471_full_results.json` 驗證再寫，不臆造；修訂在主線程進行（不丟 background agent 改 .tex，paper-workflow 硬規則）。落地後 xelatex 重編譯 + `reproduce.py` 擴充 K1471 兩表轉 green + `paper-update` 同步線上驗證。**期刊改推 QF（primary）→ JEBO**；v4 GREEN PASS 已作廢不可引用。P1-1（cell1 補 80%/90%）是獨立 compute job，可與 P0 平行。

### 進度更新 2026-07-13
- 2026-07-13 | **P0-2 + P0-3 落地（主線程）**：§cross_strategy 重寫 — 新增 tab:tfmr_gate（K1471 gate 全表：TF 4/5 excluded、MR 5/5 excluded、RR_TF/RR_MR 5/5 顯著 p=0.001）；RR_TF 惡化誠實補報；「per se」無條件識別改 footprint-scale-dependent（abstract/intro/L239/§cross 四處）；循環校準錨段刪除；舊 detector 兩表降級 superseded continuity；OAT 17/17 與 family ordering 主張全面撤回（L411/L451/L464）；L243 gate 錯誤敘述修正；abstract \% source 洩漏修復 + 94,500 因式分解修正（27 combos×7×500）。34pp 編譯 0 undefined、pdftotext 零洩漏。
- P0-1 敘事單一化已由背景 session 完成（d37775ac9）。剩：P0-4 reproduce.py K1471 擴充、P0-5 殘餘機械項（52% 歸因、sims 口徑、φ=100%、Kyle 頁碼、README metadata）。

### 進度更新 2026-07-14
- 2026-07-14 | **P0-4 reproduce.py K1471 擴充落地（論文工程 agent）**：三張 K1471 表全欄 binding 進 `reproduce.py`（tab:vt_monotone_curve / tab:matched_control_vt / tab:tfmr_gate）+ abstract 因式分解（94,500=27×7×500）+ RR_TF footprint-scale erosion narrative（TF excluded 4/5、MR 5/5、RR_TF p=0.001 5/5、level-crossing 40–70%、footprint 1.5 vs 0.004–0.008、two orders）。新增 125 條 assertion，binding 全走 K1471 canonical JSON path（caption 舊 path `treatment_results.VT_baseline.cell1` 不存在，已改用 `cells.<cell>.treatments.<treat>.per_adoption`）。gate: **173/173 = 100% green, exit 0**（`--skip-live` 與 live K827v3 rerun 皆同）。report metadata 對齊 VT-only 標題 + QF target + tables_verified 7。
- 2026-07-14 | **P0 全數收官（主線程）**：(1) provenance class sweep——agent 點名 2 處外掃出全類共 7 處印出型內部路徑（含 k1262/k1262b caption），全改「replication package」+ 路徑降 comment，PDF 零洩漏；(2) P0-2 殘留清除——conclusion「as a class」宣稱與 §knife_edge 為已撤回 ordering 辯護兩處改寫為 VT-only；(3) P0-5 機械批次全項落地（§2 redesign-layer 描述、CRN 說法查證後改寫、sims 口徑、Bonferroni(35) 句、Kyle 頁碼、bib 排序、README）。最終驗證：compile 35pp 乾淨、reproduce 173/173 green、PDF 0 內部路徑、家族級主張 grep=0。**P0-1~P0-5 全 ✅；下一 gate = v6 跨模型獨立 review**。
- 2026-07-14 | **v6 跨模型 review 收割 + BLOCKING 全修（主線程）**：verdict BLOCKING（3B+1M+3m），Codex 異模型軌（gpt-5.6-sol，raw transcript 612KB 存證於 review_history/v6_review_20260714/）與 agent code-verification 軌獨立收斂同 3 條 blocking。B1 = 我的 P0-2 grep 用 unicode ≤ 抓不到 LaTeX `$\le$` 假性通過，4 處符號式 family ordering 殘留（L391/413/420/462）全改寫；B2 = RR 配對 fidelity overclaim（「exactly the same per-step volumes」→ 實為 ensemble-moment 配對）— abstract/intro/§2/§3.3 全改 distributional 措辭；B3 = 論文描述的 turnover-cap gate 條件 code 不存在 → 刪除，gate 如實描述為 Sharpe-floor 單條件（排除計數不受影響，floor 驅動）；M1 = 「no internal break」→「no interior break（breakpoint 在飽和邊界）」×5 處；m1 +0.06~+0.09→+0.080~+0.098；m2 Welch Phase-1 來源揭露；m3 README 35pp。修正後：compile 乾淨、gate 173/173 green、雙編碼 family grep 僅剩 3 筆合法歷史描述。**教訓（B1 類）：驗證 grep 必須匹配文件的符號編碼（LaTeX `$\le$`），不是概念（unicode ≤）**。
- **⚠️ 待主線程裁定（main.tex 專屬，agent 不改 .tex）**：P0-4 的 B5+B6 provenance 修復未完成 —— L142 caption 仍寫 JSON 不存在的 `treatment_results.VT_baseline.cell1`，且 **L142 + L214 兩張 table caption 仍用 `\% source:`**（會印字面 `%` + repo 路徑到投稿 PDF；2026-07-13 只修了 abstract）。P0-4 pdftotext 洩漏 gate 因此尚未達成。
