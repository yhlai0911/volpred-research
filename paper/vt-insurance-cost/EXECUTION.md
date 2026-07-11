# EXECUTION — vt-insurance-cost

> **BADGE** · verdict `3.5/5` · stage `revision`（**從未投稿**）· journal `FRL` · **p0 = DONE** · **p1 = TODO** · dod `4/7`
> 依據：`review_history/fable_deep_review_20260711/README.md`（Fable 深審 3.5/5 GO — 獨立成篇 FRL）· `README.md` 狀態段 · `storage/paper_pipeline_status.json`
> 最後更新：2026-07-11（Fable P0 finishing pass 完成；全 portfolio 唯一 P0=DONE 的論文）

---

## 最終目標

把 vt-insurance-cost 從「finishing 差一哩路」推進到 **Finance Research Letters（FRL）可投稿** —— 深審已判 GO（獨立成篇，不 merge、不 archive），核心數字全部誠實可追溯，剩下的是投稿包強化（P1）而非研究層修補。

**核心貢獻（保留、不稀釋）**：波動率目標（VT）策略的 return shortfall 中 **91% 是機會成本**（elevated-VIX 期間少持股放棄的上漲）、僅 **9% 是交易摩擦**（direct turnover cost）。文獻（Harvey et al. 2018 把 turnover 當主 drag、Cederburg et al. 2020 記錄 OOS 失效）從未把保險費拆成 opportunity vs direct 並量化占比 —— 本篇的賣點是這個量級的實證記錄。單一乾淨 empirical point + letter 格式高度匹配 FRL；S2（VVIX 條件化）已誠實降級為 hypothesis-generating（2/6 Sharpe-basis 勝率如實報告），robust contribution 只剩分解本身，是對的取捨。

**期刊順序（已裁定）**：
1. **FRL（primary）** — 短文、單一 point、與 letter 格式匹配；分解「arithmetically straightforward」但量級記錄是合格 contribution。
2. **Journal of Asset Management / JPM（practitioner 角度，secondary）** — FRL 被拒後改投。
3. **IJF（backup，fit 較弱）** — 偏 forecasting，本篇是成本會計，適配度低。

> **關鍵裁定（寫進本檔以免再被誤導）**：deep review §2.2 確認 VT 家族三篇（P3 vt-trend-following「VT 是什麼」/ P4 本篇「花多少花在哪」/ P5 vt-crowding-abm「大家都做會怎樣」）**claim space 互不蠶食**，資料集與方法幾乎不重疊。**不 merge into vt-trend-following**（P3 已 33 頁且 ready，塞入成本分解只會稀釋機制故事，雙輸）。唯一要管理的是 **P4 與 P5 同瞄 FRL 的投稿時序** → P4 先投，P5 等 P4 有 first decision 再投（見 P2）。

---

## 當前狀態

**Verdict 3.5 / 5 ★ — GO（獨立成篇投 FRL）。已不是 major revision，是 minor-to-moderate finishing revision。**

