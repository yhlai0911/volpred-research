# Fable 深度審查 — vt-crowding-abm（2026-07-11）

**審查者**: Claude Fable 5（獨立深審，user-assigned P0）
**對象**: `paper/vt-crowding-abm/main.tex`（2026-07-01 版，編譯 32 頁）+ 全部 review_history + `experiments/k1471_vt_crowding_redesign/`
**方法**: 整篇 main.tex 精讀；v5_independent 雙審 + audit_2026-06-10 + K1471 interpretation/Codex review 交叉比對；關鍵數字直接以 Python/jq 讀 `k1471_full_results.json` 逐一核對；RR 控制組實作直接讀 code（`k1471_vt_crowding_redesign.py:239-280`）驗證。
**時間**: ⏱ 2026-07-11 22:13 開始 → 22:55 完成（台灣時間）

---

## 1. 執行摘要

**Verdict：現稿 2/5（不可投稿，MAJOR REVISION 必要）；底層 K1471 證據層 4/5（扎實、可驗證、已過 Codex adversarial review）。**

三句話：

1. K1471 redesign（2026-06-11，94,500 sims）確實修好了 v5 兩位獨立審稿人的實驗層 blocking——外生 sup-Wald detector、coherent-block active control、path-level bootstrap CI——我抽驗的所有論文數字（VT cell1 七點曲線 + CI、matched-control 表 5 cells 全欄、p 值、footprint match）與 JSON **完全吻合**，無造假跡象。
2. 但 `main.tex` 是一份**半改寫嫁接稿**：新的 monotone-erosion 敘事（abstract、§3.1 前半、§3.2、Discussion、Conclusion）與舊的 70% tipping-point 敘事（§3.1 後半、Figure 1、§3.4、§3.5、§3.6、§3.7）在同一份稿內直接互相矛盾至少 5 處，v5 指名的循環校準原文一字未刪。
3. 最嚴重的是 **K1471 的 TF/MR 不利證據被漏報與錯報**：applicability gate 實際擋掉 TF 4/5 cells、MR 5/5 cells（論文只承認 2 個例外）；RR_TF 在 5/5 cells 顯著惡化（p=0.001）卻整篇未報——「footprint per se 無害」的識別主張其實是 footprint-scale-dependent。家族層（family-level）主張在論文自己的新框架下已無有效證據，但結論仍照舊宣稱。

---

## 2. 現況盤點 — GREEN PASS 之後為何停滯、現在還成立嗎

### 2.1 Timeline（全部從檔案與 git 佐證重建）

| 日期 | 事件 | 佐證 |
|---|---|---|
| 2026-04-28 | v4 review：**4.7★ / 0 SEVERE / 0 MAJOR，「READY FOR SUBMISSION」**，預測 FRL 淨接受率 ~90% | `review_history/v4/README.md` |
| 2026-05-21 | v5_independent：Codex **REJECT**（4 blocking）+ Antigravity **REJECT**（4 blocking + 5 major） | `review_history/v5_independent/{codex,agy}_review.md` |
| 2026-06-10 | 全面 audit：確認 v5 的 4 個 blocking「自 4/28 定稿後**一條都沒修**」，verdict MAJOR_REVISION；同時做了 5 組 provenance 抽查（全過）與 21 條 citation 抽查 | `review_history/audit_2026-06-10/audit_findings.json` |
| 2026-06-11 | K1471 redesign 落地（M=500、94,500 sims、runtime 1,756s）＋ Codex adversarial review **CONDITIONAL PASS**（9 findings，無計算/lookahead/seed bug）＋ Codex phase-2 narrative rewrite（abstract/§3.1/§3.2/Discussion/Conclusion） | `experiments/k1471_vt_crowding_redesign/`、README 狀態行 |
| 2026-07-01 | main.tex 最後編輯 + 重編譯（32 頁） | 檔案 mtime、`main.log` |
| 2026-07-01 之後 | **停滯**。v6 review round 從未派發；journal_target 停在 `"decide"`；pipeline blocker=`"finishing"` | `storage/paper_pipeline_status.json` |

### 2.2 為何停滯

