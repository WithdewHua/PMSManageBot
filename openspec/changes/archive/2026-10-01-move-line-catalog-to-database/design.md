# Design

## Context

动机见 proposal.md，行为约定见 `specs/line-catalog/spec.md`。本设计假定以下变更已完成：

- `promote-line-domains`：新增了 `lines/catalog.py`（repository 角色）和 `lines.service` 中的目录函数，作为读写目录的唯一入口。它们仍然读写 `settings` 加 `save_config_to_env_file`（两个列表），以及 `core.kv`（标签和免费标记）。lines 以外读取这些配置会被架构检查拒绝。
- `unify-business-configuration`：已提供 `LegacyEnvSource`；`Settings` 已设为 `extra="ignore"`；全局开关 `premium_free` 已在 lines 的配置中。
- `move-privileged-codes-to-database`：删除了特权码的 `.env` 写入。业务代码中调用 `save_config_to_env_file` 的只剩目录接口。

现状（在 `75bc98c` 核对）：

- **两个列表**：`STREAM_BACKEND` 和 `PREMIUM_STREAM_BACKEND` 是 `list[str]`，从 `.env` 按逗号分隔加载。
- **新增线路**：名称去掉首尾空白；空名、同类重复、跨类重复都会被拒绝，各有固定的提示文案。通过后追加到列表末尾，重写 `.env`，再发送频道通知。
- **删除线路**：依次重写 `.env`、删除免费标记（仅高级线路）、删除标签、把绑定该线路的用户切回自动线路，最后禁用该线路的调度并通知。这几步各自提交。
- **免费线路**：`SystemConfig(free_premium_line, <线路名>) = "1"`。设置接口先校验都在高级线路列表中，再逐条删除、写入，每条一个事务。读取时没有排序。
- **标签**：
  - 保存为 `",".join(set(tags))`，所以顺序随机；标签为空时删除这个键。设置时不检查线路是否存在。
  - 读取时按 `,` 拆分，去掉空白，丢弃空串。
  - `all_line_tags` 遍历两类线路名的集合，所以键的顺序也是随机的。
- **列表的顺序**：决定用户线路列表、管理员列表和高级线路流量统计的输出顺序，但不影响自动切换。
- **匹配规则**：绑定时判断高级线路用子串匹配；免费列表的成员判断和流量统计用精确匹配。
- **线路名**：实际存的是主机名，不做规范化。本地副本有 10 条普通线路、5 条高级线路：列表内和两类之间都没有重复，也没有含 `/` 的名称。
- **alembic**：当前 head 是 `c0d1e2f3a4b5`。`move-privileged-codes-to-database` 的迁移可能先落在它之后，实施时以最新的 head 为准。

## Goals / Non-Goals

**Goals：**

- 目录保存在一张表里，线路、顺序、标签和免费标记由同一套事务维护，彼此不会脱节。
- 接口响应、用户列表顺序和网关缓存都不变；只按规格明确几处边缘规则。
- 导入只执行一次，可以审计；回退时有导出路径。

**Non-Goals：**

- 不改子串匹配和精确匹配的规则，也不规范化已有的线路名。
- 不新增改名、改类型、调整顺序的接口。
- 不改全局免费开关（`premium_free`），它是业务配置。
- 不改删除线路和取消免费开放之后的解绑、禁用调度和通知。这些由 `promote-line-domains` 的 service 编排，本变更只换存储。

## Decisions

### D1 线路表

```text
line_catalog
  id          BIGINT PK autoincrement
  name        TEXT NOT NULL                -- uq_line_catalog_name
  kind        TEXT NOT NULL                -- ck_line_catalog_kind: kind IN ('normal', 'premium')
  position    INTEGER NOT NULL             -- ck_line_catalog_position: position >= 0
  tags        TEXT NOT NULL DEFAULT '[]'   -- JSON 数组，有序
  free_open   SMALLINT NOT NULL DEFAULT 0  -- ck_line_catalog_free_open: free_open IN (0, 1) AND (free_open = 0 OR kind = 'premium')
  created_at  BIGINT NOT NULL
  updated_at  BIGINT NOT NULL
  uq_line_catalog_kind_position: UNIQUE (kind, position)
```

