# K193 / mile_6a601155 — Codex 24h-rule Review

**Article**: 兩支 ETF 同時暴跌時，波動率會提前發出信號嗎？
**Published**: 2026-06-11T01:01:00Z
**Reviewer**: Codex CLI (gpt-5.4 medium) + main-thread audit completion
**Date**: 2026-06-11 09:25 CST

## VERDICT: CONDITIONAL_PASS

數字、方法、code 一致可驗證；無 lookahead；無捏造。
扣分集中在「多重檢定未校正」+「effect size 與統計顯著性混淆」。
Article 自身已有部分 caveat（NS 兩對如實標示，反直覺方向有解釋），
但 SPY-QQQ / SPY-GLD「顯著」未做 Bonferroni 4-pair adjustment。

---

## 逐條 finding

### A. Lookahead — PASS
- `compute_rolling_tail_dep` (line 253-264): rolling window 嚴格使用 `r1[i - window:i]`，
  signal at end-of-window；無 t+k 資訊洩漏。
- `future_rv = spy_ret.rolling(22).std().shift(-22)` (line 259, 410, 751)
  — 顯式 shift -22 把 future RV 對齊回現在的 TDA，是 forecast target 不是 feature。
- OOS GARCH train block (line 562-589): `train_ret = spy_aligned.iloc[start_pos:pos]`
  + `rv_next = train_rv.shift(-1)` — train 期內用 future RV 作 stage-2 regression target，
  forecast 階段才用 `tda_aligned.iloc[pos]` 作 t-時 feature → 預測 t+1 RV。
  Train/forecast 切點乾淨。
- **Verdict**: NO lookahead. ✅

### B. Multi-test correction — MEDIUM (主 finding)
- 4 pair × 2 quantile × {raw r, partial r, DM} = ~24 個 hypothesis test。
- Source code 未做任何 Bonferroni / Holm / FDR 校正（grep -n "Bonferroni|Holm" → 0 hits）。
- Article 報的 OOS DM p-values：
  - SPY-QQQ p=0.0188 → Bonferroni 4-pair adj = **0.075 (NS)**
  - SPY-GLD p=0.0082 → Bonferroni 4-pair adj = **0.033 (borderline)**
  - SPY-TLT p=0.266 / QQQ-TLT p=0.434 — 已 NS，不影響
- Article 文字「SPY-QQQ −13.3% 顯著」、「SPY-GLD −12.1% 高度顯著」**未提 4-pair 校正**。
- **Fix recommendation**: 文末加一句「4 pair 同時檢驗下，Bonferroni 校正後僅 SPY-GLD 殘存 borderline 顯著（adj p≈0.033），SPY-QQQ 退到 NS (adj p≈0.075)」。

### C. Granger F=32.6 — LOW
- `tda_change = tda.diff(22)`, `corr_change = corr.diff(22)` (line 824)
  → 22-day 重疊差分 → autocorrelation 膨脹標準誤差。
- Code 未用 Newey-West HAC 校正 F-test SE（DM test 那邊有用，這邊沒有）。
- N=4789 + 22-day overlap → F 過度膨脹是已知 pattern。
- Article 報「F=32.6 (p<1e-8)」沒提 overlap caveat。
- **Fix recommendation**: 加 HAC adjustment 或改 22-day non-overlapping subset 重跑；
  預期 F 顯著下降但仍 significant。寫入 README errata。

### D. Copula method — PASS
- 用 rank-based empirical copula（line 259-265），非 parametric Joe-Clayton / GAS。
- Article 沒 misrepresent 為 parametric copula —「動態 Copula 尾部依賴」措辭一致。
- 滾動 252-day 重估、無 burn-in 偏誤、deterministic（rank 無亂數）。
- **Verdict**: 方法描述準確 ✅

### E. Effect size vs statistical significance — MEDIUM
- r_lead_22d = **−0.057**（解釋 0.33% variance）→ economic 微弱。
- t=-4.07 高度顯著只因 N≈4789 大樣本。
- Article 把此包裝成「**領先信號**」——技術上 statistically significant 但
  economically negligible。
- Article 雖有「反直覺方向，恐慌→消化」解釋，但**沒明寫 effect size 微弱**。
- **Fix recommendation**: 在「r=-0.057」段加註「r²≈0.3% 解釋力，方向訊號 ≠ 強訊號」。

### F. GARCH-X baseline — PASS
- baseline = `arch_model(vol="GARCH", p=1, o=1, q=1, dist="t")` → **GJR-GARCH-t**, not plain GARCH(1,1)。
- Article 寫「傳統的波動率預測模型」沒 misstate spec — 一般讀者口徑可接受。
- Two-stage (stage-1 GJR-t → stage-2 add TDA) 為簡化版 GARCH-X，但 valid。
- **Verdict**: baseline 合理 ✅

### G. Code quality — PASS（minor LOW）
- `np.random` / seed 全無 hits — 本實驗 deterministic (rank-based + analytical t-test)，
  無隨機程序需 seed。
- JSON results 與 article 文字數字 100% 對得上（codex exec 已 verify）：
  - λ_L means: 0.753 / 0.164 / 0.093 / 0.094 ✅
  - r_contemporaneous=0.1113, r_lead_22d=-0.0572, t=-4.07, p=4.8e-5 ✅
  - Granger F=32.6, p=1.2e-8 ✅
  - DM p-values & QLIKE improvements ✅
- **Minor**: SPY-QQQ partial r|VIX = **-0.0493 (反向)** 但 article 完全沒提 partial correlation —
  controlling for VIX 後 SPY-QQQ 的 TDA 預測力消失。
  - 屬於 selective reporting；不誤導但缺失訊息。

---

## 後續處置建議

1. **Errata to article**（建議發 short note）：補 Bonferroni / partial-r-VIX caveats 各一句
2. **Knowledge.json entry**: K193 verdict = CONDITIONAL_PASS（已存在則 amend caveats）
3. **下次同類實驗自動套用**：multi-test correction + effect size flag 應寫入 experiments preamble checklist