三個卡點疊加：(a) narrative rewrite 標了 "pending review" 但**沒有人接著派 v6 review round**——rewrite 只改了頭尾，中段（§3.4–§3.7）留待「最終 polish」而 polish 從未發生；(b) 期刊目標懸置（`journal_target: "decide"`），沒有 target 就沒有 format gate 逼收斂；(c) reproduce gate 未擴充到 K1471，照平台硬規則（reproduce gate 是 review 先決條件）v6 review 本來就不該跑——等於流程自己把自己鎖死。

### 2.3 v4 GREEN PASS 今天還成立嗎

**不成立，且應正式作廢。** 三個理由：(1) v4 的兩位「審稿人」是 Claude general-purpose subagent proxies——同模型自審，v5 兩個異模型（GPT/Codex + Gemini/agy）獨立審查立刻找到 4 個 v4 完全沒看到的 blocking。這是本平台**第三例**「ready 論文被誠實 re-review 撤回」（前兩例見 memory `project_papers_awaiting_submit_decision`）。(2) v4 審的是舊敘事（70% tipping），該敘事已被 K1471 自己推翻。(3) 現稿處於半改寫狀態，內部一致性比 v4 當時更差。v4 的「90% 淨接受率預測」無任何效力。

---

## 3. 學術深度檢視

### 3.1 Contribution — 什麼守得住、什麼守不住

**守得住（K1471 直接支撐，我逐欄驗證）**：

1. **VT monotone erosion**：canonical cell（λ=0.005, γ=200）Sharpe 0.510@10% → −0.271@100%，7 個 adoption 點 + path-bootstrap 95% CI 與 `k1471_full_results.json` `cells.cell1_baseline.treatments.VT_baseline.per_adoption` 完全吻合；相鄰 CI 自 40% 起不重疊；sup-Wald 拒絕 flatness 於 5/5 cells（p=0.001，已驗證），但不定位內部斷點。
2. **Matched-control 機制識別（本文最強、也最有新意的一筆）**：coherent-block turnover-matched 隨機方向對照 RR_VT——footprint 與 VT 實測完全一致（cell1 10%: dw_mean 0.00806 vs 0.00806；100%: 0.00367 vs 0.00367；freq 差 <0.3%，「within 5%」的表註屬實）——在 5/5 cells 零惡化（+0.080~+0.098），而 VT 同 cells 掉 −0.421~−0.899。在 VT crowding 文獻（Baltas 2019 實證、ECB 2020 定性、Barbon-Buraschi 類理論）中，這種「保留 footprint、抽掉方向」的 counterfactual 確實沒有先例——**這是論文真正的賣點，應該當成第一貢獻寫**。
3. 「70%」誠實降級為 descriptive level-crossing（3/5 cells）——這個處理本身是對的。

**守不住**：

4. **Family-level threshold ordering（TF/MR ≤ VT）**——現稿 §3.5/§3.6/knife-edge 的 17/17 robustness 全部建立在 Sharpe-only detector（K1261/K1262/K1262b）上，而論文自己在 §3.1 footnote 宣告該 detector 循環、已被 superseded。同一份稿不能一邊宣告 detector 作廢、一邊拿它的輸出當第二貢獻。且在 K1471 的新框架下（見 §4 B3），TF/MR 的有效證據近乎真空。**家族層主張必須撤或降級**。
5. **「erosion 不是 crowded flow per se」的無條件版本**——RR_TF 反例在檔（見 §4 B4）。可守的版本是「**在 VT 的 footprint 尺度上**，隨機方向零惡化」。

**Tautology 天花板（agy blocking #1，不可修只可框）**：feedback loop 是 hardcoded（Eq. 1–2 + VT rule 閉環），不是 emergent。論文 §3.7 與 Limitation 6 已誠實承認。這條決定了期刊檔次：對 JBF/JFE 級是致命傷；對 ABM 友善期刊（QF/JEBO）「computational laboratory 量化 encoded mechanism 的斜率與識別」是可接受的 framing——前提是把「量化 + 識別」講清楚、絕不暗示 emergence。

### 3.2 模型設計

