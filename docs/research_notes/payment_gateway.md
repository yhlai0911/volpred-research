# 自建平台金流方案研究（完整版）

日期：2026-03-17（更新）

## 架構概覽

```
用戶點「升級」→ Payment Gateway Checkout → 付款成功
→ Webhook → Next.js API Route → Supabase 更新 role='premium'
→ Feature Gating 自動生效（一條 SQL 切換）
```

---

## 一、各金流平台深度比較

### 1. Stripe（國際首選）

**台灣可用性：**
- 2023 年起正式支援台灣商家註冊
- 需營利事業登記證（公司或行號）
- 個人可透過 Stripe Atlas 開美國 LLC（~$500 一次性費用）
- 支援 TWD（新台幣）結算，撥款至台灣銀行帳戶
- 需符合 KYC 規範（身份證明、公司文件）

**手續費：**
| 項目 | 費率 |
|------|------|
| 國內信用卡 | 2.9% + $0.30 / 筆 |
| 國際信用卡 | +1.5% 跨境費 |
| Stripe Billing 訂閱附加費 | +0.5%（Starter）或 +0.8%（Scale） |
| 月費 / 設定費 | 無 |
| 退款費 | 原手續費不退 |

> 以 $5/月訂閱為例：每筆實際扣 2.9% + $0.30 + 0.5% = ~$0.47（扣約 9.5%）
> 以 NT$150/月為例：~NT$14/筆（扣約 9.3%）

**訂閱 / 定期扣款支援：**
- **Stripe Billing**：原生訂閱管理，業界最成熟
- 自動處理：續費、重試失敗付款、發票生成、proration
- Stripe Checkout（託管付款頁）：10 分鐘內可上線
- Stripe Customer Portal：用戶自行管理訂閱（升級/降級/取消）
- 支援 trial period、coupon、metered billing
- 台灣商家可用（台灣不在 Billing 排除名單中）

**API 品質：★★★★★（業界標準）**
- 完整 REST API + 豐富 Webhook 事件
- 官方 SDK：`stripe` (Node.js)、`@stripe/stripe-js` (前端)、Python、Go、Ruby...
- 文件品質極高（stripe.com/docs），範例完整
- Webhook 簽名驗證、重試機制
- TypeScript 完整型別支援
- 測試模式 + test card numbers

**支援付款方式（台灣）：**
- ✅ 信用卡 / 簽帳卡（Visa、Mastercard、JCB）
- ✅ Apple Pay
- ✅ Google Pay
- ✅ Link（Stripe 快速結帳）
- ❌ 超商代碼
- ❌ ATM 轉帳
- ❌ LINE Pay（無原生支援）

