# vix-sufficiency v9a — family-count edits (thirteen→twelve), apply_paper_edits.py format

**Requested by**: manager decision `item_20260805T200528019400Z`（2026-08-05）：F3/BSI 降級為
robustness 診斷，家族數 thirteen→twelve。

**Scope of this file**: 只含**純機械的計數詞替換**（19 處，含 L48 移除列舉中的
`behavioral sentiment,`），全部 1 行→1 行、無新增內容，符合 `apply_paper_edits.py` C3
（等行數）。**不含**四項需要主線程 LaTeX 判斷的結構性編輯（Table 1 footnote、§2.3 新增段落、
Table 2 marker + Holm-Bonferroni 查證句、L519/L517 段落改寫含 F10 已完成的結果）——那四項
留在 `vix_sufficiency_v9_edit_instructions_20260805.md`（prose 格式），因為插入新句／新
footnote／新 `\label` 需要主線程邊改邊確認排版與交叉引用不壞，不適合盲套機械 diff。

**已用 dry-run 自我驗證**（本部門執行，唯讀，未寫檔）：
`uv run python scripts/apply_paper_edits.py <this file> `——19 筆 Original/Replacement
全數 parse 正確、C1（hash）/C2（唯一性）/C3（等行數）三項全過，diff 與下列逐字相符。

**Target file**: `paper/vix-sufficiency/main_v5.tex`

| 項目 | 期望值 |
|---|---|
| sha256 | `1f397228119e0b875922acebf18670fceaa97c406bd2cde074aaaca82adb5f3b` |
| bytes | `139944` |

**不符即停**：round 已 stale，19 筆指令全部作廢，退回論文部重出，不要自行調整 FIND 字串去湊。

**Round evidence**: `../review_history/v9a_family_count_20260806/`（若目錄不存在，套用前由
執行者建立空目錄——本檔第一次跑，尚無先前 round 產物）。

**禁止觸碰的相似字串**：`main_v5.tex:870`「thirteen of sixteen DM statistics change by less
than 0.5」——這是「16 個 cell 裡有 13 個」的計數，與家族總數無關，本檔刻意不含這行，套用時
若看到任何工具或人工提議把它也改掉，**拒絕**。

---

## Edit 1 — `main_v5.tex:35` — 標題

**Original**

```latex
\title{Can Anything Beat VIX? A Systematic Out-of-Sample Evaluation of Thirteen Signal Families for Equity Volatility Forecasting and Volatility Timing\thanks{All errors are my own. Data and replication code are available upon request.}}
```

**Replacement**

```latex
\title{Can Anything Beat VIX? A Systematic Out-of-Sample Evaluation of Twelve Signal Families for Equity Volatility Forecasting and Volatility Timing\thanks{All errors are my own. Data and replication code are available upon request.}}
```

## Edit 2 — `main_v5.tex:48` — Abstract：計數 + 移除列舉中的 F3

**Original**

```latex
We conduct a systematic out-of-sample horse race among thirteen pre-specified signal families---cross-asset volatility momentum, VIX term structure, behavioral sentiment, the variance risk premium, multi-asset portfolio optimization, equal risk contribution, Bitcoin volatility, the yield curve slope, Google Trends fear proxies, overnight VIX changes, calendar anomalies, economic-policy uncertainty, and financial-stress indices---evaluating whether any can improve upon VIX alone for equity volatility forecasting and volatility-timing portfolio construction. Using daily S\&P~500 data spanning 1993--2026, we apply a unified forecast pipeline with strict lag enforcement, transaction-cost accounting, publication-delay-corrected treatment of weekly macroeconomic series, the \citet{harvey2016} multiple-testing threshold ($|t|>3.0$), formal Holm-Bonferroni correction, and proxy-robust evaluation following \citet{patton2011}. The main finding is strongly negative: not a single signal family produces a statistically significant out-of-sample improvement---whether measured by the standard \citet{campbell2008} $R^2_{\text{OOS}}$ relative to the historical mean, by incremental $R^2$ relative to VIX-only forecasts, or by Sharpe ratio gains for volatility-timing strategies---and all results survive Holm-Bonferroni family-wise error rate correction. The VIX--realized volatility $R^2$ ranges from 0.24 to 0.64 across five non-overlapping eras spanning 33 years (coefficient of variation = 0.33), demonstrating time-invariance. Volatility model rankings are criterion-dependent---GJR-GARCH dominates under proxy-robust QLIKE on $r_t^2$ (Model Confidence Set sole member) while AMEM dominates for VaR/ES risk management (composite score 1.94 vs.\ 1.63)---yet VIX sufficiency holds regardless of which model or criterion is used. We frame VIX sufficiency as a rational outcome of option-market information aggregation and show that volatility timing functions as drawdown insurance---costly in Sharpe terms (average drag 3.49\%/year for 12/VIX) but welfare-improving for investors with CRRA risk aversion $\gamma \geq 4.5$. The informative null sharpens the research frontier: future gains require either higher-frequency realized measures or genuinely exogenous information not already embedded in option prices.
```

