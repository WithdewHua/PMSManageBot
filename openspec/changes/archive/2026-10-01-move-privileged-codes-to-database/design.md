# Design

## Context

动机见 proposal.md，行为约定见 `specs/invitation-codes/spec.md`。本设计假定以下变更已完成：

- `promote-account-domains`：invitation 已有 service；兑换积分已改为带 `is_used=0` 条件的单事务。
- `promote-gift-pack-domain`：礼包通过 `invitation.repository.issue_codes_tx(privileged=…)` 发码，特权码的 `.env` 持久化集中在 `invitation.repository.persist_privileged_codes_tx`。
- `unify-business-configuration`：已提供 `LegacyEnvSource`。

现状（调研时的 `3f27100`）：

- **邀请表**（`invitation`）的列：`code`（主键）、`owner`（BIGINT，非空，有索引）、`is_used`（SMALLINT）、`used_by`、`service`、`plex_id`、`emby_id`。没有时间列，也没有特权标记。当前的 alembic head 是 `c0d1e2f3a4b5`。
- **`PRIVILEGED_CODES` 的读取**：兑换时判断是否跳过注册开关（`router.py:196`、`:345`），以及单个检查、批量检查、`add_redeem_code`、礼包发码。
- **写入**：`add_redeem_code` 追加码；Plex 和 Emby 兑换后删除码；礼包在锁内做切片赋值。每处写入之后都会重写 `.env`。
- **特权码的效力**：唯一的区别是跳过注册开关。积分兑换不区分特权码，也不会把特权码从列表中移除。
- **发放特权码的途径**：
  - 管理员接口 `POST /api/admin/invite-codes/generate`，传 `is_premium: true`。
  - 转盘的一次性开关 `gen_privileged_code`：先关开关，再发码，读改写没有加锁。
  - 礼包奖励 `privileged: true`。
- **凭码注册的顺序**：检查 → 外部开号 → 标记已用 → 本地建号或绑定 → 通知管理员 → 从列表删除并写 `.env`。
- **检查接口**：无需认证，只看码在不在列表里；批量接口对数量没有限制。前端用它们来跳过"注册已关闭"的提示，并给特权码显示皇冠标记。

## Goals / Non-Goals

**Goals：**

- 特权属性和邀请记录保存在同一张表、同一个事务里，发放和兑换都没有半成品状态。
- 一个码只能成功兑换一次，并发时输的一方不产生外部副作用。
- 导入只执行一次，并且对照升级前实际生效的列表。

**Non-Goals：**

- 不改变特权码的效力：它仍然只跳过注册开关。
- 不给检查接口加认证，也不限制批量数量，接口契约保持不变。
- 不删除 `save_config_to_env_file`：线路目录仍在使用它。
- 不改 `gen_privileged_code` 的开关语义。它读改写时的加锁问题，已经由 `promote-activity-domains` 处理。

## Decisions

### D1 在邀请表上加特权标记

- **新增列**：`invitation.is_privileged SMALLINT NOT NULL DEFAULT 0`，写法与 `is_used` 保持一致。检查接口按主键查询，不需要额外的索引。
- **迁移**：alembic 迁移只加这一列，downgrade 删除它。
- **发放**：`issue_codes_tx(..., privileged=True)` 直接写 `is_privileged=1`。删除 `persist_privileged_codes_tx`、礼包对它的调用，以及模块锁。
- **转盘和管理员生成**：都改用 `invitation.service.generate_codes(..., privileged=True)`。

备选方案：新建一张 `privileged_codes` 表，以外键指向邀请码。这样做需要多维护一张表的一致性，而它存的只是一个布尔属性；何况每个特权码本来就有邀请记录。所以不采用。

### D2 预占—开号—确认，保证只兑换一次

凭码注册分三个阶段：

1. **预占**：在一个事务里执行 `UPDATE invitation SET is_used=1, used_by=?, service=? WHERE code=? AND is_used=0`，并在同一事务里读出 `is_privileged`。
   - 影响行数为 0 时，抛出 `InvitationCodeUsed`，或者在码不存在时抛出 `InvitationCodeNotFound`。
   - 现在是先判断注册开关、再检查码，所以开关关闭时，即使码不存在，返回的也是"注册已关闭"。为保持这个顺序：
     - 开关关闭时，只有"存在、未使用、带特权标记"的码可以继续预占，其余一律在同一事务中回滚，并返回"注册已关闭"。
     - 开关打开时，按上面的规则区分"已被使用"和"不存在"。
