# Fable 深度審查 — eav-universal-magnitude（2026-07-11）

**Reviewer**: Claude Fable 5（深度學術審查 agent，user-assigned P0）
**審查對象**: `paper/eav-universal-magnitude/body.tex`（2026-07-01 build，30 頁）
**對照材料**: README.md（2026-06-11）、review_history/{v1, audit_2026-06-10, v2}、reproduce_report.json（2026-07-06，20/20 green）、experiments/{k1145,k1147,k1150,k1148_d2,k1149,k1172,k1207,k1216c,k1470}
**數字驗證方式**: 本輪獨立抽查 k1207 / k1216c / k1172 / k1470 四組 results JSON 全 MATCH；audit_2026-06-10 已抽查 8 組全 MATCH。無造假疑慮。

---

## 1. 執行摘要

**Verdict: 2 / 5 — NOT SUBMISSION READY；需「重估計 + 敘事重建」級別的 major revision，但底層現象real、值得繼續投入。**

三句話：

1. **Sign universality（三市場 θ_EAV>0、placebo 0/60）站得住**，這是論文最堅固的資產；但 **magnitude ordering（US>JP>TW）站不住**——它不是 normalization-invariant（論文自己的 Table `tab:multistart_lr` canonical θ_rel 欄：JP 1.668 > US 0.415 > TW 0.314，直接反轉 headline），也不是 basin-invariant（K1470 refined θ_EAV 是 canonical 的 10–28×，US refined 值落在 Table 1 自己報的 95% CI 上界之外 19 倍）。
2. Abstract 同時主張「無任何 firm-attribute predictor → market-level constant」與「driver (i) = within-market analyst attention（Harvey |t|=3.8）」——**這兩句話互相矛盾**，而 market-level constant 正是整個跨市場比較的邏輯支柱。
3. §6.3–6.5 的 OOS DM 檢定（k1148_d2 / k1149 的 local `dm_hln`）**完全沒做 HAC**（`var(d)/T` 平白 t 檢定），違反 2026-07-11 生效的 repo DM-HAC 硬規則，且這些站點不在凍結 baseline 內（稽核器盲區）——受影響數字含 binary DM t=−5.58、TW OOS DM −2.48、US −3.31。

---

## 2. 現況盤點

### Pipeline 狀態
- `storage/paper_pipeline_status.json`: stage=**revision**（2026-06-11 進入）、blocker=**finishing**、journal_target=**decide**、last_advance 2026-07-01。
- `storage/next_tasks.json`: 無 pending 的 EAV 任務（multistart 重估 K1470 與 Option A narrative rewrite 均已 succeeded）。

### 各輪 findings 追蹤（v1 2026-05-18 → audit 2026-06-10 → v2 2026-07-06 → 本輪）

