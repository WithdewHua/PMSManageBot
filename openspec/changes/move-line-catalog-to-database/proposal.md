## Why

线路目录现在分散在三处：

- `.env` 中的 `STREAM_BACKEND` 和 `PREMIUM_STREAM_BACKEND` 两个列表。
- `SystemConfig` 中的 `line_tag`。
- `SystemConfig` 中的 `free_premium_line`。

后台增删线路时，要先改内存里的 `settings`，再重写 `.env`。线路标签和免费高级线路又各自单独存了一份，几处数据很容易对不上。

## What Changes

- **新增线路表**：在 `lines` 领域新建一张线路表，记录名称、类型（普通或高级）、标签、是否免费开放、排序等字段，并附带 alembic 迁移。
- **导入现有目录**：首次启动时，从 `.env` 和 `SystemConfig` 导入现有线路目录，导入操作幂等。
- **对外接口不变**：
  - 后台线路管理接口和用户线路列表接口的 URL、响应格式不变。
  - 网关使用的 Redis 缓存键和缓存内容不变。
- **删除旧配置**：删除 `.env` 中的两个线路列表，以及 `SystemConfig` 中对应的键。如果 `save_config_to_env_file` 已经没有其他调用方，一并删除。
- **BREAKING（运维）**：导入完成后，`.env` 中的线路列表不再生效。

## Capabilities

### New Capabilities

- `line-catalog`：线路目录的存放与维护。包括：
  - 普通线路、高级线路、标签和免费高级线路的定义。
  - 后台修改后立即生效。
  - 从旧配置导入。

### Modified Capabilities

无。

## Impact

- **代码**：`domains/lines/`、`core/config.py`，以及后台的线路管理接口。
- **数据库**：需要 alembic 迁移。
- **依赖**：`promote-line-domains`、`unify-business-configuration`。
