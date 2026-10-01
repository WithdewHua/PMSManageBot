## Why

- `identity` 的按键查询（如 `get_plex_info_by_tg_id`）是门面上被调用最多的一组方法：84 处调用，其中 50 处来自本批以外的 9 个领域。这些查询返回位置元组，调用方按下标取值，例如 `plex_info[1]` 是 tg_id，改动很容易出错。
- 账号绑定、凭码注册和邀请码的生成与兑换都写在路由里。
  - 生成邀请码时，先在独立事务里插入邀请码，再扣积分；扣分失败时，码不会被撤回。
  - 把邀请码兑换成积分时，"标记已用"的 UPDATE 不检查 `is_used=0`，并发时同一个码可以兑换两次。
- 账号同步任务 `update_plex_info` 会顺带回填邀请记录的 `plex_id`；而凭码注册又要调度这个同步函数。两者形成了 design D3 记录的第 2 处环。这个环有一边走门面，所以 import 图里看不到，只登记在 AST 基线中。
- 凭码注册为了检查 Plex 人数上限，调用了读模型 reports 的方法，这是从 T3 向 T5 的反向依赖。
- 除了 3 个绑定测试外，这几块都没有测试。

## What Changes

- **先补测试**，记录以下场景的现有行为：
  - Plex 和 Emby 绑定：路由预检、新建账号行、合并未绑定时积累的积分、各种冲突。
  - 凭码注册：Plex 全流程，以及 Emby 的绑定、不绑定和绑定失败三种分支。
  - 邀请码：路由、bot、管理员三处生成；兑换积分；积分信息接口。
  - 注册开关的读取与 `register-status` 接口。
  - 同步任务、`/create_overseerr` 命令。
- **按提升模板处理 `identity`、`accounts`、`invitation`**：
  - `identity` 提供带类型的按键查询和建档函数，返回数据类而不是位置元组。
    - `accounts` 和 `invitation` 改用新 API，两个手动回填脚本也一并改用。
    - 门面上的旧方法改为只做转发的兼容层：没有 SQL，结果仍是原来的元组。其他 9 个领域在各自的提升变更中迁移，兼容层由 `retire-legacy-db-facade` 删除。
  - `accounts` 的绑定、Overseerr 建号和同步流程移进 service。
  - `invitation` 的生成、兑换和凭码注册流程移进 service：
    - 生成邀请码时，扣分和插码在同一个事务里完成。
    - 兑换积分时，用带 `is_used=0` 条件的更新保证一个码只能兑换一次。
    - 以上只改变失败和并发情况下的结果，正常路径不变。
  - 凭码注册检查 Plex 人数时，改用 identity 提供的计数，不再调用 reports。
  - 账号信息变化后更新流量记录里的用户名：这是 `accounts` 调用下层的 `traffic`，方向正确，改为调用 traffic 新增的 service 函数，不再经过门面。
- **建立领域事件机制，消除 D3 第 2 处环**：
  - 这是第一个需要"下层通知上层"的变更，所以由它引入 `core/events.py`：事务提交后同步分发，处理函数统一在组装层注册。`promote-reward-domains` 会在此基础上扩展异步处理函数。
  - `accounts` 回填 Plex 用户 ID 后发布事件，`invitation` 订阅该事件，回填自己的邀请记录，回填的时机和范围与现在一致。
  - 凭码注册改为由 `invitation` 调度自己的具名任务，替换现在"注册按邮箱命名的临时任务、由守护线程延时删除"的做法。
- **行为不变**：接口路径、状态码、响应格式和文案都保持原样。现有的"业务拒绝返回 200 + `success=false`"契约保留，由路由把类型化异常转换成原来的响应模型。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。这是纯重构，`.openspec.yaml` 设置 `skip_specs: true`。上述生成邀请码和兑换积分的原子性修复，只影响失败和并发情况下的结果，不改变任何已有规格。

## Impact

- **代码**：
  - 三个领域：`domains/identity/`、`domains/accounts/`、`domains/invitation/`。
  - `core/events.py`；新增组装模块 `app/subscriptions.py`，由 `main.py` 和 `manage.py` 在启动时注册处理函数。
  - `domains/traffic/`：新增用户名同步的 service 函数。
  - watch_rewards 对邀请人查询的 2 处调用：从 service 调用 service 是合法的，由本变更一并迁移。
  - `scripts/backfill_invitation_ids.py`、`scripts/backfill_invitation_service.py`。
- **依赖**：
  - `make-credit-changes-atomic`：绑定时要合并积分。
  - `promote-blackjack-domain`：提供提升模板。
  - `promote-gift-pack-domain`：提供 `types` 角色放行和 invitation 的 `issue_codes_tx`。
  - `unify-business-configuration`：注册开关已迁到领域配置。
