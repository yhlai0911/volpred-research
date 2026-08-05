# EXECUTION — vix-sufficiency「Can Anything Beat VIX?」

> **BADGE**: `P0=TODO` · `P1=TODO` · `P2=TODO` — 深審完成，P0 尚未動工
> **Canonical tex**: `main_v5.tex`（1,317 行，編譯 2026-07-09）— 深審實體核對確認 canonical 已推進到 v5，非 pipeline blocker 所述 v4
> **Journal target**: Journal of Forecasting（深審建議：IJF 第一 / JoF 同級可投 / JBF 第二；FRL 短 null note 版為 plan C）
> **Verdict**: 2 / 5 — REJECT-in-current-state（可救，估 2–3 週：重算推論層 + claim 全面清洗）
> **Source review**: `review_history/fable_deep_review_20260711/README.md`（180 行）
> **Owner**: 主線程（P0 tex 修訂與方法論決策不外包 agent；P0-1 重算走 compute_queue）

---

## 0. 一句話現況

主結論「**無訊號在 beneficial 方向打敗 VIX**」大概率存活（有正確 HAC 的 k778/k799/k1116e/k1116g 全部支持 null）；擋在投稿前的是三個致命傷 —— (A) 推論層 HAC 系統性失效且論文虛稱 bandwidth、(B) 41.8% 方向翻轉、(C) K732/K736 抄錯格決議 34 個月未落地。真正有翻案風險的是 **harmful-direction 顯著性宣稱** 與 panorama 個別 cell，不是 headline。

---

## 1. P0 — 投稿 blocker（依序執行；全未動工）

### P0-1 ⬜ DM/HAC 全量重算（新 K 實驗，走 compute_queue）
論文正文白紙黑字寫「Newey-West HAC bandwidth = 22 / 4」，但 source 實作是 **0 或 4–5 lags**：k1116b（Table 2 F12/F13 + Table 9 全 16 cells）、k1203（panorama 28 cells）、k1116c（weekly CW）全為零 HAC；另有 k730/k731/k736/k747/k751 五個 degenerate 站點。這是研究誠實紅線（聲稱 ≠ 實作），referee 一跑 replication 即 desk-reject。**必須全量重算，不可只改文字。**

- [ ] 範圍：k1116b 全 16 cells（3 變體 × 4 資產）、k1203 全 28 cells、k1116c weekly CW、Table 2 daily families DM（k730 等）、Table 3 strategy DM（k731/k736/k747/k751）
- [ ] 規格：一律用 `volpred.stats.model_evaluation.dm_test` canonical bandwidth `max(h−1, ceil(h^{1/3}·n^{1/3}))`；**每個 cell 先報 loss differential acf(1)**（K1655 SOP），輸出新舊 t 對照表
- [ ] Bandwidth sensitivity：weekly n≈170 → bandwidth ≈ 6；daily n≈4600, h=22 → ≈37 vs 現行 22 的差要報 sensitivity
- [ ] 產出：`experiments/k17xx/`（新編號）+ Table 2 / Table 9 / panorama 全面換數
- **DoD**：
  - [ ] beneficial null 存活 → 寫進 paper 作 robustness 賣點「null robust to HAC bandwidth」
  - [ ] harmful-direction 宣稱（F13 −3.61、F12 raw p=0.012）與 panorama |t|>3 的 8 cells（含 TLT +3.743）依重算結果重標
  - [ ] Table 9「strengthened / threshold flip」flags 全部重寫
  - [ ] Codex primary-path 語義級複核通過（非 subagent fallback closure）

### P0-2 ⬜ Claim 清洗（主線程修 tex，一個 commit）
- [ ] **41.8% 三處方向翻轉**（intro L98 / §8.2 L1038 / conclusion L1150）：k745 `improvement_pct = −41.8`，實為 5-min HAR-RV **劣於** daily HAR-ABS 且 N=37 PRELIMINARY。改為誠實方向（5-min pilot 目前落後、frontier 是 open question 非 evidence-backed promise）或整段降級刪除
- [ ] **落地 K732/K736 2026-04-19 決議**（`decisions/k732_k736_table2_rewrite.md` 已有逐欄 spec + inline comment 模板，直接執行）：F3 現印 1.64（實為 `dm_stat_oos=1.637` 抄錯格）、F11 composite salad 值全部改為 canonical
- [ ] Table 3 ERC 列算術錯（L553 ΔSharpe −0.054 vs 0.795−0.870=−0.075，混拼兩窗數字）：用 k747 canonical 同期數字重算，ΔSharpe 對齊 benchmark 定義
- [ ] intro L88「all DM |t| < 3.0」與 Table 2 F13 印 3.61 直接矛盾 + 「max incremental R²=0.038」把 in-sample ΔR² 放進 OOS 語境 → 兩處改寫
- [ ] F12 印 2.55，corrected M3 = −2.54（Table 9 L884 自己印 −2.54）→ 對齊
- [ ] VaR 表 α=0.01 self-contradiction（L1064-1073 note 稱 AMEM 唯一雙通過，但 GJR-GARCH(t) p=0.023/0.011 在 α=0.01 也不拒絕）→ 修 note
- [ ] F2 daily CW p=0.045 被寫「far short of significance」（L519）→ 改「未達 Harvey 3.0，但傳統 5% 邊緣顯著」
- [ ] L440「numerator 12 approximates long-run average VIX」vs Table 5 全樣本 mean VIX=19.5 → 改 target-vol 誠實表述

