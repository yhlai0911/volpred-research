# Fable 深度審查 — vt-insurance-cost（Paper 4）

**日期**：2026-07-11 22:37（台灣時間）
**審查者**：Fable 深度審查 agent（頂級期刊 referee 水準檢視，user-assigned P0）
**審查對象**：`main.tex`（mtime 2026-07-06 17:43，v3 修訂後）+ 完整 replication package
**證據方法**：整篇 tex 精讀；Table 1 / Table 2 / DM / regime / sensitivity / K846 全部數字逐一對照
`experiments/*.json`；review_history v1–v3 + diagnosis + audit 全讀；canonical `dm_test`
（`src/volpred/stats/model_evaluation.py:89-117`）code 檢視；`storage/ops/dm_hac_lag_baseline.json` 查核；
與 `vt-trend-following`、`vt-crowding-abm` 兩篇同族論文 README 對照。

---

## 1. 執行摘要

**Verdict：3.5 / 5 ★ — GO（獨立成篇，FRL）。已不是 major revision；是「收尾差一哩路」的 minor-to-moderate revision。**

三句話：
1. 核心貢獻（保險費 = 機會成本 91% + 交易成本 9% 的分解）誠實、可追溯、數字全部驗證吻合 —— 本次抽查 Table 1 全表、Table 2 全表、6 個 DM t 值、4 個 regime 數字、3 個 sensitivity 門檻、K846 的 54 bps / ρ=0.0572 / 子期間 −95/−56 bps，**零不符**。
2. v2 review 的 3 個 SEVERE（S-01 benchmark 標籤、S-02 cross-OOS 4/6、S-03 公式 drift）在 v3 已全部誠實解決，S2 已降級為 hypothesis-generating；**但 README 狀態過時（仍寫 S-02 pending，實際 2026-07-06 17:45 已完成）**，pipeline 顯示的「stall 7 週」有一半是狀態檔沒更新造成的假象。
3. 真正剩下的攔路石不是學術內容，是 **replication package 衛生**：包內存在一個與論文數字矛盾的 stale JSON（`k811v2_sensitivity_sweep.json`）且 README 的實驗索引正指向它、一個貼錯標籤的結果檔、以及一份過期（2026-04-20）的 reproduce gate —— referee 跑 package 第一天就會踩到。

---

## 2. 現況盤點

### 2.1 卡在哪（stall 診斷）

Pipeline（`storage/paper_pipeline_status.json`）：stage=`revision` 自 2026-05-21、blocker=`finishing/journal choice`、`journal_target="decide"`。但 git 事實是：

| 日期 | 事件 |
|---|---|
| 2026-06-10 | 針對性 audit（DM footnote / 缺 window 揭露 / premium 平均化敘述）3 HIGH 修畢 |
| 2026-07-05 | v1 citation-only 診斷 |
| 2026-07-06 | v2 首輪完整 review（2.5★，3 SEVERE）→ **同日** v3 修訂：S-01 relabel、S-03 公式對齊、C-01 改述、S-02 六窗補跑完成（`review_history/v3/s02_cross_oos_rerun_report.md`） |

所以「stall 7 週」的實況是：5/21–7/05 確實閒置，但 7/05–7/06 兩天內完成了首輪完整 review + 3 SEVERE 全修。**現在卡的只有：(a) README/pipeline 狀態檔沒有反映 v3 完成度；(b) journal_target 沒定案（README 寫 FRL，pipeline 寫 decide）；(c) 下面 §4 列的 package 衛生問題沒人收尾。** 這是 finishing 問題，不是研究問題。

### 2.2 VT 家族三篇的分工（salami-slicing 檢查）

| 論文 | 問題 | 證據型態 | 目標期刊 | 狀態 |
|---|---|---|---|---|
| vt-trend-following（P3） | VT **是什麼**？（機制：VT ≈ 趨勢跟隨暴露） | 22 資產 panel + 13 市場國際 + 因子控制 | JPM / FAJ | ready_for_submission_candidate（v7 PASS） |
| vt-insurance-cost（P4，本篇） | VT **花多少、花在哪**？（成本會計分解） | SPY 單資產 2012–2024 + K846 再平衡溢酬 | FRL | revision（v3 修畢待收尾） |
| vt-crowding-abm（P5） | **大家都做 VT 會怎樣**？（均衡：crowding 侵蝕） | 純 ABM 模擬 94,500 sims | FRL | narrative rewrite 完成待 review |

