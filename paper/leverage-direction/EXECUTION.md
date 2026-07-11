# EXECUTION — leverage-direction

> **BADGE** · verdict `2/5`（修後 `3.5/5`）· stage `multi_round_review`（**do_not_advance=true**）· journal `IJF → EmpEcon → JoF` · **p0 = TODO** · dod `0/9`
> 依據：`review_history/fable_deep_review_20260711/README.md`（Fable 深審 2/5）· `docs/paper_portfolio_review_20260711.md` · `storage/paper_pipeline_status.json`
> 最後更新：2026-07-11（Fable deep review 完成，P0 尚未執行）

---

## 最終目標

把 leverage-direction 從「手稿宣稱的中心結論證據不在稿內、三處舊正向數字與 canonical 實驗矛盾」狀態，經 **P0（證據接線 + 矛盾修復）+ P1（gate / package 衛生）約 6–8 個工作天**，推進到 **International Journal of Forecasting（IJF）methods track 可投稿**。

**核心貢獻（保留、不稀釋）**：reproducible measurement-to-allocation evaluation framework + the honest null it yields。同窗口 / 單協議下，leverage-direction taxonomy 的實證訊號在 **pre-specified + OOS + multiple-testing 修正後為 null / weak**（K1592：0/8 assets Harvey-Holm 顯著；K1591 gold ex-ante regime bootstrap CI **[-0.71, +0.39] 跨零**）。貢獻在**方法框架與誠實 null**，不是正向發現。IJF 有 informative-null 傳統（M-competition 血統）——本篇的 measurement-to-allocation 框架 + forecast-origin decision log + frozen re-test 協定是好的 methods fit。

**期刊順序（已裁定，owner email-12500 Option A + email-12398 delegate；memory `feedback_paper_autonomy_optimize_acceptance`）**：
1. **IJF（primary）** — methods track；null + measurement-to-allocation 框架 + decision log + frozen re-test 是加分；replication package（pinned snapshot + reproduce.py）符合 IJF replication 友善傳統。錄取率如實評估屬低–中（null + 小 cross-section 是硬傷）。
2. **EmpEcon（Empirical Economics，fallback）**。
3. **JoF（Journal of Forecasting，Wiley，二次 fallback）**。

> **關鍵裁定（寫進本檔以免再被誤導）**：**stage2 core rebuild 不需要再投入 —— 它已經做完了**。K1591（gold regime）+ K1592（OOS horse race）就是 `reframing_decision_20260701.md` 的 stage2 前兩項，honest rebuild 的結果 null / weak，並**直接觸發** owner 的 Option A 降檔（email-12500）。現狀不是「缺一個重型新實驗」，而是「已完成的 null 證據沒有接進稿裡、稿裡三處舊正向數字沒有 rebind canonical」。**正確動作 = 接線 + 重建 artifact + package 衛生（~6–8 工作天，無重型新實驗）**，不是新研究。繼續往「更深的 gold regime rebuild（期貨 / 機構流量資料、更長 vintage）」投入 = 另一篇論文 scope，本輪不做（Stage 3 defer 維持）。

---

## 當前狀態

**Verdict 2 / 5（現狀不可投稿；完成 P0 + P1 後預估 3.5 / 5，IJF 值得一投、非穩上）。**

