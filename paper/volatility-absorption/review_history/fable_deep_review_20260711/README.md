# Fable Deep Review — volatility-absorption (Paper 8)

**Reviewer**: Claude Fable 5（主線程指派之資深學術深審，referee 水準檢視）
**Date**: 2026-07-11 22:37 台灣時間
**Manuscript under review**: `main_v3.tex`（canonical，2026-06-11 audit-fixed scope + 2026-07-01 K-id scrub）
**Review round**: 本輪為 v3 稿的第一次全文深審。前史：2026-04 R1（`reviews/review_r1.tex`，5 SEVERE）→ K897/K741/K903/K904/K1418 修復 → 2026-06-10 Codex provenance audit（`review_history/audit_2026-06-10/`）→ 2026-06-11 scope 收斂（deferred Tables 6–8）。

---

## 1. 執行摘要

**Verdict: 2.5 / 5 — 有條件 Major Revision（不是 archive，也遠不是 ready）。**

三句話：這篇論文的**誠實度與 reproducibility 基建是全 portfolio 前段班**（reproduce gate 30/30 green、snapshot sensitivity 全文披露、無法重現的段落誠實降級為 deferred），但**識別核心有一個未關閉的致命缺口**——K897 null 模擬的 vol proxy 是 t-1 可測的，而實證的 ΔVIX 與報酬是同日同步的，這個 timing 錯配讓「absorption 不是機械效應」的關鍵證據建立在一個被弱化的 null 上。此外正文仍殘留 **5 處可被 referee 一眼抓到的內部不一致**（含一句與自家 artifact 反向的 VRP 宣稱），以及主要證據表（Table 3）的 p 值欄完全無 binding。修復路徑明確、成本可控（P0 約 1–2 個工作天），且 P0-1 的結果直接決定這篇是升級還是重新框架。

---

## 2. 現況盤點 — 這篇論文到底卡在哪

**先更正一個 stale 認知**：任務 brief 說 blocker 是「reproduce/convergence finishing」——這已過時。`reproduce_report.json`（2026-06-11 生成，v3-active-scope）是 **match_rate 100%、30/30 checks、gate pass、alert green**。7/1 之後 main_v3.tex 只動過 K-id 清洗（4 行，git c28229c85），gate 實質仍有效。convergence 問題在 6/11 的 scope 收斂（把不可重現的 Tables 6–8 降級為 deferred）中已解決。

**真正卡住的是三件事**：

1. **沒有人做過 v3 稿的正式全文 review round**。R1（4 月）審的是舊稿；6/10 audit 是 provenance 抽查不是學術深審。本報告即為 v3 的第一次深審。
2. **6/10 audit 的修復執行不完整**——audit 要求「統一 original vs pinned snapshot 數字」，6/11 修了 SPY/GLD/TLT，但 Table 4 的 0050.TW 行漏了（見 §4-C3），Appendix B 的 α/R² 欄也漏了（§4-C4）。
3. **stage=revision 停 7 週的根因是沒有 next-action owner**：deferred sections 的重建被標成「future」，但沒有人判定「不重建能不能投」。本報告 §5/§6 給出這個判定。

**撐得住的部分**（誠實列出，避免報告只有負面）：

- 我獨立抽查 5 組數字全部與 experiment JSON 一致：Table 3 SAR 五值 vs `experiments/k716_results.json`（3.16/2.77/2.37/2.32/2.43 ✓）；Table 4/Appendix B 的 β/t vs `experiments/k1418/k1418_results.json`（SPY −0.000273/−1.85 ✓，GLD −0.000434/−2.90 ✓，TLT −0.000437/−3.31 ✓）；K903 全表（baseline −0.000267/−1.77、RV −0.01249/−8.2、controlled −0.000216/−1.26、T9/T10 全對 ✓）；K897 decline 0.8162 與 CI [−0.2811, 0.5575] ✓；K741 NFP regime n/mean ✓。
- K897 設計投資不小：per-path seed（`RandomState(seed)`，seed=0..9999）、GJR-GARCH(1,1)-t、10,000 paths × 5,000 obs、persistence sensitivity（0.90/0.95/0.97/0.99）、GJR vs symmetric 對照。
- `storage/ops/dm_hac_lag_baseline.json` 對本篇 K（k716/718/719/741/897/903/904/1418）**0 hits**——凍結 backlog 不影響本篇（本篇用 NW 迴歸與 Welch t，無 DM 檢定）。
- 全文的 snapshot-sensitivity 披露（每個受影響數字都有 footnote 對照原值）在誠實度上超過多數投稿論文的水準。

