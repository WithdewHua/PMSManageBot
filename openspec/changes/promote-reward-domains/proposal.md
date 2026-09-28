## Why

- **勋章触发的环（design D3 第 1 处）**：21 点、转盘、预言、夺宝、捐赠和加密货币捐赠这六个领域，在路由里直接调度勋章颁发函数；而颁发规则又要读取这些领域的数据。
  - 触发点共有 12 个，全部位于路由中，在数据库写入提交之后执行：要么交给 `BackgroundTasks`，在响应之后运行；要么用 `asyncio.create_task` 与响应并发运行，而且不保留任务引用。
  - 基线里有 9 条与这个环相关的条目，分属 activity、blackjack 和 remaining 三个变更。
- **`badge_awards` 不在任何检查范围内**：这个包没有 `__init__.py`，import-linter 的依赖图里看不到它。补上之后，会立刻暴露 6 个合约违规：直接用 SQLAlchemy 和其他领域的模型，以及六个领域对它的反向依赖。
- **观看奖励的每日结算太臃肿**：`update_plex_credits` 和 `update_emby_credits` 各有三四百行，把发积分、勋章加成、邀请人奖励、会员流量扣费和幽灵会话补偿都塞在一个函数里。
  - 会员流量欠额列属于 premium，这里用原生 SQL 写了 6 处。
  - 整个结算在异步任务里同步执行，会阻塞 bot 的事件循环。
- **勋章领域本身也要提升**：兑换和中心配置都写在路由和 mixin 里；排行榜借门面的 MRO 调用勋章 mixin 的私有方法。
- **完全没有测试**：勋章颁发、触发点和观看结算都没有。

## What Changes

- **扩展领域事件机制**：`promote-account-domains` 已经建立了"提交后同步分发"的事件机制。本变更在它上面增加异步处理函数：
  - 处理函数在提交后被安排到事件循环上运行，不阻塞原请求，并保留任务引用。
  - 没有 session 的调用方可以使用"立即分发"接口。
- **勋章颁发改为订阅事件**：
  - 六个领域在原来的触发点改为发布事件，事件粒度与现在的触发粒度相同：每个请求一次，比如十连抽只检查一次。
  - 删除对颁发函数的直接调用，消除 9 条相关的基线条目。
  - `badge_awards` 订阅这些事件后执行检查。
  - 检查时机保持为"操作提交后、响应之外异步执行"。
  - 现在不触发检查的路径仍然不触发，每日批量检查任务保留。
- **按提升模板处理三个领域**：`badges`、`badge_awards`、`watch_rewards`。
  - `badge_awards` 读取其他领域的数据时，改为调用各领域的 service；清理完成后补上 `__init__.py`，届时各合约直接通过。
  - 每日结算拆成三部分：纯计算放进 rules，每个用户的事务放进 repository（会员欠额通过 premium 的 `*_tx` 写入），通知放进 notifications。
  - 结算和勋章检查里的同步数据库调用移出事件循环。
  - 排行榜不再借门面调用勋章的私有方法。
- **对外行为不变**：积分数额、勋章颁发条件和通知文案都保持原样。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。这是纯重构，`.openspec.yaml` 设置 `skip_specs: true`。

## Impact

- **代码**：
  - `badges`、`badge_awards`、`watch_rewards` 三个领域。
  - 发布事件的六个领域：21 点、转盘、预言、夺宝、捐赠、加密货币捐赠。
  - `core/events.py`（扩展异步处理函数）、`app/subscriptions.py`（注册订阅）。
  - `rankings` 中勋章榜的数据转换。
- **依赖**：
  - `promote-activity-domains`
  - `promote-account-domains`：提供事件机制。
  - `promote-line-domains`：会员流量扣费要用到它提供的 premium `*_tx` 和 traffic service。
  - `make-credit-changes-atomic`
