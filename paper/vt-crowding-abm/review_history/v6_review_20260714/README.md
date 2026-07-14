# v6 跨模型獨立 review — vt-crowding-abm

- **日期**：2026-07-14（台灣時間）
- **審查對象**：`paper/vt-crowding-abm/main.tex`（P0 收官後的 VT-only 稿，35pp，623 行）
- **canonical 證據**：`experiments/k1471_vt_crowding_redesign/{k1471_full_results.json, k1471_vt_crowding_redesign.py, README.md}`
- **git 版本**：`ea191161e paper(abm): P0 complete`（main.tex 為 P0-done 狀態，無未 commit 變更）
- **軌別**：Codex adversarial（決定性軌，異模型 gpt-5.6-sol）+ 本 agent referee 模擬（補充軌，**same-model，不作決定性依據**）+ compliance 預檢
- **本 review 唯讀**：未修改 main.tex 或任何 JSON。

---

## 總 verdict：**BLOCKING**（3 BLOCKING + 1 MAJOR + 2 MINOR）

**DoD 之「v6 review 通過 0 blocking」未達成。** 兩條獨立軌（Codex 異模型 + 本 agent 對 ground-truth code/JSON 的獨立核對）**各自獨立收斂到 BLOCKING**，blocking findings 完全一致（B1/B2/B3）。

關鍵定性：**底層 K1471 證據層仍然扎實**——三張 headline 表逐格吻合 JSON、compliance 乾淨、detector/seed/lookahead 政策健全。**全部 3 條 blocking 都在手稿的「方法描述接線層」**，其中 B2、B3 是**研究誠實級**問題（論文描述了 code 沒有實作 / 過度宣稱 fidelity 的方法細節），觸及「腳本／資料／論文三方一致」硬規則。這正是 P0 之後、同模型自審抓不到、必須跨模型 + 對 code 核對才浮現的一類缺陷——驗證了本篇 DoD 堅持「同模型自審不算」的必要性。

| 級別 | 編號 | 一句話 | 誰抓到 | 對 ground truth 核實 |
|---|---|---|---|---|
| BLOCKING | B1 | 符號式「TF/MR $\le$ VT」家族 ordering 殘留，與撤回敘事矛盾（split-brain） | Codex + 本 agent | ✅ grep main.tex |
| BLOCKING | B2 | RR 配對 fidelity 被 overclaim（「exactly the same per-step volumes」），實為 ensemble-moment 配對 | Codex + 本 agent | ✅ 讀 code |
| BLOCKING | B3 | 論文描述的兩段式 applicability gate 之 turnover-cap 條件在 code 中不存在 | Codex + 本 agent | ✅ 讀 code |
| MAJOR | M1 | detector「no internal break」措辭與 JSON `breakpoint_split_after`/`threshold` 不精確 | Codex + 本 agent | ✅ jq JSON |
| MINOR | m1 | intro RR「+0.06 to +0.09」≠ 表值 +0.080~+0.098 | Codex + 本 agent | ✅ jq JSON |
| MINOR | m2 | §Statistical S₅₀=0.336/S₇₀=0.084 取自 Phase-1，非 redesign 的 0.338/0.091，未揭露 | Codex + 本 agent | ✅ jq JSON |

**已核對後撤回 / 判定無問題**（避免假陽性）：seed L104 vs L126（**相容，非矛盾**）、emergence framing（乾淨）、三張核心表（逐格吻合）、compliance（乾淨）、tipping／per se／散文層 family-level（P0-1/P0-3 確實達成）。詳見下方各節。

---

## BLOCKING findings（各附行號 + 修法）

### B1 — scope split-brain：符號式家族 ordering 主張未清除

P0-2 宣稱「family-level 主張 grep=0」，但其驗證 grep 用 unicode `≤`，**抓不到 LaTeX 的 `$\le$`**，故假性通過。實際殘留 4 處：