---

## 3. 學術深度檢視

### 3-A. Contribution 定位 — 概念原創性可辯護，但防線還沒築

「Volatility absorption =  ambient fear 越高、邊際 fear shock 對報酬的衝擊越小」作為一個被命名、被系統量化的現象，在我可及的文獻記憶內沒有直接撞名的先行者——**但它與三塊已有文獻的距離近到必須正面防衛，目前正文完全沒引用**：

1. **VIX–return 同期非線性關係文獻**：Low (2004, *Journal of Business*) 記錄 return–ΔVIX 關係的凸性（convexity）；Hibbert, Daigler & Dupoyet (2008, *JBF*) 記錄同期 return–implied vol 不對稱的行為解釋；Fleming, Ostdiek & Whaley (1995) 的 VIX–return 關係基礎文獻。**SAR 隨 VIX level 遞減，在數學上可能就是「return–ΔVIX 彈性隨 VIX level 遞減」的重新包裝**——referee 第一個問的就是這個。論文必須要嘛引用並區分，要嘛承認等價然後主張「量化＋null 檢定」是貢獻。（此段文獻對照為 reviewer 記憶所及，投稿前需 citation-verifier 核實——標註：未驗證。）
2. **News impact curve / TGARCH**（已引用 engle1993/zakoian1994，處理尚可）——正文的區分論述（「level-dependent 而非 sign/size-dependent」）站得住。
3. **Attention/habituation**（da2015/andrei2015/vlastakis2012，已引用）——作為機制解釋合理，但只是敘事層。

knowledge.json 有一條重要的自家定位證據：用 absorption factor 調整 VIX **無法**改善波動率預測（adjusted VIX corr 0.669 < raw 0.680，incremental R²=0.002）——「absorption 是描述性現象，非預測工具」。這其實是誠實且可寫進論文的定位（descriptive regularity + risk-management implication），但也封死了「預測改善」這條加值路線。

### 3-B. 方法論 — 證據鏈的真實結構

正文宣稱的證據鏈：SAR（主）→ K897 null（識別）→ NSI/RV 迴歸（輔）→ NFP（事件層）→ cross-asset（外推）。逐環檢視：

**SAR 點估計**：乾淨、可重現（gate 綁定）。但 Table 3 的 **p 值欄（全部 <0.01）無任何 binding**——K716 原始腳本缺失（README 明載），`k716_results.json` 沒有 p 值，表注的描述本身自相矛盾（「two-sample t-test … via bootstrap with 10,000 replications」——到底是 t 檢定還是 bootstrap？bootstrap 什麼統計量？有無 seed？）。**主要證據表的 inference 欄目前是 unverifiable**。

**K897 null 模擬 — 本篇最重要的識別證據，有一個結構性缺口**（本輪深審最重要發現）：

