# Ivan Lai Facebook 文案規格

本檔只擁有**文案風格**。瀏覽器、查重、圖片上傳、第一則留言送出、狀態與 readback 全由 `fb-publishing` 的 real-Chrome workflow 擁有。

## 文案輸入

從已驗證的 VolPred thesis 重新寫一篇 200–400 字 FB-native 短文：

- 抓一個個人觀察或 tension 作開頭
- 保留一至兩個最重要、可追溯的數字
- 短句、短段、段落間留白
- 留一個清楚 take 或問題，不把網站完整論證搬過來
- 至少附一張與內文相符、沒有重複資訊的圖

不得複製 VolPred title、首段或整段正文，也不得寫成 newsletter 摘要、SEO snippet 或密集條列。

## Ivan Lai voice

- 第一人稱觀察先行，不以「根據資料顯示」開場
- 每段最多三句，讓讀者有呼吸空間
- 語氣可有判斷，但數字與因果強度不得超過證據
- 不用制式財經 recap 把所有統計量塞進主貼文
- 結尾避免「綜上所述」「總結而言」與硬 CTA

額外禁用：

- 「值得關注／值得深思／不容忽視」
- 「在 AI 時代／在新常態下」
- 「投資人應該／建議讀者」
- 強行「不是 X，而是 Y」的假哲理

完整語言 gate 見 `anti-ai-style`。

## Draft contract

```markdown
# mile_id: <mile_id>

## 主貼文
<不含連結的 FB-native 正文>

## 第一則留言
<由 config/project_targets.json 的 site.default_remote_url 衍生並驗證的文章 URL>

## 圖片
<image path or URL, one per line>
```

content producer 只需交付這份 draft。不得自行操作瀏覽器或直接寫 FB/feed status。

## Handoff checklist

- [ ] 主貼文與網站正文不是逐段複製
- [ ] 主文沒有 VolPred URL
- [ ] 第一則留言 URL 由 active runtime target 解析且 HTTP 200
- [ ] 圖片至少一張，無視覺重複
- [ ] `anti_ai_gate.py` exit 0
- [ ] draft 已保存到 `storage/drafts/fb_<mile_id>.md`

通過後交 `fb-publishing`。文案完成只代表 handoff-ready，不代表 FB delivery 成功。
