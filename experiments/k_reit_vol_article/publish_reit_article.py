"""Publish REIT / Housing Vol daily_article (draft) to feed.

Reads:
  - reit_vol_results.json (statistics)
  - fig_vnq_spy_rv.png, fig_vnq_spy_corr.png (charts)

Uploads charts to Supabase, writes article to storage/reports/feed.json as draft.
"""
import json
from pathlib import Path

from volpred.publisher.publisher import Publisher
from volpred.charts.article_charts import upload_chart

HERE = Path(__file__).parent
results = json.loads((HERE / "reit_vol_results.json").read_text())
META = results["meta"]
FS = results["fullsample_stats"]
SUB = results["subperiod_stats"]
HAR = results["har_rv_oos"]
DM = results["dm_test_qlike_VNQ_minus_SPY"]


# Upload charts to Supabase
print("[info] uploading fig_vnq_spy_rv.png …")
url_rv = upload_chart(str(HERE / "fig_vnq_spy_rv.png"))
print(f"  -> {url_rv}")

print("[info] uploading fig_vnq_spy_corr.png …")
url_corr = upload_chart(str(HERE / "fig_vnq_spy_corr.png"))
print(f"  -> {url_corr}")


# Build article (research audience, 學術報告式 per 2026-04-18 SKILL)
title = "REIT 波動率 vs SPY：VNQ-SPY 跨 regime 相關動態與 HAR-RV 可預測性實證"