- 模擬中 day-t 的「VIX 等價物」是 `cond_vol_ann[t] = sqrt(h[t])·sqrt(252)`，而 GJR 的 `h[t]` 由 t−1 的資訊決定（`k897_sar_null_simulation.py:269-278`）——**F_{t−1} 可測**。shock 旗標 `|Δcond_vol[t]|>2` 因此與當日 innovation z_t 統計獨立。
- 真實世界的 ΔVIX_t 是**同日**的：VIX 在市場崩的當天同步暴漲。實證 shock day 的高 |r_t| 有很大成分來自這個同期共動。
- 後果直接寫在結果裡：模擬 SAR 水準 ≈ 1.01–1.23，實證 ≈ 2.33–3.16（`fixed_threshold_results`）。null 世界裡 shock day 幾乎不比 normal day 大——因為它的 shock 定義根本抓不到當日大波動。
- **正確的 null** 應該用 `h[t+1]`（觀測完 r_t 之後的 GARCH forecast）作 day-t implied-vol proxy——這才是「收盤 VIX 反映當日資訊」的類比。在那個 null 下，shock day 會機械性地就是大 |r_t| 日，SAR 水準會逼近實證值，而 **calm-to-high decline 是否仍在 null 之外才是真檢定**。
- 現有結果並非無資訊：fixed-threshold null 下模擬 decline 均值 0.173（±0.211），代表「固定加法門檻 × GARCH 動態」本身就製造一部分 decline，而實證 0.816 遠大於它（z=3.05, p=0.0023）。但在 timing 修正後這個 margin 可能大幅縮小。**這是整篇論文的 make-or-break 檢定，還沒跑。**
- 附帶 QC 發現：(a) `percentile_threshold_results` 整組 robustness **silently failed**（全 regime `n_valid_sims=0, "Insufficient data"`），JSON 留著但論文沒揭露這個變體失敗；(b) `fixed_threshold_results` 的 z_score 有計算 bug（z = Cohen's d × 100，誤用 sim_std/√n 當標準誤，得到 z=1967 這種荒謬值）——結論不受影響（`frac_sim_above_empirical` 這個誠實統計量 4/5 regime = 0.0），但顯示產出未經 review；(c) `k897_sar_null_simulation.py:381` 有一行單位錯誤的 dead code（隨即被 384-387 行正確版覆蓋，無實害）。

**NSI/RV 迴歸家族**：pinned snapshot 下全面失去顯著性（baseline t=−1.77、controlled t=−1.26、五個 threshold 全不過 5%、subperiod 只剩 GFC era 過、2020–2026 翻正號）。唯一強的 RV-normalized（t=−8.2）已被 6/10 audit 正確地降級為「shares denominator-regressor correlation, awaits placebo calibration」。**結論：量化 inference 目前實質上只剩 SAR（p 值無 binding）+ K897（null 有 timing 缺口）兩根柱子。**

**NFP 事件研究**：方向一致但弱（整體 p=0.061/0.081，高 VIX regime n=28）。binary dummy 而非 surprise magnitude 的限制已誠實披露（§5.3 limitation 段寫得好）。但有 binding 錯誤見 §4-C7。

**Cross-asset**：K1418 pinned rerun 後 GLD/TLT 顯著、SPY marginal、0050.TW null——誠實。0050.TW 的「VIX 是 US-specific fear gauge」解釋合理且給了 VIXTWN 這個可檢驗的 future work。

### 3-C. 統計嚴謹度細項

- **NW(10) 用於 shock-day 子樣本**：shock days 在日曆上不連續，10 lags 是「觀測序」還是「日曆日」的自相關校正？未說明。n=768 下 canonical bandwidth ceil(n^{1/3})≈9.2→10 碰巧一致，數值上無大礙，但正文應一句話交代（shock-day 序列的 loss autocorrelation 結構）。
- **Shock 定義混合 VIX 上升與下降**：|ΔVIX|>2 把恐慌暴漲日與 relief rally 日混在同一個「fear shock」桶。高 VIX regime 的 shock day 有大量 VIX 下降日。敘事（「fear shocks」）與定義（對稱）不一致，需要 sign-split robustness。
- **固定加法門檻的相對強度問題**：VIX=12 時 ΔVIX=2 是 17% 的相對變動；VIX=40 時只有 5%。高 regime 的「shock」相對更弱，SAR 遞減有一部分是選樣機械效應。K897 的 fixed-threshold null 涵蓋了這一項（這是它的優點），但需在 timing 修正後的 null 下重新評估，並補 relative threshold（|ΔVIX|/V > x%）robustness。
- **同名統計量跨 snapshot 並用**：Abstract/K897 用 decline=0.816（K897 自抓 yfinance 的樣本），Table 3 隱含 decline=3.16−2.32=0.84（K716 pinned 值）。差異小但 referee 對「同一個數字兩個值」零容忍。K897 的實證端也是 live yfinance 下載（`get_empirical_data()`），未走 pinned CSV——與論文的 snapshot-pinning 原則不一致。

