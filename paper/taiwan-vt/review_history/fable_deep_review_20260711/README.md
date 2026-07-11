# taiwan-vt 深度審查（Fable Deep Review）— 2026-07-11

**Reviewer**: Claude Fable 5（深度審查 subagent，user-assigned P0）
**審查對象**: `main_v3.tex`（`\input{body_v3}`）→ `main_v3.pdf`（49pp，2026-07-06 編譯）
**Target**: Pacific-Basin Finance Journal（PBFJ）｜pipeline stage = revision，`do_not_advance: true`
**方法**: body_v3.tex 全文通讀 + 關鍵數字逐一對照 experiments JSON（K892/K896/K900/K461/K558/K1175/K1302/K1302b/K1370/paper2_* provenance 實驗）+ review_history 全歷史 + reproduce_report.json + DM/HAC 凍結 backlog 比對 + 編譯 PDF 文字抽取驗證。

---

## 1. 執行摘要

**Verdict：3 / 5（Major Revision — 內容有真貢獻，但現狀不可投稿）**

三句話：
1. 論文的兩個貢獻（diversification amplification、VT 移植到台灣 + VIX-proxy 校準）方法論框架 solid、大多數表格數字已完成 canonical 化並通過 reproduce gate（96.7% traceable match、0 MISMATCH），PBFJ 適配度高。
2. 但有 **6 個 submission blocker**：TWII γ=0.272 headline 已被 provenance 實驗證偽（可復現值 0.105–0.114，且修正後「台灣槓桿效應強於美國」的跨國敘事**反轉**）；Table 2 rolling block 是已知不可復現的 N121 遺留值；兩處 mid-line `% source:` 註解**把正文整段吞進註解**導致 PDF 靜默缺文；§7 樣本窗口自相矛盾；「GARCH ceiling」全稱宣稱被自家 package 內 K852/K886 反例打臉；§3.3 仍以事實口吻陳述已承認 untraceable 的 U.S.-side SSVS 對比。
3. 好消息是：**修正後主貢獻仍然成立** — matched-sample amplification ratio ≈ 4.2–4.7×（bootstrap 90% CI [2.28, 6.58] 排除 1，K1370 已驗證），VT 表現表全部溯源 K1175/K900 精確匹配 — 所以這是「誠實修稿 + 敘事校正」問題，不是「研究垮掉」問題。

---

## 2. 現況盤點

### 2.1 版本分岔 reconcile 後的狀態（✅ 大致乾淨）

- 2026-07-05 reconcile 完成：canonical = `main_v3.tex` → `body_v3.tex`；舊單體 main.tex/body.tex 已入 `_superseded/`。pipeline blocker 欄已更新（`blocker_verified_at: 2026-07-05`）。
- **TSMC γ canonical 鏈全文一致 ✅**：Table 1（L58）、Table 2（L183）、§8.5 footnote（L490）全部 = 0.052/t=3.98（常數均值）。實測 `experiments/k892/k892_verify_tw_gamma_results.json .assets["2330.TW"].full_sample`：γ=0.052496/t=3.9800 **精確匹配**；zero-mean 敏感度 0.0593/4.25 亦與 `paper2_tsmc_gamma_zeromean_sens` 精確匹配。舊 body 的零均值 0.039/0.87 已隨 _superseded 封存，body_v3 無殘留。
- **0050.TW γ=0.097/t=3.60 全文一致 ✅**：K892 full_sample γ=0.09704/t=3.5965（n=4,219）精確匹配；abstract、Table 1/2、§3.1、§3.2、§8.5 六處皆 0.097，舊 3-way（0.087/0.097/0.124）已清。
- reproduce gate（2026-07-06）：`alert_level=green`，`gate_status=pass_with_untraceable`，155 checks：134 VERIFIED / 2 CLOSE / 9 CONFLICT_RESOLVED / **0 MISMATCH** / 5 UNTRACEABLE，traceable match 96.7%。
- 舊 README.md 的 H1/H2 blocker 描述已 **stale**（H2 2383.TW 已在 §2.1 揭露；H1 3-way 已清）— README 本身需要更新，其 status 段還停在 2026-05-23。