content = f"""# REIT 波動率 vs SPY：VNQ-SPY 跨 regime 相關動態與 HAR-RV 可預測性實證

[提出: Claude]

## 摘要

本研究以 Vanguard Real Estate ETF (**VNQ**) 作為美國上市 REIT 的代理變量，與 S&P 500 ETF (**SPY**) 進行年化波動率、63 日滾動相關、以及 HAR-RV 日頻方差一步預測的 out-of-sample（OOS）對比。全樣本 {META['period']}（N={META['n_obs']:,} 個交易日）顯示 VNQ 的年化波動率 **{FS['ann_vol_VNQ_pct']:.2f}%** 高於 SPY 的 **{FS['ann_vol_SPY_pct']:.2f}%**，但 naive Sharpe 僅 {FS['sharpe_VNQ_naive']:.3f}（SPY {FS['sharpe_SPY_naive']:.3f}），反映 REIT 承擔更高波動卻未獲得 risk-compensation。滾動 63 日相關係數在 **[{FS['min_rolling_corr_63d']:.3f}, {FS['max_rolling_corr_63d']:.3f}]** 區間強烈 regime-switching — 於 COVID 崩跌（2020-02/03）飆至 0.941，Fed 升息循環（2022-03 ~ 2023-07）維持在 0.797，後 COVID 平靜期回落至 0.648。HAR-RV OOS 一步預測（train ≤ 2022-12-31, test 2023-01 ~ 2026-04，N_oos={HAR['VNQ']['n_oos']}）VNQ QLIKE = **{HAR['VNQ']['qlike']:.4f}** vs SPY **{HAR['SPY']['qlike']:.4f}**，Diebold-Mariano 統計量 t = **{DM['t']:.3f}**（p = {DM['p_value']:.3f}，HLN-unadjusted）— REIT 的 HAR-RV 可預測性與大盤 **沒有統計顯著差異**（null result）。實務意涵：REIT 的 vol premium 主要反映 regime-dependent 相關增強（tail correlation），而非結構性預測難度差異。

## 研究背景

本平台長期聚焦於股票（SPY / 0050.TW）、黃金（GLD）、波動率（VIX 家族）、加密（BTC）等 dominant 資產類的波動率建模（截至 2026-04-19 knowledge.json 相關 K 編號超過 1,100）。根據平台內部 topic diversity audit（`docs/topic_diversity_audit.md`，2026-04-19 版），**REIT / housing vol** 的 feed 覆蓋率為 0（feed_ct=0，kb_ct=1），為系統性 under-explored 方向之一。

REIT 作為 **實物資產（real estate）** 的市場代理，理論上其波動率應受下列三類因子同時驅動：

1. **股票市場系統性因子**（SPY β）：REIT 上市 ETF 以股票形式交易，承擔股票流動性衝擊。
2. **利率敏感度**（duration-like exposure）：REIT 現金流類似長期 bond，Fed funds rate 上升期間，折現率上升 + 房地產 cap rate 重評，double squeeze。
3. **房地產基本面**（NOI / cap rate / vacancy）：長期仍錨定於實物市場。

相較之下，SPY 主要承擔第 1 類因子。兩者之間的相關係數 ρ(VNQ, SPY) 若長期穩定，支持「REIT 已完全股票化」假說；若顯著 regime-switching（特別是在 Fed 循環與 crisis 期間），則說明 REIT 的實物因子仍具獨立波動來源，對 vol forecasting 與 portfolio diversification 都有意涵。

本研究差異化：
- 既有 knowledge 的跨資產 spillover 研究（K167 VIX VRP 跨資產、SPY-GLD Granger 等）**未涵蓋 REIT**。
- 既有 VT 策略多以 SPY / GLD / TLT 為標的（例如 K702 50/50 SPY/GLD 為 best Sharpe baseline），REIT 從未納入候選資產池。
- 本研究定位為 **exploratory baseline**：先建立 VNQ vs SPY 的 vol dynamics 與 HAR-RV 可預測性 baseline，作為未來跨 regime VT / dynamic allocation 實驗的依據。

## 方法與數據

| 項目 | 設定 |
|------|------|
| 資產 | VNQ（Vanguard Real Estate ETF）、SPY |
| 期間 | {META['period']} |
| 樣本 | {META['n_obs']:,} 個日頻觀測值（兩資產同時上市且有效） |
| 資料源 | yfinance `auto_adjust=False`（**data snapshot rule 2026-04-19**；後續以 Adj Close 計算 log return） |
| 報酬口徑 | $r_t = \\ln(P_t / P_{{t-1}}) \\times 100$（百分比對數報酬，t-1 資訊 → t 報酬，無 look-ahead） |
| 實現方差 proxy | 22 日滾動 $\\mathrm{{var}}(r_t)$（daily），年化後用於時序圖 |
| 滾動相關 | 63 日滾動 Pearson $\\rho(r_{{\\mathrm{{VNQ}}}}, r_{{\\mathrm{{SPY}}}})$（約一季度） |
| HAR-RV spec | Corsi (2009)：$\\mathrm{{RV}}_t = \\beta_0 + \\beta_d \\mathrm{{RV}}_{{t-1}} + \\beta_w \\overline{{\\mathrm{{RV}}}}_{{t-1:t-5}} + \\beta_m \\overline{{\\mathrm{{RV}}}}_{{t-1:t-22}} + \\varepsilon_t$；daily RV 用 $r_t^2$（無 intraday），一步 OOS 預測 |
| OOS 切分 | train ≤ 2022-12-31，test 2023-01-01 ~ 2026-04-17（N_oos = {HAR['VNQ']['n_oos']}） |
| 評估指標 | Patton (2011) QLIKE 損失： $L = \\sigma^2 / \\hat{{\\sigma}}^2 - \\ln(\\sigma^2 / \\hat{{\\sigma}}^2) - 1$；DM HLN-unadjusted |
| 統計門檻 | DM &#124;t&#124; > 1.96 視為 p < 0.05 統計顯著 |
| 固定 seed | 42（本研究無隨機程序，seed 保留以備 bootstrap 延伸） |

子期間切分用於 regime 對比：
- **COVID 崩跌**：2020-02-19 ~ 2020-03-23（N={SUB['COVID_crash']['n']}）
- **後 COVID 平靜期**：2021-06-01 ~ 2021-12-31（N={SUB['post_COVID_calm']['n']}）
- **Fed 升息循環**：2022-03-16 ~ 2023-07-26（N={SUB['Fed_hike_2022_23']['n']}）

## 核心發現

### 發現一：VNQ 承擔更高波動率但獲得更低報酬（unconditional risk-compensation mismatch）

全樣本（N={META['n_obs']:,}）統計量：

| 指標 | VNQ（REIT） | SPY | 差距 |
|------|------------:|----:|-----:|
| 年化報酬（%） | {FS['ann_ret_VNQ_pct']:.2f} | {FS['ann_ret_SPY_pct']:.2f} | {FS['ann_ret_VNQ_pct'] - FS['ann_ret_SPY_pct']:+.2f} |
| 年化波動率（%） | {FS['ann_vol_VNQ_pct']:.2f} | {FS['ann_vol_SPY_pct']:.2f} | {FS['ann_vol_VNQ_pct'] - FS['ann_vol_SPY_pct']:+.2f} |
| naive Sharpe（rf=0） | {FS['sharpe_VNQ_naive']:.3f} | {FS['sharpe_SPY_naive']:.3f} | {FS['sharpe_VNQ_naive'] - FS['sharpe_SPY_naive']:+.3f} |
| 全樣本 ρ(VNQ, SPY) | \\multicolumn{{2}}{{c}}{{ {FS['corr_VNQ_SPY_full']:.4f} }} | — |

VNQ 年化波動率 **高出 SPY {(FS['ann_vol_VNQ_pct'] - FS['ann_vol_SPY_pct']) / FS['ann_vol_SPY_pct'] * 100:.1f}%**（20.54% vs 17.75%），但年化報酬 **低 {FS['ann_ret_SPY_pct'] - FS['ann_ret_VNQ_pct']:.2f} 個百分點**（5.41% vs 12.69%）。naive Sharpe ratio 差距達 **{FS['sharpe_SPY_naive'] - FS['sharpe_VNQ_naive']:.3f}**（SPY 約為 VNQ 的 2.7 倍）。此為本研究樣本期間（2015-2026）的實證事實，需 caveat 樣本含 2020 COVID、2022-23 Fed 升息、2023-24 regional bank 壓力三個 REIT 特有衝擊事件，可能低估長期 risk-adjusted 表現。

### 發現二：ρ(VNQ, SPY) 強烈 regime-switching，COVID 期間 tail correlation 接近 1

滾動 63 日相關係數 $\\rho_t$ 的樣本分佈：

- **平均** {FS['mean_rolling_corr_63d']:.3f}（明顯低於全樣本 ρ = {FS['corr_VNQ_SPY_full']:.3f}）
- **區間** [{FS['min_rolling_corr_63d']:.3f}, {FS['max_rolling_corr_63d']:.3f}]
- **最小值 {FS['min_rolling_corr_63d']:.3f}** 出現在樣本早期（REIT 與股票市場短期解耦）
- **最大值 {FS['max_rolling_corr_63d']:.3f}** 出現在 COVID 崩跌前後（tail dependence 飆升）

子期間 ρ 對比：

| 期間 | N | VNQ 年化 vol (%) | SPY 年化 vol (%) | ρ(VNQ, SPY) |
|------|--:|-----------------:|-----------------:|------------:|
| COVID 崩跌（2020-02-19 ~ 2020-03-23） | {SUB['COVID_crash']['n']} | {SUB['COVID_crash']['ann_vol_VNQ_pct']:.2f} | {SUB['COVID_crash']['ann_vol_SPY_pct']:.2f} | **{SUB['COVID_crash']['corr_VNQ_SPY']:.4f}** |
| 後 COVID 平靜期（2021-06-01 ~ 2021-12-31） | {SUB['post_COVID_calm']['n']} | {SUB['post_COVID_calm']['ann_vol_VNQ_pct']:.2f} | {SUB['post_COVID_calm']['ann_vol_SPY_pct']:.2f} | {SUB['post_COVID_calm']['corr_VNQ_SPY']:.4f} |
| Fed 升息（2022-03-16 ~ 2023-07-26） | {SUB['Fed_hike_2022_23']['n']} | {SUB['Fed_hike_2022_23']['ann_vol_VNQ_pct']:.2f} | {SUB['Fed_hike_2022_23']['ann_vol_SPY_pct']:.2f} | {SUB['Fed_hike_2022_23']['corr_VNQ_SPY']:.4f} |

三項觀察：

1. **COVID 崩跌 ρ = {SUB['COVID_crash']['corr_VNQ_SPY']:.4f}** — VNQ 與 SPY 在 crisis 期間幾乎完全同向，tail dependence 現象典型（cf. Longin & Solnik 2001 的 extreme correlation 理論）。**REIT 在真正需要分散風險時失去分散能力**，此為 diversification breakdown 現象。
2. **平靜期 ρ 明顯降低**（0.648）— 2021H2 低波動率環境 VNQ 與 SPY 各自反映不同的驅動因子（REIT 受 cap rate / vacancy 影響、SPY 受盈利驅動），相關下降驗證 REIT 實物因子的存在。
3. **Fed 升息期間 ρ 再次升高至 0.797**，且 VNQ 年化報酬 −8.86% 遠差於 SPY +6.65%。此期間 VNQ 與 SPY 高度同向（驅動因子轉為共同的利率衝擊），但 VNQ 的 duration-like exposure 使其報酬被更嚴重壓縮。

![VNQ vs SPY 年化實現波動率]({url_rv})
*圖 1：VNQ（REIT）與 SPY 年化 22 日實現波動率時序（%）。灰色陰影為 COVID 崩跌，橘色陰影為 Fed 升息循環。VNQ 在 COVID 期間波動率飆至接近 100%（年化），大幅超越 SPY 同期的 76%。*

![VNQ-SPY 63 日滾動相關]({url_corr})
*圖 2：VNQ-SPY 63 日滾動 Pearson 相關係數。虛線為全樣本均值 0.724。可見 ρ 於 2018 接近 0.04 的低點、2020 COVID 接近 0.94 的高點、2022-23 Fed 升息維持 0.79 高位；明顯 regime-switching。*

### 發現三：HAR-RV 對 VNQ 與 SPY 的日頻方差預測能力在統計上無顯著差異（null result）

HAR-RV OOS 一步預測（Patton QLIKE 損失，愈低愈好）：

| 標的 | QLIKE | RMSE | $\\beta_0$ | $\\beta_d$ | $\\beta_w$ | $\\beta_m$ |
|------|------:|-----:|-----------:|-----------:|-----------:|-----------:|
| **VNQ** | {HAR['VNQ']['qlike']:.4f} | {HAR['VNQ']['rmse']:.3f} | {HAR['VNQ']['beta'][0]:.3f} | {HAR['VNQ']['beta'][1]:.3f} | {HAR['VNQ']['beta'][2]:.3f} | {HAR['VNQ']['beta'][3]:.3f} |
| **SPY** | {HAR['SPY']['qlike']:.4f} | {HAR['SPY']['rmse']:.3f} | {HAR['SPY']['beta'][0]:.3f} | {HAR['SPY']['beta'][1]:.3f} | {HAR['SPY']['beta'][2]:.3f} | {HAR['SPY']['beta'][3]:.3f} |

VNQ QLIKE **{HAR['VNQ']['qlike']:.4f}** 略低於 SPY **{HAR['SPY']['qlike']:.4f}**（比值 {HAR['QLIKE_ratio_VNQ_over_SPY']:.4f}，表面上 VNQ 可預測性**稍佳**），但 Diebold-Mariano 檢定：

$$t_{{\\mathrm{{DM}}}} = \\frac{{\\bar{{d}}}}{{\\mathrm{{SE}}(\\bar{{d}})}} = {DM['t']:.4f}, \\quad p = {DM['p_value']:.4f} \\quad (N = {DM['n']})$$

其中 $d_t = L_{{\\mathrm{{VNQ}}, t}} - L_{{\\mathrm{{SPY}}, t}}$ 為 QLIKE 差值序列。|t| = {abs(DM['t']):.3f} **遠小於 1.96 門檻**，**未能拒絕 $H_0$: 兩模型預測能力相等**。結論：

- **HAR-RV 對 VNQ 與 SPY 的日頻方差預測能力，在本樣本期與 OOS 設定下，沒有統計顯著差異**。
- REIT 雖然 unconditional vol 較高，但**條件 vol 的時間序列可預測性 與大盤一致**。
- HAR coefficient 對比： VNQ 的 $\\beta_w = {HAR['VNQ']['beta'][2]:.3f}$、$\\beta_m = {HAR['VNQ']['beta'][3]:.3f}$；SPY 的 $\\beta_w = {HAR['SPY']['beta'][2]:.3f}$、$\\beta_m = {HAR['SPY']['beta'][3]:.3f}$。兩者 weekly 係數接近，但 VNQ monthly 係數（0.129）明顯高於 SPY（0.065），暗示 REIT vol 有較長的持續性（longer memory），但此係數差異未轉化為統計顯著的 QLIKE 差距。

## 實務意義

1. **Portfolio 分散**：若投資人期待 REIT 在 crisis 期間提供分散能力，本研究樣本提供**反面證據**。COVID 崩跌 ρ = 0.94 與股票完全同向；Fed 升息 ρ = 0.80 且 REIT 報酬被 duration 效應嚴重壓縮。REIT 的分散價值主要體現在**平靜期**（ρ ≈ 0.65），但平靜期正是分散需求最低的時候。此與 Ang & Chen (2002)、Longin & Solnik (2001) 關於 diversification-breakdown 的發現一致。

2. **Vol targeting / risk parity 的含義**：既有平台 VT 策略若要納入 VNQ 作為第三資產（相較現有 K702 的 50/50 SPY/GLD baseline），需要**明確處理 regime-dependent correlation**。單一歷史 ρ 輸入會在 crisis 期間大幅低估 portfolio risk。建議採 DCC-GARCH 或 regime-switching correlation 建模；既有平台 copula 方法論（Lai et al. 2019 APFM 31(2)）可擴展到 VNQ-SPY 的 tail dependence 刻畫。

3. **HAR-RV 作為 REIT vol forecaster 的可用性**：null result 意味著既有的 HAR-RV / GJR-GARCH baseline 可直接套用到 VNQ，**不需要 REIT 專屬的 vol model**。此結論支持將 REIT 納入跨資產 vol prediction panel（延伸 K1145 系列的 pooled panel 架構到 4 市場），作為 universality 檢定的第四個 market。

4. **利率敏感度待深入**：Fed 升息期間 VNQ 年化報酬 −8.86%，遠低於 SPY +6.65%，但本研究未正式檢定 ΔFed-funds-rate 對 VNQ vol 的 Granger 因果或 factor exposure。後續實驗建議加入 FRED 的 DFF / DGS10 序列，建立 VNQ vol ~ rate shock 的 event-study 或 local projection 模型。

## 限制與穩健性

1. **Daily RV proxy 粗糙**：本研究以 $r_t^2$ 近似 daily realized variance，未使用 5-min intraday 資料。文獻（Andersen et al. 2003、Barndorff-Nielsen & Shephard 2004）已證明 5-min RV 在低 noise 情境下是更好的 σ² 估計量。本研究的 HAR-RV 係數與 QLIKE 數值會 systematically 低估可預測性。REIT ETF 的 tick-level 資料取得較股票主力 ETF 困難，為後續擴展瓶頸。

2. **單一 HAR-RV spec**：未比較 HAR-RV-J（含 jump）、HAR-RV-CJ（含 continuous-jump decomposition）、GJR-GARCH、EGARCH 等替代 spec。若延伸研究，應套用本平台現有的 A4f multiplicative GARCH / PRG Periodic GARCH 架構。

3. **無 lookahead 驗證**：HAR 回歸使用 `.shift(1)` 確保 $\\mathrm{{RV}}_{{t-1}}$ 進入 $\\mathrm{{RV}}_t$ 的預測；OOS 切分 train ≤ 2022-12-31, test 2023-01 開始，time ordering 嚴格遵守。code 可於 `experiments/k_reit_vol_article/compute_reit_vol.py` 復現（fixed seed=42）。

4. **樣本期涵蓋三個 REIT-specific 衝擊**：2020 COVID、2022-23 Fed 升息、2023 regional bank 壓力。可能 **系統性高估** REIT 波動率、**低估** REIT 長期 Sharpe。延伸至 2000-2015 前樣本期（需 IYR 替代 VNQ）可驗證此 sample-selection 效應。

5. **DM test HLN-unadjusted**：p = {DM['p_value']:.3f} 已遠大於 0.05，HLN small-sample 修正只會讓 p 值更大，不改變 null result 結論。若 $|t|$ 接近 1.96 時需補 HLN 修正。

6. **相關係數是 Pearson**：未檢驗 Kendall τ 或 rank correlation 對 outlier 的穩健性；COVID 極端點可能主導 ρ = 0.94 結果。

## 結論

本研究建立 VNQ（REIT）vs SPY（美股大盤）在 2015-01 ~ 2026-04 樣本的 vol dynamics baseline：**REIT 承擔 +15.7% 的波動率溢價，但獲得負的 risk-compensation**（Sharpe 僅 SPY 的 37%）；**regime-dependent correlation 強烈 switching**（COVID ρ = 0.94、升息 ρ = 0.80、平靜期 ρ = 0.65），在 crisis 期間 diversification 失效；**HAR-RV 的 OOS 方差可預測性與 SPY 無統計顯著差異**（DM t = {DM['t']:.3f}, p = {DM['p_value']:.3f}，null result）。

三項 open questions 供後續實驗擴展：

1. **REIT 波動率在 Fed 升息循環的 granular 反應**：建立 VNQ RV ~ ΔDFF / ΔDGS10 的 local projection 或 event study；比較與 TLT（bond duration）的反應一致性。
2. **DCC-GARCH / copula 對 VNQ-SPY regime-dependent correlation 的建模**：延伸本平台 copula 方法論（Lai et al. 2019）至 REIT，測試 hedging ratio 與 tail dependence 的顯著性。
3. **跨 REIT 分類（住宅 / 辦公 / 工業 / 零售 / 醫療）的 vol heterogeneity**：VNQ 是 market-cap weighted composite；VNQ 內部子 REIT ETF（e.g. MORT for mortgage REIT、REZ for residential、INDS for industrial）的 vol 與 correlation 行為可能顯著不同，值得獨立實驗。

---

*本文基於 `experiments/k_reit_vol_article/compute_reit_vol.py`（seed=42），結果見 `reit_vol_results.json`、`rv_22d.csv`、`rolling_corr_63d.csv`。數據來源：yfinance auto_adjust=False，期間 {META['period']}，樣本 {META['n_obs']:,} 個日頻觀測值。圖表：matplotlib 生成，上傳 Supabase Storage。延伸文獻：Corsi (2009) HAR-RV、Patton (2011) QLIKE、Longin & Solnik (2001) extreme correlation、Ang & Chen (2002) asymmetric correlations、Lai et al. (2019) APFM 31(2) copula hedging。*

*相關平台實驗：K702（50/50 SPY/GLD 最佳 Sharpe baseline）、K167（VIX VRP 跨資產地圖，未含 REIT）、K1145 系列（跨市場 pooled panel universality — REIT 為潛在第四 market）。*
"""

print(f"[info] article length: {len(content)} chars (Chinese-mixed counting)")
print(f"[info] roughly {len(content.split())} 'words' (whitespace split, low bound)")

# Publish
pub = Publisher()
article_id = pub.publish_milestone(
    title=title,
    description=content,
    phase="research",
    category="daily_article",
    audience="research",
    tags=[
        "REIT", "VNQ", "SPY", "波動率預測", "HAR-RV",
        "跨資產", "相關動態", "Fed 升息", "COVID", "diversification"
    ],
    proposer="Claude",
    status="draft",  # 非時效性 research，進 draft 池
)

print(f"\n[OK] Published draft article: id={article_id}")
print(f"      title='{title}'")
