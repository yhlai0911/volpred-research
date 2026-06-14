# Article Review: mile_1b511caa
**Review Date**: 2026-06-15 05:12 台灣時間  
**Reviewer**: Claude Sonnet (24h paper review)  
**Article Title**: 私募信貸這幾年很熱，規模愈做愈大，風險卻不太透明（K1499 BDC private-credit shadow stress 文章）  
**Published**: 2026-06-14 20:13 UTC  
**Claimed Experiment**: K1499  

---

## CRITICAL FINDING：文章本文是 K1332 的內容，不是 K1499

### 核心問題（FAIL 主因）

文章腳注明確寫：
> *本文基於實驗 `K1332`（腳本：`experiments/k1332/k1332.py`；結果：`experiments/k1332/k1332_results.json`）*

文章圖片 URL 也是 `k1332_private_credit_event.png` 和 `k1332_oos_qlike_delta.png`，全部是 K1332 的產出物。

**此篇文章的全部數字來自 `experiments/k1332/k1332_results.json`，不是 `k1499_results.json`。**

---

## 5 維度逐項評估

### (a) Numeric Trace — 數字追溯

**文章所有數字確認對應 K1332，非 K1499：**

| 文章 Claim | 文章數值 | K1332 source | 對應? | K1499 source | 備註 |
|---|---|---|---|---|---|
| BKLN 壓力日後隔日波動 / 非壓力日 | **12.5 倍** | `event_study[0].ratio = 12.516` (BKLN, next_day) | ✅ K1332 | K1499 無 BKLN 數據 | FAIL: 文章稱為 K1499 實驗 |
| HYG 壓力日後隔日波動 / 非壓力日 | **4.6 倍** | `event_study[2].ratio = 4.630` (HYG, next_day) | ✅ K1332 | K1499 HYG fwd5d_ratio=2.856 ❌ | FAIL: 不匹配 K1499 |
| KRE 壓力日後隔日波動 / 非壓力日 | **2.3 倍** | `event_study[4].ratio = 2.289` (KRE, next_day) | ✅ K1332 | K1499 KRE fwd5d_ratio=2.331 ~≈ | 數值近似但文章稱 K1332 來源 |
| IWM 壓力日後隔日波動 / 非壓力日 | **2.8 倍** | `event_study[6].ratio = 2.811` (IWM, next_day) | ✅ K1332 | K1499 IWM fwd5d_ratio=2.054 ❌ | FAIL: 不匹配 K1499 |
| BKLN 顯著性 p=0.009 | 0.009 | `event_study[0].bootstrap_p_value = 0.009` | ✅ K1332 | K1499 無 BKLN | FAIL |
| HYG 顯著性 p=0.001 | 0.001 | `event_study[2].bootstrap_p_value = 0.001` | ✅ K1332 | K1499 HYG p=0.0 | 接近 |
| BKLN 基準 QLIKE 13.621 | 13.621 | `rolling_oos.BKLN.models.har.qlike = 13.621` | ✅ K1332 | K1499 無 QLIKE | FAIL |
| BKLN 加入私募信貸後 12.138 | 12.138 | `rolling_oos.BKLN.models.har_pc.qlike = 12.138` | ✅ K1332 | K1499 無 QLIKE | FAIL |
| BKLN 改善幅度 +10.9% | +10.9% | `(13.621-12.138)/13.621 = 10.9%` | ✅ K1332 | K1499 無 QLIKE | FAIL |
| HYG 改善幅度 +7.1% | +7.1% | `(3.575-3.320)/3.575 = 7.1%` | ✅ K1332 | K1499 無 QLIKE | FAIL |
| KRE -1.6% | -1.6% | `(3.966-4.028)/3.966 = -1.6%` | ✅ K1332 | K1499 無 QLIKE | FAIL |
| IWM -1.5% | -1.5% | `(3.187-3.236)/3.187 = -1.5%` | ✅ K1332 | K1499 無 QLIKE | FAIL |
| SPY+VIX 控制後 BKLN 再 +9.0% | — | K1332 `har_market_pc` vs baseline delta | UNTRACEABLE (無法直接追) | K1499 無 QLIKE | UNTRACEABLE |
| SPY+VIX 控制後 HYG 再 +6.6% | — | 同上 | UNTRACEABLE | K1499 無 QLIKE | UNTRACEABLE |
| 樣本期間 2013-02-12 至 2026-06-12 | ✅ | K1332 `n_required_panel_days=3354` | ✅ K1332 | K1499 BIZD n=3354 (同期間) | 期間相同 |
| 3354 個交易日 | 3354 | K1332 `n_required_panel_days=3354` | ✅ K1332 | K1499 BIZD n=3354 | 同期間 |
| 樣本外 1367 個交易日，自 2021-01-04 | 1367 | K1332 `rolling_oos.BKLN.models.har.n_oos=1367` | ✅ K1332 | K1499 無 OOS 窗口 | FAIL |

