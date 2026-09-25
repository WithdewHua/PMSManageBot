## Why

线路相关的逻辑分散在很多地方：

- `user.py`：线路绑定和线路调度接口
- `admin.py`：线路管理
- `db_func`：自动切换线路的任务
- `utils`：高级线路判断
- `premium.py`：会员流程和媒体权限同步

此外，`custom_line.py` 还从 admin 路由导入业务函数。这些区域目前都没有测试。

## What Changes

- **先补测试**，记录以下场景的现有行为：
  - 线路绑定和权限
  - 线路调度
  - 会员开通和到期
  - 下载与 NSFW 解锁
  - 自建线路的审核和流量结算
- **按提升模板处理五个领域**：`lines`、`custom_lines`、`traffic`、`premium`、`media_access`。
- **媒体服务器权限同步统一放到提交后**：Plex/Emby 权限同步涉及网络调用，统一由 service 在事务提交后执行。
- **线路目录收拢到一个接口**：线路目录的读写统一经过 `lines` 的一个接口。存储位置暂时不变，由 `move-line-catalog-to-database` 负责迁移。
- **对外行为不变**。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。这是纯重构，`.openspec.yaml` 设置 `skip_specs: true`。

## Impact

- **代码**：
  - 上述五个领域
  - 以下领域中的相关调用：`gift_pack`、`luckywheel`（会员奖励）、`watch_rewards`（会员流量扣费）、`profile`、`reports`
- **依赖**：`promote-account-domains`、`make-credit-changes-atomic`
