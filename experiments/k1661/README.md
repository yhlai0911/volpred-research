# K1661 | HARQ 測量誤差加權在日頻 OHLC 代理噪音下的 contrarian 檢定

**Verdict**: `NULL`（canonical，統計顯著性層級）｜ contrarian 假說 directional 支持 = `SUPPORTED_DIRECTIONAL`
**Date**: 2026-07-08 ｜ **Seed**: 1661 ｜ **Reviewer**: code-reviewer subagent fallback（Codex 額度用盡，7/11 恢復後二審）

---

## 1. 研究問題（反直覺）

HARQ（Bollerslev, Patton & Quaedvlieg 2016, JoE）的核心創新是用 **realized quarticity (RQ)** 衡量「當日 RV 的測量誤差」，並讓 autoregressive daily loading 隨測量誤差**動態衰減**：

$$RV_t = \beta_0 + (\beta_d + \beta_{dQ}\sqrt{RQ_{t-1}})\,RV^{d}_{t-1} + \beta_w RV^{w}_{t-1} + \beta_m RV^{m}_{t-1} + \varepsilon_t$$

理論預期 $\beta_{dQ}<0$：測量誤差大（$RQ$ 高）的日子，$RV_{t-1}$ 較不可信 → 下修其權重。這在**高頻**RV 下站得住腳，因為 $RQ=\frac{N}{3}\sum r_i^4$ 對 $N$ 筆日內報酬取平均，是相對穩定的測量誤差估計。

**Contrarian 問題**：若我們**只有日頻 OHLC**，用 Garman-Klass range 近似 $RV$、再用 range 四次方近似 $RQ$，則 $RQ$ proxy 本身是「單日、無日內平均、極高噪音」的估計。此時測量誤差加權到底**幫助還是傷害** OOS 預測？

**假說**：在此 regime 下 $\sqrt{RQ_{t-1}}=(\ln H/L)^2_{t-1}\propto\sigma^2_{t-1}$ 幾乎與 $RV_{t-1}$ **共線**，交互項 $\sqrt{RQ_{t-1}}\cdot RV_{t-1}\approx RV_{t-1}^2$，本質是加了一個「噪音平方」項而非乾淨的測量誤差訊號 → HARQ 相對樸素 HAR **無 OOS 增益甚至輕微傷害**（「代理噪音下誤差加權反轉」）。

## 2. 與庫內既有 K 的差異化

| K | RV 來源 | 測到什麼 |
|---|---|---|
| **K1582**（item 05793297）| **高頻 5-min RV**（TX/SPY/0050）| HARQ/SHARK 在 TX_active 方向有利（+1.94%, DM t=-2.60）但不過 Harvey \|t\|>3；DIRECTIONAL_ONLY |
| rough-vol race（fae873b0）| **高頻 5-min RV**（TX/SPY）| HARQ 最佳但不顯著；"measurement vs allocation" |
| **K1661（本實驗）**| **日頻 OHLC 代理**（Garman-Klass）| HARQ **無增益、一致但不顯著輕微退化**（與高頻方向相反）|

既有 K 全在**高頻 RV**下測 HARQ。K1661 專測**日頻 OHLC 代理噪音**這個全新 regime，且假說方向相反——這是 contrarian 角度的核心。

## 3. 文獻

- **Corsi (2009)** JFE 7(2), 174-196 — HAR baseline（daily/weekly/monthly RV lags）
- **Bollerslev, Patton & Quaedvlieg (2016)** JoE 192(1), 1-18 — HARQ、insanity filter、$\sqrt{RQ}$ 交互 spec
- **Garman & Klass (1980)** J. Business 53(1), 67-78 — OHLC range 變異數估計（本實驗 RV proxy）
- **Parkinson (1980)** J. Business 53(1), 61-65 — extreme-value range 變異數（GK 負值 fallback + RQ proxy 基礎）
- **Patton (2011)** JoE 160(1), 246-256 — QLIKE 對不完美 proxy 的 robust ranking 性質
- **Harvey, Leybourne & Newbold (1997)** IJF 13(2), 281-291 — DM 檢定的 small-sample 修正（本實驗 DM gate）

## 4. 方法

**資料**：yfinance 日頻 OHLC，2010-01-04 → 2026-07-07。
- SPY（美股 ETF，可交易，range 乾淨）
- 0050.TW（台股 ETF，可交易，range 乾淨）
- TWII = `^TWII`（台股加權指數，**TX 台指期代理**；yfinance 無 TX 連續合約日 OHLC，用指數代理並註明 caveat）

**RV proxy — Garman-Klass**：
$$GK_t = 0.5(\ln H_t/L_t)^2 - (2\ln 2 - 1)(\ln C_t/O_t)^2$$
負值（罕見，當 $|C-O|$ 相對 range 過大）以 Parkinson $\;PK_t=(\ln H/L)^2/(4\ln 2)$ 補正（恆正）。GK 量測**日內（open-to-close）**變異數，忽略隔夜跳空。

