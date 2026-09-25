## Why

转盘、夺宝、预言、竞拍四个活动的问题很相似：

- 路由里写着业务流程和通知。
- 按异常字符串分支处理错误。
- 调度和启动恢复的逻辑写在路由模块里。

21 点试点确立模板后，这四个活动可以批量提升。

## What Changes

- **按提升模板处理四个活动领域**：`luckywheel`、`treasure`、`prediction`、`auction`。
- **转盘成为免费次数账本的唯一入口**：`luckywheel` 统一提供免费次数的发放、消耗、释放和汇总，覆盖礼包和 21 点两种来源。
- **一次性调度统一改为具名任务**：夺宝自动开期、竞拍结束等一次性调度都改用具名任务。竞拍结束任务原来在内存 jobstore 里按函数引用调度，现在改为具名任务，仍然放在内存 jobstore 中。
- **群通知移到 notifications**：预言和夺宝的群通知移到 notifications，由 service 在提交后调用。
- **排行查询不回迁**：各活动的排行查询已经在 rankings 里，不再移回活动领域。
- **行为不变**。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。这是纯重构，`.openspec.yaml` 设置 `skip_specs: true`。

## Impact

- **代码**：四个活动领域，以及调用它们的 `gift_pack`（条件统计）、`badge_awards` 和 `rankings`。
- **依赖**：`promote-blackjack-domain`（提供模板和 `DomainError`）、`make-credit-changes-atomic`。
- **不在范围内**：勋章触发的环（design D3 第 1 处）不在本变更解决，仍由 `promote-reward-domains` 负责。