2. **开号**：在事务之外调用 Plex 或 Emby。失败时执行释放：`UPDATE ... SET is_used=0, used_by=NULL, service=NULL WHERE code=? AND used_by=?`，然后返回原有的失败提示。
3. **确认**：回填 `plex_id` 或 `emby_id`，本地建号或绑定。之后的通知在提交后执行。

几点说明：

- 兑换积分已经在 `promote-account-domains` 中改为条件更新，这里不需要再改。
- 进程如果在第 1、2 步之间崩溃，这个码会停留在"已用、但没有外部账号"的状态。日志中记录预占的信息，管理员可以据此人工释放。这种情况比"两个外部账号"容易处理。

备选方案：在开号期间一直持有行锁。外部调用可能耗时数十秒，长事务会占用连接并阻塞其他查询，所以不采用。

### D3 检查接口

- 单个和批量检查都改为一次查询：`WHERE code IN (...) AND is_used=0 AND is_privileged=1`。
- 批量接口仍然返回每个输入码的结果，不存在的码为 false。
- 请求和响应的模型、路径和鉴权方式都不变。

### D4 一次性导入

- **读取**：用 `LegacyEnvSource` 读取升级前实际生效的 `PRIVILEGED_CODES`，优先级与旧加载器一致。
- **时机**：`main.py` 在初始化数据库之后、启动服务之前执行导入；`manage.py` 不执行。
- **处理规则**：
  - 存在且未使用的码：设 `is_privileged=1`。
  - 已被使用的码：跳过，记 info 日志。这个码当初是不是作为特权码被兑换的，已经无从判断，所以不追溯标记。
  - 在数据库中不存在的码：跳过，记 warning 日志。
- **执行一次**：导入完成后，用 `core.kv` 写入标记 `invitation/privileged_codes_imported`，值是导入时间和计数。之后的启动看到这个标记就跳过导入。
- **启动警告**：`.env` 或环境变量里仍有 `PRIVILEGED_CODES` 时，与 unify 变更一样，启动时警告"已迁出，不再生效"。
- **删除配置字段**：删除 `Settings.PRIVILEGED_CODES`。

### D5 删除 `.env` 写入与文档更新

- **删除写入**：删除 invitation 中 4 处写特权码的 `.env` 调用，以及列表的增删逻辑。
- **更新文档**：`docs/architecture.md` 的例外清单删除"特权码提交前写 `.env`"；"配置分类"一节注明特权码已迁入数据库。
- **仍保留的调用**：`save_config_to_env_file` 剩下线路目录的 4 处调用。

## Risks / Trade-offs

- **[导入把 `.env` 中的"脏码"排除在外]** → 已使用和不存在的码都记日志，在生产形态副本上先跑一遍导入，把跳过的清单交给维护者核对。
- **[预占和开号之间崩溃，留下"已用、但没有外部账号"的码]** → 记录预占日志，并在运维文档中写明人工释放的方法。它的影响远小于并发下开出两个外部账号。
- **[检查接口的结果在边缘情况下变化]** → 只影响列表和数据库原本就不一致的码，这是修复；spec 已写明。
- **[回退]** → 旧版本只读 `.env`，导入后在数据库中新发放的特权码，回退后会失去特权。回退前，用只读脚本把"未使用的特权码"导出为 `PRIVILEGED_CODES` 行，写回 `.env`。

## Migration Plan

1. alembic 迁移：新增 `is_privileged` 列。在一次性 PostgreSQL 上执行 upgrade → downgrade → upgrade，并做元数据比对。
2. 实现发放、预占兑换、检查接口和一次性导入，每一项配测试。
3. 在生产形态副本上演练导入，由维护者核对跳过的清单。
4. 部署：先执行迁移，再启动新版本；首次启动时自动导入。
5. 回退：运行导出脚本，把导出的行写回 `.env`，然后回退镜像。新增的列保留，旧版本会忽略它。

## Open Questions

无。
