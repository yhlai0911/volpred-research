# Paper 9 (garch-x-vix) — Fable 深度審查 2026-07-11

**Reviewer**: Claude Fable 5（頂級期刊 referee 水準深度檢視，user-assigned P0）
**Scope**: `main.tex`（1,135 行全篇）+ `mcs_dm_results.json` canonical 對照 + `errata_pending.md` + `reproduce_report.json`（2026-07-09）+ review_history v6/v7 + `r1_response_queue.md` + audit_2026-06-10 + K988/K988b/K994/K995/K997/K1003/K1023/K1027/K1045/K1391/K1393 實驗檔 + `storage/ops/dm_hac_lag_baseline.json` + `storage/paper_pipeline_status.json`
**方法**: 每個引用數字實際讀自檔案；無法驗證處標「未驗證」。未改動任何 .tex / 共享 JSON；未 git commit。

---

## 1. 執行摘要

**Verdict: 2.5 / 5（現狀不可投稿；完成本報告 P0 修正後可達 4/5，IJF 有實質錄取機會）**

三句話：

1. **實證核心是健全的**——canonical 統計機械（`compute_mcs_dm.py`、K1393、K994/K997 走 `volpred.stats.model_evaluation.dm_test`）全部使用正確的 n^(1/3) 級 HAC bandwidth，不在 2026-07-11 DM-HAC 凍結 backlog 的 139 個退化站點內；VaR 表（K995）、VRP 相關表（K988b）、殘差診斷（K1045）、敏感度表（K1003）逐格抽查全數吻合；MCS/B1 的誠實框架（「A4f 與最佳 MIDAS 統計上不可區分，賣點是簡約」）是這篇論文最值得保留的資產。
2. **手稿層是不健全的**——Table 3 的 C1 值 3.49 無任何來源（canonical 1.995，Harvey 由 Yes 翻 No）、A3f/B2 兩處 Harvey 質性標錯、headline 4.03 的來源宣稱為偽（main.tex:723 稱出自 `mcs_dm_results.json`，該檔實存 4.148）、§5.9 宣稱測了六個總經變數但 K1001 只跑了兩個、`acerbi2019` 是嵌合引用（標題屬 Du & Escanciano 2017 MS）、pairwise DM 表符號慣例註記與數字相反。這些全是 referee 一眼可見、無需重跑即可抓到的問題。
3. **Pipeline 卡住的真正根因是一個假前提**——全部修正（`r1_response_queue.md` Q1–Q5 + v7 P1–P3）被「body frozen until R1 reviewer response」政策擋住，但 `storage/paper_pipeline_status.json` 2026-07-10 更正記錄（owner Telegram msg 331/340）確認**本論文從未投稿任何期刊**，沒有 reviewer 會來。凍結政策 = 無限期自我封鎖。解法不是等 sign-off，是立即解凍、把整份 queue 落地到 body。

---

## 2. 現況盤點

### 2.1 v7 verdict（2026-06-05 Codex adversarial，過去未被主線程消化——現正式消化）

`review_history/v7/codex_adversarial_review_2026-06-05.md` verdict = **`revision_required`**，4 findings：

| # | Severity | Finding | 現狀（2026-07-11 驗證） |
|---|---|---|---|
| 1 | HIGH | Replication metadata（README/reproduce_report）stale、與 body 矛盾 | 部分修（2026-06-10 README headline qualified），但 README 首行仍寫「submitted (under review)」= 虛假狀態；reproduce mismatch 仍在 |
| 2 | MED-HIGH | "statistically non-inferior" 過強（main.tex:806, 813） | **未修**——本次全篇重讀確認兩處原句仍在 |
| 3 | MED-HIGH | g_t 與 g-proxy 概念混淆（abstract/intro/conclusion vs §6） | **未修**——且本次審查發現問題比 v7 所述更深（見 §3.4） |
| 4 | MED | Conclusion 五之七未對齊自家 Bonferroni caveat（main.tex:911） | **未修** |

