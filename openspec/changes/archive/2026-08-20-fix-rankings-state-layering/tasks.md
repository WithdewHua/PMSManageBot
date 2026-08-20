## 1. 统一状态结构

- [x] 1.1 在 `Rankings.vue` 的 `data()` 中定义状态键的单一来源：一个包含全部 11 个键的列表（`credits`、`donation`、`badge`、`invitation`、`watched-plex`、`watched-emby`、`traffic-plex`、`traffic-emby`、`game-wheel`、`game-treasure`、`game-prediction`），由它派生 `loading`、`loaded`、`errors` 三个字典的初始值，使三者键集合不可能失同步（design 决策 3、Risks 末条）
- [x] 1.2 从 `loading` / `loaded` 中移除 `watched`、`traffic`、`game` 三个标签页级键 —— 复合标签页的状态由 `{tab}-{source}` 键唯一表达（design 决策 2）
- [x] 1.3 删除 `data()` 中的 `error: null`，改由 `errors` 字典承担（design 决策 3）

## 2. 改造数据加载方法

- [x] 2.1 `loadTabData(tab)`：对 `watched` / `traffic` / `game` 三个复合标签页不再检查也不再设置 `loaded[tab]`，直接委托给对应的 `loadWatchedTimeData` / `loadTrafficData` / `loadGameData`；简单标签页（`credits`、`donation`、`badge`、`invitation`）保持原有的 `loaded[tab]` 逻辑（`Rankings.vue:1516-1582`，design 决策 2）
- [x] 2.2 `loadTabData` 的 `try`/`catch`/`finally` 改为只写自己那一格：成功写 `loaded[tab]`、失败写 `errors[tab]`、结束清 `loading[tab]`；移除开头的 `this.error = null`，改为在本次加载开始时清除 `errors[tab]`
- [x] 2.3 `loadWatchedTimeData(source)`：失败时写 `errors['watched-' + source]`，开始时清除同键；移除对共享 `this.error` 的读写（`Rankings.vue:1584-1618`）
- [x] 2.4 `loadTrafficData(source)`：同 2.3，键为 `traffic-{source}`（`Rankings.vue:1620-1654`）
- [x] 2.5 `loadGameData(source)`：同 2.3，键为 `game-{source}`（`Rankings.vue:1656-1720`）
- [x] 2.6 全文搜索 `this.error`，确认已无残留引用

## 3. 收敛流量榜的缓存失效逻辑

- [x] 3.1 新增 `invalidateAllTrafficSources()` 方法：将 `loaded['traffic-plex']` 与 `loaded['traffic-emby']` 一并置为 `false`（design 决策 1）
- [x] 3.2 `trafficDateRange` watcher 改为调用 `invalidateAllTrafficSources()`，随后只重新获取当前 `trafficSource` 的数据（`Rankings.vue:1416-1425`）
- [x] 3.3 `onTrafficDateChange()` 中的失效逻辑改为调用 `invalidateAllTrafficSources()`（`Rankings.vue:2099-2104`）
- [x] 3.4 `confirmDateSelection()` 中的失效逻辑改为调用 `invalidateAllTrafficSources()`（`Rankings.vue:2136-2140`）
- [x] 3.5 全文搜索 `loaded[\`traffic-`，确认三处失效点均已改为调用统一方法，无遗漏的「只失效当前 source」写法

## 4. 状态展示下移到内容区

- [x] 4.1 新增统一的状态展示单元（同文件内的局部组件或带具名插槽的 `<template>`），入参为状态键与展示名称，按 `loading` → `errors`（含就地重试按钮）→ 空数据 → 内容的顺序渲染，避免五处近似模板重复（design 决策 4 末段）
- [x] 4.2 删除模板中的整页加载分支（`Rankings.vue:20-25`）与整页错误分支（`Rankings.vue:27-32`），使标签栏与筛选控件无条件渲染
- [x] 4.3 删除失去调用方的 `isCurrentTabLoading()` 方法（`Rankings.vue:1735-1746`）
- [x] 4.4 `watched` 与 `traffic` 的 `v-window-item`：将既有的内层加载分支（`Rankings.vue:256-259`、`483-486`）接入统一状态单元，补上失败态与重试入口 —— 这两处此前因外层条件相同而永不渲染，本次激活
- [x] 4.5 为 `credits`、`donation`、`badge`、`invitation` 四个简单标签页的 `v-window-item` 补上内层状态展示（此前依赖已删除的整页分支）
- [x] 4.6 为 `game` 的 `v-window-item` 补上内层状态展示，键为 `game-{gameSource}`
- [x] 4.7 确认加载与失败状态下，页面标题、标签栏、数据源选择与日期筛选控件均保持可见可操作

