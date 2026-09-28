# Tasks

## 1. 行为冻结与测试补齐

- [ ] 1.1 冻结三个领域的行为快照：OpenAPI 与路由顺序、bot handler、调度任务，以及绑定、凭码注册、邀请码、注册开关、Overseerr 各接口和命令在成功与各类拒绝下的响应夹具；把 identity、invitation 的 mixin 方法和 accounts 的模块函数登记进 `mapping.toml` 并写明目标位置。验证：连续生成两次，快照一致；没有未映射的成员。
- [ ] 1.2 补齐绑定测试：Plex 和 Emby 的路由预检、新建账号行、合并未绑定积分、邮箱无权限、账号已被其他 TG 绑定、观看时长查询失败、Emby 回滚。外部接口用替身。验证：新测试在当前代码上全部通过。
- [ ] 1.3 补齐邀请测试：
  - 凭码注册：Plex 全流程；Emby 的绑定、不绑定、绑定失败三种分支。
  - 邀请码：路由、bot、管理员三处生成，以及 `points-info` 返回 500 的现状。
  - 兑换积分，包括"UPDATE 不检查 `is_used`"的现状。
  - `register-status`。

  验证：新测试在当前代码上全部通过，已知问题的现状由测试明确断言。
- [ ] 1.4 补齐同步测试：`update_plex_info` 的改名、按邮箱回填 plex_id、回填 invitation、改流量用户名，以及缺少本地行时中止的现状；`update_users_last_viewed`、`refresh_emby_user_info`、`/create_overseerr`。验证：新测试在当前代码上全部通过。

## 2. identity 的类型化 API 与兼容层

- [ ] 2.1 新增 `identity/types.py` 中的数据类，以及 design D1 列出的模块级查询、计数和建档函数（都有 `*_tx` 版本），由 identity.service 暴露不带事务的版本。验证：单元测试覆盖每个函数的命中、未命中、邮箱忽略大小写，以及在调用方事务里读取。
- [ ] 2.2 把 `IdentityRepository` 改为只做转发的兼容层：没有 SQL，结果转换回原来的元组，保留原有吞异常的语义；把 `add_plex_user` 和 `add_emby_user` 中"提交前写缓存"改为提交后回调。新增架构检查：兼容层不得导入 SQLAlchemy。验证：现有调用方的测试全部通过；兼容层中的 SQL 导入会让检查失败；事务回滚时缓存不被写入。
- [ ] 2.3 把 accounts、invitation 和两个回填脚本改用新 API。验证：用 AST 确认这些模块不再对 identity 的查询结果做下标访问；第 1 组的测试全部通过。
- [ ] 2.4 对 4 个没有调用方的函数，核对手动运维清单并请维护者确认，确认后删除。在 `docs/architecture.md` 中写明两条规则："建档一律调用 `ensure_statistics_tx`"，以及兼容层的剩余调用方和各自的负责变更。验证：确认结论记录在本变更中；文档中列出的剩余调用方与代码一致。

## 3. 领域事件与具名任务

- [ ] 3.1 实现 `core/events.py`：`DomainEvent`、`publish`、`subscribe`、提交后分发、异常隔离；新增 `app/subscriptions.py` 的 `register_all()`，由 `main.py`、`manage.py` 和测试夹具调用；把 `app.subscriptions` 加入顶层分层合约；在架构检查中放行 `events` 角色跨域导入，并禁止在组装层以外调用 `subscribe`。验证：单元测试覆盖——提交后分发、回滚后丢弃、处理函数抛错不影响原事务、同一 session 的多个事件按顺序分发；AST 检查的正反例测试通过。
- [ ] 3.2 accounts 在"按邮箱回填 plex_id"时发布 `PlexUserIdResolved`，invitation 订阅并回填邀请记录，条件与原实现相同；删除 accounts 对 `update_invitation_plex_id` 的调用。验证：
  - 回填的触发条件和结果与 1.4 的夹具一致，包括区分大小写。
  - accounts 不再导入或调用 invitation。
  - `Acyclic domain siblings` 合约通过。
- [ ] 3.3 在 `core.scheduler.schedule_task` 上增加内存 jobstore 的 interval 触发（带结束时间）；凭码注册改为调度具名任务 `invitation.resolve_plex_id`，任务完成后自己移除；删除守护线程。验证：单元测试覆盖 interval 具名任务的注册、执行和自我移除；调度快照中该任务的开始时间、间隔和结束时间与原实现一致。

## 4. service 与入口迁移

- [ ] 4.1 实现 `accounts.service`：Plex 和 Emby 绑定、Overseerr 建号、同步编排，以及 `/set_register`；新增 `traffic.service.rename_user`；路由和 bot 只调用 service。验证：第 1 组中 accounts 相关的夹具逐项一致；accounts 的入口不再导入门面、models 或 SQLAlchemy。
- [ ] 4.2 实现 `invitation.service`：
  - `generate_codes`：扣分和插码在同一事务里。
  - `redeem_for_credits`：条件更新加上加分，在同一事务里。
  - `register_plex` 和 `register_emby`。
  - `add_redeem_code` 的兼容语义。

  定义 `InvitationError` 系列异常，并在路由中映射回原来的响应模型。验证：
  - 生成时注入扣分失败，不会留下码。
  - 在一次性 PostgreSQL 上并发兑换同一个码，只有一次成功。
  - 其余夹具逐项一致。
  - 路由中不再有字符串匹配。
- [ ] 4.3 把 watch_rewards 对邀请人查询的 2 处调用改为调用 `invitation.service`。验证：观看结算的邀请人奖励测试通过；这 2 条基线条目已删除。
- [ ] 4.4 清理基线和合约：删除 accounts 中 3 处对 `register_cache_invalidation` 的显式调用（design D6）；清除本批的基线条目（63 条，其中 12 条 `credits.types` 条目已由礼包变更清除）；删除 7 个门面冻结放行项、B3 标注的 9 条范围忽略项，以及入口合约和六层合约中本批的 `→db` 忽略项；把 4 条兼容层组合边的注释改为 retire 负责；下调封存计数。验证：`PYTHONPATH=src .venv/bin/lint-imports --no-cache` 和 `pytest tests/architecture` 通过；`baseline.json` 中不再有 owner 为本变更的条目。

## 5. 集成验证

- [ ] 5.1 运行全量回归：`pytest tests/`、`ruff check`、`ruff format --check`、`lint-imports`、`pre-commit run --all-files`。验证：全部通过；OpenAPI、路由、调度和 Bot 快照与 1.1 一致，唯一的差异是具名任务的注册方式。
- [ ] 5.2 生产形态本地彩排：外部接口用替身，完成一次 Plex 凭码注册（绑定 TG），然后运行同步任务。验证：plex_user 和 invitation 的 plex_id 都被回填；具名任务自己移除；日志中没有异常。
- [ ] 5.3 运行 `openspec validate promote-account-domains --strict`。验证：校验通过；工作区干净。