- **L391**（§oat 開頭）：「The VT erosion … and **the cross-strategy ordering TF/MR $\le$ VT documented in \S\ref{sec:cross_strategy}** could in principle be artifacts…」— 宣稱 §cross_strategy「documents」此 ordering，但 §cross_strategy（L300/L330）恰恰**撤回**它。直接內部矛盾。
- **L413**（footnote b）：「**The directional ordering TF/MR $\le$ VT is preserved under both MC settings**」— 主張式。
- **L420**（§oat findings）：「the joint robustness surface comprises 17 distinct parameter-perturbation checks …, **all preserving TF/MR $\le$ VT**. The critique that a single $(\lambda,\gamma)$ choice manufactures the 70\% threshold is therefore **not supported by the data**.」— 這是全稿**最強的家族 ordering robustness 主張**（17 檢查全過），也重新為「70% threshold」辯護，與 monotone-not-tipping 主旨相衝。並且與**同一子節** L418「draw **no family-level ordering conclusion** from them」**自我打架**。
- **L462**（Limitations 收束）：「whose **ordering (TF/MR $\le$ VT) is robust** to the tested specification choices—is more robust than any single numerical threshold.」— 主張式。

與 abstract L36（「family-level ordering claims are withdrawn」）、§cross_strategy L300/L330（「we withdraw it as evidence of class-level crowding」「confine the paper's mechanism claims to VT」）**直接矛盾**。referee 讀到 §oat/Limitations 會看到論文一邊撤回、一邊 17 檢查力挺同一 ordering。

**修法**：刪除或改寫 L391/L413/L420/L462 的 `TF/MR $\le$ VT`；§oat 整節（sec:oat, L388–420）與 knife-edge 節（L464–471）需從「捍衛 70% threshold + 家族 ordering」的舊框改寫為「VT monotone 形狀對 λ/γ 的 robustness」。§oat findings 段（L418–420）的第三句與 L420 全句應對齊 L418 的「draw no family-level ordering conclusion」。

### B2 — RR matched-control 配對 fidelity 被 overclaim（研究誠實）

**論文宣稱**：
- L99：「the matched-control RR\_$X$ … **inherits, at every step $t$, the per-step weight-change magnitude $|\Delta w_t^X|$** and rebalancing frequency … realized by the corresponding $X$ treatment **in a paired simulation**」
- L243：「Because RR\_VT **trades exactly the same per-step volumes as VT** but selects the trade sign by coin flip」

**code 實況**（`k1471_vt_crowding_redesign.py` L240–282, L816–845）：`RandomRebalanceAgent` 只接收三個**標量** `freq / dw_mean / dw_std`（stage-1 對 (cell, adoption) 量測的 ensemble turnover 摘要）。每個 rebalance 日：以獨立機率 `freq` 觸發、方向 ±1 各半、`|Δw| ~ lognormal(ln_mu, ln_sigma)`（參數配到該 strategy 的 **mean/std**）。**沒有**逐步、逐路徑重用 X 的實際 `|Δw_t|`；rebalance 日也非 X 實際 rebalance 的同一天。

即實為 **cell×adoption ensemble-moment 配對**（lognormal(mean,std) + 頻率），**非逐步逐路徑**。L243「exactly the same per-step volumes」是 **code 不支持的不實宣稱**，且這句是「matched-control identification」（本文最強貢獻）的因果推論核心。更矛盾的是 L237 已有**誠實版**：「realized RR\_VT footprint (mean $|\Delta w|$, rebalance frequency) is within 5\% of the corresponding VT treatment footprint」——同稿並存 overclaim 與 honest 版。

**修法**：把 L99/L243 改為「distributional / ensemble-moment matched（頻率 + `|Δw|` 的 mean/std 配對，within 5%）」，並相應**弱化因果措辭**（不可寫「exactly the same volumes」「trades exactly」）。若要保留逐步同量的強宣稱，必須**重跑**真正逐路徑 common-footprint 版本。abstract/intro 的「replicating VT's trading footprint」「matches the offending strategy's trading footprint」也應加 distributional 限定詞。

### B3 — 論文描述的 turnover-cap applicability gate 在 code 中不存在（研究誠實）

**論文宣稱**（L101）：applicability gate 有**兩個**條件——(i) baseline-Sharpe floor `> -0.5`，**且 (ii) turnover-cap check**：「no more than 10\% of MC simulations have $|\Delta w_t^X|$ exceeding the clip rail at $>20\%$ of trading days」。L237 進一步宣稱五 cell「satisfy the matched-input applicability gate: baseline-Sharpe floor $> -0.5$, **footprint turnover within clip rail at $>80\%$ of MC days**」。

