# media-account-sync Specification

## Purpose
约定每日 Plex 和 Emby 账号信息同步的容错：个别账号的异常不能让整次同步中止，否则改名、plex_id 回填、邀请记录回填和头像刷新都会被跳过。

## Requirements

### Requirement: 同步不因单个账号中止

同步 SHALL 逐个账号、逐个阶段处理，以下情况 SHALL 只跳过当前账号，并在应用日志中记录原因：

- 媒体服务器上的好友在本地没有对应记录。
- 更新某个账号时违反唯一约束。
- 处理某个账号时出现其他异常。

同步 SHALL NOT 为缺少记录的好友自动建立本地记录。

#### Scenario: 服务器上有本地没有的好友

- **WHEN** Plex 好友列表中，第二个好友在本地没有记录，第三个好友改了用户名
- **THEN** 第三个好友的用户名被更新；plex_id 回填、邀请记录回填和头像刷新三个阶段都执行；日志中记录第二个好友被跳过

#### Scenario: 待回填的账号

- **WHEN** 一个已绑定的 Plex 账号在注册后超过 1 小时才接受邀请
- **THEN** 下一次每日同步为它回填 plex_id，并回填对应的邀请记录

### Requirement: 按邮箱解析 Plex 账号时不区分大小写

按邮箱查找 Plex 用户 ID 时，系统 SHALL 忽略邮箱的大小写。

#### Scenario: 注册时输入的邮箱大小写不同

- **WHEN** 用户注册时填写 `Alice@Example.com`，Plex 返回的邮箱是 `alice@example.com`
- **THEN** 系统能解析出这个用户的 plex_id
