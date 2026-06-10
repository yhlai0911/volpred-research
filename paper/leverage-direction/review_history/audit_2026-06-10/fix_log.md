# leverage-direction 審查修正 log（2026-06-10，主線程 fable-5）

決策：採 K903 canonical 全文一致化（abstract 既有方向）。SUBMISSION FROZEN 直到 reproduce gate green。

## HIGH（6/6 處置）

| # | Finding | 處置 |
|---|---------|------|
| 1 | 核心結果自相矛盾（Intro/§4.2/§5 殘留 −5.79/93%） | ✅ Intro L11 重寫（K903 +0.002/t=+0.15/67%、regime-dependent 敘事）；L134 重寫；L154-156 HAC/bootstrap 段重寫（刪 bootstrap CI 句 — 舊 vintage 無 K903 對應）；L157 non-overlap 檢查 gold 區間標 earlier-draft vintage 並把 gold 主張完全錨定 regime 分解；L161-162 的 93%→67%（K903）+ 刪 2025-26「100% negative/−0.089」（K903 無 sub-period 資料可驗證） |
| 2 | L134 腳註「不同物件」說法不實 | ✅ 腳註改寫：承認 K903 同規格 canonical replication、SIGN REVERSED（引 k903_vs_paper_diff.md）、全文採 K903 |
| 3 | Table 3 八列 legacy | ✅ 全表 9 列換 K903（experiments/k903/tables/k903_table3.csv，加 % source 註）；L144 敘事重寫（QQQ 2025 p=0.086 非 0.023；GLD 23-24 GARCH 顯著勝 p=0.001 如實報告）；L188 QQQ natural-experiment 弱化為 illustrative |
| 4 | BTC 分類規則矛盾 | ✅ 明確區分單窗 t vs quarterly-mean HAC t；BTC 標 GJR/Borderline（Table 2 Model Choice 欄改）；9/9 改「prescribed model is never significantly beaten」判準 + BTC borderline 揭露（Intro/abstract/§4.3.2 三處一致）；L200 的 γ>0.08 改 [0.12,0.17] band |
| 5 | Reproduce gate 過期 amber | ⚠️ 殘項：reproduce.py expected values 對齊新表後重跑 — 需 compute（已列 next step；gate green 前維持 FROZEN） |
| 6 | ρ=0.944 p<0.001 錯一數量級 | ✅ 3 處（L13/L249/L270）改 p=0.016 + L249 加「formal inference 以 N=14 為準」；L407/L513/abstract 無 p 值不需改 |

## MEDIUM（部分處置）

- 門檻三版漂移 → ✅ 統一 t>1.65 主規則 + [0.12,0.17] band（Intro/L198/L200）
- −3.8% vs −0.59% 尺度混用 → ✅ L214/L453/tab:var_ortho 註腳標 centered vs quasi-LL + canonical p=0.003
- tab:var_ortho 9 vs 10 violations vintage → ✅ L214 加 vintage-sensitivity 腳註（K802 9/502 p≈0.11 Green Zone）
- 「two channels」數目 → ✅ 改 three channels
- 樣本期間口徑（§3.1） → ⚠️ 殘項（需補 §3.1 期間總表段）
- hood2025/nelson2025/xu2024 citation 可疑 → ⚠️ 殘項（citation-verifier / web 查證後決定 Contribution 2 錨點）
- tab:vt 統一窗重算 + ρ=0.944 統一窗版 → ⚠️ 殘項（需重算，與 reproduce 重跑同批）
- multiple-testing 區分 t>3 vs 名目 5% → ⚠️ 殘項
- BH FDR audit 無溯源 → ⚠️ 殘項（補 K 實驗或刪句）

## LOW

- unused bibitems → ⚠️ 殘項；experiments.md 表號 mapping 更新 → ⚠️ 殘項

## 殘項 next steps
1. reproduce.py 對齊 + 重跑 → green（解凍前提）
2. citation 三條查證
3. tab:vt 統一窗重算（compute_queue）
4. §3.1 期間總表、multiple-testing 段、BH 溯源、bib 清理