- **實驗層健全** ✅：K1591 / K1592 設計嚴謹（dev / holdout 分割、Holm 校正、canonical QLIKE / DM、forecast-origin decision log 齊全）；K1592 SPY rule-vs-GARCH **Holm p=0.104** 證明 null 對校正方式 robust（不是靠 t>3 門檻硬壓）；k903 `dm_test_hac` 用 canonical bandwidth `ceil(h^{1/3}·n^{1/3})`，**不在** 2026-07-11 DM-HAC 凍結 backlog（133 站點無本論文腳本）。**該做的重實驗已經做完了。**
- **手稿層不健全** ❌：中心 null 的證據（K1592 0/8 Holm、K1591 CI 跨零）做完卻**一個數字都沒進稿**；三處殘留舊正向宣稱與 canonical 實驗矛盾——(a) HM high-VIX `t=-4.63` 被 K1256 canonical 推翻為 `t=-0.79`（NS）；(b) §5.4 只報**內生** bull/bear `t=-3.79` 而隱去 K1591 ex-ante 弱結果；(c) abstract 的 26-asset / 14-asset 延伸**在全 package 找不到 artifact** 卻自稱 primary basis。cover letter 還是舊標題 + 正向宣稱、與 null 稿直接矛盾。全是 referee 一眼可見、無需重跑即可抓到。
- **Pipeline**：stage=`multi_round_review`、`do_not_advance=true`（2026-07-02 IJF fresh multi-round review = FAIL_DO_NOT_ADVANCE）。canonical = `main_v_ijf.tex` + `body_v_ijf.tex`（7/8 13:16）+ `tables_main.tex`（6 表），編譯 35–36pp、0 undefined refs。
- **Reproduce gate**：171/171 traceable MATCH，但**只 gate table sources**，不 gate `body_v_ijf` prose / tab:vt / 6-of-6 OOS / ρ=0.83 N=14 → **GREEN 燈與 prose 錯誤並存**（F3 的 HM 錯誤數字被列 NOTE tier，照樣亮綠）。
- **LATENT 風險**：JBF-era `main.tex` / `body.tex`（正向宣稱版）未封存，`papers.py:250-263` 候選清單看不到 `*_v_ijf.tex` → 誤跑 `paper-update --paper-id leverage-direction` 會發佈 stale 正向版。
- **未關閉的最大實證風險**：null 論文最大攻擊面是 **power**，現稿只對 N=6 classification 認了 underpowered，**DM null 本身沒有 MDE / power 陳述**（873 OOS 天、|t|>3+Holm 門檻下，多大的 QLIKE 差才偵測得到？）。

---

## 完成定義（DoD）— 全部未達成

- [ ] **P0-1** 落地：新增「Pre-Specified Out-of-Sample Re-Test」小節裝 K1592（8 資產 × {rule-vs-GARCH, rule-vs-GJR} DM t / Holm p / GJR share / MCS survivors，dev vs holdout panel 分列）；methodology 補出**精確** multiple-testing 程序；§5.2 每個 null 句子都指得到稿內表格
- [ ] **P0-2** 落地：§5.4 gold regime 改雙軌（內生 bull/bear `t=-3.79` 降為 descriptive + ex-ante holdout CI `[-0.71, +0.39]` 跨零）；正文無未伴隨 K1591 counter-evidence 的「gold regime p<0.001」宣稱
- [ ] **P0-3** 落地：HM high-VIX `-0.068/t=-4.63` → K1256 canonical `-0.030/t=-0.79`（NS）；`p>0.70` → canonical `p=0.31`；句子改「remains negative but insignificant」
- [ ] **P0-4** 落地：26 / 14-asset 延伸宣稱處置（找回 source / 重建新 K / 裁到可證範圍三選一）；abstract 每個量化延伸宣稱稿內或 supplement 有對應 artifact
- [ ] **P1** 落地：reproduce gate 升級 gate `body_v_ijf` prose literals + package docs 全面 IJF 化 + supplement 重建 + 一致性小修（cover_letter / title_page / tab:desc / Data section / DM lag prose）+ Power/MDE 段
- [ ] `reproduce.py` exit 0 且 `reproduce_report.json` match_rate ≥ 95% / **alert green**（新 check family gate `body_v_ijf` prose，MISMATCH 級非 NOTE 級）
- [ ] fresh IJF multi-round review 收斂（`latex-academic-reviewer` + `citation-verifier` + `journal-review`，Codex primary path，7/11 額度恢復後）—— 無 FAIL_DO_NOT_ADVANCE
- [ ] `journal-review` compliance gate 通過（author = Yi-Hao Lai only；無 volpred / AI / LLM 字樣）
- [ ] `uv run volpred ops paper-update --paper-id leverage-direction` 同步 + 線上驗證（先確認 canonical 指向 `*_v_ijf.tex`，非 stale JBF 版）

---

## P0 — 投稿前必做（估 ~4 天；全部 ⬜ TODO；先於任何新 review round）

### ⬜ P0-1 — K1592 進稿 + multiple-testing 程序指定（純手稿 + 新表，估 1.5–2 天主線程）

