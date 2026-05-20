# Mag 7 Q1 2026 財報全解：source-attributed 重寫版（capex 數字、AI 變現節奏、與波動率連結）

> **更新註記（2026-05-08）**：本文為 **2026-05-06 原版的重寫版**。原版被 Codex paper review（2026-05-07）標記 1 CRITICAL + 4 MAJOR：
>
> - **CRITICAL**：Meta FY2026 capex prior 區間原文寫 \$114–118B，實際官方 disclosure 是 **\$115–135B**（已上修至 \$125–145B）。Source: [investor.atmeta.com Q1 2026 press release（2026-04-29）](https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-First-Quarter-2026-Results/default.aspx)。
> - **MAJOR**：原文用「hyperscaler 2026 年 capex 總計約 \$725B」並標 "all numbers from SEC 8-K"，但 \$725B 是 market analyst aggregate，**不是 SEC 8-K 直接揭露的數字**；MSFT AI +123% / Alphabet Cloud +63% 缺 claim-level 出處；"earnings healthy 縮水" 結論缺數學佐證。
>
> 本版按官方 press release 重新逐項標註出處，並加上 per-company net income vs capex 的具體數字 + 三張源自官方數據的圖表。

---

## 一、為什麼要逐 number 標出處：研究誠實的代價

原版本的核心錯誤不是 narrative 走偏，而是 **provenance 鬆散**：把 market estimate aggregate（\$725B）說成 "from SEC 8-K"、把 prior capex 區間記錯（\$114–118B vs \$115–135B）、AI growth 數字沒附 earnings call 出處。對學術讀者與專業投資人，這種「方向對但數字鬆」的寫法傷害的是長期可信度。本平台的研究誠實 §1（不可造假/虛構）+ §6（如實報告）要求的是 byte-level traceability，不是 narrative 順暢。

以下每一個 \$X 數字、% 數字均對應到具名來源（公司投資人關係頁面 / SEC EDGAR filing / 公開 earnings release）。Sources 欄位列在文末。

---

## 二、五家 Q1 2026 財報關鍵數字（逐項標 source）