**RQ proxy — range-based quarticity**（本實驗核心近似，caveat 重）：
$$RQ_t = (\ln H_t/L_t)^4 \quad\Rightarrow\quad \sqrt{RQ_t} = (\ln H_t/L_t)^2$$
維度上 $\sqrt{RQ}$ 落在變異數尺度（$\propto\sigma^2$），與 BPQ 的 $\sqrt{RQ}$ 對齊；比例常數由回歸 $\beta_{dQ}$ 吸收（見 §7 caveat）。此 proxy 是**單日**估計，無高頻 RQ 的日內平均 → 高噪音。

**模型**（全部同 estimation window、同 lag 慣例、同 OOS split）：
- `HAR`：Corsi 2009 baseline
- `HARQ`：daily-only $\sqrt{RQ_{t-1}}$ 交互（BPQ-lite）
- `HARQ-F`：$\sqrt{RQ_{t-1}}$ 交互到 daily/weekly/monthly 三項（BPQ full spec）
- `HARQ-smooth`：**機制探針**——用 5 日平均 $\sqrt{RQ}$（降噪，模擬高頻 RQ 的日內平均）交互 daily

**估計/評估**：rolling window $W=1000$（BPQ 慣例），one-step，**每日 refit**。$\sqrt{RQ}$ 交互項用訓練窗統計 standardize（forecast-neutral，純數值 conditioning）。BPQ **insanity filter**（預測 $\le 0$ 或超訓練樣本 $[\min,\max]$ → 用訓練均值取代）**統一套用到所有模型**。

**Loss**：QLIKE（canonical $a/f-\log(a/f)-1$，Patton 2011 proxy-robust）+ MSE。
**檢定**：Diebold-Mariano + **Harvey-Leybourne-Newbold (1997) small-sample 修正**，$h=1$：
$$\text{DM-HLN} = \text{DM}\times\sqrt{\tfrac{T+1-2h+h(h-1)/T}{T}},\quad \text{對照 Student-}t(T-1)$$
方向約定：$d=L_{\text{HARQ}}-L_{\text{HAR}}$，$d<0\Rightarrow$ HARQ 較優（DM-HLN $t<0$）。Gate = Harvey $|t|>3$。

## 5. 結果

| 資產 | $n_{oos}$ | HAR QLIKE | HARQ (Δ%) | HARQ DM-HLN $t$ (p) | HARQ-F (Δ%) | HARQ-F $t$ (p) | HARQ-smooth (Δ%) | $\beta_{dQ}$(std) | corr($\sqrt{RQ},RV_d$) |
|---|---|---|---|---|---|---|---|---|---|
| SPY | 3129 | 0.43037 | 0.43932 (**−2.08%**) | +0.493 (0.62) | −11.67% | +1.543 (0.12) | 0.42768 (**+0.63%**) | −0.0113 | 0.94 |
| 0050.TW | 3012 | 0.50836 | 0.51379 (**−1.07%**) | +0.710 (0.48) | −3.57% | +1.877 (0.06) | 0.51941 (−2.17%) | −0.0070 | 0.93 |
| TWII | 3007 | 0.37401 | 0.37858 (**−1.22%**) | +0.541 (0.59) | −19.84% | +2.615 (0.009) | 0.38825 (−3.81%) | −0.0062 | 0.92 |

（Δ% = 相對 HAR 的 QLIKE 改善；負 = 更差。MSE 同向：3/3 資產 HAR ≤ HARQ ≤ HARQ-F。）

**核心觀察**：
1. **HARQ 3/3 資產 QLIKE 都比 HAR 差 1–2%，但 DM-HLN $t$ 僅 0.49–0.71（遠 < Harvey 3），皆不顯著** → canonical `NULL`。insanity filter 只在 0.1–0.2% 的日子觸發，排除「數值爆炸」解釋。
2. **In-sample $\beta_{dQ}<0$（3/3）**——符合 BPQ 理論符號，模型在**樣本內**確實偵測到「$RQ$ 高的日子該下修 $\beta_d$」；但這個訊號**OOS 無法轉化為預測改善**，反而輕微傷害。
3. **主機制證據：$\text{corr}(\sqrt{RQ_{t-1}}, RV_{t-1})\approx 0.93$（3/3 一致，見 fig `rq_collinearity.png`）**——日頻下「測量誤差權重」$\sqrt{RQ}$ 幾乎與 $RV$ 本身共線，交互項 $\approx RV^2$，**不帶 $RV$ 以外的獨立測量誤差訊息**，多出的 $\beta_{dQ}$ 只增加估計變異 → 溫和 OOS 退化。
4. **HARQ-F（更多測量誤差參數）大幅更差**（SPY −11.67%、TWII −19.84%，TWII $t=2.615$, p=0.009 達 5% 顯著更差、但未達 Harvey 3）——**參數越多，在代理噪音下 overfit 越嚴重**，強力佐證 contrarian 方向。
5. **次要機制探針（mixed）**：平滑 $\sqrt{RQ}$（5 日）只在 **1/3**（SPY，最乾淨的 ETF）縮小退化並略回正，兩檔台股反而更差 → 單日 $RQ$ 噪音只是**部分**原因；日頻測量誤差校正整體上是**冗餘的**。