| Finding | 首見 | 現況（本輪驗證） |
|---|---|---|
| [CITATION NEEDED] cross-market EAV anchor | v1 SEVERE | ✅ 已修（2026-06-11 誠實降級為 "to our knowledge first"，未捏造引用） |
| θ_rel 雙 normalization 同符號矛盾 | audit HIGH #4 | ✅ 已加 footnote disambiguation（body.tex:976–994）；**但衍生更深問題見 §3-F1** |
| 3-market vs 13-market scope 脫節 | audit HIGH #2 | ✅ Option A 已寫入 abstract/intro/conclusion（boss confirm 2026-06-11） |
| Table 1 single-init FRAGILE 未重估 | audit HIGH #1 | ⚠️ **半修**：K1470 已跑 100-multistart，但 Table 1 數字未改、refined 無 bootstrap/placebo 推論；Table 1 footnote（body.tex:646–658）仍寫「NOT yet re-estimated…open verification item」，與 abstract:85–91 引 K1470「ordering preserved」**直接互相矛盾**（= v2 SEVERE #2，未修） |
| reproduce gate 只蓋 Tables 1–3 | audit HIGH #5 | ❌ 未修：reproduce_report.json（2026-07-06 重跑）仍 20 cells；§6.6 全部數字（k1163/k1172/k1207/k1216c/K1470/multistart LR 表 10 行/Figures 5A–5E）不在 gate 內；4 處 `% source: k1222b_revision_guide.md`（body.tex:887–888,1028,1087,1166）仍綁 markdown 非 JSON |
| Summary stats 表全 `---` + Appendix A placeholder | v1 MAJOR / v2 SEVERE #1 | ❌ 未修，且 body.tex:379–380 footnote 仍把不存在的 Appendix A 當「analytic-gradient verification」引用 = 引用不存在的內容 |
| 市場數口徑混亂（9/10/12/13；172 vs 182） | audit MEDIUM / v2 SEVERE #3 | ❌ 未修：abstract:76–79 說 "13-market" 但只列 12 個（漏 AU）；§6.6 標題 "12-Market"（:861）；:899 同 panel 變 182 obs；:246,:1091 "all 9 audited markets (AU+5 EM+4 DEV)"＝算術上 10；:1140–1141 同一表註先 "All 10 markets" 後 "9/9 FRAGILE" |
| K1149 TW LRT p=0.010 vs Wald t=−0.39 解釋不通 | audit MEDIUM | ❌ 未修（body.tex:808–811 原句仍在） |
| 模型記號問題（τ_t 含 EAV_{i,t-1} 應為 τ_{i,t}；m_i 不在式中；g×τ scale indeterminacy；ε 標準化殘差量綱） | audit MEDIUM / v2 HIGH #4 | ❌ 未修 — **且本輪判定它與 two-basin pathology 可能同根**（見 §3-F3） |
| HLN(1997)、Bollerslev(1986) 缺引；patell_wolfson1979 期刊錯（應為 JAE 1(2) 非 JFE 7(2)） | audit MEDIUM / v2 citation | ❌ 未修（本輪 grep references.bib 確認：無 harvey1997、無 bollerslev；patell_wolfson journal 欄仍是 JFE） |
| 內部工作語言入正文（"FINAL"、"Paper 2 commits…"、"§5.5.4" 懸空引用 body.tex:1083） | v2 SEVERE #4 | ❌ 未修 |
| B=150 bootstrap、EAV timing 敘述模糊、CJK preamble、draft 標記 | v1/audit LOW | ❌ 未修 |

**卡在哪**：2026-06-11 之後只做了 v2 review（7/6），v2 列的 6 項 must-fix 一項都還沒動。實質 blocker 是三件重活：(a) 主表 basin-aware 重推論、(b) reproduce gate 擴充、(c) 全文敘事/口徑重整——全部堆在 "finishing" 底下沒有拆單。

---

## 3. 學術深度檢視

### 3.1 Contribution：universality claim 站得住嗎？

**站得住的部分——sign universality**。三市場 pooled θ̂_EAV>0、cluster-bootstrap |t|∈{4.50,5.24,11.99}、placebo 0/60 each（設計 credible：within-stock date permutation 保留公告次數）。兩個 basin 的 θ 都是正的，所以 sign 結論對 K1470 的 basin 問題免疫。13-market panel 把「不是 US 特例」的外部效度做起來了。**這是論文的護城河，任何改寫都不該犧牲它。**

**站不住的部分——magnitude ordering（headline claim）**，三個獨立的破口：

**F1（本輪新發現，最致命）：ordering 不是 normalization-invariant。**
θ_EAV 是 raw variance 單位，跨市場比較天然被各市場平均變異數水準 confound——論文自己在 §6.6 引入 θ_rel ≡ θ_EAV/σ̄² 正是為了去尺度。但去尺度之後：
- K1163 four-market normalization：US 0.586 > JP 0.388 > TW 0.167 —— ordering 保持 ✓（k1163_results.json 已驗）
- **K1216c pooled-joint canonical（body.tex 自己的 Table `tab:multistart_lr`）：JP 1.668 > US 0.415 > TW 0.314 —— ordering 反轉 ✗**（k1216c_results.json per_market canonical_theta_rel，本輪驗證吻合）
- K1470 refined θ_rel：US 16.4 > JP 7.9 > TW 1.8 —— 保持 ✓（k1470_results.json）

