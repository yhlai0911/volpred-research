# K1683 — Leveraged-fund Treasury futures crowding 能預測債市風險嗎？

> 狀態：完整執行、cache 重現與數字驗證已完成。所有數字以 `k1683_results.json` 為準。

## Data & Methodology

- **方法論類型**：empirical public-proxy diagnostic；不是因果識別。
- **公開資料**：CFTC Traders in Financial Futures（Futures Only）、FRED DGS10，以及 Yahoo Finance 的 TLT、IEF、ZN=F、SPY adjusted closes。
- **理想資料**：SEC Form PF 的 fund-level Treasury cash／derivatives／repo／margin／risk-limit exposure。這些機密資料沒有可下載的精確月序列；Fed 2026 圖表只作動機，沒有從圖形反推數字。
- **公開 proxy**：CFTC `Leveraged Funds` 四個核心期限（2Y／5Y／10Y／Bond）的 gross contract participation：`(long + short + 2×spread) / (2×open interest)`，再把 expanding-z level 與 13 週變化等權平均。
- **名稱限制**：Leveraged Funds 也包含 CTA、CPO 與其他 managed funds；這不是 hedge-fund AUM、basis-trade 規模、DV01 或 fund concentration。

## Differentiation

既有 `k_repo_basis_funding_stress_gate_duration_2026_06_14` 已把 SOFR／EFFR／TGCR 與 10Y／Bond leveraged short share 合成 stress proxy，對 TLT／IEF／ZN 次週 RV 得到 verified NULL。本題不重跑相同 composite：移除 funding，改測四期限 gross participation，並把 yield jump 與 SPY–TLT correlation break 納入預先指定的主結果。

## Timing and lookahead policy

CFTC position 是 Tuesday close snapshot，通常 Friday 15:30 ET 發布。歷史 API 的日期是 report date，不是 publication date。主訊號先對齊名義 Friday release，再明寫 weekly `.shift(1)`；因此 Friday close 的 forecast 只用前一份 report。2013 與 2018–19 政府停擺的 catch-up report windows 排除。所有市場 targets 都從 forecast origin 後第一個交易日開始，expanding training 只接受 `target_end_date < forecast_origin` 的 label。

## Pre-registered tests

四格 primary family：

1. TLT next-5-trading-day RV，QLIKE。
2. IEF next-5-trading-day RV，QLIKE。
3. DGS10 next-5-day最大絕對 bp jump，log-model 的 level MSE。
4. SPY–TLT next-20-day correlation Fisher-z，MSE。

ZN=F next-5-day RV 因 continuous-futures roll artifact，只作 sensitivity。各模型先用 260 週 initial train、逐週 expanding re-estimation；augmented 模型只比 matched baseline 多一個 crowding signal。四個 HLN-DM p-values 一次做 BH-FDR。Cell gate 要同時滿足：loss improvement > 0、DM t < −3、BH q < 0.05、crowding association coefficient > 0，且 early／late OOS improvement 同號為正。

## Results

CFTC 四合約資料共 **4,192 列**，report span 為 2006-06-13 至
2026-07-07；經 expanding scaling、publication blackout 排除與 weekly
lag 後有 **899 個 signal origins**。市場價格為 2006-01-03 至
2026-07-10。四格 expanding OOS 各有 **630–637 週**，起點約在 2013-09，
每格 timing audit 均確認所有 training target end 早於 forecast origin。

| Cell | OOS n | baseline loss | augmented loss | 改善率 | HLN-DM t | BH q | early / late 改善 | 通過 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| TLT RV5 | 637 | 0.305192 | 0.300912 | +1.4026% | -1.2701 | 0.5635 | +2.9803% / -0.5407% | 否 |
| IEF RV5 | 637 | 0.314674 | 0.313108 | +0.4979% | -0.5780 | 0.5635 | +1.1878% / -0.2985% | 否 |
| DGS10 jump5 | 636 | 12.822682 | 12.856699 | -0.2653% | +0.6871 | 0.5635 | +0.2939% / -0.6615% | 否 |
| SPY–TLT corr20 | 630 | 0.182410 | 0.184854 | -1.3396% | +0.9859 | 0.5635 | +0.8872% / -2.6680% | 否 |

TLT 與 IEF 全期 loss 有小幅改善，但 DM 不顯著，且 late-OOS 都轉為
惡化；yield jump 與 stock-bond correlation 直接惡化。四格 **0/4** 通過，
verdict 為 `NULL_NO_ROBUST_INCREMENT`。Roll-sensitive ZN=F sensitivity 也只有
+0.2831% 改善（DM t=-0.5507，p=0.5820），不改變結論。

公開 CFTC proxy 從 2023-01-03 的 0.24063 增至 2025-09-30 的 0.30101，
變化為 **+25.0946%**；這與 Fed Form PF 報告的美元 gross exposure 翻倍並不
矛盾，因為兩者單位、母體與涵蓋部位完全不同。Cache-only 重跑在移除
`run_utc` 後得到相同 canonical JSON SHA-256。

這個 null 只能說：保守 release lag 下，CFTC category-level futures crowding
沒有為這四個 weekly risk targets 提供穩健增量預測力。它不能推論
forced-deleveraging 機制不存在，因為 public proxy 沒有 cash／repo／margin／
risk-limit shock，也沒有 fund-level concentration。

## Reproduction

```bash
uv run python experiments/k1683/k1683.py --refresh
uv run python experiments/k1683/k1683.py
```

必要產出：`k1683.py`、`k1683_results.json`、`README.md`、`data/*.csv` pinned inputs、兩張 PNG 與 review artifacts。

## References

- Monin, P. J. (2026). *Decomposing Hedge Funds’ U.S. Treasury Exposures*. FEDS Notes. DOI: 10.17016/2380-7172.4082.
- Kruttli, M. S., Monin, P. J., Petrasek, L., & Watugala, S. W. (2025). *LTCM Redux? Hedge fund Treasury trading, funding fragility, and risk constraints*. Journal of Financial Economics, 169, 104017. DOI: 10.1016/j.jfineco.2025.104017.
- Glicoes, J., Iorio, B., Monin, P., & Petrasek, L. (2024). *Quantifying Treasury Cash-Futures Basis Trades*. FEDS Notes. DOI: 10.17016/2380-7172.3458.
- Avalos, F., & Sushko, V. (2023). *Margin leverage and vulnerabilities in US Treasury futures*. BIS Quarterly Review.
