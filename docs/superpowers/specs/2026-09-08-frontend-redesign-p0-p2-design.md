# 前端重设计（P0 地基 + P2 应用外壳）设计方案

> 关联 ADR：[0011 技术栈](../adr/0011-frontend-redesign-vue-tailwind-shadcn-vue.md) · [0012 共存与回归策略](../adr/0012-tailwind-element-plus-coexistence-and-visual-regression.md)
> 日期：2026-09-08 · 分支：`feat/fe-redesign-p0-p2`

## 1. 背景与目标

前端 19 个 `.vue` 共 5224 行、约 280 处 `el-*` 调用，公共组件仅 5 个，观感陈旧且存在 10 类 UI 重复。目标：建立**新设计系统的地基**并**重做应用外壳**，使后续按页面替换时有统一的令牌、组件层与安全网。

**成功标准**：新外壳观感焕新、13 个路由行为不变、既有页面视觉零变化（未被 Tailwind 破坏）、改造过程有截图基线可比对。

## 2. 范围

**本期做**：P0 地基（依赖与构建、设计令牌 v2、`ui/` 最小子集、回归网）+ P2 应用外壳（AppShell）。

**本期不做**（明确非目标）：
- 14 个页面内部改造（P3–P5，后续批次）
- `ui/` 完整适配层（Table / Form / Modal / Pagination / Select 等留待 P1）
- 暗色模式开关（仅预留 `.dark` 变量占位，不做切换 UI）
- `ui-baseline.md` 改写（本期产出 v2 草稿，待用户设计确认后再替换）
- 后端任何改动；`api/` 与 `types/` 只增不改（API 契约冻结）

## 3. 设计令牌 v2

`src/styles/theme.css` 保留 v1 全部 `--color-*` / `--space-*` / `--radius-*` 变量名（页面仍在用，改名会炸），在其上扩展：

| 类别 | 新增/调整 |
|---|---|
| 色彩 | 新增 `--color-border-strong` `#C4B5FD`、`--color-overlay` `rgb(30 27 75 / 0.45)`；其余沿用 v1（primary `#7C3AED` / accent `#0891B2` / destructive `#DC2626`） |
| 字阶 | `--text-xs` 12/1.5 · `--text-sm` 13/1.6 · `--text-base` 14/1.6 · `--text-md` 16/1.5 · `--text-lg` 18/1.4 · `--text-xl` 22/1.3 · `--text-2xl` 28/1.25 |
| 圆角 | `--radius-control` 8 / `--radius-card` 12 / `--radius-dialog` 16 / `--radius-pill` 999 |
| 阴影 | `--shadow-xs/sm/md/lg`（四级 elevation，替代现在「只有边框没有层级」的观感） |
| 动效 | `--duration-fast` 150ms / `--duration-base` 200ms / `--duration-slow` 300ms · `--ease-standard` `cubic-bezier(.2,0,0,1)` |
| 暗色 | `.dark { }` 变量集占位（值为空，待后续填充），不引入切换 UI |

**Tailwind 映射**：在 Tailwind v4 的 `@theme inline` 中把上述令牌映射为工具类（`bg-primary`、`text-muted-foreground`、`rounded-card`、`shadow-card`、`text-lg` 等），使新写样式与既有 CSS 变量同源，不出现第二套色值。

## 4. 技术基建

- 依赖：`tailwindcss@4` + `@tailwindcss/vite`（Vite 插件，无需 postcss 配置）；shadcn-vue 生成物所需 `reka-ui`、`class-variance-authority`、`clsx`、`tailwind-merge`、`lucide-vue-next`、`tw-animate-css`；dev 增 `@playwright/test`。
- `vite.config.ts`：新增 `tailwindcss()` 插件；保留既有 `manualChunks`（Vue / element-plus / markdown / monaco 四块），Tailwind 产物走默认 CSS 分包。
- `components.json`（shadcn-vue）：Tailwind v4、base color `neutral`、CSS 变量开启、别名 `@/components` → `src/components`、`@/lib` → `src/lib`、组件目录 `src/components/ui`。
- **CSS 分层与导入顺序**（ADR-0012）：`src/styles/index.css` 内
  `@layer theme, base, components, utilities;` → `@import "tailwindcss/theme.css" layer(theme)` → `@import "tailwindcss/preflight.css" layer(base)` → `@import "tailwindcss/utilities.css" layer(utilities)` → 其后写 `@theme inline` 令牌映射与 `@layer base` 的基础样式。`main.ts` 中先引 `styles/index.css`、后引 `element-plus/dist/index.css`，保证 Element Plus 以无层样式恒胜。