也就是說，US>JP>TW 在論文自己使用的三套尺度中**兩套成立、一套反轉**。2026-06-11 加的 footnote 解釋了「兩套 θ_rel 不可直接比較」，但沒有面對真正的問題：**headline ordering 是 normalization-dependent，而 §6.2 的 institutional 解釋（analyst coverage / earnings-call culture）是對著 raw-scale ordering 講的故事**。依 K1416 教訓（uniqueness/ordering claims 必須對 current result table 重驗），這條 headline 目前驗不過。

**F2（本輪新發現）：abstract 自我矛盾——market-level constant vs within-market analyst attention。**
- Abstract:72–75 / §1 / §6.6 synthesis：「no observable firm-attribute predictor of θ_EAV survives multiple-testing correction → market-level constant」——這是跨市場比較「不被 sample composition confound」的邏輯支柱（§1.2、body.tex:731–734、776–783 都這樣用）。
- Abstract:79–82 / §6.6.1：driver (i) = **within-market** analyst attention，panel-OLS（market FE，識別來自市場內跨firm變異）Harvey |t|=3.79（k1172 已驗），五輪 N-extension 單調上升。
兩句話不能同時成立。技術上的和解點是：TW null chain（K1109 sector ANOVA、K1113 六covariate）**從來沒測過 analyst coverage**（六個 covariates 是 mktcap/beta/earnings freq/volume/vol/momentum），而 N=31 的檢定力遠低於 172-stock panel。誠實的寫法是「六個 pre-registered covariates 內無 predictor；更高檢定力的 172-stock panel 找到 analyst attention」——但這樣一來 **market-level constant 解釋必須撤回或大幅降級**，連帶 §6.2 的 magnitude-ordering 因果敘事要重寫。Referee 在 abstract 就會抓到這一條。

**F3：two-basin / flat-ridge 讓 Table 1 的推論整體失效（audit HIGH #1 只修了一半，本輪往根因推進）。**
K1470（2026-06-11，本輪已讀原始 JSON）：
- TW：LR=1.43 < 3.84 判 STABLE，但 identification_flag=**FLAT_RIDGE**——θ 從 6.36e-5 移到 6.84e-4（**10.8×**）loglik 幾乎不變。「STABLE」是粉飾性的標籤：真相是 **TW 的 magnitude 在一個數量級內不被 likelihood 識別**，任何含 TW 的 ratio 敘事（§6.1 的 "3:1"）都是 basin-dependent（refined basin 下 US/TW ≈ 7.8:1）。
- US：LR=40.6，refined θ=5.34e-3 = canonical 的 **28.0×**，且是 Table 1 報告的 95% CI 上界（2.80e-4）的 **19 倍**。JP：LR=10.8，refined 2.88e-3 = 20.4×，同樣遠出 CI [1.29e-4, 1.76e-4]。**論文報告的 CI 排除了論文自己找到的全域最適估計** —— 這不是 caveat 可以蓋掉的，是推論體系失效。
- Refined 估計只有 Hessian t，**沒有 cluster bootstrap、沒有 placebo、沒有 CI**。現狀是「有推論的點估計在劣 basin、在優 basin 的點估計沒有推論」。
- **根因假說（建議當 P0 驗證）**：g×τ 同時放 free ω_i 與 free θ0 有 scale indeterminacy（audit MEDIUM 早已點名、未修）。Engle & Rangel (2008) 的原始 spline-GARCH 對 short-run component 施加 **unit-variance normalization（E[g]=1）**——論文引用他們卻沒採用其 normalization。flat ridge 很可能就是這條未固定的 scale ray 的症狀；固定 normalization 後 two-basin pathology 可能大幅縮小，屆時「multistart protocol」這個 Contribution #5 也要相應降級（它可能主要是 parameterization artifact 的偵測器，而非普適方法論貢獻）。
- 另一個 K1470 內部疑點：basin B 的 θ 平均 = 0.00999999…，100 starts 有 13–41% 堆在 0.01——這看起來是 **optimizer 上界堆積**，不是真正的第二個 basin。K-means K=2 的「two-basin」修辭在主 spec 上需要重新檢視（初始化是 log-uniform [1e-6, 5e-4]，收斂點卻到 0.01，代表 bound 在 0.01）。

