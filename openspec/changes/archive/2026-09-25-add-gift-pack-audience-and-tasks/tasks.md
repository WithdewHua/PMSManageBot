## 1. 数据层

- [x] 1.1 在 `src/app/models/models.py` 为 `GiftPack` 新增 `audience`、`requirements`、`task_end_at`、`max_task_prompt_count`（server_default 0）、`notify_audience_on_start`（server_default 0）及 CheckConstraint；为 `GiftPackUserState` 新增 `audience_locked_at`、`task_prompt_count`（server_default 0）、`last_task_prompted_at`、`start_dm_sent_at`；验证：`python -c "import app.models.models"` 通过
- [x] 1.2 生成并审阅 Alembic 迁移（只加列与约束），本地 `alembic upgrade head` 后 `alembic downgrade -1` 再 upgrade；验证：新列存在，已有礼包行的 `max_task_prompt_count` 为 0

## 2. Schema

- [x] 2.1 在 `src/app/webapp/schemas/gift_pack.py` 实现 14 种叶子条件与 `AnyOf`，组装为受众联合与领取条件联合（`AnyOf.items` 只接受叶子）；校验项：days 在 1–365、只支持历史累计的类型拒绝其他时间范围、credits 至少有 min 或 max、any_of 至少 2 项、`user_list` 只能放在受众顶层；验证：spec「条件组合」「计数条件与时间范围」「领取资格」里的每个非法配置都返回 422
- [x] 2.2 创建与编辑请求：新增 `audience`、`requirements`、`task_end_at`、`max_task_prompt_count`（默认 2）、`notify_audience_on_start`，删除 `eligibility`；校验 `task_end_at` 在 (start_at, end_at] 内，开启开始通知时受众顶层必须有 include 名单；空列表规范化为 None；验证：spec「礼包定义」「名单型礼包的开始通知」的校验场景
- [x] 2.3 响应模型：`RequirementProgress`（Leaf | Group），`GiftPackItem` 新增 `requirements` 进度与 `task_closed`、删除 `ineligible_reasons`；开屏提醒响应新增 `task_packs`；管理端条目新增 `audience`、`requirements`、两份摘要、`audience_size`、`claim_rate`、`task_prompted_users`；验证：应用启动后 `/openapi.json` 能正常生成

## 3. 条件引擎（`src/app/databases/db.py`）

- [x] 3.1 实现 `_resolve_gift_pack_conditions(pack)`，读取时把旧的 `eligibility` 转为领取条件（design.md D11）；验证：三个旧字段各自转为等价的叶子，旧行的任务提醒上限为 0
- [x] 3.2 实现 8 个计数器：签名为 `(session, tg_id, since, until, **qualifiers)`，内部按表换算时间单位，口径见 design.md D3；验证：逐个指标测试时间范围边界、`paid_only`、`min_bet`、准确率（`decisions_total` 为 0 的情况）、按期去重与按场去重、已取消赛事的报名不计
- [x] 3.3 扩展 `_load_gift_pack_user_context`：加入持有的勋章与已领取的礼包，并按 `(metric, since, until, qualifiers)` 在单次请求内缓存计数结果；验证：两个 `start_at` 相同、都用「礼包开始后转盘」的礼包，只产生一次计数查询
- [x] 3.4 实现 `_evaluate_conditions(items, ctx, pack, ref)`，一次遍历返回 `(ok, progress)`，由服务端生成 label；验证：spec「满足其一」「组内都未满足」的进度与文案
- [x] 3.5 扩展 `_gift_pack_lifecycle` 以支持 `claim_only`，并实现 `ref = min(now, task_end_at or end_at)`；验证：边界测试（`now == task_end_at` 算进行中；`task_end_at == end_at` 时没有 `claim_only`；未开始礼包的 `pack` 范围计数为 0 且不查库）
- [x] 3.6 实现受众判定：顶层名单实时判定，其余项看是否已锁定，未锁定则实时判定（design.md D5）；验证：spec「受众锁定」的三个场景

## 4. 用户侧入口

- [x] 4.1 改写 `get_gift_packs_for_user`：受众外的礼包不返回；状态按 design.md D6 的顺序判定；附带进度、`task_closed`，以及未开始礼包的「开始后才计数」说明；验证：spec「礼包中心列表」「受众」的场景
- [x] 4.2 改写 `prompt_check_gift_packs`：写入受众锁定；按领取提醒与任务提醒分类，两类分别计数、分别按天节流；返回 `packs` 与 `task_packs`；保留无活跃礼包时的短路；验证：spec「开屏提醒」的全部场景，重点覆盖同一天先任务提醒后达标、任务提醒用完不影响领取提醒、上限为 0、仅可领取阶段不发任务提醒
- [x] 4.3 改写 `claim_gift_pack`：受众外按「礼包不存在」拒绝；在持锁的 session 内按冻结后的 `ref` 复核领取条件，不满足时返回当前进度；验证：spec「领取时条件已不满足」「受众外提交领取」
- [x] 4.4 在 create/update 中自动补 `bound` 条件（design.md D14）：变更 `expand-gift-pack-rewards` 已落地时读它的登记表，否则只看 `premium_days`；验证：含 Premium 天数、领取条件里没有 bound 的礼包，保存后自动追加 `{type: bound, service: any}`