### P0-3 ⬜ reproduce gate v5 重建
現行 `reproduce_report.json` = v3 / 2026-04-20 / 98% / green，但 gate 三重失效：(A) v4/v5 新增約佔正文 1/3 完全不在 gate 內；(B) gate 是 **JSON↔JSON**，從不解析 .tex（`errata_table3_bh_sharpe_canonical_fix.md` 已明文承認）→ tex 印 1.64 而 JSON 5.58 仍綠燈存活三版；(C) hardcode 值與已裁決 canonical 脫鉤。

- [ ] 新 `reproduce.py` 加 **LaTeX 數字 extractor**（tex↔JSON 雙向），覆蓋 v5 全部 tables（k1203/k1121/k1116b/c/e/g/k1137-43）
- [ ] gate 通過門檻：`paper_version="v5"` + match_rate ≥ 95% + alert_level=green，才准進下一輪 review
- [ ] 同 commit 修 `scripts/audit_dm_hac_lag.py` AST pattern，補 4 個逃逸變體（plain-variance `dm`/`hln` 命名、`nw_lag=0` 參數、`ttest_1samp` 冒名 DM、異名 `dm_test_func`）；enforcement owner 維持 `scripts/tests/test_dm_hac_lag_ratchet.py`（anti-stacking：不開新 gate）
- [ ] `docs/governance/2026-07/dm_hac_lag_class_sweep.md` 盲區分析補上此 6 站點的 pattern class

---

## 2. P1 — 投稿前必要（P0 後並行）

- [ ] **8 個 v4 MAJOR 逐項修**（v5 全部原地未修，深審逐項驗證仍在）：
  - [ ] Holm family 口徑統一（abstract 限定「across the 10 regression tests」，撤「all results survive HB」）
  - [ ] Harvey 3.0 措辭全文一致化為 approximate / conservative；撤 abstract「demonstrating time-invariance」
  - [ ] `k780_tail_first_es.py` Student-t quantile 做 unit-variance scaling `sqrt((df−2)/df)`（K802 class），重算 VaR/ES 表 + Basel traffic-light 正式引用 BCBS(1996) 或改稱自訂口徑
  - [ ] CRRA welfare 加 estimation uncertainty；「most retail investors」（L1122）降級
  - [ ] conclusion 撤「frontier exhausted」與 regulator 背書（L1150/1154）
  - [ ] pre-spec 段改誠實兩階段揭露（L74 safeguard(i)「13 families 全部 defined before examining OOS」與 L77「12–13 added in this revision」互斥 → 刪絕對句）
  - [ ] citation 補 Acerbi-Szekely(2014)、BCBS、CBOE VIX white paper、Carr-Wu(2009)；engle2006/bollerslev2020 補 inline cite 或移出 bib（現為 orphan）
- [ ] **圖表 ≥ 3 張**（現全文 0 圖，實證論文初審觀感差）：era R² 穩定性圖（K752）、DM/CW forest plot（重算後全 cells 一圖收斂，正好展示 null 的 across-the-board 性質）、VT drawdown insurance 圖（K738）
- [ ] **瘦身至 ≤ 40 頁**（現 61–63 頁對 JoF 太長）：§7.8 channel heterogeneity 移 online appendix；§7.10 allocation 壓縮 1 頁 + appendix
- [ ] `research_program.md` P7 列由 stale「✅ READY — GREEN 98%」降級改寫（已被 2026-06-10 MAJOR_REVISION + 2026-07-06 Codex REJECT 推翻）
- [ ] `experiments.md` 補 k1116e/g、k1203、k1121 索引

---

## 3. P2 — 投稿策略與後續