**F4（本輪新發現）：OOS DM 檢定零 HAC——違反 2026-07-11 repo 硬規則，且在稽核器盲區內。**
- `experiments/k1149/k1149.py:742` `dm_hln` 與 `experiments/k1148_d2/k1148_d2.py:562` `dm_hln_stat`：`var_d = np.var(d, ddof=1)/T`，**對 loss differential 完全沒做任何 HAC**（也沒有真正的 HLN 小樣本修正因子；h=1 時該因子≈1 所以名義上無害，但 HAC 缺失是實質的）。
- 依 `.claude/rules/experiments.md` DM-HAC 硬規則：`lag = max(h-1, ceil(h^{1/3}·n^{1/3}))`；h=1 絕不等於可以不做 HAC。K621 教訓：漏 HAC 是**雙向**誤設（負自協方差下修正後 |t| 反而變大）——不可預設「顯著的還是會顯著」。
- **這兩個站點不在 `storage/ops/dm_hac_lag_baseline.json`（133 sites，本輪全量搜尋確認）**：稽核器 AST 掃的是 `range(1,h)` 迴圈 pattern，「完全沒寫 HAC 迴圈」的實作反而漏網——這是 class-sweep 的盲區，應回報給 enforcement owner。
- 受影響的對外數字：§6.5 binary DM t=−5.58 / continuous −5.25（k1148_d2）；§6.4 TW OOS DM −2.48 / US −3.31（k1149）；K1148_d1 TW binary OOS p=0.076（marginal，翻盤風險雙向）。
- 加重因素：panel DM 是 per-stock DM + stock bootstrap 聚合，**同日跨股共同 shock 未處理**（K1355 規則：先按日期聚合再 HAC/DM 才能當 primary claim）。

### 3.2 統計嚴謹度（其餘發現）

- **ρ=+0.379（p=0.20，N=13）被包裝成「structural driver (c)」**：這是 null result。「modestly weaker but surviving」的修辭掩蓋了它從未顯著過（canonical +0.441 p=0.152 也不顯著）。當 contribution 賣，referee 必砍。降為 suggestive/directional evidence。
- **F=689.5（9 df，market-clustered SE，12 clusters）不可信的精確度**：cluster-robust joint Wald 在 G=12、q=9 時嚴重失真（自由度接近耗盡，F 可爆大）。p=7.9e-14 在 12 個 cluster 下不是可辯護的數字。需要 wild cluster bootstrap 或至少誠實 caveat。（數字本身與 k1207_results.json 吻合——問題在方法不在 provenance。）
- **Placebo z=70.7σ（US）**：0/60 的 rejection 是乾淨的；但把 z 報到 70σ 這種天文數字反而暗示 placebo SE 被低估（60 個 permutation 的 SE 估計本身噪音大）。建議只報 0/60 + placebo 分佈圖，z 降級為附註。
- **B=150 bootstrap percentile CI**（30–31 clusters）：偏少，期刊慣例 ≥999（audit LOW，未修）。
- Bonferroni |t|>2.39、Harvey |t|>3 的使用是合格的。

### 3.3 內部一致性
F1/F2/F3 之外：市場數口徑（9/10/12/13）與 N（172/182）混亂、Table 1 footnote vs abstract 的 K1470 狀態矛盾、Appendix A 被引用但是 placeholder、"§5.5.4" 懸空引用、內部工作語言（"FINAL"、"Paper 2 commits"）——v2 已列，本輪逐一在 tex 行號上確認仍在（見 §2 表）。

