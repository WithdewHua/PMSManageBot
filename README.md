## PMSManageBot

### 项目说明

个人自用的 Plex/Emby 用户管理 Telegram 机器人（MiniAPP），一切按照自身喜好设计；

注意：代码很烂很乱，能跑，没动力重构

### 功能特点

- 支持 Plex 和 Emby 的用户管理：注册、绑定、线路绑定/切换等；
- 支持多种游戏活动和奖励机制
- 丰富的排行榜
- 无强制 TG 绑定要求
- 无签到保号功能，且不会做

### 部署方式

#### docker compose(推荐)

```bash
# 下载 docker-compose.yaml
mkdir -p /opt/PMSManageBot/data
cd /opt/PMSManageBot
wget https://raw.githubusercontent.com/withdewhua/PMSManageBot/main/docker-compose.yaml

# 下载示例配置文件
wget https://raw.githubusercontent.com/withdewhua/PMSManageBot/main/.env.example -O data/.env
```

按照自身需求修改 `data/.env` 及 `docker-compose.yaml`，然后执行：

```bash
docker compose up -d
```
