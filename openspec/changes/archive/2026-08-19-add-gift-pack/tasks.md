## 1. 数据层

- [x] 1.1 在 `src/app/models/models.py` 新增 `GiftPack` 模型（title / description / rewards / eligibility / total_quantity / claimed_count / start_at / end_at / max_prompt_count / is_enabled / expiry_notified / created_by / created_at / updated_at），含 `end_at > start_at`、`claimed_count >= 0`、`max_prompt_count > 0` 等 CheckConstraint
- [x] 1.2 在 `src/app/models/models.py` 新增 `GiftPackUserState` 模型（pack_id / tg_id / claimed_at / reward_snapshot / last_prompted_at / prompt_count），含 `UniqueConstraint(pack_id, tg_id)` 与 `Index(tg_id, claimed_at)`
- [x] 1.3 生成并审阅 Alembic 迁移（`alembic revision --autogenerate -m "add gift pack tables"`），确认 CheckConstraint 与索引均已生成
- [x] 1.4 本地 `alembic upgrade head` 验证建表成功，`alembic downgrade` 验证可回滚

## 2. 校验与前置调查

- [x] 2.1 验证 `update_premium_status()`（`src/app/premium.py:131`）的事务边界：确认其内部 `get_session()` 是否会在外层事务中独立提交，据此确定 Premium 发放放在领取事务内还是提交后（见 design.md — Risks 第一条）
- [x] 2.2 在 `src/app/webapp/schemas/gift_pack.py` 定义奖励项与资格的 Pydantic 模型，含 validator：奖励项非空、同类型不重复、数值为正、资格字段取值合法
- [x] 2.3 实现 `end_at > start_at`、`total_quantity > 0`（若提供）的请求级校验

## 3. 核心业务逻辑（`src/app/databases/db.py`）

- [x] 3.1 实现资格判定函数：输入 tg_id 与 eligibility，实时查询积分、Premium 状态、绑定状态，返回是否满足及未满足的具体原因（含「还差多少积分」）
- [x] 3.2 实现奖励发放分发器：按 `type` 分发到积分发放与 Premium 天数发放，返回 `reward_snapshot`；Premium 分支对所有已绑定服务逐个调用 `update_premium_status()`，永久会员（返回 None）记为 skipped
- [x] 3.3 实现 `create_gift_pack()`：含 Premium 奖励时自动补 `require_binding: "any"` 资格（管理员未配置更严格绑定要求时）
- [x] 3.4 实现 `get_gift_packs_for_user()`：返回礼包列表及每个礼包对该用户的状态（可领取／未满足条件+原因／已领取+snapshot／已领完／已结束／未开始）与余量
- [x] 3.5 实现 `claim_gift_pack()`：单事务内 `with_for_update()` 锁 pack 行 → 校验启用/窗口/余量/资格/未领取 → 发放 → `claimed_count += 1` → upsert user_state，任一步失败整体回滚（参照 `db.join_treasure_issue()`，`db.py:1189`）
- [x] 3.6 实现 `prompt_check_gift_packs()`：先查是否存在进行中且启用的礼包，为空立即返回空列表且不写库；否则按 D5 的候选集条件筛选，对候选逐个 `prompt_count += 1` 与 `last_prompted_at = now`（「今天」按 `settings.TZ` 判定）
- [x] 3.7 实现管理端查询：礼包列表、单个礼包的领取统计（领取人数、剩余份数、各类奖励发放总量）、领取记录分页
- [x] 3.8 实现 `update_gift_pack()` / `set_gift_pack_enabled()` / `delete_gift_pack()`，其中删除在存在领取记录时拒绝

## 4. 通知

- [x] 4.1 实现礼包上线通知：创建接口内经 `BackgroundTasks` 调用 `notify_admins_by_url()`，内容含标题、奖励、时间窗、限量
- [x] 4.2 实现限量领完通知：领取事务提交后判断 `claimed_count == total_quantity` 时触发
- [x] 4.3 实现发放失败异常通知：领取路径异常分支立即通知，含礼包标识、用户标识、失败原因
- [x] 4.4 实现过期汇总扫描任务：周期扫描 `end_at < now ∧ expiry_notified = 0` 的礼包，发送领取汇总后置 `expiry_notified = 1`；注册到 `Scheduler`，周期 10 分钟
- [x] 4.5 确认无任何逐笔领取通知

## 5. 后端路由（`src/app/webapp/routers/gift_pack.py`）