### 2.2 殘留的真問題（版本 reconcile 沒解決的）

γ canonical 化只完成了 **0050/TSMC 鏈**；**TWII 鏈與 Table 2 rolling block 是兩條還沒收斂的髒鏈**，加上本次審查新發現的 PDF 靜默缺文（§4 詳述）。

---

## 3. 學術深度檢視

### 3.1 Contribution 與 PBFJ 適配度（優勢面）

- **適配度高**：亞太市場 focus、retail-dominated 市場結構（>60% turnover）、TSMC 單一持股集中度、美→亞資訊傳遞，全是 PBFJ 的核心題材。兩個貢獻的「emerging-market 在地化」角度（VIXTWN 校準、無本地 IV 指數的 proxy 解法、台灣交易成本結構）比一般 US-centric VT 論文更適合 PBFJ。
- **貢獻 1（diversification amplification）**：機制（Ang-Chen 相關性不對稱）+ 量化（ratio + bootstrap CI）+ 跨 index 對照（TAIEX vs 0050）是完整的故事。K1370 已驗證：matched-sample（2008–2024）TAIEX γ=0.1139、9-stock 平均 γ=0.0242、ratio=4.70，90% CI [2.284, 6.581]，B=1,000/1,000 valid，seed 固定 ✅。CI 排除 1（有 amplification）、含 2.8（不能宣稱強於美國）— 正文已如實揭露後者 ✅。
- **貢獻 2（VT 策略評估）**：VT 表現表全部精確溯源 — Table 3 vs `k1175_results.json`（B&H 0.7989/-33.83/14.48、EWMA 0.7012/-21.17/7.42、vix_863 1.1369/-13.71/10.72 ✅）；Table 4 common-period vs `k900_taiwan_vt_performance_results.json .table_common_period`（1.1223/1.1324/1.0835/1.0182 ✅）。共同期間比較表（Table 4）的存在本身就是方法論上的加分（回應「不同期間 Sharpe 不可比」的 referee 必問題）。
- **條件槓桿延伸**：K558 驗證 sharpe_diff=0.162、Harvey t=4.7929、bootstrap n_positive=100/100、0056 robustness t=5.6664 全部精確匹配 ✅。18/18 cross-OOS 未逐項驗但實驗檔在 package 內。
- **VaR/ES 段**：`k896` 精確匹配 — GJR+Normal 1.71% trinity FAIL、Student-t/HistSim 1.03% trinity PASS、C-F 0.51% FAIL（over-conservative）、FZ scores 4.011/4.025 ✅。「唯二同時過 VaR trinity + ES」的 uniqueness 宣稱**在 4-spec population 內驗證成立** ✅，且措辭已 scoped（"the only two specifications"指向該表四個 spec）。Basel 250-day 口徑 caveat 已在 intro 揭露 ✅（符合 methodology 硬規則）。

### 3.2 Timing 假設（✅ 乾淨）

- VIX_{t-1}（美國收盤）→ 台灣下一交易日 session = **legitimate timing**（與 session-boundary 判定原則一致）：權重在台灣開盤前已確定，無 contemporaneous overlap；§4.3 並明確揭露曾犯的 same-day timing bias（Sharpe 灌水 ~1.0）與修正過程 — 這段誠實揭露是加分項。
- VT 權重 Eq (8)：`w_{t-1} · r_t` 明確 lag ✅。
- Appendix TZ 的 overnight-gap 分解正確區分「可實作 alpha」與「開盤 gap 吸收的不可交易部分」，並誠實不把 o2o alignment check 當 implementable return ✅。

### 3.3 統計嚴謹度（有缺口）

