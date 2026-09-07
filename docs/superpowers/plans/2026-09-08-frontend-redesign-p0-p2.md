# 前端重设计 P0+P2 Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking. 单线程为主，子代理仅用于只读盘点。

**Goal:** 建立新设计系统的地基（Tailwind v4 + shadcn-vue 基建、设计令牌 v2、`src/ui/` 最小适配层、Playwright 截图基线），并据此重做应用外壳 `AppShell`。既有 14 个页面视觉零变化，13 个路由行为不变。

**Architecture:** 双设计系统共存期。Tailwind 输出进 cascade layer，Element Plus 保持 unlayered（ADR-0012）；shadcn-vue 源码落 `src/components/ui/`，本项目应用级适配层落 `src/ui/`，页面/外壳只依赖 `@/ui/*`（ADR-0011）。API 契约冻结。

**Tech Stack:** Vue 3.5 · Vite 6 · TypeScript 5.7 · Tailwind CSS v4 + `@tailwindcss/vite` · shadcn-vue（`reka-ui` / `cva` / `clsx` / `tailwind-merge` / `lucide-vue-next` / `tw-animate-css`）· Element Plus（共存，逐步退场）· Vitest + Playwright(chromium)

**Spec:** `docs/superpowers/specs/2026-09-08-frontend-redesign-p0-p2-design.md`

## Global Constraints

- 后端契约冻结：`src/api/`、`src/types/` 只增不改；不动 `useSse.ts` 的流式实现与 `MarkdownView` 的 v-html 唯一豁免点。
- 术语以 `CONTEXT.md` 为唯一来源，新增标识符不得自造术语。
- 每个任务结束：`npm run build` 与 `npm test` 通过，才进入下一任务。
- **未经用户明确下令不 commit**（`AGENT.md` 铁律）。
- 不做本期范围外的改动；发现范围外问题登记不修。

## Task 1 · 旧版视觉基线（改造前必须先存）

- [ ] 安装 `@playwright/test@^1.63`，写 `playwright.config.ts`（chromium、`baseURL=http://localhost:5173`、截图输出 `tests/screenshots/`）
- [ ] 起后端 + dev server，用种子账号 `admin / Admin@12345` 跑 `tests/e2e/smoke.spec.ts`，对 14 个路由截图
- [ ] 截图归档为 `tests/screenshots/baseline/`（标记 `v1-old`），作为后续 diff 参照

**验收**：14 张基线图齐备；`npm run test:e2e` 可重复执行。

## Task 2 · 安装并配置 Tailwind v4 + shadcn-vue

- [ ] 装 `tailwindcss@^4` `@tailwindcss/vite` `reka-ui` `class-variance-authority` `clsx` `tailwind-merge` `lucide-vue-next` `tw-animate-css`
- [ ] `vite.config.ts` 加 `tailwindcss()` 插件，保留既有 alias 与 `manualChunks`
- [ ] 生成 `components.json`（Tailwind v4 / neutral / CSS 变量 / 别名 `@/*`→`src/*`），跑 `shadcn-vue init` 产出 `src/lib/utils.ts` 与目录骨架
- [ ] `src/styles/index.css`：按 ADR-0012 写三段分层导入；`main.ts` 调整导入顺序（Tailwind 先、Element Plus 后）

**验收**：`npm run build` 通过；**逐路由比对 Task 1 基线，既有页面无视觉变化**（重点 `el-button` / `el-input` / `el-table`）。此项不过不得继续。

## Task 3 · 设计令牌 v2

- [ ] `theme.css` 在保留 v1 变量的前提下扩展：字阶、阴影、动效时长/曲线、`--color-border-strong`、`--color-overlay`、`--radius-pill`
- [ ] 在 `index.css` 的 `@theme inline` 中映射为 Tailwind 工具类（颜色/圆角/阴影/字号/字体族）
- [ ] 写 `.dark {}` 变量占位（不接切换 UI）

**验收**：`bg-primary` / `rounded-card` / `shadow-card` / `text-lg` 等工具类可用；既有页面仍无视觉变化。

## Task 4 · `src/ui/` 最小适配层（外壳必需 6 件）

- [ ] `UiIcon`（lucide 封装，禁 emoji 落点）、`UiButton`（cva：5 variant × 3 size）、`UiBadge`（4 variant）
- [ ] `UiDropdownMenu` / `UiTooltip` / `UiSheet`（包 shadcn-vue 同名组件）
- [ ] 每个组件补最小 vitest 用例（渲染 + variant 类名）

**验收**：`npm test` 通过；6 件组件无业务逻辑、不碰 store。

## Task 5 · 导航模型与外壳实现（P2）

- [ ] 抽 `src/nav.ts`：`NAV: NavItem[]`（`path`/`label`/`icon`/`group`/`adminOnly`），覆盖现有 13 项并分「学习」「管理」两组
- [ ] 重写 `AppShell.vue`：header（品牌/折叠触发/用户菜单）+ aside（分组导航，折叠 72px + tooltip）+ main（max-width 1440、gutter 24）
- [ ] 折叠状态持久化 `localStorage['lct.sidebar.collapsed']`；<1024 用 `UiSheet` 抽屉
- [ ] a11y：`nav[aria-label]`、当前项 `aria-current="page"`、focus-visible ring、skip-link

**验收**：13 路由可达、管理员 13 项可见、学生仅 6 项、退出登录正常、键盘 Tab 可达全部导航项。

## Task 6 · 回归与比对

- [ ] 更新 `tests/e2e/smoke.spec.ts`：断言侧栏项数、当前项高亮、折叠/展开、角色可见性
- [ ] 重跑截图，产出新版图并与 `v1-old` 人工比对：外壳应为预期差异，页面内部应为零差异
- [ ] 过 12 功能点冒烟清单（README 演示路径），功能口径无删减

**验收**：差异全部可解释；冒烟清单全过。

## Task 7 · 文档收口

- [ ] 产出 `ui-baseline.md` v2 草稿（令牌/字阶/阴影/动效/外壳结构），**等用户设计确认后再替换** v1
- [ ] `CONTEXT.md` 登记新术语（设计令牌 v2 / UI 适配层 / 截图基线）并写修订记录
- [ ] README「已知限制 / 技术栈」同步双设计系统共存状态
- [ ] 汇报：改动效果 + 验证方式 + 遗留项，**由用户亲自检查**

**验收**：文档与实现一致，无漂移。
