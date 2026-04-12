# K1070: 0050.TW ETF-Level CAR/CASV Event Study — Aggregation Effect of Earnings

**Proposer**: Claude (extension of K1068 to ETF level)
**Executor**: Claude
**Data**: 0050.TW (cleaned via `volpred.utils.clean_tw50_data`), ^TWII market model, earnings announcement dates from `財報公告日.txt` (Big5)
**Period**: 2010-01-01 to 2025-12-31 (3,906 common trading days)
**Random seed**: 42

## 1. 問題描述與動機

K1062（舊方法）用單點的事件日 r² 比率（T+0 / T+1）測試 0050.TW ETF 對財報日的波動反應，得到 T+1 ratio=1.132 — 方向對但統計上只是「H1 PARTIAL」。

K1068（新方法，剛完成）在 10 檔個股上採用 MacKinlay (1997) 的正規 CAR/CASV 事件研究法，得到：
- **CAR[-5,+5] NULL**（t_BW=-0.04, p=0.966）：財報不引發方向性 drift。
- **CASV[-5,+5] 高度顯著**（t=+4.35）：財報前後波動率的確出現 spike，且強度是 K1060 簡化法的 2 倍。

本實驗的目的是：**把 K1068 的嚴謹方法套回 0050.TW ETF，量化聚合效應（diversification dilution）到底把個股級的財報 CASV signal 削弱多少。** 同時回答「K1062 的 PARTIAL 判決是不是因為方法弱？」

## 2. 方法

### 2.1 Market Model 與統計檢定

對 0050.TW 的每一個事件日分別估計：
```
R_{0050,t} = α + β · R_{TWII,t} + ε_t,  t ∈ [T-250, T-11]
```

以 **^TWII（TAIEX 價格指數）** 為 market benchmark。0050.TW 是 TWSE 50 指數追蹤 ETF，β 理論上接近 1，residual 非常小 — 這正好是我們要測試的 ETF 稀釋效應：abnormal return 在 ETF 上本來就應該很小。

每個事件計算：
- `AR_t = R_{0050,t} - (α̂ + β̂ · R_{TWII,t})` over `[-5, +5]`
- `CAR(t1,t2) = Σ AR_t`
- `SCAR = CAR / √(L · σ²_resid)` （Patell 1976 標準化）
- `CASV(t1,t2) = Σ (AR_t²/σ²_resid − 1)` （Patell–Wolfson 1984）

三重檢定（K1068 一致）：
| 檢定 | 用途 |
|---|---|
| Brown–Warner (1985) | CAR cross-sectional t |
| Patell (1976) | Standardized CAR z |
| Boehmer–Masumeci–Poulsen (1991) | BMP SCAR t（robust to event-induced variance） |
| One-sample t on CASV | 波動 spike 是否顯著 |

**額外 robustness**：median CASV、5% trimmed mean CASV（對右尾異常事件敏感性檢查）。

### 2.2 四組事件集（aggregation mechanism 對比）

| Set | 定義 | 用途 | N（usable） |
|---|---|---|---|
| A | TSMC (2330) only | 單一大型個股 | 56 |
| B | Top 4 caps (2330/2454/2317/2303) | 少數重量股 | 173 |
| C | TWSE-50 universe (聯集) | 全 ETF 成分股 | 999 |
| D | Dense days（單日 ≥ 11 家 TWSE-50 公告，90th percentile）| 聚集極端 | 102 |

所有事件集都套上市場模型，分別估計 per-event 的 α/β 和 CAR/CASV，然後 pooled 計算平均值與 t 檢定。

## 3. 結果

### 3.1 Pooled CAR / CASV（[-5, +5]）

| Set | N | CAR | t_BW | p_BW | CASV (mean) | CASV (median) | CASV trim5% | t_CASV | p_CASV |
|---|---|---|---|---|---|---|---|---|---|
| A TSMC-only | 56 | -0.0012 | -0.76 | 0.452 | +1.780 | −2.917 | +0.234 | +0.98 | 0.329 |
| B Top-4 | 173 | -0.0007 | -0.67 | 0.505 | +6.451 | −2.364 | −0.353 | +1.24 | 0.215 |
| **C TWSE-50** | **999** | **-0.0008** | **-2.21** | **0.028** ** | **+2.781** | **−2.364** | **−0.880** | **+2.13** | **0.034** ** |
| D Dense | 102 | -0.0002 | -0.17 | 0.864 | +1.164 | −2.058 | −0.584 | +1.00 | 0.322 |

### 3.2 子窗口分解（Set C，TWSE-50，N=999）

| 窗口 | CAR | t_BW | p_BW | CASV | t_CASV | p_CASV |
|---|---|---|---|---|---|---|
| [-5,-1] pre-event | -0.0001 | -0.42 | 0.672 | +2.536 | +1.98 | 0.048 ** |
| [0,+1] immediate | -0.0002 | -1.59 | 0.113 | +0.230 | +1.65 | 0.099 * |
| [+2,+5] drift | -0.0004 | -2.21 | 0.027 ** | +0.015 | +0.09 | 0.928 |
| [-5,+5] full | -0.0008 | -2.21 | 0.028 ** | +2.781 | +2.13 | 0.034 ** |