| 公司 | 期別 | 營收 | GAAP 淨利 | 資料來源 |
|---|---|---:|---:|---|
| Apple | Q2 FY2026（截至 2026-03-31）| \$111.2B（+17% YoY）| \$29.6B | [apple.com/newsroom 2026-04-30](https://www.apple.com/newsroom/2026/04/apple-reports-second-quarter-results/) |
| Microsoft | Q3 FY2026（截至 2026-03-31）| \$82.9B（+18% YoY）| \$31.8B（+23% GAAP）| [microsoft.com/en-us/investor FY26 Q3 2026-04-29](https://www.microsoft.com/en-us/investor/earnings/fy-2026-q3/press-release-webcast) |
| Alphabet | Q1 2026 | \$109.9B（+22% YoY）| \$62.6B（+81% YoY）| [Q1 2026 earnings release PDF](https://s206.q4cdn.com/479360582/files/doc_financials/2026/q1/2026q1-alphabet-earnings-release.pdf) ／ [SEC 8-K Ex-99.1](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000043/googexhibit991q12026.htm) |
| Amazon | Q1 2026 | \$181.5B（+17% YoY）| \$30.3B | [ir.aboutamazon.com Q1 2026 release 2026-04-29](https://ir.aboutamazon.com/news-release/news-release-details/2026/Amazon-com-Announces-First-Quarter-Results/) |
| Meta | Q1 2026 | \$56.31B（+33% YoY）| \$26.8B（含 \$8.03B 稅務利益）| [investor.atmeta.com Q1 2026 release 2026-04-29](https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-First-Quarter-2026-Results/default.aspx) ／ [SEC 8-K Ex-99.1](https://www.sec.gov/Archives/edgar/data/1326801/000162828026028364/meta-03312026xexhibit991.htm) |

注：Apple 的「Q2 FY2026」對應曆年 Q1 2026（fiscal year boundary：Apple FY 自每年 10 月 1 日起算）；Microsoft 的「Q3 FY2026」同樣對應曆年 Q1 2026。Alphabet/Amazon/Meta fiscal year 與曆年一致。

---

## 三、Hyperscaler Capex：per-company 出處全列

原版用 \$725B aggregate 並錯標來源為 "SEC 8-K"。實際情況是：**\$725B 是 market analyst aggregate（多家賣方研究估值）**，不是任何單一 SEC filing 的 line item。以下逐家列**官方 disclosure**的 capex 指引：

| 公司 | Q1 2026 actual capex | FY2026 公司自身指引 | 較上次更新 | 出處（official） |
|---|---:|---:|---|---|
| Meta | 公司未拆季度（指引 raised） | **\$125–145B** | **上修自 \$115–135B**（CRITICAL fix）| [investor.atmeta.com Q1 2026 release](https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-First-Quarter-2026-Results/default.aspx) — 文中明列 "between \$125 billion and \$145 billion, up from a prior range of \$115 billion to \$135 billion" |
| Microsoft | **\$31.9B**（+49% YoY）| **約 \$190B**（含約 \$25B 元件漲價影響）| Q4 FY26 將續增至 >\$40B | [microsoft.com/en-us/investor FY26 Q3 webcast](https://www.microsoft.com/en-us/investor/earnings/fy-2026-q3/press-release-webcast) |
| Alphabet | **\$35.7B** | **\$180–190B**（上修自 \$175–185B）| 2027 預告 "significantly increase" | [Alphabet Q1 2026 release PDF](https://s206.q4cdn.com/479360582/files/doc_financials/2026/q1/2026q1-alphabet-earnings-release.pdf) |
| Amazon | **\$44.2B** | 約 \$200B（2026 年 2 月先期指引）| Q1 已超過季度線性化 | [ir.aboutamazon.com Q1 2026 release](https://ir.aboutamazon.com/news-release/news-release-details/2026/Amazon-com-Announces-First-Quarter-Results/) — Q1 capex \$44.2B 為 8-K Ex-99.1 揭露；FY2026 \$200B 為 2026-02 先期 guidance |

**4 家加總（公司官方 self-disclosed FY2026 上限）**：145 + 190 + 190 + 200 = **\$725B**。換句話說，原版引用的 \$725B 巧合地等於本季度上修後**4 家公司各自 FY2026 上限的算術加總**——這個數字本身在更新後可被 traceable 重建，但**它是「彙總自 4 家獨立 self-disclosed guides」而非「SEC 8-K aggregate」**——後者根本沒有這個聚合 line item。本版本明確改寫為前者表述。

![Mag 7 hyperscaler 4 家 FY2026 capex 指引：藍 bar 為官方公司自身 guide 區間，紅鑽為 Q1 2026 actual](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/mag7_q1_2026_capex_guide.png)

---

## 四、AI 變現速度：claim-level attribution

| Claim | 數字 | 出處（直接引用） |
|---|---|---|
| Microsoft AI 業務 +123% | annual revenue run-rate 達 \$37B，YoY +123% | [news.microsoft.com 2026-04-29](https://news.microsoft.com/source/2026/04/29/microsoft-cloud-and-ai-strength-fuels-third-quarter-results/) — Nadella 於 earnings call 明示；Q3 FY26 press release webcast 同步揭露 |
| Microsoft Azure 整體 +40% | Azure and other cloud services +39% constant currency / +40% reported | [microsoft.com/en-us/investor FY26 Q3 webcast](https://www.microsoft.com/en-us/investor/earnings/fy-2026-q3/press-release-webcast) |
| Alphabet Google Cloud +63% | Cloud 營收 \$20.0B，+63% YoY；backlog \$460B+ | [Alphabet Q1 2026 release PDF p.2](https://s206.q4cdn.com/479360582/files/doc_financials/2026/q1/2026q1-alphabet-earnings-release.pdf) ／ [SEC 8-K Ex-99.1](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000043/googexhibit991q12026.htm) |
| Amazon AWS +28% | AWS 營收 \$37.59B，+28% YoY（15 個季度新高）| [ir.aboutamazon.com Q1 2026 release](https://ir.aboutamazon.com/news-release/news-release-details/2026/Amazon-com-Announces-First-Quarter-Results/) ／ [SEC 8-K Ex-99.1](https://www.sec.gov/Archives/edgar/data/1018724/000101872426000012/amzn-20260331xex991.htm) |
| Meta 整體營收 +33% | \$56.31B，YoY +33%（自 2021 以來最快季度）| [investor.atmeta.com Q1 2026 release](https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-First-Quarter-2026-Results/default.aspx) ／ [SEC 8-K Ex-99.1](https://www.sec.gov/Archives/edgar/data/1326801/000162828026028364/meta-03312026xexhibit991.htm) |

![Q1 2026 各家 AI / Cloud 變現速度 YoY 排序，每筆 % 後面註明 source URL](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/mag7_q1_2026_ai_growth.png)

---

## 五、剝除非經常項：core profitability 的具體 math

原版說「earnings healthy 但縮水」缺數學。下表把已揭露的 one-time items 從 GAAP NI 中扣除，給出 **ex-items NI** 數字：

| 公司 | GAAP Q1 2026 NI | one-time item（揭露來源）| ex-items NI（核心）| 縮水比 |
|---|---:|---|---:|---:|
| Meta | \$26.8B | \$8.03B 稅務利益（US Treasury Notice 2026-7 對 corporate AMT 處理 R&D 資本化的更新；公司 explicitly 揭露「ex-tax-benefit EPS would be \$3.13 lower」）| **\$18.7B** | **−30.2%** |
| Amazon | \$30.3B | Anthropic 投資 mark-up \$16.8B 稅前 non-operating 利得（公司明列 "pre-tax gains of \$16.8 billion included in non-operating income from our investments in Anthropic"）| ex-tax 估約 \$13–17B（依稅率假設）| **約 −45% 至 −57%** |
| Alphabet | \$62.6B（+81% YoY）| 含 \$37.7B 股權證券利得（多為被投資公司 fair-value mark-up，非經常）| 估約 \$24–28B | **約 −55% 至 −62%** |
| Apple | \$29.6B | 無顯著一次性 | 同 \$29.6B | 0% |
| Microsoft | \$31.8B | 無顯著一次性（GAAP +23% / non-GAAP +20%）| 同 \$31.8B | 0% |

**結論**：剝除非經常後，Mag 7 已揭露 5 家中 **3 家（Alphabet/Amazon/Meta）核心 NI 顯著低於 headline**，其中 Alphabet 與 Amazon 的非經常成分都來自**對 Anthropic / 被投資 AI 新創的 fair-value mark-up**——這是 AI 投資週期一個重要訊號：**AI infra 投入產出（capex 端）尚未轉化為 cash flow 端的對應放大，但被投資 AI 新創的 equity 估值卻同步上修，把帳面 NI 推高**。對讀者的意涵是：**headline EPS surprise 的可持續性需要打 30–50% 折扣**。

數字驗證：Meta 的 \$8.03B 稅務利益由 [investor.atmeta.com Q1 2026 release](https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-First-Quarter-2026-Results/default.aspx) 直接揭露；Amazon 的 \$16.8B 非經常 Anthropic mark-up 由 [Q1 2026 earnings release](https://ir.aboutamazon.com/news-release/news-release-details/2026/Amazon-com-Announces-First-Quarter-Results/) 直接揭露。

![Q1 2026 GAAP 淨利 vs 季度 capex（Meta 用 FY26 guide /4 作 proxy），灰色斜紋區為 GAAP 淨利中的非經常成分](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/mag7_q1_2026_ni_vs_capex.png)

---

## 六、與本平台波動率研究的連結

以下是 Q1 2026 財報季在 vol regime 上的觀察與**本平台已完成 K 實驗**的連結：

1. **Hyperscaler capex 巨幅上修（Meta \$115–135B → \$125–145B）導致財報日 vol 不對稱反應**：Meta 雖然營收 +33% beat，但因 capex 上修股價當日下跌 ~10%（[Fortune 2026-04-29 報導](https://fortune.com/2026/04/29/meta-zuckerberg-145-billion-ai-spending-roi/)）。這呼應本平台 K877 的 "VIX 充足性" 命題：在 idiosyncratic capex shock 下，事件後個股 vol 反應與大盤 VIX 可能脫鉤。

2. **AI 變現節奏 dispersion**：MSFT +123% / GOOGL Cloud +63% / AWS +28% 跨家 dispersion 約 4×，意味 NDX 內部 cross-sectional vol 在 AI 主題日將進一步分化。本平台 K1073 已記錄個股事件 vol 與指數 vol 的 spread 在事件密集期會放大。

3. **集中度風險**：Mag 7 合計約佔 SPY 市值 30%（市場 consensus 估計，非單一 SEC 出處）；本平台 K867 在 tail dependence 結構研究指出，集中度上升會使 traditional Gaussian-correlation risk model 低估極端共動風險——這在 5/20 NVDA 財報前後的 NDX vol surface 將是 testable 觀察點。

---

## 七、Codex review 修正前後對照

| 議題 | 原版（被 FAIL）| 重寫後 |
|---|---|---|
| Meta capex prior range | \$114–118B（**錯**）| \$115–135B（[Meta IR 直引](https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-First-Quarter-2026-Results/default.aspx)） |
| \$725B aggregate 出處 | "from SEC 8-K"（over-stating）| **4 家自身 FY2026 guides 加總**：Meta 145 + MSFT 190 + GOOGL 190 + AMZN 200，每數字附公司 IR 連結 |
| MSFT +123% claim | 無 attribution | [news.microsoft.com 2026-04-29](https://news.microsoft.com/source/2026/04/29/microsoft-cloud-and-ai-strength-fuels-third-quarter-results/) Nadella earnings call quote |
| Alphabet Cloud +63% | 無 attribution | [Alphabet Q1 2026 release PDF](https://s206.q4cdn.com/479360582/files/doc_financials/2026/q1/2026q1-alphabet-earnings-release.pdf) Cloud \$20.0B 直引 |
| "earnings healthy 縮水" | 無 math | 第五節 ex-items NI 表 + Meta −30% / Amazon −45 至 −57% / Alphabet −55 至 −62% 具體比率 |

---

## 八、研究誠實限制聲明

- 各 % YoY 與 \$ 金額**均對應公司官方 Q1 2026 press release（2026-04-29 ~ 04-30 公佈）或 SEC EDGAR 8-K filing**；FY2026 capex 指引以最新 earnings call / press release 揭露為準。
- Anthropic / 被投資公司 fair-value mark-up 是**會計處理**結果，非 cash flow；ex-items NI 數字基於公司在 press release 揭露的稅前金額與合理稅率假設，**不等同於正式 non-GAAP financial measure**。
- 本文不構成個股買賣建議；vol 連結段為市場結構觀察，不是 strategy backtest。
- NVDA Q1 fiscal 2027（曆年 Q1 2026 對應期）將於 2026-05-20 揭露，本文寫作時尚未公布，因此 Mag 7 中**僅 5 家**（Apple/Microsoft/Alphabet/Amazon/Meta）納入；Tesla Q1 2026 已於 4 月中先行揭露，不在本季度 4/29-30 主軸窗內。

## 九、資料來源（完整列表）

**官方公司財報：**

- Apple Q2 FY2026 press release, 2026-04-30: <https://www.apple.com/newsroom/2026/04/apple-reports-second-quarter-results/>
- Microsoft FY26 Q3 IR page, 2026-04-29: <https://www.microsoft.com/en-us/investor/earnings/fy-2026-q3/press-release-webcast>
- Microsoft Source blog (Nadella AI run-rate quote): <https://news.microsoft.com/source/2026/04/29/microsoft-cloud-and-ai-strength-fuels-third-quarter-results/>
- Alphabet Q1 2026 earnings release PDF: <https://s206.q4cdn.com/479360582/files/doc_financials/2026/q1/2026q1-alphabet-earnings-release.pdf>
- Alphabet SEC 8-K Ex-99.1: <https://www.sec.gov/Archives/edgar/data/1652044/000165204426000043/googexhibit991q12026.htm>
- Amazon Q1 2026 release: <https://ir.aboutamazon.com/news-release/news-release-details/2026/Amazon-com-Announces-First-Quarter-Results/>
- Amazon SEC 8-K Ex-99.1: <https://www.sec.gov/Archives/edgar/data/1018724/000101872426000012/amzn-20260331xex991.htm>
- Meta Q1 2026 release: <https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-First-Quarter-2026-Results/default.aspx>
- Meta SEC 8-K Ex-99.1: <https://www.sec.gov/Archives/edgar/data/1326801/000162828026028364/meta-03312026xexhibit991.htm>

**本平台相關研究：**

- K877: VIX 充足性 family（事件前緩升、事件後回落觀察）
- K1073: 跨資產 vol 比較（個股事件 vol 與指數 vol spread 在事件密集期放大）
- K867: tail dependence 結構（集中度與 Gaussian-correlation risk model 的偏誤）
- K129 / K301: VIX 對重大事件公告反應的前瞻性檢驗

**本文圖表本地檔（可版本化）**：`experiments/mag7_q1_2026_followup/{mag7_q1_2026_capex_guide,mag7_q1_2026_ni_vs_capex,mag7_q1_2026_ai_growth}.png`

**本次重寫驅動者**：Codex paper review 2026-05-07 對 mile_d716099a 的 1 CRITICAL + 4 MAJOR finding（task `rewrite_mile_d716099a_mag7_source_attribution`）。本平台研究誠實 §1（不可造假）+ §6（如實報告）觸發完整 unpublish-and-rewrite 流程。