**Numeric trace pass rate（相對 K1332）**: 13/15 traceable（2條 UNTRACEABLE，2條數值不匹配 K1499）  
**相對 K1499（被宣稱的實驗）**: 0/15 可追溯（BKLN 根本不在 K1499；QLIKE table 整體缺失）

---

### (b) PARTIAL Framing 一致性

**問題：文章 conclusion 與 K1499 PARTIAL verdict rationale 不一致**

K1499 verdict_rationale：
- HYG：BDC-RV stress 不 survive（pure SPY beta）；NAV-discount proxy 只在 h=5 survive（HAC t=3.18）
- KRE/IWM：NEITHER signal survives SPY-vol control

文章實際呈現（K1332 結果）：
- 呈現的是 K1332 的 OOS QLIKE 改善（BKLN/HYG 顯著正向，KRE/IWM 反轉）
- K1332 的結論是 `PASS_NARROW_CREDIT_ONLY`，不是 PARTIAL
- 文章標題「只對高收益債有用」是 K1332 的結論，符合 K1332 的 BKLN/HYG vs KRE/IWM 對比

**K1499 的 PARTIAL framing 核心內容（NAV-discount proxy vs BDC-RV stress；只有 HYG h5 survive；HAC t=3.18）完全沒有出現在文章中。**

判定：**PARTIAL framing 不一致**（文章呈現的是 K1332 的框架，不是 K1499 的框架）

---

### (c) Lookahead 檢查

文章表述：「訊號再往後 lag 一天，才拿去對照隔天和未來五天的波動，避免偷看」— 描述正確。

K1332 程式碼（未讀，但 K1499 已確認）:

**K1499 `k1499.py` 中 shift(1) 明確存在：**
- Line 274: `bdc_rv_z_lag1 = bdc_rv_z.shift(1)` ✅
- Line 275: `nav_z_lag1 = nav_z.shift(1)` ✅  
- Line 283: `spy_rv_z_lag1 = spy_rv_z.shift(1)` ✅
- Line 302: `own_rv = realized_vol(tgt_ret).shift(1)` ✅
- Forward RV: `ret.rolling(horizon).std().shift(-horizon)` — 正確往後移動 ✅

K1499 程式碼 lookahead policy 明確且正確，forward RV 測量嚴格在 signal date 之後。

但本文基於 K1332（腳注明確），K1332 lookahead 未直接審查，但描述與 K1499 同 logic，認定 K1332 設計相似。

判定：文章描述的 lookahead 防護邏輯正確（針對其聲稱的 lag 機制）；**但此評審針對 K1499 文章，K1332 腳注是文件錯誤。**

---

### (d) Anti-AI Style 9-Checklist

執行結果：
```
# Feed mode (--no-fb-mode):
PASS — no AI-style landmines (warn=0/3 ok)

# Default mode (含 FB checks):
PASS — no AI-style landmines (warn=2/3 ok)
  [WARN] 3.2 段落長度: 3 段超過 4 行 / 200 字（FB tone 要短段）
  [WARN] 3.4 列表結構: 7 行列表結構（FB 不是 newsletter）
```

