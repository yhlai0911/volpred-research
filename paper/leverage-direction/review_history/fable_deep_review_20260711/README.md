# Fable Deep Review — leverage-direction（2026-07-11）

**Reviewer**: Fable 深度審查 agent（user-assigned P0；頂級期刊 referee 水準檢視）
**審查對象（canonical）**: `main_v_ijf.tex` + `body_v_ijf.tex`（2026-07-08 版，354 行，honest-null reframe 後）+ `tables_main.tex`（6 表）
**Pipeline 狀態**: stage=`multi_round_review`，`do_not_advance=true`（`storage/paper_pipeline_status.json` papers[0]）
**Owner directive**: email-12500（2026-07-02）Option A = method diagnosis + honest null，target IJF methods track（fallback EmpEcon）

---

## 1. 執行摘要

**Verdict：2/5（現狀不可投稿）→ 完成 P0+P1 修復後可達 3.5/5（IJF 值得一投，非穩上）**

三句話核心評估：

1. **Reframe 方向正確且 prose 執行到位，但「換引擎」只做了一半**：正文把 headline 換成了 honest null，卻**沒有把支撐 null 的兩個 frozen re-test（K1592 horse race、K1591 ex-ante gold regime）的任何數字、表格、程序細節放進稿裡** —— 論文宣稱自己的中心結論，但讀者（referee）在稿內看不到該結論的證據。
2. **三處殘留的「舊正向宣稱」與 canonical 實驗矛盾**（HM high-VIX t=-4.63 被 K1256 canonical 推翻為 t=-0.79；§5.4 gold regime 只報內生 bull/bear t=-3.79 而隱去 K1591 ex-ante 弱結果；abstract 的 26-asset/14-asset 延伸在全 package 找不到 artifact）—— 這是研究誠實層級的問題，任一被 referee 抓到都是 desk-reject。
3. **好消息：該做的重實驗已經做完了**。K1591/K1592 設計嚴謹（dev/holdout 分割、Holm 校正、canonical QLIKE/DM、decision log 齊全），SPY Holm p=0.104 證明 null 對校正方式 robust —— 剩下的是 1-2 週的「接線 + package 衛生」工作，不是新研究。**不需要再投入 stage2 級的新實驗**。

---

## 2. 現況盤點

### 2.1 Canonical 版本確認

| 檔案 | 狀態 |
|---|---|
| `main_v_ijf.tex`（elsarticle review class，title=「A Pre-Specified Out-of-Sample Evaluation」）+ `body_v_ijf.tex`（7/8 13:16）+ `tables_main.tex` | ✅ canonical，編譯 35-36pp，0 undefined refs |
| `main.tex` + `body.tex`（JBF-era，正向宣稱版） | ⚠️ 仍在根目錄未封存。`src/volpred/ops/papers.py:250-263` 的候選清單看不到 `*_v_ijf.tex` → 誤跑 `paper-update --paper-id leverage-direction` 會發佈 stale 正向版（LATENT，`canonical_state_findings_20260702.md` §1-2；`do_not_publish` schema guard 仍未建） |
| `supplementary_content.tex` / `supplementary.pdf` | ⚠️ JBF-era 內容未改版（見 3.4） |

### 2.2 逐條驗證 2026-07-02 IJF review 的 5 個 blocker