- **写法与现有表一致**：参照礼包表，用 BIGINT 主键、SMALLINT 标志加 `IN (0, 1)` 检查、BIGINT 时间戳，JSON 存为 TEXT，约束都显式命名。
- **标签存在同一行**：用 JSON 数组保存，不另建标签表。规格要求"只能给目录中已有的线路设置标签"，所以标签和线路的生命周期完全一致，删除线路时一并删除。
- **免费标记用列表示**：`free_open` 是一列，而不是单独的表。只有高级线路可以为 1，由检查约束保证。
- **顺序**：`position` 是同类中的排序键。新增时取同类的 `max(position) + 1`；删除时不重排，允许留下空洞。读取一律 `ORDER BY position`，输出与列表语义一致。
  - 不重排的原因：批量前移会在非延迟的唯一约束上中途冲突，要么需要可延迟约束（SQLite 不支持），要么要分两步改写。而空洞不影响任何输出。
  - 并发新增：两个请求读到同一个最大值时，`UNIQUE (kind, position)` 让后提交的一方失败，service 捕获后重试一次，仍然失败就返回现有的失败响应。同名的并发新增由 `UNIQUE (name)` 挡住，返回"已存在"的提示。

备选方案：沿用 `SystemConfig`，加一个存 JSON 的"线路列表"键。这样仍然是三份数据，一致性问题没有解决。

### D2 目录接口换存储

`lines/catalog.py` 改为读写 `line_catalog`；`lines.service` 中目录函数的签名和调用方都不变：

| 函数 | 实现 |
|---|---|
| `normal_lines` / `premium_lines` | 按类型读取，`ORDER BY position` |
| `free_premium_lines` | `kind = 'premium' AND free_open = 1 ORDER BY position` |
| `line_tags` / `all_line_tags` | 读 `tags` 列。`all_line_tags` 覆盖目录中的全部线路，没有标签的是空列表，与现在一致；键按目录顺序排列，普通线路在前 |
| `add_line` | 名称去掉首尾空白后，校验非空、不含 `/` 和 `,`，并校验同类和跨类都不重复；排在同类末尾。现有的失败提示文案不变，非法字符用新的提示。提交后发送现有的频道通知 |
| `delete_line` | 在一个事务里删除该行，标签和免费标记随之删除。提交后的解绑、禁用调度和通知不变 |
| `set_line_tags` | 线路不存在时失败。按规格规范化后写入；空列表写 `[]`，效果与现在删除这个键相同 |
| `set_free_premium_lines` | 一个事务：校验全部是目录中的高级线路，再更新 `free_open`。提交后，按现有逻辑处理被取消免费开放的线路，并对新开放的线路发送频道通知 |

- **缓存**：目录读取经过进程内缓存。本进程的写入在提交后立即让缓存失效；另设与 `DomainConfig` 相同的 30 秒 TTL，兜底进程外的修改，例如导出脚本的 `--apply` 或直接改库。
- **与现在不同的地方**，规格已经写明，并由专门的测试断言：
  - 标签顺序从随机变为提交顺序。
  - 免费线路从没有排序变为按目录顺序。
  - 为不存在的线路设置标签，从静默成功变为失败。
  - 新增线路名中的 `/` 和 `,` 被拒绝。
  - `all_line_tags` 的键从随机顺序变为目录顺序。前端按键取值，不受影响；回归测试按字典比较。

### D3 一次性导入

- **读取来源**：
  - 用 `LegacyEnvSource` 读取升级前实际生效的两个列表，优先级与旧加载器一致。
  - 从 `core.kv` 读取全部 `line_tag` 行，按现在读取时的规则拆分（按 `,` 拆分、去掉空白、丢弃空串），保持存储时的顺序。
  - 从 `core.kv` 读取全部 `free_premium_line` 行，按现在读取免费线路的规则判断哪些生效。
