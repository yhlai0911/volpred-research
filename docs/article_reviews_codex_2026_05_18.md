# Codex 24h-Rule 文章審查報告
**審查日期**: 2026-05-18
**審查工具**: Codex CLI (codex-cli 0.130.0, gpt-5.4, ChatGPT auth)
**審查類型**: 3-model review discipline — Codex 部分
**文章類型**: experiment_id=null（無對應實驗代碼），聚焦 writing quality + methodology claim accuracy

---

## 1. mile_8d1c7528 — 處置效應與波動率：行為金融的視角好聽，但對預測沒幫助

**verdict**: CONDITIONAL_PASS

**key findings**:
1. **措辭錯誤（P0）**: 文章已發布版本寫「卡方達顯著水準（顯著性 0.72）」，但 p=0.72 明確是未達顯著（卡方 0.13）。措辭自相矛盾，傷可信度，需修正。
2. **過度宣稱**: 「CGO 只是過去報酬的偽裝」「90% 以上來自共線性」「絕對沒有變好」等措辭比實際證據更強。相關係數 0.889 顯示高度共線但非「幾乎是同一個變數」；DM t=-1.81 (p=0.07) 是「無可靠增量證據」而非「確定無效」。
3. **方法主架構可信**: QLIKE 定義（越小越好）、lookahead 處理（rv.shift(-1)）、OOS refit（21 天窗口）均正確。VIX 控制合理。OOS 502 天足夠基本 horse race，但不足以作「結構性無效」強判。

**需修正項目**: (1) 修正 p=0.72 的顯著性措辭；(2) 降低「偽裝」「絕對」等過強主張語氣；(3) QLIKE 方向在文中需明確說明（越小越好）。

---

## 2. mile_5061e209 — 用「相變理論」預測股災？21 年 15 次崩盤實測：複雜統計指標贏不了 VIX

**verdict**: CONDITIONAL_PASS

**key findings**:
1. **數字錯誤（P0）**: 文章標題/正文寫「5,346 天測試」，但同一段表格與實驗結果檔均為 `4,687` 個交易日。另外文章寫 bootstrap 1,000 次，但程式實際使用 OOS AUC CI 2,000 次、AUC difference 5,000 次。
2. **Bootstrap CI 解讀不足**: incremental AUC CI = [-0.072, -0.010] 整段在負值，代表 composite **顯著劣於 VIX**；文章將其寫成「沒有統計上顯著的改善」過度輕描，應寫「在此 bootstrap 設定下 composite 出現顯著劣化」。
3. **統計功效與機制宣稱均偏強**: 70/30 OOS 切點約在 2019-11-05，測試集僅含 5 個 crash episodes；對 9 指標 logistic 而言功效偏弱，「VIX 已把這些訊號吃進去了」係 plausible explanation 非已識別機制。

**需修正項目**: (1) 修正 5,346→4,687 天；(2) 修正 bootstrap 次數描述；(3) 更正 CI 解讀方向；(4) 將 VIX absorb 機制從定論降為假說。

---

## 3. mile_7ba7ee54 — 看似有效、其實只是搭了多頭便車——台積電財報事件交易策略的誠實檢視

**verdict**: FAIL

**key findings**:
1. **論證鏈條不完整（核心問題）**: 文章用「A 策略」(事件後加碼) 的全樣本 NW t≈3.70 建立「表面顯著」的 framing，但後面用來否定它的 OOS 切片、bootstrap CI、交易成本、月勝率，全部對象都換成了「C 策略」(前減後加組合)。「A 的顯著主要只是多頭便車」這個核心論點在文內未被直接證成，只證成了「C 不穩健」。
2. **統計口徑錯置**: 文章以「NW t=3.70 背後對應的效應大小其實小到 CI 吃進零」串聯 A 和 C 的結果，但 NW t 是 A 策略的 HAC 修正 t 值；CI [-0.155%, +1.195%] 是 C 策略的 iid resampling 年化均值區間。兩者不是同一 estimand，不能直接拿來做此結論。
3. **事件日近似過度精確**: 文章寫「可能有 ±1 日落差」，但程式只是機械設定每月 10 日，未驗證真實公告日，±1 日的量化描述無實際依據。