| # | Blocker（7/2 版） | 2026-07-11 現況 | 證據 |
|---|---|---|---|
| (a) | same windows/single protocol 宣稱 vs tab:vt asset-native windows 矛盾 | **部分解決（降級為揭露，未修復）**。7/2 hourly-12 prose fix + A-tick-1 後，intro（body_v_ijf.tex:170）與 methodology（:204）已明示 forecast-level 共用視窗、allocation-level 用 asset-native 視窗並定調為「null context」；tab:vt notes 也逐資產揭露視窗。但**核心 allocation 證據仍建立在異質視窗上**：uniform 2015–2026 重驗只 match 6/20 cells，GLD BH Sharpe 1.56（native 2022–2026 bull window）→ 0.83（uniform）（`REPLICATION.md` §5.3）。另 tab:vt notes 指錯 section（`tables_main.tex:128` 引 `sec:var_compliance`，應為 allocation/data section — JBF 時代的殘留引用） |
| (b) | reproduce.py GREEN 只 gate table sources，不 gate prose/tab:vt/6-of-6/ρ=0.83 N=14 | **仍成立且更嚴重**。`reproduce.py:30-44` 自述 prose 檢查對象是 JBF-era `body.tex`/`main.tex`，body_v_ijf 數字只「manually verified during drafting」；`reproduce.py:16` 明記「Abstract 6/6 OOS + rho=0.83 (N=14): no JSON source -> NOTE tier」。更嚴重處：**ρ=0.83 N=14 的 artifact 在整個 repo（含 Online Supplement）都不存在**（見 3.3 F4） |
| (c) | title_page_v_ijf.tex draft AI disclosure | **仍成立**（`title_page_v_ijf.tex:40`，標 DRAFT 待 owner sign-off — policy 項，不可自動改）。**新發現**：title page 標題還是舊版「A Cross-Asset Complexity Ceiling」（:18-19），與 manuscript 現行標題不一致 |
| (d) | REPLICATION.md / submission_package.md stale JBF | **仍成立**。`REPLICATION.md:3-4` 仍是 JBF 標題+target；`submission_package.md` 更危險：status 還寫 `READY_FOR_UPLOAD`、highlights 第 1 條還是**已撤回的 t=-5.79** 宣稱、第 5 條還是已刪除的 time-zone contribution（:38-42）。`experiments.md` 也仍是 JBF 14-table 索引，與 IJF 6-table 結構完全對不上 |
| (e) | `experiments/k903/README.md` placeholder | **仍成立**（全部「待補充」，status: planning）。k903 是 tab:desc/gamma/qlike 三張主表的 canonical source，README 空白 = 外部 replication checker 無法讀 |

### 2.3 A-tick-2 的「宣稱完成」vs 實際完成

`body_v_ijf.tex:130-136` 的 A-tick-2 TODO 寫明要「wire K1592 frozen OOS horse race (0/N sig) + K1591 gold-regime bootstrap CI [-0.71,0.39] as tabulated numbers; every retained number reproduce-gated」。實際的 A-tick-2（`reframe_atick2_complete_20260703.md`）做的是 header reconciliation + 9 處殘留 over-claim 修字 —— **接線工作從未執行**。7/8 readiness review（`review_ijf_readiness_20260708.md`）給 MINOR_FIXES 是因為它只檢查 narrative 一致性，沒有對照 K1591/K1592 的實驗檔案。

---

## 3. 學術深度檢視

### 3.1 Contribution 定位 — 方向對，但「framework + honest null」的 framework 沒有被展示

honest-null 定位（reproducible measurement-to-allocation evaluation framework + the null it yields）是 IJF methods track 的合理 fit —— IJF 有刊登 informative null 與「simple beats complex」傳統（M-competitions 血統）。但 methods-track 論文的存在理由是**協定本身可被複用與檢驗**，現稿有三個結構性缺口：