**裁定：三篇 claim space 互不蠶食** —— 機制辨識 / 成本會計 / 均衡外部性是三個不同的研究問題，資料集與方法論也幾乎不重疊（panel 因子迴歸 vs 單資產成本分解 vs 模擬）。唯一交集是共用的敘事背景「VT 跑輸 BH / 50/50」（K687 發現），P4 的 §4.4 對 50/50 的結構優勢做了 P3 沒做的量化（K846 再平衡溢酬），屬互補不屬切香腸。**不建議 merge** —— P3 已 33 頁且 ready，塞入 P4 的成本分解只會稀釋其機制故事。

一個要管理的點：**P4 與 P5 同時瞄準 FRL**。同作者短期內對同一期刊投兩篇 VT 主題，desk 端觀感有風險。建議錯開（P4 先投，P5 等 P4 有 first decision 再投），或把其中一篇改投 Journal of Asset Management / JPM。

---

## 3. 學術深度檢視

### 3.1 Contribution（insurance-cost framing 的原創性）

- **核心 claim**：VT 的 return shortfall 中 91% 是機會成本（少持股的放棄報酬）、僅 9% 是交易摩擦（main.tex:36, 174）。文獻裡 Harvey et al. (2018) 把 turnover 當主要 drag 報告、Cederburg et al. (2020) 記錄 OOS 失效，但**「把保險費拆成 opportunity vs direct 並量化占比」的確沒有先行文獻直接做過** —— 論文自己也誠實承認分解「arithmetically straightforward」（main.tex:60），賣點在於量級的實證記錄。這對 FRL（短文、單一乾淨論點）是合格的 contribution；對 JBF/JFE 則不夠（v2 review 判斷一致，我同意）。
- **與 Bongaerts et al. (2020) 的區隔**（main.tex:58）寫得清楚：他們 conditioning on volatility state 做 Sharpe 最適化，本文 conditioning on vol-of-vol 做成本歸因。站得住。
- **貢獻分層在 v3 後是誠實的**：S2（VVIX 條件化）已從 contribution tier 降級為 hypothesis-generating（abstract、§4.5、Discussion、Conclusion 四處一致），2/6 窗口勝率如實報告。robust contribution 只剩分解本身 —— 這是對的取捨。

### 3.2 方法論

以 `.claude/rules/experiments.md` Methodology 硬規則逐條核對：

| 硬規則 | 狀態 | 證據 |
|---|---|---|
| Lookahead / lag | ✅ PASS | code 全用 `*_lag` 欄位（`k811v2_insurance_premium_vov_fixed.py:213-216, 314-316`）；v2 review 曾獨立驗證 clean；S-02 rerun code review 再確認 |
| DM HAC 落後期不可只用 h−1 | ✅ PASS | primary path import canonical `strategy_dm_test` → `dm_test` 用 `max_lag = ceil(h^{1/3}·n^{1/3})` = 15（`model_evaluation.py:101`）；論文 footnote「maximum lag ⌈T^{1/3}⌉」與 h=1 時的 canonical 一致。archived t=2.4183 與 rerun t=2.4156（N 差 1 天）到小數三位一致，可證兩次都走 canonical path 而非 lag-1 fallback |
| dm_hac_lag 凍結 backlog | ✅ 無影響 | baseline 只含 `k786`（前身實驗，未被本論文引用）；k811v2/k846 不在凍結名單 |
| 跨資產 pooled iid | N/A | 單資產 SPY，DM 是同日兩策略報酬差，無 pooling 問題 |
| QLIKE 方向 | N/A | 無 variance-forecast loss；DM loss = −r（negative_return），實作與 footnote 相符（audit 2026-06-10 HIGH#1 已修） |
| Uniqueness claims retrofit 重驗 | ✅ | 無 uniqueness framing；v3 後所有強 claim 已降級 |
| 修訂型總經資料 vintage | N/A | 只用市場價格資料（SPY/GLD/VIX/VVIX），無 revision 問題 |