現稿 headline 是「pre-specified multiple-testing-controlled evaluation」，但正文**沒有寫出 multiple-testing 程序、也沒有放 frozen test 的任何數字**（F1，自我矛盾）。新增「Pre-Specified Out-of-Sample Re-Test」小節（§5.x）把中心 null 的證據接進 `body_v_ijf.tex`：

- ⬜ **新表**：8 資產 × {rule-vs-GARCH, rule-vs-GJR} 的 DM t / Holm p / GJR share / MCS survivors，dev={SPY, QQQ, EEM, GLD, TLT} 與 holdout={IWM, SLV, BTC} panel **分列**（來源 `experiments/k1592/k1592_results.json`）
- ⬜ **methodology 補精確程序**：frozen rule 定義（γ>0 & t>1.65 → GJR、window 504、refit 21d）、判準（**|t|>3 + Holm p<0.05**）、family 大小、monthly refit、date-clustered panel（K1355-compliant）、decision log 檔名 `k1592_forecast_origin_decision_log.csv`
- ⬜ **關鍵數字**：SPY rule-vs-GARCH `t=-2.85`、unadjusted `p=0.0045`、**Holm p=0.104** → 「no asset shows significant OOS superiority」對校正方式 robust（0/8 assets Harvey-Holm 顯著；MCS holdout panel 保留全部三個模型）
- ⬜ `k1592_forecast_origin_decision_log.csv` 列入 replication package（恰是 7/1 Codex contribution gate 點名要的 decision log）
- ⬜ 補一段 **design-provenance**（何時凍結、凍結什麼、decision log 指引）——回應 referee 必問的「pre-specified 是什麼時點、凍結了什麼」

**成功標準**：§5.2 的每個 null 句子都指得到稿內表格；methodology 寫得出**具體**哪種校正（Holm / family 大小），不再只寫「Harvey-style multiple-testing correction」。
**驗證 gate**：xelatex 重編譯無誤 + `reproduce.py` gate 新表數字（MISMATCH 級）+ §5.2 無「無稿內表格支撐」的 null 宣稱。
（對應 experiment：`experiments/k1592/`；main-thread verification = PASS research-honesty，verdict NULL_OR_WEAK）

### ⬜ P0-2 — K1591 進稿 + gold regime 雙軌降級（估 0.5–1 天）

§5.4 目前只引用**內生** bull/bear 分解（`bull γ=-0.043 vs bear γ=+0.048, t=-3.79, p<0.001`），regime 由金價自身方向事後定義（ex-post，正是 7/1 Codex 批評點）。改為雙軌報告：

- ⬜ 內生 bull/bear 分解降級為 **descriptive / suggestive**（明標 ex-post regime）
- ⬜ 加入 **ex-ante 外生 regime**（lagged VIX≥20 + DXY trend + Treasury basis；train ≤2018 / holdout 2019–2026）的 holdout 結果：safe-haven `γ_diff=-0.087`（HAC `t=-0.66`）、block-bootstrap **95% CI [-0.71, +0.39] 跨零**、僅 69.8% draws 為負 → 如實標 **directionally supportive, not significant**（來源 `experiments/k1591/README.md`）
- ⬜ gold regime 敘事強度整體下修一級；`reframe axis` 註解（`body_v_ijf.tex:21-22` 宣稱 grounded in K1591）與正文對齊

**成功標準**：正文不再有任何「gold regime p<0.001」等級宣稱未伴隨 K1591 counter-evidence（避免「自己的 frozen re-test 推翻自己引用的顯著性卻只報有利版本」= 研究誠實層級問題）。

### ⬜ P0-3 — HM high-VIX 數字 rebind K1256 canonical（估 0.5 天）

- ⬜ `body_v_ijf.tex:307` 的 `γ_HM=-0.068 / t=-4.63`（宣稱 significantly negative）→ K1256 canonical `pure_vt_high_vix` 的 **`-0.030 / t=-0.79 / p=0.43`（不顯著）**（來源 `experiments/k1256/k1256_results.json`，verdict DIVERGENT_SAME_SIGN）
- ⬜ 改寫該句為「conditional on high-VIX episodes the point estimate remains negative but insignificant」
- ⬜ 同段「unanimously fail to reject ... (p>0.70)」→ K1256 canonical（`pure_vt_full p=0.31`）

