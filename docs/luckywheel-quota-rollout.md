# 转盘邀请码周限额：上线与回滚手册

本手册面向维护者。以下生产命令是操作说明，不表示开发验证时已执行生产操作。

接口变更与管理员使用见 [luckywheel-api.md](luckywheel-api.md)。结构版本为 `6c54e137c19b`，前一版本为 `b5c6d7e8f9a0`。

## 上线前提

- 全服默认 30、个人默认 5，按北京时间周一 00:00 划周；上线前本周已发码计入。
- 不撤销、截断或兑换回收已发的邀请码；历史超过新上限时保留真实用量，阻止后续发行。
- 新后端、管理员前端及迁移应使用同一已验证镜像版本。现有 Compose 示例使用 `latest`，正式上线建议固定具体 tag 或 digest。
- 必须停止所有旧版抽奖写入者，包括其他实例、机器人及相关调度进程；仅关闭某个 HTTP 页面不够。
- 先备份数据库。历史报告含 Telegram ID，应限制访问，不提交到 Git 或粘贴到公开日志。
- 只凭现有 `WheelStats` 不能证明真实发码历史完整。必须人工核对本周部署历史、曾使用的自定义奖项语义和数据是否缺失；不确定则保持维护状态。

## 维护窗口操作

以下命令基于仓库现有 Compose 服务名 `pmsmanagebot` 和 `/app/data` 数据卷。`docker compose run` 覆盖镜像默认启动命令，不启动应用、机器人或调度器。

### 1. 停止写入并升级结构

停止其他部署实例后，在本部署执行：

```sh
docker compose stop pmsmanagebot
docker compose run --rm --no-deps pmsmanagebot alembic upgrade head
```

必须显式确认迁移成功，不依赖 `start.sh` 的错误处理继续启动。迁移仅新增账本结构，不回填首周业务数据。SQLite 还将原 `wheel_stats.id` 的物理类型改为 `INTEGER PRIMARY KEY` 以支持自动生成审计关联 ID，保留全部原 ID 值；PostgreSQL 的原 BIGINT 主键不改变。

### 2. 生成只读历史报告

```sh
docker compose run --rm --no-deps pmsmanagebot \
  python scripts/initialize_luckywheel_invite_quotas.py \
  --output /app/data/wheel-quota-baseline.json
```

脚本默认只读数据库；`--output` 创建权限为 0600 的新文件，文件已存在时拒绝覆盖。重新生成时使用新文件名或由维护者明确处置旧报告。

检查报告：

- `week_start_ms` / `week_end_ms` 是当前北京时间自然周。
- `scanned_count`、`prize_counts` 覆盖本周全部来源；按时间戳而不是可能错误的旧 `date` 字段划周。
- `rows` 是按实际奖品效果识别的邀请码候选记录，`issued` 是候选数量，`users` 是个人汇总。
- 历史 NULL 来源保留未知，不按参与费推断是否免费。
- 历史已使用、已兑换积分的码不能从用量中扣除。
- 确认自定义名称的真实历史效果及记录完整性。报告只是核对材料，不是对历史发码事实的独立证明。

不能通过修改报告内的数量、TG ID 或候选行来直接重写额度；apply 会重新计算并核对源记录。缺失或歧义必须先调查解决，不能默认按零初始化。

### 3. 确认并原子应用

确认全部写入者仍停止，且维护者已核对历史后：

```sh
docker compose run --rm --no-deps pmsmanagebot \
  python scripts/initialize_luckywheel_invite_quotas.py \
  --apply --input /app/data/wheel-quota-baseline.json \
  --history-verified --writers-stopped
```

这两个标志是维护者明确确认，不是脚本自动判断外部进程已停止或历史完整。

