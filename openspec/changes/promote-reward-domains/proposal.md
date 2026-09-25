## Why

- 21 点、转盘、预言、夺宝、捐赠和加密货币捐赠这六个领域，在操作完成后都会直接调用勋章颁发函数；而颁发规则又要读取这些领域的数据。于是形成了 design D3 记录的第 1 处环，基线里有六个领域的条目与它有关。
- 观看奖励的每日结算（`update_plex_credits` / `update_emby_credits`）把好几件事放在一个函数里：发积分、勋章加成、邀请人奖励、会员流量扣费，以及幽灵会话补偿。

## What Changes

- **建立领域事件机制**（如果之前的变更还没有建立）：下层领域在事务提交后发布事件，处理函数统一在组装层注册。具体形式由本变更的 design 决定。
- **勋章颁发改为订阅事件**：
  - 上述六个领域改为发布事件，并删除对颁发函数的直接调用。
  - `badge_awards` 订阅这些事件后颁发勋章。
  - 颁发时机不变，仍是"操作完成后立即检查"。
- **按提升模板处理三个领域**：`badges`、`badge_awards`、`watch_rewards`。
  - 每日结算拆成两部分：纯计算放在 rules，事务放在 repository。
  - 通知移到 notifications。
- **对外行为不变**。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。这是纯重构，`.openspec.yaml` 设置 `skip_specs: true`。

## Impact

- **代码**：
  - `badges`、`badge_awards`、`watch_rewards` 三个领域。
  - 发布事件的六个领域。
  - `core/events.py`。
  - 组装层：注册事件处理函数。
- **依赖**：
  - `promote-activity-domains`
  - `promote-account-domains`
  - `promote-line-domains`：会员流量扣费要用到它提供的 `*_tx`。
  - `make-credit-changes-atomic`