- 目录：`src/components/ui/`（shadcn-vue 源码，可改）、`src/ui/`（本项目应用级适配层）、`src/lib/utils.ts`（`cn()`）。

## 5. UI 适配层 `src/ui/`（本期最小子集）

只做外壳必需的 6 件，全部为**薄封装**，页面/外壳只依赖 `@/ui/*`：

| 组件 | 底层 | 契约 |
|---|---|---|
| `UiButton` | 原生 button + cva（不包 el） | `variant: default \| secondary \| ghost \| danger \| link` · `size: sm \| md \| icon` · 完整转发原生 button 属性与事件 |
| `UiBadge` | 原生 span + cva | `variant: primary \| warning \| muted \| danger` |
| `UiIcon` | `lucide-vue-next` | `:name` + `:size`（默认 16）+ `stroke` 统一；禁 emoji 的落点 |
| `UiDropdownMenu` | shadcn-vue dropdown-menu | 外壳用户菜单用；`trigger` / `content` 插槽 |
| `UiTooltip` | shadcn-vue tooltip | 侧栏折叠态的图标提示 |
| `UiSheet` | shadcn-vue sheet | <768px 的移动端抽屉导航 |

契约三条：① 只在此层引入第三方 UI 原语，页面不得直接 import `el-*` 或 `components/ui/*`；② 组件不内置业务逻辑（不发请求、不碰 store）；③ 每个组件带最小 vitest 用例（渲染 + variant 类名）。

## 6. 应用外壳（P2）

- **结构**：`header`（sticky，h-56，品牌 + 折叠触发 + 右侧用户菜单）+ `aside`（240px 分组导航，折叠态 72px 纯图标）+ `main`（`max-width: 1440px`，gutter 24，可滚动）。
- **导航模型**：抽 `src/nav.ts` 导出 `NAV: NavItem[]`，字段 `{ path, label, icon, group: 'learn' \| 'admin', adminOnly }`，供外壳与后续测试复用；两条分组标题「学习」「管理」仅在有可见项时渲染。
- **响应式**：≥1280 展开；1024–1279 折叠为图标 + tooltip；<1024 隐藏侧栏，顶栏出现菜单按钮，用 `UiSheet` 抽屉；<768 内容 gutter 16。
- **用户菜单**：`UiDropdownMenu`，头部显示用户名 + 角色 `UiBadge`，项：退出登录（沿用 `auth.doLogout()` → `router.push('/login')`）。
- **可访问性**：`nav` 带 `aria-label`、当前项 `aria-current="page"`、`:focus-visible` 用 `--color-ring`、提供 skip-link 跳到主内容。
- **行为不变项（回归重点）**：13 个路由与顺序、管理员项仅 `auth.isAdmin` 可见、未登录跳 `#/login`、非管理员访问 `/admin/*` 跳 `#/chat`、退出清 token。
- 折叠状态持久化到 `localStorage`（键 `lct.sidebar.collapsed`）。

## 7. 回归网

- **旧版基线先行**：改造前用 Playwright 对 14 个路由 + 折叠态截图，归档 `tests/screenshots/baseline/`，作为后续比对的「旧版」参照。
- `playwright.config.ts`：chromium，`baseURL=http://localhost:5173`，`--update-snapshots` 更新基线，失败截图输出 `tests/screenshots/actual/`。
- `tests/e2e/smoke.spec.ts`：种子账号 `admin / Admin@12345` 登录 → 逐个路由截图 → 断言侧栏可见项数（管理员 13 项）与关键文案；学生账号场景用运行期新建（或直接断言管理员态），本期以管理员态为主。
- `package.json` 增 `test:e2e` / `test:e2e:update` 两个 script。
- **冒烟清单**（12 功能点，改造后人工过）：沿用 README 的演示路径表，功能口径不得删减。

## 8. 验收标准

1. `npm run build`（`vue-tsc --noEmit` + `vite build`）零错误。
2. `npm test`（vitest）通过，且新增 `ui/` 组件用例。
3. **既有页面视觉零变化**：P0 完成后逐路由比对旧版基线，除令牌引入的预期差异外不得有 Element Plus 破样式（重点看 `el-button` / `el-input` / `el-table`）。
4. P2 完成后：13 路由可达、角色过滤正确、折叠/抽屉/键盘导航可用、退出登录正常。
5. 无新增 `v-html`（`MarkdownView` 仍是唯一豁免点）。
6. 构建体积较改造前的增量可接受（Tailwind 产物为 CSS，Monaco 仍动态 import）。