### 3-D. 內部一致性 — 5 處 referee 一眼可抓的矛盾（全部已實錘）

| # | 位置 | 矛盾內容 | 證據 |
|---|------|---------|------|
| C1 | Intro line 76 | 「We find that the VRP narrows at high VIX (+2.8% vs +3.5%) but remains strictly positive---there is no VRP sign flip」——但 §5.5 已把 VRP 全部降級為 deferred（「not as active numerical evidence」），且唯一存活的 artifact `experiments/k720_results.json` 寫 **`vrp_flip_confirmed: true`**——與宣稱**正好相反** | 6/10 audit 已抓到 k720 反向，6/11 修復只降級了 §5.5，漏了 Intro 這句 |
| C2 | Table 2 note (line 284) | 「The absorption regression (Tables cross_asset_detail and robust_threshold) reports N=893」——這兩張表現在報的是 769/768。stale cross-ref | 對照 line 467-471, 715-718 |
| C3 | Table 4 (line 351) | 0050.TW 行 = **+0.00019 / t=+1.62 / p=0.106（舊 snapshot 值）**，表注卻宣稱全表「under the 2026-04-19 pinned snapshot… consistent with Appendix Table B」；Intro (line 74) 寫 +0.000092（pinned）、Appendix B 寫 +0.92e-4 / t=+0.28。同一統計量三處兩個值 | `k1418_results.json`: beta=9.21e-5, t=+0.283 |
| C4 | Appendix Table B (lines 715-718) | α 欄（0.092/0.099/0.094/0.073）與 adj R² 欄（0.012/0.024/0.023/−0.001）**與 k1418 產出不符**（CSV: α=0.0822/0.0548/0.0531/0.0473；R²=0.0076/0.0142/0.029/−0.0013）。β/t 欄是 pinned 值、α/R² 欄是舊值——同一行左右欄來自兩個 snapshot 的 chimera。6/10 audit 只 spot-check 了 JSON 有的 β/t 欄，漏掉 CSV 才有的 α/R² | `experiments/k1418/tables/k1418_cross_asset.csv` |
| C5 | §5.3 line 368 | 「NFP days produce absolute returns **1.17 times the non-NFP average**」——1.17 是 **vs-Friday** 的比值（k741: ratio_vs_friday=1.165），vs 全部非 NFP 是 **1.14**（ratio_vs_all=1.145）。標籤與數字錯配；另 footnote 的「4,081 trading days」與 JSON 隱含的 195+3909=4,104 不符 | `k741_nfp_event_study_results.json .part_a_historical` |

### 3-E. 引用完整性

- **4 條孤兒引用**：`chernov2018`（且 bibitem label 2018 / 內文 2022 的年份錯誤也還沒修——R1 S5 指名的問題）、`baur2010`、`patton2011`、`romer2004`——全部在 bibliography 但正文 0 引用。
- **zakoian1994 期刊錯誤**（6/10 audit 已抓）：正文寫 *Journal of Time Series Analysis*, 15(3), 253–266；正確出處是 *Journal of Economic Dynamics and Control*, 18(5), 931–955（標註：依 reviewer 記憶 + audit 佐證，最終以 citation-verifier 為準）。
- 其餘約 30 條經 6/10 audit 抽查大致正確；全部無 DOI（投稿格式化時要補）。

---

## 4. 風險與致命傷（嚴重度排序）