**優點**：Kyle-λ 線性 impact + 內生 VIX 簡潔透明；lookahead-safe 確認（VT 讀 `vix_series[t-1]`，TF/MR 用 `returns[t-window:t]` 不含 t）；seed 政策完備（K1262b formula + treatment offsets 不重疊、permutation B=999 / bootstrap B=2000 各固定 base seed、字串 hash 用 `zlib.crc32` 避開 per-process randomization）；單元測試 6/6 PASS。

**RR 控制的一個關鍵實作事實（論文沒寫清楚，referee 必問）**：我讀了 `k1471_vt_crowding_redesign.py:269-280`——RR 是 **coherent-block**：整個 block 同一天、同一個 sign、同一個 |Δw| 一起動（單次 rng draw 施加到全體權重向量）。這是**正確**的設計——保留了「協同大額流量」的性質，讓對照真的檢驗到 footprint channel；若是 per-agent 獨立抽號，聚合流量會 √N 抵銷、控制組就無效。但 main.tex §2.1 只寫 "applies the sign of Δw_t from an independent Bernoulli(0.5) draw"，讀起來像 per-agent 獨立——**必須明寫 block-coherent**，否則審稿人會用「你的控制組聚合流量根本不協同」直接打掉識別主張（打錯了，但你給了他打的空間）。

**弱點**：(a) baseline 市場（φ=0）是 iid Gaussian + 線性 impact，excess kurtosis ≈ 0（Table 2 第一列自己的數字）——**無 fat tails、無 volatility clustering、無任何 Cont (2001) stylized fact**；所有厚尾都是 treatment 製造的。ABM 期刊 referee 的標準第一問就是 baseline 像不像真市場。(b) s=10 的 TF/MR 參數化在新框架下自曝其短：TF baseline（10% adoption）Sharpe −0.82~−1.25、MR −0.69~−5.49——**策略在模型裡本身就不可行**，任何 crowding 比較都失去意義。(c) 類內同質（所有 VT agent 同一條 12/VIX 規則）——Limitation 2 已認。

### 3.3 Calibration 嚴謹度 — 哪些 moment 被 match？

**答案：沒有任何 empirical moment 被 match。** λ=0.005、γ=200、V̄=18、σ_f=16%、κ=0.03 全是 assumption-based 設定值；沒有 impact regression 錨定 λ、沒有 VIX-對-RV 斜率校準 γ、沒有對任何實際市場序列做 moment matching 或 indirect inference。OAT ±50% sweep 是**敏感度分析，不是校準**。對 QF/JEBO 這是一個確定會被要求補強的 MAJOR（但通常不是 reject 理由，若 framing 誠實）；對 JEDC 這幾乎是入場券缺失。P2 至少要補「λ 的量級對照實證 price-impact 文獻」一段。

### 3.4 內部一致性 — 最大災區

同一份稿內新舊敘事直接互撞（行號以 2026-07-01 版 main.tex 為準）：

| 位置 | 現行文字 | 與新敘事的矛盾 |
|---|---|---|
| L197 | "consistent with a **phase-transition-like threshold**" | Abstract/§3.1 說無 threshold |
| L201-203 Figure 1 | caption "**VT tipping point**... red-shaded band marks the empirical **tipping zone**; green... **safe zone**" | 圖本身仍是舊敘事的視覺主張 |
| L287 §3.4 | "confirming that the **tipping point between 30% and 50% represents a genuine structural break**"、"the second transition as a distinctly larger structural break" | 直接否定 headline「no internal break」，且 30–50% 與 50–70% 兩處「斷點」跟舊 70% 也對不上 |
| L317 §3.5 | Sharpe-only detector "reproduces **exactly** the 70% threshold... **the primary anchor**" | v5 兩位審稿人指名的循環校準原文，一字未動 |
| L343 §3.7 | "negligible below 30%, become material at 50%, and are **catastrophic at 70%**" | 三段式 threshold 敘事 |
| L357-379 §3.6 | "The **headline 70% VT threshold**"、"**calibration is exact**: cell1 baseline VT threshold is 70%" | K1471 下 VT 的 sup-Wald split 在 100%（grid artifact）、70% 只是 descriptive |
| L425-434 knife-edge | "17/17 robustness checks preserving the ordering" | 全部來自 superseded detector |

