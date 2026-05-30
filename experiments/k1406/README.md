# K1406 — 投資時機策略 conditional block bootstrap

## 問題與動機

兩個散戶最常爭論的「投資時機」問題，用真實資料 + conditional block bootstrap 給出 VolPred 自己的可復現證據，供兩篇讀者向文章引用：

- **Group A — 定期定額(DCA) vs 單筆投入(Lump Sum)**：同一筆固定資金，要一次全投，還是分 12 期慢慢投？
- **Group B — 持續投入(Stay-invested) vs 逢低買進(dip-buying)**：每期有現金，要立即投入，還是囤著等回檔再進場？

兩個待驗證命題：

- **命題 A**：總報酬率上 Lump Sum 通常勝（本金在市場的時間更長）；但以 **IRR（money-weighted，資金效率）** 衡量，兩者本質接近相等。
- **命題 B**：囤現金等回檔通常**輸**給持續投入 —— 閒置現金的 cash-drag 成本大於擇時利益，即 **time in market > timing**。

## 資料

| 資產 | 來源 | 跨度 | 交易日數 |
|---|---|---|---|
| SPY | yfinance（auto-adjust 收盤價） | 2005-01-03 ～ 2026-05-29 | 5,385 |
| 0050.TW | yfinance（auto-adjust 收盤價） | 2009-01-02 ～ 2026-05-28 | 4,257 |

- 資料涵蓋 2008 金融海嘯、2020 COVID 崩盤、2022 升息空頭等多次完整空頭，bootstrap 母體充分。
- 0050.TW yfinance 實際自 2009-01 起有資料（早於此無連續收盤）。
- **Fallback 機制**：若執行時 yfinance 不可用（DNS/network），腳本自動改用 `experiments/k1090/data/{SPY,0050.TW}.csv`（2018–2024，含 2020 崩盤 + 2022 空頭，但樣本期較短、bootstrap 母體有限）。`k1406_results.json` 的 `data` 欄位會標明實際來源（`yfinance_live` / `yfinance_cached` / `fallback_k1090`）；本次產出為 `yfinance` 真實長樣本。

## 方法

- **Conditional block bootstrap**：circular block bootstrap，block = 20 交易日（保留波動聚集/自相關），`np.random.default_rng(SEED)`，**SEED = 20260530**。
- **Horizon**：1 年（252 交易日）+ 3 年（756 交易日）。
- **Regime 分類**：每條 bootstrap 路徑依「全路徑年化報酬」分三類：
  - 純多頭 `bull`：年化 > +10%
  - 純空頭 `bear`：年化 < −10%
  - 中性 `neutral`：其間
  - 各 regime 至少累積 ≥ 500 條路徑（不足則加跑批次），每資產每 horizon ≥ 2,000 條（實際 4,000–26,000 條）。
- **Group A 指標**：終值/總報酬率、IRR（money-weighted）、各 regime + 整體勝率。
- **Group B 指標**：終值/總報酬率、勝率、平均閒置現金時間比例（cash drag）、「等不到回檔」case 比例；回檔門檻測 5% / 10% / 15% 三組。
- **IRR**：對現金流序列（投入為負、終值為正）以 `scipy.optimize.brentq` 在安全範圍 (−0.5, +0.5) 掃描 sign-change 求每期（每交易日）IRR，再年化。grid-scan 較慢，故 IRR 只對每 horizon 前 2,000 條路徑計算（`n_irr` 欄位記實際有效樣本）；**FV 勝率/報酬/cash-drag 用全 bootstrap 樣本**。
- **公平比較**：兩策略同資金、同期間、同一條 bootstrap 路徑（paired comparison，降低 sampling noise）。

## Lookahead 防錯（最高風險）

- **Dip-buying 觸發**：rolling high 用 `high_lag[t] = max(prices[max(0,t-W):t])`，**切片不含 `prices[t]`**（W=63 交易日 ≈ 3 個月），等同 `.shift(1)`，決策只用 **t-1 及更早**價格。觸發當日以 `prices[t]`（當期可觀察收盤價）投入囤積現金，屬合法執行價、非未來資訊。
- **DCA / Lump Sum**：投入時點外生固定（day 0, 21, 42, …），完全不依賴價格或未來資訊，無 lookahead。
- 已記取 `docs/error_log.md` 多次 lookahead 教訓（K547/K562/K222 family：`weights × same-day ret` 同期 pattern）。本實驗無權重×同期報酬結構，唯一時序敏感點是 dip 觸發，已 lag-correct。

### 執行時點假設（Codex review 明示）

Dip-buying 在 day `t` 觀察到回檔（rolling high 只用 t-1 及更早）後，**以同日 `prices[t]`（收盤價）成交**。這是「收盤觀察、收盤可交易」假設（與本平台 PRG/PRS 系列一致），**非跨日 lookahead**：`high_lag[t]` 完全不含未來資訊，`prices[t]` 是當期可下單的執行價。若要更保守（訊號 t 觀察、t+1 成交），可改 `signal@t → execute@t+1`，但對「dip-buying 整體輸 fixed」的結論方向預期不變（延後一日只會略增 cash drag）。Codex 二審 verdict = **CONDITIONAL_PASS**（無硬性跨期 lookahead 或 paired-comparison bug，唯一 caveat 即此執行時點假設，已於此明示）。