- **DM/HAC lag 未依 repo canonical 驗證**：凍結 backlog（`storage/ops/dm_hac_lag_baseline.json`，133 站點）**不含**本文引用的任何 K 實驗（k463/k972/k790v2 是台灣相關但非本文引用）— 表面乾淨。但 **audit 只掃 `experiments/**`，`paper/taiwan-vt/experiments/*.py`（17 個本地 K 腳本）是掃描盲區**。論文的三個關鍵 DM 檢定（GJR vs GARCH p=0.86、import growth p=0.043、VIX+leading combo p=0.0005）的 HAC bandwidth 實作未被 ratchet 覆蓋。h=1 QLIKE DM 若用 `lag=h-1=0` 即完全無 HAC（K1655/k621 教訓：雙向誤設，p=0.043 這種 marginal 顯著可能翻掉，p=0.86 的 null 也可能翻成顯著）。
- **Steiger Z=16.2**（VIX vs VXEEM 預測力比較）：對 daily overlapping/autocorrelated rank 序列做 dependent-correlation 檢定但無 HAC 校正 — Z 幾乎必然高估。結論方向（0.595 > 0.459，K1181 驗 ρ=0.594 ✅）大概率存活，但 Z 值本身不可信賴。
- **§4.3 "Sharpe(K·r)=Sharpe(r)" 數學宣稱不嚴謹**：在 `min(K/VIX, 1)` cap + risk-free blending 下不成立（cap 綁定時 K 改變截斷點）。且 k900 顯示 common-period 12/VIX Sharpe=1.1341 ≈ 8.63/VIX 1.1324 — §4「8.63/VIX outperforms 12/VIX」實質是 **MDD story（-13.7% vs -18.6%）不是 Sharpe story**，行文需校正。

### 3.4 Uniqueness / all-claims 盤點（K1416-class 檢查）

| 宣稱 | 位置 | 判定 |
|---|---|---|
| "the only two specifications passing both VaR trinity and ES"（Student-t/HistSim） | abstract、§7.2、§7.5 | ✅ **驗證成立**（k896，4-spec population 內，population 已明示） |
| "only one achieves out-of-sample significance: import growth"（27 指標） | §5.1 | ⚠️ **未驗證** — 27-indicator sweep 無對應 results JSON（reproduce gate untraceable gaps 明列 "Sec 6 macro correlations lack JSON"）；p=0.043 marginal + HAC lag 未驗 → fragile |
| "the only distribution to achieve a perfect 6/6 pass rate"（skewed-t） | §7.3 | ⚠️ **未驗證** — cross-asset panel 實驗未在本次抽查範圍內 trace 到 |
| "**all** volatility forecasting enhancements validated on U.S. equities fail to improve OOS QLIKE for 0050.TW" + "GARCH ceiling extends to Taiwan" | §4.2（K472 footnote） | ❌ **被自家 package 反例打臉** — `experiments.md` 明載 K852「Realized GARCH beats GJR on QLIKE」、K886「PRG_Extended DM t=5.27 Harvey PASS vs GJR」（兩者都在 `paper/taiwan-vt/experiments/` 內）。footnote 有 scope 到三種 GARCH-X regressor，但正文 "all ... including" 是開放式全稱。必須降級為「所測試的三種 daily-frequency GARCH-X regressors 皆失敗」。這正是 K1416 教訓的 all-claims 變體。 |
| U.S.-side SSVS「no exogenous variable is needed」對比 | §3.3 L258 | ❌ **audit fix 修表未修文** — tab:ssvs_pip 表注已誠實承認 U.S.-side 實驗 untraceable、"stated qualitatively ... pending"，但 L258 正文仍以「The fact that ... produces diametrically opposite conclusions ... provides statistical evidence」的事實口吻陳述無來源結果。 |

---

## 4. 風險與致命傷

### 🔴 F1（最重）：TWII γ=0.272/t=3.18 已被證偽，且修正會**反轉跨國比較敘事**

