# Tasks

## 1. 行为冻结与测试补齐

- [x] 1.1 补齐勋章颁发测试：至尊贡献者和游戏王两种检查，分别覆盖单用户模式和批量模式（门槛边界、21 点准确率舍入口径、已持有时不重复颁发、通知文案），以及冠军勋章的续期。外部通知用替身。验证：新测试在当前代码上全部通过；单用户与批量模式在准确率舍入上的差异，由测试明确断言。
- [x] 1.2 为 12 个触发点编写测试：每类操作都会调度恰好一次检查；超时结算、兜底扫描、锦标赛和 `/set_donation` 不调度检查。验证：新测试在当前代码上全部通过。
- [x] 1.3 补齐观看结算测试：Plex 和 Emby 两种结算，覆盖时长封顶、惩罚、勋章加成、邀请人奖励、会员欠额扣费、已绑定 TG 但缺少统计行、幽灵会话补偿与水位线；冻结用户、邀请人和管理员的通知文案。验证：新测试在当前代码上全部通过；通知文案的夹具中包含已知的显示问题。
- [x] 1.4 补齐 badges 测试：定义的增删改查、兑换（成功、积分不足、已持有）、中心配置、加成查询。验证：新测试在当前代码上全部通过；兑换的响应与夹具一致。

## 2. 事件机制扩展与触发点替换

- [x] 2.1 按 design D1 扩展 `core/events.py`：新增 `subscribe_async`、`emit`、`bind_main_loop`，在三种执行上下文中分发，保留任务引用，隔离异常；`main.py` 在 PTB 循环就绪后绑定主循环；新增测试用的 `drain()` 夹具。验证：单元测试覆盖三种执行上下文的分发、任务不会被回收、异常不外泄、回滚时不分发。
- [x] 2.2 在 blackjack、luckywheel、prediction、treasure 中定义事件，按 design D2 的位置在 service 中发布；删除这四个领域对 `badge_awards` 的全部导入和调用。验证：1.2 中四个领域的测试改为断言事件分发后仍然通过；`grep` 确认这四个领域中不再出现 `badge_awards`。
- [x] 2.3 在 donation 和 crypto_donation 中定义事件，在现有的路由触发点改用 `emit`；删除它们对 `badge_awards` 的导入。验证：1.2 中这两个领域的测试通过；`/set_donation` 仍然不分发事件。
- [x] 2.4 在 `app/subscriptions.py` 中注册两组异步订阅。验证：集成测试从路由、线程池任务和 CLI 发布事件后，对应的检查都会执行，并且与 1.1 的结果一致。

## 3. 三个领域的提升

- [x] 3.1 提升 badges：改为模块级 repository；实现 service（兑换在同一事务里、`active_bonus_percentage`、`award_badge` 幂等插入）；新增 `BadgeError` 系列异常并在路由中映射；rankings 的勋章榜改为在内部转换数据；从门面删除 `BadgesRepository`。验证：1.4 的测试通过；在 SQLite 和一次性 PostgreSQL 上并发调用 `award_badge`，每人只有一行、只返回一次 True；勋章榜的响应与夹具一致。
- [x] 3.2 提升 badge_awards：实现 service 中的两个处理函数和两个批量检查；读取数据改为调用各领域的 service（在 luckywheel、treasure、prediction、donation 中新增只读计数函数）；批量模式在每个用户提交之后再追加通知；同步数据库调用改用 `to_thread`。验证：1.1 的测试通过；各计数函数与原 SQL 的口径逐条一致；批量模式下，冲突的用户不会收到通知。
- [x] 3.3 拆分 watch_rewards：提取 rules 和 notifications；repository 的 `settle_user_tx` 通过 premium 的 `*_tx` 写会员欠额，通过 `ensure_statistics_tx` 建档；service 编排；`update_credits` 在线程中完成结算后再发送通知。验证：1.3 的测试逐项通过；`watch_rewards` 中不再出现原生 SQL；调度快照中这个任务的 id、触发器和 runner 都不变。
- [x] 3.4 补上 `badge_awards/__init__.py`。验证：`PYTHONPATH=src .venv/bin/lint-imports --no-cache` 直接通过，没有新增任何 `ignore_imports`；grimp 图中出现 badge_awards 的模块。

## 4. 基线清理与集成验证

- [x] 4.1 清理基线：删除 badges 中 1 处对 `register_cache_invalidation` 的显式调用（design D6）；清除本变更名下的条目（56 条，其中 15 条 `credits.types` 条目已由礼包变更清除），以及以 badge_awards 为目标的 9 条；删除 3 条标给本变更的忽略项、4 条 B3 忽略项和相关的门面组合边忽略项，并下调封存计数；行号移动的条目用重键脚本处理；更新 `docs/architecture.md`，写明 D3 第 1 处环已消除，并补充事件机制的异步用法。验证：`pytest tests/architecture` 通过；`baseline.json` 中不再有本变更名下的条目，也没有以 badge_awards 为目标的条目。
- [x] 4.2 生产形态本地彩排：在完整数据库副本上分别用旧实现和新实现运行一次每日观看结算和两个勋章批量检查（外部服务用固定的替身数据，通知替换为记录器）。验证：积分变化、会员欠额、邀请奖励、颁发的勋章和通知内容逐项一致。
- [x] 4.3 运行全量回归：`pytest tests/`、`ruff check`、`ruff format --check`、`lint-imports`、`pre-commit run --all-files`，然后运行 `openspec validate promote-reward-domains --strict`。验证：全部通过；工作区干净。

### 整合验证补充

- 4.2 的原始旧版对比发现 Emby 欠额参数错误；原始差异已保留。仅修正该参数的旧版对照与新版全部 33 张业务表及结算/通知输出一致，详见 design「实施彩排发现的基线缺陷」及 `docs/architecture.md` 验证记录。
- PostgreSQL 专项实跑：勋章颁发/兑换、邀请码预占和线路目录并发共 25 项通过，无跳过。
- 线路目录、特权码两个平行变更已整合；公共 `.env` writer 已删除，并增加架构守护测试。所有最终结果以整合后全量检查为准。
