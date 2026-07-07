# K1656 — 淨成本波動率目標：no-trade band 與訊號平滑

**Verdict: CONDITIONAL_PASS**（reviewer: `feature-dev:code-reviewer` subagent fallback — Codex 用量達上限至 2026-07-11）

**一句話結論**：降低 VT 再平衡換手率的淨效益**完全取決於市場的交易成本水準** — 在低成本美股 (SPY)，no-trade band / 訊號平滑 / 日曆再平衡對**淨** Sharpe 全無顯著改善（皆 p>0.49，確認 K48/K125）；在高成本台股 (TAIEX，含證交稅)，換手率減半以上可**顯著**提升淨 Sharpe（best plain band +0.061, p=0.003；訊號平滑+band 組合 +0.143, p=0.028），但 plain no-trade band 並非最優手段 — 日曆月頻、rebalance-to-edge、平滑+band 在同等或更低換手率下都做得更好。

---

## 1. 研究動機與差異化

波動率目標 (VT) 策略以日度再平衡追蹤目標波動率，實務痛點是高換手率（本實驗 20 日 vol 規格下年化 ~1,100%），扣掉交易成本後淨 Sharpe 被侵蝕。2025-26 的實務與學術熱點（FMPM 2025 optimal rebalancing boundary、Leland no-trade region）主張加入**再平衡帶寬 (no-trade band)** 降低換手。

**與內部 prior art 的差異化**：

| 既有 K | 覆蓋 | 本實驗補的空缺 |
|---|---|---|
| **K48** (Rebalancing boundary) | **月頻** 12/VIX 策略，boundary 減 turnover 但 net Sharpe 改善不顯著 | K48 打的是本就低換手的月頻策略；本實驗打**日頻 VT**（換手率的真痛點），band 邊際效益理論上更大 |
| K499 / K220 / K230 | rebalance frequency（calendar）最優頻率 | 把 no-trade band 與 calendar 再平衡做 **turnover-matched** 對照，回答「band 是否為更好的降 turnover 手段」 |
| K604 / K625 | 台股成本水準（K604「13x」被 K625 更正為高估） | 用**第一原理**成本（證交稅只課賣出，追蹤 Δw 符號做非對稱成本），避開高估陷阱 |
| K125 | 美股散戶 VT「成本可忽略」 | 量化「可忽略」的邊界：低成本市場成立，高成本台股不成立 |

核心貢獻：**毛 (gross) vs 淨 (net) Sharpe 並列**，band 各檔一列，雙市場對照，把「換手率下降幅度 → 淨 Sharpe 改善」的因果鏈用正式檢定量測。

---

## 2. 資料

| 項目 | SPY (美股) | TAIEX (台股 proxy) |
|---|---|---|
| 來源 | yfinance `SPY`，`auto_adjust=False` 的 `Adj Close`（總報酬） | yfinance `^TWII`（TAIEX 指數）|
| 有效樣本期 | 2011-07-29 ~ 2026-07-07 | 2011-07-29 ~ 2026-07-06 |
| 樣本數 | 3,755 交易日 | 3,640 交易日 |
| OOS 空頭覆蓋 | 2020 COVID、2022 熊市 | 2020 COVID、2022 熊市 |

**資料品質事件（已抓已修，研究誠實紀錄）**：原計畫用 `0050.TW` ETF，但 yfinance 的 `0050.TW` Adj Close 在 **2014-01-02 有 -75% 的假象斷裂**（37.41→9.33 且不回補），整段 post-2014 序列被錯誤縮放（2024 顯示 45 vs 真實 ~180），`repair=True` 亦修不好。此壞點在 2x 槓桿下使淨日報酬 <-100%、equity 走負、CAGR=nan、且污染 baseline Sharpe（污染版台股 net Sharpe 0.12 → 清乾淨後 0.53）。**修法**：棄用 `0050.TW`，改用乾淨的 `^TWII` TAIEX 指數當台股 proxy（投資載具仍為 0050 ETF，故套用 ETF 交易成本），並在 `load_prices()` 加入 `|日報酬| > 30%` 的資料品質 guard，未來 bad tick 會直接 raise 而非靜默污染。

