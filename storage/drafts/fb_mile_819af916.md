# FB Draft — mile_819af916
# fb_post_status: awaiting_interactive_session
# 注意：FB 個人帳號只能走 Claude in Chrome，由 interactive session 接手

---

六月底，美股悄悄有一個數字值得注意。

XLK 科技板塊的 30 日波動率，是 XLP 消費必需品的 2.5 倍。兩邊的價差不是一兩天的事——這個比值整個六月從 1.3 倍直接拉到 2.0 倍以上。

同一段時間，XLV 醫療 ETF 漲了 8%，QQQ 跌了 1.8%。

波動率高，不代表報酬好。過去一個月，承擔兩倍波動的科技股，報酬反而輸給了安靜的防禦板塊。

用波動率視角看板塊輪動，會比看哪個板塊「熱門」早一點感覺到市場在轉方向。

詳細分析和圖表在 VolPred（連結在留言）。

---

## 使用說明（互動 session 接手時）

1. 開 Ivan Lai FB（Claude in Chrome），先 get_page_text 掃最近 7-14 天是否有同主題貼文
2. 確認沒有重複 → 貼上文案（pbcopy 整段 → Cmd+V，不要逐字 type）
3. 主貼文不放連結
4. 發佈後在第一則留言放：https://volpred.zeabur.app/v3/reports/mile_819af916
5. 截圖驗證留言已送出
6. 跑 `uv run python scripts/mark_fb_post_status.py --mile-id mile_819af916 --status success`
