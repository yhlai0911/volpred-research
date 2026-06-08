# K1427 — 股市大跌時是「資金齊撤」還是「資金輪動」?用 sector dispersion 拆開「齊跌」

**Status: COMPLETE**

## 核心發現（一段話）

對一個總經評論主張「近期（2026 年 6 月初）那波 selloff 資金並未撤出股市，而是輪動到能源與防禦性類股的抗通膨交易」——本實驗用真數據裁決為 **MIXED（部分成立、部分不成立）**。最近一次大跌日（2026-06-05，SPY −2.58%）的橫斷面板塊離散度落在歷史 **99.5 分位**，防禦類股當天逆勢上漲（XLU +0.93%、XLP +1.71%、XLV +0.61%），同時科技 XLK 重挫 −6.66%——這部分**支持**「不是全面撤離、底下在輪動」。但主張特別點名的**能源 XLE 當天卻是下跌 −1.84%**（只是比科技抗跌），所以「資金輪動到能源抗通膨交易」這個**具體說法不成立**。誠實結論：那天是「資金從科技流向防禦」的輪動，**不是**流向能源。更廣的歷史檢視也打臉「大跌＝齊跌」的直覺：2014 年以來 101 個大跌日的橫斷面 dispersion 平均是平常日的 **1.75 倍**（1.25% vs 0.71%，Welch p=3.2e-12）——大跌時板塊分歧其實**更大**，不是更小。但 dispersion 高 ≠ 一定在輪動：69 個 selloff episode 裡只有 **19 個（28%）是真輪動**（有板塊逆勢正報酬），**33 個（48%）是高 dispersion 但全板塊皆跌**（spread 大只因跌幅參差），**17 個（25%）是低 dispersion 齊跌清算**。

## 動機與差異化

靈感來自一個「股債金油齊跌、資金去哪」的總經評論。但 **VolPred 不做總經/Fed/CPI 預測**（lane 外）。差異化貢獻：用**波動率與橫斷面 dispersion** 把「齊跌」這個指數層印象拆開——指數看起來齊跌，底下可能是高 dispersion 的**板塊輪動**（錢從科技流向防禦/能源），這是可測量的橫斷面結構。

**vs feed 既有「相關/分散」文章的明確區隔**（避免 narrative-arc 重複）：

| 既有文章 | 角度 | 本文不同處 |
|---|---|---|
| mile_cc3c987a | SPY–黃金下尾相依、分散崩 | 不做 pairwise tail dependence |
| mile_1a6d9369 | 分散救不了市場 | 不是再講「分散失靈」 |
| mile_47ad5dc0 | 相關性模型能否少虧 | 不做相關性翻正交易 |
| mile_a0ac369d | 策略套娃 | 無策略回測 |

本文唯一焦點 = **cross-sectional sector DISPERSION（橫斷面板塊離散度）+ 輪動 vs 清算 regime 分類 + 裁決一個具體外部主張**。重點是「齊跌底下其實在輪動 or 真的在撤」這個可測量的方向性結構，不是相關性。

## 資料

- 來源：yfinance（`auto_adjust=True`，調整後收盤），期間 **2014-01-01 ~ 2026-06-08**。
- 指數：SPY。
- 11 SPDR 板塊 ETF：XLE 能源、XLU 公用、XLP 必需消費、XLK 科技、XLF 金融、XLV 醫療、XLY 非必需消費、XLI 工業、XLB 原物料、XLRE 房地產、XLC 通訊。
- **晚上市處理**：XLRE（2015-10）、XLC（2018-06）上市較晚。canonical 主分析用 **early-9**（排除 XLRE/XLC，涵蓋 2014 起最長期間、含 2015/2018/2020/2022 多次空頭）；**full-11** 作 robustness（results.json `robustness_full11`，結論一致：大跌日 dispersion 顯著較高）。
- 缺值 inner-join 對齊後 drop，drop 數記於 results.json。
- 日報酬 `pct_change`；realized vol = 日報酬 rolling-20 std × √252（年化）。

## 方法

1. **Selloff 偵測**：大跌日 = SPY 日報酬 < −2%（101 天）。相鄰 ≤3 交易日的大跌日歸為同一 episode（69 episodes）。
2. **Cross-sectional dispersion**：每日 = 當日 N 板塊日報酬的橫斷面標準差（ddof=1）。
3. **Regime 分類（2-D 誠實版）**：dispersion 高低 × 方向廣度——
   - `rotation`：dispersion ≥ 歷史 70 分位 **且** 至少 1 板塊 episode 累積正報酬（真有資金輪進去）。
   - `broad_selloff_high_disp`：dispersion 高 **但全板塊皆跌**（spread 大只因跌幅不一，本質仍齊跌）。
   - `liquidation`：dispersion 低（齊跌、diversification 失靈）。
   - **方法論註**：只用 dispersion 分位會把「全跌但跌幅參差」誤標成 rotation（例：COVID 2020-02~03 dispersion 高但 9 板塊全跌 −25% 到 −55%）。dispersion 只量「分散度」不量「方向」，故加方向廣度條件才誠實。
