# Ivan Lai Facebook 貼文 — 風格與機制規則

每篇 trending_repost（以及未來其他 reader-facing FB 發文）的 FB 貼文寫法。
原則：FB 是社群動態，不是 newsletter 副本。

---

## 文案結構規則（重寫，不複製 VolPred 內文）

1. **FB 文案必須是改寫版**
   - ❌ 不可把 VolPred 原文整段或大段 copy-paste 到 FB
   - ❌ 不可把 title + first paragraph 直接 reuse
   - ✓ 從 VolPred 文章抓 1 個 hook + 1 個關鍵數字 / 場景，重新組成 FB 短文
   - ✓ FB 文案字數 200-400 字（中文）— 比 VolPred 內文短得多

2. **主貼文不要放連結**
   - ❌ 主貼文 body 內**不貼** volpred.zeabur.app/... 連結
   - 原因：FB 演算法對外連結 reach 大幅打折
   - 主貼文純文字（中文） + 視需要 1 張圖（VolPred 文章的核心圖表，獨立上傳 FB）

3. **VolPred 連結放在第一則留言**
   - 主貼文發出後，**自己**立刻在貼文下方 reply 1 則留言
   - 留言內容：「完整版分析 + 圖表在這裡 → https://volpred.zeabur.app/v3/reports/<mile_id>」
   - **URL hard rule**：只能用 `/v3/reports/<mile_id>`，**絕對不可**用 `/article/<mile_id>`（404）。發文前 `curl -I` 驗 HTTP 200。
   - 留言可以簡單，但連結要完整正確

---

## Ivan Lai 舊文口吻（必模仿）

每篇 FB 文案要符合 Ivan Lai 在 FB 上的個人帳號慣有口吻：

### 結構原則

1. **先個人觀察或判斷**
   - 開頭不是「今天市場…」「根據資料…」（這是新聞稿腔）
   - 開頭是「我覺得…」「看到 XXX 時，我會想…」「這幾天有件事卡在我腦袋裡…」（第一人稱觀察 / 思考起點）

2. **句子短、段落短**
   - 每句 ≤ 25 字（中文）
   - 每段 ≤ 3 句
   - 段落間用空行分隔，視覺呼吸感

3. **保留留白**
   - 不寫成密集論證
   - 結尾不下標準新聞稿結論（「綜上所述…」「總結而言…」全禁）
   - 留 1-2 個讀者自己連結的空間（拋問題、留懸念）

4. **不把論證一次講滿**
   - VolPred 完整論證留在原文（連結看了才有）
   - FB 只給：1 個觀察 + 1 個關鍵數字 + 1 個個人 take
   - 想知道完整推導 → 點留言連結

5. **不要寫成制式財經摘要**
   - 禁「Q1 EPS 1.85 美元（YoY +12%）」這種純財經 brief 寫法
   - 改成「Meta 帳上多了一張 1000 億的單。我想的是這錢誰付」（口語 + 個人 take）

### 禁用 / 慎用詞彙（FB 比 VolPred 內文更嚴）

除了 `.claude/skills/anti-ai-style/references/8-landmines.md` 的 8 大地雷外，FB 額外禁：

- 「綜上所述」/「總結而言」/「總的來說」（新聞稿腔）
- 「值得關注」/「值得深思」/「不容忽視」（套話）
- 「在 AI 時代」/「在後疫情時代」/「在新常態下」（大詞包裝）
- 「根據資料顯示」/「研究表明」（FB 沒人這樣講話）
- 「投資人應該…」/「建議讀者…」（FB 不是顧問報告）

### 好範例 vs 壞範例

❌ 壞範例（制式財經摘要）：
> Meta Q1 2026 財報出爐，EPS 1.85 美元，YoY +12%，CapEx 240 億美元。在 AI 時代，巨頭資本支出競賽白熱化，值得投資人深思。

✓ 好範例（Ivan Lai 口吻）：
> Meta 這季財報我看到一個數字，腦袋停了一下。
>
> CapEx 240 億美元一季。
>
> 過去 Meta 一年才花這個數字。現在一季就燒掉。
>
> 不是說燒得對不對，而是當這成為新常態，毛利模型要重寫了。

（短句、空行、第一人稱、留白給讀者自己連結）

---

## 操作備註

### 中文文案輸入方式

claude-in-chrome 在 FB 貼文輸入中文時：

1. **不要逐字輸入**（type one character at a time）
   - 原因：FB 編輯器對中文 IME 處理不穩；逐字輸入容易：
     - 字打到一半 input 失焦
     - 中文輸入法狀態被切回英文
     - 看似輸入完成但實際只 partial 進去
2. **優先用整段貼上**
   - 用 `mcp__claude-in-chrome__form_input` 一次塞完整段文字
   - 或先 copy 到 clipboard 再 paste（如 form_input 不穩）
3. **貼上後先檢查內容**
   - Screenshot 確認文字完整、中文無亂碼、換行正確
   - 確認**沒有意外把 VolPred 連結貼進主貼文**
4. **檢查通過才送出**
   - 點「發佈」前再次確認 — FB 一旦 publish 不能 silent edit（edit 會有「已編輯」標記，影響觀感）

### 留言（first comment）操作

5. 主貼文 publish 後，立刻在自己貼文下方 reply 一則 comment
6. Comment 內容：簡短引導 + VolPred 完整連結
7. Comment 也用整段貼上不要逐字輸入
8. Comment publish 後 screenshot 留 audit trail，更新 `storage/reports/trending_repost_log.json`：
   ```json
   "fb_post_status": "success",
   "fb_post_url": "https://www.facebook.com/...",
   "fb_comment_url": "https://www.facebook.com/...",
   "fb_post_timestamp": "2026-05-16T...+08:00"
   ```

### 失敗 fallback

- claude-in-chrome session 沒登入 Ivan Lai FB → log `fb_post_status: failed`，原因 `not_logged_in`，下次重試前提示用戶登入
- 主貼文發出但 comment 連結沒貼成功 → log `fb_post_status: partial_no_comment_link`，下次手動補
- 中文 input 出現亂碼 → 立刻 cancel publish，screenshot 留證，log `fb_post_status: failed`，原因 `chinese_input_corruption`，3 retry 後 escalate 給用戶

---

## 為什麼這麼嚴

- **Mission Goal 5（曝光流量拉高）+ Goal 1（文章寫好）** 同時依賴 FB 發文品質
- FB 是 VolPred 主要曝光入口之一；發得像新聞稿 / 像 AI → reach 與互動雙降
- Ivan Lai 個人帳號的觀感（個人聲量 / 信任度）是長期商業價值的 anchor — 一篇看起來像「AI 代寫」會傷信任 brand
- FB 主貼文無連結 + 留言連結 是經 reach test 的最高 ROI 寫法（FB 演算法對純文字 + 圖比帶連結 reach 高 2-5×）
