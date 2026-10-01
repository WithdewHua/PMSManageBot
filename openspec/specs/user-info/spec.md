# user-info Specification

## Purpose
约定 Telegram bot `/info` 命令在用户统计数据或媒体账号资料不完整时的稳定回复、默认值和错误隔离行为。

## Requirements

### Requirement: 缺少统计数据时的 /info

已绑定媒体账号、但没有统计数据的用户使用 `/info` 时，bot SHALL 正常回复，积分和捐赠额显示为 0，与 WebApp 用户信息接口的默认值一致。bot SHALL NOT 为此补建统计数据。

#### Scenario: 没有统计数据

- **WHEN** 一个只有 Emby 账号、没有统计数据的用户发送 `/info`
- **THEN** bot 回复账号信息，积分显示为 0.00