- **导入规则**：
  - 先导入普通线路，再导入高级线路，`position` 按线路在列表中的位置从 0 编号。
  - 以下情况跳过，并逐条记 warning：
    - 同一列表内的重复名称：保留第一次出现。
    - 同时出现在两个列表中的名称：保留在普通线路中。
    - 对应线路不在目录中的标签和免费标记。
    - 普通线路上的免费标记。
  - 已有的线路名不做 D2 的名称校验，原样导入。
- **一个事务**：写入 `line_catalog`，删除这两类 kv 行，并在 `core.kv` 中写入完成标记 `lines/catalog_imported`（值包括导入时间和各类计数）。
- **执行时机**：`main.py` 在初始化数据库之后、启动服务之前执行导入，与业务配置的种子和特权码的导入在同一阶段；`manage.py` 不执行。已有完成标记时直接跳过。
- **删除旧配置**：删除 `Settings` 中的两个列表字段。三个旧来源中仍有这两个键时，启动时警告"已迁出，不再生效"。

### D4 `save_config_to_env_file` 的去留

本变更之后，业务代码不再调用 `save_config_to_env_file`，只剩 `Settings.save_current_config` 内部的一处。按 `unify-business-configuration` 任务 6.2 的结论处理：

- **已经删除了 `save_current_config` 和 `get_saveable_config`**：一并删除 `save_config_to_env_file`。
- **经维护者确认保留**：把它改为私有方法，只供 `save_current_config` 使用，并加一条架构测试，禁止 `src` 中的其他代码调用它。

实施时如果 `move-privileged-codes-to-database` 还没有完成，特权码仍在写 `.env`，本变更就只删除目录的调用，`save_config_to_env_file` 留给那个变更处理。

`docs/architecture.md` 的"配置分类"一节：删除"遗留例外"中关于线路目录的内容；这一条没有其他内容时整条删除，并写明运行时业务数据一律存在数据库，`.env` 只存放只读的部署配置。

### D5 回退导出

新增只读脚本 `scripts/export_line_catalog.py`，输出两部分：

- `STREAM_BACKEND=…`、`PREMIUM_STREAM_BACKEND=…` 两行，按目录顺序。
- 用于恢复 `line_tag` 和 `free_premium_line` 两类 kv 行的 SQL。标签按保存的顺序用 `,` 连接，免费线路按目录顺序。

也可以用 `--apply` 直接写入这两类 kv 行。只有 `--apply` 会写库，而且需要显式指定；它不修改 `line_catalog`。

## Risks / Trade-offs

- **[导入时丢弃孤儿键]** → 每条都记录日志；先在生产形态副本上演练导入，把跳过的清单交给维护者确认。
- **[回退时标签顺序和免费线路集合的还原]** → 导出脚本按目录顺序还原；旧版本读取时本来就不保证标签顺序，所以回退后的行为与升级前一致。
- **[并发新增时顺序值冲突]** → 唯一约束兜底，service 重试一次；在一次性 PostgreSQL 上做并发新增测试，确认没有重复的顺序值，目录不被破坏。
- **[线路名规则收紧]** → 只作用于新增的线路，已有的线路原样导入。

## Migration Plan

1. alembic 迁移：新增 `line_catalog` 表。在一次性 PostgreSQL 上执行 upgrade → downgrade → upgrade，并做元数据比对。
2. 实现 repository，替换目录接口的存储，实现导入和导出脚本，每一项配测试。
3. 在生产形态副本上演练导入：核对导入的目录，与原来的两个列表、标签和免费标记逐项一致；跳过清单交给维护者确认。
4. 部署：先执行迁移，再启动新版本；首次启动时自动导入。
5. 回退：运行导出脚本，把两个列表行写回 `.env`，并用 `--apply` 恢复 kv 行，然后回退镜像。新增的表保留，旧版本会忽略它。

## Open Questions

无。