v7 的整體判斷「不再是 core model invalid，剩 claim discipline / packet consistency」**與本次獨立審查一致**，但 v7 之後的 audit_2026-06-10 又追加了 5 個 BLOCKING（Q1–Q5），全部被凍結政策擱置至今。

### 2.2 A4f errata（4.03 vs 4.148）現況與裁定

**現況**：SPY A4f-vs-GJR DM t 有三個 vintage——4.030（drafting，pre-2026-04-19 yfinance）、4.148（2026-04-19 pinned snapshot，canonical `mcs_dm_results.json`）、4.293（2026-07-09 live）。Harvey |t|>3 三者皆過，質性不變。`errata_pending.md` 的架構是「shelf errata、等 R1 才動 body」，pipeline blocker 寫「awaiting owner sign-off」。

**裁定：errata 機制整個作廢，改為直接修訂手稿。**理由：

1. Errata 是「已發表/已投稿的文獻的更正機制」。本論文**從未投稿**（`paper_pipeline_status.json` stage_correction_note 2026-07-10：owner 明示 no paper is actually submitted，先前 under_journal_review 標籤 aspirational/false）。對一份未投稿的手稿，「errata + body freeze」是範疇錯誤——正確動作就是改稿。
2. 不存在需要 owner sign-off 的決策點：老闆 2026-07-09 授權（memory `feedback_paper_autonomy_optimize_acceptance`）論文修訂自主執行。
3. **具體落地**：全文統一改用 canonical pinned-snapshot 值（4.03→4.148；Table 3 全表由 `mcs_dm_results.json` 重生；下游 lines 52/80/723/776/905 同步），資料節加一句 vintage 聲明（「所有數字出自 2026-04-19 pinned yfinance snapshot，隨附 replication package」）。這同時解掉 reproduce gate 唯一的 mismatch（match_rate 85.7% yellow → 預期 100% green），滿足 paper-workflow 硬規則 2（reproduce green 是 review/submit 先決條件）。`errata_pending.md` 降級為歷史 audit trail，加 SUPERSEDED 頭註。

### 2.3 Reproduce gate 現況

`reproduce_report.json`（2026-07-09，snapshot-first）：7 scored / 6 match / **match_rate 85.7% / alert yellow**。唯一 mismatch 就是 4.03 vs 4.148。另有 6 個 skipped（需 --live）。警告欄明載 `readme_status_mismatch`（README 宣稱 under review vs 實際未投稿）。→ §2.2 裁定落地後 gate 可轉 green。

---

## 3. 學術深度檢視

### 3.1 Contribution 評估（相對文獻的增量）

**核心主張**：當外生變數本身就是日頻（VIX）時，GARCH-MIDAS 的混頻 Beta-polynomial 機械是冗餘的；最簡單的日頻乘法規格 A4f（τ_t = θ₀+θ₁VIX²_{t-1}，free ω）點估計最優、與最短 lag MIDAS（B1, K=22）統計不可區分、顯著勝過長 lag MIDAS（K≥65）。

**這個「簡約論」contribution 是真實且乾淨的**，MCS 誠實框架（α=0.10 全 17 模型存活、只有 GJR 在 α=0.25 被剔除）讓它站得住。但相對文獻的定位有三個缺口：