### 3.4 應該肯定的部分
- 數字 provenance 紀律極佳：兩輪合計 12+ 組抽查全 MATCH，`% source` binding 覆蓋主表。
- 誠實文化到位：continuous-spec 撤回、Round-3 asymmetric artifact 全揭露、selection-bias caveat 自己寫進 §7。這在 revision 裡是資產。
- Multistart 診斷本身（K1213→K1216c→K1470 系列）是有價值的方法論工作——問題只在它被放在「補充貢獻」的位置，卻同時炸毀了主表而沒人回去重建主表的推論。

---

## 4. 風險與致命傷（依嚴重度排序）

1. **[FATAL] F3 — Table 1 推論失效**：CI 排除自家全域最適估計；TW magnitude 不被識別（flat ridge 10.8×）。不修這條，任何期刊的計量 referee 都是直接 reject。
2. **[FATAL] F1 — magnitude ordering 非 normalization-invariant**：論文自己的表格反轉 headline。標題級 claim 驗不過 K1416 規則。
3. **[FATAL] F2 — market-level constant vs analyst-attention driver 自我矛盾**：跨市場比較的邏輯支柱與 panel 的第一驅動因子互斥。
4. **[SEVERE] F4 — OOS DM 零 HAC**：§6.3–6.5 全部 DM 數字需重跑；兼稽核器盲區（流程面要回修）。
5. **[SEVERE] 完成度**：兩個 placeholder 印在 PDF、引用不存在的 Appendix A、reproduce gate 只蓋 1/3 的數字、citation 三處錯漏——這些是「一眼看出沒 finish」的信號，任何 desk editor 都會退。
6. **[HIGH] 貢獻堆疊過寬**（5 個 contributions）：sign universality + panel mechanism 是真貢獻；magnitude ordering 待 F1/F3 裁決；multistart protocol 可能隨 normalization 修正而縮水；ownership ladder 是 null。收斂到 2–3 個。
7. **[結構風險] 若 F1/F3 修完後 ordering 不保**：論文仍然成立——pivot 成「sign universality + within-market analyst attention/sector composition mechanism + normalization/identification 方法論教訓」，其實是更誠實也更耐審的論文。要有這個 Plan B 心理準備，不要把所有敘事押在 US>JP>TW 上。

---

## 5. 接下來的研究計畫

### P0（不做完不得進下一輪 review；預估 2–3 週，前三項是 compute-heavy）

| # | 任務 | 內容 | 產出 |
|---|---|---|---|
| P0-1 | **Normalization refit**（新 K） | 對主 spec 施加 E[g_i]=1（Engle-Rangel canonical）或等效 scale 約束，重推導識別；normalized spec 下重跑 3-market 100-multistart（沿用 K1470 protocol/seeds）。檢驗：flat-ridge/two-basin 是否隨 normalization 消失；同時查 K1470 的 0.01 邊界堆積是否 bound artifact | 決定唯一 canonical scale；magnitude ordering 在該尺度下的裁決（保 → 修表；不保 → Plan B pivot） |
| P0-2 | **Basin-aware 推論重建**（新 K，依賴 P0-1） | 在 normalized+refined 最適點重做 cluster bootstrap（B≥999）+ placebo（每個 bootstrap/placebo refit 內建 ≥10 warm+random multistart）；重寫 Table 1 為 canonical vs refined 對照 + 有效 CI；同步改 abstract / Table 1 footnote（消除 K1470 狀態矛盾） | 新 Table 1 + 一致的 abstract |
| P0-3 | **DM/HAC 重跑**（新 K） | k1148_d2 / k1148_d1 / k1149 的 OOS DM 改用 canonical `volpred.stats.model_evaluation.dm_test`（bandwidth ceil(n^{1/3})）+ 依 K1355 做 date-aggregated panel DM 當 primary；先報 loss differential acf 再下結論。**流程面**：把「無 HAC 迴圈的 local DM」pattern 回報給 dm_hac_lag 稽核器 owner 補盲區 | §6.3–6.5 數字更新；稽核器 patch |
| P0-4 | **Heterogeneity 矛盾和解**（新 K + 改寫） | 在 TW N=31 明確補測 log(analyst)（延伸 K1113 covariate set）；abstract/§1/§6 改寫為「六個 pre-registered covariates 無 predictor；高檢定力 panel 揭示 analyst attention」；撤回或降級 market-level constant 措辭 | 內部一致的 heterogeneity 敘事 |

