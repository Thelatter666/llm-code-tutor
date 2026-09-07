# 前端共存策略：Tailwind 入 cascade layer，回归靠 Playwright 截图基线

引入 Tailwind v4 后，它会与全量引入的 Element Plus 长期共存（ADR-0011）。同时前端只有 1 个 `markdown.spec.ts`，5000 行级改造没有安全网。本 ADR 定这两件事的做法。

## 决策一：Tailwind 输出整体进入 cascade layer，Element Plus 保持 unlayered

Tailwind v4 的 preflight 会给 `button` 强加 `border-style: solid; border-width: 0; background-color: transparent`，直接破坏 `el-button`（表现为按钮背景透明、边框丢失）。

不用「关掉 preflight」这条路：本项目依赖 preflight 提供的 `box-sizing: border-box` 与基础重置，关掉会引起全站布局偏移。

采用 **CSS 级联层**：把 Tailwind 的三段输出分别放进 `@layer theme / base / utilities`，Element Plus 的 CSS 保持无层（unlayered）。按 CSS 级联规则，**无层样式优先于任何层内样式**，于是：

- `el-button` 等组件样式恒胜 preflight，既有页面零视觉变化；
- Tailwind 工具类不会误伤 Element Plus 内部 DOM，两个阶段互不干扰；
- 需要工具类强制覆盖时，用 Tailwind v4 的 `!` 后缀（如 `bg-card!`）或在无层的自定义 CSS 中写。

导入顺序固定在 `main.ts`：`@/styles/index.css`（Tailwind 三段 + 设计令牌）先，`element-plus/dist/index.css` 后。

## Considered Options

- **关掉 preflight（`corePlugins.preflight = false`，v4 为不导入 `preflight.css`）**：常见做法，但等于放弃基础重置，本项目 14 个页面会同时出现盒模型与字体继承差异，风险集中且难定位。
- **给 Tailwind 加类名前缀（如 `tw-`）**：隔离彻底，但所有新写类名都要带前缀，与 shadcn-vue 生成的组件代码不兼容（其源码不含前缀），需要逐个改写生成物。
- **cascade layer 隔离（采纳）**：零侵入、可逆，且是纯 CSS 层机制，不依赖构建插件。

## 决策二：回归网用 Playwright 截图基线 + 冒烟清单，不追求组件单测

- 截图基线：`@playwright/test`（chromium），对 14 个路由逐个截图存 `tests/screenshots/baseline/`，改造前先存一份「旧版基线」作为对照，改造后逐张 diff，人工确认差异是否预期。
- 冒烟清单：覆盖 12 个功能点的演示路径（README 已列），每期改造后人工/脚本过一遍，功能口径不得删减。
- **不建**组件级单测与 E2E 全覆盖：本阶段价值密度低，先把「有没有坏」的网建起来。

## Consequences

- `playwright.config.ts` 以 `http://localhost:5173` 为 baseURL，截图基线需本地 dev server 或 `make serve` 起后端（登录用种子账号 `admin / Admin@12345`）。
- 截图基线是**人工确认**工具，不是自动断言门禁；差异由用户判定，避免把视觉微调误判为回归。
- 共存期结束后（Element Plus 退场），preflight 可恢复默认位置，layer 隔离随之移除——此项列入后续批次的收尾任务。