- `experiments/paper2_twii_fullsample_gamma_provenance/results.json`：1997–2026 full-sample 重估 γ=**0.1047**/t=5.312（Δγ=-0.167，tol 0.02 不匹配）；K892 corroborate：TWII full γ=**0.109**/t=5.62（n=7,044），rolling w=2000 mean=0.114、**max=0.236** — 0.272 在任何 documented spec 下都達不到。body_v3 L52-55、L151 已掛 DISPUTED PROVENANCE 註記，AWAITING OWNER SIGN-OFF。
- 出現位置：intro（L10、L14）、Table 1（L51）、Table 2（L150）、§3.2 footnote（rolling 5.0× 的分子）、conclusion（L539）。abstract 未直接引 0.272 但 "rolling-window specification yields a comparable 5.0× point estimate" 依賴它。
- **後果超出改數字**：修正後 TAIEX γ≈0.109 **低於** SPY（K892 full 0.2197 / 論文 0.211）— §3.1「TAIEX 槓桿效應 substantially exceeding the U.S. S&P 500」**方向反轉**。倖存的是 amplification 故事（0.114/0.027 ≈ 4.2×，仍高於美國 2.8× 點估計、CI 已如實含 2.8）；死掉的是「台灣 index-level 槓桿效應絕對值更強」的所有句子。rolling 5.0× ratio 同步垮（用 K892 rolling mean 0.114 / 可復現 rolling avg 0.037 ≈ 3.1×，或按 Table 2 註解試算 7.4× — 視 pairing 而定，需重算後統一）。
- conclusion L539 還有 spec 標籤錯置：「(γ = 0.272, t = 3.18, **rolling-window** specification) that is amplified approximately 4.3× ... under the **canonical full-sample** BW-robust specification」— 同一句混用兩個 spec 的數字。

### 🔴 F2：Table 2 rolling block = 已知不可復現的 N121 遺留值，且修正會翻掉 0056 敘事

- L155-181 provenance 註解自承：Hon Hai/MediaTek/Mega/0056 四列 + 9-stock/10-security rolling 平均（0.054/0.060）+ footnote rolling ratios（5.0×/4.5×）只溯源到已刪除 K530 的 knowledge entry N121，**無任何存活 JSON**；可復現重估（`experiments/paper2_taiwan_indiv_rolling_gamma`）顯示 2886 差 3 倍（0.179→0.054）、**0056 從 0.112（"second-highest"）翻成 0.310（全場最高、高於 index 0.272）**。
- §3.2「Sensitivity to 0056.TW inclusion」整段建立在「0056 second-highest、inclusion bias 是 conservative」上 — 0056=0.310 會把該段敘事翻掉（inclusion 反而大幅拉高 stock-avg、ratio 大跌）。
- 注意 caveat：可復現 per-stock 窗口**未 calendar-aligned**（2886 snapshot 到 2025-01），採納前需 aligned snapshot 重跑 — 這正是 P0-2 要做的事。
- 對照組 K1302 v2 byte-match 的對象是**舊 body.tex 的 canonical full-sample 值**（2317 0.032/1.74 等）— 那條鏈是乾淨的（γ̄=0.0273 → §3.2 的 0.027 ✅），亂的只有 rolling 顯示層。

### 🔴 F3（本次審查新發現）：兩處 mid-line `% source:` 註解把正文吞進註解，PDF 靜默缺文

- **L343（§4.3）**：`...(canonical replication; see Notes to Table~\ref{tab:vt_results}).% source: ...` 之後同一物理行還接著約 1,100 字元的**正文**：「The two strategies therefore deliver economically indistinguishable Sharpe ratios ... 20.1 percentage point reduction of maximum drawdown ... statistically significant (**bootstrap p < 0.001**) ... VT predominantly truncates the left tail ...」— 全部在 `%` 之後，**從未渲染**。已用 `pdftotext main_v3.pdf` 驗證：`economically indistinguishable`、`20.1 percentage point` 在 PDF 中 **0 hits**。
- **L387（§5.3）**：同 pattern 吞掉三樣東西：(a) honesty caveat「The substantial-outperformance claim refers to the 2018–2024 sub-period; over the longer 2016–2026 window the BCI momentum advantage is more modest (1.260 vs 1.137)」、(b) 一整個解釋 footnote、(c) 段落 punchline「The key insight is that the business cycle indicator's value lies in its directional change, not its level.」— PDF 皆 0 hits。
- 被吞文字裡引用 `\ref{sec:results}` — **該 label 全文不存在**（.aux 0 hits），證明這段文字寫完後從未以渲染狀態編譯檢查過。
- 全檔 class sweep（mid-line `%` + tail>300 字元）：**僅此兩處**；行尾 `% source` 表格註解無此問題。
- 這是「已上線 ≠ 版面合格」的論文版變體：`.tex` 有字 ≠ PDF 有字。**建議固化為 gate**：reproduce/paper-update 流程加一步 pdftotext 抽查 — 掃描 body 中 mid-line `%` 後含句號+大寫的 tail（本次的偵測 heuristic 可直接移植）。