**與 Supabase + Next.js 整合：**
- **最成熟的組合**，大量開源範例
- Webhook → API Route → Supabase service_role 更新 profiles.role
- Vercel 官方模板：[nextjs-subscription-payments](https://github.com/vercel/nextjs-subscription-payments)
- Stripe Elements 可嵌入 Next.js 頁面（無需跳轉）

---

### 2. 綠界 ECPay（台灣市佔最高）

**基本資訊：**
- 台灣第三方支付領導品牌
- 一般會員（個人）免年費即可使用
- 合約會員（企業）可談更低費率

**手續費：**
| 項目 | 費率 |
|------|------|
| 國內信用卡 | 2.75%（一般會員），新戶優惠 1.8% |
| 國際信用卡 | 需另詢 |
| 超商代碼 | 依金額 NT$25-NT$45 / 筆 |
| ATM 虛擬帳號 | NT$10-NT$15 / 筆 |
| 月費 / 年費 | 免（一般會員） |
| 提領手續費 | NT$15/筆（永豐帳戶免費） |

> 所有手續費另加 5% 營業稅

**訂閱 / 定期定額支援：**
- ✅ 信用卡定期定額（原生支援）
- 消費者只需刷卡一次，後續由綠界自動授權扣款
- 可設定：扣款週期（日/月/年）、每次金額、執行次數
- 付款頁會顯示每期金額、週期、總次數
- 有 `PeriodReturnURL` webhook 回傳每期授權結果

**API 品質：★★★（堪用但不夠現代）**
- 有 REST API（AIO 全方位金流）
- 有 Webhook 通知（NotifyURL / ReturnURL）
- 用 CheckMacValue 驗證（非標準簽名方式）
- 官方 SDK：PHP、C#、Java、Python
- **Node.js SDK**：官方品質差，建議用第三方 `node-ecpay-aio`（TypeScript 支援）
- 文件中文為主，格式較舊，部分參數說明不清
- 測試環境可用

**支援付款方式（台灣，最全面）：**
- ✅ 信用卡（Visa/Master/JCB/銀聯）
- ✅ Apple Pay
- ✅ 超商代碼繳費（7-11/全家/萊爾富/OK）
- ✅ ATM 虛擬帳號轉帳
- ✅ 超商條碼繳費
- ✅ WebATM
- ✅ TWQR 碼支付
- ✅ WeChat Pay
- ❌ LINE Pay（需另串）
- ❌ Google Pay

**與 Supabase + Next.js 整合：**
- 可行，但需自行處理更多邏輯
- NotifyURL webhook → Next.js API Route → Supabase 更新
- CheckMacValue 驗證需手動實作
- 無官方 Next.js 範例，需參考社群實作

---

### 3. 藍新 NewebPay（穩定老牌）

**基本資訊：**
- 台灣老牌金流（原智付通）
- PCI-DSS 3.2.1 認證
- SSL 256bit 加密

**手續費：**
| 項目 | 費率 |
|------|------|
| 國內信用卡 | 2.8%（可談至 2.4%） |
| 分期付款 | 3%-15%（依期數） |
| 超商代碼 | 固定金額 / 筆 |
| ATM 轉帳 | NT$10 / 筆（每月前 5 筆免費） |
| 月費 / 年費 | 免 |
| 提領手續費 | NT$10/筆（每月前 5 筆免費） |

> 費率依商店營運規模與資質彈性調整，另加 5% 營業稅

**訂閱 / 定期定額支援：**
- ✅ 約定信用卡定期扣款
- 有 `notify_url`（每期授權結果通知）
- 有 `return_url`（委託完成導向）
- 商家可自訂扣款週期與金額

**API 品質：★★★（中規中矩）**
- MPG 多功能支付（幕前 POST 導向支付頁）
- AES 加密 + SHA256 雜湊驗證
- 有 Node.js 社群 SDK：
  - `newebpay-mpg-sdk`（幕前支付）
  - `node-newebpay`（加解密工具）
  - `NewebPay-API-Implementation`（完整 Node.js 實作）
- 文件品質中等，中文為主
- 測試環境可用

**支援付款方式（台灣）：**
- ✅ 信用卡（Visa/Master/JCB/銀聯）
- ✅ Apple Pay
- ✅ Google Pay
- ✅ Samsung Pay
- ✅ LINE Pay
- ✅ 超商代碼繳費
- ✅ ATM 虛擬帳號
- ✅ 超商條碼

**與 Supabase + Next.js 整合：**
- 可行，需自行實作加解密
- webhook（NotifyURL）→ API Route → 解密 → Supabase 更新
- 多個 Node.js 開源實作可參考

---

### 4. TapPay（最現代 API）

**基本資訊：**
- Cherri Tech 產品，台灣新創常用
- 20,000+ 商店使用
- API 設計最接近國際標準

**手續費：**
| 項目 | 費率 |
|------|------|
| 國內信用卡 | ~2.6%-2.75%（依合約） |
| 國際信用卡 | ~3.5% |
| iPhone 卡緊收（Tap to Pay） | 國內 2.75% / 國外 3.5% |
| 月費 | 1 台手機 NT$150/月（卡緊收） |
| 年費 / 設定費 | 依合約 |

> 另加 5% 營業稅。費率依商店規模與風險條件彈性調整

**訂閱 / 定期定額支援：**
- ✅ 透過 Bind Card API 實作定期扣款
- 流程：Pay by Prime → 取得 card_key + card_token → 定期呼叫 Pay by Card Token
- 扣款週期與金額完全由商家自行控制（更靈活但需自己排程）
- **注意**：不像 Stripe Billing 那樣自動管理訂閱生命週期，需自己寫 cron job

**API 品質：★★★★（現代 RESTful）**
- 純 RESTful JSON API
- 直接嵌入式信用卡欄位（Direct Pay，類似 Stripe Elements）
- 支援 3D Secure
- 內建反詐欺（Cherri X）
- 前端 JS SDK + 後端 REST API
- 文件品質佳，有英文版
- 測試環境完整

**支援付款方式（台灣）：**
- ✅ 信用卡 / 簽帳金融卡
- ✅ Apple Pay
- ✅ Google Pay
- ✅ LINE Pay
- ✅ 街口支付
- ✅ Pi 錢包
- ✅ 悠遊付
- ✅ 全支付 / 全盈支付
- ✅ iPhone Tap to Pay（卡緊收）
- ❌ 超商代碼
- ❌ ATM 轉帳

**與 Supabase + Next.js 整合：**
- 可行，API 風格接近 Stripe
- Direct Pay 可嵌入 Next.js 頁面
- webhook 需自行設定
- 無官方 Next.js 範例，但 API 設計直覺好串

---

### 5. PayPal（有嚴重限制）

**台灣限制：**
- ⚠️ **2015 年起禁止台灣對台灣交易**
- 台灣 PayPal 帳號不能收台灣 PayPal 帳號的錢
- 只能收**國際付款**（海外買家付款給台灣賣家）
- PayPal Credit 在台灣不可用

**手續費：**
| 項目 | 費率 |
|------|------|
| 國際交易 | 3.49% + $0.49 / 筆 |
| 幣別轉換 | +2.5% |
| 提領至台灣銀行 | 有手續費 |

**訂閱支援：**
- ✅ 有訂閱按鈕（Subscription Buttons）
- 但台灣用戶互相付款被禁止，嚴重限制使用場景

**結論：不適合純台灣市場，僅適合國際讀者付款**

---

## 二、總覽比較表

| 維度 | Stripe | 綠界 ECPay | 藍新 NewebPay | TapPay | PayPal |
|------|--------|-----------|--------------|--------|--------|
| **信用卡費率** | 2.9%+$0.30 | 2.75% | 2.8% | ~2.6% | 3.49%+$0.49 |
| **月費/年費** | 免 | 免 | 免 | 依合約 | 免 |
| **原生訂閱管理** | ★★★★★ | ★★★ | ★★★ | ★★（需自建） | ★★★ |
| **API 品質** | ★★★★★ | ★★★ | ★★★ | ★★★★ | ★★★ |
| **信用卡** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Apple Pay** | ✅ | ✅ | ✅ | ✅ | ❌ |
| **Google Pay** | ✅ | ❌ | ✅ | ✅ | ❌ |
| **LINE Pay** | ❌ | ❌ | ✅ | ✅ | ❌ |
| **超商代碼** | ❌ | ✅ | ✅ | ❌ | ❌ |
| **ATM 轉帳** | ❌ | ✅ | ✅ | ❌ | ❌ |
| **台灣公司需求** | 需要 | 不需要 | 不需要 | 不需要 | 不需要 |
| **Next.js 整合** | ★★★★★ | ★★ | ★★ | ★★★ | ★★★ |
| **開源範例** | 極多 | 少 | 少 | 少 | 中 |

---

## 三、Substack / Patreon 如何處理付款

### Substack 的付款架構
```
Creator 註冊 Stripe Connect → 設定付費方案
Reader 訂閱 → Stripe Checkout → 信用卡扣款
→ Stripe 扣 2.9% + $0.30 + 0.5%（Billing fee）
→ Substack 扣 10%
→ 剩餘撥款至 Creator 的 Stripe 帳戶 → 銀行
```

- 底層完全使用 **Stripe Payments + Stripe Billing**
- Stripe 處理：儲存卡號、訂閱續費、失敗重試、合規
- Substack 只負責前端體驗和內容管理
- 2025 年已有 500 萬付費訂閱，創作者總收入 $4.5 億
- 費用疊加：Stripe ~3.7% + Substack 10% ≈ 每筆扣 **~13.7%**

### Patreon 的付款架構
```
Creator 設定多層級方案（$1/$5/$10/月）
Patron 選擇層級 → Stripe 或 PayPal 扣款
→ 付款處理費 2.9% + $0.30
→ Patreon 平台費 5-12%（依方案）
→ 幣別轉換費 2.5%（如適用）
→ 撥款至 Creator 銀行帳戶
```

- 主要使用 **Stripe** 處理信用卡，也支援 PayPal
- 2025 年 8 月起，新創作者統一 10% 平台費
- 費用疊加：Stripe ~3.7% + Patreon 10% ≈ 每筆扣 **~13.7%**

### 自建的優勢
| 項目 | Substack/Patreon | 自建 + Stripe |
|------|-----------------|---------------|
| 每筆扣除 | ~13.7% | ~3.4%（僅 Stripe） |
| 100 人 × $5/月 | 收 $432/月 | 收 $483/月 |
| 1000 人 × $5/月 | 收 $4,315/月 | 收 $4,830/月 |
| 年省下 | — | ~$612（100人）/ ~$6,180（1000人） |
| 會員數據 | 平台擁有 | 自己擁有 |
| 品牌 | 平台品牌 | 自有品牌 |
| SEO | 平台域名 | 自有域名 |

---

## 四、最佳實踐架構：Stripe + Supabase + Next.js

### 整體流程

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Next.js    │────▶│   Stripe     │────▶│  Supabase   │
│  Frontend   │     │   Checkout   │     │  Database   │
└─────────────┘     └──────────────┘     └─────────────┘
       │                    │                    │
       │  1. 用戶點升級     │                    │
       │──────────────────▶│                    │
       │                   │  2. 付款完成        │
       │                   │  3. Webhook 通知    │
       │                   │──────────────────▶│
       │                   │                   │  4. 更新 role
       │  5. 重新載入頁面   │                   │
       │◀──────────────────────────────────────│
       │  6. Feature Gating 自動生效            │
```

### 資料庫設計

```sql
-- profiles 表新增欄位
ALTER TABLE profiles ADD COLUMN stripe_customer_id TEXT;
ALTER TABLE profiles ADD COLUMN subscription_status TEXT DEFAULT 'free';
  -- free / active / past_due / canceled

-- subscriptions 表（詳細記錄）
CREATE TABLE subscriptions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES profiles(id),
  stripe_subscription_id TEXT UNIQUE,
  stripe_customer_id TEXT,
  status TEXT DEFAULT 'active',
  plan TEXT DEFAULT 'monthly',
  price_id TEXT,
  current_period_start TIMESTAMPTZ,
  current_period_end TIMESTAMPTZ,
  cancel_at_period_end BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- RLS: 用戶只能看自己的訂閱
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can view own subscriptions"
  ON subscriptions FOR SELECT
  USING (auth.uid() = user_id);
```

### Next.js API Routes

```
/api/stripe/checkout    → 建立 Checkout Session（導向 Stripe 付款頁）
/api/stripe/webhook     → 接收 Stripe 事件（付款成功/取消/失敗）
/api/stripe/portal      → 導向 Stripe Customer Portal（管理訂閱）
```

### Webhook 處理（核心邏輯）

```typescript
// app/api/stripe/webhook/route.ts
import Stripe from 'stripe';
import { createClient } from '@supabase/supabase-js';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);
const supabase = createClient(
  process.env.SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!  // 注意：用 service_role，不是 anon
);