1. **最近的先行文獻未被引用（referee 必抓）**：
   - **Kanniainen, Lin & Yang (2014, J. Banking & Finance)** "Estimating and using GARCH models with VIX data"——與本文最接近的先行者（GARCH 納入 VIX 資訊、S&P 500）。未引用。這是投 JEF/IJF 都躲不掉的對照。〔未驗證：憑審查者文獻知識，需 citation-verifier 確認卷期〕
   - **Blair, Poon & Taylor (2001, J. Econometrics)**——VIX（VXO）對 S&P 100 波動率預測增量資訊的經典。未引用。
   - **Amado & Teräsvirta (2013, J. Econometrics)** 乘法時變 GARCH——與 Engle-Rangel (2008) spline-GARCH 並列的乘法分解直系前身。**本文只引 Engle-Rangel，不引 Amado-Teräsvirta**，referee 可以直接說「你的 σ²=τ×g 就是 Amado-Teräsvirta 骨架把 transition variable 換成 VIX」。§2 需要一段明確劃界（本文 τ 是外生日頻觀測變數的確定函數 vs A-T 的參數化平滑轉換；本文重點是 OOS 預測與風險管理而非結構檢定）。
   - **HEAVY（Shephard & Sheppard 2010）/ Realized GARCH（Hansen, Huang & Shek 2012）**——「用外生已實現/隱含測度驅動條件變異數」的另一整支文獻，至少要在 §2 承認並解釋為何比較對象選 GARCH-MIDAS 而非 HEAVY 家族。
2. **「the most comprehensive specification comparison to date」（main.tex:80）過度宣稱**——Conrad & Kleen (2020) 與後續 GARCH-MIDAS 比較研究規模不小。改為描述性語句（"a systematic comparison of 17 specifications"）。
3. **VRP「source decomposition」是最弱的 contribution**（見 §3.4）——建議降級為 interpretive section，不要放 abstract 頭條。

### 3.2 方法論

- **Lookahead**：τ_t 全部用 VIX_{t-1}，OOS 為 rolling W=2000、refit 63d；K1393 重驗通過。✅
- **Engle Eq.4 timing convention**（u_{t-1}=r_{t-1}/√τ_t）：已有誠實 footnote（main.tex:184）交代設計選擇 + K988b/K1056b 對照。✅ 這是 v6 之後做對的事。
- **QLIKE 方向**：Eq. (12) 是 canonical actual/predicted 形；報告用 log(σ̂²)+r²/σ̂² kernel（差一個 model-independent 常數，排名/DM 不受影響）。✅ 但 **QLIKE 尺度雙軌（−8.3 vs 1.4–1.6）的 footnote（main.tex:296）解釋含糊**（"a different normalization"），且產生了三個互相矛盾的 GJR QLIKE（Table 3: −8.273 / Table 4 SPY 列: −8.277 / canonical JSON: −8.2710）。需統一。
- **DM/HAC lag（2026-07-11 硬規則重點稽核）**：✅ **全部乾淨**。`compute_mcs_dm.py:805` max_lag=floor(n^{1/3})≈12；`k1393.py:392` q=int(n^{1/3})；K994/K997 直接用 canonical `dm_test`（ceil(h^{1/3}n^{1/3})，`model_evaluation.py:101`）。無 h−1 退化 pattern；`dm_hac_lag_baseline.json` 凍結 backlog 139 站點不含本論文任何 canonical 來源。
- **多重檢定**：Harvey |t|>3 + Bonferroni 2.95 + MCS 三層，架構好。但 Harvey-Liu-Zhu (2016) 的 t>3 是橫斷面因子發現的門檻，借用到時序 DM 是慣例外用法——文中已與 White (2000) 並引，可守；referee 若挑剔，答辯詞已在 §3.7（Bonferroni 一致）。
- **VaR/ES**：Student-t quantile 有 √((ν−2)/ν) unit-variance scaling（Eq. 15）✅ 符合 K802 教訓；四檢定（Kupiec/Christoffersen/DQ/Acerbi-Szekely Z1-Z2）標準。

### 3.3 統計嚴謹度——本次抽查結果（全部實讀檔案）