### 🔴 F4：§7 樣本窗口自相矛盾

- §7.2（L422）：「the canonical backtest uses the full **2019–2026** out-of-sample window (n = 1,756)」；§7.5（L439）：「over the full **2008–2026** OOS period (n = 1,756)」。n=1,756 日 ≈ 7 年，只能是 2019–2026；L439 的 "2008–2026" 是錯的（k896 n_total=1756 ✅）。

### 🟠 F5：GARCH-ceiling 全稱宣稱（見 §3.4 表）— 自家反例，必須降級措辭。

### 🟠 F6：U.S.-side SSVS 對比正文未降級（見 §3.4 表）— 表注已誠實、正文還沒。

### 🟡 M 級（彙整）

| # | 問題 | 位置 |
|---|---|---|
| M1 | 4.3× 點估計無法從任一 documented pairing 精確重現：0.114/0.0273=4.18、K1370 matched=4.70、mixed=4.45。建議統一為 K1370 matched-sample pairing 並在文中給出算式 | abstract、§3.2、§8.3、conclusion |
| M2 | GJR VT Sharpe 兩值並存：1.074（Table 3，k1175 n=1,511）vs 1.084（Table 4，k900 n=1,512）；abstract 用 1.084 但 "+0.124" 差值來自 1.074−0.950。一日之差的兩個實驗並存可以，但 abstract/正文引用要選定一處並註明 | abstract、§4.2 |
| M3 | SPY γ 0.211/t=5.79 與 K892 不精確匹配（rolling last 0.2077/4.17；full 0.2197/6.94）— 屬 legacy 值，順手 canonical 化 | Table 1/2 |
| M4 | TWII "7,148 trading days" vs provenance 實驗 n_prices=7,107 — 資料描述數字待對齊 | §2.1 |
| M5 | Steiger Z=16.2 無 HAC（見 §3.3） | §2.5 |
| M6 | "Sharpe(K·r)=Sharpe(r)" 在 cap 下不成立 + 12/VIX common-period Sharpe 實際≈8.63/VIX（k900：1.1341 vs 1.1324）；「outperforms」需改寫為 risk/MDD 語言 | §4.3、§4 Fig2 段 |
| M7 | Appendix TZ 主數字（c2c Sharpe 1.915、TW+JP 2.192、五市場 t 值）在 untraceable gaps 清單（K1176 binding 未補） | Appendix |
| M8 | §5 macro 數字（import growth partial r=0.214/DM p=0.043、27 指標、BCI R²=7.1%、combo DM p=0.0005）大multiple lack JSON；K1180 只救回 BCI momentum 部分（IS 0.413 errata ✅、OOS 1.2694 ✅、t=3.74 ✅） | §5、§8.4 |
| M9 | 主 repo README.md status 段 stale（停在 2026-05-23 的 H1/H2，其實已清）；experiments.md 標示 "superseded" 對象需同步 body_v3 | package |

### DM/HAC backlog 判定

凍結 baseline 133 站點與本文引用實驗**零交集** → 論文不背 backlog 債。但 `paper/taiwan-vt/experiments/*.py` 在 `audit_dm_hac_lag.py` 掃描範圍（`experiments/**`）之外 — **盲區**，P1-6 補掃。

