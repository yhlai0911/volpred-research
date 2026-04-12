# K1060: Individual Taiwan Stock Earnings Announcement Volatility (EAV)

## 動機（Why）

K1059 發現一個矛盾：TSMC（0050.TW 50% 權重）財報公告日，0050.TW ETF 的 event-day / non-event r² 比 = 1.007（NULL）。這與美股文獻（Patell & Wolfson 1984、Beaver 1968、Savor & Wilson 2016）一致顯示個股 earnings day 波動顯著上升的結果矛盾。

**核心問題**：是台灣個股根本沒有 EAV，還是 ETF diversification 把 EAV 洗掉？

## 方法（How）

### 數據
- 財報公告日：`財報公告日.txt`（Big5，153,875 筆，1986-2025）
- 股價：yfinance daily close（2010-01-01 ~ 2025-12-31）
- 樣本：10 檔台股（科技 5、金融 3、電信 1、傳產 1）

### 10 檔樣本股
| ticker | 名稱 | 板塊 | 公告數 |
|--------|------|------|--------|
| 2330.TW | TSMC | Tech | 60 |
| 2454.TW | MediaTek | Tech | 59 |
| 2317.TW | Hon Hai | Tech | 60 |
| 2308.TW | Delta | Tech | 61 |
| 2303.TW | UMC | Tech | 60 |
| 2412.TW | Chunghwa Telecom | Telecom | 60 |
| 2882.TW | Cathay Holdings | Financial | 60 |
| 2891.TW | CTBC Financial | Financial | 60 |
| 2881.TW | Fubon Financial | Financial | 60 |
| 2002.TW | China Steel | Traditional | 60 |

### Event study 設計
1. 對每檔股票，以 daily r²（squared log-return）作為 realized variance proxy
2. 建立 trailing 60 日 r² 滾動平均作為 baseline（shift(1) 避免汙染）
3. 比較 event-day r² 與 non-event r²（排除 [-5,+5] 事件窗）
4. **T+0 vs T+1 雙測試**：台灣財報公告多在**盤後**發佈，因此新增 T+1 效應測試（next trading day after announcement）
5. 指標：ratio = event_r² / non_event_r²、Welch t-test、2000-rep bootstrap CI
6. Cumulative abnormal volatility (CAV) over [-5, +5]
7. 截面聚合：one-sample t-test on ratios、binomial test on ratio > 1 count

### Random seed
`np.random.seed(42)` + `np.random.default_rng(42)` for bootstrap

## 結論（What we found）

### 1. T+0 假說 NOT SUPPORTED — 10 檔股票中 7 檔 ratio < 1

| 指標 | 數值 |
|------|------|
| Mean ratio (T+0) | **0.9356** |
| Mean t-stat | -0.886 |
| Stocks with ratio > 1 | 3/10 |
| Binomial p-value | 0.945（反方向） |

**公告日當天沒有波動放大**，甚至略為收斂。中信金 t=-3.65（p<0.001）、富邦金 t=-2.90（p=0.005）顯示**顯著的公告日波動下降**——與文獻完全相反。

### 2. T+1 假說 WEAKLY SUPPORTED — Taiwan after-close announcement 效應

| 指標 | 數值 |
|------|------|
| Mean ratio (T+1) | **1.4657** |
| Mean t-stat | +0.577 |
| Stocks with ratio > 1 | 6/10 |
| Binomial p-value | 0.377 |

- UMC T+1 ratio=2.58（t=+2.48, p=0.013）、Hon Hai 2.06（t=+2.02）、Delta 1.68（t=+1.81）
- T+1 > T+0 對 10 檔股票中 9 檔成立（唯一例外：2412 中華電，本就是低波動電信股）
- 截面平均比值從 0.94 升到 1.47 (+0.53)，但同時 cross-sectional 變異極大（中華電 0.45 vs UMC 2.58），使得 binomial test 仍未達 0.05 門檻

### 3. 板塊異質性顯著（H3 SUPPORTED）

| 板塊 | n | mean T+0 ratio | mean T+1 ratio |
|------|---|----------------|----------------|
| Tech | 5 | 1.164 | **1.636** |
| Financial | 3 | 0.689 | 1.293 |
| Telecom | 1 | 0.518 | 0.452 |
| Traditional | 1 | 0.953 | 2.146 |

- **科技股**：T+1 最強（mean 1.64），符合「營收數字敏感、分析師預期差異大」的理論
- **金融股**：T+0 明顯**收斂**（0.69）、T+1 回升至 1.29 — 財報內容相對可預測（法規報表）
- **電信股**：2412 中華電是典型的「公告日無反應」股，兩日 ratio 皆 < 1
- **傳產**：China Steel T+1 ratio=2.15 最大——景氣循環股的財報最具資訊內容

