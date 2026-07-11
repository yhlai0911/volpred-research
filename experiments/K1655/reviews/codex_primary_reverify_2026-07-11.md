# K1655 — Codex primary-path re-verify (2026-07-11, hourly-16)

Task: `k1655_codex_primary_reverify`  |  Reviewer: Codex CLI 0.144.1 / gpt-5.6-sol (ultra)
Prior review: code-reviewer subagent FALLBACK (2026-07-09, Codex quota exhausted) → verdict PASS, no corrections.
**Primary-path verdict: FAIL.** The fallback PASS was wrong. This is exactly the K1259 lesson.

```
VERDICT: FAIL

原始 JSON 的算術一致、forward-label embargo 也正確；但 NFCI 並非真正 point-in-time vintage，且 DM/HAC 推論不足以支撐部分核心顯著性。因此 `CONDITIONAL_PASS` 不應 finalize。

CRITICAL ISSUES:

1. [K1655.py:120–182](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:120)、[K1655.py:271–285](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:271) — NFCI 有實質 lookahead，並非 README 宣稱的真 PIT。

   程式下載的是 `fredgraph.csv` 的今日修訂後完整歷史，再人為替每筆歷史值指定 `obs_date + 3 BDay`。但 NFCI 到 2011 年才公開推出，ALFRED 的首個可稽核 release 是 2011-05-25；OOS 卻從 2004–05 開始：

   - H=1：343/1,131 origins 早於首個 ALFRED release。
   - H=4：340/1,125。
   - H=12：332/1,109。

   更嚴重的是，Chicago Fed 明確說明 NFCI 歷史值會隨新資料與模型重估而修訂；因此 2011 年後的 origins 也使用了當時未知的最終 vintage。這直接否定 [README.md:91–104](/Users/yhlai0911/volpred-research/experiments/K1655/README.md:91) 的「rigorous PIT」主張。[Chicago Fed 2011 introduction](https://www.chicagofed.org/utilities/newsroom/news-releases/2011/04-05-nfci-release)、[ALFRED NFCI release history](https://alfred.stlouisfed.org/series?seid=NFCI)、[Chicago Fed revision explanation](https://www.chicagofed.org/publications/blogs/chicago-fed-insights/2020/nfci-revisions)。

   Suggested fix：用 ALFRED 每個 forecast origin 當時有效的完整 vintage 重建特徵；禁止在指數公開前評分，然後重跑全部結果。若不做，只能改稱「final-vintage pseudo-OOS」，撤回 real-time predictive claim。

2. [K1655.py:202–229](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:202)、[K1655.py:439–459](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:439) — HLN 公式與 H−1 lag 寫對了，但對實際 loss differential 的 HAC 不足。

   正確部分：`h=H`、NW lag=`H−1`、HLN factor 均正確；`d=loss_cond-loss_uncond`，所以負 t 表示 conditional 較佳。

   問題是實際 loss differential 的序列相關遠超 H−1：

   - NFCI vol、H1、τ=.95：lag-1 ACF=0.677，但主檢定 lag=0；t 從 −4.22 降至 helper 的 −1.71，Harvey 與一般 5% 顯著性都消失（[results:1735–1740](/Users/yhlai0911/volpred-research/experiments/K1655/K1655_results.json:1735)）。
   - VIX vol、H4、τ=.95：主 t=−3.31，helper t=−2.52，Harvey 結論消失（[results:2428–2433](/Users/yhlai0911/volpred-research/experiments/K1655/K1655_results.json:2428)）。
   - NFCI return、H1、τ=.05：主 t=−2.74，helper t=−2.09（[results:447–452](/Users/yhlai0911/volpred-research/experiments/K1655/K1655_results.json:447)）。

   此外 conditional model 與 unconditional benchmark 是 nested、recursive estimated forecasts；HLN correction 本身沒有處理 nested-model／parameter-estimation 的非標準推論。

   Suggested fix：HAC bandwidth 採 `max(H−1, data-driven bandwidth)` 並報完整 sensitivity；主推論改用 recursive block bootstrap 或 quantile forecast-encompassing／Giacomini–White 類檢定。

3. [K1655.py:607–622](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:607)、[README.md:147–149](/Users/yhlai0911/volpred-research/experiments/K1655/README.md:147) — 「VIX dominates/subsumes/absorbs NFCI」沒有被實驗設計檢定。

   程式只各自比較 NFCI-only、VIX-only 與 unconditional benchmark。VIX 的點估 pinball loss 在三個 H 都較低，但沒有：

   - NFCI vs VIX 的 paired loss DM；
   - VIX+NFCI vs VIX-only 的 incremental/encompassing test。

   因此「VIX subsumes NFCI」及「confirms K503/K828」超過證據範圍，且是 README verdict 的核心敘事。

   Suggested fix：在完全相同 origins 上直接比較兩組 pointwise losses，並新增 VIX-only 對 VIX+NFCI 的 OOS quantile encompassing test。

4. [K1655.py:232–254](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:232)、[K1655.py:328–345](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:328) — 「in-sample 三個 horizon 都顯著」的 bootstrap leg 不夠穩健。

   `block=H` 只處理機械重疊；H=1 直接退化成 iid pairs bootstrap，未涵蓋 NFCI persistence／危機 clustering。`boot_p` 其實是 `2Φ(-|coef/bootstrap_sd|)`，不是 bootstrap-null p-value。Block-length sensitivity 中，H4 p 可升至 .056，H12 的 95% percentile CI 可包含 0。

   Suggested fix：用資料驅動 block length、報多組 block sensitivity，並採 recentered/studentized bootstrap p-value。

MINOR ISSUES:

1. [K1655.py:459](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:459)、[K1655.py:564–570](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:564)：`abs(t)>3` 會把顯著較差的正 t 也標為 Harvey，且 verdict 可把不同 H 的 nominal win 與 adverse Harvey cell 拼成 `PASS`。應要求同一 cell 的 `t < -3`。目前 26 個 Harvey flags 都是負 t，所以未改變這次 JSON。

2. `|t|>3` 符合 repo heuristic，但不是正式 multiplicity correction。本次有 60 個 OOS DM tests；Bonferroni 5% 臨界約為 |t|>3.35。應明定 confirmatory family：primary NFCI return τ=.05 只有三個 H，其他 57 cells 屬 exploratory。

3. [K1655.py:79](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:79)、[K1655.py:194–199](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:194)、[K1655.py:248–252](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:248)：全域忽略 warnings 並吞掉 exceptions。完整重跑發現：

   - bootstrap：11/30,000 fits 達 2,000 iteration cap；
   - OOS：2/16,860 refits 達 cap，包括 primary NFCI-return H4 τ=.05；
   - thrown exceptions=0。

   這與 [README.md:183–186](/Users/yhlai0911/volpred-research/experiments/K1655/README.md:183)「primary return fits 未觀察到」矛盾。提高 `max_iter` 後目前 aggregate 幾乎不變，但程式應儲存 convergence diagnostics 並 fail/retry。

4. Separate quantile fits 沒有 non-crossing constraint。OOS 重跑發現 NFCI-return H12 有 7/1,109 origins 出現 q.05>q.25；NFCI-vol H12 更有 65/1,109。對「完整 conditional distribution」主張應做 rearrangement 或 joint quantile estimation。

5. [K1655.py:139–150](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:139) 實際使用 `^GSPC`，不是 SPY。這是 S&P 500 price index，不含 SPY total return；README 的「SPY／tradeable」措辭不準確。

6. [K1655.py:265–269](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:265)：原始價格只到 2026-06-30，但 resample 把未完成 bin 標成 2026-07-03；每個 H 都有一個被評分 target 結束於這個 partial week。

7. [K1655.py:451](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:451) 的 reduction 無零／近零 denominator guard。當前最小 benchmark loss=0.0025724，因此本次未受影響。

8. [K1655.py:592–597](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:592) 刪除了 origins、realized、forecasts、pointwise losses；JSON 因而無法獨立重算 breach、DM 或 calibration。應另存 forecast-level artifact。

FULL-POPULATION AUDIT:

- 完整讀取 709 行 Python、201 行 README、2,534 行 JSON。
- 掃描全部 60 個 in-sample cells 與 60 個 OOS cells：
  `2 targets × 2 specs × 3 H × 5 τ`。
- 所有值 finite；無 missing cells。
- IS n 全數為 H1=1,382、H4=1,379、H12=1,371。
- OOS n 全數為 H1=1,131、H4=1,125、H12=1,109。
- 60/60 reductions 重算完全一致；60/60 DM signs、`cond_better`、NW lag、Harvey flags 一致。
- 51/60 reductions 為正，35/60 raw p<.05，26/60 Harvey-significant。
- Primary NFCI-return τ=.05：只有 H1 nominally significant，0/3 Harvey。
- 兩個 specs 的 return τ=.05 六列中，VIX-H1 是唯一 Harvey cell；此 uniqueness framing在該明確範圍內成立。
- 完整 replay：30,000 bootstrap fits、16,860 OOS refits、67,300 pointwise loss differentials。
- Blind spots：未以真 ALFRED vintages 重跑，因此 revision bias 的方向與幅度未知；未做正式 NFCI-vs-VIX paired test；圖中「2008/2020 precisely」屬視覺敘事，JSON 不足以正式檢驗。
- Forward timing 本身通過：
  - [K1655.py:288–301](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:288)：return 與 RV labels 都恰好結束於 j+H。
  - [K1655.py:385–400](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:385)：最大 train row 是 i−H−1，其 label 結束於 i−1；scoring row i 不會進 training。
  - [K1655.py:404–425](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:404)：benchmark 使用同一 embargoed `ytr`；cache 最多 stale 三週，不含 future data。
  - X 沒有 centered rolling。VIX_F 在「Friday close 後發布 forecast」假設下 timing 合法；NFCI 的缺陷是 vintage/backcast，不是 j/H indexing。

CLAIM CHECK:

1. [README.md:3–7](/Users/yhlai0911/volpred-research/experiments/K1655/README.md:3) `CONDITIONAL_PASS` → **JSON 有支援，但研究結論不應 finalize**。JSON 確實寫入 `CONDITIONAL_PASS`（[results:2521](/Users/yhlai0911/volpred-research/experiments/K1655/K1655_results.json:2521)），但 PIT 與推論缺陷使 verdict 無效。

2. 「n=1,383；OOS ≈1,110–1,131」→ **大致支援**。正確範圍是 1,109–1,131，不是 1,110–1,131；資產應稱 `^GSPC`，不是 SPY。

3. 「NFCI in-sample GaR fan、τ=.05 三個 H 都顯著，median 不顯著」→ **依 committed numbers 支援，但不穩健**：

   - H1 slope −0.021918，p=.013832；
   - H4 −0.066049，p=.034591；
   - H12 −0.147197，p=.022868；
   - median p=.2155、.7863、.7064。

   三組 slope 都隨 τ 單調上升；但 bootstrap 設計不足以支持「cleanly confirmed」。

4. 「NFCI return-tail 只有 H1 nominal edge、全部不過 Harvey」→ **支援**：

   - H1 +6.739%，t=−2.740，p=.00624；
   - H4 +3.515%，t=−.874，p=.382；
   - H12 −3.323%，t=+.739，p=.460；
   - Harvey 0/3。

   「vanishes at 4w」若指統計顯著性成立；若指 point improvement 為零則不成立。

5. 「VIX return H1 通過 Harvey」→ **支援**：+12.456%，t=−3.622，p=.000306。H4 仍有 +7.427%、p=.021，但不過 Harvey；H12 +0.331%、p=.937。

6. 「VIX dominates/subsumes NFCI」→ **點估描述支援、推論主張不支援**。三個 H 的 VIX loss 都較低，但沒有直接或 incremental test。

7. 「conditional 5% quantile breach 4.2%，calibration good」→ **4.2% 數字重算正確，但 JSON 不支援完整主張**：47/1,125=4.1778%。JSON 沒存 count、forecast path 或正式 coverage/independence test；「good」與「precisely in 2008/2020」超出 artifact。

8. Vol-at-Risk 表四列 → **數字支援，但顯著性敘事過強**：

   - NFCI H1 +25.420%，t=−4.222；helper t=−1.707。
   - NFCI H4 +20.539%，t=−2.334；helper t=−1.637。
   - VIX H1 +51.394%，t=−7.253；helper t=−3.360。
   - VIX H4 +36.987%，t=−3.314；helper t=−2.517。

   README 漏報 H12：NFCI +1.951%、p=.813；VIX +21.486%、p=.05184。

9. 「full grid is reported」→ **只對 JSON 成立**。JSON 有完整 120 cells；README 只顯示 25 個選定 cells，且漏掉兩個 H12 vol-tail rows。

10. 「iteration-limit issue negligible、primary return fits 未受影響」→ **部分不支援／部分錯誤**。Higher-iteration sensitivity 顯示 aggregate 影響很小，但 primary NFCI-return H4 OOS 與 primary-return bootstrap 確實出現 iteration cap，且 artifact 沒有儲存診斷。

全程唯讀；未修改任何檔案。
tokens used
240,120
VERDICT: FAIL

原始 JSON 的算術一致、forward-label embargo 也正確；但 NFCI 並非真正 point-in-time vintage，且 DM/HAC 推論不足以支撐部分核心顯著性。因此 `CONDITIONAL_PASS` 不應 finalize。

CRITICAL ISSUES:

1. [K1655.py:120–182](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:120)、[K1655.py:271–285](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:271) — NFCI 有實質 lookahead，並非 README 宣稱的真 PIT。

   程式下載的是 `fredgraph.csv` 的今日修訂後完整歷史，再人為替每筆歷史值指定 `obs_date + 3 BDay`。但 NFCI 到 2011 年才公開推出，ALFRED 的首個可稽核 release 是 2011-05-25；OOS 卻從 2004–05 開始：

   - H=1：343/1,131 origins 早於首個 ALFRED release。
   - H=4：340/1,125。
   - H=12：332/1,109。

   更嚴重的是，Chicago Fed 明確說明 NFCI 歷史值會隨新資料與模型重估而修訂；因此 2011 年後的 origins 也使用了當時未知的最終 vintage。這直接否定 [README.md:91–104](/Users/yhlai0911/volpred-research/experiments/K1655/README.md:91) 的「rigorous PIT」主張。[Chicago Fed 2011 introduction](https://www.chicagofed.org/utilities/newsroom/news-releases/2011/04-05-nfci-release)、[ALFRED NFCI release history](https://alfred.stlouisfed.org/series?seid=NFCI)、[Chicago Fed revision explanation](https://www.chicagofed.org/publications/blogs/chicago-fed-insights/2020/nfci-revisions)。

   Suggested fix：用 ALFRED 每個 forecast origin 當時有效的完整 vintage 重建特徵；禁止在指數公開前評分，然後重跑全部結果。若不做，只能改稱「final-vintage pseudo-OOS」，撤回 real-time predictive claim。

2. [K1655.py:202–229](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:202)、[K1655.py:439–459](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:439) — HLN 公式與 H−1 lag 寫對了，但對實際 loss differential 的 HAC 不足。

   正確部分：`h=H`、NW lag=`H−1`、HLN factor 均正確；`d=loss_cond-loss_uncond`，所以負 t 表示 conditional 較佳。

   問題是實際 loss differential 的序列相關遠超 H−1：

   - NFCI vol、H1、τ=.95：lag-1 ACF=0.677，但主檢定 lag=0；t 從 −4.22 降至 helper 的 −1.71，Harvey 與一般 5% 顯著性都消失（[results:1735–1740](/Users/yhlai0911/volpred-research/experiments/K1655/K1655_results.json:1735)）。
   - VIX vol、H4、τ=.95：主 t=−3.31，helper t=−2.52，Harvey 結論消失（[results:2428–2433](/Users/yhlai0911/volpred-research/experiments/K1655/K1655_results.json:2428)）。
   - NFCI return、H1、τ=.05：主 t=−2.74，helper t=−2.09（[results:447–452](/Users/yhlai0911/volpred-research/experiments/K1655/K1655_results.json:447)）。

   此外 conditional model 與 unconditional benchmark 是 nested、recursive estimated forecasts；HLN correction 本身沒有處理 nested-model／parameter-estimation 的非標準推論。

   Suggested fix：HAC bandwidth 採 `max(H−1, data-driven bandwidth)` 並報完整 sensitivity；主推論改用 recursive block bootstrap 或 quantile forecast-encompassing／Giacomini–White 類檢定。

3. [K1655.py:607–622](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:607)、[README.md:147–149](/Users/yhlai0911/volpred-research/experiments/K1655/README.md:147) — 「VIX dominates/subsumes/absorbs NFCI」沒有被實驗設計檢定。

   程式只各自比較 NFCI-only、VIX-only 與 unconditional benchmark。VIX 的點估 pinball loss 在三個 H 都較低，但沒有：

   - NFCI vs VIX 的 paired loss DM；
   - VIX+NFCI vs VIX-only 的 incremental/encompassing test。

   因此「VIX subsumes NFCI」及「confirms K503/K828」超過證據範圍，且是 README verdict 的核心敘事。

   Suggested fix：在完全相同 origins 上直接比較兩組 pointwise losses，並新增 VIX-only 對 VIX+NFCI 的 OOS quantile encompassing test。

4. [K1655.py:232–254](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:232)、[K1655.py:328–345](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:328) — 「in-sample 三個 horizon 都顯著」的 bootstrap leg 不夠穩健。

   `block=H` 只處理機械重疊；H=1 直接退化成 iid pairs bootstrap，未涵蓋 NFCI persistence／危機 clustering。`boot_p` 其實是 `2Φ(-|coef/bootstrap_sd|)`，不是 bootstrap-null p-value。Block-length sensitivity 中，H4 p 可升至 .056，H12 的 95% percentile CI 可包含 0。

   Suggested fix：用資料驅動 block length、報多組 block sensitivity，並採 recentered/studentized bootstrap p-value。

MINOR ISSUES:

1. [K1655.py:459](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:459)、[K1655.py:564–570](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:564)：`abs(t)>3` 會把顯著較差的正 t 也標為 Harvey，且 verdict 可把不同 H 的 nominal win 與 adverse Harvey cell 拼成 `PASS`。應要求同一 cell 的 `t < -3`。目前 26 個 Harvey flags 都是負 t，所以未改變這次 JSON。

2. `|t|>3` 符合 repo heuristic，但不是正式 multiplicity correction。本次有 60 個 OOS DM tests；Bonferroni 5% 臨界約為 |t|>3.35。應明定 confirmatory family：primary NFCI return τ=.05 只有三個 H，其他 57 cells 屬 exploratory。

3. [K1655.py:79](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:79)、[K1655.py:194–199](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:194)、[K1655.py:248–252](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:248)：全域忽略 warnings 並吞掉 exceptions。完整重跑發現：

   - bootstrap：11/30,000 fits 達 2,000 iteration cap；
   - OOS：2/16,860 refits 達 cap，包括 primary NFCI-return H4 τ=.05；
   - thrown exceptions=0。

   這與 [README.md:183–186](/Users/yhlai0911/volpred-research/experiments/K1655/README.md:183)「primary return fits 未觀察到」矛盾。提高 `max_iter` 後目前 aggregate 幾乎不變，但程式應儲存 convergence diagnostics 並 fail/retry。

4. Separate quantile fits 沒有 non-crossing constraint。OOS 重跑發現 NFCI-return H12 有 7/1,109 origins 出現 q.05>q.25；NFCI-vol H12 更有 65/1,109。對「完整 conditional distribution」主張應做 rearrangement 或 joint quantile estimation。

5. [K1655.py:139–150](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:139) 實際使用 `^GSPC`，不是 SPY。這是 S&P 500 price index，不含 SPY total return；README 的「SPY／tradeable」措辭不準確。

6. [K1655.py:265–269](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:265)：原始價格只到 2026-06-30，但 resample 把未完成 bin 標成 2026-07-03；每個 H 都有一個被評分 target 結束於這個 partial week。

7. [K1655.py:451](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:451) 的 reduction 無零／近零 denominator guard。當前最小 benchmark loss=0.0025724，因此本次未受影響。

8. [K1655.py:592–597](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:592) 刪除了 origins、realized、forecasts、pointwise losses；JSON 因而無法獨立重算 breach、DM 或 calibration。應另存 forecast-level artifact。

FULL-POPULATION AUDIT:

- 完整讀取 709 行 Python、201 行 README、2,534 行 JSON。
- 掃描全部 60 個 in-sample cells 與 60 個 OOS cells：
  `2 targets × 2 specs × 3 H × 5 τ`。
- 所有值 finite；無 missing cells。
- IS n 全數為 H1=1,382、H4=1,379、H12=1,371。
- OOS n 全數為 H1=1,131、H4=1,125、H12=1,109。
- 60/60 reductions 重算完全一致；60/60 DM signs、`cond_better`、NW lag、Harvey flags 一致。
- 51/60 reductions 為正，35/60 raw p<.05，26/60 Harvey-significant。
- Primary NFCI-return τ=.05：只有 H1 nominally significant，0/3 Harvey。
- 兩個 specs 的 return τ=.05 六列中，VIX-H1 是唯一 Harvey cell；此 uniqueness framing在該明確範圍內成立。
- 完整 replay：30,000 bootstrap fits、16,860 OOS refits、67,300 pointwise loss differentials。
- Blind spots：未以真 ALFRED vintages 重跑，因此 revision bias 的方向與幅度未知；未做正式 NFCI-vs-VIX paired test；圖中「2008/2020 precisely」屬視覺敘事，JSON 不足以正式檢驗。
- Forward timing 本身通過：
  - [K1655.py:288–301](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:288)：return 與 RV labels 都恰好結束於 j+H。
  - [K1655.py:385–400](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:385)：最大 train row 是 i−H−1，其 label 結束於 i−1；scoring row i 不會進 training。
  - [K1655.py:404–425](/Users/yhlai0911/volpred-research/experiments/K1655/K1655.py:404)：benchmark 使用同一 embargoed `ytr`；cache 最多 stale 三週，不含 future data。
  - X 沒有 centered rolling。VIX_F 在「Friday close 後發布 forecast」假設下 timing 合法；NFCI 的缺陷是 vintage/backcast，不是 j/H indexing。

CLAIM CHECK:

1. [README.md:3–7](/Users/yhlai0911/volpred-research/experiments/K1655/README.md:3) `CONDITIONAL_PASS` → **JSON 有支援，但研究結論不應 finalize**。JSON 確實寫入 `CONDITIONAL_PASS`（[results:2521](/Users/yhlai0911/volpred-research/experiments/K1655/K1655_results.json:2521)），但 PIT 與推論缺陷使 verdict 無效。

2. 「n=1,383；OOS ≈1,110–1,131」→ **大致支援**。正確範圍是 1,109–1,131，不是 1,110–1,131；資產應稱 `^GSPC`，不是 SPY。

3. 「NFCI in-sample GaR fan、τ=.05 三個 H 都顯著，median 不顯著」→ **依 committed numbers 支援，但不穩健**：

   - H1 slope −0.021918，p=.013832；
   - H4 −0.066049，p=.034591；
   - H12 −0.147197，p=.022868；
   - median p=.2155、.7863、.7064。

   三組 slope 都隨 τ 單調上升；但 bootstrap 設計不足以支持「cleanly confirmed」。

4. 「NFCI return-tail 只有 H1 nominal edge、全部不過 Harvey」→ **支援**：

   - H1 +6.739%，t=−2.740，p=.00624；
   - H4 +3.515%，t=−.874，p=.382；
   - H12 −3.323%，t=+.739，p=.460；
   - Harvey 0/3。

   「vanishes at 4w」若指統計顯著性成立；若指 point improvement 為零則不成立。

5. 「VIX return H1 通過 Harvey」→ **支援**：+12.456%，t=−3.622，p=.000306。H4 仍有 +7.427%、p=.021，但不過 Harvey；H12 +0.331%、p=.937。

6. 「VIX dominates/subsumes NFCI」→ **點估描述支援、推論主張不支援**。三個 H 的 VIX loss 都較低，但沒有直接或 incremental test。

7. 「conditional 5% quantile breach 4.2%，calibration good」→ **4.2% 數字重算正確，但 JSON 不支援完整主張**：47/1,125=4.1778%。JSON 沒存 count、forecast path 或正式 coverage/independence test；「good」與「precisely in 2008/2020」超出 artifact。

8. Vol-at-Risk 表四列 → **數字支援，但顯著性敘事過強**：

   - NFCI H1 +25.420%，t=−4.222；helper t=−1.707。
   - NFCI H4 +20.539%，t=−2.334；helper t=−1.637。
   - VIX H1 +51.394%，t=−7.253；helper t=−3.360。
   - VIX H4 +36.987%，t=−3.314；helper t=−2.517。

   README 漏報 H12：NFCI +1.951%、p=.813；VIX +21.486%、p=.05184。

9. 「full grid is reported」→ **只對 JSON 成立**。JSON 有完整 120 cells；README 只顯示 25 個選定 cells，且漏掉兩個 H12 vol-tail rows。

10. 「iteration-limit issue negligible、primary return fits 未受影響」→ **部分不支援／部分錯誤**。Higher-iteration sensitivity 顯示 aggregate 影響很小，但 primary NFCI-return H4 OOS 與 primary-return bootstrap 確實出現 iteration cap，且 artifact 沒有儲存診斷。

全程唯讀；未修改任何檔案。
```