1. **Multiple-testing 程序從未被具體指定**。methodology 只說「disciplined against data mining with a multiple-testing correction \citep{harvey2016}」（body_v_ijf.tex:251）；結果段說「once the eleven DM comparisons ... are disciplined with a Harvey-style multiple-testing correction ... no asset shows significant OOS superiority」（:293）——哪種校正（Holm？BH？t>3 threshold？）、family 幾個檢定、在哪張表？稿內全部沒有。實際程序在 K1592（Holm across assets + |t|>3 + p_holm<0.05），但 K1592 不在稿裡。**一篇 headline 是「pre-specified multiple-testing-controlled evaluation」的論文，正文沒有寫出 multiple-testing 程序，是自我矛盾**。
2. **「frozen before a genuinely future evaluation window」的 frozen test 沒有出現**。tab:qlike 的 11 個 DM 比較（k903）是 GARCH-vs-GJR 的 same-window 比較，不是 frozen γ-rule horse race；真正的 frozen test 是 K1592（dev={SPY,QQQ,EEM,GLD,TLT} / holdout={IWM,SLV,BTC}、2023-01–2026-06、monthly refit、forecast-origin decision log），其結果（0/8 assets Harvey-Holm 顯著；MCS holdout panel 保留全部三個模型）正是論文的中心 null——**卻一個數字都沒進稿**。K1592 還附 `k1592_forecast_origin_decision_log.csv`，恰好是 7/1 Codex contribution gate 點名要的 decision log，做好了卻沒用。
3. **「pre-specified」的程序性宣稱需要 provenance 段落**。整個研究計畫跑過 110+ 實驗後才凍結 re-test 協定；K1591/K1592 是「在各自 OOS 視窗前凍結」的 re-test，不是先驗假設。對 null 方向這不致命（selection bias 方向是偏向找到正效果，報 null 反而保守），但 referee 一定會問「pre-specified 是什麼時點、凍結了什麼」。需要一段 design-provenance（何時凍結、凍結內容、decision log 指引），否則「pre-specified」讀起來像行銷詞。

### 3.2 統計嚴謹度 — 逐表抽查

| 位置 | 抽查結果 |
|---|---|
| tab:gamma（SPY +0.132/t=+11.08、GLD +0.002/t=+0.15 等 7 列） | ✅ reproduce gate 覆蓋（`experiments/k903/tables/k903_table2.csv`，171 MATCH / 0 MISMATCH）。HAC 8 lags 對 87.5% overlap 合理 |
| tab:qlike 11 列 DM p 值 | ✅ gate 覆蓋（k903_table3.csv）。BTC 2025 無 canonical row 而缺列已誠實註記 |
| k903 `dm_test_hac`（k903.py:501-513） | ✅ 用 canonical bandwidth `ceil(h^{1/3}·n^{1/3})`，**不在** K1655 DM-HAC-lag 凍結 backlog（`storage/ops/dm_hac_lag_baseline.json` 133 個 degenerate sites 無 k903/k1591/k1592/k829/k799/k802） |
| **但** methodology 宣稱 DM 用「Newey–West HAC standard errors (five lags)」（body_v_ijf.tex:247） | ❌ 與 k903 程式實際的 bandwidth 規則不符（n≈500 → 8 lags；n≈250 → 7 lags）。replicator 會抓到 prose-code 不一致 |
| K1592（`volpred.stats.model_evaluation.dm_test` + Holm + date-clustered panel per K1355） | ✅ 全部合規；SPY rule-vs-GARCH t=-2.85、unadjusted p=0.0045、**Holm p=0.104** → 「no asset significant」對校正方式 robust，不是靠 t>3 門檻硬壓 |
| ρ=0.944（p=0.016, N=5, tab:vt MDD improvement vs base vol） | ⚠️ 可由 tab:vt 自行重算（非虛構），但 N=5 Pearson 本身無推論價值；正文已誠實改依 14-asset 樣本為 primary basis —— 而那個樣本不存在（F4） |
| ρ=0.886（p=0.019, N=6）+ 0.821 pre/post-sample（body_v_ijf.tex:314） | ⚠️ 無 gate 覆蓋、無 inline source；N=6 已在 Limitations 承認 underpowered |
| gold anti-VT Sharpe 1.71/1.51/1.56（:301） | ⚠️ 無 inline `% source:`（7/8 review 已列 blocker 3，未修） |
| 12/VIX（0.856 vs 0.826；MaxDD bootstrap p=0.0004）、EWMA COVID（1.130 vs 0.745）（:303-305） | ⚠️ 無 gate 覆蓋；lag 處理有揭露（footnote 明示 +1.0 Sharpe same-day bias 已避開）——lookahead 紀律這點值得肯定 |
| tab:var_panel notes「Original values were not reproducible under data-vintage variations」（tables_main.tex:107） | ⚠️ 7/1 Codex 已點名這類 audit note 不該以此形式出現在投稿稿；仍在 |