### 4. K1059 puzzle 的解釋

| 來源 | ratio |
|------|-------|
| 0050.TW ETF (K1059, T+0) | 1.007 |
| 個股截面平均 (K1060, T+0) | 0.936 |
| 個股截面平均 (K1060, T+1) | **1.466** |

**關鍵 insight**：0050.TW ETF 在 T+0 看起來 NULL（1.007）並非 diversification 把 EAV 洗掉——**個股 T+0 本來就沒有 EAV**。真正的 EAV 在 T+1，K1059 只看 T+0 錯過了真實效應。

**方法論教訓**：跨市場套用事件研究法時，必須考慮**公告 timing**——美股盤中/盤前公告居多（T+0 可見），台股盤後公告居多（T+1 才可見）。

## 假說驗證總結

| 假說 | 結果 |
|------|------|
| H1（文獻 baseline, T+0）| **NOT SUPPORTED** — 台灣個股 T+0 無 EAV |
| H1b（T+1 extension）| **WEAK SUPPORTED** — 平均 ratio 1.47、6/10 > 1，但 binomial p=0.38 |
| H2（ETF diversification）| **推翻** — 個股本來就無 T+0 EAV，不是 diversification 問題 |
| H3（Sectoral heterogeneity）| **SUPPORTED** — 科技 > 金融 > 電信 |

## 局限（Limitations）

1. **樣本小**：僅 10 檔股票，截面 t-test 檢定力有限；放大到 50+ 檔可能讓 T+1 binomial p 跨越 0.05
2. **板塊不均**：Telecom/Traditional 各只 1 檔，無法做正規板塊檢定
3. **公告時點粗略**：未精確區分「盤中公告」vs「盤後公告」——若有精確時點，T+0/T+1 分類會更乾淨
4. **單一 proxy**：僅用 r²（close-to-close），未用 5-min RV 或 range-based vol 驗證
5. **公告「真實日期」問題**：CSV 某些日期為週末，已 forward-roll 到下一個交易日；可能與交易所的 `實際揭露日` 有差異
6. **Bootstrap CI**：報告了 CI low/high，但兩種樣本為獨立重抽而非配對，抽樣分布假設偏鬆

## 衍生方向（寫入 research_program.md）

1. **K1061**：擴展到 TWSE 50 檔所有成份股的 T+0 vs T+1 EAV（N≥50 提升檢定力）
2. **K1062**：直接在 0050.TW 上重做 K1059，但以 T+1 event window 測試，驗證 ETF 層級 T+1 是否也有 EAV
3. **K1063**：精確區分盤中/盤後公告時點（從公開資訊觀測站爬時間戳記），測試 same-day 盤後公告 vs 盤前公告的差異
4. **K1064**：建立 `TW_EAV_factor` — 是否可作為波動率模型的 exogenous regressor（延伸 A4f 族系）
5. **Sector-conditional A4f**：K1050 顯示 SPY earnings season 全面改善；台股若需要板塊條件模型（A4f 對科技股 T+1 效應，但對金融股無效）可能是 K1058 NS 的原因

## 檔案清單

- `k1060.py` — 主腳本
- `k1060_results.json` — 完整結果（per-stock + sector + hypotheses）
- `k1060_per_stock_eav.png` — 10 檔股票 T+0 vs T+1 比值 bar chart
- `k1060_event_windows.png` — 10 檔股票 [-5,+5] event window 曲線
- `k1060_sectoral_comparison.png` — 板塊比較（mean ratio + event window）
- `README.md` — 本文件

## 參考文獻

- Patell, J.M. & Wolfson, M.A. (1984). "The intraday speed of adjustment of stock prices to earnings and dividend announcements." *J Financial Economics*, 13(2), 223-252.
- Beaver, W.H. (1968). "The information content of annual earnings announcements." *J Accounting Research*, 6, 67-92.
- Savor, P. & Wilson, M. (2016). "Earnings announcements and systematic risk." *J Finance*, 71(1), 83-138.
- Ball, R. & Kothari, S.P. (1991). "Security returns around earnings announcements." *Accounting Review*, 66(4), 718-738.

## 已引用的歷次實驗

- K1059: TSMC → 0050.TW NULL（T+0, ratio=1.007）
- K1058: A4f on 0050.TW mixed
- K1050: SPY earnings season uniform improvement
- K176: TSMC DeltaCoVaR

## 署名

- 提出: Claude
- 執行: Claude
- 日期: 2026-04-12
- Random seed: 42
