## Why

剩下的领域包括捐赠、加密货币捐赠、Vaultwarden，以及三个读模型。它们体量不大，放在最后统一提升，为移除门面做准备。调研还发现了下面这些问题，需要一并处理。

**三个业务领域有原子性和并发缺陷。**

- **捐赠确认**：确认时，改状态的 UPDATE 不检查 `status='pending'`，两次并发确认会重复入账。状态、捐赠额和积分又分三个事务写入，中途失败会留下"已批准但未入账"的记录。管理员登记和 bot 登记则是先读出捐赠额、再写回绝对值。
- **UPay 回调**：完成订单的 UPDATE 不带状态条件，重复回调会重复入账；入账失败时仍然返回成功，UPay 不会重试，这笔入账就丢了。
- **Vaultwarden 兑换**：先调用外部服务开号，再扣积分。扣分失败时，接口返回"兑换成功但更新积分失败"，账号已经开出去了。Vaultwarden 也没有 repository，SQL 直接写在路由里。

**三个读模型的查询分散，而且套用了其他领域的业务规则。**

- 预言、流量和 21 点的榜单查询不在 rankings 里。
- 转盘榜硬编码奖品名"邀请码 1 枚"，夺宝榜用魔数判断状态，邀请人数的统计规则与 invitation 重复。
- 系统统计用线路名的子串识别线路类型。
- 个人信息接口自行计算会员欠额，与 premium 的规则重复。
- `profile/schemas.py` 的 30 个类中，只有 1 个属于 profile，其余被 lines、custom_lines 和 credits 使用。

**`make-credit-changes-atomic` 留下了 14 条基线条目。** 这个变更已经完成，但还有 14 条没清：credits 的路由从 profile 导入转账模型，积分缓存重写任务直接查询 identity 的模型。

## What Changes

- **按提升模板处理三个业务领域**：`donation`、`crypto_donation`、`vaultwarden`。
  - 捐赠的确认、管理员登记和 bot 登记，都改为单事务：带状态条件的更新、捐赠额增量，以及积分的 `add_tx`。
  - UPay 回调在一个事务里完成：带状态条件完成订单，再入账。重复回调直接返回成功；入账失败时整体回滚，返回失败让 UPay 重试。
  - Vaultwarden 改为先扣积分、再开号，开号失败时退还积分；并新建 repository。
  - 这些只改变失败和并发情况下的结果，正常路径不变。
  - 勋章事件的发布位置从路由移进 service，发布条件不变。
- **整理三个读模型**：`rankings`、`reports`、`profile`。
  - 每个读模型的查询都收拢到自己的 repository 里，只读不写，并新增架构检查守住这一点。
  - 读模型只在"不涉及业务规则的聚合"时直接读其他领域的表；用到其他领域业务规则的地方，改为调用该领域的 service。21 点排行已经按这种方式处理，本变更把转盘、夺宝、邀请的排行，以及系统统计中的线路分类都改成这样。
  - bot 排行命令和排行接口本来就共用 SQL。它们的差异只在数量上限、是否排除管理员和过滤条件，改为 service 的显式参数，两边的输出都不变。
  - `profile/schemas.py` 中属于其他领域的模型，搬回各自的领域。
- **清理 `make-credit-changes-atomic` 留下的 14 条基线条目**：转账模型搬进 `credits/schemas.py`，积分缓存重写任务的查询搬进 credits 的 repository。
- **对外行为不变**：接口路径、状态码、响应格式和文案，以及 bot 命令的输出，都保持原样。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。这是纯重构，现有的 `rankings` 规格不变，`.openspec.yaml` 设置 `skip_specs: true`。上述原子性修复只影响失败和并发情况下的结果。排行接口在查询出错时返回 200 加空列表、与 `rankings` 规格冲突的问题，不在本变更修复。

## Impact

- **代码**：
  - 上述六个领域。
  - `credits` 的转账模型和缓存重写任务。
  - 为读模型提供排行和统计函数的领域：luckywheel、treasure、invitation、lines、custom_lines、media_access。
  - `tests/architecture`：读模型只读的检查。
- **依赖**：`promote-reward-domains`（捐赠触发的勋章颁发已改为事件），以及此前的各个 promote 变更。`fix-webapp-auth-bypass` 已加固 UPay 回调的签名和金额校验。
