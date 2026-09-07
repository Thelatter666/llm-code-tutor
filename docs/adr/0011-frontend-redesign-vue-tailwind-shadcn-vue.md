# 前端重设计采用 Vue 3 + Tailwind v4 + shadcn-vue，不迁 React

前端需要整体重新设计，参照的组件生态（21st.dev）是 React + Tailwind + shadcn，而本系统是 Vue 3 + 全量引入的 Element Plus。因此栈的选择决定了「重新设计」是重写还是演进。结论：**保留 Vue 3，引入 Tailwind CSS v4 与 shadcn-vue，以页面为单位渐进替换 Element Plus**；不迁 React。

触发重设计的现实约束：前端 19 个 `.vue` 共 5224 行、约 280 处 `el-*` 调用，公共组件仅 5 个，10 类 UI 重复（容器三派、loading 三套、管理端筛选+表格+分页三连、`formatTime` 五份等）。

## Considered Options

- **A · 只换肤（留在 Vue 3 + Element Plus，改主题与布局）**：改动最小、回归风险最低，Element Plus 已覆盖 90% 控件。但 21st.dev 那类组件（AI 对话、KPI 卡、图表、空态）在 Element Plus 里没有对等物，只能手写——换皮之后观感提升有限，10 类重复也原样保留，达不到「整体重新设计」。

- **B · 保留 Vue 3，引入 Tailwind v4 + shadcn-vue 渐进替换（采纳）**：shadcn-vue 与 21st.dev 同源（Tailwind + shadcn 设计语言），组件以源码形式进仓库、可直接改；Vue 侧的 Sidebar / Bubble / Message / Empty / Chart 等与本项目场景高度对应。`api/`、`types/`、路由、SSE、Monaco 集成等资产全部保留，后端契约零改动。代价是共存期内双设计系统并存，需要显式的隔离策略（见 ADR-0012）。

- **C · 迁 React + Tailwind + shadcn**：与参照生态完全一致，组件可近乎直接复用。但等于重写全部 5224 行前端，且要重建路由守卫、SSE、Monaco 集成与构建分包；对一个已验收的演示项目，工期与回归风险数倍于收益，而后端契约与功能口径不会因此有任何改善。

## Consequences

- 新增依赖：`tailwindcss@4` + `@tailwindcss/vite`、`shadcn-vue`（CLI 生成 `components.json` 与 `src/components/ui/*`）、`reka-ui`、`class-variance-authority`、`clsx`、`tailwind-merge`、`lucide-vue-next`、`tw-animate-css`。
- `src/components/ui/` 为 shadcn-vue 源码目录（与既有 `components/` 五个组件并存）；`src/ui/` 为本项目的**应用级适配层**，页面只依赖 `@/ui/*`，不直接依赖 `el-*` 或 `components/ui/*`——这是后续换底层的唯一接缝。
- Element Plus **不立即移除**：随页面改造逐步退场，退场完毕前保持全量引入与既有主题变量映射。
- `docs/ui-baseline.md` 是强制约束，新版设计产出后改写为 v2，且须经用户设计确认；在 v2 落地前，v1 的色彩/间距/圆角继续生效（本 ADR 不推翻 v1，只扩展字阶、阴影、动效与暗色预留）。
- 每次页面改造都需同步更新 README 的 12 功能点映射与演示路径——本项目对文档漂移零容忍。