另有量化口徑矛盾：Abstract 因式分解「5 cells × 7 levels × 7 treatments × 500」= 122,500 ≠ 宣稱的 94,500（實際 = 7 treatments × **27** 個 cell×adoption 組合 × 500：cell1 七點、cells2–5 各五點）；§2.1 L103 說 adoption grid 是 {0,10,20,30,50,70,100}%，但 Table `tab:vt_monotone_curve` 用的是 K1471 grid {10,30,40,50,60,70,100}%——設計章沒有描述產生 headline 表的實驗設計；§2.4 L125 說 Phase 1 = 14,000 sims，Table 3 caption 說 "10,500-simulation Phase 1 run"（audit 已指出：VT slice 是 K827v3 重用）。

---

## 4. 風險與致命傷

**Blocking（B1–B6，任一不修都不可送審）**：

- **B1 Split-brain 敘事**（§3.4 表列 7 處）。任何 referee 讀到 §3.4「genuine structural break」對上 abstract「identifies no internal break」就結束了。
- **B2 循環校準原文未刪 + 家族層仍靠舊 detector**。v5 codex blocking #1 的指名文句（L317）原封不動；Tables 3/4、knife-edge §、Conclusion 第二 claim 全部以 superseded detector 為證據基礎。
- **B3 K1471 TF/MR 證據錯報**。L243 宣稱 gate 只排除「RR_MR in cell3 + cell2-TF@φ=30%」。實際（`k1471_full_threshold_table.md`，已對 JSON 驗證）：**TF treatment 在 cells 1/3/4/5 全被 `not_applicable_saturated_loss` 擋下（baseline Sharpe −0.82~−1.25），MR 在 5/5 cells 全擋（−0.69~−5.49）**；TF 唯一存活的 cell2 也被 interpretation 文件判為病態 regime（baseline −0.444，曲線 −0.44→−3.16→−1.69→−0.77→−2.74 劇烈非單調）不可引用。且 L243 承諾「Matched-control evidence for TF and MR is reported in §3.5」——§3.5 內 RR_TF/RR_MR 數字**一個都沒有**。
- **B4 RR_TF 不利證據省略（研究誠實層級）**。`k1471_full_results.json` 中 RR_TF 在 **5/5 cells 顯著惡化**（p=0.001，threshold 40–70%，cell1 從 −0.037 掉到 −0.307）。這是「大型協同流量本身有 self-impact 成本」的直接證據（K1471 interpretation 文件自己就是這樣寫的），與論文「erosion is identified to the systematic direction rather than to crowded flow per se」的無條件版本相抵觸——正確的主張是 **footprint-scale-dependent**：VT 的 footprint 很小（|Δw|≈0.004–0.008）所以隨機方向無害；TF-scale footprint（|Δw|≈1.5）隨機方向也有實質侵蝕。這筆不利證據在論文正文完全缺席 = 選擇性報告。
- **B5 Reproduce gate 未覆蓋 headline 表**。`reproduce.py`（4/28）只綁 k827v3/k1261/k1262，**零 K1471 覆蓋**——abstract、Table `tab:vt_monotone_curve`、Table `tab:matched_control_vt` 的所有數字都在 gate 之外，違反平台硬規則「reproduce gate 是 review 先決條件」。且兩張新表 caption 的 binding 路徑寫錯：`treatment_results.VT_baseline.cell1` 在 JSON 裡不存在（實際是 `cells.cell1_baseline.treatments.VT_baseline.per_adoption`）。
- **B6 內部 provenance 字串洩漏到 PDF**。Abstract 與兩張新表 caption 用的是 `\% source: ...`——`\%` 會**印出**字面 `%`，即投稿 PDF 的摘要裡直接出現 `% source: experiments/k1471_vt_crowding_redesign/k1471_full_results.json, total_sims=94,500` 這樣的內部 repo 路徑。binding 應該用純 LaTeX comment（行首 `%`），不是 `\%`。

