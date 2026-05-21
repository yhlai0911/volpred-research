REJECT

**BLOCKING**
1. **閾值定義存在明顯內生校準，核心結論屬「先定答案再驗證」**（Abstract lines 36, 60；§2.4 lines 121；§3.4 lines 218, 243；§3.6 lines 279, 305；Conclusion lines 367-368）。文中反覆強調 Sharpe-only detector 是「calibrated to the standalone VT benchmark」且能「exactly」重現 70% VT threshold。這不是外生識別，而是用為了重現既有 headline 而設計的 detector 來再次得到同一 headline。若核心貢獻是「VT-specific vs family-level threshold」，則 threshold detector 必須在分析前由理論或獨立準則給定，而不是以重現既有 70% 結果作為 calibration anchor。否則 cross-strategy ordering 的有效性不足。

2. **同一 baseline cell 的 TF/MR threshold 在文內自相矛盾，卻仍被拿來支持 5/5 robustness claim**（§3.4 Table 3 lines 220-245；§3.6 Table 4 notes lines 290-300, 305-307）。同樣的 cell1 microstructure，Table 3 給 TF=20%、MR=20%，但 Table 4 note 又承認 OAT baseline 用 M=200 時變成 TF=30%、MR=70%。這不是小誤差，而是 central result 對 MC count 與 adoption grid boundary 高度敏感。更嚴重的是 line 305-307 仍宣稱「5/5 OAT cells preserve ordering」並將其包裝為 robustness。若同一 cell 的 threshold magnitudes 可從 20% 跳到 70%，則文中的 threshold 比較不具可再現性，至少目前證據不足以支撐「family-level threshold 已被建立」。

3. **統計推論與信賴區間建構前後不一致，且主要 CI 做法不適合支持文中精確門檻敘述**（§3.1 Table 1 notes lines 156-157；Figure 1 caption lines 167-168；§3.3 lines 213-214）。Table 1 note 說 95% CI 來自「pooled return distribution within each adoption cell」的 iid bootstrap，明確不是 simulation-level Sharpe 的 between-simulation uncertainty；但 Figure 1 caption 又說 whiskers 是「95% bootstrap CIs from 500 Monte Carlo simulations per adoption level」，兩者不是同一件事。再者，Sharpe ratio 是 path-level statistic，將 500 條長度 2520 的 simulated paths 全部攤平成 126 萬日報酬後做 iid bootstrap，會忽略 path dependence 與 time-series dependence，不能支撐文中對 50%/70% tipping zone 的精確判讀。line 156 還出現「1.26M days × 500 sims」的樣本數自我重複計算。核心門檻推論的統計基礎目前不成立。

4. **NoiseControl 不是有效的 falsification/control，無法支持「positive-feedback 而非大規模協同行為」這一識別主張**（§2.1 lines 97-99；§3.4 lines 245-246；§3.7 lines 360）。NoiseControl 被設成固定權重 0.5，實際上幾乎沒有持續再平衡流量；這與 VT/TF/MR 的動態交易強度根本不匹配。它因此無法檢驗「只要有足夠大的 coordinated trading block 就會不穩定」這個對立假說，因為你拿來對照的是一個幾乎不交易的 treatment。若要做 falsification，至少需要一個非正回饋但交易強度、持倉變動幅度、再平衡頻率可比的 active control。

**MAJOR**
1. **MR 被歸類為「positive-feedback family」的概念基礎很弱，策略設計也不像文獻中的標準短期反轉**（§2.1 lines 90-97；Introduction lines 54-56）。你定義的 MR 是對 22-day cumulative return 的 sign-flipped momentum，這更像一個任意反號的 time-series rule，而非 Lehmann/Lo-MacKinlay 脈絡中的標準短期反轉設計。更關鍵的是，MR 在 line 95 才以「若價格跌後買盤大到足以再觸發反向 cascade」來論證其正回饋性，這是二階、條件式、模型特有機制，不是與 VT/TF 對稱的一階正回饋。若 MR 的機制本質不同，則「family-level」標籤被誇大。

2. **多處事實或數值宣稱沒有足夠證據，且有外推過度問題**（Abstract line 36；Introduction lines 54, 60；Discussion lines 323, 327, 367-369）。例如「VT remains the empirically dominant case (largest AUM, real-world deployment)」、「current levels below 5%」、「ESRB and FSOC could incorporate adoption metrics」都沒有直接可驗證證據或適當 citation。對 top journal 來說，模擬論文可以討論 policy relevance，但不能把未被本文估計或未被文獻嚴格支持的實證量級，寫成近似既定事實。

3. **100% adoption 的定義與 population accounting 不一致**（§2.1 lines 72, 99）。line 72 先說組成在 \(\phi<80\%\) 時才「well-defined」，但又說在 100% adoption 時「all non-noise agents are strategy-treatment agents」；line 99 又把 \(\phi\) 定義為 \(N\) 中使用 active treatment 的 fraction。若 noise traders 固定為 200，則 100% adoption 實際上只可能是 800/1000 的非噪音代理被替換，不是 treatment agents 真占全體 \(N\) 的 100%。這會直接影響 adoption 軸的經濟意義與外部解讀。

4. **將 cell3 的 MR「null」硬編碼為支持 H1+ ordering，屬後設分類規則替代實證結果**（§3.6 Table 4 note lines 299-300）。MR 在高 \(\lambda\) 下因 10% baseline 已經極度負 Sharpe（-5.56）而不再觸發 detector，這本身說明 detector 在 loss-making regime 失效；文中卻把這個 null 用 rank encoding 視為「MR threshold ≥ VT threshold」，再納入 5/5 ordering robustness。這不是穩健性，而是把不可比較情形算成支持主張。

5. **Design validation 的「52% degradation 來自 liquidity evaporation」表述過度精確**（Introduction line 60；§3.6 lines 312-315；Conclusion line 367）。這個 52% 只是用兩個 Sharpe drop（0.25 vs 0.13）做比率分解，但模型同時改了 adoption-to-liquidity mapping，並未做正式 decomposition 或 counterfactual identification。可說「liquidity scaling materially matters」，但不能把 52% 寫成接近識別出的結構份額。

**MINOR**
1. **Table 1 note 有明顯數值表述錯誤**（§3.1 line 156）。「1.26M days × 500 sims」重複乘上 500；每 cell 本身就是 500 sims × 2520 days = 1.26M observations。

2. **flash-crash 敘述與表格不完全一致**（§3.1 line 157；§3.2 lines 173-179）。Figure 2 caption 說 kurtosis jump「matching the flash-crash frequency spike」，但 Table 1 的 Flash/yr 僅從 1.09 升到 1.20，作者自己在 footnote 又承認 100% row 有 measurement artifact。這裡措辭應收斂。

3. **line 95 的極端價格崩到 \(10^{-23}\) 被直接稱為 legitimate finding，缺少足夠診斷**（§2.1 line 95）。至少需要說明是否受 lower bound、浮點數、或 return compounding convention 影響，否則讀者合理懷疑是數值退化而非經濟機制。

4. **引用與主張有若干鬆動**（Introduction lines 54-58）。例如用 `cole2017` 支持「over USD 2 trillion」與 VT/vol-sensitive AUM 規模，來源是研究報告而非可審核資料庫；用 `asness2013` 來支撐 trend-following 類型也較間接。這些不是致命，但會削弱說服力。

整體看法：這篇稿件有一個可發展的問題意識，但目前 central identification、threshold estimator、falsification design、以及 robustness 敘事都還不夠乾淨，且內部一致性不足。若不重做 threshold 定義與 active control 設計，我不認為目前版本能支持「family-level threshold」這個主結論。