**code 實況**（`detect_threshold_exogenous`, L500–535）：gate 只有**一個**條件——`base_mean < APPLICABILITY_FLOOR (= -0.5)` → `not_applicable_saturated_loss`。全 code grep 無任何 turnover-cap / clip-rail / 10%-of-sims / 20%-of-days 邏輯。即**論文描述了一個未實作的 gate 條件**，且宣稱各 cell「satisfy」它。

**修法**：二擇一——(a) 在 code 實作 condition (ii) 並重跑（確認 gate 結論不變）；或 (b) **刪除** L101 condition (ii) 與 L237 的 turnover-cap 宣稱，如實描述 gate 只有 Sharpe floor 一條。若選 (b)，需檢查是否影響任何「gate 排除 TF 4/5、MR 5/5」的計數（該計數由 Sharpe floor 驅動，預期不受影響，但須明記）。

---

## MAJOR

### M1 — detector「no internal break」措辭不精確

L136 / L138 / L199 / L478 稱 sup-Wald「rejects flatness but **identifies/locates no internal break**」。但 JSON `.cells.cell1_baseline.detector.VT_baseline` 明含 `breakpoint_split_after = "70%"`、`threshold = "100%"`、`degradation_direction = true`、`threshold_bootstrap_freq {"100%": 1.0}`。detector 機械上**確實回報了一個 argmax 斷點**（落在最後區間 70%→100%，即飽和邊界 100%）。「no internal break」措辭易被 referee 抓為與自家 JSON 矛盾。

**修法**：改為「the single sup-Wald breakpoint **localizes to the saturation boundary (after 70\%, i.e. the 100\% endpoint)**, and the path-bootstrap concentrates there, consistent with accelerating monotone erosion rather than an **interior** regime switch」。L136 footnote 已有一半這個論述（permutation null 測 flatness 非 break），把「no internal break」統一改為「no **interior** break / break localizes to the boundary」即可，內容不需重跑。

---

## MINOR

- **m1（L60）**：intro 稱 RR\_VT「improves by **$+0.06$ to $+0.09$**」，但 matched_control_vt 表（L228–232）實際 Δ 範圍為 **+0.080 ~ +0.098**（min 為 cell3 +0.080，非 +0.06）。改為「+0.08 to +0.10」或「+0.080 to +0.098」。
- **m2（L295）**：§Statistical 用 $\bar S_{50\%}=0.336$、$\bar S_{70\%}=0.084$，但 redesign canonical cell（JSON）為 **0.338 / 0.091**。0.336/0.084 rounds to Table~\ref{tab:main} 的 0.34/0.08，即取自 **Phase-1 M=500 baseline** 而非 redesign 層，且未揭露兩 run 不同。建議統一用 redesign 數字重算 Welch t，或明記「Welch t 在 Phase-1 cross-treatment run 上計算」。
- **m3（README metadata）**：`README.md` 寫「Pages: 34」，實際 `main.pdf` 為 **35 頁**。微調。

---

## 決定性軌：Codex adversarial review（異模型 gpt-5.6-sol）

- **命令**：`printf '%s' "$(cat <prompt>)" | bash scripts/codex_exec_bounded.sh --timeout <N> -s read-only -`（唯讀 sandbox，中文 prompt via stdin）
- **codex-cli**：0.144.1，model `gpt-5.6-sol`，reasoning effort `ultra`
- **raw transcript（durable 證據）**：`paper/vt-crowding-abm/review_history/v6_review_20260714/codex_raw_transcript.txt`（含兩次 run 全程）

### 誠實聲明：兩次 run