方法設計本身的 referee 級評語：

1. **「opportunity cost」是淨額不是毛額**（可修的概念性弱點）：IP_opp = r̄_BH − r̄_VT,gross 已經**淨掉了危機期 VT 少虧的「保險理賠」**。它不是純「放棄的上漲」，而是「放棄的上漲 − 躲掉的下跌」。論文的詮釋（「foregone equity participation during elevated-VIX periods that are followed by positive returns」）方向正確但沒把這件事講明。regime 分析其實已隱含此點（HighVoV_Falling 的 opp cost 19.95% vs LowVoV_Falling 2.54%，JSON 驗證吻合）。建議加一段明確定義：IP_opp 是 net-of-payout 的口徑，並說明這使 91% 是保守（偏低）估計還是偏高估計。
2. **費率假設的方向性正確**：c=5 bps 對「機會成本占比高」是保守設定（費率越高、direct 越大、opp share 越低）；1 bp 下 98% 的補充（main.tex:108）方向也對。內部一致性驗證：S1 turnover 872.4% × 5 bps = 0.436%/yr ≈ JSON direct 0.428 ✅。
3. **S2 在啟動 regime 內其實比 S1 更貴**：HighVoV_Rising 內 S2 total cost 6.85% > S1 5.54%（進出場 whipsaw：direct 1.99 vs 0.68；JSON `insurance_by_regime`）。論文沒提。這不推翻結論（S2 省的是其他 76% 天數的 opp cost），但主動揭露會更防 referee。
4. **無任何圖**。FRL 短文可以無圖，但一張「累積財富 + VoV regime 底色」圖能讓 2/6 勝率與 2018/2020 兩次理賠一眼看懂，性價比極高。

### 3.3 統計嚴謹度

- DM 全表誠實：無一對通過 Harvey |t|>3（S1 vs S0 t=2.42、S2 vs S0 t=0.75，JSON 驗證吻合），論文如實引用且不借 p<0.05 偷渡顯著性。✅
- Cross-OOS 六窗完整（2026-07-06 rerun），2/6 勝率如實寫進 abstract。✅
- **缺口**：91% 這個 headline share 沒有抽樣不確定性度量。建議 stationary bootstrap（固定 seed）給 opp share 一個 95% CI —— 成本低、對 referee「這 91% 有多穩」的必然提問是直接答案。
- 敏感度分析（門檻 0.5/1.0/1.5 → share 64/57/65%，reduction 62–76%）**數字驗證吻合**（`k811v2_th{0_5,1_0,1_5}_results.json`：1.137/1.772=64.2%、0.696/1.218=57.1%、0.737/1.129=65.3%；reduction 61.7/73.7/75.6%）。✅ 但見 §4 的 package 矛盾檔問題。

### 3.4 內部一致性（本次新抓到的問題）

1. **§4.4 期間混用**（main.tex:184）：「SPY and GLD exhibit near-zero correlation (ρ=0.057) over the extended 2006–2024 sample period, producing a portfolio volatility of 11.47%—30.7% below SPY's standalone volatility of 16.56%」—— ρ=0.0572 是 2006–2024（K846 ✅），但 **11.47% / 16.56% 是 2012–2024 的 K811v2 Table 1 數字**；K846 自己的 2006–2024 年化波動是 SPY 19.38% / GLD 17.76%（`part1_theoretical`）。同一句話裡兩個樣本期的數字被縫在一起，referee 必抓。修法：改用 19.38%（並重算折減幅）或把句子拆成兩個明確 scope。
2. **Eq. (3) 的 N 符號衝突**（v2 M-01，v3 未修）：`IP_direct = Σ c|Δw|/N`、「annualized over N years」，但全文 N=3,262 是交易日數。建議 T=3262、Y=T/252≈12.94 分開記號。
3. **README 狀態過時**：`README.md:4` 仍寫「cross-OOS still covers only 4 of 6 … re-runs pending」，實際 6/6 已於 2026-07-06 完成。
4. **孤兒 K ref**：README 列 K860（prospect theory）為 supporting，但 main.tex 全文未使用 → 依 paper-workflow 檢查清單需明註「unused in final draft」或移除。
5. Abstract「S2 outperforms buy-and-hold in only 2 of 6 windows」未註明是 Sharpe 口徑（rerun 表是 Sharpe 比較）。一字之修。

