## Why

- `identity` 的按键查询（如 `get_plex_info_by_tg_id`）是门面上被调用最多的一组方法。
- 账号的绑定、解绑和凭码注册写在 `user.py`、`invitation.py` 的路由里。
- 账号同步任务 `update_plex_info` 会顺带回填邀请记录的 `plex_id`；而凭码注册又要调用这个同步函数。两者形成了 design D3 记录的第 2 处环。
- 这几块目前都没有测试。

## What Changes

- **先补测试**，记录以下场景的现有行为：
  - 绑定和解绑，包括合并尚未绑定时积累的积分。
  - 凭码注册。
  - 账号同步。
  - 注册开关。
- **按提升模板处理 `identity`、`accounts`、`invitation`**：
  - `identity` 提供带类型的按键查询和建档函数，替换门面上的对应方法。
  - `accounts` 的绑定、解绑和同步流程移进 service。
  - 邀请记录 `plex_id` 的回填移进 `invitation`，消除 D3 第 2 处环。
  - 账号信息变化后要更新流量记录里的用户名。这是 `accounts` 调用下层的 `traffic`，方向正确，保持直接调用。
- **行为不变**。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。这是纯重构，`.openspec.yaml` 设置 `skip_specs: true`。

## Impact

- **代码**：三个领域，以及所有调用 identity 查询的地方。门面上的调用里，这一批数量最多。
- **依赖**：
  - `make-credit-changes-atomic`：绑定时要合并积分。
  - `promote-blackjack-domain`：提供提升模板。