**Replacement**

```latex
We conduct a systematic out-of-sample horse race among twelve pre-specified signal families---cross-asset volatility momentum, VIX term structure, the variance risk premium, multi-asset portfolio optimization, equal risk contribution, Bitcoin volatility, the yield curve slope, Google Trends fear proxies, overnight VIX changes, calendar anomalies, economic-policy uncertainty, and financial-stress indices---evaluating whether any can improve upon VIX alone for equity volatility forecasting and volatility-timing portfolio construction. Using daily S\&P~500 data spanning 1993--2026, we apply a unified forecast pipeline with strict lag enforcement, transaction-cost accounting, publication-delay-corrected treatment of weekly macroeconomic series, the \citet{harvey2016} multiple-testing threshold ($|t|>3.0$), formal Holm-Bonferroni correction, and proxy-robust evaluation following \citet{patton2011}. The main finding is strongly negative: not a single signal family produces a statistically significant out-of-sample improvement---whether measured by the standard \citet{campbell2008} $R^2_{\text{OOS}}$ relative to the historical mean, by incremental $R^2$ relative to VIX-only forecasts, or by Sharpe ratio gains for volatility-timing strategies---and all results survive Holm-Bonferroni family-wise error rate correction. The VIX--realized volatility $R^2$ ranges from 0.24 to 0.64 across five non-overlapping eras spanning 33 years (coefficient of variation = 0.33), demonstrating time-invariance. Volatility model rankings are criterion-dependent---GJR-GARCH dominates under proxy-robust QLIKE on $r_t^2$ (Model Confidence Set sole member) while AMEM dominates for VaR/ES risk management (composite score 1.94 vs.\ 1.63)---yet VIX sufficiency holds regardless of which model or criterion is used. We frame VIX sufficiency as a rational outcome of option-market information aggregation and show that volatility timing functions as drawdown insurance---costly in Sharpe terms (average drag 3.49\%/year for 12/VIX) but welfare-improving for investors with CRRA risk aversion $\gamma \geq 4.5$. The informative null sharpens the research frontier: future gains require either higher-frequency realized measures or genuinely exogenous information not already embedded in option prices.
```

## Edit 3 — `main_v5.tex:74` — Introduction

**Original**

```latex
We address this gap by conducting the first comprehensive, pre-specified horse race among thirteen signal families, evaluated under a unified framework with six methodological safeguards (families 1--11 were specified in the original design; families 12--13 were added in this revision and evaluated under the identical pipeline and multiple-testing correction):
```

**Replacement**

```latex
We address this gap by conducting the first comprehensive, pre-specified horse race among twelve signal families, evaluated under a unified framework with six methodological safeguards (families 1--11 were specified in the original design; families 12--13 were added in this revision and evaluated under the identical pipeline and multiple-testing correction):
```

## Edit 4 — `main_v5.tex:77` — Pre-specification bullet

**Original**

```latex
    \item \textbf{Pre-specification}: All thirteen signal families and their construction rules are defined before examining out-of-sample results, eliminating data-snooping in signal selection.
```

**Replacement**

```latex
    \item \textbf{Pre-specification}: All twelve signal families and their construction rules are defined before examining out-of-sample results, eliminating data-snooping in signal selection.
```

## Edit 5 — `main_v5.tex:94` — Information aggregation

**Original**

```latex
We interpret this null through the lens of option-market information aggregation. VIX is not simply a backward-looking statistical estimate; it is the forward-looking consensus of thousands of option traders who collectively incorporate cross-asset signals, macroeconomic data, sentiment, and term structure information into their pricing. The thirteen signal families we test are precisely the inputs that option traders use. VIX, by construction, already contains them.
```

