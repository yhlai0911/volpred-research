凍結核對通過：

- `.py`: `302efae4a0ea6064d793cef9266b6982ebab8e3e7723db34d0c0fff697184f43`
- `results.json`: `c6e63d449c7e6722884dcb3935d8eaeabfb0505d2e8596d959f403a683a2c85e`
- `README.md`: `9fa30a8663a439f0f8822016634c72c9bae475d3e3158ef079f13fbf3c5e2ee7`

1. Lookahead／洩漏：FAIL

- PASS：`ret_lag1..5` 使用 `r.shift(k)`；momentum 與 volatility-adjusted momentum均截至 \(t-1\)（py 198–210）。
- PASS：`rv_d/w/m`、EWMA 全部明確 shift（py 212–220）；high-vol regime 僅使用截至 \(t-1\) 的 RV（py 225–228）。
- PASS：星期 dummy 是預測日 \(t\) 的已知日曆資訊，不需 shift（py 230–233）。
- PASS：GARCH 的時間遞迴本身 causal：每塊只以 `rs[:start]` 估計，先產生 \(\sigma_t\)，再以 \(r_t\) 更新下一日狀態（py 155–183）。
- PASS：StandardScaler 位於 Pipeline（py 250–255），每塊只對 `[:start]` fit；測試列為 `[start:end]`（py 264–279）。初訓1000列、63日重訓與 results 設定一致（results 4–10）。
- FAIL／blocking：GARCH 失敗處理不是宣稱的「no silent fallback」。程式全域關閉 warnings（py 45），不檢查 `arch` 的 convergence flag；只有 exception 才記錄警告（py 160–171）。若參數非有限，`used_garch=False` 後會直接進 EWMA，沒有 log（py 169、179–182）；有限性檢查還漏掉 `mu` 與 `resid_prev`。若其為 NaN，後續特徵可能被 `dropna()` 靜默刪除（py 239–240）。results 也沒有逐資產／逐塊 convergence、fallback 或刪除診斷，與 README 70、117 的明確宣稱衝突。

另有非阻斷揭露問題：GARCH 先消耗原始1000日，對齊後分類器又初訓1000列，因此第一次方向 OOS 約在原始序列第2000日，而不只是讀者容易理解的「約四年後」（py 155、239–240、273）。

2. 檢定正確性：FAIL

- PASS：PT 的 \(P\)、\(P^*\)、有限樣本方差與右尾 p 值公式正確（py 286–307）。
- PASS：DM 使用 `d = loss_benchmark − loss_model`，正值代表模型較佳；benchmark 確為 always-up 的0/1 loss（py 324–333、456–459）。
- PASS：loss differential 的均值檢定使用 statsmodels HAC/Newey–West，lag 規則明載於 py 310–321；DM 單尾方向與「模型較佳」假說一致。
- PASS：binomial vs 0.5、vs majority，以及 always-up base rate 有分欄保存（py 442–459；results 39–50等）。
- FAIL／blocking：README 將「模型較佳」右尾 DM p≈1 解讀為模型「顯著較差」（README 136–137、154–155、196–197）。反尾檢定後，0050 logistic 與 GB 的 p 分別約為 `0.0670`、`0.0792`（results 217–218、250–251），5% 水準並不顯著。正確結論是「8/8 未顯著優於 always-up；6/8 顯著較差」，不是8/8顯著較差。
- 非阻斷：`binom_p_vs_majority` 把由同一 OOS 樣本估出的 majority rate 當固定成功機率，並非嚴格的 exact out-of-sample benchmark test；不宜作核心推論。

3. 多重檢定校正：PASS

- 四資產 × 二模型的8條 PT p 值全部收集（py 603、626–631），再整批套用 BH 與 Bonferroni（py 649–673）。
- results 361–405顯示 raw顯著1/8、BH 0/8、Bonferroni 0/8；最小調整後 p 均為 `0.3496265`。
- README 139–144的數字與 results 一致。
- 但 README 146稱校正後不顯著「證明」該結果是假陽性，屬統計過度推論；只能說未通過校正，不能證明其必是假陽性。

4. 交易成本：PASS

- `pos∈{−1,+1}`；`turnover=|pos_t-pos_{t-1}|`，完整翻倉為2單位，首日計入建倉成本（py 339–351）。
- US 2bp、TW 5bp設定正確（py 63–73），2×成本亦正確計算（py 359–367）。
- 我以 results 復算所有八組：
  `net_ann_return = gross_ann_return − 252 × cost × avg_daily_turnover`，誤差皆僅浮點等級 \(<10^{-16}\)。
- README 176–185的 gross/net/2×/buy-hold Sharpe及換手與 results 逐格一致。
- 非阻斷：results 未保存每日 prediction、return、position及cost序列，因此只能核對表格與年化報酬恆等式，無法從凍結 JSON 獨立重算 Sharpe 分母。README「0個贏buy-hold」實際比較的是 Net Sharpe（py 678–682），措辭應限定為此指標。

5. 數字一致性：PASS

- SPY logistic：hit `0.536798`、PT `1.1351 (0.1282)`、DM `−2.1633 (0.9847)`，README 127與 results 34–50一致。
- QQQ logistic：hit `0.543910`、PT `0.8453 (0.1990)`、DM `−2.0303 (0.9788)`，README 129與 results 118–134一致。
- QQQ GB：raw PT p=`0.04370`、BH=`0.34963`，README 130與 results 164–180一致。
- 波動 QLIKE改善可由 results 中 HAR／benchmark QLIKE精確復算：SPY `22.63%`、QQQ `19.87%`、0050 `−0.32%`、TWII `14.72%`（results 98–104、182–188、266–272、350–356），與 README 163–166一致。
- 0050.TW OOS \(R^2=-0.995\%\) 亦正確揭露。

6. 結論強度：FAIL

- README 194稱「NULL，證實假說」，README 146稱不通過校正「證明」是假陽性。Failure-to-reject 不能證實不可預測；本實驗至多證明這兩種模型與這組特徵未找到穩健 edge。沒有 equivalence test、最小經濟效果界線或檢定力分析，不能把未拒絕提升為「證實 NULL」。
- 「波動率明顯可預測」只有 OOS \(R^2\) 與 QLIKE 點估，沒有對 loss differential 做 HAC DM、bootstrap或其他正式顯著性檢定。證據只支持「本樣本中3/4資產的 HAR 點估優於 expanding-mean benchmark」，不足以正式證明「明顯可預測」。
- 0050.TW 的負 \(R^2\) 與負 QLIKE改善已在 README 165、170–172誠實揭露；但「不影響整體結論」仍需要正式跨資產推論，不能由3/4正點估直接推出。
- 圖 `direction_vs_vol_predictability.png` 的標題直接寫成「variance is predictable OOS; sign is not」，同樣超出目前僅有的點估與不拒絕證據。

Blocking defects：

1. GARCH convergence／非有限參數可能靜默失敗或回退，且凍結結果缺乏逐塊診斷，違反明示的 no-silent-fallback 要求。
2. DM 單尾 p 值被錯誤解讀為8/8模型「顯著較差」；實際僅6/8在反方向5%檢定顯著。
3. 把多重校正後不顯著寫成「證實 NULL／證明假陽性」，且未以正式推論支持「波動率明顯可預測」。

VERDICT: FAIL
