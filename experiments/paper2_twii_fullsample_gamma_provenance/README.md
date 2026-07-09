# paper2_twii_fullsample_gamma_provenance

**類型**：Provenance 稽核（governance / provenance-sweep-legacy-paper-numbers）
**起因**：telegram-312 — Paper2（taiwan-vt）滾動 γ 表 TWII 0.272 掛錯來源 / 無活來源；
屬 provenance gate（2026-05-17）上線前寫入的舊帳。
**日期**：2026-07-09

## 稽核目標

論文 `paper/taiwan-vt` 在多處以 **TWII (TAIEX) full-sample 1997–2026 GJR-GARCH(1,1)
γ = 0.272, t = 3.18**（n≈7148 天）作為 headline leverage 參數：
- Abstract（main_v2.tex 舊版直接寫 `γ = 0.272, t = 3.18`）
- Table 1 描述統計（body_v3.tex L51 `TWII (1997--2026) ... 0.272 & 3.18`）
- Table 2 tab:gamma（body_v3.tex L146 `TWII (TAIEX) & 0.272 & 3.18`）
- 「diversification amplification ≈ 4.3×/5.0×」敘事以 0.272 為分子

但 `reproduce_report.json` 早已標此格為 **HIGH severity divergence**：
「Paper value exceeds any K892 rolling window; source unidentified」。
`reproduce.py`（L192–200）以 NOTE 級 footnote 辯解，聲稱「0.272 來自 1997–2026
long-sample specification」— 本稽核直接檢驗此辯解是否成立。

## 方法

從**兩個已 commit 的離線 CSV** 拼出 1997–2026 TWII 收盤序列：
- `paper/taiwan-vt/data/_twii_1997_2007_snapshot.csv`（date, twii_close；1997-07..2007-12）
- `paper/taiwan-vt/data/0050_tw_twii_..._2008-2026.csv` 的 `twii_close` 欄（2008-01..2026-07）

兩檔日期邊界無重疊（snapshot 末列 2007-12-31，主檔首列 2008-01-02；code-reviewer 實測確認）。
Spec：GJR-GARCH(1,1) constant-mean normal QMLE，Bollerslev–Wooldridge robust SE
（對齊論文 index 行「full-sample MLE」慣例）。純 in-sample fit，無 lookahead 疑慮。

## 結果

| 項目 | γ | t(γ) | n | 來源 |
|---|---|---|---|---|
| **論文宣稱** | **0.272** | **3.18** | 7148 | 無活來源（此稽核推翻）|
| 本重估（1997–2026） | **0.1047** | 5.31 | 7106 | 本 experiment results.json |
| K892 full_sample（獨立）| **0.1090** | 5.62 | 7044 | experiments/k892/..._results.json |

**兩條獨立資料源 + 獨立腳本一致收斂於 γ ≈ 0.105–0.109**（Δ vs 論文 = −0.167）。

## 結論（code-reviewer PASS）

1. **論文 headline TWII γ = 0.272 無法重現**，且與論文自身引用的 K892（full_sample γ=0.109）**矛盾**。
2. `reproduce.py` 的「0.272 = 1997–2026 long-sample」辯解 **factually false**：1997–2026
   long-sample 實測 = 0.109，不是 0.272。此 NOTE 級掩蓋了一個真實錯誤，違反 provenance 完整性。
3. 可重現的 canonical full-sample TWII γ = **0.105–0.109**（本 experiment + K892 一致）。
4. 0.272 疑為 gate 上線前某舊 vintage / 錯 spec 的 orphan 值 —— **禁造假湊舊值**，改用可重現值。

## 修正清單（等 owner sign-off，不擅改 headline）

影響 headline 數字 + 槓桿放大敘事 magnitude，屬 narrative-affecting change，依 narrative
state machine **不由單一 fire 擅自改 body**。建議修正：

- [ ] **Table 1 (L51)**：`TWII (1997--2026) ... 0.272 & 3.18` → `0.109 & 5.62`（K892 canonical）
- [ ] **Table 2 (L146)**：`TWII (TAIEX) & 0.272 & 3.18 & 0.012 & 0.870 & 0.990` → 全列以
      K892 full_sample 重估值替換（γ=0.109, t=5.62, persistence=0.985）
- [ ] **Abstract / body_v3 L14 L136**：`γ = 0.272, t = 3.18` → `γ = 0.109, t = 5.62`
- [ ] **放大倍數重算**：0.272 → 0.109 會使 index/stock γ-ratio 下降（0.109 / 0.037 ≈ 2.9×，
      非 4.3×）；amplification 故事**質性仍成立**（index γ > 個股均值）但 magnitude 需全面下修，
      abstract / sec:leverage / 4.3× / 5.0× 均連動。
- [ ] **reproduce.py**：移除 false「1997–2026 long-sample = 0.272」NOTE 辯解，重分類為
      RESOLVED（指向本 experiment + K892），regen reproduce_report.json。

## 檔案

- `reestimate.py` — 重估腳本（code-reviewer PASS）
- `results.json` — 重估輸出
- 交叉驗證：`experiments/k892/k892_verify_tw_gamma_results.json`