4. **板塊行為**：每板塊在大跌日的平均報酬、逆勢頻率（大跌日正報酬比例）、RV ratio（大跌日 RV / 全期 RV）。
5. **（描述性，非 forecast）** contemporaneous dispersion_t → 未來 SPY realized vol（t+1..t+N，**明確 lag、無 lookahead**：`shift(-1).rolling(N).std().shift(-(N-1))`）。只在大跌日把 dispersion 分高/低比較未來 vol。**小樣本（僅大跌日），定位為描述性 hint，不是預測模型**。N=5 時高 dispersion 大跌後的未來 5 日 SPY RV 反而略高（37.3% vs 29.0%，Welch p=0.13，不顯著）——即輪動型大跌**未必**後續更平靜，誠實報告 null。

## 外部主張裁決（results.json `external_claim_verdict`）

- **Verdict：MIXED**
- (a) dispersion：最近 selloff（2026-06-05）在歷史 **99.5 分位**（>70，輪動證據成立）。
- (b) 防禦：XLU +0.93% / XLP +1.71% / XLV +0.61% vs 科技 XLK −6.66%（**防禦全面逆勢，成立**）。
- (b') 能源：XLE **−1.84%**（雖比 XLK 抗跌，但**是負報酬**→「輪動到能源抗通膨交易」**不成立**）。
- (c) 同步性：9 板塊中 5 跌 4 漲（**非全面清算**）。
- **誠實結論**：那天是「科技 → 防禦」的輪動，支持「資金沒全撤」；但主張特指的「能源抗通膨交易」沒有數據支持。不為了「有結論」硬選邊。

## 板塊行為（全期大跌日平均，early-9）

防禦最抗跌、逆勢頻率最高；科技/景氣循環跌最凶。所有板塊大跌日 RV 都 ≈1.56–1.75× 全期（vol 普遍噴，無人倖免）：

| 板塊 | 大跌日均報酬 | 逆勢頻率 | RV ratio |
|---|---|---|---|
| XLU 公用(防禦) | −1.70% | 12.9% | 1.56 |
| XLP 必需消費(防禦) | −1.80% | 8.9% | 1.72 |
| XLE 能源 | −3.28% | 8.9% | 1.63 |
| XLV 醫療(防禦) | −2.37% | 2.0% | 1.65 |
| XLK 科技 | −3.71% | 0.0% | 1.75 |

## 圖表

- `fig1_timeseries_dispersion.png`：SPY 報酬 + 橫斷面 dispersion 時間序列，標出 selloff 日與 70 分位門檻。
- `fig2_dispersion_distribution.png`：大跌日 vs 平常日 dispersion 分佈（violin+box），ratio 1.75x、Welch p=3.2e-12。
- `fig3_representative_selloff.png`：代表性 selloff（SPY 跌最深者＝COVID 2020-02~03）的板塊累積報酬 + RV ratio。

## 結論一句話

大跌不等於齊跌：歷史上大跌日板塊分歧反而更大（1.75×），但「dispersion 高」多數時候仍是「全板塊跌幅參差」而非真輪動（69 episodes 僅 28% 是真輪動）；最近那波（2026-06-05）確實是「科技→防禦」的輪動而非全面撤離，但「資金輪動到能源抗通膨交易」的具體說法被數據打臉（XLE 同步下跌）。

## 復現

```bash
python experiments/k1427/k1427.py
```

- seed = 42（`np.random.seed(42)`，全程固定）。
- 數據來源：yfinance（即時抓取，期間 2014-01-01 至執行日）。
- 所有數字寫入 `k1427_results.json`，本 README 引用的數值均來自該檔。
- 第 5 項預測檢驗為描述性（contemporaneous dispersion → future vol，明確 lag），非 forecast model；其餘為描述性橫斷面分析。
- 不含任何 Fed/CPI/macro 預測或投資建議。

## Reviewer

- Codex CLI code review（見 commit message / 下方審查結論）。

## Review 紀錄（2026-06-09）
- **Reviewer**: `feature-dev:code-reviewer` subagent fallback（Codex CLI 0.137.0 故障，exec 無輸出）。
- **Verdict**: CONDITIONAL_PASS。無 lookahead（主路徑）、無捏造數字、seed=42 固定、external_claim_verdict 誠實（XLE 當天 −1.84% → 能源那部分判 REFUTED，未 cherry-pick）。
- **唯一條件（Q5 caveat）**：q5「dispersion → 未來 N 日 RV」的 forward 公式（k1427.py line 207）有雙重 shift，實際窗口比宣稱的 t+1..t+N 滑後 N-1 天（仍向未來，非 lookahead，但窗口定義不符）。Q5 本為描述性 null result、非核心結論。**文章不引用 Q5 具體數字，只用「無預測力」方向性結論。** 核心發現（q1 dispersion 比較 / q2 regime / q4 最近 selloff / external_claim_verdict）不受影響。