> **口徑註記**：SPY 用 Adj Close（含息總報酬）、TAIEX 用價格指數（不含息，約低估 3-4%/yr 股息）。因此**跨市場絕對 Sharpe 不可直接比較**；本實驗的核心結論是**市場內部**「band/平滑 vs baseline」的再平衡規則比較，該比較對股息漂移近似不變（股息對所有變體施加近乎相同的漂移）。

---

## 3. 方法

### 3.1 VT 策略規格（baseline 與所有變體共用）
- 波動率估計：20 日 rolling realized vol，年化 ×√252。**明確 `.shift(1)`** → 決策日 t 只用 returns[t-20..t-1]。
- 目標權重：`w_target[t] = clip(0.15 / vol_ann[t], 0, 2.0)`（目標波動率 15%、槓桿上限 2.0）。
- 現金腿報酬設 0（baseline 與變體一致，comparison 內差不受影響）。

### 3.2 時序（無 lookahead）
`w_held[t]`（第 t 日持有權重）決策於 t 日開盤前，用：(a) `w_target[t]`（vol ≤ t-1）、(b) `w_drift[t]`（前日權重與 `r[t-1]` 漂移）。當日賺 `w_held[t]·r[t]`，成本在再平衡當日扣。決策**完全不觸及 `r[t]`**。權重漂移公式（單一風險資產+現金）：`w_drift = wp(1+rp)/(1+wp·rp)`。

### 3.3 變體
| 變體 | 規則 |
|---|---|
| baseline_daily | 每日全再平衡回 target |
| band_{5,10,15,20} | \|target − drift\| > band 才再平衡回 target（no-trade band, task spec）|
| band_edge_{5..20} | 同上但只再平衡到帶寬**近邊**（Leland 2000 最優）|
| smooth21 | 對 w_target 做 21 日 MA 後每日再平衡 |
| smooth21_band_{5..20} | 平滑 + band 組合 |
| calendar_weekly / monthly | 週頻 / 月頻再平衡（**turnover-matched 對照**）|

### 3.4 成本（per unit one-way turnover \|Δw\|，追蹤買賣方向）
- **美股 SPY**：買賣對稱 2.5 bp（= 5 bp round-trip）。robustness：5 bp one-way（10 bp round-trip）。
- **台股 0050 ETF**：手續費 0.1425% × 0.6（6折電子下單）= 8.5 bp 單邊；**證交稅 0.15% 僅賣出課徵** → 買入 8.5 bp、賣出 23.5 bp。`cost_of_trade` 依 Δw 符號套非對稱成本。

### 3.5 統計檢定
淨 Sharpe 差（變體 vs baseline）用 **stationary block bootstrap**（Politis-Romano, block=10, B=5,000, seed=1656），成對重抽每日淨報酬，回報 point diff、95% percentile CI、two-sided p（centered distribution）。**邊界不一致時以 p 值為準**（percentile CI 已知在邊界 anti-conservative；如 TAIEX band_20 CI 排除 0 但 p=0.064）。

---

## 4. 結果

### 4.1 SPY（低成本，5 bp round-trip）

| 變體 | turnover% | gross Sh | **net Sh** | cost drag | net Δ vs base | p |
|---|---|---|---|---|---|---|
| baseline_daily | 1105.0 | 0.9075 | **0.8906** | 0.0169 | — | — |
| band_5 | 934.9 | 0.9090 | 0.8948 | 0.0143 | +0.0042 | 0.491 |
| band_10 | 794.5 | 0.9025 | 0.8905 | 0.0121 | −0.0002 | 0.992 |
| band_15 | 700.0 | 0.8998 | 0.8892 | 0.0105 | −0.0014 | 0.927 |
| band_20 | 628.2 | 0.9019 | 0.8924 | 0.0095 | +0.0018 | 0.950 |
| band_edge_20 | 398.2 | 0.9175 | 0.9117 | 0.0058 | +0.0211 | (未測)† |
| smooth21 | 487.3 | 0.8583 | 0.8516 | 0.0067 | −0.0391 | 0.599 |
| calendar_monthly | 486.3 | 0.9154 | 0.9087 | 0.0066 | +0.0181 | 0.813 |