### P1（submission 前必須；文字/工程層，可與 P0 並行）

- 市場數口徑統一 + **panel provenance table**（一張表列 K1172=12mkt/172、K1207=12mkt/182、K1216c=13mkt Spearman、K1470=3mkt，各自 N/期間/estimator label；v2 HIGH #3 的 estimator 分名一併解決）
- reproduce.py 擴充到 §6.6 全部 cells（K list 見 audit fix_log：k1163/k1165/k1166/k1168/k1171/k1172/k1207/k1213/k1216*/k1173/k1470）+ 4 處 k1222b_revision_guide source 改綁 JSON + 補 K1470 cells → gate green
- 填 summary stats 表（reproduce.py 加 section）；寫 Appendix A（P0-1/P0-2 的 analytic gradient + multistart 材料直接充當內容）；在此之前把引用它的 footnote 改 forward-looking
- Citation 三件：patell_wolfson1979 → JAE 1(2)；+harvey1997（HLN, IJF 13(2) 281–291）；+bollerslev1986；全 bib 補 DOI
- 修 K1149 LRT/Wald 矛盾句（改寫為 likelihood-surface 病態訊號、TW interaction 降 inconclusive——與 F3 敘事自然銜接）
- ρ=0.379 從 "driver" 降級為 suggestive；F=689.5 補 wild cluster bootstrap 或 caveat；placebo z 降級為附註
- 刪內部工作語言 / "§5.5.4" 懸空引用 / draft 標記；貢獻收斂到 2–3 個

### P2（submission 打磨）
- CJK/fontspec preamble 移除（pdflatex 相容）；overfull hbox；B=999 已併入 P0-2
- CA/HK/KR multistart 補齊（消掉 pre-registration disclosure 的懸念）；COVID structural break（conclusion 自己列的）
- 可選 spin-off：multistart/normalization 方法論教訓獨立成短文（Economics Letters / Finance Research Letters methods note）——若 P0-1 顯示 pathology 是 parameterization artifact，這篇短文反而比塞在本文裡更有價值

### 期刊目標建議
- **P0 全過且 ordering 在 canonical normalization 下存活** → **Journal of Empirical Finance**（主推：cross-market empirical + methodology 混合體質最合）；備選 **IRFA**。
- **Ordering 不保、pivot 成 sign universality + mechanism** → **IRFA** 主推（國際市場橫斷面體質合）、**JIFMIM** 備選；FRL 當快出口但會浪費 13-market panel 的厚度。
- **JBF/JoE 暫不建議**：JoE 會對 identification/normalization 窮追猛打（F3 根因就是他們的主場），JBF 對 5-contribution 大雜燴不友善。等 P0-1 結果落地再重評。

---

## 6. Go / No-Go 建議

**投稿：NO-GO（現狀距可投稿還有 P0 四件重活 + P1 一輪）。**
**繼續投入：GO。** 理由：(a) sign universality + placebo 設計 + 13-market panel 是真資產，provenance 紀律好，誠實文化到位；(b) 三個 FATAL 全部有明確、可執行的修法，而且 P0-1（normalization）一件事可能同時解掉 F3 的根因、裁決 F1、並重定 Contribution #5 的價值——投入產出比高；(c) 即使 worst case（ordering 不保），Plan B 論文（universality + mechanism + methodological lesson）依然是一篇誠實且可投 IRFA 級的論文。**下一步的第一張骨牌是 P0-1，建議立即立 K 並派 compute_queue。**

---

*本報告所有引用數字均直接讀自上列 results JSON / tex / report 檔案；k1148_d1 p=0.076 取自 README.md 表格（未開原始 JSON 覆核，標註為二手）。本輪未改動任何 .tex / 共享 JSON，未 git commit。*
