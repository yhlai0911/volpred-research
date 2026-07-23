# first-Friday proxy 全庫 sweep — 交件（assign_23b2a961）

狀態：**已完成（非 partial）**。完成驗證 2026-07-19 14:10（台灣時間），二次驗證 8 個 README 警語均在。
改動：只加 8 個封存實驗 README 警語，無代碼變更、無 commit、未動 paper/** 與 storage/**。
canonical accessor max()→min()+cadence gate 修復（commit 305d118a3）已知悉；遷移建議照舊指向 `nfp_release_dates`，不受影響。

## 1. 站點全量清單（真 NFP first-Friday proxy，9 處）

| # | 檔案:行號 | 用途 | proxy 寫法 | 分類 | 處置 | blast radius |
|---|---|---|---|---|---|---|
| 1 | experiments/k528/k528_nfp_event_study.py:44-58 | 主 NFP event study | get_first_friday / generate_nfp_dates | 封存 | README 警語 | feed×7 |
| 2 | experiments/k741/k741_nfp_event_study.py:42-51 | NFP event study | days_until_friday=(4-d.weekday())%7 | 封存 | README 警語 | **論文源** + feed×7 + knowledge×7 |
| 3 | experiments/k259/k259_macro_surprise.py:160-189 | macro surprise | generate_nfp_dates | 封存 | README 警語 | knowledge×4 |
| 4 | experiments/k661/k661_nfp_vol_analysis.py:71-98 | NFP vol analysis | get_first_friday(monthdatescalendar) | 封存 | README 警語 | feed×2 + knowledge×7 |
| 5 | experiments/k513/k513_macro_event_vol.py:160-165 | macro event vol | days_until_friday | 封存 | README 警語 | 盲區補抓 |
| 6 | experiments/k773/k773_event_risk_budgeter.py:100-107 | event risk budgeter | get_nfp_dates(while !=4) | 封存 | README 警語 | 盲區補抓 |
| 7 | experiments/k820/k820_event_risk_budgeter.py:160-165 | event risk budgeter | days_until_friday | 封存 | README 警語 | 盲區補抓 |
| 8 | experiments/k1608/k1608.py:247 | 電影注意力衝擊（次要 covariate） | nfp_proxy_week=any(weekday==4 & day<=7) | 封存 | README 警語 | knowledge×10 |
| 9 | experiments/k904/k904_paper8_shock_nfp_fix.py:415-424 | Paper8 S4 重製 | days_until_friday | paper(c) | **不動，report-only** | feed×2 + 論文 reproduction |
| — | paper/volatility-absorption/experiments/{k741,k904}*.py | 論文內副本 | 同上 | paper | 不動（scope） | — |

改動檔案（8）：experiments/{k528,k741,k259,k661,k513,k773,k820,k1608}/README.md

## 2. 盲區聲明

- 實際 8 支 > brief 預期 6 支。第一輪 pattern（first.friday | weekday()==4）漏 k513/k773/k820，因它們寫 days_until_friday=(4-weekday())%7（無字面 ==4）或 while weekday()!=4。多 pattern 補掃（days_until_friday / while !=4 / monthdatescalendar / nonfarm-payroll 檔名掃）才補齊。
- 已排除的非 NFP 週五站點（逐一確認）：k1703 / k1354 / k631 / scripts/experiment_vix_seasonality.py = 第三個週五(OpEx)；k_trending_index_inclusion_vol / K1341 = Russell(六月最後週五)/S&P 季度再平衡；K1609 = 一般週五抽樣 filter；src/volpred/ops/summaries.py:597 = 週報週五到期；k235/k873/k743/k577/k684/k563/k598/research_buyback_blackout_vol = 一般週五 dummy。scripts/_legacy/write_nfp_articles.py = 純 prose、不計算日期（_legacy/）。experiments/event_article_nfp_2026_07_03_t1/ = 已正確（用 canonical nfp_release_dates，"No proxy and no fallback"）。
- 未掃：(a) 只掃 *.py，未掃 .ipynb / tex 硬編日期列表；(b) 以「Friday idiom + NFP token」為錨，若某檔用完全不同 idiom 算 NFP 且鄰近無 NFP 字樣會漏；(c) 本次僅掃 NFP，但 k259/k513/k820/k773 同時帶 CPI(~13號)/FOMC 日曆 proxy（同 error class），已在警語點名但完整 CPI/FOMC sweep 未做。
- 無 category-(a) 活躍代碼：9 站點全是 one-shot 封存實驗，無一被 live pipeline import/引用；live 端（populate_upcoming_events.py、event_article）早已用 canonical。故零代碼修改、零 syntax check。

## 3. k904 論文影響分析（category c，主線程裁決）

論文：paper/volatility-absorption/（main.tex / main_v2.tex / main_v3.tex，v3 為最新 7/14）。

- **修正 brief 假設**：論文 NFP 表格真正 source 是 **k741 而非 k904**。main_v3.tex:391 字面註解 `% source: experiments/k741/k741_nfp_event_study_results.json .part_a_historical (n_nfp=195, n_non_nfp=3909)`。k904 是佐證 reproduction（n_nfp=196，數字一致）。兩者都用 first-Friday proxy。
- 只有 k904 的 task_s4_nfp 用 proxy；task_s2_shock_types（|ΔVIX|>2 分類）不碰 NFP 日期 → S2/shock-type 數字乾淨。
- 受污染數字（main_v3.tex，與 k741 part_a_historical 逐位吻合）：
  - Abstract(L43/L72) + Results(L368-396) + Table tab:nfp(L375-391)
  - Overall：1.14× vs 全非NFP(p=0.081)、1.16× vs 週五(p=0.061)、N_NFP=195、2010–2026（= k741 ratio_vs_all=1.145 / ratio_vs_friday=1.165 / p=0.081/0.061）
  - 分 regime：Low(<15) 1.24×(t=1.85,p=0.069,n=62)｜Medium(15-20) 1.30×(p=0.009)｜Elevated(20-25) 1.18×(p=0.279,n=27)｜High(≥25) 0.95×(p=0.777,n=28)｜Wilcoxon p=0.0037
  - 舊版 main.tex/main_v2.tex 用 1.17×（main.tex p=0.037）— 同 proxy 血緣、較早 framing。
- 嚴重度：論文已把 NFP 定位為 SAR 主分析的補充/方向性證據（main_v3:398 "absorption hypothesis does not depend on the NFP result alone"）並帶「無 surprise control」caveat → proxy 不觸及 headline SAR 貢獻；但每個 NFP 數字（overall + 4 regime ratio + 全部 p/n）都建在污染日期上，改用 canonical nfp_release_dates 重跑後會位移，方向/幅度需實跑（超出 scope）。
- 建議：投稿前用 canonical nfp_release_dates 重跑 k741(+k904 S4)，再決定 main_v3 NFP 表 + abstract 數字是否更新；k528/k661 的 feed 文章（feed×7/×2）數字同屬回溯範圍（本 task 未動 storage/reports）。
