# 2026-Q3 orphan-work retirement signal

## 症狀與根因

dispatch supervisor移除orphan workspace前，舊流程沒有一個不可略過、可證明未漏記的
durable evidence boundary。初版補上hash-chain ledger後，Matt雙軸review再找到三個
會破壞證據可信度的缺口：

1. branch probe失敗寫入`unresolved`後，下一輪actual branch被當成identity drift；
2. event直接寫final path，crash可能留下partial JSON；
3. reader只驗單筆hash，沒有驗workspace跨事件狀態機；直接升v2又會破壞v1與rollback。

## 底層修正

- finalize前先append；append失敗即中止workspace removal。
- 每dimension以`flock`序列化，先持久化append intent，再將完整event寫入mode-600
  temp inode、fsync、以hard-link no-clobber安裝final event，最後原子更新durable head。
- recovery會驗sequence、previous hash、event、intended head與目前head，再完成缺少的
  event/head；同identity重播不新增事件。
- branch unreadable先留下`unresolved` detection並fail closed。下一輪只允許補一筆
  同workspace／同job的actual resolution；解析後改成其他actual仍hard fail。
- loader在hash／sequence／timestamp驗證後，另驗每workspace只能有一筆detection或
  `unresolved detection → actual resolution`兩筆。materializer只把detection計為
  violation，但仍用resolution推進watermark與保留evidence ref。
- on-disk schema/key set維持`orphan-work-retirement-event.v1`。resolution用第二筆
  v1 event隱式表達；舊版回滾可完整讀取，最壞保守多計，不會遺失或拒讀證據。

## 驗證

- commits：`b30b3bd8a`,`d72311c86`,`3959bdfe6`,`b586aa48c`
- `tests/test_legacy_retirement_events.py`：24 passed
- workspace相鄰測試：11 passed
- partial temp recovery同時覆蓋legacy-business-fire與orphan-work。
- forged-but-rehashed chain連durable head一併重建後仍被語意verifier拒絕。
- Matt Spec與Standards最終複審均PASS，無actionable finding。
- 20:10自然fire
  `operations-core-v1:legacy_retirement_signal_materialize:1302e10729ea1f2566623753`
  為attempt 1／exit 0；signal mode 600、`count=0/high_watermark=0`，pending intent缺席。
- canonical、installed與manifest wrapper SHA：
  `c9a9c6d93bd0ebb4e714e1ce8f2320ad9a40b5cf1cf2929cdd0fd1c4799037ac`。

## 狀態

orphan-work evidence producer slice已完成五步Gate，狀態
**`root_cause_fixed_and_verified`**。Issue #46仍等待direct blocking edges、
14日sustained-clean observation及physical retirement，因此umbrella維持
**`contained`**，recorder尚未排程。