### 3.3 內部一致性與研究誠實 — 四個 must-fix 發現（本輪新增）

**F1｜中心 null 的證據不在稿內**（上述 3.1；致命）。

**F2｜§5.4 gold regime 選擇性引用**（致命，研究誠實）：
- 正文（body_v_ijf.tex:312）仍引用**內生** bull/bear 分解：「bull γ=-0.043 versus bear γ=+0.048 (t=-3.79, p<0.001), consistent with gold's safe-haven role」。regime 由金價自身方向事後定義 —— 正是 7/1 Codex item 2 批評的「ex-post regime」。
- 為回應該批評而做的 K1591（ex-ante 外生 regime：lagged VIX≥20 + DXY trend + Treasury basis；train ≤2018 / holdout 2019–2026）結果是**弱**：holdout safe-haven γ_diff=-0.087（HAC t=-0.66）、block-bootstrap contrast 95% CI **[-0.71, +0.39] 跨零**、僅 69.8% draws 為負（`experiments/k1591/README.md`）。
- **稿內完全沒提 K1591**。reframe axis 註解（body_v_ijf.tex:21-22）宣稱 manuscript「grounded in ... K1591 (gold regime bootstrap CI spans 0)」——正文實際上仍只展示強的內生版本。這是「自己的 frozen re-test 推翻自己引用的顯著性、卻只報有利版本」，若被 referee 或 post-publication 檢驗發現，傷害等同 7/1 cover letter t=-5.79 事件。
- 附帶：t=-3.79 宣稱的樣本是 2005–2026，但 pinned CSV（`data/spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv`）從 2010 起、Data section 宣稱資料 2017 起 —— 這個數字**用 package 內的資料算不出來**，也無 reproduce gate 覆蓋、無明確 K-source。

**F3｜HM high-VIX 顯著性宣稱被 canonical 重估推翻**（致命）：
- 正文（body_v_ijf.tex:307）：「conditional on high-VIX episodes (VIX>25), the timing coefficient is significantly *negative* (γ̂_HM=-0.068, t=-4.63)—VT misses post-crisis recoveries」。
- K1256 canonical 重估同一 spec（`pure_vt_high_vix`）：γ_HM=**-0.030、t=-0.79、p=0.43（不顯著）**，verdict=DIVERGENT_SAME_SIGN、t 差 3.84（`experiments/k1256/k1256_results.json`）。reproduce gate 把它列 NOTE tier（reproduce.py:428-448「pending L11 errata path (c)」）所以 GREEN 照亮 —— gate 綠燈與 prose 錯誤並存的活案例。
- 同段「unanimously fail to reject ... (p>0.70)」也與 K1256（pure_vt_full p=0.31）不符；結論方向（timing null）不變，但數字必須 rebind 到 canonical。

**F4｜Abstract 的 cross-section 延伸宣稱無 artifact**（致命）：
- Abstract（main_v_ijf.tex:80-81）：「extended to twenty-six assets」；正文 :170「validation extended to up to twenty-six assets」；:299「extended 14-asset sample **reported in the Online Supplement**, which we treat as the **primary basis for inference**」。
- 查證結果：`supplementary_content.tex` **沒有** 14-asset MDD-volatility 相關內容（grep fourteen/14-asset/0.83 僅命中無關的 Merton timing p=0.83）；repo 內無 26-asset 或 14-asset 的 result JSON；reproduce.py:16 自記 no JSON source；K1592 limitations 明寫「does not satisfy the stronger 14/26-asset validation requested by the review gate」。26-asset 句是 JBF-era body.tex:11 的殘留繼承。**論文自宣的 primary inferential basis 在 package 中不存在。**