**Replacement**

```latex
We interpret this null through the lens of option-market information aggregation. VIX is not simply a backward-looking statistical estimate; it is the forward-looking consensus of thousands of option traders who collectively incorporate cross-asset signals, macroeconomic data, sentiment, and term structure information into their pricing. The twelve signal families we test are precisely the inputs that option traders use. VIX, by construction, already contains them.
```

## Edit 6 — `main_v5.tex:100` — Roadmap paragraph

**Original**

```latex
The remainder of the paper is organized as follows. Section~\ref{sec:whyvix} reviews the theoretical and empirical foundations of VIX as a benchmark. Section~\ref{sec:data} describes the data and the thirteen signal families. Section~\ref{sec:methodology} details the forecast design, loss function choice, and the \citet{patton2011} proxy-robustness framework. Section~\ref{sec:evaluation} explains the statistical evaluation framework, including the Model Confidence Set of \citet{hansen2011mcs}. Section~\ref{sec:strategy} describes the volatility-timing strategy design. Section~\ref{sec:results} presents the main results, criterion-dependent model rankings, and robustness checks. Section~\ref{sec:null} discusses why the null is informative, including economic significance via VaR/ES backtesting. Section~\ref{sec:conclusion} concludes.
```

**Replacement**

```latex
The remainder of the paper is organized as follows. Section~\ref{sec:whyvix} reviews the theoretical and empirical foundations of VIX as a benchmark. Section~\ref{sec:data} describes the data and the twelve signal families. Section~\ref{sec:methodology} details the forecast design, loss function choice, and the \citet{patton2011} proxy-robustness framework. Section~\ref{sec:evaluation} explains the statistical evaluation framework, including the Model Confidence Set of \citet{hansen2011mcs}. Section~\ref{sec:strategy} describes the volatility-timing strategy design. Section~\ref{sec:results} presents the main results, criterion-dependent model rankings, and robustness checks. Section~\ref{sec:null} discusses why the null is informative, including economic significance via VaR/ES backtesting. Section~\ref{sec:conclusion} concludes.
```

## Edit 7 — `main_v5.tex:134` — Structural argument

**Original**

```latex
We argue that VIX's forecasting dominance is not accidental but structural. Options markets aggregate information from heterogeneous traders---fundamental analysts who track earnings volatility, macro strategists who monitor the yield curve, systematic traders who exploit cross-asset correlations, and market makers who process order flow. Each of the thirteen signal families we test represents one channel of information that at least some option traders monitor. VIX, as the price-weighted consensus of their collective activity, already incorporates these inputs.
```

**Replacement**

```latex
We argue that VIX's forecasting dominance is not accidental but structural. Options markets aggregate information from heterogeneous traders---fundamental analysts who track earnings volatility, macro strategists who monitor the yield curve, systematic traders who exploit cross-asset correlations, and market makers who process order flow. Each of the twelve signal families we test represents one channel of information that at least some option traders monitor. VIX, as the price-weighted consensus of their collective activity, already incorporates these inputs.
```

## Edit 8 — `main_v5.tex:144` — Contribution statement

**Original**

```latex
Our contribution differs from these studies in three ways: (i) we test thirteen signal families simultaneously rather than one at a time; (ii) we use a unified evaluation pipeline with consistent lag, cost, and statistical conventions; and (iii) we frame the null as informative rather than disappointing, connecting it to option-market efficiency.
```

**Replacement**

```latex
Our contribution differs from these studies in three ways: (i) we test twelve signal families simultaneously rather than one at a time; (ii) we use a unified evaluation pipeline with consistent lag, cost, and statistical conventions; and (iii) we frame the null as informative rather than disappointing, connecting it to option-market efficiency.
```

## Edit 9 — `main_v5.tex:148` — Section title

**Original**

```latex
\section{Data and the Thirteen Signal Families}
```

**Replacement**

```latex
\section{Data and the Twelve Signal Families}
```

## Edit 10 — `main_v5.tex:163` — Subsection title

**Original**

```latex
\subsection{The Thirteen Signal Families}
```

**Replacement**

```latex
\subsection{The Twelve Signal Families}
```

## Edit 11 — `main_v5.tex:165` — Pre-specification sentence

**Original**