| 論文宣稱 | 位置 | 來源檔實值 | 判定 |
|---|---|---|---|
| A4f QLIKE −8.360 | Table 3 | `mcs_dm_results.json` −8.36021 | ✅ |
| A4f vs GJR DM t=4.03 | abstract/Table 3 | canonical 4.148（drafting vintage 4.030） | ⚠️ vintage 錯位 + **來源宣稱為偽**（line 723） |
| C1 DM t=3.49 Harvey Yes | Table 3:413 | canonical **1.995**（k988b 2.849）——`midas_fs_verification` 註明 C 系列已用一致 GJR baseline 重算 | ❌ **3.49 無來源，Harvey 翻轉** |
| A3f 2.92 No / B2 2.99 No | Table 3 | canonical 3.018 / 3.066（皆 **Yes**） | ❌ 質性標錯 ×2 |
| 「10 of 16 |t|>3」 | main.tex:817 | canonical 計數 **11 of 16** 且成員不同（C1 出、A3f+B2 進） | ❌ |
| Rank 9 A1 / 10 A3f | Table 3 | canonical rank 9 A3f / 10 A1（對調）；且 prose(436) 說 A1 "ranks 10th"、§5.2(754) 說 "A3 ranks 7th"（表為 6th） | ❌ prose-表-JSON 三方不一致 |
| A5 t=1.84（prose） | main.tex:428 | 表 1.90，canonical 1.947 | ❌ 三個值 |
| QQQ 3.71 / GLD+GVZ 3.17 / 0050.TW 1.44 / VRP ρ 0.80 | Table 4/5 | k994 −3.7081 / k997 3.173 / k994 −1.4388 / k988b 0.8008 | ✅（量值；符號見下） |
| pairwise 表符號 | Table `tab:pairwise_dm` | 註記寫「positive t = first model better」，但 A4f-vs-B2 印 −3.04 且解讀為 A4f 勝（canonical −3.085 = 負號慣例）；同表 GJR 列又印 +4.03（翻正慣例） | ❌ **同表混兩套符號慣例** |
| A4f-t VaR 1%: viol 1.42/UC .087/CC .158/DQ .354；2.5% DQ .006；5% viol 5.42 | Table 8 | k995 1.4247/.0865/.1576/.3533/.00605/5.4247 | ✅ 逐格吻合 |
| 殘差診斷 kurt 3.065→1.238 / JB 938.8→224.2 / ν 5.28→8.00 | Table 11 | K1045（README 載 verified rtol≤0.002） | ✅ |
| 敏感度 16 格（refit/window/subperiod/VIX variant） | Table 12 | K1003 全對映（13/16 Harvey） | ✅（prose 1.60/2.50 vs K1003 1.59/2.49 微差） |
| 7 窗 pooled t=6.977 / 4.80–7.00% mean 6.42% | §6 narrative | K1027（n=3,328, 2013–2026） | ✅ 但**文中無 K 出處、且 pooled 窗超出論文宣稱 OOS**，需標明 |
| 六個 macro 變數、t=4.77「VIX vs best macro」 | main.tex:861 | K1001 **只跑 2 個 macro**；4.77 實為 **A4f vs GJR** 而非 vs best macro | ❌ **未被實驗支撐的宣稱 + 統計量誤標**（研究誠實層級） |
| K1393 COVID 窗「~2.5× larger」QLIKE 改善 | main.tex:723 段 | audit_2026-06-10 Q5：JSON 比值 ≈7.6× | ❌〔未親驗 7.6×，引 audit；修訂時重算〕 |
| Prop 1/2：Corr(τ,g)≈0.49、θ₁-ratio 0.78 | §6 | K1023：0.493 / 0.781 | ✅ |
| MCS α=0.25 GJR p=0.229 | §5.3 | canonical p=0.22 | ⚠️ 微drift |
| GW χ²=16.28 vs GJR / 3.77 vs B1 | §5.4 | canonical 17.24 / 3.775 | ⚠️ **同段落混 vintage**（vs B1 已用 canonical，vs GJR 還是舊值） |

**結論**：實驗層（K 檔案）品質高；手稿層是「多 vintage 拼貼 + 三處無來源/翻轉值 + 一處未支撐宣稱」。