- [x] 5.1 创建路由文件与 `APIRouter(prefix="/api/gift-packs")`，在 `src/app/webapp/__init__.py` 注册
- [x] 5.2 `POST /prompt-check` — 返回待提醒礼包列表并记账
- [x] 5.3 `GET /` — 礼包中心列表（含每个礼包对当前用户的状态与余量）
- [x] 5.4 `POST /{pack_id}/claim` — 领取，返回逐项发放结果（含永久会员跳过的说明）
- [x] 5.5 管理端 `GET/POST/PUT /admin/...` — 列表、创建、编辑、启用停用、删除、统计、领取记录，全部经 `check_admin_permission()` 保护
- [x] 5.6 所有路由加 `@require_telegram_auth`，错误经 `HTTPException` 抛出并使用中文 detail

## 6. 前端服务层

- [x] 6.1 新增 `webapp-frontend/src/services/giftPackService.js`，封装用户端与管理端全部接口，统一走 `apiClient`

## 7. 前端用户侧

- [x] 7.1 新增 `GiftPackDialog.vue` 礼包中心：进行中与已领取默认展开，已结束未领取折叠收起；展示奖励摘要、余量 `剩余 X/Y`、不可领取原因；时间按浏览器时区展示（参照 `TreasureDialog.vue`）
- [x] 7.2 在礼包中心实现领取交互与结果展示，逐项显示发放结果（含 Premium 各服务的新到期时间与永久会员跳过说明）
- [x] 7.3 新增 `GiftPackPromptDialog.vue` 汇总提醒弹窗：列出全部待领礼包及奖励摘要与余量，超过 3 个截断为「…等 N 个礼包」，提供「稍后再说」与「前往领取」
- [x] 7.4 在 `App.vue` 挂载提醒弹窗并在启动后调用 `POST /prompt-check`（独立请求，不与 `getUserInfo` / `systemStatus` 合并），返回非空才弹窗
- [x] 7.5 在 `BottomMenu.vue` 的 "+" 操作菜单新增「我的礼包」入口，打开礼包中心
- [x] 7.6 打通「前往领取」→ 关闭提醒弹窗 → 打开礼包中心的跳转链路

## 8. 前端管理端

- [x] 8.1 新增 `GiftPackAdminPanel.vue`，在 `Management.vue` 的「活动管理」tab 新增礼包入口卡 + 全屏管理弹窗引入（参照 `WheelAdminPanel.vue` 的组件划分与视觉语言）
- [x] 8.2 实现礼包列表与创建/编辑表单：标题、描述、时间窗、限量、提醒次数上限、启用开关
- [x] 8.3 实现动态奖励项配置（参照 `WheelAdminPanel.vue:958-1083`）：增删奖励项，按类型切换参数字段，已选类型从下拉中剔除
- [x] 8.4 实现资格配置：最低积分、要求 Premium、要求绑定（不限/Plex/Emby）；含 Premium 奖励时提示绑定要求已自动生效
- [x] 8.5 时间录入按 `settings.TZ` 解析并在输入框旁标注时区名
- [x] 8.6 实现停用/启用操作；对已有领取记录的礼包隐藏或禁用删除按钮并说明只能停用
- [x] 8.7 实现领取统计与领取记录查看

## 9. 验证

- [x] 9.1 并发领取最后一份：多请求并发，验证恰好一人成功且 `claimed_count` 不超过 `total_quantity`
- [x] 9.2 同用户并发重复领取：验证至多一次成功，奖励与单次领取一致
- [x] 9.3 Premium 发放矩阵：仅绑 Plex／仅绑 Emby／双绑／某服务永久会员／全部永久会员，逐一验证发放结果与 `reward_snapshot`
- [x] 9.4 未绑定账号用户对含 Premium 礼包：验证列表显示未满足条件、不进入提醒、领取被拒
- [x] 9.5 提醒节流：当天重复打开不再弹、跨天再弹、达到 `max_prompt_count` 后不再弹、多礼包只弹一个汇总弹窗
- [x] 9.6 资格动态性：积分从不足变为满足后，礼包重新可领并重新进入提醒候选
- [x] 9.7 空态短路：系统中无进行中礼包时，`prompt-check` 返回空且不写入任何 `gift_pack_user_state` 行
- [x] 9.8 窗口边界：未开始／已结束／已停用状态下领取均被拒绝且不发放奖励
- [x] 9.9 通知验证：上线、领完、过期汇总、发放失败各触发一次；确认批量领取过程中无逐笔通知
- [x] 9.10 删除限制：有领取记录的礼包删除被拒，无记录的可删除
- [x] 9.11 运行 `ruff check src/` 与 `ruff format src/`；在 `webapp-frontend/` 运行 `npm run lint` 与 `npm run build`
