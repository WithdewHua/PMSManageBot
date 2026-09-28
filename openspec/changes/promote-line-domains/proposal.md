## Why

线路相关的五个领域（lines、custom_lines、traffic、premium、media_access）在 B 阶段只是搬进了各自的目录，结构问题都还在：

- **SQL 与业务流程写在入口里**：custom_lines 的 SQL 散落在路由（9 处）、管理员路由（6 处）和任务里，repository 只有 2 个函数。lines 的路由经门面调用了 45 次。
- **premium 的 service 保留了 B1 的桥接**：它在函数内延迟导入门面（4 处），并直接写 SQL。`sync_media_permission` 和 `update_premium_status` 还要求调用方传入门面实例。另外有 2 处以属性引用的方式调用 `db.set_*_line`，扫描器看不到。
- **多写入操作不在一个事务里**：
  - 会员购买先提交会员，再扣积分。扣分失败时会员就白送了。
  - 下载解锁先扣积分，再在另一个事务里设标志。设标志时不检查影响行数，没绑定的服务也照样扣分。
- **自建线路的任务在未提交的 session 里等待网络**：下线、删除和三个定时任务，都在打开的 session 里依次 await 解绑、禁用调度和发 Telegram 消息。
- **规则重复**：
  - "会员是否有效"有三种判定口径，分散在 5 处。
  - premium 和 lines 各有一套"解绑会员线路"的实现。
  - 线路目录分散在 `.env`、`SystemConfig` 和 settings 中，被 lines、premium、traffic、reports 直接读取。
- **模型放错了领域**：lines 和 custom_lines 的 27 个 Pydantic 模型定义在 `profile/schemas.py` 里，共占 90 条基线条目。
- **几乎没有测试**：线路绑定、调度、会员、NSFW 与下载解锁、自建线路和流量采集，都没有行为测试。

## What Changes

- **先补测试**，记录以下场景的现有行为：
  - 线路绑定、权限判定、网关缓存的写入、认证绑定。
  - 线路调度：增删改、解锁扣分、生效调度的选择、自动切换。
  - 会员：购买、到期、临期提醒、统计、流量额度与欠额。
  - 下载解锁与 NSFW 解锁、锁定。
  - 自建线路的完整生命周期、流量检查和月度结算。
  - 流量日志的采集、月度聚合和清理。
- **按提升模板处理五个领域**：
  - 删除 premium 的 B1 桥接和对门面的属性引用；所有 SQL 移入 repository。
  - premium 提供会员流量欠额的 `*_tx`，供 `promote-reward-domains` 的观看结算使用。
  - traffic 提供按用户查询每日流量和流量排行的 service。
  - lines 和 custom_lines 的 Pydantic 模型从 `profile/schemas.py` 搬回各自的领域。
  - "会员是否有效"的三种口径，分别命名为纯函数，调用方各自保持原口径。
  - "解绑会员线路"合并为 lines 的一个实现。
- **单事务与提交后副作用**：
  - 会员购买、下载解锁、NSFW 解锁与锁定、自建线路的各状态变更，都在一个事务里完成数据库写入。
  - Plex、Emby 的权限同步和通知，统一在提交后执行。同步失败时，用补偿事务退款并还原标志，所以用户看到的结果与现在相同：媒体服务器没有生效时不扣分。
  - 以上只改变失败情况下的中间状态，正常路径不变。
- **线路目录收拢到一个接口**：线路目录的读写统一经过 `lines` 的目录接口，premium、traffic、reports 不再直接读取 settings 或 `SystemConfig`。存储位置暂时不变，由 `move-line-catalog-to-database` 负责迁移。
- **对外行为不变**：接口路径、状态码、响应、网关使用的 Redis 键和值，以及调度任务，都保持原样。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。这是纯重构，`.openspec.yaml` 设置 `skip_specs: true`。上述单事务改造只影响失败情况下的中间状态。

## Impact

- **代码**：
  - 五个领域。
  - 以下领域中的相关调用：`profile`（模型搬出，以及会员额度、下载解锁的查询）、`reports`（目录和统计）、`accounts`（`all_lib` 的写入）、`gift_pack` 和 `watch_rewards`（改用本变更提供的 `*_tx`）、`rankings`（流量排行）。
  - `identity/rules.py`：宽表会员列的读取规则。
  - 测试依赖：test extra 中加入 `fakeredis`。
- **依赖**：`promote-account-domains`（identity 的类型化 API、traffic 的用户名同步函数）、`make-credit-changes-atomic`、`unify-business-configuration`（`premium_free` 等开关已是领域配置）。