export async function POST(req: Request) {
  const body = await req.text();
  const sig = req.headers.get('stripe-signature')!;

  // 1. 驗證 webhook 簽名
  const event = stripe.webhooks.constructEvent(
    body, sig, process.env.STRIPE_WEBHOOK_SECRET!
  );

  // 2. 處理事件
  switch (event.type) {
    case 'checkout.session.completed': {
      const session = event.data.object as Stripe.Checkout.Session;
      const userId = session.metadata?.supabase_user_id;

      // 建立/更新訂閱記錄
      await supabase.from('subscriptions').upsert({
        user_id: userId,
        stripe_subscription_id: session.subscription,
        stripe_customer_id: session.customer,
        status: 'active',
      });

      // 更新用戶角色
      await supabase.from('profiles')
        .update({ role: 'premium', subscription_status: 'active' })
        .eq('id', userId);
      break;
    }

    case 'invoice.paid': {
      // 續費成功（每月自動觸發）
      const invoice = event.data.object as Stripe.Invoice;
      await supabase.from('subscriptions')
        .update({
          status: 'active',
          current_period_end: new Date(invoice.period_end * 1000),
        })
        .eq('stripe_subscription_id', invoice.subscription);
      break;
    }

    case 'invoice.payment_failed': {
      // 付款失敗 → 標記 past_due
      const invoice = event.data.object as Stripe.Invoice;
      const sub = await supabase.from('subscriptions')
        .select('user_id')
        .eq('stripe_subscription_id', invoice.subscription)
        .single();

      await supabase.from('profiles')
        .update({ subscription_status: 'past_due' })
        .eq('id', sub.data?.user_id);
      break;
    }

    case 'customer.subscription.deleted': {
      // 訂閱取消 → 降級
      const subscription = event.data.object as Stripe.Subscription;
      const sub = await supabase.from('subscriptions')
        .select('user_id')
        .eq('stripe_subscription_id', subscription.id)
        .single();

      await supabase.from('profiles')
        .update({ role: 'free', subscription_status: 'canceled' })
        .eq('id', sub.data?.user_id);

      await supabase.from('subscriptions')
        .update({ status: 'canceled' })
        .eq('stripe_subscription_id', subscription.id);
      break;
    }
  }

  return new Response('OK', { status: 200 });
}
```

### Feature Gating

```sql
-- 啟動付費時只需一條 SQL
UPDATE feature_flags SET required_role = 'premium'
WHERE feature IN ('realtime_thinking', 'priority_research',
                  'unlimited_questions', 'early_access');