---

## 4. 風險與致命傷

**致命傷 0 個（學術內容層面）。** 高風險 finishing 問題 3 個 + 中風險若干：

| # | 等級 | 問題 | 證據 |
|---|---|---|---|
| R1 | **HIGH（package）** | **包內矛盾 stale 檔**：`experiments/k811v2_sensitivity_sweep.json` 的數字（s1_total=3.75、S2 reduction 為**負**：−30.5/−13.1/−8.5%）與論文及 `k811v2_th*_results.json` **完全矛盾**（疑似修 bug 前的舊 run 殘留）。而 `README.md:41` 的實驗索引寫「`k811v2_sensitivity_*.json` — Sensitivity analysis results」**正指向這個錯檔**。referee 跑 package 會直接得出「敏感度分析與論文不符」的結論 | 本次 jq 對讀 |
| R2 | **HIGH（package）** | `k811v2_threshold_0.5_results.json` 內容是 threshold=1.0 的結果（regime counts 1485/999/467/251、S2 CAGR 11.144 與主檔完全相同；真正的 0.5 門檻檔 `k811v2_th0_5_results.json` regime counts 是 1244/784/682/492）→ 檔名與內容不符。另有 `_tmp_th*.py` 三個暫存檔留在 package 內 | 本次 jq 對讀 |
| R3 | **HIGH（gate）** | reproduce gate 過期：`reproduce_report.json` 是 2026-04-20 產物，引用的 main.tex 行號對不上 v3 文本；claim #9 靠放寬 tolerance 5→10 bps 才 green（62.91 vs 54 bps，股息口徑差異）。依 paper-workflow 硬規則 #2，v3 後必須重跑；claim #9 建議直接把正文 headline 錨到 replication 口徑（raw-Close ≈63 bps），54 bps 降到註腳，恢復 5 bps tolerance 拿真 green | `reproduce_report.json` + `reproduce.py:374` |
| R4 | MED | §4.4 期間混用（§3.4-1）+ Eq.(3) N 衝突（§3.4-2） | main.tex:184, 86-89 |
| R5 | MED | v2 的 8 個 MEDIUM citation 問題只修了 C-01；C-02–C-09 全數未動：12/VIX 過度歸功 perchet（main.tex:70）、perchet 年份/key 不符（bibitem 2015 vs key perchet2016）、「consistent with CRSP to within rounding precision」無佐證（main.tex:108，建議刪）、cboe2014 白皮書不可驗證、harvey2018/harvey2016/liu2019/fleming2001 支撐度措辭 | `review_history/v2/citation_check_report.md` |
| R6 | MED | P4 與 P5 同投 FRL 的時序風險（§2.2） | — |
| R7 | LOW | 91% share 無 CI；gold crisis-alpha claim（main.tex:184）無表支撐（v2 M-07）；S2 啟動 regime 內成本高於 S1 未揭露 | §3.2, §3.3 |

---

## 5. 接下來的研究計畫

### P0 — 收尾必做（合計約 1 個工作 session + 一次 reproduce 重跑）

1. **Package 衛生清掃**：刪除或重生 `k811v2_sensitivity_sweep.json`（若保留須與 th* 檔一致並註明產生腳本）；修正 `k811v2_threshold_0.5_results.json` 錯標（重跑 threshold=0.5 或改名）；移除 `_tmp_th*.py`；README 實驗索引改指 `k811v2_th{0_5,1_0,1_5}_results.json`；K860 標註 unused。
2. **Reproduce gate 重跑 + claim #9 re-anchor**：正文 54 bps → raw-Close 62.91 bps 為 headline（54 bps 移入現有雙口徑註腳），tolerance 收回 5 bps，對 v3 文本重產 `reproduce_report.json`（行號 binding 更新）→ 真 green。
3. **文字修正三件**：§4.4 期間混用（換 K846 的 19.38% 或拆句）、Eq.(3) T/Y 記號、abstract 補「(Sharpe basis)」。README 狀態段同步 v3 實況；pipeline `journal_target` 定為 FRL。