### 3.4 內部一致性——g_t/VRP 敘事的結構性問題（比 v7 更深）

v7 說這是「latent g_t vs g-proxy 的措辭問題」。實讀後判定更嚴重：**abstract 的頭條性質（ρ≈0.80）不屬於論文推薦的模型**。

- Table 5（tab:vrp_corr）白紙黑字：**A4f（recommended）的 g_t 與 VRP 的 ρ = −0.017（p=0.479）**；0.78–0.82 屬於 A3f/A2n/A4n——三個非冠軍規格。
- §6（main.tex:893）又寫 model-recursion g_t「ρ≈0.06」——與表中 −0.017 **是第三個版本的數字**（未在任何 JSON 找到 0.06 的來源；〔未驗證〕）。
- 因此 abstract「We show that the g_t component contemporaneously tracks the VRP (ρ≈0.80)」對 A4f 而言是**假的**；對 A3f/A2n/A4n 而言才成立。這不只是加 hat 符號的問題：誠實寫法是「在 E[g]=1 類規格下 g_t 追蹤 VRP（ρ≈0.80）；推薦的 A4f 因 free ω 吸收了平均 VRP 水位，其 g_t 與 VRP 近乎正交——兩者共同構成 VRP 修正的雙通道證據（θ₁ 通道 + E[g] 通道，Prop 2）」。這其實是**更有趣**的故事，且 K1023 的 Prop 2 驗證已經支撐它。
- 修訂時 §4.2/§6/abstract/conclusion 四處要用同一套物件命名 + 同一個數字（−0.017 或重算值）。

### 3.5 樣本期間穩健性——未關閉的最大實證風險

- K1393（K988-faithful）已把 C1 關掉：non-COVID t=+4.26、full OOS t=+3.60，優勢非 COVID artifact。✅
- **但 K1391（full QLIKE kernel、Codex v2 PASS）顯示 OOS 延長 41 天到 2026-05-20 後全樣本 DM t = −2.03（GJR 反勝）**，且 grep 全 `experiments/` 確認**至今沒有任何 K988-faithful spec 的延長 OOS 重跑**。K1391 用的是 K1392-bug 家族 spec（K1393 修了 5 個 bug），所以 −2.03 可信度存疑——但「存疑」不等於「可忽略」。投稿在即，referee 拿到稿件時距 2026-04-07 已 6+ 個月，「為何樣本停在 4 月」是必問題；若 faithful spec 延長後真的翻負，這是 headline claim 的樣本敏感性問題，**必須在投稿前自己知道答案**（研究誠實 § 不能讓步）。→ P0-2。

---

## 4. 風險與致命傷

依嚴重度排序：

1. **【致命傷-流程】假投稿狀態鎖死一切修正**。README/`research_program.md`/v7 decision/v8_plan 全部建立在「submitted under review」上，而 owner 2026-07-10 已確認從未投稿。所有已知 BLOCKING 修正（Q1–Q5）被一個不存在的 reviewer 擋了一個月。
2. **【致命傷-誠實】§5.9 macro 比較**：宣稱六變數、實驗只有兩變數；t=4.77 張冠李戴。若被 referee 或讀者發現，傷害的是作者信譽而非單篇論文。
3. **【重大】Table 3 C1=3.49 無來源 + A3f/B2 Harvey 翻轉 + 10/16 計數錯**——replication package 自帶反證（任何人跑 `reproduce.py` 就能看到）。
4. **【重大】g_t/VRP 敘事**：abstract 頭條性質不屬於推薦模型（§3.4）。
5. **【重大】K1391 延長 OOS 反轉未用 faithful spec 覆核**（§3.5）。
6. **【中】嵌合引用 acerbi2019**（標題=Du & Escanciano 2017 MS 63(4):940–958，作者=Acerbi & Szekely，卷期/DOI 皆非兩者；Z1/Z2 正確出處是 Acerbi & Szekely 2014, Risk 27(11):76–81）+ 文獻缺口（Kanniainen et al. 2014；Blair et al. 2001；Amado-Teräsvirta 2013；HEAVY/Realized GARCH）。
7. **【中】pairwise DM 表符號慣例自相矛盾**；GW 段落混 vintage；n 值五個版本（1825/1824/1828/1852/1866）散落各表無對照說明。
8. **【中-replication】k994_results.json 的 `direction` 欄位系統性標反**（"gjr_better" 實為 A4f better；QLIKE 與 canonical dm_test 符號慣例可證）；`results/README.md` 把 VaR 表綁到不存在的 `k988_results.json → var_backtest`（實際來源 K995）；STOXX50E/FEZ 無 reproduce binding 且 K1144 重跑 drift −16.9%/−9.7%（快照從未按 SF2 行動項釘住）。
9. **【低】** README「1 MAJOR citation issue」已過時（Bayer-Hackethal 已移除）；`compute_mcs_dm.py` metadata 把 Harvey-Liu-Zhu 誤寫成 "Harvey, Leybourne & Newbold (2016)"；README 狀態行、`experiments.md` 標頭「under review」殘留。

