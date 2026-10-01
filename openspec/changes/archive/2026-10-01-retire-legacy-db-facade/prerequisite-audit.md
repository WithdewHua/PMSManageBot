# 前置核对盘点报告 (Task 1.1 Prerequisite Audit)

- **目标变更**: `retire-legacy-db-facade`
- **盘点结论**: **PASSED**
- **执行规则**: proposal / design 决策 D1、AGENTS.md、OpenSpec 任务 1.1

## 1. 核心核对结论汇总

| 检查项 | 检查内容 | 期望条件 | 当前结果 | 判定 |
|---|---|---|---|---|
| 1. 基线非 line_budgets 为空 | `tests/architecture/baseline.json` | 0 条遗留违规 | 0 项违规 (79 跨域调用/导入 + 7 份非零合约计数) | ✅ 通过 |
| 2. 合约仅含门面组合边 | `pyproject.toml` [tool.importlinter] | 仅 `app.databases.db -> ...` | 0 项非门面遗留边 (覆盖 6 个合约) | ✅ 通过 |
| 3. src 源码门面导入清洁 | AST 与 Grimp 全仓扫描 `src/` | 仅 `app.databases` 自身导入 | 仅 `src/app/databases/__init__.py` 导入 `app.databases.db` | ✅ 通过 |

## 3. Check 1 详细数据：baseline.json

- `cross_domain_calls`: **0** 条
- `contract_ignore_counts`: 非零合约数 **2**
- `config_access`: 0
- `line_budgets`: 0 (豁免保留类别)
- `model_registry`: 0
- `mixin_duplicates`: 0
- `numbered_modules`: 0

### cross_domain_calls 归属分布

| 归属变更 | 源领域 | 目标领域 | 类型 | 数量 | 源码举例 |
|---|---|---|---|---|---|

## 4. Check 2 详细数据：import-linter ignore_imports

- 门面组合边 (合法过渡放行): **4**
  - `[Six-tier domain dependencies] app.databases.db -> app.domains.invitation.repository`
  - `[Six-tier domain dependencies] app.databases.db -> app.domains.watch_rewards.repository`
  - `[Acyclic domain siblings] app.databases.db -> app.domains.invitation.repository`
  - `[Acyclic domain siblings] app.databases.db -> app.domains.watch_rewards.repository`

- 非门面遗留边 (违背清空前提): **0**

| 合约 | 忽略导入边 | 归属变更 / 注释 | 源码中是否真实存在 | 源码证据位置 |
|---|---|---|---|---|

## 5. Check 3 详细数据：src/ app.databases 导入

- AST 扫描 `src/` 总命中: 1 处
- 外部模块导入 `app.databases`: **0** 处
- 内部自身导入:
  - `src/app/databases/__init__.py:1`: `from app.databases.db import db`

- Grimp 下游模块 (`find_downstream_modules('app.databases')`): `[]`
- Grimp 下游模块 (`find_downstream_modules('app.databases.db')`): `['app.databases']`

**结论**: `src/` 中除 `app/databases` 自身外没有任何模块导入门面，Check 3 完全通过。

## 6. Check 4 兼容层与脚本调用现状

- `DatabaseORM` 当前组合的 mixin/repo: `IdentityRepository, PremiumCompat, InvitationRepository, MediaAccessCompat, LinesCompat, TrafficCompat, WatchRewardsRepository`
- `IdentityRepository` 兼容方法数: 15 个
- `src/` 中对 `db.*` / `DatabaseORM.*` 的调用点: **0** 处
- `tests/` 中对 `db.*` / `orm.*` 的直接方法调用点: **4** 处 (注：测试夹具 `orm` 作为 fixture 注入 239 处，但均已改由内部 `get_session` 或直接调用 service/repo)
- `scripts/` 中直接调用 `db.*` 的方法点: **0** 处：

- `scripts/` 中导入 `app.databases` 的脚本清单 (1 处):
  - `scripts/refactor/snapshot.py:309`: `from app.databases import db`

- `tests/` 中导入 `app.databases` 的测试文件清单 (6 处):
  - `tests/conftest.py:48`: `from app.databases.db import DatabaseORM`
  - `tests/test_badge_awards_promotion.py:398`: `from app.databases.db import DatabaseORM`
  - `tests/test_accounts_sync_resilience.py:68`: `from app.databases import db`
  - `tests/refactor/test_blackjack_cross_domain.py:129`: `from app.databases.db import DatabaseORM`
  - `tests/refactor/test_model_registry.py:24`: `from app.databases import db`
  - `tests/refactor/test_activity_rejections.py:34`: `from app.databases.db import DatabaseORM`

## 7. 下一步行动建议

1. **保持任务 1.1 未勾选** (`- [ ] 1.1`)，严格遵守 OpenSpec 任务前置条件与提案 D1 停工规定。
2. **停止当前变更的重构代码编写**（绝对不要删除 `app/databases/`、不要修改 `baseline.json` 放行项、不要修改 `pyproject.toml` 合约）。
3. **退回前序变更补齐前置清零**：
   - **`promote-line-domains`**: 清理 75 条 cross_domain_calls，重构 `premium.service -> app.core.db`、`traffic.jobs` 直连数据库及跨域模型导入、`traffic.repository -> lines.catalog` 等。
   - **`promote-gift-pack-domain`**: 清理 4 条 cross_domain_calls 及 `gift_pack.rules -> gift_pack.models` 忽略项。
   - **`promote-blackjack-domain`**: 解耦 `blackjack.router -> blackjack.jobs` 依赖。
   - **手动脚本迁移**: 改写 `scripts/migrate_redis_to_database.py` 与 `scripts/migrate_line_traffic_stats.py`，改用新领域 service/repository。
4. 待上述依赖项全部完成基线清零后，重新运行本盘点脚本，全绿后再行勾选 task 1.1 并推进门面删除。