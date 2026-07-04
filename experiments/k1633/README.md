# K1633 — 「VIX 破 30/40 就是抄底訊號」投資迷思驗證

**類型**：投資迷思驗證系列（老闆 TG msg154 directive）／事件研究
**主題**：恐慌極值（VIX 首次穿越 30 / 35 / 40）進場後，SPY 的前瞻報酬勝率與分布，是否真的優於「隨機進場」的無條件 baseline？

---

## 動機

散戶常說「VIX 破 30（甚至 40）就是恐慌極值，閉著眼睛買就對了」。這句話把兩件事混在一起：

1. **底層漂移**：SPY 長期本來就上漲，任何一天進場、放夠久，勝率天生就 > 50%。
2. **恐慌溢酬**：在別人最恐慌時進場，是否還能**額外**贏過隨機進場？

本實驗把兩者拆開：用**同一套前瞻報酬定義**，比較「VIX 穿越門檻後進場」與「無條件（每一天都當起點）進場」的差距，並用重疊窗口穩健的推論方法檢定這個差距是否顯著。

## 資料

- **來源**：yfinance `^VIX`（Close，指數點位）+ `SPY`（Close，`auto_adjust=True` 已還原股息/分割）
- **期間**：1993-01-29 .. 2026-07-02（8,413 個交易日）
- **快取**：`data/vix_full.csv`、`data/spy_full.csv`（首次執行自動抓取後快取）

## 方法

- **事件定義**：VIX 由下往上**首次穿越**門檻（`v[t-1] < thr <= v[t]`）。
- **去叢集（de-cluster）**：一次 panic 會在門檻附近反覆震盪，只有距離上一個已接受事件 **≥ 20 交易日** 才算新事件。
- **進場與前瞻報酬**：
  - lag0（主）：訊號日收盤進場，`fwd = SPY[t+H]/SPY[t] − 1`。
  - lag1（穩健性）：隔日收盤進場（`signal.shift(1)`），`fwd = SPY[t+1+H]/SPY[t+1] − 1`。
  - 只保留前瞻窗口完整落在樣本內的事件（無未來函數 / 無 lookahead）。
- **門檻 × horizon**：門檻 {30, 35, 40} × horizon {5, 10, 20, 60} 交易日 = 12 個 cell。
- **Baseline**：無條件前瞻報酬（每一交易日都當起點，**同樣的 H、同樣的價格序列、同樣的報酬定義**）。
- **推論（重疊窗口穩健，K1355 教訓）**：
  - 主推論：Newey-West/HAC 回歸 `fwd ~ const + event_dummy`，`maxlags = H`（涵蓋重疊自相關）；係數 = 事件均值 − 非事件均值。
  - 穩健性：定態 block bootstrap（期望 block 長度 = H ≥ horizon）+ random-entry placebo（抽 N 個隨機起點 5,000 次建 null 分布）。
- **Seed**：SEED=1629；每個 cell 用 `SEED + H + thr` 派生獨立 seed，完全可復現。

## 事件數（去叢集後）

| 門檻 | 事件數 | 期間 |
|---|---|---|
| VIX ≥ 30 | 50 | 1997-10 .. 2026-03 |
| VIX ≥ 35 | 25 | 1997-10 .. 2025-04 |
| VIX ≥ 40 | 17 | 1998-08 .. 2025-04 |

> ⚠️ 門檻 35 / 40 的事件數偏小（25 / 17），單一 cell 的推論力有限，須連同多重檢定一起看，不可單挑最漂亮的 cell 下結論。

## 主要結果（lag0，excess = 事件均值 − baseline 均值）

| cell | excess | win_vs_base | HAC p | 5% 顯著 |
|---|---|---|---|---|
| thr30_H5 | +1.26% | +11.2pp | 0.0068 | ✓ |
| thr30_H10 | +0.65% | +2.1pp | 0.372 | |
| thr30_H20 | +1.34% | +10.6pp | 0.085 | |
| thr30_H60 | +2.55% | +2.1pp | 0.036 | ✓ |
| thr35_H5 | +0.99% | +17.2pp | 0.253 | |
| thr35_H10 | +0.89% | +6.1pp | 0.410 | |
| thr35_H20 | +1.84% | +10.6pp | 0.207 | |
| thr35_H60 | +4.89% | +12.1pp | 0.0089 | ✓ |
| thr40_H5 | +1.59% | +17.7pp | 0.153 | |
| thr40_H10 | −0.04% | +2.8pp | 0.973 | |
| thr40_H20 | +1.63% | +11.1pp | 0.484 | |
| thr40_H60 | +6.19% | +16.4pp | 0.019 | ✓ |

**baseline 無條件勝率**（SPY 天生上漲）：H5 58.8%、H10 61.9%、H20 65.4%、H60 71.9%。