**SPY 全部變體 vs baseline 淨 Sharpe 差皆不顯著（p ≥ 0.49）**。cost drag 僅 ~0.017 Sharpe（成本太小），故降 turnover 淨無所得；訊號平滑甚至**傷害**淨 Sharpe（延遲空頭降險，gross 0.858 < baseline 0.908）。† rebalance-to-edge 未跑對 baseline 的 bootstrap，但 +0.021 的點估計在 SPY 這種低成本下方向對但幅度小。

### 4.2 TAIEX（高成本，買 8.5bp / 賣 23.5bp）

| 變體 | turnover% | gross Sh | **net Sh** | cost drag | net Δ vs base | p |
|---|---|---|---|---|---|---|
| baseline_daily | 1110.5 | 0.6371 | **0.5303** | **0.1068** | — | — |
| band_5 | 904.0 | 0.6451 | 0.5582 | 0.0870 | +0.0279 | **0.000** \*\*\* |
| band_10 | 751.3 | 0.6541 | 0.5822 | 0.0719 | +0.0519 | **0.000** \*\*\* |
| band_15 | 588.3 | 0.6474 | 0.5915 | 0.0560 | +0.0612 | **0.003** \*\*\* |
| band_20 | 520.8 | 0.6220 | 0.5730 | 0.0490 | +0.0427 | 0.064 \* |
| band_edge_20 | 282.3 | 0.6760 | 0.6504 | 0.0256 | +0.1201 | (未測)† |
| smooth21 | 385.7 | 0.6741 | 0.6391 | 0.0350 | +0.1088 | 0.054 \* |
| **smooth21_band_20** | **228.4** | 0.6941 | **0.6735** | 0.0206 | **+0.1432** | **0.028** \*\* |
| calendar_monthly | 420.0 | 0.6957 | 0.6586 | 0.0371 | +0.1283 | 0.054 \* |
| calendar_weekly | 681.1 | 0.6395 | 0.5753 | 0.0643 | +0.0450 | 0.133 |

**TAIEX cost drag 高達 0.107 Sharpe**（turnover 1110% × 非對稱稅 → 年化成本 ~1.8%/yr）— 是 SPY 的 6 倍以上，故降 turnover 淨效益顯著。注意 **gross Sharpe 也隨降頻上升**（0.637→~0.70），代表日頻再平衡有一部分在交易 noise，降頻同時省成本+濾雜訊。

### 4.3 Turnover-matched 對照（band vs calendar 在同等換手率）

- **SPY**：band 與 calendar 在同 turnover 水準下淨 Sharpe 差異微乎其微（band 較 weekly +0.003~+0.008），無一顯著 → **兩種降 turnover 手段等價且皆無淨效益**。
- **TAIEX 關鍵誠實發現**：
  - plain band_15（588% turnover, net 0.5915）勝週頻（681%, 0.5753）— band 換手更低且淨更高。
  - **但 calendar 月頻（420% turnover, net 0.6586）勝所有 plain band**（最佳 band_15 僅 0.5915）且換手更低；band_20（521%, 0.573）在 turnover-matched 下**輸**月頻 −0.086。
  - **plain no-trade band 不是最優降 turnover 手段** — 月頻日曆、rebalance-to-edge（Leland）、訊號平滑+band 在同等或更低換手率下淨 Sharpe 都更高。呼應 K48（band 降 turnover 但非贏家）與 K499（高成本下月頻最優）。

### 4.4 成本敏感度（SPY 10 bp round-trip）
baseline net 0.8738、band_edge_20 0.9058、calendar_monthly 0.9021 — 成本翻倍後降 turnover 的淨效益略增（drag 0.034→edge 0.012）但仍屬小幅，模式不變 → **確認 SPY 結論對成本假設穩健**。