## 5. 管理端

- [x] 5.1 `create_gift_pack` / `update_gift_pack` 写入新字段并把 `eligibility` 置空；在 db 层校验 `badge_id`、`pack_id` 存在，且 `pack_id` 不能是自身；验证：引用不存在的勋章或礼包时拒绝保存
- [x] 5.2 实现 `_validate_post_start_edit(old, new)`（design.md D10），违规时指出字段并附「可停用后新建」；验证：spec「开始后的编辑限制」的五个场景，以及 `task_end_at` 由空改为有值被拒绝
- [x] 5.3 删除礼包时，若被其他礼包的 `claimed_pack` 条件引用则拒绝，并列出引用方；验证：测试
- [x] 5.4 实现名单解析：db 方法与端点 `POST /api/gift-packs/admin/resolve-users`（design.md D13）；验证：spec「混合粘贴」，另测歧义匹配被列为无法解析
- [x] 5.5 扩展 `get_gift_pack_stats`：加入 `task_prompted_users`，include 名单型礼包再加名单人数与领取率；管理端列表返回条件摘要；验证：spec「名单型礼包的领取率」

## 6. 名单型礼包的开始私信

- [x] 6.1 在 `routers/gift_pack.py` 实现 `scan_gift_pack_start_dms`，db 方法负责挑选候选并「先写 `start_dm_sent_at` 再发送」；每条间隔 0.5s，每轮最多 200 条（design.md D9）；验证：每人只收到一条、已领取的用户被排除、中途加入名单的用户在下一轮收到、受众条件不满足的用户被排除
- [x] 6.2 在 `src/app/main.py` 注册该任务（每 5 分钟一次）；验证：启动日志出现注册信息

## 7. 前端

- [x] 7.1 `services/giftPackService.js` 新增 `resolveGiftPackUsers`；验证：`npm run lint` 通过
- [x] 7.2 新增 `GiftPackConditionEditor.vue`，受众与领取条件共用：添加条件、添加「满足其一」组，各类型的参数与时间范围选择（在「礼包开始后」旁提示任务类礼包推荐此项）；名单支持粘贴后解析，并展示无法解析的标识；验证：能配出 spec 中的每个示例
- [x] 7.3 `GiftPackAdminPanel.vue` 接入条件编辑器，新增任务截止、任务提醒上限（默认 2）、开始通知开关（仅受众含 include 名单时可用）；礼包开始后，不可改的字段只读、目标值只能调低；展示服务端生成的摘要、名单人数与领取率；验证：`npm run lint` 通过，开始后违规修改时显示后端的错误信息
- [x] 7.4 `GiftPackDialog.vue`：新增 `in_progress` 状态（显示为「未达成」），逐项显示进度条与「任选其一」组，`task_closed` 时说明任务已截止，未开始礼包说明「开始后才计数」；移除 `ineligible_reasons` 的使用；验证：spec「展示任务进度」「已过任务截止时间」「未开始礼包的计数说明」
- [x] 7.5 `GiftPackPromptDialog.vue` 与 `App.vue`：分为「可以领了」与「待完成」两块，按钮在有可领取项时显示「前往领取」，否则显示「查看礼包」；验证：spec「只有待完成的礼包」「首次提醒」

## 8. 测试与收尾

- [x] 8.1 新增 `tests/test_gift_pack_conditions.py`，覆盖 2.1、3.1–3.5；验证：`pytest tests/test_gift_pack_conditions.py` 通过
- [x] 8.2 新增 `tests/test_gift_pack_audience.py`，覆盖 3.6、4.1–4.3、5.2、6.1；验证：`pytest tests/` 全部通过
- [x] 8.3 运行 `ruff check src/ && ruff format --check src/` 与前端 `npm run lint`；验证：无新增告警
- [x] 8.4 在 Migration Plan 中补上找出回滚后会变开放的礼包的 SQL，并在测试库上执行一遍；验证：能正确列出使用了新条件的礼包
- [x] 8.5 运行 `openspec validate add-gift-pack-audience-and-tasks --strict`；验证：通过