### P1 — 投稿前強化（1–2 sessions）

4. **Citation 清理**（C-02–C-09 一次修完，跑 citation-verifier 複核）。
5. **一張主圖**：累積財富曲線（S0/S1/S2/S4）+ VoV regime 底色 + 2018/2020 標註；可順帶做 gold-by-regime 迷你表（收掉 M-07）。
6. **91% share 的 stationary bootstrap 95% CI**（固定 seed；直接回答 referee 必問題）+ 一段「IP_opp 為 net-of-payout 口徑」的定義澄清。

### P2 — 投稿與後續

7. **journal-review skill 跑 FRL profile gate**（字數/格式/highlights/合規），與 P5 錯開投稿時序（P4 先行）。
8. （選配，非本篇 blocker）跨資產延伸（QQQ/EFA/EEM 的 opp/direct 比率）留作下一篇或 revision 彈藥，不進本稿。

**期刊建議**：**FRL（主）** — 短文、單一乾淨 empirical point、與其 letter 格式高度匹配；備援依序 Journal of Asset Management、JPM（practitioner 角度）、IJF（偏 forecasting，fit 較弱）。JBF+ 需要跨資產外部驗證與更強識別，本稿不必追。

---

## 6. Go/No-Go 建議

**GO — 獨立成篇投 FRL。不 merge、不 archive。**

- 不 merge into vt-trend-following：兩篇問題不同（機制 vs 成本會計）、方法不同、期刊層級不同；P3 已 ready，合併是雙輸。
- 不 archive：核心數字全部可追溯且誠實，v2→v3 的修訂軌跡展示了研究誠實原則的正面案例（S2 主動降級、負面子期間主動揭露）。剩餘工作是 finishing，不是 rescue。
- 條件：P0 三項完成前**不得**標 ready / 進 journal gate（reproduce gate 硬規則）。P0+P1 完成後預估可達 v2 reviewer 預測的 FRL ~3.5★ 投稿水準。

---

### 附錄：本次數字驗證清單（全部吻合，0 不符）

| 論文數字 | 來源檔 | 驗證值 |
|---|---|---|
| Table 1 全表（5 策略 × 8 指標） | `k811v2_..._fixed_results.json .full_period_metrics` | ✅ 全吻合（如 S0 CAGR 12.506→12.51、S2 Sharpe 0.6335→0.63） |
| Table 2 分解（3×3 + shares + Δ） | 同上 `.insurance_cost_decomposed` | ✅（4.195/0.428/4.623；90.74%；−73.65%；−28.4%） |
| DM t 值（6 對） | 同上 `.dm_tests` | ✅（S1vS0 2.4183≈2.42；S2vS0 0.7487≈0.75） |
| Regime（19.95%/2.54%/7.7%/45.5%/86%/76%） | 同上 `.insurance_by_regime`, `.weight_stats` | ✅ |
| Sensitivity（64/57/65%；62–76%） | `k811v2_th{0_5,1_0,1_5}_results.json` | ✅（64.2/57.1/65.3%；61.7–75.6%） |
| K846（54 bps；ρ=0.057；10.02 vs 9.49；−95/−56 bps） | `k846_rebalancing_premium_results.json` | ✅（53.67；0.0572；10.0234/9.4867；−95.27/−55.55） |
| Cross-OOS 2/6、S4 3/6 | `..._cross_oos6_results.json` + v3 report | ✅ |
| 內部一致性抽核：turnover×費率 vs direct cost | 872.4%×5bps=0.436 vs 0.428 | ✅ |

未驗證項：FRL 現行字數上限（需 journal-review skill 於投稿 gate 時查證）；Codex spot-check 的「真月頻 50/50 Sharpe ≈0.59」（引自 v2 review，未重算）。
