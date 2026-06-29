# K1580 Codex Code Review

Reviewer: Codex CLI (gpt-5.4), primary-path review（非 fallback）

## v1 review → CONDITIONAL_PASS（6 點）
無造假、無硬性 lookahead，核心結論成立。要修：
1. 同日收盤被寫成「決策時已知」不精確 → 改「理想化同日收盤(MOC)執行假設」。
2. 建倉成本沒進 CAGR（分母用 value.iloc[0]）→ 改用 INITIAL 為分母。
3. 再平衡成本為近似（非嚴格 self-financing）→ 加 fixed-point 迭代。
4. 年度序列漏首年（resample 後 pct_change 丟首年）→ anchor 期初淨值補回。
5. sector ETF「無 survivorship」說太滿 → 改「降低個股偏差，非完全無偏」。
6. 缺 README + data_source metadata → 補。

## 最終複審 → CONDITIONAL_PASS（4 點，全為措辭/metadata，無計算 bug）
**已確認到位**（Codex 合成資料驗證）：`_metrics(initial=INITIAL)` 建倉成本進績效、三腿一致；
`_simulate` fixed-point 收斂（residual 近零）；`_annual_returns` 首年納入無重複；
`_basket_window` 無 off-by-one；`clean_tw50_data` 只清 0050 benchmark 不誤清個股。

修正項（已全部落地）：
1. docstring/labels 殘留「決策時已知」「無存活者偏差」措辭 → 已統一改正。
2. 結論措辭「6 籃子全部略輸/打平」不精確 → 改「無顯著穩健 alpha；CAGR 點估計混合偏正，
   5/6 籃子持平或略高，只有台股 0050 略低（存活者偏差）」。
3. subperiod bootstrap 補 `boot_low_power=True` + `boot_note`（短窗+多重比較 power 低）。

## Verdict
**CONDITIONAL_PASS** — 計算正確、無 lookahead、結論誠實（NULL / regime-dependent）。
所有 reviewer 指出的措辭與 metadata 問題已修正。可寫 knowledge / 報告文。