**F5｜Cover letter 與 manuscript 矛盾**（desk-reject 級）：
- `cover_letter_ijf.tex:27` 用舊標題「A Cross-Asset Complexity Ceiling」；:29 宣稱「earns statistically detectable out-of-sample forecast gains ... in a restricted domain: a homogeneous equity universe with a significant asymmetry」——**與 manuscript 的「no asset shows significant OOS superiority」直接矛盾**（cover letter 是 7/2 03:15 編譯，早於 7/3 reframe）。與 7/1 被抓的 cover-letter-vs-body 不一致完全同類。

其他一致性問題（可修級）：tab:desc caption「In-Sample Period: 2017–2025」（tables_main.tex:5）與 canonical partition（IS=2017–2022）衝突；Data section 宣稱資料 2017-01 起（body_v_ijf.tex:209）但主表 tab:gamma 用 2010–2026（tables_main.tex:24）、gold regime 用 2005–2026、12/VIX 用 2009–2025、HM 用 2014–2026 —— Data section 必須改寫為描述實際使用的全部資料範圍。

### 3.4 Online Supplement 狀態

`supplementary_content.tex` 仍是 JBF-era：含 time-zone 章（7/1 Codex 明令整個拿掉的內容）、complexity-ceiling 10-row 表（舊 headline）；**缺**正文五處「Online Supplement」指向的內容中的兩項（14-asset extended sample、EWMA/window robustness 只有 SPY 單資產的 tab:window 在 `tables_supplement.tex`）。正文以純文字（非 \ref）指向 supplement，編譯不會報錯 —— 但投稿時 referee 打開 supplement 對不上，等同虛引。

### 3.5 寫作結構

honest-null 的 prose 品質好：title/abstract/intro/§5.2 header/§6.1/conclusion 口徑一致，「apparent gains ... do not survive」的 framing 紀律在 7/3 兩輪 codex 對抗審查後相當乾淨。結構問題只有一個：**Empirical Results 缺一個「§5.x The Pre-Specified Re-Test」小節**來裝 K1592/K1591 —— 現在 §5.2 的敘事在 same-window 證據（tab:qlike）與 frozen-test 結論之間跳躍，referee 會迷路。

---

## 4. 風險與致命傷

**致命（must fix or kill）**：
| # | 問題 | 證據 |
|---|---|---|
| F1 | 中心 null 無稿內證據（K1592 未接線、multiple-testing 程序未指定） | body_v_ijf.tex:293 vs experiments/k1592/ |
| F2 | gold regime 選擇性引用（內生 t=-3.79 在稿、ex-ante K1591 CI 跨零不在稿） | body_v_ijf.tex:312 vs experiments/k1591/README.md |
| F3 | HM high-VIX「significantly negative t=-4.63」被 K1256 canonical（t=-0.79 NS）推翻 | body_v_ijf.tex:307 vs k1256_results.json |
| F4 | 26-asset / 14-asset 延伸宣稱無 artifact（且自稱 primary basis） | main_v_ijf.tex:80、body_v_ijf.tex:299、supplementary_content.tex |
| F5 | cover letter 舊標題+正向宣稱與 null 稿矛盾 | cover_letter_ijf.tex:27-29 |

**可修（submission hygiene）**：title page 舊標題 + AI disclosure draft（policy，需 owner）；REPLICATION.md / submission_package.md / experiments.md 三份 stale JBF 文件（submission_package 還留著 t=-5.79 highlight）；k903 README 空白；reproduce.py 不 gate body_v_ijf；supplement 未改版；tab:desc caption、Data section 資料範圍、DM「five lags」prose、tab:vt 錯誤 section ref、var_panel「not reproducible」note 措辭；JBF-era main.tex/body.tex 未封存 + paper-update latent stale-publish 風險。