1. **Run 1（13:14:04–13:23:04，session `019f5f0c`）**：Codex 自行 fan-out 出多個平行子審查（(a)-(c)/(d)/(e)），在 540s watchdog 前**未收斂出最終結構化 verdict**（transcript 結尾停在「等待數字獨立審查回報後定稿」）。**但已浮現實質發現並存檔**：明確指出「scope split-brain」「detector 誤述」，並額外抓到「RR control 並非逐路徑／逐日精確配對，而是 cell×adoption ensemble moments 配對」「turnover-cap gate 在 K1471 code 中不存在」——即 B2/B3 的種子。
2. **Run 2（13:26:25–13:29:23，session `019f5f17`，聚焦重跑，禁 fan-out、單 pass、只要 verdict）**：**成功輸出最終結構化 verdict**（89,228 tokens）。

### Codex 最終 verdict（verbatim，Run 2）

```
總 verdict = BLOCKING
[1] CONFIRM：L391/413/420/462仍稱TF/MR≤VT，與L36、300/330、418撤回說衝突。
[2] CONFIRM：RR僅按cell×adoption之freq/均值/SD重抽；L99/243逐步同量不實。
[3] CONFIRM：code僅Sharpe floor，無turnover-cap gate。
[4] REJECT：VT/TF/MR offset皆0；僅RR分流，L104/126相容。
[5] CONFIRM：JSON為split_after=70%、threshold=100%；應稱邊界argmax。
[6] CONFIRM：RR Δ=.080–.098；S50/S70=.338/.091，稿值皆錯。
[7] REJECT：L122/381/456明稱機制encoded，無emergent暗示。
[8] REJECT：VT10=.510、RRVT cell1 Δ=.093、TF cell1=-.825均合JSON。
BLOCKING findings：[1][2][3]；刪ordering；RR改稱ensemble-moment matched並弱化因果（或重跑逐路徑）；實作turnover gate重跑，否則刪除。
```

Codex 的 `[1][2][3] CONFIRM = blocking`、`[5] CONFIRM = major`、`[6] CONFIRM = minor` 與本 agent 獨立結論**完全一致**。`[4][7][8] REJECT` 也與本 agent 對 code/JSON 的獨立核對一致。

### 對 Codex `[4] REJECT`（seed）的獨立採信說明

本 agent 初判 L104（CRN pairing across VT/TF/MR）與 L126（treatment/control disjoint）為矛盾，列為候選 MAJOR。Codex 讀 `TREATMENT_SEED_OFFSET` 後 REJECT。本 agent 隨即**親自核對 code ground truth**：
```
TREATMENT_SEED_OFFSET = {'VT_baseline':0,'TF':0,'MR':0,'NoiseControl':0,
                         'RR_VT':7000003,'RR_TF':7100003,'RR_MR':7200003}
```
VT/TF/MR offset 皆 0 → 主 treatment 間 seed **確實 paired**（L104 正確）；只有 RR 控制有 offset + 專屬 RNG stream（`RR_RNG_OFFSET=10000019`）→ 與 matched treatment **disjoint**（L126 正確）。兩句描述不同對象、**互相相容**。**本 agent 撤回此候選 finding**，採信 Codex + 自核。（此為 cross-model review 有效性的正面例證：異模型 reject 掉了主軌的一個假陽性。）

---

## 補充軌：本 agent referee 模擬（same-model，非決定性）

以 QF referee 視角，methods / 圖表 / 對齊 / 檢定 / bib 面（不重複上方 code/JSON 級 findings）：

- **Methods 完整性**：模型設定完整（Eq. price/vix/vt/tf/mr、Kyle-λ、endogenous VIX、noise trader、seed/lookahead 政策）。主要缺陷即 B2/B3 的方法描述層。§2.4 三層 phase（46,800）+ redesign 層（94,500）口徑一致；conclusion L478「46,800 + 94,500」對齊。
- **圖表**：`figures/fig_monotone_erosion.png`（2026-07-13 重生，無紅綠區帶）與 `fig_kurtosis_spike.png` 皆存在且被引用；舊 `fig_tipping_point.png` 仍在資料夾但**未被 `\includegraphics` 引用**（superseded artifact，無害）。**P1-2 的「VT vs RR_VT overlay money plot」尚未加入**——非 blocking，但那是本文賣點視覺，投稿前強烈建議補（referee 會期待看到 identification 的視覺化）。
- **abstract / intro / conclusion 對齊**：三者均為 VT-only monotone 框架、互相一致。**唯一不對齊處是 §oat + Limitations（B1）**——中段仍殘留舊家族 ordering 框。
- **多重檢定句**：L136 已含 Bonferroni(35)（`35×0.001=0.035<0.05`）+ p=0.003 邊緣不採信之聲明 ✅。L291–295 Welch t 用法說明（vs DM）合理 ✅（惟 m2 數字來源問題）。
- **bib**：22 bibitems，`thebibliography`按字母序 ✅，主要期刊條目附 DOI ✅。Kyle(1985) 頁碼 1315–1335 已修 ✅。

