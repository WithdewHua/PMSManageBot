## Context

排行榜整个页面是单文件组件 `webapp-frontend/src/views/Rankings.vue`（约 3760 行），无子组件拆分。状态集中在 `data()` 的三组结构里：

- `rankings.*` —— 各榜单数据，按 `{榜单}_rank[_{数据源}]` 命名
- `loading.*` / `loaded.*` —— 两个平铺字典，键混用了两种粒度：标签页级（`credits`、`traffic`）与「标签页+数据源」级（`traffic-plex`、`watched-emby`）
- `error` —— 单个字符串，全页共用

筛选状态是 `trafficSource` / `watchedTimeSource` / `gameSource` / `trafficDateRange` / `trafficStartDate` / `trafficEndDate`，各自由 `watch` 驱动加载。

两个既有事实约束了方案：

1. **`App.vue:4` 的 `<router-view />` 未包 `<keep-alive>`**。组件每次进入被重建，`data()` 重新执行，所有缓存标记归零。因此缓存生命周期本就是「单次页面访问」，无需额外的过期机制。
2. **后端无缓存**（`src/app/webapp/routers/rankings.py` 直查数据库），响应即时反映最新数据。前端少缓存一层不会有性能悬崖。

问题的共性是：`loading` / `loaded` / `error` / 手动刷新这四样东西描述的层级与它们实际生效的层级不一致。详见 `proposal.md` 的 Why。

## Goals / Non-Goals

**Goals:**

- 让 `loading`、`loaded`、`errors` 三个字典使用**同一套键**，使「一格数据」成为状态的统一单位
- 缓存失效的粒度与筛选条件的作用范围对齐
- 状态的展示层级与其数据的作用范围对齐

**Non-Goals:**

- 不拆分 `Rankings.vue`。组件确实过大，但拆分是独立的重构，与本次修复混在一起会让 diff 无法审查。
- 不引入 `<keep-alive>`。当前的「离开即失效」正是移除刷新按钮后的新鲜度兜底，加 `keep-alive` 会破坏它。
- 不引入 Pinia／Vuex 或跨组件状态管理。
- 不改动任何后端接口。
- 不做跨日期范围的缓存复用（见下方决策）。

## Decisions

### 决策 1：缓存键保持 `{tab}-{source}`，日期变化时失效全部数据源

**方案**：`loaded` 的键仍为 `traffic-plex` / `traffic-emby`，不把日期拼进键。日期范围变化时把两个数据源的标记一并置为失效，仅重新获取当前展示的那个，另一个留待切换时懒加载。

**否决的替代方案**：把日期并入键，即 `traffic-{source}-{start}-{end}`。

| | 键含日期 | 全源失效（采纳） |
|---|---|---|
| 正确性 | 天然正确 | 需要三个失效点都写对 |
| 跨日期复用 | 有 | 无 |
| 键的数量 | 随自定义日期无界增长 | 固定 4 个 |
| `loading`/`errors` 同构 | 三个字典都要动态键 | 保持静态键 |

选后者的理由：日期范围在语义上是**全局筛选器** —— 它一变，页面上所有数据源的数据在语义上都过期了。「全部失效」直接表达这个语义。而跨日期复用的收益很小（用户很少来回切日期），却要换来无界增长的键空间和三个字典的动态键写法。加上组件每次进入都重建、缓存本就只活一次访问，复用窗口极短。

**代价**：正确性依赖三个失效点都被覆盖。这三处是同一份「只失效当前 source」的重复代码：

- `Rankings.vue:1416-1425` `trafficDateRange` watcher —— 预设范围切换
- `Rankings.vue:2080-2106` `onTrafficDateChange()` —— 自定义日期变更
- `Rankings.vue:2132-2141` `confirmDateSelection()` —— 日期选择器确认

**缓解**：抽出一个统一的失效方法（如 `invalidateAllTrafficSources()`），三处都调它。重复代码是漏改的根源，收敛成一处即消除该风险。

### 决策 2：移除复合标签页的标签页级缓存标记

**问题**：带数据源维度的标签页（`watched` / `traffic` / `game`）同时被两层标记描述：

```
loaded['traffic']        ← 标签页级，由 loadTabData 设置（Rankings.vue:1574）
loaded['traffic-emby']   ← 数据源级，由 loadTrafficData 设置（Rankings.vue:1646）
```

`loadTrafficData` 内部 catch 掉异常不外抛，因此 `loadTabData` 的 `try` 会继续执行到 `this.loaded[tab] = true` —— **请求失败了，标签页级却被标记为成功**。后果链：

```
① 进入流量榜，Emby 请求失败
   loaded['traffic'] = true ⚠   loaded['traffic-emby'] = false   error = '获取失败'
② 切到积分榜，成功。loadTabData 开头 this.error = null，失败提示被抹掉
③ 切回流量榜。loaded['traffic'] 为 true → 直接 return，不重新获取
   → 界面显示「暂无 EMBY 数据」（实际是请求失败）
```

**方案**：`loadTabData` 对这三个标签页既不检查也不设置 `loaded[tab]`，直接委托给 `loadWatchedTimeData` / `loadTrafficData` / `loadGameData`；它们各自的 `{tab}-{source}` 标记就是唯一真相。相应地从 `loading` / `loaded` 字典中删掉 `watched` / `traffic` / `game` 三个键，避免留下无人写入的死键造成误解。