## 5. 移除头部刷新按钮

- [x] 5.1 删除 `Rankings.vue:8-17` 的「刷新数据」按钮，头部仅保留标题与副标题，与 `Management.vue` / `UserInfo.vue` 一致
- [x] 5.2 删除 `.refresh-btn` 样式规则（`Rankings.vue:2200-2205`），并检查 `@media` 响应式区块内是否有该类的覆盖规则需一并清理
- [x] 5.3 将 `forceRefreshData()` 改为接收状态键参数、只重试该键对应的那一格数据（`Rankings.vue:1749-1769`，design 决策 5）
- [x] 5.4 将各内层状态单元的重试按钮接到改造后的 `forceRefreshData(key)`

## 6. 静态检查

- [x] 6.1 `npm run lint` 无报错、无新增警告
- [x] 6.2 `npm run build` 构建成功
- [x] 6.3 检查浏览器控制台在页面各项操作下无报错（含 Vue 的 undefined 属性访问警告 —— 状态键改动后尤需确认）

## 7. 手工验收：核心缺陷

对应 spec「筛选条件与展示数据的一致性」与「流量榜的日期范围筛选」。

- [x] 7.1 流量榜以「本月」查看 Emby → 切换到 Plex → 确认展示的是**本月**的 Plex 数据，且日期标签与列表内容一致
- [x] 7.2 先切到 Plex 加载一次 → 切回 Emby → 改为「本月」→ 切到 Plex → 确认为本月数据（原缺陷的精确复现路径）
- [x] 7.3 依次执行「切 Plex」→「昨日」→「切 Emby」→「本月」→「切 Plex」，确认最终为本月的 Plex 数据
- [x] 7.4 自定义日期路径：设自定义范围 → 切换数据源 → 确认沿用该自定义范围
- [x] 7.5 日期选择器确认路径：在选择器中改日期并点确认 → 切换数据源 → 确认沿用新范围
- [x] 7.6 自定义范围越界收敛：选择早于本月一日的开始日期，确认被收敛为本月一日并按收敛后范围取数
- [x] 7.7 自定义范围结束日期早于开始日期，确认被收敛为与开始日期相同

## 8. 手工验收：状态作用范围

对应 spec「加载状态的作用范围」「失败状态的作用范围与恢复」「失败与无数据的区分」。

- [x] 8.1 切换流量榜数据源时，确认仅列表区域出现加载提示，标题、标签栏、筛选控件保持可见（不再整页闪白）
- [x] 8.2 某标签页数据仍在加载中时点击其他标签页，确认可正常切换
- [x] 8.3 加载提示中正确标示了正在获取的数据源
- [x] 8.4 模拟单个数据源请求失败（如临时改错该接口路径或断网后只切该数据源）：确认失败提示与重试入口出现在列表区域内，标签栏与数据源选择仍可用，可直接切回另一数据源查看数据
- [ ] 8.5 就地重试仅重新获取该项数据，其他标签页与数据源的已有数据不受影响
- [ ] 8.6 某数据源失败后切到积分榜（成功）再切回，确认失败提示与重试入口**仍然存在**，且未被显示成「暂无数据」（原缺陷 2 的复现路径）
- [ ] 8.7 真实空结果（选一个确无流量记录的日期范围）确认展示的是无数据提示，与失败提示形态可区分

## 9. 手工验收：获取时机与回归

对应 spec「榜单数据的获取时机」「媒体服务数据源切换」「手动刷新入口」。

- [x] 9.1 确认头部无刷新按钮，且标题区域排版与 `Management.vue` / `UserInfo.vue` 观感一致（原按钮占位移除后无残留空隙）
- [x] 9.2 同一次访问内标签页来回切换，确认已加载的简单标签页不重复请求（观察 Network 面板）
- [x] 9.3 同一筛选条件下数据源来回切换，确认不重复请求
- [x] 9.4 离开排行榜页面后经底部导航返回，确认数据重新获取（移除刷新按钮后的新鲜度兜底路径）
- [x] 9.5 逐一回归七个标签页：积分、捐赠、观看时长（Plex／Emby）、流量（Plex／Emby）、勋章、游戏（转盘／夺宝／预言家各自的排名类型切换）、邀请 —— 确认列表渲染、勋章展示、跑马灯效果、等级图标均未受影响
- [x] 9.6 观看时长榜切换数据源，确认不受日期筛选影响（该榜单无日期维度）
- [x] 9.7 移动端视口（≤600px）下确认上述状态展示与头部排版正常