**戰略風險**：(i) null 論文最大攻擊面是 power —— 現稿只對 N=6 classification 認了 underpowered，**DM null 本身沒有 MDE/power 陳述**（873 OOS 天、|t|>3+Holm 的門檻下，多大的 QLIKE 差才偵測得到？）；(ii) 若 14-asset artifact 找不回也重建不了，allocation-level 推論退回 N=5，IJF 說服力大減。

---

## 5. 接下來的研究計畫

**總判斷：stage2 core rebuild 不需要再投入 —— 它已經做完了**（K1591/K1592 就是 reframing_decision_20260701.md 的 stage2 前兩項，結果 null/weak，並直接觸發了 owner 的 Option A 降檔）。剩餘工作是**接線、重建 artifact、package 衛生**，約 6-8 個工作天，無重型新實驗。繼續往「更深的 gold regime rebuild（期貨/機構流量資料）」投入 = 另一篇論文的 scope，本輪不做（維持 7/1 決策的 Stage 3 defer）。

### P0 — 證據接線（先於任何新 review round；~4 天）

1. **K1592 進稿**（1.5-2 天）：新增「Pre-Specified Out-of-Sample Re-Test」小節 + 新表（8 資產 × {rule-vs-GARCH, rule-vs-GJR} DM t / Holm p / GJR share / MCS survivors，dev 與 holdout panel 分列）；methodology 補精確程序（frozen rule 定義、|t|>3 + Holm p<0.05 判準、family 大小、monthly refit、decision log 檔名）。成功標準：§5.2 的每個 null 句子都指得到稿內表格；`k1592_forecast_origin_decision_log.csv` 列入 replication package。
2. **K1591 進稿**（0.5-1 天）：§5.4 改為雙軌報告 —— 內生 bull/bear 分解（降級為 descriptive/suggestive）+ ex-ante 外生 regime 的 holdout 結果與 bootstrap CI [-0.71, 0.39]（如實標 directionally supportive、not significant）。gold regime 敘事強度整體下修一級。成功標準：正文不再有任何「gold regime p<0.001」等級的宣稱未伴隨 K1591 counter-evidence。
3. **HM 數字 rebind K1256 canonical**（0.5 天）：-0.068/t=-4.63 → -0.030/t=-0.79（NS）；改寫該句為「conditional on high-VIX episodes the point estimate remains negative but insignificant」；p>0.70 同步修正。timing-null 結論不變、反而更乾淨。
4. **26/14-asset 宣稱二選一**（0.5-1.5 天）：(i) 找回 JBF-era 14-asset MDD-vol correlation 的 source 實驗（先 grep knowledge.json/舊 K）；找不到就 (ii) 用 yfinance 重建 14+ 資產 VT panel 為新 K 實驗（pin snapshot、進 supplement + reproduce gate），或 (iii) 直接把 abstract/intro 的延伸宣稱裁到現有可證範圍（K1592 的 8 資產 + tab:vt 的 5 資產）。**kill 標準：若 (ii) 重建後 ρ 顯著變弱（如 CI 含 0），依研究誠實原則改寫 allocation 結論並降 tier 投稿。**

### P1 — Gate 與 package（可與 P0 平行部分進行；~3 天）