- [ ] 期刊定案：主推 **IJF**（forecast-comparison null + MCS/CW 契合度最高；Hansen-Lunde 血統）；備選 J. Forecasting；JBF 需強化經濟意義段；FRL 短 null note 為 plan C
- [ ] **F9/F10 daily CW data-provisioning followup**（論文 L519 已自我披露）：pin Google Trends、VIX open 序列後補 2 個 CW cell
- [ ] **F3 不是資料問題，是描述問題**（2026-08-05 論文部查證，取代原本併在上一項的「pin CBOE put-call」）：K732 從未使用任何 put-call 序列。產出腳本 `k732_pcr_behavioral_sentiment.py:53-58` 只下載 SPY / GLD / ^VIX / ^SKEW / ^VIX3M，BSI 是四個 VIX/SKEW 百分位的等權平均；腳本檔頭 `:11` 與 results JSON 的 `data_limitation` 欄位都明記代換。所以 pin CBOE put-call **不會**補上 F3 的 CW cell —— 那會製造一個新的 family，不是完成這一個。
  - 已修（本部門轄區內）：`data_sources.md` 虛構的 PCR 列已換成實際使用的 ^SKEW 列（並修正樣本期間：原列宣稱 1995 起，實際估計樣本是 2011-01-07 – 2026-03-20, n=3,760）；`experiments.md` K732 描述已改為 BSI 實際構成。
  - **待主線程處理（`.tex` 為保留區，本部門無寫入權）**：`main_v5.tex:519` 仍寫「Family~3 (behavioral put-call ratio)」並宣稱其 CW 因「CBOE put-call volume … not yet pinned」而 deferred —— 標籤與延後理由兩者皆不成立。§3.2.3（`:210-212`）本身是正確的，缺陷只在 L519 這一句。
  - **另一層，需方法論裁決**：BSI 四個分量有三個由 VIX 導出（VIX level、VIX/VIX3M、VIX 22 日動能），只有 SKEW 在 VIX 複合體之外。在一篇主張 VIX sufficiency 的論文裡，這使 F3 的 null（|t|=0.52）大部分是「VIX 的重組贏不了 VIX」，證據力低於標題所暗示的獨立 family。不是造假，但把它列入「thirteen pre-specified signal families」的橫向比較會被審稿人指出。
- [ ] **Cover letter 賣點**：pre-registration 誠實揭露 + publication-delay convention + Clark-West self-check + HAC-bandwidth robustness（P0-1 副產品）—— 把這輪修復寫成方法論貢獻
- [ ] 投稿前 compliance scrub（作者僅 Yi-Hao Lai、無 AI/volpred 字樣、acknowledgement 清理）走 `journal-review` skill

---

## 4. 禁止事項（本篇特有）

- **K732/K736 決議必落地，勿再拖**：正式 root-cause 文件 + canonical 決議 + execution checklist 齊備卻 34 個月零執行；再拖一版即從 process 失效升級為投稿後資料誠信事故。P0-2 內必須清帳，不可標「下版再修」。
- **DM 零 HAC 站點勿當 primary**：k1116b/k1203/k1116c 及五個 degenerate 站點在 P0-1 重算完成前，其 t 值一律只能放 diagnostic，**不得**餵任何對外結論（feed 文章、FB、cover letter）。
- **reproduce gate 只驗 JSON 不驗 LaTeX 是設計盲區**：綠燈 ≠ tex 正確（tex 印 1.64 / JSON 5.58 綠燈存活三版即為活證據）。未完成 P0-3 的 LaTeX extractor 前，不得以現行 green gate 作為「已復現」背書。
- **在 P0-1 重算完成前，disable 任何「已驗證 null」對外引用**，以免傳播可能要重標的 cell 數字（K1655 雙向原則：正自相關收縮 |t|、負自協方差反向放大 |t|，不可預設安全）。
- 不看圖下結論、不自寫 local DM/HLN 蓋掉 canonical（K1655 硬規則）。

---

## 5. Definition of Done（整體投稿門檻，全未達）

- [ ] P0-1 重算完成，論文所有 DM/CW cell 與 source JSON 逐格 traceable，bandwidth 文字與實作一致
- [ ] P0-2 claim 全面清洗，41.8% 方向與 K732/K736 決議落地，抽查零方向翻轉
- [ ] P0-3 reproduce gate v5 重建，`paper_version="v5"` + match_rate ≥ 95% + green（含 LaTeX extractor）
- [ ] P1 八 MAJOR 全清 + ≥3 圖 + ≤40 頁
- [ ] fresh paper-review-cycle 通過（Codex primary + agy 二審）
- [ ] `paper-update --paper-id vix-sufficiency` 同步平台成功
- [ ] compliance scrub 通過（作者僅 Yi-Hao Lai、無 AI/volpred 字樣）

---

## 6. 進度日誌

| 日期 | actor | 事件 | commit |
|---|---|---|---|
| 2026-07-11 | Fable deep review | 深審完成，待執行 P0 | f913ed68c |

---

## 7. 接續提示詞

讀 `paper/vix-sufficiency/review_history/fable_deep_review_20260711/README.md` §3.3 + §5 P0 後，從 **P0-1 DM/HAC 全量重算**開工：以 canonical bandwidth `max(h−1, ceil(h^{1/3}·n^{1/3}))` 開新 `experiments/k17xx/` 重跑 k1116b 全 16 cells、k1203 全 28 cells、k1116c weekly CW 及 k730/k731/k736/k747/k751 strategy DM，每 cell 先報 loss differential acf(1) 再出新舊 t 對照表（走 compute_queue）。主結論 beneficial-direction null 大概率存活（作 robustness 賣點）；翻案風險集中在 harmful-direction 顯著性與 panorama |t|>3 的 8 cells，依 K1655 雙向原則實際重算、不預設安全。P0 tex 修訂與方法論決策留主線程，重算完成後 Codex primary-path 複核才寫 knowledge。