**注意子窗口的 CASV 分布**：pre-event ([-5,-1]) 的 CASV 幾乎和 [-5,+5] 一樣高（+2.536），而 immediate ([0,+1]) CASV 只有 +0.230。這顯示 **ETF 的波動信號集中在事件前幾天，不是公告日本身** — 與 K1068 個股的 [0,+1] CASV=+1.358（t=+4.15）形成對比。個股的「spike」在 T+0/T+1 集中；ETF 的「spike」被分攤到前 5 天，且來自 pre-event 端。

### 3.3 Diversification dilution

相對於 K1068 個股 CASV[-5,+5] = +3.128：

| Set | CASV_ETF | 稀釋比 (ETF / 個股) |
|---|---|---|
| A TSMC | +1.780 | 0.57 |
| C TWSE-50 | +2.781 | 0.89 |
| D Dense | +1.164 | 0.37 |
| B Top-4 | +6.451 | 2.06 ← outlier，見下方說明 |

## 4. 假設判決

### H1: ETF CAR[-5,+5] 是 NULL（與 K1068 一致）

**MIXED** — Set C 在 5% 傳統門檻 **略顯著**（CAR=-0.0008, t_BW=-2.21, p=0.028），方向為負，但：
- **Fails Harvey (2016) t>3.0 門檻**（|t|=2.21 不到）
- 經濟意義非常小：-0.08% 的累積報酬，相當於一個交易日的典型日內波動
- K1068 個股為真 NULL，而 ETF 表面上有個微弱 drift 但與單支股票的個人因素無關，很可能是 999 事件樣本下的多重比較問題

**結論**：ETF CAR signal 不是穩健的研究發現。沒有交易意義。

### H2: ETF CASV[-5,+5] 顯著正

**SUPPORTED at 5% 但 FAILS Harvey t>3** — Set C CASV=+2.781, t_CASV=+2.13, p=0.034
- mean=+2.781 但 median=**−2.364**，5% trimmed mean=**−0.880**
- **CASV spike 完全由右尾的少數極端事件驅動，不是典型事件的 shift**
- 強度為 K1068 個股的 89%（dilution ratio 0.89），但實際上可比性存疑 — 因 K1068 CASV 的 median 結構未報（未檢查）
- Set A（TSMC-only）CASV=+1.780 的「稀釋比」0.57 是更公允的「單名公司事件 ETF 稀釋估計」

### H3: K1070 取代 K1062 — 嚴謹方法找到 K1062 漏掉的 signal？

**SUPPORTED（但伴隨重要警告）** — K1062（T+1 ratio=1.132, one-sample t=2.08, p=0.034）是「H1 PARTIAL」。K1070 在同一個 ETF 上：
- 用 [-5,+5] 窗口的 CASV 得到 t=+2.13, p=0.034（顯著強度與 K1062 幾乎一樣）
- 真正的改進是**分解出來源**：波動 spike 來自 [-5,-1] pre-event（CASV=+2.536, t=+1.98）而非 [0,+1] immediate（CASV=+0.230, t=+1.65）
- K1062 聚焦 T+0/T+1 抓不到 pre-event leakage

**結論**：K1062 的「PARTIAL」判決不是方法錯 — 是**窗口錯**。T+0/T+1 不是 ETF 波動反應的主場；pre-event [-5,-1] 才是。

### H4: 聚集效應 — 多公司同日 CASV > 單公司 CASV？

**NOT SUPPORTED** — 逆向結果：
- Set A（TSMC only）CASV=+1.780
- Set D（dense, ≥11 firms/day）CASV=+1.164

多公司同日 CASV 反而**較低**。可能的解釋：
1. Dense days 常對應固定的財報截止日（每季 5/15、8/14、11/14），市場已預期集中公告，**不確定性被日期本身吸收**
2. 單家公司的意外公告（如 TSMC 營收猜錯）才有真正的驚喜成分
3. Set D 的 N=102 偏小，檢定力不足

## 5. 與 K1062 / K1068 對照表

| 指標 | K1062（0050.TW 簡化）| K1068（10 個股正規）| **K1070（0050.TW 正規）** |
|---|---|---|---|
| Subject | 0050.TW | 10 stocks | 0050.TW |
| Normal return | rolling 60d r² | market model | market model |
| Return target | r² ratio T+0/T+1 | CAR[-5,+5] split | CAR[-5,+5] split |
| CAR[-5,+5] | — | -0.0001 (NS) | -0.0008 (p=0.028, fails Harvey) |
| CASV[-5,+5] | — | **+3.128 (t=+4.35)** | **+2.781 (t=+2.13)** |
| Best window | T+1 | [0,+1] | **[-5,-1] pre-event** |
| Verdict | H1 PARTIAL | H1 null / H3 strong | H1 mixed / H2 weak-supported |