**Major（audit 2026-06-10 殘留，全數未修）**：52% 歸因方向仍算反（L388：0.13/0.25=52% 是 crowding 殘存份額，liquidity 份額是 48%；Intro/Conclusion 的 "approximately half" 反而對）；iid pooled bootstrap CI 仍是 legacy Table 1 的口徑 + "1.26M days × 500 sims" 重複計數字串仍在（L191）+ Figure 1 caption 口徑仍與表註矛盾；φ=100% 實為 800/1000=80% 的 population accounting 未解（L72）；§3.4 Welch 數字本身無誤（audit 抽驗過）但解讀語言全錯；MR 崩潰 sims 的 `Sharpe=0.0` fallback（`pv>0 else 0.0`，MR 30% × cells 1/4/5 各 500/500）與 1e-23 價格未在論文揭露診斷；35 個 detector runs 無多重檢定討論（p=0.001 過 Bonferroni(35)，p=0.003 邊緣——一句話就能守住，但現在沒寫）；"1,000 heterogeneous agents" vs Limitation 2 自承類內同質。

**Minor**：Kyle (1985) 頁碼 1315–1336 應為 1315–1335；thebibliography 未按字母序；README metadata 全面過期（"FRL / 15 pages / 16 citations" vs 實際 32 頁 / 21 條 bib）；`\thanks` "available upon request" 建議改 repository 聲明（期刊多要求 data availability statement）。

---

## 5. 接下來的研究計畫

### 核心裁決：收斂為 VT-only 論文

家族層（TF/MR）在新框架下證據真空（B3），救它需要在 viable 參數化下重跑整套 K1471（P2），會再拖 1–2 個月且結論未卜。**建議直接收斂為 VT-only**：「VT crowding 的 monotone erosion + matched-control 機制識別」本身是完整、乾淨、有新意的一篇。TF/MR 素材不是丟掉，而是誠實轉述為一節「cross-strategy extension: what the applicability gate reveals」——gate 把 s=10 的 TF/MR 判為模型內不可行，這本身是有資訊量的方法論結果（並附 RR_TF 的 footprint-scale 發現）。

### P0（本週內，主線程 .tex 工作——平台規則：論文寫作不派 background agent）

| # | 工作 | 對應致命傷 |
|---|---|---|
| P0-1 | 敘事單一化 pass：重寫/刪除 L197、Figure 1 caption（圖要重畫，見 P1-2）、§3.4 全段（Welch 數字保留、改為 pairwise 比較敘述、刪 tipping/structural break 語言）、§3.7 三段式 threshold 句、§3.6 "headline 70%/calibration is exact" | B1 |
| P0-2 | Scope 收斂：Tables 3/4 + knife-edge § 移到 appendix 並明標「superseded Sharpe-only detector 的歷史結果，僅作 continuity 參考」或整段刪除；title/abstract/conclusion 對齊 VT-only；刪 L317 循環校準句 | B2 |
| P0-3 | 誠實補報 K1471 TF/MR：gate 失效全表（TF 4/5、MR 5/5 + baseline Sharpe）、RR_TF 5/5 惡化 + footprint-scale caveat（「not crowded flow per se」改為「not crowded flow at VT's footprint scale」）、修正 L243 的錯誤 gate 敘述 | B3、B4 |
| P0-4 | `reproduce.py` 擴充 K1471 section（兩張新表逐欄 binding + match_rate gate）；修 caption binding 路徑；`\% source` 全部改行首 `%` comment | B5、B6 |
| P0-5 | 機械修正批次：abstract 因式分解（7×27×500）、§2.1 補 K1471 grid 描述、52%→48%（或統一 "approximately half"）、14,000/10,500 口徑、φ=100% accounting 重定義、"heterogeneous"→"heterogeneous types"、Kyle 頁碼、bib 排序、README metadata、§2.1 補 coherent-block 描述與 common-random-numbers seed pairing 說明、加一句多重檢定（Bonferroni(35) 下 p=0.001 仍過） | B7 + Major 群 |

### P1（1–2 週，P0 完成後）