- 源记录变化、报告修改、跨周或配置损坏会拒绝执行。
- 同一报告重复 apply 不覆盖上线后新增计数，不重复回填。
- 已存在其他初始化基线时拒绝覆盖。后续正常自然周不需要再次运行脚本，应用会安全创建新周期行。
- 操作不生成邀请码、不修改用户余额、不发送通知。失败会回滚整个初始化事务。
- 如果维护窗口跨周，重新生成并核对当前周报告，不使用旧周报告继续启用。

本地隔离环境也可用 `.venv/bin/python scripts/initialize_luckywheel_invite_quotas.py ...`。默认数据库仍由环境配置决定；测试时必须显式传入临时 `DATA_DIR` 和独立 `DATABASE_URL`，禁止误用生产 `data/.env`。

### 4. 启动与核对

```sh
docker compose up -d pmsmanagebot
```

开放抽奖前确认：

1. 管理员新接口能读取完整奖池，普通 `/api/luckywheel/config` 只有公开白名单字段。
2. 管理员周统计 `initialized=true`，历史量与已审核报告一致，历史量加新增量等于全服实际用量。
3. 管理限额是预期的 30 / 5（或明确配置的值）；0 表示禁止对应范围发码。
4. 单抽、免费抽、十连抽的所有最终奖项对象均不含 `probability`。
5. 普通用户不能读取管理配置或审计；普通界面没有限额或重选提示。
6. 初始化缺失或存储故障时，抽奖失败且不扣费，不把故障当作额度充足或普通重选。

## 调整与观察

通过管理员面板或管理员限额接口调整，不直接改周计数或审计记录。限额取数据库可存储的非负整数（0～2147483647）；调低不撤销已发码，调高只增加剩余空间。新结算读取已提交的新配置，进行中的结算保持快照。

配额默认值只在首次账本初始化之前由 owning repository（转盘所属仓储）受控创建，`seed_all()` 不自动播种该配置。一旦存在账本，配额配置丢失时，管理员读取和应用重启均不得重建 30/5 默认值；抽奖保持关闭，维护者须查明原因并明确恢复经核对的完整配额配置，不能靠删行重启恢复默认值。

观察 2～4 个完整周：全服与个人发行量、历史/新增核对、触顶分布、不同抽奖来源、周初耗尽情况、存储或锁异常。全服与个人命中可以同时发生，不能把三个命中计数直接相加。无法从证据确定的历史时间或特权状态保持未知，不自行填造。

不添加定时清零任务；周期键承担换周。用户换绑迁移审计归属，个人数量合并，全服数量不变。

## 回滚

1. 先关闭抽奖并停止所有相关写入者，禁止旧新版同时发码。
2. 优先回退应用与前端，保留新表、审计和已审核报告。旧代码不执行本次硬限额，不能在恢复旧版抽奖后仍声称受 30/5 保护。
3. 若必须降级结构，先单独导出配额周记录和审计，停机执行 `alembic downgrade b5c6d7e8f9a0`。该操作会删除新增账本；原邀请码及用户余额不撤销，原统计 ID 保留。
4. 再次升级必须核对本周期间的全部发行事实。旧代码恢复期间可能新增发码，不能信任过期的初始化基线；未经核对不要重新开放。

## 可重复验证入口

```sh
# 普通隔离 SQLite、HTTP、迁移和并发回归
.venv/bin/python -m pytest tests/test_luckywheel_invite_quotas.py \
  tests/test_luckywheel_public_api.py tests/test_luckywheel_quota_migration.py \
  tests/test_luckywheel_quota_concurrency.py

# 前端组件逻辑、公开/管理员读取路径、名称式开奖定位
cd webapp-frontend
node --test tests/wheelInviteQuotaPanel.test.js
npm run build
```

PostgreSQL 并发测试需要显式设置 `PMS_QUOTA_TEST_DATABASE_URL`，并且只接受本地专用容器 `pms-luckywheel-quota-verify` 中的 `pms_test_quota_runtime` 数据库。测试会重建该数据库的 `public` schema，因此不能指向其他数据库；未设置变量时 PostgreSQL 参数项跳过，不能将跳过称为通过。