---

## Compliance 預檢（QF gate 前置）

| 項目 | 結果 |
|---|---|
| Author | ✅ 僅 `Yi-Hao Lai`（L25，Da-Yeh University），無共同作者 |
| volpred / AI / LLM / Claude / Codex / GPT / anthropic / openai / gemini 字樣 | ✅ **全文零殘留**（grep -niE 全 miss） |
| Acknowledgements（L483–486） | ✅「All methodological choices and the final manuscript content are the author's responsibility.」— 無 AI 協作、無機構致謝洩漏 |
| Provenance 洩漏（`\% source:` / repo 路徑印入 PDF） | ✅ 全部為行首 `%` LaTeX comment（不印入 PDF）；P0-4 class sweep 已處理，PDF 零內部路徑 |
| `\thanks` 資料可及性聲明（L23） | ✅「Simulation code and replication data are available upon request.」 |

Compliance 預檢 **PASS**（無 blocking）。惟須注意：QF 若要求 replication package，B2/B3 的「論文↔code 不一致」會在 package 審查時被發現，故 compliance-clean **不代表**可送——B1/B2/B3 必須先修。

---

## P0 已確實達成的部分（正面核實，非空過）

- **P0-1 敘事單一化**：全稿 `tipping / structural break / safe zone` 殘留**全部為合法用法**（否定式「rather than a discrete tipping point」、研究問句、或明標 superseded 的歷史指涉）。abstract/§3.1/Figure 1 caption 已單一化。✅
- **P0-3 誠實補報 + per se**：`tab:tfmr_gate` 在稿、RR_TF 5/5 惡化補報、footprint-scale caveat 到位；三處「per se」**全為 liquidity-attribution 合法用法**，無「not crowded flow per se」無條件識別殘留。✅
- **三張 headline 表逐格吻合 JSON**（本 agent 全表核 + Codex 抽核）：`tab:vt_monotone_curve`（7 點 mean+CI）、`tab:matched_control_vt`（5 cell VT/RR_VT）、`tab:tfmr_gate`（TF/MR/RR baseline）——**零造假跡象**。「cells 1/4/5 的 MR baseline 同為 −1.776」經核為真實性質（同 λ=0.005、10% adoption 下 γ 幾乎不影響 MR baseline），非 bug。✅
- **reproduce gate** 173/173 green（依 EXECUTION.md P0-4 記錄）。✅

---

## 結論與下一步

v6 review **未通過 0-blocking gate**。**底層研究無問題**（K1471 證據扎實、數字真實、compliance 乾淨），3 條 blocking **全在手稿方法描述接線層**且**純寫作 / 小重跑可解**：

1. **B1**：刪 4 處符號式 `TF/MR $\le$ VT` + 改寫 §oat/knife-edge 舊框（純寫作）。
2. **B2**：L99/L243 改「ensemble-moment matched」+ 弱化因果措辭，對齊已在稿的 L237 誠實版（純寫作；若要保「逐步同量」強宣稱才需重跑）。
3. **B3**：刪 L101 condition (ii) + L237 turnover-cap 宣稱，如實描述 gate 只有 Sharpe floor（純寫作；或實作 gate 重跑）。
4. M1/m1/m2/m3：措辭精確化 + 兩處數字對齊 redesign JSON + README 頁數。

修訂在主線程進行（`.claude/rules/paper-workflow.md`：不派 background agent 改 .tex）。落地後重編譯 + 重跑本 v6 review（0-blocking）才可進 QF compliance gate 與 paper-update。**B2/B3 是研究誠實級，修完必須跨模型複核，不可同模型自審放行。**