- **實驗層健全** ✅：deep review 逐格抽查 Table 1 全表、Table 2 分解、6 個 DM t 值、4 個 regime 數字、3 個 sensitivity 門檻、K846 的 54 bps / ρ=0.0572 / 子期間 −95/−56 bps，**零不符**。方法論硬規則逐條 PASS（lag 全用 `*_lag` 欄位；DM 走 canonical `strategy_dm_test`→`dm_test` 的 `ceil(h^{1/3}·n^{1/3})`=15 HAC bandwidth；**不在** DM-HAC 凍結 backlog 內 —— baseline 只含前身 k786，k811v2/k846 未列）。
- **P0（收尾）已於 2026-07-11 由主線程真實完成** ✅ —— 見下方 P0 段，全 portfolio 唯一 P0=DONE 的論文。package 衛生 + reproduce gate 9/9 真 green + main.tex 三處文字修正皆已落地並 commit。
- **「stall 7 週」有一半是假象**：git 事實顯示 7/05–7/06 兩天內完成首輪完整 review + 3 SEVERE 全修（S-01 relabel / S-02 六窗補跑 / S-03 公式對齊），5/21 起的閒置有一半是 README/pipeline 狀態檔沒反映 v3 完成度。狀態檔已於 P0 同步。
- **Reproduce gate**（`reproduce_report.json` 2026-07-11 23:21）：`match_rate_pct 100.0` / `alert_level green` / `exit_code 0`。claim #9 已 re-scope 成同口徑檢查（raw-Close 62.910 vs 揭露 ~63 bps，tolerance 收回 5）→ **9/9 真 green，不靠放寬 tolerance**。
- **剩餘工作全在 P1（投稿包強化，非 gate blocker）**：C-02–C-09 citation 清理、一張主圖、91% share 的 bootstrap CI + net-of-payout 口徑澄清。這些不阻擋 gate，但拉高 FRL 錄取機會。

---

## 完成定義（DoD）

- [x] **P0-1** 落地：package 衛生清掃完成（stale sweep JSON 刪 / 錯標 threshold_0.5 檔刪 / `_tmp_th*.py` 改名 `k811v2_sensitivity_th*.py` / 索引三檔同步 / K860 標 unused）— `5183318c0` + `b0ea148e9`
- [x] **P0-2** 落地：reproduce gate 重跑 + claim #9 re-anchor 成同口徑檢查 → `match_rate_pct 100.0` / `green` / **9/9 真 green** — `b0ea148e9`
- [x] **P0-3** 落地：main.tex 三處文字修正（§4.4 期間混用拆句 / Eq.(3) T/Y 記號 / abstract+§4.5 補 Sharpe-basis）+ README/pipeline 狀態同步 — `b0ea148e9`
- [x] `reproduce.py` exit 0 且 `reproduce_report.json` match_rate 100% / **alert green**（已達成，見上）
- [ ] **P1** 落地：C-02–C-09 citation 清理 + `/citation-verifier` 重跑 0 MAJOR + 一張主圖 + 91% share bootstrap CI + net-of-payout 澄清段
- [ ] FRL `journal-review` compliance gate 通過（author = Yi-Hao Lai only；無 volpred / AI / LLM 字樣）+ 字數/highlights 格式檢查
- [ ] main.tex 改動後 **xelatex 重編譯確認** + `uv run volpred ops paper-update --paper-id vt-insurance-cost` 同步 + 線上驗證

---

## P0 — 收尾必做（**已於 2026-07-11 全部完成**）

### ✅ P0-1 — Package 衛生清掃（DONE）

referee 跑 package 第一天就會踩到的矛盾檔已全部清除（修流程不修資料）：

- ✅ **刪除與論文數字矛盾的 stale `k811v2_sensitivity_sweep.json`**（該檔 S2 reduction 為負 −30.5/−13.1/−8.5%，疑似修 bug 前殘留）— `5183318c0`（該 commit 訊息誤標 `test-single-exec-commit-garchx`，實際內容是本篇 package 衛生）
- ✅ **刪除錯標的 `k811v2_threshold_0.5_results.json`**（內容實為 threshold=1.0 結果，檔名與內容不符）+ 冗餘 `k811v2_threshold_0.5.py` / `k811v2_threshold_1.5.py` / `sensitivity_sweep.py` — `5183318c0`
- ✅ **`_tmp_th{0.5,1.0,1.5}.py` 改名 `k811v2_sensitivity_th{0_5,1_0,1_5}.py`** — `5183318c0`（證據：`experiments/k811v2_sensitivity_th0_5.py` 已存在）
- ✅ **README/experiments.md/scripts/README.md 三檔實驗索引同步**，改指 `k811v2_th{0_5,1_0,1_5}_results.json`；K860（prospect theory）標「**unused in final draft**」— `b0ea148e9`