```

```tsx
// 前端自動分流
function FeatureGate({ feature, children }) {
  const { user } = useAuth();
  const canAccess = user?.role >= feature.requiredRole;

  if (!canAccess) {
    return <UpgradePrompt feature={feature} />;
  }
  return children;
}
```

---

## 五、開源參考專案

### 最推薦

1. **[Vercel nextjs-subscription-payments](https://github.com/vercel/nextjs-subscription-payments)**
   - Vercel 官方維護
   - Next.js + Supabase + Stripe 完整範例
   - 產品/價格自動從 Stripe Dashboard 同步到 Supabase
   - 包含 Checkout、Customer Portal、Webhook 處理

2. **[next-supabase-stripe-starter](https://github.com/KolbySisk/next-supabase-stripe-starter)**
   - 高品質 SaaS starter（shadcn/ui）
   - Supabase migrations + Stripe fixtures
   - Webhook 自動同步 Stripe → Supabase

3. **[Vercel SaaS Starter Kit](https://vercel.com/templates/next.js/stripe-supabase-saas-starter-kit)**
   - Drizzle ORM + PostgreSQL
   - Stripe 整合 + 訂閱管理
   - 可一鍵 deploy 到 Vercel

### 其他參考

4. **[launch-mvp-stripe-nextjs-supabase](https://github.com/ShenSeanChen/launch-mvp-stripe-nextjs-supabase)**
   - 含自動化 email（Supabase Edge Functions + Resend）
   - 註冊/訂閱/取消自動寄信

5. **[MakerKit](https://makerkit.dev/docs/next-supabase/stripe-configuration)**
   - 免費開源 SaaS boilerplate
   - 詳細的 Stripe webhook 處理文件

---

## 六、推薦方案與實作路線

### 首選：Stripe（國際 + 信用卡用戶）

**理由：**
- Next.js + Supabase + Stripe 是最成熟的 indie SaaS 技術組合
- API 品質業界最高，文件完整，TypeScript 支援佳
- Stripe Billing 自動管理訂閱生命週期（續費/重試/取消）
- 開源範例極多，半天內可上線
- Substack / Patreon 底層都用 Stripe，驗證過的架構

**台灣商家注意事項：**
- 需營利事業登記（公司或行號）
- 個人可先用 Stripe Atlas 開 US LLC（$500）
- 或先用台灣金流起步，有公司後再切 Stripe

### 次選：TapPay（純台灣市場、個人起步）

**理由：**
- API 設計最現代（接近 Stripe 風格）
- 個人可申請，不需公司登記
- 支援 Apple Pay / Google Pay / LINE Pay / 街口
- Direct Pay 可嵌入 Next.js（類似 Stripe Elements）
- **缺點**：訂閱管理需自建（card_token 定期扣款 + cron job）

### 備選：綠界 ECPay（最多付款方式、覆蓋無卡用戶）

**理由：**
- 超商代碼 + ATM 轉帳 → 覆蓋沒有信用卡的用戶（台灣很多人習慣）
- 台灣市佔最高，用戶信任度高
- 原生定期定額功能
- **缺點**：API 文件品質較差，整合體驗不如 Stripe/TapPay

### 不建議：PayPal

- 台灣對台灣付款被禁止（2015 年起）
- 僅適合收國際付款
- 手續費高、提領不便

---

## 七、分階段實作計畫

### Phase 1（現在）— 全部免費
- 累積用戶和內容
- 建立 Supabase profiles.role 欄位（已有）
- 設計 feature_flags 表

### Phase 2（有付費需求時）— Stripe 上線
- 串接 Stripe Checkout（~半天工作量）
- 建立 subscriptions 表
- 實作 webhook API route
- 執行 `UPDATE feature_flags` 啟動分流
- **參考**：fork `nextjs-subscription-payments` 快速上線

### Phase 3（擴大台灣市場）— 多金流
- 加入 TapPay 或綠界作為補充管道
- LINE Pay + 超商代碼覆蓋無信用卡用戶
- 統一 webhook 邏輯：不同金流 → 同一個 Supabase 更新

---

## 八、定價建議

| 方案 | 價格 | 功能 |
|------|------|------|
| **Free** | $0 | 基礎文章 + 每月 3 次研究提問 |
| **Premium 月付** | $5/月 或 NT$150/月 | 即時研究思路 + 無限提問 + 優先研究 + 早期訪問 |
| **Premium 年付** | $50/年 或 NT$1,500/年 | 同上，約 83 折 |

> Substack 常見定價為 $5/月，台灣知識付費常見 NT$99-299/月

---

## 九、參考來源

### Stripe
- [Stripe 台灣收款指南](https://stripe.com/resources/more/payments-in-taiwan)
- [Stripe 全球可用性](https://stripe.com/global)
- [Stripe 定價](https://stripe.com/pricing)
- [Stripe Billing 定價](https://stripe.com/billing/pricing)
- [Stripe 訂閱定價模型](https://docs.stripe.com/billing/subscription-pricing)
- [如何在台灣開設 Stripe 帳戶](https://www.doola.com/stripe-guide/how-to-open-a-stripe-account-in-taiwan/)
- [Stripe Webhook + Supabase](https://supabase.com/docs/guides/functions/examples/stripe-webhooks)
- [Stripe 台灣商家指南 (Roo.Cash)](https://roo.cash/blog/stripe-guide/)

### 綠界 ECPay
- [綠界服務費率表](https://www.ecpay.com.tw/Business/payment_fees)
- [綠界 API 技術文件](https://developers.ecpay.com.tw/)
- [綠界信用卡定期定額 API](https://developers.ecpay.com.tw/?p=2868)
- [node-ecpay-aio (Node.js SDK)](https://github.com/simenkid/node-ecpay-aio)

### 藍新 NewebPay
- [藍新金流服務平台](https://www.newebpay.com/)
- [藍新 API 文件下載](https://www.newebpay.com/website/Page/content/download_api)
- [NewebPay Node.js 實作](https://github.com/Rayologist/NewebPay-API-Implementation)
- [newebpay-mpg-sdk](https://github.com/depresto/newebpay-mpg-sdk)

### TapPay
- [TapPay 服務費率](https://www.tappaysdk.com/taiwan-zhtw/help/pricing)
- [TapPay 開發文件](https://docs.tappaysdk.com/tutorial/en/back.html)
- [TapPay 進階功能（定期扣款）](https://docs.tappaysdk.com/tutorial/en/advanced.html)

### PayPal
- [PayPal 在台灣的限制](https://www.onesafe.io/blog/does-paypal-work-in-taiwan)
- [PayPal 禁止台灣國內付款](https://www.newsbtc.com/news/paypal-stops-domestic-payments-in-taiwan/)

### 開源範例
- [Vercel nextjs-subscription-payments](https://github.com/vercel/nextjs-subscription-payments)
- [next-supabase-stripe-starter](https://github.com/KolbySisk/next-supabase-stripe-starter)
- [Stripe & Supabase SaaS Starter Kit (Vercel)](https://vercel.com/templates/next.js/stripe-supabase-saas-starter-kit)
- [launch-mvp-stripe-nextjs-supabase](https://github.com/ShenSeanChen/launch-mvp-stripe-nextjs-supabase)
- [MakerKit Stripe Webhook 處理](https://makerkit.dev/docs/next-supabase/stripe-webhooks)

### Substack / Patreon
- [Substack 如何使用 Stripe](https://support.substack.com/hc/en-us/articles/4405482746132)
- [Substack 付費訂閱運作方式](https://faq.substack.com/p/how-do-paid-subscriptions-on-substack)
- [Stripe 客戶案例：Substack](https://stripe.com/customers/substack)
- [Patreon 創作者費用](https://support.patreon.com/hc/en-us/articles/11111747095181)
- [Patreon 2025 費率變更](https://support.patreon.com/hc/en-us/articles/36426991446797)