**成功標準**：timing-null 結論不變（反而更乾淨）；正文無與 `k1256_results.json` 矛盾的數字；reproduce.py 把此格由 NOTE tier 升為 MISMATCH-gated。

### ⬜ P0-4 — 26 / 14-asset 延伸宣稱處置（估 0.5–1.5 天）

Abstract（`main_v_ijf.tex:80-81`）+ 正文（`body_v_ijf.tex:170, 299`）宣稱延伸到 26 資產、14-asset 樣本「reported in the Online Supplement, which we treat as the **primary basis for inference**」——查證：`supplementary_content.tex` 無 14-asset 內容、repo 無 26/14-asset result JSON、`reproduce.py:16` 自記 no JSON source。**論文自宣的 primary inferential basis 在 package 中不存在**（F4）。三選一：

- ⬜ (i) grep `knowledge.json` / 舊 K 找回 JBF-era 14-asset MDD-vol correlation 的 source 實驗
- ⬜ (ii) 找不到就用 yfinance 重建 14+ 資產 VT panel 為新 K（pin snapshot、進 supplement + reproduce gate）
- ⬜ (iii) 或直接把 abstract / intro 的延伸宣稱**裁到現有可證範圍**（K1592 的 8 資產 + tab:vt 的 5 資產）

**kill 標準**：若 (ii) 重建後 ρ 顯著變弱（如 CI 含 0），依研究誠實原則改寫 allocation 結論並降 tier 投稿。
**驗證 gate**：abstract 每個量化延伸宣稱稿內 / supplement 有對應 artifact + reproduce binding。

---

## P1 — 投稿包強化（與 P0 平行可做，估 ~3 天；非 gate blocker 但投稿前必達）

- **reproduce.py 升級 gate `body_v_ijf`**（1 天）：新 check family 綁 `body_v_ijf` prose literals（K1592 / K1591 / K1256 canonical 數字、gold anti-VT Sharpe 1.71/1.51/1.56、12/VIX 0.856 vs 0.826、EWMA COVID 1.130 vs 0.745），**MISMATCH 級而非 NOTE 級**；跑到 GREEN ≥ 95% 才准進下一輪 review（paper-workflow rule 2）。
- **Package docs 全面 IJF 化**（1 天）：`REPLICATION.md`（仍 JBF 標題 / target）、`submission_package.md`（刪 `READY_FOR_UPLOAD` + **已撤回的 t=-5.79 highlight** + 已刪的 time-zone contribution）、`experiments.md`（JBF 14-table → IJF 6-table 映射）、`experiments/k903/README.md` 補全（現全「待補充」，是 tab:desc/gamma/qlike 三張主表 canonical source）；封存 JBF-era `main.tex` / `body.tex` 到 `_archived/`（消除 paper-update stale-publish 風險，或先建 `do_not_publish` schema guard）。
- **Supplement 重建**（1 天）：刪 time-zone 章（7/1 Codex 明令拿掉）+ complexity-ceiling 舊表；加入 body 五處「Online Supplement」實際指向的內容（14-asset artifact、EWMA crisis、視窗 robustness、VaR orthogonality）；與 body 指向一一對齊（現為純文字指向，編譯不報錯但 referee 打開對不上 = 虛引）。
- **一致性小修**（0.5 天）：`cover_letter_ijf` 全文重寫（null framing + 新標題；現為 7/2 舊標題「A Cross-Asset Complexity Ceiling」+ 正向宣稱，與 null 稿直接矛盾 = desk-reject 級 F5）；`title_page` 標題同步；`tab:desc` caption「In-Sample 2017–2025」→ canonical IS=2017–2022；Data section 資料範圍改寫（描述 2005 / 2010–2026 的實際使用範圍與各結果視窗，非只宣稱 2017 起）；DM「Newey–West five lags」prose → canonical bandwidth 規則（n≈500 → 8 lags）；`tab:vt` section ref 修正（現引錯 `sec:var_compliance`）；`var_panel`「not reproducible」note 措辭。AI disclosure（`title_page_v_ijf.tex:40`）→ **email 老闆要 sign-off（policy，不自動改）**。
- **Power / MDE 段落**（0.5–1 天，小型計算非新實驗）：以 K1592 的 loss-differential SE 反推 |t|>3+Holm 下的 minimum detectable QLIKE 差，寫入 Limitations —— null 論文對 referee「你只是 power 不夠」攻擊的必要防線。