### ✅ P0-2 — Reproduce gate 重跑 + claim #9 re-anchor（DONE）

- ✅ claim #9 由「靠放寬 tolerance 5→10 才 green」re-scope 成**同口徑檢查**：raw-Close **62.910** vs 揭露 ~63 bps，tolerance 收回 5 → **9/9 真 green，不靠放寬** — `b0ea148e9`
- ✅ 對 v3 文本重產 `reproduce_report.json`：`match_rate_pct 100.0` / `alert_level green` / `reproduce_exit_code 0`（timestamp 2026-07-11T23:21:15+08:00）
- ✅ 行號 binding 更新至 v3 文本

### ✅ P0-3 — main.tex 三處文字修正 + 狀態同步（DONE）

- ✅ **§4.4 期間混用拆句**（原句把 2006–2024 的 ρ=0.0572 與 2012–2024 的 11.47%/16.56% 縫在一句 → 拆成明確 scope）— `b0ea148e9`
- ✅ **Eq.(3) 的 N 符號衝突**：交易日數 T 與年數 Y=T/252 分開記號 — `b0ea148e9`
- ✅ **abstract + §4.5 補「(Sharpe basis)」**（S2 outperforms buy-and-hold in only 2 of 6 windows 標明是 Sharpe 口徑）— `b0ea148e9`
- ✅ README 狀態段同步 v3 實況（S-02 no longer pending）；pipeline `journal_target` 定為 FRL — `b0ea148e9`

> **P0 完成 ≠ 可投稿**：P0 是「拆掉 referee 第一天會踩到的地雷」，投稿水準要 P1 補足（citation + 圖 + CI）。且 main.tex 改動後**尚未 xelatex 重編譯**（見禁止事項）。

---

## P1 — 投稿包強化（全 ⬜ TODO；與 gate 無關但拉高 FRL 錄取率）

### ⬜ P1-1 — Citation 清理 C-02–C-09（首要，源 `review_history/v2/citation_check_report.md`）

v2 的 8 個 MEDIUM citation 問題只修了 C-01；C-02–C-09 全數未動：

- ⬜ 12/VIX 過度歸功 `perchet`（main.tex:70）；`perchet` 年份/key 不符（bibitem 2015 vs key perchet2016）
- ⬜ 「consistent with CRSP to within rounding precision」無佐證（main.tex:108，建議刪）
- ⬜ `cboe2014` 白皮書不可驗證
- ⬜ `harvey2018` / `harvey2016` / `liu2019` / `fleming2001` 支撐度措辭校準
- ⬜ 全部修完跑 `/citation-verifier` 複核，目標 **0 MAJOR**

### ⬜ P1-2 — 一張主圖

- ⬜ **累積財富曲線（S0/S1/S2/S4）+ VoV regime 底色 + 2018/2020 兩次「理賠」標註** —— 讓 2/6 勝率與兩次危機一眼看懂，性價比極高（FRL 短文可無圖，但這張回本）
- ⬜ 順帶做 gold-by-regime 迷你表，收掉 v2 M-07（gold crisis-alpha claim 無表支撐）

### ⬜ P1-3 — 91% share 不確定性 + 口徑澄清

- ⬜ **91% opp share 的 stationary bootstrap 95% CI**（固定 seed）—— 直接回答 referee 必問「這 91% 有多穩」
- ⬜ 加一段 **「IP_opp 為 net-of-payout 口徑」的定義澄清**：IP_opp = r̄_BH − r̄_VT,gross 已淨掉危機期 VT 少虧的「保險理賠」，不是純放棄的上漲；並說明這使 91% 是偏保守還是偏高估計
- ⬜ （選配）主動揭露 S2 在啟動 regime（HighVoV_Rising）內 total cost 6.85% > S1 5.54% —— 不推翻結論但防 referee

---

## P2 — 投稿與後續

