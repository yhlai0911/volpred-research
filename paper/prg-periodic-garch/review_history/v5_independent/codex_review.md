REJECT

**BLOCKING**

1. **核心比較存在資訊集與預測時點不對等，無法識別「結構優勢」**（Section 2.2–2.4, lines 112–139; Table 1 note, lines 205–205; Discussion, lines 346–346; Abstract, line 41; Conclusion, lines 360–362）  
主文已明確承認 PRG 的全日預測是兩階段形成：`h_{d,0}` 於 `d-1` 收盤後、`h_{d,1}` 於 `d` 開盤時在觀察到當日 overnight return 後更新；相對地，GJR/HAR 被限制在較弱的 `\mathcal F_{d-1}^c` 資訊集下比較。這表示六市場主結果混合了「模型形式差異」與「額外資訊/較晚決策時點」兩種效果，無法把 Table 1 的 PRG-vs-GJR 優勢解讀為結構性勝利。更嚴重的是，文中卻反覆將此結果表述成 PRG 本身的 forecasting dominance 與 first-order structural contribution。這是識別問題，不是措辭問題。

2. **所謂 “fair-information GJR-X” 並不公平，關鍵宣稱被自己的方程式推翻**（Section 4.5, lines 306–313; Eq. (10), lines 307–310）  
文中聲稱「PRG 與 GJR-X consume identical session-level information」；但 GJR-X 使用的是 `r^2_{\text{overnight},t-1}`，PRG 在 Eq. (8) 使用的是**當日**已實現的 `r^2_{d,0}` 來形成 `h_{d,1}`。兩者資訊集不同，因此 line 311 與 line 313 的“structural, not informational”結論不成立。若要做公平對照，基準模型也必須在 `d` 開盤時取得同一個當日 overnight realization，否則此節不能支持論文的主識別主張。

3. **開盤可交易性與 lookahead 敘事未被證成，經濟價值結果因此不可信**（Section 2.2, lines 113–124; Table 4 note, lines 297–297）  
`r_{d,0}=\log(P_d^o/P_{d-1}^c)` 需要觀察到 `P_d^o` 才能計算；但文中同時聲稱可在「day-`d` open」用包含 `r_{d,0}` 的 full-day forecast 進行再平衡，甚至暗示可用 opening price 本身交易。這在市場微觀結構上並不自動成立：你通常要先等開盤撮合價格出現，才知道 `P_d^o`；一旦知道該價格，是否還能在同一開盤價成交，必須明確說明 auction participation / order submission protocol。現在的寫法把“觀察到開盤價”與“用同一開盤價成交”混為一談，等於把 implementability 當作已證事實。Table 4 的 VT 結果因此有可執行性偏誤。

**MAJOR**

4. **統計顯著性標準的引用與方法論敘述有問題**（Section 2.4, lines 139–139; Abstract, line 41; Introduction, line 63; Results, lines 209–209; Table 5 note, lines 335–335）  
全文把 `|t|>3.0` 說成來自 `Harvey et al. (2016)` 且「現在是 volatility forecasting / MCS literatures 的標準門檻」。這個說法至少在文內沒有被證成，且 `Harvey et al. (2016)` 並不是 Diebold–Mariano 檢定門檻的經典來源。你可以選擇更保守的判準，但不能把它包裝成該文獻所建立、且已是此文獻脈絡下的標準規則。這屬於 citation misuse，也影響全文 PASS/FAIL 敘事。

5. **VaR / ES 的強結論沒有足夠證據支撐**（Abstract, line 41; Section 4.3, lines 245–273）  
摘要寫「PRG also dominates in VaR and Expected Shortfall evaluations」；line 273 更說「一致排序 across all six markets for both VaR and ES」。但 Table 3 只完整展示了極少數模型/市場，ES 的 FZ DM 統計甚至只給 SPY 一個值，其餘大量留白。這不足以支持“all six markets”“consistent ranking”“dominates”這種全面性陳述。現有證據最多支持「部分市場、部分比較下表現較佳」。

6. **從單一市場 ablation 推廣到一般機制的結論過強**（Section 4.2, lines 217–241; Conclusion, line 360）  
SPY 的 ablation 很有資訊量，但 line 239 把它解讀成「session-boundary information transfer is the sole driver」，line 241 又把 PRG-vs-Separate 視為跨市場 generalization，這仍然過度。Ablated PRG 與 Separate GARCH 不是同一個對照；前者改變的是模型內更新，後者是另一組雙方程 benchmark。你可以說證據「一致支持 bridge 很重要」，但不能據此斷言它是「唯一」或「全部」機制。

7. **“HAR dominance over GJR is largely a target-mismatch artifact” 的外推超過證據**（Introduction, line 63; Results, lines 213–213; Conclusion, line 360）  
這個命題被寫成對“prior literature”的一般性修正，但文中實際展示的核心數字只有 TAIFEX 上的 `DM t = 0.57`。即使該案例成立，也不足以支持“previously documented HAR dominance… is largely an artifact”這種廣泛文獻裁決。

**MINOR**

8. **TAIFEX 的 MCS 描述前後不一致**（Table 1, line 195; Results, line 211）  
Table 1 的 MCS 欄寫的是 `PRG only`，但正文說「only the PRG Basic and PRG Extended survive」。若 MCS 存活者有兩個模型，表內應明確列出，否則讀者會誤解成只有一個 PRG 規格存活。

9. **若干機制性解釋缺少直接證據或引用**（Results, line 182; Discussion, lines 344–350）  
例如 GLD「absence of an equity-like asymmetric volatility effect in gold」、以及 TAIFEX/OHLC proxy “quantitatively similar” 等說法，目前在文內沒有對應表格、附錄或文獻支持。這些可作為推測，但不宜寫成已證結論。

10. **經濟價值段落缺少正式統計檢定**（Section 4.4, lines 277–301）  
Sharpe、Sortino、MDD 的改善幅度有報告，但沒有 Sharpe difference test、bootstrap CI 或交易成本敏感度的正式表格。對 FRL/JBF 類審稿標準而言，這使經濟顯著性的說服力偏弱。

整體而言，本文最大問題不是模型想法本身，而是**主結果的識別設計與可交易時點敘事沒有站穩**。在目前版本下，我無法接受作者把六市場 QLIKE 勝利與 GJR-X 結果解讀為「PRG 的結構優勢已被乾淨識別」。如果作者重寫比較框架，明確區分 `d-1` 收盤 forecast、`d` 開盤 update forecast、以及真正可執行的交易時點，並提供同資訊集下的公平 benchmark，稿件才有重新評估的基礎。
