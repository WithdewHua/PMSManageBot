## Why

线路目录现在分散在三处：

- `.env` 中的 `STREAM_BACKEND`、`PREMIUM_STREAM_BACKEND` 两个列表。
- `SystemConfig` 中的 `line_tag`：以线路名为键，逗号分隔的标签串为值。
- `SystemConfig` 中的 `free_premium_line`：以线路名为键，值为 `"1"`。

后台增删线路时，要先改内存中的 `settings`，再重写 `.env`。线路标签和免费高级线路又各自单独存了一份，几处数据很容易对不上：

- 删除线路要依次重写 `.env`、删除免费标记、删除标签，这几步不在一个事务里，中途失败就会在 `SystemConfig` 里留下孤儿键。设置标签时不检查线路是否存在，也会留下孤儿键。
- 设置免费线路时逐条写入，每条一个事务，中途失败会只改了一部分。
- 标签保存时经过 `set()`，顺序是随机的。
- 免费线路读取时没有排序。
- 线路名包含逗号时会破坏 `.env` 的编码；包含 `/` 时，删除接口无法匹配到这条线路。

`promote-line-domains` 已经把目录的读写收拢到 `lines` 的目录接口，现在可以只替换存储。完成后，业务代码中就不再有写 `.env` 的地方。

## What Changes

- **新增线路表**：在 `lines` 领域新建线路表，附带 alembic 迁移。每条线路记录名称（唯一）、类型（普通或高级）、在同类中的顺序、标签（有序）和是否免费开放。
- **导入现有目录**：首次启动时，从升级前实际生效的两个列表，以及 `SystemConfig` 中的标签和免费标记导入目录。
  - 两个列表的顺序保持不变。
  - 孤儿键和冲突项跳过并记录日志。
  - 导入只执行一次，完成后删除 `SystemConfig` 中的这两类键。
- **对外接口不变**：
  - 后台线路管理接口（包括 `emby-*` 兼容路径）、标签接口、免费高级线路接口、设置总览，以及用户线路列表接口，URL 和响应格式都不变。
  - 网关使用的 Redis 缓存键和缓存内容不变。
- **明确几处边缘规则**：
  - 标签去掉首尾空白并丢弃空标签；含 `,` 的标签按 `,` 拆开，与现在读取时的结果相同；然后按提交顺序去重保存。
  - 免费线路按目录顺序输出。
  - 给不存在的线路设置标签时返回失败。
  - 新增的线路名不能为空，不能包含 `/` 或 `,`。
- **删除旧配置**：
  - 删除 `Settings` 中的两个线路列表字段。`.env` 或环境变量中残留这两个键时，启动时发出警告。
  - 业务代码不再写 `.env`，`save_config_to_env_file` 随之删除。如果 `unify-business-configuration` 经维护者确认保留了手动运维用的 `save_current_config`，就改为只供它使用的私有方法。
- **BREAKING（运维）**：导入完成后，`.env` 中的线路列表不再生效，要在后台修改。

## Capabilities

### New Capabilities

- `line-catalog`：线路目录的存放与维护，包括：
  - 普通线路、高级线路、标签和免费高级线路的定义与顺序。
  - 后台修改立即生效，并在重启后保留。
  - 删除线路时，对用户绑定和线路调度的影响。
  - 用户线路列表的组成与顺序。
  - 从旧配置导入。

### Modified Capabilities

无。全局的"免费开放高级线路"开关（`PREMIUM_FREE`）属于 `business-configuration`，不在本能力中。

## Impact

- **代码**：`domains/lines/`（模型、目录的 repository 与 service），以及 `core/config.py`（删除两个列表字段，处理 `save_config_to_env_file`）。后台接口的实现代码已经由 `promote-line-domains` 收拢到目录接口，本变更不需要改动。
- **数据库**：需要 alembic 迁移，新增线路表。
- **回退**：回退前运行只读导出脚本，把目录恢复为 `.env` 中的两个列表行和 `SystemConfig` 中的键。
- **依赖**：
  - `promote-line-domains`、`unify-business-configuration`。
  - `move-privileged-codes-to-database`：只影响 `save_config_to_env_file` 能否删除。它删除了特权码的 `.env` 写入，之后业务代码中写 `.env` 的只剩线路目录。