## 綜合（多重檢定，BH-FDR — 已內建於 `k1633.py`，寫入 `verdict.multiple_testing`）

- 12 個 cell 中 **11 個** excess 為正 → 方向幾乎一致（買恐慌 > 隨機進場，方向上真實）。
- raw 5% 顯著 4 個：`thr30_H5`、`thr30_H60`、`thr35_H60`、`thr40_H60`（集中在門檻 30 的短天期，以及三門檻共同的 **H60 三個月天期**）。
- **Benjamini-Hochberg FDR 5%：無任何 cell 個別存活**（最小 p 值群距門檻僅一線之差）。
- **FDR 10%：3 個存活**（`thr30_H5`、`thr35_H60`、`thr40_H60`）。
- 穩健性（lag1 隔日進場 + block bootstrap placebo）：門檻 30 的 H5 / H10 / H60 placebo 單尾 p = 0.0 / 0.041 / 0.016，**跨進場時點與推論方法一致存活**；門檻 35 / 40 則因樣本小而脆弱。

## 誠實結論（myth_verdict = half_true / qualified）

「VIX 破 30/40 是抄底訊號」**部分成立、但與散戶想像不同**：

1. **不是「立刻反彈」**：短天期（H5/H10）除了門檻 30 之外多半不顯著。散戶「破 30 隔幾天就彈」的直覺，證據薄弱。
2. **真正穩定的是「3 個月的反轉溢酬」**：H60 在 30/35/40 三門檻全顯著、且**恐慌越深、溢酬越大**（+2.55% → +4.89% → +6.19%），這是最耐看的 pattern。
3. **大半是底層漂移**：baseline 勝率本就很高（H60 已 71.9%），「抄底」多數是搭上 SPY 長期上漲的順風車，恐慌帶來的**增量**優勢真實但不大。
4. **統計上脆弱**：拉多重檢定後（FDR-5%）個別 cell 都不再顯著；方向一致性（11/12 正）比任何單一 cell 的星號更值得相信。

一句話：**恐慌時進場能小幅贏過隨機進場，但贏的是「三個月的耐心」，不是「三天的反彈」；而且門檻越極端、樣本越少、越不能單靠一個數字說話。**

## 檔案

- `k1633.py`：完整可復現腳本（BH-FDR 多重檢定已內建，`python k1633.py` 一鍵重現全部結果）
- `k1633_results.json`：per-cell（含 `bh_qvalue` / `bh_fdr_5pct` / `bh_fdr_10pct`）+ baseline + lag1 穩健性 + `verdict.multiple_testing`（script 產生的 BH-FDR 綜合）
- `fig1_forward_path.png`：事件後平均 SPY 路徑 vs baseline
- `fig2_winrate.png`：各門檻×horizon 勝率 vs baseline
- `fig3_dist60.png`：H60 前瞻報酬分布（事件 vs baseline）
- `data/`：VIX / SPY 快取

## Review

- **Codex review（primary path，2026-07-05）**：整體 **CONDITIONAL_PASS**。核心方法論 PASS（無 lookahead、HAC maxlags=H 正確、de-cluster 正確、seed 固定、小樣本已揭露）；Codex 獨立重算 BH-FDR 與本檔綜合完全吻合。原 must-fix：BH-FDR 未內建於 code → 已修（本次內建，`python k1633.py` 自足重現）；bootstrap CI 為 event-order 次要推論、主推論為 HAC → 已於 `config.bootstrap_ci_note` 明示；lag1 excess 對 lag0 baseline 的近似 → 已於 `config.lag1_baseline_note` 明示。
- **注意**：`mean_boot95` 與圖表 CI band 是事件序列的 block resampling（次要/診斷用）；overlap-robust 的主推論是 HAC（Newey-West，maxlags=H），見 K1355。

## 復現

```bash
cd experiments/k1633 && python k1633.py
```

## 防錯與方法論對照

- **無 lookahead**：進場點 = 訊號日（或隔日）收盤，前瞻報酬只量之後；lag1 變體確認非同收盤 artifact。
- **Baseline 同口徑**：同 H、同價格序列、同報酬定義。
- **重疊窗口（K1355）**：HAC maxlags=H + block bootstrap block≥H，不把重疊 asset-day 當 iid。
- **多重檢定**：12 cell 不把 raw 5% 當 confirmed，補 BH-FDR 綜合。
- **小樣本揭露**：門檻 40 僅 17 事件，明確標註推論力限制。
- **Seed 固定**：SEED=1629，per-cell 派生 seed。

## 相關 K

- K1355（跨資產/重疊窗口 pooled inference 不可當 iid）
- 投資迷思驗證系列其他 K（美股大跌台股補跌、黃金避風港、開盤第一小時最危險等）
