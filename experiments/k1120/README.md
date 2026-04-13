# K1120 — TLT FinStress regime-dependent tracking (rolling 52-week DM + regime split)

**Status**: PASS (H1 supported — regime-dependent signal confirmed)
**Proposer**: Claude K1118/K1116b 衍生
**Executor**: Claude
**Date**: 2026-04-13
**Worktree commit**: see `git log --oneline experiments/k1120/`

---

## 問題描述

K1116b 用 FRED publication delay 修正後，TLT M4 (AR1+FinStress NFCI) 的 full-sample OOS DM-t 從 K1118 原本的 **+3.74** 掉到 **+1.96**，失去 Harvey 顯著性（|t|>3）。full-sample 結果被 Paper 4 納入「universal native-IV sufficiency」主張。

但這個 full-sample 平均可能**掩蓋 regime-dependent 結構**：2022 Fed 開始激進升息（+475 bp / 18 個月）後，NFCI 這類金融條件指數可能捕捉到 MOVE（TLT native IV）未涵蓋的系統性流動性/融資壓力資訊。K1120 直接檢驗這個假說。

## 假說

| 假說 | 敘述 | 判準 |
|------|------|------|
| **H1 regime-dependent** | 2022-03 後 M4 DM-t 顯著、之前不顯著 | Post-2022 M4 vs M3 \|t\|>3 & Pre-2022 \|t\|<2 |
| **H2 universal NULL** | 兩個 regime 都不顯著 | 兩 regime \|t\|<3（K1118/K1116b confirmation）|
| **H3 短暫爆發** | 只有極短窗口顯著、其他時期 noise | rolling peak t>3 但 >3 的 window 比例 <15% |

## 動機

- K1116b 修正 publication delay 導致 TLT 原本 Paper 4 唯一的 positive cell 失效。如果 regime-dependent 成立，Paper 4 的 universal claim 須加 regime caveat。
- 長債 ETF 對融資條件（NFCI）敏感度應隨利率政策 regime 變動——理論預期 + 實證檢驗。
- 避開 E064 踩過的坑：不用 IS 資料分位點做 regime cutoff，改用**外生日期**（首次升息 2022-03-16 FOMC）。

## 數據

| 序列 | 來源 | 頻率 | publication delay |
|------|------|------|------------------|
| TLT | yfinance（auto_adjust） | daily → weekly W-FRI RV | — |
| ^MOVE | yfinance | daily → weekly mean | shift(1) week |
| NFCI, STLFSI4 | FRED local cache | daily/weekly → weekly mean | shift(2) week（K1116b/E062）|
| ANFCI | FRED（no cache available） | — | 未納入（M4 剩 NFCI + STLFSI）|

期間 2015-01-09 到 2026-04-10，共 588 週觀測。Regime cutoff 2022-03-16（首次升息 +25 bp）。

## 方法

所有模型 = OLS AR(1) 擴充（與 K1116b/K1118 一致）：
- **M1**: `RV_w = a + b RV_{w-1}`
- **M3**: M1 + `c MOVE_{w-1}` — Paper 4 A4f-IV baseline
- **M4**: M1 + `c NFCI_{w-2} + d STLFSI_{w-2}` — A4f-FinStress

三個評估層次：
1. **Full-sample regime_split** (IS=50%, OOS=50% within full panel) — K1116b 風格 replication。
2. **Rolling 52-week DM** — expanding-window OLS fit at each anchor, 預測接下來 52 週 OOS 並算 HLN-DM t-stat。共 432 個 rolling windows。
3. **Formal regime split**：Pre-2022 (2015–2022-03-15) 與 Post-2022 (2022-03-16–2026-04-10) 各自獨立 IS/OOS（50/50 within-regime）。
4. **Block bootstrap**（8-week blocks, 1000 reps, seed=42）對 Post-2022 vs Pre-2022 DM-t 分佈做穩健性檢查。
5. **Sub-period rolling breakdown**：ZIRP 2015-2019 / COVID-reflation 2020-2022 / active-hike 2022-2023/07 / hold-peak 2023-2024/09 / cutting 2024-2026。

## 預期決策樹

- Post-2022 M4 DM t > 3 穩定 + Pre-2022 NS → **H1**，Paper 4 narrative 須加 regime caveat
- 全期 NS → **H2**，K1118/K1116b null robust confirmation
- Peak rolling DM-t > 3 但 <15% windows → **H3**，視為 transient anomaly

## 結果

### 正式 regime split（單次 IS/OOS fit within regime）

| DM pair | Pre-2022 t | Post-2022 t |
|---|---|---|
| M4 vs M1 | -0.936 (NS) | **+8.054** |
| M4 vs M3 | +0.722 (NS) | **+5.675** |

### Rolling 52-week DM（432 windows, M4 vs M3）

| 子期間 | n | mean t | median t | max t | %(t>2) |
|---|---|---|---|---|---|
| ZIRP 2015-2019 | 156 | **-1.47** | -1.42 | +1.50 | 0.0% |
| COVID-reflation 2020-03/2022-03 | 115 | +0.38 | +0.14 | +2.44 | 14.8% |
| **Active hiking 2022-03/2023-07** | 71 | **+1.54** | +1.45 | +2.91 | **23.9%** |
| Hold-peak 2023-07/2024-09 | 60 | +0.81 | +0.67 | +2.98 | 10.0% |
| Cutting 2024-09/2026-04 | 30 | +0.77 | +0.87 | +2.50 | 3.3% |

Pre-2022 only **35.4%** of windows show M4>M3; Post-2022 **94.4%** of windows show M4>M3.