- ⬜ **FRL `journal-review` skill 跑 profile gate**：字數上限 / 格式 / highlights / 合規（author = Yi-Hao Lai only；無 volpred / AI / LLM 字樣）。P0 三項完成前不得標 ready 已達成，P1 完成後預估達投稿水準。
- ⬜ **與 vt-crowding-abm（P5）錯開投稿時序**：同作者短期對 FRL 投兩篇 VT 主題 desk 端觀感有風險 → **P4（本篇）先投，P5 等 P4 有 first decision 再投**；或 P5 改投 Journal of Asset Management / JPM。
- ⬜ （選配，非本篇 blocker）跨資產延伸（QQQ/EFA/EEM 的 opp/direct 比率）留作下一篇或 revision 彈藥，不進本稿。

---

## 禁止事項（本篇特有）

- ⛔ **別動 headline 54 bps**：deep review 曾建議正文 headline 由 54 bps 改成 raw-Close ~63 bps，但**主線程裁定不改** —— 54 bps 是 K846 canonical（`auto_adjust=True` Adj-Close 錨），改成 63 會與 K846 canonical 數字矛盾。gate 已用「claim #9 re-scope 成同口徑檢查」的方案解決（raw-Close 62.910 vs ~63，9/9 真 green），不需動正文 headline。54/63 雙口徑已在 main.tex:184 揭露。
- ⛔ **別 merge into vt-trend-following**：兩篇問題不同（機制辨識 vs 成本會計）、方法不同、期刊層級不同；P3 已 ready，合併雙輸（deep review §6 明確裁定）。
- ⛔ **投稿前必跑 xelatex 重編譯**：main.tex 三處改動（`b0ea148e9`）**尚未重新編譯確認**；paper-update 前先 `xelatex` 確認無誤再 `uv run volpred ops paper-update --paper-id vt-insurance-cost` 同步。
- ⛔ **不手改 JSON 湊數字**（修產生腳本，不 sed / Edit 欄位）—— 修流程不修資料。
- ⛔ **不混 vintage**：K846 錨值 54 bps（Adj-Close）與 replication raw-Close 62.910 bps 是股息口徑差異，正文兩者都要明示，勿一半新一半舊。
- ⛔ **不整檔讀** `feed.json` / `knowledge.json`（用 grep/jq/單檔）。

---

## 進度日誌

```
2026-07-11 | Fable deep review     | 深審完成 3.5/5 GO-FRL              | f913ed68c
2026-07-11 | Fable P0 finishing    | package衛生+gate 9/9 green+main.tex 3處 | 5183318c0+b0ea148e9
```

---

## 接續提示詞

讀 `paper/vt-insurance-cost/EXECUTION.md` 後，**P0 已全數完成（package 衛生 + reproduce gate 9/9 真 green + main.tex 三處，commit `5183318c0`+`b0ea148e9`）**，從 **P1-1 citation 清理** 開始：讀 `review_history/v2/citation_check_report.md` 的 C-02–C-09（perchet 過度歸功與 year/key 不符、CRSP 佐證缺失建議刪、cboe2014 不可驗證、harvey/liu/fleming 支撐度措辭），一次修完 `main.tex` bibliography 與正文引用點 → 跑 `/citation-verifier` 複核目標 0 MAJOR。接著 P1-2（累積財富 + VoV regime 底色主圖）、P1-3（91% share stationary bootstrap 95% CI 固定 seed + net-of-payout 口徑澄清段）。修訂在主線程進行（不丟 background agent 改 .tex，paper-workflow 硬規則）。**投稿前硬 gate：main.tex 改動後先 xelatex 重編譯確認**，再 `uv run volpred ops paper-update --paper-id vt-insurance-cost` 同步線上驗證。禁止事項務必遵守：別動 headline 54 bps（改 63 與 K846 canonical 矛盾，gate 已用同口徑方案解決）、別 merge 進 vt-trend-following、與 P5 錯開投稿時序（P4 先行）。
