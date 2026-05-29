# Codex 24h Review — mile_55b0f69f (K1382)

- **Article**: 銀行法規說用「平方根法」估一個月風險，但它真的失準了嗎？SPY 十年數據給出一個不舒服的答案
- **Reviewed**: 2026-05-29 20:00 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **CONDITIONAL_PASS**

## Findings

1. **`k1382_results.json` 的摘要欄位數字寫錯，provenance 已分裂。**  
   腳本硬編碼 `summary.main_finding` 為 `GARCH-Sim (ratio=1.048, p=0.799)`，但同檔詳細結果、文章正文、以及實際月期 `h=21, alpha=1%` 統計都是 `ratio=0.94, p=0.7486`。[experiments/k1382/k1382.py:316]( /Users/yhlai0911/Desktop/volpred-research/experiments/k1382/k1382.py:316 )、[k1382_results.json]( /Users/yhlai0911/Desktop/volpred-research/experiments/k1382/k1382_results.json:1 )、[feed.json]( /Users/yhlai0911/Desktop/volpred-research/storage/reports/feed.json:76 ) 三者不一致。若後續摘要生成、knowledge sync 或文章改寫吃 `summary.main_finding`，會把錯數字再擴散。

2. **文中對 HistSim 失敗原因的機制敘述超過 artifact 可證範圍。**  
   文章把 `2015-2019` 月期 HistSim ratio `3.97` 解釋成「2009-2014 低波動樣本讓歷史分布太平靜、尾部被壓縮過頭」；但實驗 artifact 只有 sub-period exception 統計，沒有做 rolling-window 組成分析、counterfactual window 比較、或任何可直接支持這個因果說法的檢驗。[feed.json]( /Users/yhlai0911/Desktop/volpred-research/storage/reports/feed.json:76 ) 這段應降級成合理推測，而不是寫成已驗證原因。

3. **「月期讓兩個方法的誤差結構趨近，差距統計上消失」有過度宣稱。**  
   實驗有做的是各方法各自的 Kupiec coverage test；沒有做 `GARCH-Sim` vs `SRT` 的直接差異檢定，也沒有對兩者 exception-rate difference 給 paired / bootstrap / DM 類型比較。文章可描述為「月期兩者 coverage 都通過、數字接近」，但「差距統計上消失」比證據更強。[feed.json]( /Users/yhlai0911/Desktop/volpred-research/storage/reports/feed.json:77 )

## What Holds

- **Lookahead**：代碼用 `train_data = returns.iloc[:t_idx]`，實際損益用 `returns.iloc[t_idx:t_idx+h].sum()`，前視偏差檢查通過。[k1382.py]( /Users/yhlai0911/Desktop/volpred-research/experiments/k1382/k1382.py:161 )
- **核心 headline 數字**：文章主表中的 `h=1/5/10/21` exception ratio、`h=21` 的 `0.94 / 1.08 / 5.03` 與 Kupiec p 值，均可在 `k1382_results.json` 對上。
- **研究三件套**：K1382 有 README / script / results.json，基本可重現性存在。

## Recommended Fix

1. 修 `k1382.py` / `k1382_results.json` 的 `summary.main_finding`，改成從詳細結果程式化生成，不要手寫數字。
2. 將文章中 `2015-2019 HistSim 為何失敗` 那段改成 **推測 / 可能原因** 口吻，或補一個專門的 window-forensic 實驗再保留強說法。
3. 把「差距統計上消失」降級成「兩者月期 coverage 都通過、數字接近」，除非補上直接方法比較檢定。

## Bottom Line

這篇不是 `FAIL`。核心結果大致有 artifact 支撐，lookahead 也沒看到問題。  
但它還不能算乾淨 `PASS`，因為 provenance 摘要欄位已寫錯，且幾段機制解釋比實驗本身更強。最合理狀態是 **保留 draft/published 皆可，但要儘快做 errata 級修文**。
