# PMS Manage Bot

这是一个用于管理 Plex/Emby 媒体服务器的 Telegram 机器人，支持用户管理、积分系统、邀请码等功能，并集成了 Telegram WebApp。

## 特性

- 用户注册和绑定（Plex/Emby）
- 积分和捐赠系统
- 媒体库权限管理
- 观看时长统计
- 排行榜
- 邀请码系统
- Overseerr 集成
- Telegram WebApp 支持

## 安装与配置

### 依赖项

- Python 3.11+
- Redis
- Node.js 16+ (用于 WebApp 前端)

### 安装步骤

1. 克隆仓库
2. 安装 Python 依赖:
   ```bash
   pip install -r requirements.txt
   ```
3. 安装前端依赖:
   ```bash
   cd webapp
   npm install
   ```
4. 构建前端:
   ```bash
   npm run build
   ```
5. 复制配置模板并编辑:
   ```bash
   cp src/app/config.tpl.py src/app/config.py
   # 编辑 config.py 文件，填写必要的配置
   ```
6. 启动服务:
   ```bash
   python src/run.py
   ```

## WebApp 特性

WebApp 提供了两个主要功能标签页:

1. **个人信息**: 显示用户的积分、捐赠情况、媒体账户信息和可用邀请码
2. **排行榜**: 显示积分榜、捐赠榜和观看时长榜

## 机器人命令

- `/start` - 查看帮助信息
- `/webapp` - 打开 WebApp
- `/info` - 查看个人信息
- `/exchange` - 生成邀请码
- `/redeem_plex` - 兑换 Plex 邀请码
- `/bind_plex` - 绑定 Plex 账户
- `/unlock_nsfw_plex` - 解锁 Plex NSFW 内容
- `/lock_nsfw_plex` - 锁定 Plex NSFW 内容
- `/redeem_emby` - 兑换 Emby 邀请码
- `/bind_emby` - 绑定 Emby 账户
- `/unlock_nsfw_emby` - 解锁 Emby NSFW 内容
- `/lock_nsfw_emby` - 锁定 Emby NSFW 内容
- `/bind_emby_line` - 绑定 Emby 线路
- `/unbind_emby_line` - 解绑 Emby 线路
- `/create_overseerr` - 创建 Overseerr 账户

## 贡献

欢迎提供问题报告和功能建议。
