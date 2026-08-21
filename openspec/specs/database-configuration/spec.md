## Purpose

约定数据库连接的配置契约——哪些数据库类型受支持、各配置项之间的优先级，以及不受支持的连接方式的边界。核心立场是对外声称的支持范围必须与实际验证过的范围一致。

## Requirements

### Requirement: 受支持的数据库类型

系统 SHALL 支持 SQLite 与 PostgreSQL 两种数据库类型。

系统 SHALL NOT 声称支持任何未经验证的数据库类型。文档与配置样例中标示的支持范围 SHALL 与实际验证过的范围一致。

未被识别的数据库类型 SHALL 按既有行为回退到 SQLite。

#### Scenario: 使用 SQLite

- **WHEN** 数据库类型配置为 `sqlite` 或留空
- **THEN** 系统连接数据目录下的 SQLite 文件

#### Scenario: 使用 PostgreSQL

- **WHEN** 数据库类型配置为 `postgresql`，且主机、端口、用户、密码、库名已配置
- **THEN** 系统按这些配置连接 PostgreSQL

#### Scenario: 文档标示的支持范围

- **WHEN** 使用者查阅项目文档或配置样例中的数据库说明
- **THEN** 其中列出的数据库类型仅为 SQLite 与 PostgreSQL

### Requirement: 完整连接 URL 的优先级与边界

系统 SHALL 支持通过完整连接 URL 直接指定数据库，该配置 SHALL 优先于数据库类型及其相关的分项配置。

通过完整连接 URL 连接受支持范围之外的数据库 SHALL 被允许但 SHALL NOT 被视为受支持——所需的数据库驱动由使用者自行安装，其可用性与正确性不在保证范围内。

#### Scenario: 完整 URL 覆盖分项配置

- **WHEN** 完整连接 URL 与 PostgreSQL 分项配置同时存在且指向不同目标
- **THEN** 系统连接完整连接 URL 所指的目标

#### Scenario: 借完整 URL 连接不受支持的数据库

- **WHEN** 使用者设置指向受支持范围之外数据库的完整连接 URL，并自行安装了相应驱动
- **THEN** 系统尝试按该 URL 连接；该用法不受支持，其结果不在保证范围内

### Requirement: 依赖范围与支持声明一致

项目 SHALL NOT 为不受支持的数据库预置驱动依赖，容器镜像 SHALL NOT 默认安装此类驱动。

可选依赖组 SHALL 仅覆盖受支持的数据库类型。

#### Scenario: 容器镜像的依赖

- **WHEN** 构建容器镜像
- **THEN** 镜像仅安装受支持数据库所需的驱动，不含已移除数据库类型的驱动

#### Scenario: 可选依赖组

- **WHEN** 使用者查看项目的可选依赖组
- **THEN** 仅存在与受支持数据库类型对应的组