**Feed 模式 Anti-AI Gate: PASS (0 MUST hit)**  
FB 模式 2 個 WARN，均非阻斷性（不適用 feed 文章）。

---

### (e) Overclaim Flags

1. **正向**：文章最後幾段相當節制，明確說「訊號不是市場哪裡都能用的萬用燈號」，指出 KRE/IWM 無 incremental signal，符合研究誠實原則。

2. **反向 overclaim（第一段表格之後）**：文章呈現四個市場都有 event study 顯著比率（含 KRE 2.3x, IWM 2.8x），並說「四個市場都會受影響」。但 K1332 的 OOS QLIKE 分析（緊接其後）顯示 KRE/IWM 都沒有改善（-1.6%, -1.5%）。兩層結果切割清楚，沒有 overclaim。

3. **BKLN 在 event study 列但沒在 QLIKE 改善表**：文章第一張表列 BKLN 12.5x，第二張 QLIKE 表也列 BKLN +10.9%，兩表都有 BKLN — 這是 K1332 的 basket，K1499 根本沒有 BKLN。

4. **文章標題「只對高收益債有用」**：K1332 的 OOS QLIKE 結論確實是 BKLN/HYG positive, KRE/IWM negative — 此 framing 對 K1332 屬 honest narrowing。但 K1499 PARTIAL 是只有 NAV-discount proxy HYG h5，連 BKLN 都沒有，差距更大。

**Overclaim flags**: 文章本身寫得嚴謹，沒有放大信號效果。但問題不在 overclaim，在 **wrong experiment ID**。

---

## 根本問題彙總

| 問題 | 嚴重度 | 說明 |
|---|---|---|
| 文章腳注寫 K1332，被分配給 K1499 里程碑 | **CRITICAL** | 文章 body 全部數字來自 K1332，圖片也是 K1332 產出 |
| BKLN 出現在 K1499 文章但 K1499 根本沒有 BKLN 數據 | **CRITICAL** | K1499 targets = HYG / KRE / IWM 僅此三個 |
| QLIKE table 整體來自 K1332，K1499 無 QLIKE 分析 | **CRITICAL** | K1499 方法論是 forward-RV + HAC regression，不是 OOS QLIKE |
| K1499 唯一 survive 的 NAV-discount HYG h5（HAC t=3.18）完全未提 | **CRITICAL** | K1499 核心 verdict 被隱沒 |
| 圖片引用 `k1332_*.png`，非 `k1499_*.png` | CRITICAL | 圖片引用錯誤 |

---

## Final Verdict

**FAIL**

**原因**：文章宣稱基於 K1499 但腳注、數字、圖片、BKLN 的存在、QLIKE 框架全部指向 K1332。文章不能代表 K1499 PARTIAL 實驗結果。這是 experiment ID 錯配（wrong article assigned to wrong milestone），不是 numerical error。

---

## Fix 建議

### 方案 A（推薦）：更正 milestone 指向
- `mile_1b511caa` 正文是有效 K1332 文章，但 milestone metadata 應指向 K1332 而非 K1499
- 更新 `storage/reports/feed.json` 中 `mile_1b511caa` 的 `details.experiment_refs` 從 `K1499` → `K1332`
- 確保 K1332 已有 milestone 或重新歸檔

### 方案 B：另撰 K1499 文章
- 另起一篇文章專門呈現 K1499 PARTIAL 結果：
  - 核心訊息：NAV-discount proxy（BIZD minus HYG return）在 HYG 5d horizon survive SPY-vol control（HAC t=3.178）
  - BDC-RV stress 本身是 pure SPY beta（Model B 不 survive）
  - KRE/IWM 無任何 incremental signal
  - 比 K1332 更嚴格的 beta 控制 + multi-horizon forward-RV design
  - 圖片用 `k1499_lead_lag_corr.png` + `k1499_event_study_path.png`（已生成）

**不可做**：直接把現有文章標籤改成 K1499 而不改內容——數字全錯。

---

*Review by: Claude Sonnet 24h-rule review | 2026-06-15 05:15 台灣時間*