---

## 禁止事項（本篇特有）

- ⛔ **stage2 core rebuild 不再投入** — K1591 / K1592 已做完（`reframing_decision_20260701.md` stage2 前兩項），honest rebuild 結果 null / weak；剩餘是**接線非新研究**。別把本輪誤當「需要重型新實驗」。
- ⛔ **不回頭衝 JBF** — 7/1 contribution gate 已判 BORDERLINE 且 positive story 已被自家 re-test 推翻；FRL 2500 字上限會砍掉框架本身。維持 **IJF primary → EmpEcon → JoF**。
- ⛔ **不隱去 K1591 弱結果** — §5.4 必須雙軌報告 ex-ante regime holdout CI **[-0.71, +0.39] 跨零**；只報有利的內生 `t=-3.79` = 「自己的 frozen re-test 推翻自己引用的顯著性、卻只報有利版本」，傷害等同 7/1 cover-letter t=-5.79 事件（研究誠實層級）。
- ⛔ **不保留與 canonical 矛盾的舊正向數字** — HM high-VIX `t=-4.63`（K1256 canonical `t=-0.79` NS）、gold unconditional 顯著宣稱、26 / 14-asset 無 artifact 卻自稱 primary basis，三處必修（K1416 uniqueness 重驗教訓 + 研究誠實）。
- ⛔ **不誤跑 `paper-update` 發佈 stale JBF 正向版** — `main.tex` / `body.tex`（JBF-era 正向宣稱）未封存、`papers.py:250-263` 候選清單看不到 `*_v_ijf.tex`；**封存或建 `do_not_publish` guard 前不可跑 paper-update**。
- ⛔ **不做任何為把 null 翻回正結果的再挖掘** — 違反 pre-specification 紀律；K1592 的 decision log 就是防這件事。gold 深度 rebuild（期貨 / 機構資料）+ VT channel GJR-independent identification 均 **Stage 3 defer 維持**。
- ⛔ **不丟 background agent 改 `.tex`** — 論文寫作與方法論決策留主線程（paper-workflow 硬規則）。
- ⛔ **不整檔讀** `feed.json` / `knowledge.json`（用 grep / jq / 單檔）。

---

## 進度日誌

```
2026-07-11 | Fable deep review | 深審完成，待執行 P0 | f913ed68c
```

---

## 接續提示詞

讀 `paper/leverage-direction/EXECUTION.md` 後，從 **P0-1** 開始：新增「Pre-Specified Out-of-Sample Re-Test」小節，把中心 null 的證據（K1592）接進 `body_v_ijf.tex` —— **首要動作 = 建新表**（8 資產 × {rule-vs-GARCH, rule-vs-GJR} 的 DM t / Holm p / GJR share / MCS survivors，dev={SPY,QQQ,EEM,GLD,TLT} vs holdout={IWM,SLV,BTC} panel 分列）。每個數字**先讀 `experiments/k1592/k1592_results.json` 驗證再寫**（SPY rule-vs-GARCH `t=-2.85`、unadjusted `p=0.0045`、**Holm p=0.104**；0/8 assets Harvey-Holm 顯著），不臆造。同步在 methodology 補出**精確** multiple-testing 程序（frozen rule 定義、|t|>3+Holm p<0.05 判準、family 大小、monthly refit、date-clustered panel、decision log 檔名 `k1592_forecast_origin_decision_log.csv`），完整清單見上方 P0-1。落地後 xelatex 重編譯 + `reproduce.py` gate 新表 + 確認 §5.2 每個 null 句指得到稿內表格。修訂在**主線程**進行（不丟 background agent 改 `.tex`，paper-workflow 硬規則）。接著依序落地 P0-2（K1591 進稿 + gold regime 雙軌降級，讀 `experiments/k1591/README.md`）、P0-3（HM rebind K1256，讀 `experiments/k1256/k1256_results.json`）、P0-4（26/14-asset 處置）；P1 的 reproduce gate 升級與 package 衛生可與 P0 平行。**注意**：paper-update 前先確認 canonical 指向 `*_v_ijf.tex`（`main.tex`/`body.tex` 是 JBF-era 正向版，未封存前誤跑會發佈 stale 稿）。
