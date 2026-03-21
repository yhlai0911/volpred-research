# 付費閱讀平台研究

日期：2026-03-17

## 國際平台

| 平台 | 模式 | 抽成 | 適合 | 特色 |
|------|------|------|------|------|
| **Substack** | Newsletter 訂閱制 | 10% + Stripe 2.9% | 寫作者、研究分析師 | 免費/付費文章混合，SEO 好，自帶發現機制 |
| **Patreon** | 多層級會員 | 5-12% | 多元內容創作者 | 多 tier（基礎/進階/VIP），適合社群經營 |
| **Medium** | 閱讀量分潤 | Partner Program | 長文、部落格 | 不直接收費，靠 Medium 會員閱讀量分潤 |
| **beehiiv** | Newsletter + 廣告 | 免費起 | 成長型 newsletter | 內建廣告變現 + 推薦系統 |
| **Ghost** | 自架 + 訂閱 | 0%（自架）| 技術型創作者 | 開源，完全自主，無抽成 |
| **Buy Me a Coffee** | 打賞 + 訂閱 | 5% | 小型創作者 | 門檻最低 |

## 台灣平台

| 平台 | 模式 | 適合 | 特色 |
|------|------|------|------|
| **PressPlay** | 訂閱制學習 | 知識付費、線上課程 | 台灣最大訂閱學習平台，長期少量內容 |
| **vocus 方格子** | 訂閱 + 單篇購買 | 寫作者、專欄作家 | 支援付費牆、訂閱、單篇購買 |
| **CxC** | 訂閱 + 單本購買 | 小說、創作 | 功能最完整（訂閱/付費/追蹤限定/AI 朗讀） |
| **Matters** | 區塊鏈打賞 | 獨立寫作者 | 去中心化，加密貨幣打賞 |

## 與我們的比較

我們的 VolPred 研究網站走的是**自建平台 + Supabase Auth + Feature Gating**：

| 項目 | 第三方平台（如 Substack） | 自建（我們的方案） |
|------|--------------------------|-------------------|
| 控制權 | 受限於平台規則 | 完全自主 |
| 抽成 | 10%+ | 0%（只有金流手續費） |
| SEO | 依賴平台域名 | 自有域名 |
| 會員數據 | 平台擁有 | 自己擁有 |
| 客製化 | 有限 | 完全自由 |
| 開發成本 | 零 | 需要自建 |
| 適合階段 | 起步驗證 | 有技術能力後 |

## 結論

- **起步階段**可以用 Substack（零成本驗證 PMF）
- **有技術能力後**自建更好（完全控制、零抽成、自有數據）
- 我們已有自建網站 + Supabase 重構計畫 → **直接做自建付費牆**最合適
- Feature Gating 已在 v4 計畫中（一條 SQL 切換 free→premium）

## 收益數據（2024-2025）

### Substack 收益分佈
| 層級 | 月收入 | 佔比 |
|------|--------|------|
| 頂尖（50+ 作者）| $83,000+/月（年破百萬） | <0.003% |
| Top 10 | 合計 $40M/年 | 極少數 |
| 中層 | $2,000-$10,000/月 | 少數 |
| 中位數 | ~$333/月（年 $4,000） | 50% |
| 多數 | 幾百美元/月以下 | 大多數 |

- Substack 2025 付費訂閱達 500 萬，作者總收入 $450M
- 平台抽成 10%，常見定價 $5/月 或 $50/年
- **高度集中**：頂尖作者拿走大部分，多數人收入很少

### Patreon
- 2024 年創作者總收入超過 $35 億（歷史累計）
- 頂尖創作者月收入可達 $100K+
- 平均中小創作者 $500-$2,000/月

### 台灣平台
- PressPlay / vocus 收益數據不公開
- 台灣市場規模小，預估頂尖創作者月收 NT$50,000-200,000
- 一般創作者 NT$5,000-20,000/月

## API / 程式發文能力

| 平台 | 官方 API | 程式發文 | 方法 |
|------|---------|---------|------|
| **Substack** | ❌ 無官方 API | ✅ 可行 | 非官方 Python 套件 ([substack-api](https://pypi.org/project/substack-api/))、session cookie 驗證、n8n 自動化 |
| **Patreon** | ✅ 有 REST API | ✅ 可行 | OAuth2 認證，可建立/管理貼文 |
| **Medium** | ✅ 有 API | ✅ 可行 | Token 認證，POST /users/{id}/posts |
| **Ghost** | ✅ 完整 API | ✅ 最佳 | Admin API + Content API，JSON/Markdown |
| **vocus 方格子** | ❌ 無 API | ❌ 不可行 | 只能手動或爬蟲 |
| **PressPlay** | ❌ 無 API | ❌ 不可行 | 只能手動 |

### 對我們的影響

如果要雙發（自建網站 + 第三方平台），最佳選擇：

1. **Ghost（自架）**：零抽成 + 完整 API + 訂閱制 → 但需要自架
2. **Substack**：免費 + 有非官方 API → 可用 Python 自動發佈
3. **自建（當前方案）**：Supabase + Next.js → 完全自主，Claude 直接 POST

**建議**：短期用自建網站（已有）。如果要擴大觸及，可以**同步發佈到 Substack**（用非官方 API），免費曝光 + 付費導流回自建站。

## 參考來源

- [Substack vs Patreon](https://feather.so/blog/substack-vs-patreon)
- [Medium vs Substack](https://memberful.com/blog/substack-vs-medium)
- [Patreon vs Substack](https://helloaudio.fm/patreon-vs-substack/)
- [PressPlay 知識付費](https://medium.com/宥手寫字/知識付費該怎麼玩)
- [vocus 方格子 2024 觀察](https://vocus.cc/article/67b7093ffd8978000140bb4f)