---

## 5. 接下來的研究計畫

### P0（投稿前必做；預估 2 個工作 sprint）

| # | 項目 | 內容 | 驗證 gate |
|---|---|---|---|
| P0-1 | **解凍 + canonical rebind** | 撤銷「body frozen until R1」（前提為偽）。把 `r1_response_queue.md` Q1–Q5 + v7 P1–P3 一次落地 main.tex：Table 3 全表由 pinned `mcs_dm_results.json` 重生（C1→1.995 No、A3f→3.018 Yes、B2→3.066 Yes、計數 10/16→11/16）、4.03→4.148 全文同步、macro 段改寫為兩變數實況 + t=4.77 重標、acerbi2019→acerbi2014(Risk)（可另引 Du & Escanciano 2017）、"non-inferior"→"not statistically distinguishable"、g_t/g-proxy 全文統一（§3.4 的雙通道誠實敘事）、五之七→雙門檻並列、pairwise 表符號統一、2.5×→重算、GJR QLIKE 三值統一、n 對照 footnote | xelatex 重編譯 + `reproduce.py` match_rate ≥95% **green** + `paper-update` 同步 |
| P0-2 | **延長 OOS faithful-spec 覆核**（新 K） | 以 K1393 的 K988-faithful A4f spec、新 pinned snapshot，OOS 延到最新資料（≥2026-06），full QLIKE kernel + canonical DM。若 Harvey 仍過：資料節更新至新端點一併投稿；若翻轉：加誠實 sample-sensitivity 小節（K1027 七窗證據可支撐「長期優勢 vs 近期窗口逆風」的框架），headline 改寫 | 實驗三件套 + Codex review PASS；結論寫入 knowledge.json |
| P0-3 | **Replication package 除雷** | 修 k994 `direction` 欄產生邏輯並重生 JSON（修流程不修資料：改 k994.py 的符號判斷）、`results/README.md` VaR 綁定 k988→k995、STOXX50E/FEZ 快照釘住 + 加入 reproduce bindings、README/`experiments.md`/`research_program.md` 狀態行改「revision, not submitted」 | `reproduce.py` 含新 bindings 全綠；grep 全 repo 無殘留 "under review" |

### P1（投稿包強化；與 P0 平行可做）

- **文獻補強與劃界**：§2 加 Kanniainen-Lin-Yang (2014 JBF)、Blair-Poon-Taylor (2001 JoE)、Amado-Teräsvirta (2013 JoE)、HEAVY/Realized GARCH 一段劃界；刪「most comprehensive to date」。→ `/citation-verifier` 全跑一輪（citation_check.md 已是 2026-04-10 舊版）。
- **K1066 OC-proxy robustness 併入**：`r1_prep/robustness_oc_proxy.tex` shelf-ready（A4f_oc vs GJR_oc DM t=+4.04，5/5 子期），直接回應 Limitations 的 proxy-sensitivity；這是現成的 referee 前置回應，未投稿就不必留「shelf」。
- **VRP 節重寫為雙通道敘事**（§3.4）——把弱點變賣點。
- **abstract 重寫**：4.148、雙門檻跨資產計數、g-proxy 措辭、刪 "passes none (scorecard 1/4)" 的混淆並列。