## 結果摘要

> 整體與各 regime 勝率、IRR、cash-drag 數字皆來自 `k1406_results.json`，由 `k1406.py` 一鍵重跑可復現。

### Group A — Lump Sum 終值勝率（%，各 regime）

| 資產×Horizon | 純多頭 | 中性 | 純空頭 | 整體 | IRR 年化中位差(Lump−DCA) |
|---|---|---|---|---|---|
| SPY 1y | 96.9% | 56.1% | 9.2% | **74.1%** | +0.03pp |
| SPY 3y | 85.7% | 59.5% | 28.6% | **73.4%** | +0.02pp |
| 0050 1y | 95.6% | 53.0% | 8.5% | **74.1%** | −0.79pp |
| 0050 3y | 85.1% | 61.3% | 51.5% | **74.7%** | +0.53pp |

- **總報酬率：Lump Sum 整體約 74% 勝率穩定壓過 DCA** —— 多頭情境近乎必勝（本金越早全進、在市場時間越長越有利）；空頭情境反轉（DCA 延後投入避開早期崩跌），印證「Lump 贏在 time-in-market 而非擇時」。
- **IRR（資金效率）四個 cell 年化中位差皆落在 |0.8pp| 內**，整體（跨 cell 中位）僅約 **+0.03pp**，IRR 勝率約 50%（接近 coin-flip）。資金效率本質接近相等：DCA 終值低不是因為「效率差」，而是平均投入時間短、暴險時間少。

### Group B — Dip-buying（逢低買進）vs Fixed（持續投入）

| 資產×Horizon | 門檻 | dip 勝率 | 平均閒置現金時間(cash drag) | 等不到回檔比例 |
|---|---|---|---|---|
| SPY 1y | 5% / 10% / 15% | 49.0% / 43.2% / 35.1% | 25.7% / 61.9% / 83.5% | 1.5% / 29.9% / 65.3% |
| SPY 3y | 5% / 10% / 15% | 48.8% / 42.9% / 36.9% | 6.6% / 26.9% / 56.3% | 0.0% / 2.5% / 25.4% |
| 0050 1y | 5% / 10% / 15% | 46.4% / 41.5% / 36.1% | 18.5% / 53.7% / 77.6% | 0.2% / 20.6% / 54.8% |
| 0050 3y | 5% / 10% / 15% | 46.1% / 41.6% / 39.4% | 4.6% / 20.4% / 46.9% | 0.0% / 0.8% / 15.3% |

- **逢低買進在所有門檻、所有資產、所有 horizon 的勝率皆 < 50%**，且門檻越深（要求回檔越大）勝率越低、cash drag 越重、「等不到回檔」比例越高。
- 10% 門檻代表值：dip 勝率約 41–43%、平均約 20–62% 的現金生命週期處於閒置、短 horizon 下高達 ~30% 路徑整段「等不到回檔」（資金乾等、完全沒投到）。
- **囤現金等回檔的擇時利益，被閒置現金的 cash-drag 成本壓過 —— time in market > timing 成立。**

## Verdict

| 命題 | Verdict | 關鍵數字 |
|---|---|---|
| **A**：總報酬 Lump 勝、IRR 兩者近似相等 | **confirmed** | Lump 整體終值勝率 74.1%（>55%）；IRR 年化中位差 +0.0003（< 2pp） |
| **B**：囤現金等回檔輸持續投入（time > timing） | **confirmed** | 10% 門檻 dip 勝率 42.3%（<50%）；平均閒置現金時間 40.7%；等不到回檔 13.4% |

## 檔案

- `k1406.py` —— 完整可重跑腳本（資料載入 + bootstrap + 兩 group 計算 + IRR + 出圖）。重跑：`uv run python experiments/k1406/k1406.py`
- `k1406_results.json` —— 所有數字（各 group × 資產 × horizon × regime 的勝率/中位終值比/IRR/cash-drag）+ verdicts
- `data/{SPY,0050.TW}.csv` —— yfinance 快取（首次執行寫入，之後重跑直接讀快取確保可復現）
- `figures/`
  - `fig_a_dca_vs_lump_winrate.png` —— DCA vs Lump 各 regime 終值勝率 bar
  - `fig_b_dca_vs_lump_dist_irr.png` —— 終值報酬率分布 + IRR 資金效率 violin 對比
  - `fig_c_dip_vs_fixed_winrate_drag.png` —— Dip-buying（各門檻）勝率 + cash-drag
  - `fig_d_dip_dist_never.png` —— Dip-buying 終值分布 + 「等不到回檔」比例

## 限制

- Bootstrap 路徑是對歷史日報酬的重組，保留 block 內的自相關但打散 block 間的長期 path-dependence；regime 標籤依「實現年化報酬」事後定義，是描述性切分而非可交易訊號。
- DCA 期間固定 12 期×~21 交易日；不同 DCA 排程（週/雙週/不同期數）數值會變，但 Lump 在多頭佔優、IRR 近似相等的結論為結構性，預期穩健。
- 未計交易成本與稅；對 DCA（多次小額買入）相對不利、對 Lump（單次）相對有利，計入成本只會強化命題 A 的方向，不會反轉。
- IRR 以子樣本（每 horizon 2,000 條）估計以控制計算成本；FV 勝率/cash-drag 用全樣本。