**需修正項目**: 最低要求—(1) 固定全文分析對象為同一策略（A 或 C 擇一）；(2) 對同一策略補齊 full-sample / OOS / bootstrap / 成本 / 月勝率的完整檢驗；(3) 移除量化事件日誤差的敘述。此篇目前無法作為完整論文發佈，需重做局部分析。

---

## 4. mile_27038b04 — VIX 是全球恐慌指標，但 12/VIX 策略只在美股奏效——四大市場實證

**verdict**: CONDITIONAL_PASS

**key findings**:
1. **EEM 顯著性被高估**: Bootstrap 使用 i.i.d. resampling 未處理報酬時序相依，也未做多重比較校正（4 市場 × 2 策略 = 多個假設）。EEM CI = [-0.3535, -0.0036] 僅勉強低於 0（邊界顯著），在 Holm/Bonferroni 校正後大概率不再顯著。文章寫「確實顯著輸給」語氣過滿。
2. **12 的參數來源後設合理化**: 「12」在程式中是固定常數，無理論依據。文章將其解釋為「因 SPY 長期 VIX 均值約 19-20 所以平均 60-70% 部位」屬事後合理化，非設計依據。VolAdj 版本合理但屬 ad hoc 工程校正，不能包裝成「更公平的正式 benchmark」。
3. **二元敘事過度簡化**: 「VIX 是全球指標但只在美股奏效」的對立框架遮蔽了更精確的版本：VIX 與各市場實現波動相關性高（0.609-0.813），但直接轉化為配置權重時 SPY 的 Sharpe 優勢本身也未達顯著（CI 包含 0）；非美股主要效益在回撤保護。

**需修正項目**: (1) 降低 EEM 顯著性措辭；(2) 補充多重比較校正討論；(3) 修正 12 的參數說明；(4) 收斂二元敘事為更精確的條件性結論。

---

## 5. mile_50a70b23 — 把波動率拆成長期與短期，真的會比較準嗎？DMEM 雙乘子模型實測

**verdict**: CONDITIONAL_PASS

**key findings**:
1. **Claim 與實作不一致**: 文章寫 DMEM「以 22 日已實現變異數帶動」長期成分，但 K776 實際 target 是 `E[|r_{t+1}|]`（絕對報酬），長期成分也是 22 日平均絕對報酬 `|r|`，不是 `r²` 或高頻 RV。文章描述框架（QLIKE 在「真實波動 proxy 上的比較」）與實作有落差，需修正。
2. **α_g=0 結論缺乏統計支持**: 文章寫「短期 ARCH 係數 α_g = 0」作為「退化」的強結論，但結果 JSON 只有點估計，無標準誤、t-stat 或 boundary/Wald test。僅能寫「α_g 估計值貼至下界 0，暗示 short-run ARCH 項可能不活躍」。
3. **方法描述不精確**: 資料來源與方法節寫「重抽樣比較 + 嚴格統計檢驗門檻」，但程式實際使用 DM test with HAC variance（無 bootstrap/resampling）。OOS 天數、三段切片、calm/crisis 各 1,082 天均正確，核心數字可信。

**需修正項目**: (1) 修正長期成分的描述（22 日平均 |r| 非 RV/r²）；(2) α_g 退化結論降階為點估計觀察；(3) 方法節中「重抽樣比較」改為「DM test with HAC variance」。

---

## 彙總

| id | title (縮) | verdict |
|---|---|---|
| mile_8d1c7528 | 處置效應與波動率 | CONDITIONAL_PASS |
| mile_5061e209 | 相變理論預測股災 | CONDITIONAL_PASS |
| mile_7ba7ee54 | 台積電財報事件策略 | FAIL |
| mile_27038b04 | VIX 四大市場實證 | CONDITIONAL_PASS |
| mile_50a70b23 | DMEM 雙乘子模型 | CONDITIONAL_PASS |

**審查人**: Codex CLI (gpt-5.4, 5 個獨立 session)
**備注**: 所有 CONDITIONAL_PASS 文章均已發布，建議在下次更新周期時按上述修正項目勘誤。mile_7ba7ee54 (FAIL) 需在修正論證一致性後才適合保留為已發布狀態。