1. **【致命】K897 timing 錯配**（§3-B）：識別核心建立在弱 null 上。若 contemporaneous null 吃掉 decline，全篇主張需重寫。這是唯一能殺死論文的風險，也是唯一還沒跑的關鍵檢定。
2. **【致命級不一致】C1 VRP 反向宣稱**：一句與自家 artifact 相反的「We find」留在 Intro。referee 或任何 replicator 抓到即喪失全篇可信度。修復成本：刪或改寫一句話。
3. **【重大】Table 3 p 值無 binding**：主要證據表的 inference 欄 unverifiable，且 K716 腳本永久缺失（K1249 確認 rebuild blocked）。必須用 pinned snapshot 重寫 SAR inference 腳本。
4. **【重大】C3+C4 混 snapshot chimera 表**：6/10 audit 修復不完整的直接殘留。機械修正即可，但不修不能投。
5. **【中】統計顯著性整體薄弱**：pinned snapshot 下 NSI 家族全不顯著。論文已誠實降級敘事（「directionally consistent」），但 top-tier referee 會問「除了 SAR 和模擬，你還剩什麼」。答案必須是修好的 K897 + 補強的 SAR inference。
6. **【中】Prior-art 防線未築**（Low 2004 / Hibbert et al. 2008 未引用未區分）。
7. **【低】C2/C5、孤兒引用、zakoian 期刊、K897 z-score bug、percentile 變體 silent fail、shock sign-split 缺失——逐項可修的衛生問題。**

---

## 5. 接下來的研究計畫

### P0（gate：不完成不得標 ready / 不得投稿；預估 1–2 工作天）

| 項 | 內容 | 產出 |
|---|------|------|
| **P0-1** | **開新 K：contemporaneous null 重跑 K897**。改動極小：`simulate_garch_sar_fixed_thresholds` 中 day-t vol proxy 改用 `h[t+1]`（觀測 r_t 後的 forecast），shock 定義隨之同期化；同 seed 集、同 10k paths；同時加 relative-threshold（|Δproxy|/proxy > 對應百分位）變體與 sign-split。**判定規則（事前寫死，研究誠實）**：empirical decline 仍在 95% null 外 → 識別關閉，論文顯著升級；落入 null 內 → absorption 主張降級為「fixed-threshold 選樣 + 同期共動的機械分解」，走重新框架路線（§6）。無論哪個結果都要如實寫進論文。 | `experiments/k1683/`（或下一個可用 K 編號）三件套 + main_v3 §Robustness 更新 |
| **P0-2** | **修 5 處內部不一致**（C1–C5，§3-D 表）。C1 刪句或改寫為 deferred 口徑；C3/C4 用 k1418 pinned 值統一（0050.TW 行 + α/R² 欄）；C2 改寫 stale note；C5 改成「1.14× vs all non-NFP（1.17× vs Fridays）」並修 4,081→JSON 一致值。 | main_v3.tex diff + 重編譯 |
| **P0-3** | **Table 3 inference rebuild**：pinned CSV 上重算五 regime SAR + seeded bootstrap（明確統計量：SAR_calm − SAR_j 的 percentile CI），產出 JSON、綁進 reproduce.py、更新表注（消掉「t-test via bootstrap」的混亂描述）。 | 新腳本 + JSON + reproduce.py 新增 checks |
| **P0-4** | **reproduce.py 補 checks**：Table 4 0050.TW t、Appendix B α/R²（讀 k1418 CSV）、NFP overall ratio/p、Table 3 新 p 值。gate 從 30 checks 擴到 ~40。 | reproduce_report 重跑 green |

### P1（投稿前完成；預估 2–3 工作天）

- **P1-1** 引用修理：刪或補引 4 條孤兒、修 zakoian 出處、修 chernov 年份；跑 citation-verifier 全掃。
- **P1-2** Prior-art 段落：Intro/Lit review 補 Low (2004)、Hibbert et al. (2008)、Fleming-Ostdiek-Whaley (1995) 並正面區分（SAR 的 within-regime 設計 + null 模擬是相對這批文獻的增量）。
- **P1-3** K897 衛生：z-score 修正、percentile 變體失敗揭露或修復、實證端改讀 pinned CSV、0.816 vs 0.84 統一為 pinned 口徑。
- **P1-4** NW lag 一句話交代 + shock-day 序列 acf 診斷附錄。

