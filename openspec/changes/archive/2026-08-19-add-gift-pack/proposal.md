## Why

目前没有任何面向全体用户的运营活动发放渠道。管理员想在节日、周年庆等节点给用户发福利，只能手工改积分或逐个私聊，既不可审计也无法规模化。同时，用户侧缺少"有福利待领取"的主动触达——所有既有活动（幸运大转盘、夺宝奇兵、大预言家、竞拍）都依赖用户自己点进去，运营活动如果同样被动等待，触达率会很低。

礼包功能补上这个缺口：管理员配置一个带时间窗、带领取资格、带限量的礼包，用户在窗口内打开小程序时被主动提醒一次，前往礼包中心一键领取。

## What Changes

- **新增礼包定义与领取记录两张表**，礼包内容支持多项奖励（积分、Premium 天数），支持绝对时间窗、限量份数、领取资格。
- **新增用户侧礼包中心**，从底部导航中间 "+" 菜单进入，展示进行中与已领取的礼包，已错过的折叠收起。
- **新增开屏汇总弹窗**：窗口内存在可领礼包时，在应用启动后弹出一次汇总提醒，每个礼包每天最多提醒一次、累计不超过其配置的提醒上限。用户可选择「稍后再说」或「前往领取」。
- **新增管理端礼包管理面板**，作为「活动管理」tab 中的一张活动入口卡 + 全屏管理面板（与转盘/竞拍/夺宝同构），支持创建/编辑/停用礼包、配置多项奖励与领取资格、查看领取统计。
- **新增里程碑与异常通知**：礼包上线、限量领完、窗口过期汇总三个节点通知管理员；奖励发放失败时立即通知。日常逐笔领取不通知。
- 礼包一旦有人领取则**不可删除**，只能停用。

## Capabilities

### New Capabilities

- `gift-pack`: 礼包的定义、生命周期、领取资格判定、多项奖励发放、限量与幂等、开屏提醒节流、管理端配置与统计、管理员通知。

### Modified Capabilities

（无。既有能力的行为不变；礼包通过新增表与新增路由实现，不改动积分、Premium、勋章等既有能力的对外契约。）

## Impact

**后端**

- `src/app/models/models.py` — 新增 `GiftPack`、`GiftPackUserState` 两个模型
- `alembic/versions/` — 新增一个迁移
- `src/app/databases/db.py` — 新增礼包相关的 `DatabaseORM` 方法（查询、领取、统计）
- `src/app/webapp/routers/gift_pack.py` — 新增路由（用户端 + 管理端）
- `src/app/webapp/schemas/gift_pack.py` — 新增 Pydantic 模型
- `src/app/webapp/__init__.py` — 注册新路由
- `src/app/premium.py` — 复用 `update_premium_status()`；为满足领取的严格原子性，对其做向后兼容的重构（新增可选 `session` 参数以复用外层事务，抽出 `sync_media_permission()` 供事务提交后调用），既有三处调用方行为不变
- `src/app/scheduler.py` 的既有 `Scheduler` — 新增一个扫描过期礼包并汇总通知的定时任务

**前端**

- `webapp-frontend/src/components/BottomMenu.vue` — "+" 菜单新增「我的礼包」入口
- `webapp-frontend/src/components/GiftPackDialog.vue` — 新增礼包中心弹窗
- `webapp-frontend/src/components/GiftPackPromptDialog.vue` — 新增开屏汇总提醒弹窗
- `webapp-frontend/src/components/GiftPackAdminPanel.vue` — 新增管理面板
- `webapp-frontend/src/views/Management.vue` — 「活动管理」tab 新增礼包入口卡与全屏管理弹窗
- `webapp-frontend/src/App.vue` — 挂载开屏提醒弹窗并触发独立的 pending 查询
- `webapp-frontend/src/services/giftPackService.js` — 新增 API 封装

**不受影响**

- 积分、Premium、勋章、邀请码等既有发放逻辑的对外行为不变
- 开屏 pending 查询是**独立请求**，不合并进 `getUserInfo` / `systemStatus`