## 6. 重要 caveats

1. **CASV 極度右尾驅動**：4 個 set 的 median CASV 全是負的（−2.0 到 −2.9）；只有少數極端事件（右尾）把 mean 推成正的。Set C 的顯著 t_CASV=2.13 在大 N=999 下靠的是 mean shift，但「典型」事件日（中位數）其實沒有 CASV 增加。**這意味著波動 spike 不是普遍效應，而是少數事件的集體貢獻。**
2. **Set B 的 CASV=6.451 看似「反稀釋」是 outlier artifact**：std=68.2, CV=10.6, t=1.24（NS）— 4 家公司的共同公告偶爾撞上一個別的極端事件（大盤震盪日），不是真正的聚合放大。
3. **0050.TW 的 β ≈ 1**：市場模型 residual 極小，CAR 的絕對水準（0.0001 量級）對於微小的共整合偏移很敏感。Set C 的微弱 CAR drift（-0.08%）可能是 ^TWII 指數 vs 0050.TW ETF 的追蹤誤差累積，不一定與財報有因果關係。
4. **Event-date mapping**：公告日若為收盤後，T+0 對應下一交易日開盤 — 本實驗用 `searchsorted` 自動 roll 到下一個可交易日，但未區分盤中/盤後公告，可能低估 immediate 反應。
5. **多重比較**：4 個事件集 × 4 個窗口 × 3 個 CAR 檢定 = 48 個 t 檢定。期望下有 2-3 個假陽性。Set C 的 CAR/CASV 5% 顯著可能就是這個量級的雜訊。

## 7. 結論與衍生方向

**本實驗核心發現**：
1. **ETF CAR 基本 NULL**（方向性 drift 不可交易）— 與個股 K1068 一致
2. **ETF CASV 顯著但是「右尾效應」**，不是普遍存在的 spike；強度約為個股的 57–89%（視事件定義）
3. **Pre-event [-5,-1] 才是 ETF 波動 spike 的主場**，不是 [0,+1] — 這是 K1062 漏掉的關鍵窗口
4. **Dense days 沒有聚合放大** — 反而被預期性吸收

**衍生方向（主線程請寫入 research_program.md）**：
1. **N1070a** 替換 market benchmark 為 SPY（美股跨市場 driver，K1058 已確認）— 看 TAIEX benchmark 是否把 spillover 算進 normal return 而吸掉了 abnormal
2. **N1070b** CASV 的右尾結構 — 哪些個別事件貢獻了 80% 的 CASV total？是否對應 ±2σ+ 個股事件 (TSMC 大漲/大跌) 或市場 tail day？
3. **N1070c** 交易時段分解 — 用 5min 數據把 CAR 拆為 overnight/intraday，看 pre-event [-5,-1] 的 CASV 是不是隔夜聚集（外資 inflow 預期）
4. **N1070d** 擴展到 2007-2009 金融危機、2020 疫情期間 — 看 CASV 在高波動 regime 的結構

## 8. 檔案清單

| 檔案 | 內容 |
|---|---|
| `k1070.py` | 完整實驗腳本 |
| `k1070_results.json` | 完整結果（4 sets × 4 windows × 3 tests + AAR/CAAR/dilution/hypotheses）|
| `k1070_car_casv_windows.png` | Heatmap: 4 sets × 4 windows，上 CAR 下 CASV |
| `k1070_aar_timeseries.png` | AAR/CAAR day-by-day for 4 sets |
| `k1070_comparison_k1068.png` | ETF vs individual stock effect sizes bar chart |

## 9. 參考文獻

- MacKinlay, A.C. (1997) "Event studies in economics and finance" JEL 35(1): 13-39
- Brown, S. & Warner, J. (1985) "Using daily stock returns: the case of event studies" JFE 14(1): 3-31
- Patell, J.M. (1976) "Corporate forecasts of earnings per share and stock price behavior" J Accounting Research 14(2): 246-276
- Boehmer, E., Masumeci, J., Poulsen, A.B. (1991) "Event-study methodology under conditions of event-induced variance" JFE 30(2): 253-272
- Patell, J.M. & Wolfson, M.A. (1984) "The intraday speed of adjustment of stock prices to earnings and dividend announcements" J Financial Economics 13(2): 223-252
- Beaver, W.H. (1968) "The information content of annual earnings announcements" J Accounting Research 6: 67-92
- Savor, P. & Wilson, M. (2016) "Earnings announcements and systematic risk" JFQA 51(1): 197-224
- Harvey, C.R. (2016) "…and the cross-section of expected returns" RFS 29(1): 5-68（t>3 threshold）
- K1060 (rolling r² ratio, individual), K1062 (0050.TW simplified), **K1068 (10 stocks traditional CAR/CASV)**