**为什么不选「失败时不设 `loaded[tab]`」**：那只是把两层标记调成同步，双层结构仍在，下一处改动仍可能让它们再次分叉。删掉冗余的那一层才是治本。

### 决策 3：`error: String` → `errors: Object`，键与 `loading`/`loaded` 同构

```js
loading: { credits, donation, badge, invitation, 'watched-plex', 'watched-emby',
           'traffic-plex', 'traffic-emby', 'game-wheel', 'game-treasure', 'game-prediction' }
loaded:  { …同上… }
errors:  { …同上… }   // 新增
```

三个字典键完全一致，「一格数据」有且只有三种状态归属，`loadXxxData` 的 `try`/`catch`/`finally` 各自只写自己那一格。

顺带解决了上面步骤 ② 的「失败提示被其他成功请求抹掉」：不再有共享的 `this.error` 可抹。

**为什么不保留 `error` 做兜底**：两套错误状态并存会立刻产生「该看哪个」的问题。单一来源更清晰。

### 决策 4：加载态与失败态完全下移到内容区

**现状**是三层互斥结构，外层赢：

```
Rankings.vue:20   v-if="isCurrentTabLoading()"     ← 全屏 spinner，标签栏一起消失
Rankings.vue:27   v-else-if="error"                ← 全页错误，标签栏一起消失
Rankings.vue:34   v-else                           ← 标签栏 + 内容
Rankings.vue:483    v-if="loading[`traffic-${trafficSource}`]"   ← 内层
```

`isCurrentTabLoading()`（`Rankings.vue:1735-1746`）返回的**就是** `loading['traffic-' + trafficSource]`，与内层 483 行条件完全相同 → 外层为真时内层不渲染，外层为假时内层必假。**`Rankings.vue:256` 与 `483` 的数据源级加载提示是永不执行的死代码。**

**方案**：删除外层的整页 `loading` / `error` 分支，标签栏与筛选控件无条件渲染；每个 `v-window-item` 内部按 `loading[key]` → `errors[key]` → 空数据 → 列表的顺序自行决定展示。`watched` / `traffic` 已有内层加载分支（激活即可），`credits` / `donation` / `badge` / `invitation` / `game` 需要补。

**副产品**：`isCurrentTabLoading()` 失去调用方，一并删除。

**为什么不用最小改动方案**（给外层加 `&& !isCompositeTab`）：那样加载态仍分裂在两个层级，且没有解决「加载时标签栏消失、无法切换」的问题 —— 而这正是 spec 里「加载期间标签栏保持可操作」要求的。

**统一状态块**：五处新增的内层状态分支形态相同（加载中／失败＋重试／空数据）。为避免五份近似模板，抽成一个局部展示单元（同文件内的小组件或 `<template>` + 具名插槽），入参为状态键与对象名称。这不构成决策 Non-Goals 里排除的「拆分组件」——它是消除本次新增的重复，而非重构既有结构。

### 决策 5：删除头部刷新按钮，保留 `forceRefreshData` 服务于就地重试

`Rankings.vue:8-17` 的按钮及 `2200-2205` 的 `.refresh-btn` 样式删除，头部回归与 `Management.vue` / `UserInfo.vue` 一致的纯标题形态。

`forceRefreshData()`（`Rankings.vue:1749-1769`）**保留**：`Rankings.vue:29` 的重试按钮依赖它。但语义收窄为「重试指定的那一格」，因此改为接收状态键参数而非隐式读取 `activeTab`：调用方是各内层状态块里的重试按钮，键已在手。

移除依据见 `proposal.md`。要点：无 `keep-alive`，离开再进入即完整重新获取；按钮唯一独占的场景仅剩「停在页面手动求新」，而流量与观看时长依赖 Tautulli／Emby 的上报与定时同步，即时点击大概率拿到相同数字。

## Risks / Trade-offs

**[三个日期失效点漏改一处，核心 bug 复现]** → 收敛成单一 `invalidateAllTrafficSources()` 方法，三处均调用，物理上消除漏改可能。验收时逐一走查三条路径：预设范围切换、自定义日期变更、日期选择器确认。

**[放弃跨日期缓存复用，来回切日期会重复请求]** → 接受。后端直查数据库无缓存层，且组件每次进入即重建、缓存本就短命；用户来回切换同一日期范围的频率低。若日后出现性能问题，再按决策 1 的替代方案把日期并入键。

**[删除刷新按钮后，长时间停留页面的用户没有手动求新入口]** → 已在 spec 中约定替代路径（离开并重新进入、或变更筛选条件）。若上线后确有反馈，可在各榜单标题行内补一个作用范围明确的局部刷新图标 —— 位置与作用范围一致，不重犯原按钮的错位问题。

**[五处新增内层状态块引入模板重复]** → 抽统一状态展示单元（决策 4）。

**[单文件 3760 行，改动横跨模板与逻辑，回归面较宽]** → 改动集中在状态管理与状态展示两处，不触碰任何榜单的数据渲染逻辑与样式。七个标签页 × 各自数据源需逐一手工验收，验收清单落在 `tasks.md`。

**[`errors` 字典与 `loading`/`loaded` 键失同步]** → 三者键集合完全相同，建议由单一键列表派生初始值，使新增数据源时不可能只加一半。

## Migration Plan

纯前端改动，无数据迁移、无接口变更、无部署顺序依赖。构建产物替换即生效。

回滚：单文件改动，`git revert` 即可完全还原，无残留状态。

## Open Questions

无。方案已收敛，所有决策点已在上文定论。