### 4.5 圖表
- `fig1_gross_vs_net_sharpe.png` — 毛 vs 淨 Sharpe by band width（兩市場）
- `fig2_turnover_curve.png` — 換手率隨 band width 下降曲線
- `fig3_turnover_matched_scatter.png` — 淨 Sharpe vs turnover 散點（band vs calendar vs baseline）

---

## 5. 結論（誠實、market-conditional，不過度宣稱）

1. **降 VT 換手率的淨效益 ∝ 市場交易成本**。低成本美股 (SPY)：no-trade band / 平滑 / 日曆再平衡對淨 Sharpe **全無顯著改善**（p ≥ 0.49），甚至平滑有害 → 確認 K48（daily VT 亦然）與 K125（美股成本可忽略）。
2. **高成本台股 (TAIEX，含證交稅)**：換手率減半以上**顯著**提升淨 Sharpe。plain band_5/10/15 皆 p<0.01；最佳可行策略為**訊號平滑 + 20% band**（淨 Sharpe 0.674 vs baseline 0.530，+0.143, p=0.028），換手率從 1110% 降至 228%（−79%）。
3. **plain no-trade band 非最優**：即便在台股，月頻日曆、rebalance-to-edge（Leland）、平滑+band 在 turnover-matched 下都勝過 plain band → no-trade band 有效但不是降 turnover 的最佳實作。
4. **對 K604/K625 的呼應**：台股成本（尤其證交稅）確實主導，是唯一讓再平衡紀律產生顯著淨價值的市場；美股則否。

---

## 6. 侷限
- **Turnover 絕對水準取決於 vol window（20 日）**：更長窗（如 60 日）會大幅降低 baseline 換手率；相對結論（band 降 ~50%、淨效益的市場條件性）對窗長穩健，但絕對數字不可外推到別的 vol 規格。
- **TAIEX 為價格指數**（不含息），與 SPY 總報酬口徑不同；跨市場絕對 Sharpe 不可直比，市場內比較才是主結論。
- **成本為固定比例模型**，未含 market impact / 滑價 / 借券成本；槓桿部位（w>1）未計融資利差（baseline 與變體一致，差不受影響）。
- **6 折手續費為假設**；更深折扣會縮小台股 cost drag，但賣出證交稅 0.15% 為法定下限，台股 > 美股的定性結論不變。
- rebalance-to-edge 未對 baseline 跑 bootstrap（僅 point estimate）；下一步可補。

---

## 7. 文獻
1. **Bai et al. (2025)** "Target volatility strategies: optimal rebalancing boundary for transaction cost minimization", *Financial Markets and Portfolio Management*, DOI 10.1007/s11408-025-00486-5.
2. **Leland, H. (2000)** "Optimal Portfolio Management with Transaction Costs and Capital Gains Taxes" — no-trade region 理論；最優為再平衡到帶寬**邊界**（非回 target），turnover 減 ~50%。
3. **Fleming, Kirby, Ostdiek (2003)** "The Economic Value of Volatility Timing Using Realized Volatility", *JFE*.
4. **Moreira & Muir (2017)** "Volatility-Managed Portfolios", *Journal of Finance*.
5. 內部 **K48**（月頻 12/VIX boundary：turnover 降但 net Sharpe 不顯著）、**K499**（高成本下月頻最優）、**K604/K625**（台股成本主導、13x 高估更正）、**K125**（美股散戶 VT 成本可忽略）。

---

## 8. 復現
```bash
cd experiments/k1656
python3 k1656.py          # 需 yfinance / pandas / numpy / scipy / matplotlib
# 產出：k1656_results.json + fig1/2/3.png；資料快取於 data/（首次執行自動下載）
# seed=1656 固定；bootstrap B=5000 block=10
```
- 三件套：`README.md` / `k1656.py` / `k1656_results.json` + 3 張圖 + `data/` 快取。
- 資料品質 guard：任何 |日報酬| > 30% 直接 raise（防 bad tick 靜默污染）。