5. **reproduce.py 升級 gate body_v_ijf**（1 天）：新 check family 綁 body_v_ijf prose literals（K1592/K1591/K1256 canonical 數字、gold anti-VT、12/VIX、EWMA），MISMATCH 級而非 NOTE 級；跑到 GREEN ≥95% 才准進下一輪 review（paper-workflow rule 2）。
6. **Package docs 全面 IJF 化**（1 天）：REPLICATION.md、submission_package.md（刪 READY_FOR_UPLOAD + t=-5.79 highlight）、experiments.md（改 IJF 6-table 映射）、k903 README 補全；封存 JBF-era main.tex/body.tex 到 `_archived/`（消除 paper-update stale-publish 風險 —— 或先建 `do_not_publish` schema guard）。
7. **Supplement 重建**（1 天）：刪 time-zone 章；加入 body 實際指向的內容（14-asset artifact、EWMA crisis、視窗 robustness、VaR orthogonality）；與 body 的五處指向一一對齊。
8. **一致性小修**（0.5 天）：cover_letter_ijf 全文重寫（null framing + 新標題）；title_page 標題同步；tab:desc caption；Data section 資料範圍改寫（描述 2005/2010–2026 的實際使用範圍與各結果視窗）；DM lag prose 改為 canonical bandwidth 規則；tab:vt section ref 修正。AI disclosure → email 老闆要 sign-off（policy，不自動改）。
9. **Power/MDE 段落**（0.5-1 天，小型計算非新實驗）：以 K1592 的 loss-differential SE 反推 |t|>3+Holm 下的 minimum detectable QLIKE 差，寫入 Limitations —— 這是 null 論文對 referee「你只是 power 不夠」攻擊的必要防線。

### P2 — 投稿與後續

10. **Gate 順序**：P0+P1 完成 → reproduce GREEN → 跑 fresh multi-round review（latex-academic-reviewer + citation-verifier + journal-review，Codex 額度 7/11 恢復後走 primary path）→ 過了才動 submission package。
11. **期刊策略**：**IJF 維持 primary**（methods track 有 informative-null 傳統；本稿的 measurement-to-allocation 框架 + decision log + frozen re-test 是好的 methods fit），但如實評估錄取率屬低-中 —— null + 小 cross-section 是硬傷。**EmpEcon 維持 fallback**；中間可考慮 Journal of Forecasting（Wiley）作為第二 fallback。**不建議**回頭衝 JBF（7/1 gate 已判 BORDERLINE 且 positive story 已被自家 re-test 推翻）；FRL 2500 字上限會砍掉框架本身（先前判斷維持）。
12. **Desk-reject 風險清單（投稿前自查）**：cover letter 與稿一致（F5 修復驗證）、abstract 每個量化宣稱稿內有表、supplement 指向一一存在、replication package 從 clean clone 可跑（k903 README + REPLICATION.md 修復驗證）。

### 明確不做（本輪）

- Gold regime 深度 rebuild（期貨/機構資料、更長 vintage）— 新論文 scope（Stage 3 defer 維持）
- VT channel 的 GJR-independent identification — 7/1 決策已 defer，維持
- 任何為了「把 null 翻回正結果」的再挖掘 — 違反 pre-specification 紀律，K1592 的 decision log 就是防這件事的

---

## 6. Go/No-Go 建議

**CONDITIONAL GO（push，先修後投）**：不 archive、不 merge、不 major rebuild —— 該 rebuild 的實驗已完成且結論誠實，但現稿「宣稱的證據不在稿內、稿內的三處舊數字與 canonical 實驗矛盾」，以現狀送 IJF 必被 desk-reject 且有研究誠實風險；完成 P0（證據接線 + 三處矛盾修復）+ P1（gate/package 衛生）約 6-8 個工作天後，這是一篇框架乾淨、null 誠實、可複現的 IJF methods-track 候選，值得一投。

---

_審查方法備註：所有引用數字均實際讀自 repo 檔案（.tex 行號、experiment JSON jq 輸出、README）；未修改任何 .tex / 共享 JSON；未 commit。K1592 Holm p 值由 `experiments/k1592/k1592_results.json` 直接驗證；K1256 三 spec 由 `experiments/k1256/k1256_results.json` 直接驗證。DM-HAC-lag 凍結 backlog（`storage/ops/dm_hac_lag_baseline.json`，133 sites）查無本論文相關腳本。_
