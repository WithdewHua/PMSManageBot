# 实施验证记录

## 环境与安全边界

- 所有数据库写入均在临时 SQLite 或本地一次性容器 `pms-luckywheel-quota-verify` 中进行。
- PostgreSQL 使用专用 `pms_test_luckywheel`（迁移/初始化/HTTP 串联）与 `pms_test_quota_runtime`（独立连接并发及隔离 schema 换绑）数据库；凭据为本地测试值。
- 演练隔离 `DATA_DIR`，通知及相关缓存回调替换为 no-op。没有执行生产迁移、生产回填、生产抽奖或生产配置修改。
- 未自动归档、提交 Git 或发布；验证结束后已停止本次创建的一次性 PostgreSQL 容器。

## 规格 → 证据

| 验收点 | 可重复验证入口 |
| --- | --- |
| 默认 30/5、非负整数/0、上限调整、权威配置而非缓存、单批快照 | `tests/test_luckywheel_invite_quotas.py` |
| 已初始化后配置缺失、管理员读取/启动不恢复默认值 | 同文件 `test_lost_restrictive_config_is_not_repaired_by_reads_or_startup`、`test_quota_defaults_are_seeded_only_by_owner_before_initialization` |
| 北京时间周界、跨年、秒级历史/毫秒周键、跨周批次 | `tests/test_luckywheel_invite_quotas.py` |
| 自定义邀请码识别、无有效后备池拒绝、保留加权保护、允许负积分后备奖项 | `tests/test_luckywheel_invite_quotas.py` |
| 24/4 与 40/8 历史、NULL 来源、报告变动、回滚、重复 apply、旧写入者造成的账本不一致 | `tests/test_luckywheel_invite_quotas.py` 及下述真实 CLI 演练 |
| 真实独立连接争抢全服/个人最后一枚、单抽/十连共享、新周期并发创建 | `tests/test_luckywheel_quota_concurrency.py`，SQLite 外键关/开和 PostgreSQL 三种参数均启用 |
| 免费/付费、特权开关、单笔/整批回滚、计数与审计相等 | `tests/test_luckywheel_invite_quotas.py`、`tests/test_luckywheel_spins.py`、`tests/test_blackjack_retention.py` |
| 换绑迁移、3+2=5、全服不变、不串联、后续失败回滚 | `tests/test_tg_rebind_matrix.py`、`tests/test_tg_rebind_rewards.py`、并发测试中的换绑用例；三后端矩阵已启用 |
| SQLite 自增修复不更改旧 ID，结构迁移不回填业务数据 | `tests/test_luckywheel_quota_migration.py`（外键关/开）及下述 PostgreSQL pre-head 往返 |
| 公开配置、单抽/十连全部嵌套奖项脱敏、错误不泄露、管理员鉴权/权重保存/配额读取修改 | `tests/test_luckywheel_public_api.py`（真实 FastAPI HTTP 序列化），以及串联演练中的真实业务服务 + HMAC 请求 |
| 管理员正确加载/保存、错误与陈旧数据不假成功、普通轮盘名称式结果定位/免费/十连、预览禁用 | `webapp-frontend/tests/wheelInviteQuotaPanel.test.js`，10 项 Node 测试 |
| 分层、模型标记、换绑覆盖、架构基线 | `tests/architecture` 与 `lint-imports --no-cache`；未修改 `tests/architecture/baseline.json` |

## 迁移与 CLI 串联

1. 在含 24 条旧抽奖记录、6 个用户的 pre-head `b5c6d7e8f9a0` 上执行 `upgrade → downgrade → upgrade`，均通过；旧记录/用户保留，迁移没有业务回填。
2. CLI dry-run 识别全服 24、每人 4，其中 12 条来源保持 NULL；数据库无写入，报告文件权限 0600。
3. 经已知测试数据核对后 apply：`already_initialized=false, issued=24`。
4. 免费、付费、十连继续结算至 `历史24 + 新增6 = 全服30`，6 人各 5；超限候选重选，未重复扣费。真实并发另由三后端独立连接测试覆盖。
5. 重复同一报告 apply：`already_initialized=true, issued=30`，不覆盖新增计数。
6. 真实签名 HTTP 验证公开/管理员隔离；完整 TG 换绑把源用户 5 枚历史带到目标用户，全服仍为 30，随后目标用户仍重选。
7. 业务时钟跨周演练使用独立认证时钟：真实 HMAC 请求仍有效，目标用户在新周获得 1 枚邀请码；管理员统计新周为 1，旧周仍为 30，公开开奖对象仅含奖项名称。该完整串联在隔离 PostgreSQL 上通过。

## 独立审查

只读审查发现一项配置丢失时的默认值恢复风险，已修正：管理员读路径仅能在完全没有账本时创建初始默认值，启动统一播种排除该配置；已有账本后丢失配置保持关闭。加入上述针对性回归。未以审查替代测试。

## 最终验收

- 修正后全量测试：**1106 passed, 4 skipped, 16 warnings**，70.35 秒；显式启用了转盘并发和完整换绑的 PostgreSQL 参数。
- Ruff：`src/` 全量及新增脚本/测试通过。
- 导入契约：**11 kept, 0 broken**。
- 额外独立执行 `tests/architecture`：**96 passed**，架构基线文件无改动。
- 独立 Pyright（真实 `.venv`）：`src/app/domains/luckywheel/`、`src/app/business_config.py`、初始化脚本均为 **0 errors, 0 warnings**。
- OpenSpec 严格校验通过，Git diff 空白检查通过。
- AFT 内置诊断对仓储子模块的属性解析与独立 Pyright 有差异；未将其显示为零。上述命令行类型检查和实际运行测试是本次验收依据。

前端已完成：10 项逻辑测试、全量 `npm run lint -- --no-fix`、`npm run build`。保留构建正常更新的 `public/service-worker.js` 和 `public/version.json`。构建仍有包体积及依赖弃用类警告，不把这些警告表述为零。

当前已识别的全量测试跳过项是与本变更无关、需要单独显式数据库变量的 4 项：`BADGES_TEST_POSTGRES_URL` 1 项、`POSTGRES_TEST_URL` 1 项、`REMAINING_TEST_POSTGRES_URL` 2 项。转盘配额和换绑的 PostgreSQL 参数项没有跳过。

没有进行真实 Telegram 客户端的人工视觉验收，也没有等待真实运营 2～4 周；当前证据为组件逻辑测试、生产构建、真实 HTTP 和隔离数据库演练。生产上线仍须按 [维护窗口手册](../../../docs/luckywheel-quota-rollout.md) 人工核对真实历史后执行。
