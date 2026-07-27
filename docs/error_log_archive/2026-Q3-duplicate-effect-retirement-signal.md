# 2026 Q3 — Duplicate-effect retirement signal

## 症狀與根因

Issue #46的14日legacy-retirement gate需要`duplicate_effect`的canonical interval
evidence。正式Effect Delivery雖以outbox/receipt狀態機阻止正常路徑重送，卻沒有在
durable settlement邊界保存「不可能事件」；只讀outbox終態無法證明觀察期間從未發生
第二次acknowledged delivery。

初版tripwire另有兩個根因缺口：

1. PostgreSQL identity sequence不是transactional；觸發器插入後若外層交易rollback，
   row消失但sequence仍前進，不能作為gap-free/deletion evidence。
2. 兩個同EffectRequest的delivered insert若並行，沒有共同serialization boundary時
   可能各自看不到另一筆，造成duplicate漏記。

## 底層修正

- `effect_attempt_receipts`的AFTER INSERT trigger是不可避邊界；非delivered直接忽略，
  delivered則先取得effect-scoped advisory transaction lock。
- private singleton head以同一交易`UPDATE ... RETURNING`配置下一個dense sequence；
  event insert、head advance或原settlement任何一步失敗會一起rollback。
- event/head表皆為`volpred_ops_definer`持有、RLS＋FORCE RLS；PUBLIC、anon、
  authenticated、service_role均無直接table access。
- fixed-search-path security-definer RPC只授權service_role，回傳指定cursor後完整、
  有序且截至同一high watermark的event集合；head遺失、row刪除或cursor越界均fail
  closed。
- Operations Core materializer驗證exact schema、sequence coverage、attempt identity、
  evidence SHA、observed/window time，再以mode 600 atomic replace生成typed signal。
- 既有`legacy_retirement_signal_materialize`每5分鐘依序刷新
  `legacy_business_fire`與`duplicate_effect`；任一失敗job非零。它不記observation，
  因此不會提前啟動14日窗。

## 回歸與production回讀

- PG17涵蓋migration replay、兩條並行delivered、attempt編號逆序、外層rollback後
  sequence仍從1開始、private table denial與service-role-only RPC。
- unit涵蓋cursor/schema/gap、前一observation watermark、事件落在前一interval之前、
  mode-600 typed output。
- schedule／wrapper manifest／scheduled-writer ownership相鄰回歸全綠。
- Supabase migration API receipt：
  `20260727112014 operations_core_duplicate_effect_retirement_signal`。
- Production catalog：event/head owner均為`volpred_ops_definer`，RLS與FORCE RLS=true，
  trigger enabled，RPC security-definer且`search_path=""`；anon/authenticated execute
  false、service_role true。
- Production RPC與materializer初始回讀：event count=0、head high watermark=0，
  typed signal `count=0/high_watermark=0`。
- 19:25第一個migration後自然Operations Core fire
  `operations-core-v1:legacy_retirement_signal_materialize:a08baf4868d03695348302f5`
  attempt 1、exit 0；legacy-business-fire與duplicate-effect兩個typed signal均由
  formal scheduler owner刷新，duplicate file為mode 600。

本producer slice完成五步Gate後可標
`root_cause_fixed_and_verified`；Issue #46 umbrella仍須等待silent-loss/orphan-work
producer、連續14日gap-free observations與physical legacy retirement，維持
`contained`。
