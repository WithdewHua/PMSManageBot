## Why

礼包目前只能发积分与 Premium 天数两种奖励，运营想用礼包做活动引流（送大转盘免费机会、争霸赛余额）、拉新（送邀请码）或送功能体验（线路调度、下载权限）时都无从下手，只能手工操作。站内其实已有这些奖励的全部载体，缺的只是把它们接进礼包的发放分发器。

其中大转盘免费机会的载体 `luckywheel_free_spins` 是为 21 点「打满手数」机制建的，周上限计数、获得通知、消耗记录、对账脚本都隐含「每一行都来自 21 点」的假设。礼包若直接往该表写行，会静默占用用户的 21 点周配额、触发错误的「打满手数」私信、并污染 21 点的让利率对账——因此本变更同时要把免费机会按来源解耦。

## What Changes

- **新增 5 种礼包奖励类型**：
  - `wheel_free_spins` 大转盘免费机会（次数 + 有效天数）
  - `tournament_wallet` 争霸赛余额（仅可支付锦标赛报名费）
  - `invite_codes` 邀请码（数量 + 是否特权码）
  - `line_schedule_unlock` 线路调度功能永久解锁
  - `download_unlock` 下载权限永久解锁（同步到媒体服务器）
- **统一「需绑定媒体账号」的奖励**：Premium 天数、线路调度解锁、下载权限解锁都作用于已绑定服务，含其中任一项的礼包都隐含「至少绑定一个媒体账号」的领取资格（原先只有 Premium 天数有此规则）。
- **统一「已拥有」语义**：一次性解锁类奖励遇到用户已拥有（已解锁、或 Premium 期间已自动拥有但未永久解锁的情况除外）时跳过该服务并在结果中说明，不阻断领取——与永久会员跳过 Premium 天数同一口径。
- **大转盘免费机会按来源解耦**（**行为修正**，影响 21 点能力）：
  - 21 点的周上限只统计 21 点来源的机会
  - 「打满手数奖励到账」私信只针对 21 点来源的机会
  - 消耗免费机会时按该机会的真实来源写转盘参与记录（新增 `gift_pack_free` 来源），不再写死为 21 点
  - 对账脚本的手数进度与让利率统计只统计 21 点来源
  - 到期提醒、可用次数展示、优先消耗顺序对所有来源一视同仁
- 管理面板的奖励编辑器支持新类型；领取结果与礼包中心按新类型展示（邀请码领取后提示去「我的邀请码」查看）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `gift-pack`: 奖励类型扩充为 7 种；「需绑定」隐含资格从 Premium 天数推广到所有作用于已绑定服务的奖励；新增各类奖励的发放语义（免费机会、争霸赛余额、邀请码、功能解锁）。
- `blackjack`: 「打满手数送免费大转盘机会」中周上限、获得通知、参与记录区分、审计口径改为只针对 21 点来源的机会；免费机会的消耗、到期作废与到期提醒对所有来源生效。

## Impact

**后端**

- `src/app/webapp/schemas/gift_pack.py` — 新增 5 个奖励项模型并加入判别联合；`GiftPackRewardView` 扩展字段
- `src/app/databases/db.py` — `_grant_gift_pack_rewards` 新增 5 个分支；`_gift_pack_reward_label` 新增文案；`create_gift_pack` / `update_gift_pack` 的隐含绑定规则推广；免费机会相关方法（周上限计数、通知游标、`consume_blackjack_freespin` 返回来源）按来源过滤
- 新增事务内版本的发放辅助函数（线路调度解锁、下载解锁、邀请码写入），复用调用方 session，不另开连接
- `src/app/webapp/routers/activities/luckywheel.py` — 单次转盘按消耗到的机会来源写 `wheel_stats.source`
- `src/app/webapp/routers/gift_pack.py` — 领取成功后执行不可回滚的外部副作用（下载权限同步到媒体服务器、特权邀请码写入配置）
- `scripts/blackjack_retention_audit.py` — 两处计数加来源过滤
- 无数据库结构变更（`luckywheel_free_spins.source` 与 `wheel_stats.source` 均为既有的自由文本列）

**前端**

- `GiftPackAdminPanel.vue` — 奖励类型选项与各类型的参数表单
- `GiftPackDialog.vue` / `GiftPackPromptDialog.vue` — 新奖励类型的展示与领取结果
- `LuckyWheel.vue` — 免费机会角标文案不再暗示只来自 21 点（如有此类文案）

**不受影响**

- 礼包的领取资格、提醒、限量、生命周期等既有规则不变（这些由 `add-gift-pack-audience-and-tasks` 另行处理）
- 21 点「打满手数」的计数、阈值、周上限数值与有效期不变；普通转盘、十连抽行为不变
