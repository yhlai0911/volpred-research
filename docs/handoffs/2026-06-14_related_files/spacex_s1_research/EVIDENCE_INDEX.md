# Evidence Index

本檔用來追蹤研究稿裡的主要判斷，對應到本地下載的 SEC S-1 文字檔：
`task_artifacts/spacex_s1_research/spacex_s1.txt`

SEC 原始文件：
https://www.sec.gov/Archives/edgar/data/1181412/000162828026036936/spaceexplorationtechnologi.htm

## 公司結構與 AI 併入

- `spacex_s1.txt:278-280`：財報包含 xAI 與 X 的歷史結果，因為 xAI Merger 與 X Merger 屬於 common control。
- `spacex_s1.txt:469`：AI segment 指 SpaceX 在 2026 年 2 月收購 xAI 後取得的 AI 業務。
- `spacex_s1.txt:887-899`：SpaceX 將 space、connectivity、AI 放成同一個未來敘事，並稱 xAI 是 vertically integrated company 的支柱。

## 三大業務財務

- `spacex_s1.txt:1003-1006`：2026 Q1 consolidated revenue 46.94 億美元、operating loss 19.43 億美元；2025 revenue 186.74 億美元、operating loss 25.89 億美元。
- `spacex_s1.txt:1011-1026`：Space segment 2025 revenue 40.86 億美元、operating loss 6.57 億美元，並投入 Starship R&D。
- `spacex_s1.txt:1032-1050`：Connectivity / Starlink 2025 revenue 113.87 億美元、operating income 44.23 億美元、Segment Adjusted EBITDA 71.68 億美元。
- `spacex_s1.txt:1052-1065`：AI segment 2025 revenue 32.01 億美元、operating loss 63.55 億美元。
- `spacex_s1.txt:1067-1070`：2026 Q1 capex：Space 10.52 億、Connectivity 13.32 億、AI 77.23 億美元。

## 軌道 AI Compute

- `spacex_s1.txt:988-999`：SpaceX 認為可部署大規模 AI compute satellite constellations，可能有數百萬衛星，最快 2028 年開始部署 orbital AI compute satellites。
- `spacex_s1.txt:1346-1381`：S-1 將 AI 競爭拆成 compute capacity、cost per token、model-to-compute integration。
- `spacex_s1.txt:1382-1395`：COLOSSUS 與 COLOSSUS II 約 1.0GW compute power，並主張建置速度與成本優勢。
- `spacex_s1.txt:1398-1407`：軌道 AI 的核心理由是太陽能與地面能源限制。
- `spacex_s1.txt:1410-1424`：100GW/year 軌道算力部署需要 thousands of launches per year 與約 one million metric tons to orbit annually。
- `spacex_s1.txt:1454-1468`：Terafab 與 Tesla、Intel 的合作；目標是 one terawatt compute hardware/year，但具體專案仍需另行協議。

## Anthropic 合約

- `spacex_s1.txt:1658-1676`：Anthropic Cloud Services Agreements，Anthropic 每月支付 12.5 億美元至 2029 年 5 月，但任一方可 90 天通知終止。

## 控制權

- `spacex_s1.txt:96-108`：Class A 一股一票、Class B 一股十票；Class B 股東可選出董事會多數，Musk 可控制股東事項，公司將是 controlled company。
- `spacex_s1.txt:1678-1698`：Musk 擔任 founder / CEO / CTO / chairman，透過 Class B common stock 控制董事與公司事務；controlled company 可豁免部分治理要求。

## 用途與債務

- `spacex_s1.txt:1875-1891`：IPO net proceeds 數字仍空白，用途包括 AI compute infrastructure、launch infrastructure、satellite constellations。
- `spacex_s1.txt:23726-23746`：Musk 2026 年股權激勵，包含 10 億股 B 類限制股、火星百萬居民、非地球資料中心 100 terawatts compute/year。
- `spacex_s1.txt:23811-23823`：SpaceX 2026 年 3 月簽 200 億美元 bridge loan，用來清掉 X 與 xAI 的多筆貸款/票據。

## 逐字稿

- 機器轉錄純文字：`task_artifacts/spacex_s1_research/whisper/video_wpb-DrbhEiY.txt`
- 含時間碼字幕：`task_artifacts/spacex_s1_research/whisper/video_wpb-DrbhEiY.srt`
- 轉錄提醒：Whisper 產出有辨識錯字，研究引用以整理後精要為主，不直接把轉錄文字當精準引用。