---

## 5. 接下來的研究計畫

### P0 — Submission blockers（預估 1–2 週，全部主線程論文修訂流程）

1. **TWII γ decision package → owner sign-off**（F1）：整理 0.272 vs 0.105/0.109 證據包（已齊：provenance 實驗 + K892），提請 owner 核准 headline 替換。核准後全文替換（intro×2、Table 1/2、§3.2 footnote、conclusion），**跨國比較句全部重寫**（TAIEX 絕對 γ 低於 SPY；保留 amplification ratio 4.2×>2.8× 點估計 + CI 含 2.8 的誠實揭露）；rolling 5.0× 句用重算值或直接刪除 rolling variant。
2. **Table 2 rolling block 重建**（F2）：`paper2_taiwan_indiv_rolling_gamma` 以 **calendar-aligned snapshots 重跑**（現有結果 2886 端點 2025-01 未對齊，是採納前置條件）→ Codex review → 替換 N121 四列 + 平均列 + footnote ratios → **0056 段落敘事重寫**（0.310 = 最高，「conservative bias」論證翻掉）。
3. **修 L343/L387 comment swallow**（F3）：prose 移出註解（`% source` 換行放行尾）、`\ref{sec:results}` 改指 §4.1 或刪除、xelatex 後 pdftotext 驗證「economically indistinguishable」「The key insight」出現在 PDF。
4. **§7 窗口矛盾**（F4）：L439 "2008–2026" → "2019–2026"。
5. **措辭降級兩處**（F5/F6）：§4.2 "all ... enhancements" → 明示三種 GARCH-X regressor scope（並考慮把 K852/K886 的 intraday-RV 例外寫進 footnote，反而強化「cross-market channel 才是台灣的增量資訊來源」論點）；§3.3 L258 U.S. SSVS 對比降為 qualitative + 標 pending。
6. P0 收尾：xelatex → `reproduce.py` 重跑（目標 0 MISMATCH 維持）→ `uv run volpred ops paper-update --paper-id taiwan-vt`。

### P1 — 統計加固（2–4 週，可與 P0 平行派工）

7. **DM/HAC lag 盲區補掃**：`audit_dm_hac_lag.py` 擴 `paper/*/experiments/**`；重驗三個 DM claim（p=0.86 / p=0.043 / p=0.0005）— 先量 loss differential acf 再判方向（k621 教訓：null 也可能翻顯著）。
8. **§5 macro 補實驗**：27-indicator sweep 落地成 results JSON（或把 §5.1/§5.2 未溯源數字降級為 qualitative）；import growth p=0.043 用 canonical bandwidth 重跑後決定去留。
9. **Appendix TZ 補 K1176 binding**（c2c Sharpe 表全列）。
10. **4.3× 統一**（M1）+ GJR VT 1.074/1.084 統一（M2）+ SPY row canonical 化（M3）+ TWII 天數（M4）。
11. **Steiger Z HAC 敏感度**（M5）+ §4.3 K-invariance 句改寫（M6）。
12. **skewed-t 6/6 與 cross-asset panel 溯源**（§3.4 未驗證項）。

### P2 — PBFJ 投稿準備（P0+P1 綠後）

