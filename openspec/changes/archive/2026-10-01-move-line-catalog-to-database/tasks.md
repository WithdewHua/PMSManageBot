# Tasks

## 1. 数据模型与目录存储

- [x] 1.1 在 lines 的 models 中新增 `line_catalog`（按 design D1，包括命名的唯一约束和检查约束），编写 alembic 迁移，并更新 model registry。验证：
  - 在一次性 PostgreSQL 上执行 upgrade → downgrade → upgrade；`check_metadata_pg.py` 没有差异。
  - 约束测试：非法类型、普通线路设为免费开放、重复名称、同类重复顺序值，都被数据库拒绝。
- [x] 1.2 让 `lines/catalog.py` 改为读写 `line_catalog`：顺序值分配、名称校验、标签规范化、免费标记校验，以及提交后失效加 TTL 的读取缓存。`lines.service` 目录函数的签名和提交后的副作用都不变。验证：
  - 目录函数的单元测试覆盖规格中的每个场景：跨类型重复、非法名称、标签的空白、空串、逗号和顺序、给不存在的线路设标签、免费线路校验、删除后其余线路的顺序。
  - 在一次性 PostgreSQL 上并发新增同类线路：没有重复的顺序值；冲突的一方重试后成功，或者返回现有的失败响应。
- [x] 1.3 用 `promote-line-domains` 冻结的夹具，回归后台线路管理、标签、免费高级线路、设置总览和用户线路列表接口（包括兼容路径），以及网关缓存。验证：
  - 除 design D2 列出的差异外，响应和 fakeredis 中的键和值与夹具一致。
  - 这些差异各有专门的测试断言。

## 2. 导入、导出与清理

- [x] 2.1 实现一次性导入：从 `LegacyEnvSource` 和 `core.kv` 读取，按 design D3 的规则写入目录；在同一事务里删除旧的 kv 行并写入完成标记。`main.py` 在启动服务之前执行导入，`manage.py` 不执行；旧键仍然存在时发出警告；删除 `Settings` 中的两个列表字段。验证：
  - 导入测试覆盖：正常导入、同一列表内的重复名称、两个列表中的重复名称、孤儿标签、孤儿免费标记、普通线路上的免费标记。
  - 重复启动时不再导入。
  - 导入之后修改 `.env`，不产生任何影响。
- [x] 2.2 新增导出脚本 `scripts/export_line_catalog.py`：默认只读，`--apply` 只恢复 kv 行。验证：测试证明导出的 `.env` 行和 kv 行被旧版代码读取后，得到的目录、标签和免费线路与导出前一致。
- [x] 2.3 按 design D4 处理 `save_config_to_env_file`，并更新 `docs/architecture.md` 的"配置分类"一节。验证：
  - `src` 中没有写 `.env` 的业务代码：要么不再出现 `save_config_to_env_file`，要么它只剩 `save_current_config` 这一个调用方，并由架构测试保证。
  - 文档写明 `.env` 只存放只读的部署配置。
   - **集成完成**：已同时合入特权码迁移并删除 `save_config_to_env_file`；`tests/architecture/test_no_business_env_writes.py` 守护旧 writer 与三个可变配置字段不再进入部署 Settings。

## 3. 集成验证

- [x] 3.1 生产形态本地彩排：在完整数据库副本和 `data/.env` 上启动新版本，逐项核对导入的目录与原来的两个列表、标签和免费标记，并把跳过清单交给维护者确认。然后在后台新增、删除一条线路，修改标签和免费线路，再重启服务。验证：导入结果和确认结论已记录；修改立即生效，重启后仍然保留。
- [x] 3.2 运行全量回归：`pytest tests/`、`ruff check`、`ruff format --check`、`lint-imports`、`pre-commit run --all-files`，然后运行 `openspec validate move-line-catalog-to-database --strict`。验证：全部通过；工作区干净。