1. **cell1 補 80%/90% adoption 點**（M=500，走 compute_queue）——關掉「(70%,100%] 是最寬 gap、最大邊際惡化定位不了」這個 referee 攻擊點（Codex HIGH #3 的 (v) 建議）。
2. **重生成兩張圖**：Figure 1 改為 K1471 monotone 曲線（無紅綠區帶）+ **新增 money plot：VT vs RR_VT 兩線 overlay（5 cells 小圖陣）**——這張圖就是論文的賣點視覺。
3. **v6 review round**：paper-review-cycle（latex-academic-reviewer + citation-verifier）+ **Codex adversarial（異模型，必要）**——v4 教訓：同模型自審 GREEN 無效力，跨模型獨立審查應為 stage-gate 硬條件。
4. 期刊格式 pass（journal-review skill，target 見下）。

### P2（選配，投稿後或平行）

1. TF/MR 在 viable 參數化（s∈{1,3}，K1262 表顯示 s=1 時 TF threshold 70% → baseline 應為正）重跑 K1471 框架——若成，family-level 是第二篇論文，不是本篇的附屬品。
2. Endogenous λ（stress-dependent liquidity）——Limitation 1 自己點名的最高價值延伸，做了才有 JEDC 入場券。
3. λ 的實證量級錨定段落（對照 empirical price-impact 文獻）。

### 期刊推薦與時程

| 選項 | 判斷 |
|---|---|
| **主推：Quantitative Finance（QF）** | simulation/microstructure/crowding 的天然家；對「encoded mechanism 的量化 + 識別」framing 接受度高；不受 letter 長度限制，TF/MR gate 一節與 appendix 放得下；中等審稿速度 |
| **次推：JEBO** | mechanism-quantification ABM 傳統深；容忍 stylized model；缺點是審稿慢、對 baseline stylized facts 可能追打 |
| **快軌備選：FRL（現 target）** | 要壓到 letter 長度就必須 VT-only + 砍 appendix；速度與曝光優先時選這。注意 v4 的「90% 接受率」預測作廢，不要帶入錨定 |
| **不推：JEDC** | 無 emergence、無 learning、無 empirical calibration，hardcore ABM referee 會用 Brock-Hommes/Franke-Westerhoff 標準打；P2-2 完成前不要去 |
| **不推：JBF/JFE** | tautology 天花板 + 無實證層，構不到 |

**時程**：P0（~1 週內完成，主線程 2–3 個工作段）→ P1-1/1-2 平行（compute ~1 天 + 圖 1 段）→ v6 review（1 週）→ 若綠：**2026-08 上旬可投 QF**（或決策 FRL 快軌）。

---

## 6. Go/No-Go 建議

- **No-Go：現稿投任何期刊。** B1–B6 任一條都足以 desk reject；六條齊發等於送分。
- **Go：這篇論文值得救，而且離救活不遠。** 底層 K1471 證據是本平台少見的「redesign 真正回應了審稿人」案例：外生 detector、coherent-block active control、path-level CI、固定 seed、單元測試、Codex adversarial CONDITIONAL PASS、interpretation 文件把可主張/不可主張邊界寫得清清楚楚——**問題只在 main.tex 從未被完整帶到與證據一致的狀態**。P0 是純寫作工作量（無需重跑任何模擬），P1-1 是一次 compute_queue 排程。
- **治理教訓（建議寫入 error_log / pipeline gate）**：(1) v4「GREEN PASS」= 同模型自審 proxy 假陽性，本平台第三例——跨模型獨立審查應成為 ready 判定的機械 gate；(2) 「narrative rewrite 完成 → pending review」這種半成品狀態掛了 30 天沒有自動催動——pipeline 的 stall detector 應把 `blocker=finishing` 超過 N 天視為 alert。

---

*所有引用數字均直接讀自 `k1471_full_results.json`、`k1471_full_threshold_table.md`、`main.tex`、review_history 各檔；RR 實作結論來自直接閱讀 `k1471_vt_crowding_redesign.py:239-280`。未能驗證的項目已標明（無）。本審查未改動任何 .tex / 共享 JSON，未做 git commit。*