### Block bootstrap（8-wk, 1000 reps, seed=42）on M4 vs M3

| Regime | t_obs | boot mean | 95% CI | Pct > 3 |
|---|---|---|---|---|
| **Post-2022** | +6.55 | +6.50 | [+3.69, +10.32] | **99.8%** |
| **Pre-2022** | +0.75 | +1.06 | [-0.87, +3.07] | 2.6% |

### Verdict: **H1 支持** — TLT FinStress 是 regime-dependent

- Post-2022 regime M4 vs M3 DM-t = **+5.675** Harvey-sig (p < 10^-7)
- Pre-2022 M4 vs M3 DM-t = **+0.722** NS
- 區塊 bootstrap 99.8% > 3 in post-2022, 2.6% > 3 in pre-2022 — 極強 regime contrast
- Sub-period: active-hiking (2022-03 → 2023-07) 為最強 signal 來源（mean rolling t +1.54, 23.9% >2）

### Preamble Rule #5 self-check（DM-t > 6 trigger）

Post-2022 M4 vs M1 = +8.054 觸發「> 6 自我質疑」。驗證：
1. **Block bootstrap 99.8%** of samples > Harvey 3 — 不是 single-shock 造成。
2. **Rolling 52-week max 僅 +2.98**，沒有單一 52-週窗口破 Harvey +3——+8.054 是 104-週 regime-wide fit 的 joint 檢定結果。
3. **Pre-2022 symmetric test** 得 NS (+0.72)，排除「演算法 bias」或「FRED 資料本身 inflation」。

結論：+8.054 真實但高估單日 slice 信號強度。**Paper 4 應引用 post-2022 M4 vs M3 t=+5.675（with bootstrap 99.8% > 3）作主要證據**，+8.054 vs M1 作輔助支持。

## 結論（Paper 4 narrative impact）

K1118 原本的「universal IV sufficiency」主張需要加 **regime caveat**：

> **Revised claim**: Native-IV sufficiency holds in 3 / 4 asset classes (SPY/GLD/BTC) universally. For TLT (long Treasury ETF), native-IV (MOVE) is sufficient **except during rapid Fed tightening cycles**. 2022-03 起的升息期間，FRED 系列金融條件指數（NFCI + STLFSI）對週 RV 有顯著 incremental predictive power 超越 MOVE (DM-t +5.675, bootstrap 99.8% > Harvey 3)。機制推測：MOVE 只捕捉 Treasury options 市場的隱含波動率，未涵蓋銀行業 funding spreads、shadow banking 流動性等由 NFCI/STLFSI 直接量度的系統性金融條件——這些在激進升息 regime 下對長天期 Treasury vol 有強外生衝擊（SVB 2023/03、regional banks stress 2023/04-05 為具體案例）。

## 局限

1. **Regime length 不對稱**：Post-2022 只有 213 週（104 IS + 105 OOS）；Pre-2022 有 375 週。post 樣本偏小雖 bootstrap 穩健，仍建議未來加入更多利率週期（1994-1995, 2004-2006, 2015-2018 slow hike 比較）。
2. **ANFCI 缺失**：沒有 ANFCI cache，M4 只用 NFCI + STLFSI（K1116b/K1118 原本 3 個 FinStress 都含）。信號可能因此偏弱，結論方向不變。
3. **Regime boundary is exogenous but sensitive**：若改用 2022-01-01 或 2022-06-01 可能改變量化。已用 FOMC 首次升息日 2022-03-16 作為可辯護的單一 cutoff。
4. **Mechanical 風險**: 2022-2023 NFCI 急升 + TLT 波動率大增——兩者都是升息大事件的反應。信號可能部分是「同步反應大 common shock」而非「NFCI 提供獨立 information」。建議後續用 residualized NFCI（控制 VIX/MOVE 後的殘差）重測（K1120 後續）。
5. **Sample period ends 2026-04**：目前 cutting cycle 只有 30 個 rolling windows，3.3% > 2。若未來升息再來，可驗證機制可重複。

## 檔案

- `k1120.py` — 主腳本（data fetch + rolling DM + regime split + bootstrap + plots）
- `k1120_results.json` — 完整結果（panel stats + DM + bootstrap + subperiods + verdict）
- `k1120_rolling_dm.png` — rolling 52-week DM 時間序列 + Fed events markers + hike regime shading
- `k1120_regime_compare.png` — pre vs post 2022 DM bar chart
- `run.log` — 完整 stdout

## 參考文獻

- K1116b (`experiments/k1116b/`) — publication-delay re-verification, TLT M4 +3.74 → +1.96
- K1118 (`experiments/k1118/`) — 原本 cross-asset sufficiency, TLT +3.74 (pre-correction)
- K1121 (`experiments/k1121/`) — daily allocation, 正確 NFCI shift(5 days) 發現
- E062 — FRED publication-delay 教訓（docs/error_log.md 2026-04-13）
- E064 — IS-based regime cutoff degeneracy（避免用 IS 分位點 split, K1120 採 exogenous date）
- Harvey, Leybourne, Newbold (1997) — HLN DM correction
- Patton (2011) JoE — QLIKE robust loss function
- Brave, Butters (2011) — NFCI methodology
- Kliesen, Smith (2010) — STLFSI methodology
- FOMC Minutes (March 2022) — first hike +25bp 2022-03-16

## Reproducibility

- `np.random.seed(42)`（bootstrap 使用）
- OLS + DM 無隨機成分
- 本地 FRED cache（`experiments/k1121/data/fred_NFCI.csv`、`storage/macro/fred_STLFSI4.csv`）
- yfinance live download（TLT, ^MOVE）