```latex
We pre-specify thirteen signal families spanning seven broad categories: cross-asset, derivatives-based, behavioral, macroeconomic, alternative data, calendar, and economic-policy/financial-stress uncertainty. Table~\ref{tab:signals} summarizes each family. Families 12--13 are added in this revision to test whether canonical alt-data uncertainty proxies (EPU and financial-stress indices) carry orthogonal information beyond VIX.
```

**Replacement**

```latex
We pre-specify twelve signal families spanning seven broad categories: cross-asset, derivatives-based, behavioral, macroeconomic, alternative data, calendar, and economic-policy/financial-stress uncertainty. Table~\ref{tab:signals} summarizes each family. Families 12--13 are added in this revision to test whether canonical alt-data uncertainty proxies (EPU and financial-stress indices) carry orthogonal information beyond VIX.
```

**注**：本行未加入 F3 地位說明句（那需要 `\S\ref{sec:family3}` 交叉引用，`\label` 尚未存在，
留給結構性編輯那批一次處理，避免這裡先加一個指向不存在 label 的引用）。

## Edit 12 — `main_v5.tex:171` — Table 1 caption

**Original**

```latex
\caption{The Thirteen Signal Families}
```

**Replacement**

```latex
\caption{The Twelve Signal Families}
```

## Edit 13 — `main_v5.tex:467` — Table 2 lead-in

**Original**

```latex
Table~\ref{tab:main_results} presents the main results for all thirteen signal families. The key finding is unanimous: no signal produces a statistically significant out-of-sample improvement over VIX; two of the canonical alt-data families (EPU and financial stress) are reported here in their standalone specification (M3/M4, which replace VIX) and are signed in the \emph{worse-than-VIX} direction, i.e., the alt-data-only forecast is significantly worse than the VIX-only baseline. When these same series are instead added to VIX, the nested Clark-West increment is statistically zero (Section~\ref{sec:clark_west}), so the direction reflects redundancy under a standalone reading rather than harm.
```

**Replacement**

```latex
Table~\ref{tab:main_results} presents the main results for all twelve signal families. The key finding is unanimous: no signal produces a statistically significant out-of-sample improvement over VIX; two of the canonical alt-data families (EPU and financial stress) are reported here in their standalone specification (M3/M4, which replace VIX) and are signed in the \emph{worse-than-VIX} direction, i.e., the alt-data-only forecast is significantly worse than the VIX-only baseline. When these same series are instead added to VIX, the nested Clark-West increment is statistically zero (Section~\ref{sec:clark_west}), so the direction reflects redundancy under a standalone reading rather than harm.
```

## Edit 14 — `main_v5.tex:473` — Table 2 caption

**Original**

```latex
\caption{Volatility Forecasting: Thirteen Signal Families vs.\ VIX}
```

**Replacement**

```latex
\caption{Volatility Forecasting: Twelve Signal Families vs.\ VIX}
```

## Edit 15 — `main_v5.tex:671` — Era decomposition paragraph

**Original**

```latex
The era decomposition qualifies rather than overturns VIX sufficiency. In the three calm regimes the competing signals are negligible, consistent with VIX absorbing all usable volatility information. In the two crisis regimes---the GFC and the COVID/Inflation era---several signals do add statistically significant \emph{in-sample} explanatory power, volatility momentum most strongly (up to 3.7\% incremental $R^2$). This crisis-era in-sample content does not, however, translate into out-of-sample forecasting gains: cross-asset volatility momentum, the variance risk premium, and overnight VIX changes are all among the thirteen families evaluated in the main horse race (Section~\ref{sec:results}), and none produces a statistically significant out-of-sample improvement over VIX after Holm--Bonferroni correction. The pattern---in-sample crisis-era significance that vanishes out-of-sample---is the signature of overfitting to episodic volatility clustering rather than of exploitable ex-ante information. VIX sufficiency is therefore best characterized as a robust \emph{out-of-sample} property that holds across regimes, not as an absence of any in-sample association in any era.
```

**Replacement**