### P2（後續研究方向，非投稿 blocker）

- **RV-proxy 主檢驗**：用 5-min RV（SPY 可得）重跑 QLIKE/DM 主表——這是 IJF referee 最可能的第一個要求，論文自己也把它列為 future work；先做完就把最大的 R1 風險消滅。
- **多變量延伸**：conclusion 提到的 DCC-A4f 初步結果（未驗證、無 K 來源）——要嘛補實驗給出處，要嘛從 conclusion 刪除（現狀是一個無出處的 preliminary claim）。
- **VIX9D 深化**：Table 12 顯示 VIX9D t=5.15 > VIX 3.92——短天期 IV 作 τ 驅動可能是下一篇的種子（與 K989 convexity 結果串）。
- **跨市場第二篇**：VIXTWN/0050（K1098）+ 歐系 VSTOXX 直測（本文用 US VIX 測歐股成立，但「global fear factor」宣稱用 VSTOXX 對照會更完整）。

### 期刊選擇裁定（pipeline 決策點）

**推薦：International Journal of Forecasting（primary）→ Journal of Empirical Finance（secondary）→ Journal of Forecasting（backup）。**

理由：

1. **貢獻形態是 forecast-evaluation 型**（QLIKE/DM/MCS 橫評 + 簡約論 + VaR/ES scorecard），這是 IJF 的核心文類；MCS「不可區分」的誠實結論在 IJF 是加分（評估文化成熟），在 JEF 會被讀成「so what」。
2. **本文的經濟貢獻線（VRP source decomposition）是最弱環節**（§3.4），JEF referee 會重壓這裡；IJF 對「decomposition 是詮釋工具 + 誠實 null（g_t 無預測力）」接受度高。
3. **Replication package**（pinned snapshot + reproduce.py）符合 IJF 的 replication 友善傳統，是現成資產。
4. J. Forecasting 影響力低於 IJF，同文類下沒有先投的理由；JEF 留作 IJF 被拒後的改寫目標（屆時把 VRP 雙通道敘事升級為主線）。

老闆已授權期刊選擇自主判斷（memory `feedback_paper_autonomy_optimize_acceptance`）；建議 pipeline `journal_target` 由 `decide` 直接設 `IJF`，據此跑 `journal-review` skill 的 IJF profile 格式檢查。

---

## 6. Go / No-Go 建議

- **現狀投稿：NO-GO。**手稿層 BLOCKING（§4 items 2–6）任一被 referee 抓到都是 desk-reject 或信譽傷害等級；reproduce gate yellow 也未達 paper-workflow 硬規則。
- **修訂路徑：GO，且應立即啟動。**P0-1/P0-3 是純手稿+metadata 工作（估 1–2 天主線程工作量）；P0-2 是一個 compute job。全部沒有外部依賴——先前唯一的「依賴」（等 reviewer）已被證明不存在。
- **投稿觸發條件**：P0 三項全綠 + `/citation-verifier` 重跑 0 MAJOR + IJF journal-review compliance gate 通過 → 投 IJF。
- **一句話**：這篇論文的問題不在研究，在敘事紀律與一個把自己鎖住的假狀態；解鎖後它是一篇誠實、可復現、有清楚簡約論貢獻的 IJF 候選稿。

---

*Sources（引用驗證用外部來源）: [Du & Escanciano (2017) Management Science 63(4)](https://pubsonline.informs.org/doi/abs/10.1287/mnsc.2015.2342), [SSRN 2548544](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2548544)*