## 6. Verdict

- **Canonical `NULL`**：無資產達 Harvey $|t|>3$（HARQ 顯著優 0/3、顯著劣 0/3）。結論強度不超過證據。
- **Contrarian 假說 directional 支持 = `SUPPORTED_DIRECTIONAL`**：3/3 資產 HARQ QLIKE 一致劣於 HAR（1–2%），MSE 同向，HARQ-F 大幅更差，機制上 $\sqrt{RQ}$–$RV$ 共線 0.93。
- **一句話**：日頻 OHLC 代理下，HARQ 的測量誤差加權相對樸素 HAR **無 OOS 增益**（一致但不顯著的輕微退化），與高頻 RV 下 HARQ 方向有利（K1582 TX）形成對照。**「測量誤差加權」的價值取決於測量誤差本身能否被穩定估計；當 RQ 只能用單日 range 近似時，加權訊號與 RV 共線、退化為噪音。**

> ⚠️ 一致的 3/3 方向是 directional 佐證，非統計證明；不可誇大為「HARQ 顯著傷害」。跨資產不做 iid pooling（K1355 規則）；3/3 同向的 sign 觀察僅為 suggestive（binomial p=0.125）。

## 7. Caveats / 限制

- **RQ proxy 是粗近似**：$(\ln H/L)^4$ 不是 integrated quarticity 的無偏估計，僅維度對齊的 range-based 代理；比例常數由 $\beta_{dQ}$ 吸收（standardize 後 forecast-neutral）。這正是 contrarian 假說的前提——日頻下沒有更好的 RQ。
- **TWII 是指數非成交價**：`^TWII` 的 H/L 由成分股極值合成、非單一可交易價，range 有額外量測誤差（低估真實日內 range）→ RQ proxy 更噪，這**強化**而非削弱 contrarian 方向；SPY/0050.TW 為可交易 ETF，range 較乾淨。TX 台指期連續合約日 OHLC 若日後可得應複驗。
- **GK 僅日內（open-to-close）變異數**，忽略隔夜跳空；target 與 feature 同用 GK 尺度，內部一致（QLIKE 對 conditionally-unbiased proxy robust，Patton 2011）。
- **樣本**：$n_{oos}\approx 3000$/資產，跨 2010–2026 含多次空頭（2011/2015/2018/2020/2022），OOS 穩健。

## 8. Lookahead 聲明

- 設計矩陣以 **target date $t$ 對齊**：$RV^d=RV_{t-1}$、$RV^w=\text{mean}(RV_{t-5..t-1})$、$RV^m=\text{mean}(RV_{t-22..t-1})$、$\sqrt{RQ}=\sqrt{RQ_{t-1}}$，全部由 `.shift(1)` / `rolling().shift(1)` 構成（見 `build_design()`）——features 僅用 $t-1$ 之前的 realized OHLC 預測 $RV_t$。
- rolling 訓練窗 `d.iloc[i-W:i]` 的 target date 皆 $\le$ idx$[i-1]$，嚴格早於預測日 idx$[i]$（$target\_end < forecast\_origin$）——無訓練列看見預測日或之後的 realized 值。
- $\sqrt{RQ}$ standardize 用**訓練窗**統計（非全樣本）→ 無 lookahead；且 standardize 為線性重參數化，forecast-neutral。
- $h=1$，DM-HLN inference horizon 與 forecast horizon 一致。
- Seed = 1661；本實驗除 numpy 全域 seed 外無其他隨機程序（OLS 為 closed-form）。

## 9. 檔案

- `k1661_harq_ohlc.py` — 可復現主腳本（seed 固定）
- `k1661_results.json` — per-asset per-model QLIKE/MSE、DM-HLN、in-sample $\beta_{dQ}$、verdict
- `data/{SPY,0050.TW,TWII}_ohlc.csv` — 抓取快照（provenance）
- `figures/qlike_comparison.png` — HAR vs HARQ 家族 OOS QLIKE bar
- `figures/rq_collinearity.png` — $\sqrt{RQ}$ vs $RV_{t-1}$ 共線性散點（核心機制圖）
- `figures/rolling_loss_diff.png` — HARQ−HAR 累積 QLIKE loss 差分
- `reviews/codex_review.md` — 代碼審查 verdict

## 10. 復現

```bash
python3 experiments/k1661/k1661_harq_ohlc.py   # yfinance 優先，storage/macro cache fallback
```
