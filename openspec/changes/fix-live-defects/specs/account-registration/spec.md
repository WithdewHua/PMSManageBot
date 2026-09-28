# Spec Delta

## Purpose

约定凭邀请码注册媒体账号、绑定媒体账号，以及邀请码接口对未绑定用户的行为，保证 Plex 人数上限有效、邀请关系能被正确记录。

## ADDED Requirements

### Requirement: Plex 人数上限

已绑定 plex_id 的 Plex 用户数达到或超过上限时，Plex 注册 SHALL 被拒绝：不消耗邀请码，不发送邀请，按现有格式返回"Plex 用户数已达上限"。特权码 SHALL 同样受这个限制。

#### Scenario: 已经超过上限

- **WHEN** 已有 101 个 Plex 用户，上限为 100，用户提交 Plex 注册
- **THEN** 注册被拒绝，邀请码仍为未使用，没有向 Plex 发出邀请

### Requirement: 不绑定 TG 的 Plex 注册同样记录账号

凭码注册 Plex 时，无论用户是否选择绑定 TG，也无论绑定是否因该 TG 已绑定其他 Plex 账号而降级，系统 SHALL 为这个 Plex 账号建立本地记录，并在用户接受邀请后回填它的 plex_id 和对应邀请记录的 plex_id。这与 Emby 注册的行为一致。

未绑定 TG 的 Plex 账号 SHALL 与未绑定的 Emby 账号一样，按天累积观看积分；它的邀请人 SHALL 从回填后的下一次结算起获得奖励。

#### Scenario: 不绑定 TG 注册

- **WHEN** 用户凭码注册 Plex 且不绑定 TG，随后接受了邀请
- **THEN** 本地有这个账号的未绑定记录，plex_id 和邀请记录都被回填；下一次结算时邀请人获得奖励

#### Scenario: 绑定因已有 Plex 账号而降级

- **WHEN** 用户勾选绑定，但他的 TG 已经绑定了另一个 Plex 账号
- **THEN** 新账号按不绑定处理，同样建立未绑定记录并回填

### Requirement: 绑定已注册但未绑定的 Plex 账号

用户通过 `/bind/plex` 绑定 Plex 账号时，如果本地已有该邮箱的未绑定记录（包括还没有 plex_id 的记录），系统 SHALL 绑定这条记录，SHALL 回填 plex_id 和邀请记录，并按现有规则转入这条记录上累积的积分。

并发绑定导致的拒绝 SHALL 提示"该账户已被绑定"，SHALL NOT 提示"未知错误"。

#### Scenario: 绑定没有 plex_id 的记录

- **WHEN** 一个不绑定 TG 注册的用户，之后用 `/bind/plex` 绑定这个账号
- **THEN** 绑定成功，plex_id 和邀请记录被回填，累积的积分转入他的 TG 账户

#### Scenario: 并发绑定同一个账号

- **WHEN** 两个请求同时绑定同一个 Plex 账号
- **THEN** 一个成功，另一个收到"该账户已被绑定"

### Requirement: 未绑定用户调用邀请码接口

没有绑定任何媒体账号的用户查询邀请码积分信息或生成邀请码时，系统 SHALL 按现有的 200 契约返回失败结果，提示"用户未绑定 Plex/Emby 账户"：积分信息接口返回不可生成、当前积分为 0；生成接口返回失败，不生成邀请码，不扣积分。

#### Scenario: 未绑定用户打开生成邀请码

- **WHEN** 未绑定媒体账号的用户打开"生成邀请码"
- **THEN** 前端显示"用户未绑定 Plex/Emby 账户"，而不是"获取积分信息失败"