```latex
The era decomposition qualifies rather than overturns VIX sufficiency. In the three calm regimes the competing signals are negligible, consistent with VIX absorbing all usable volatility information. In the two crisis regimes---the GFC and the COVID/Inflation era---several signals do add statistically significant \emph{in-sample} explanatory power, volatility momentum most strongly (up to 3.7\% incremental $R^2$). This crisis-era in-sample content does not, however, translate into out-of-sample forecasting gains: cross-asset volatility momentum, the variance risk premium, and overnight VIX changes are all among the twelve families evaluated in the main horse race (Section~\ref{sec:results}), and none produces a statistically significant out-of-sample improvement over VIX after Holm--Bonferroni correction. The pattern---in-sample crisis-era significance that vanishes out-of-sample---is the signature of overfitting to episodic volatility clustering rather than of exploitable ex-ante information. VIX sufficiency is therefore best characterized as a robust \emph{out-of-sample} property that holds across regimes, not as an absence of any in-sample association in any era.
```

## Edit 16 — `main_v5.tex:805` — Failure-channel intro

**Original**

```latex
The aggregate null across thirteen signal families conceals a structured heterogeneity in \emph{how} different model architectures fail. We characterize three channels with qualitatively distinct failure patterns, providing sharper guidance for future research beyond ``all signals fail.''
```

**Replacement**

```latex
The aggregate null across twelve signal families conceals a structured heterogeneity in \emph{how} different model architectures fail. We characterize three channels with qualitatively distinct failure patterns, providing sharper guidance for future research beyond ``all signals fail.''
```

## Edit 17 — `main_v5.tex:1030` — Sufficient-statistic paragraph

**Original**

```latex
i.e., VIX is a sufficient statistic for all information already incorporated in option prices. Our thirteen signal families are all elements of $\Omega_t$, which explains the zero incremental forecasting power.
```

**Replacement**

```latex
i.e., VIX is a sufficient statistic for all information already incorporated in option prices. Our twelve signal families are all elements of $\Omega_t$, which explains the zero incremental forecasting power.
```

## Edit 18 — `main_v5.tex:1141` — Conclusion opening

**Original**

```latex
We set out to answer a straightforward question: can any observable signal beat VIX for equity volatility forecasting and volatility timing? After a systematic evaluation of thirteen pre-specified signal families across 33 years of data, five market eras, and a unified pipeline with strict lag enforcement, transaction-cost accounting, publication-delay correction for weekly macroeconomic series, Harvey (2016) approximate thresholds, formal Holm-Bonferroni multiple-testing correction, and proxy-robust evaluation per \citet{patton2011}, the answer is no.
```

**Replacement**

```latex
We set out to answer a straightforward question: can any observable signal beat VIX for equity volatility forecasting and volatility timing? After a systematic evaluation of twelve pre-specified signal families across 33 years of data, five market eras, and a unified pipeline with strict lag enforcement, transaction-cost accounting, publication-delay correction for weekly macroeconomic series, Harvey (2016) approximate thresholds, formal Holm-Bonferroni multiple-testing correction, and proxy-robust evaluation per \citet{patton2011}, the answer is no.
```

## Edit 19 — `main_v5.tex:1143` — Conclusion, options-market efficiency

**Original**

```latex
This null is not a failure but an informative finding. It reflects the efficiency of the options market, which aggregates heterogeneous information---cross-asset correlations, macroeconomic indicators, sentiment, term structure dynamics---into a single summary statistic. Each of the thirteen signal families we tested represents one channel of information that option traders already incorporate into their pricing. VIX, as the price-weighted consensus, already contains them.
```

**Replacement**

```latex
This null is not a failure but an informative finding. It reflects the efficiency of the options market, which aggregates heterogeneous information---cross-asset correlations, macroeconomic indicators, sentiment, term structure dynamics---into a single summary statistic. Each of the twelve signal families we tested represents one channel of information that option traders already incorporate into their pricing. VIX, as the price-weighted consensus, already contains them.
```

---

## 套用後

1. `git diff paper/vix-sufficiency/main_v5.tex` 應只有這 19 行，且每行只有 thirteen/Thirteen
   → twelve/Twelve（Edit 2 額外少了 `behavioral sentiment, `）
2. 確認 L870「thirteen of sixteen」**未被誤觸**
3. 接續套用 `vix_sufficiency_v9_edit_instructions_20260805.md` 的四項結構性編輯（Table 1/2
   footnote、§2.3 新段、L519/L517 段落改寫），那批完成後家族數的敘述與 F3/F9/F10 的實際狀態
   才完全一致
4. 兩批都套用完才重編、跑 `paper-update`、開 v9 review round；本檔單獨套用不構成可投稿狀態