13. `reproduce.py` rebind body_v3（pipeline 已立案 followup）+ README.md/experiments.md 去 stale。
14. 完整 `paper-review-cycle` round（latex-academic-reviewer + citation-verifier，經 codex exec）→ review_history/v3。
15. `journal-review` PBFJ profile：format check、highlights、cover letter、compliance scrub（author=Yi-Hao Lai only、無 volpred/AI 提及）。
16. **時程**：P0（1–2 週）→ P1 平行收斂（+2 週）→ review cycle 1–2 輪（+1–2 週）→ PBFJ 投稿。合理目標 **2026-08 中下旬**。
17. **流程固化**（PDCA）：(a) mid-line comment swallow 偵測併入 reproduce gate；(b) `audit_dm_hac_lag.py` 掃描範圍擴 paper/*/experiments（class-level 修，其他論文同受益）。

---

## 6. Go / No-Go 建議

**現狀：No-Go。P0 六項清完 + 一輪 review cycle 後：Conditional Go。**

理由：
- **No-Go 的硬理由**：F1 的 0.272 是 DISPUTED 且已有壓倒性反證 — 帶著它投稿違反研究誠實原則第 1 條，且 PBFJ referee 只要重估一次 TWII GJR 就會抓到（這是任何 referee 都會做的 Table 1 複核）；F2 的 Table 2 rolling block 同理；F3 意味著現行 PDF 連作者意圖的內容都不完整。
- **Conditional Go 的信心來源**：貢獻核心（amplification CI、VT 表現表、VaR/ES、條件槓桿）已全部通過逐數字驗證；修正是敘事校正而非結果崩塌；PBFJ 適配度真實存在。修正後這是一篇誠實、可復現、題材對口的 solid paper。
- **最大殘餘風險**：owner 若不核准 0.272 替換（或拖延），論文卡死 — F1 沒有繞過路徑，所有下游修訂都依賴它先落地。建議 decision email 直接給兩個選項：(a) 換 canonical 0.105/0.109 + 敘事反轉重寫（推薦）；(b) 找回 0.272 的原始估計環境並補 JSON（成本高、大概率失敗 — K892 rolling max 僅 0.236）。

---

## 附：本次驗證的數字對照表（全部實際讀自檔案）

| 論文數字 | 來源檔 | 驗證結果 |
|---|---|---|
| 0050.TW γ=0.097/t=3.60 | k892 .assets["0050.TW"].full_sample = 0.09704/3.5965 | ✅ |
| TSMC γ=0.052/t=3.98 | k892 .assets["2330.TW"].full_sample = 0.052496/3.980 | ✅ |
| TSMC zero-mean 0.059/4.25 | paper2_tsmc_gamma_zeromean_sens = 0.05930/4.2469 | ✅ |
| TWII γ=0.272/t=3.18 | provenance 重估 0.1047/5.312；K892 full 0.109/5.617、rolling mean 0.114/max 0.236 | ❌ 證偽 |
| TAIEX γ 0.114（§3.2） | K1370 matched-sample TAIEX_gamma=0.11392 | ✅ |
| 9-stock γ̄=0.027 | K1302+K1302b（k1302b 內 9-stock 合併值 0.027274） | ✅ |
| 90% CI [2.28, 6.58]、median 3.78、B=1000 | k1370 .amplification_ratio | ✅ |
| Table 3：B&H 0.799/-33.8/14.48；EWMA 0.701/-21.2/7.42；vix_863 1.137/-13.71/10.72/102% | k1175_results.json | ✅ |
| Table 4：1.122/1.018/0.950*/1.084/1.132 | k900 table_common_period（*GARCH 引 k1175） | ✅ |
| VaR 1%：Normal 1.71% FAIL／Student-t 1.03% PASS／HistSim 1.03% PASS／C-F 0.51% FAIL；FZ 4.011/4.025 | k896 results."1%" | ✅ |
| SSVS PIP：SPY 1.000／AR 0.9994／mom 0.937／ΔVIX 0.881／VIX 0.801 | k461 .variable_groups | ✅ |
| 條件槓桿 +0.162／t=4.79／bootstrap 100%／0056 t=5.67 | k558（0.162/4.7929/100/5.6664） | ✅ |
| K1180 BCI：IS 0.413 errata、OOS 1.2694、t=3.74 | experiments.md K1180 行 | ✅（間接） |
| SPY γ=0.211/t=5.79 | K892 rolling 0.2077/4.17、full 0.2197/6.94 | ⚠️ 不精確匹配 |
| §5 macro（p=0.043 等）、Appendix TZ（1.915 等）、skewed-t 6/6 | 無 JSON / 未 trace | ⚠️ 未驗證 |

⏱ 審查時段：2026-07-11 22:28–22:47（台灣時間）