### P2（R&R 彈藥 / 選擇性）

- **P2-1** NFP surprise-magnitude 規格（Philadelphia Fed real-time dataset；正文 future work 已承諾的 β₃ interaction 規格）。
- **P2-2** VIXTWN/V2X local-vol-index 擴充（0050.TW 的正面檢定）。
- **P2-3** Deferred sections（shock-type / VRP / hedging）pinned-snapshot 重建——**建議放棄回填、維持 deferred**：K716–K722 腳本永久缺失，重建成本高且 K720 artifact 與敘事反向；新論文空間有限。

### 期刊目標建議（目前 TBD → 給明確推薦）

- **Primary: Journal of Banking & Finance**。理由：fear/attention 主線文獻（Vlastakis & Markellos 2012）在 JBF；R1 reviewer 也判「realistic chance at JBF or JFQA」；主題（risk management implication + VIX regime）是 JBF 的核心讀者群；JFE/RFS 等 top-5 對「描述性現象 + 無理論模型 + 無預測增益」的容忍度太低，不建議浪費一輪。
- **Backup: Journal of Empirical Finance 或 International Review of Financial Analysis**（若 P0-1 結果偏弱、需降層投遞）。
- **重新框架情境**（P0-1 失敗）：以「VIX-shock 選樣的機械分解」為主軸改寫成 measurement note 投 **Finance Research Letters**，或將 SAR/null-simulation 方法併入其他 VIX 系列論文。

---

## 6. Go / No-Go 建議

**有條件 GO——P0-1 是唯一的決定點，先跑它再談其他投入。**

- **不建議 archive/merge（現在）**：(a) 修復成本低（P0 全部 1–2 天）而資訊價值高；(b) reproducibility 基建（pinned snapshot、gate、audit trail）已是沉沒投資中可復用性最高的部分；(c) 概念與 K897 框架即使在最壞情境下也能降級改寫（FRL note 或併入其他 paper），不會歸零。
- **不建議按現狀繼續 revision-polish**：在 P0-1 跑完之前做任何文字打磨都是錯誤的投入順序——若 contemporaneous null 吃掉效應，打磨全部作廢。
- **Hard gate（事前承諾，研究誠實）**：P0-1 若顯示 empirical decline 落入 contemporaneous null 的 95% 區間，本篇不得以「volatility absorption 是超越機械效應的現象」為主張投稿；屆時二選一——重新框架為機械分解 note，或 merge/archive。判定以實驗 JSON 為準，不以敘事偏好為準。
- 7 週 stall 的流程教訓：deferred-scope 決策做完後沒有指派「下一個 make-or-break 檢定」的 owner。建議把 P0-1 直接排入 `storage/next_tasks.json`（P1 priority，experiment 類型，引用本報告路徑作 brief）。

---

## 附錄：本輪抽查與證據路徑

- 數字抽查（5 組，全對）：§2「撐得住的部分」。
- 內部不一致證據：§3-D 表格內逐項標注 JSON/CSV 路徑。
- K897 timing 分析依據：`paper/volatility-absorption/experiments/k897_sar_null_simulation.py` lines 269-316（h[t] 遞迴與 shock 定義）、`k897_sar_null_simulation_results.json .fixed_threshold_results`（sim SAR 1.01–1.23 vs empirical 2.33–3.16）。
- 未驗證項（依研究誠實原則標注）：Low (2004)/Hibbert et al. (2008)/FOW (1995) 的書目細節、zakoian 正確出處——均為 reviewer 記憶，投稿前須 citation-verifier 核實。
- 本報告未改動 main_v3.tex、任何 experiment JSON 或共享狀態；未 git commit（依任務約束，commit 由主線程決定）。
