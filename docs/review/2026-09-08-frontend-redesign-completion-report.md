# 前端整体重新设计 完成报告（P0–P6）

> **定位**：本报告是前端后续所有修改的**上下文基线**。改动前端前请先读 §3 架构、§5 适配层契约、§6 不可动清单、§7 实证坑。
> 日期：2026-09-08 · 执行分支：`feat/fe-redesign-p0-p2` → `-p3-student` → `-p4-student` → `-p5-admin` → `-p6-finalize`（均已合回 `main`）
> 关联：ADR-0011（技术栈）、ADR-0012（共存与回归策略）、`frontend/docs/ui-baseline.md`（v2 设计基线，强制）、spec / plan 见 `docs/superpowers/`

---

## 1. 任务背景与目标口径（用户裁定，不得偏离）

- **参照系**：21st.dev 组件生态（React + Tailwind + shadcn）。经用户拍板走 **B 路线**：保留 Vue 3，引入 **Tailwind CSS v4 + shadcn-vue**，渐进替换 Element Plus，**不迁 React**。
- **改动深度**：视觉重做 **+ 组件抽取**（决策 ②）——顺势消灭历史重复（容器三派、loading 三套、管理端筛选+表格+分页三连、`formatTime` 五份等 10 类）。
- **视觉方向**：**v2 基线的浅紫 AI-Native**。色彩完全沿用 v1（主色 `#7C3AED` / 强调 `#0891B2`），**不做"改头换面"式换色**——用户已明确"改头换面之后自己弄"。
- **回归保障**：Playwright 截图基线 + 12 功能点冒烟清单（不追求组件级全覆盖）。
- **交付形态**：六期分批（P0 地基 → P2 外壳 → P3/P4 学生端 → P5 管理端与登录 → P6 收口），每期独立分支、独立验收、逐期合回 main。

## 2. 批次与提交清单

| 批次 | 分支 | merge 提交 | 内容 |
|---|---|---|---|
| P0 地基 | `feat/fe-redesign-p0-p2` | — | Tailwind v4（`@tailwindcss/vite`）、设计令牌 v2、`src/ui/` 最小集、Playwright + 冻结基线 `v1-old/` |
| P2 外壳 | 同上 | `438290e` | `src/nav.ts` 导航模型 + `AppShell` 重做（分组侧栏 / 折叠 / 抽屉 / 用户菜单 / skip-link） |
| P3 学生端核心 | `feat/fe-redesign-p3-student` | `e29fcd5` | ChatView / CodeReviewView / CodeEditorView + `useNotify` / `useConfirm` + UiCard/Alert/Empty/Textarea/Select/Checkbox/RadioGroup/Progress/Collapse |
| P4 学生端其余 | `feat/fe-redesign-p4-student` | `c9a24f4` | KnowledgeSearchView / ExerciseView / MistakeBookView + UiInput/UiSlider/UiCheckboxGroup/UiPagination |
| P5 管理端与登录 | `feat/fe-redesign-p5-admin` | `782061a` | 7 个管理页 + LoginView + UiDialog/UiUpload/UiDatePicker/UiInputNumber + `usePagedList`；**修 box-sizing 缺失** |
| P6 收口 | `feat/fe-redesign-p6-finalize` | `d1406f2` | `DegradedBanner` 收编 `UiAlert`（模板级 `el-*` 清零）、ui-baseline 补共存期约定与检查项、README / CONTEXT 同步 |

关键单点提交：`7922b04`（box-sizing 修复）、`da27257`（工具栏宽度容器）、`ceaa12d`（登录卡）、`4945875` / `a5eb160`（ui/ 扩容）。

## 3. 最终架构

```
frontend/src/
├─ main.ts                 # 引入顺序固定：styles/index.css → element-plus css → theme.css
├─ App.vue                 # 仅 <router-view/>；有 token 则 fetchMe
├─ nav.ts                  # 导航模型：NavItem{path,label,icon,group:'learn'|'admin',adminOnly} + NAV(13 项)
├─ router/index.ts         # hash 路由 + requiresAuth / requiresAdmin 守卫（未动）
├─ styles/
│  ├─ index.css            # 设计系统入口：@layer + Tailwind theme/utilities + @theme inline 映射 + 最小重置
│  └─ theme.css            # 令牌唯一来源（v1 全保留 + v2 扩展：字阶/阴影/动效/pill）
├─ lib/utils.ts            # cn()（clsx + tailwind-merge）
├─ ui/                     # ★ 应用级适配层：21 个组件，页面唯一允许的第三方 UI 出口
├─ components/             # 5 个共享组件：AppShell / CodeEditor / MarkdownView / CitationList / DegradedBanner
├─ composables/            # useSse / useNotify / useConfirm / usePagedList
├─ stores/auth.ts          # Pinia（未动）
├─ api/ · types/           # 后端契约镜像（冻结，只增不改）
└─ views/
   ├─ LoginView.vue        # 品牌化登录卡
   ├─ student/ (6)         # 全部已改造
   └─ admin/ (7)           # 全部已改造
```

**依赖方向（硬规则）**：`views/` 与 `components/` → `@/ui` → （内部）el-* 或将来的 shadcn-vue。
**禁止反向**：页面不得直接 import `el-*`、`components/ui/*`、`ElMessage`、`ElMessageBox`。

## 4. 设计系统要点（v2 基线）

- **色彩不变**（v1 全保留）：Primary `#7C3AED`、Accent `#0891B2`、Destructive `#DC2626`、背景 `#FAF5FF`、前景 `#1E1B4B`。
- **Tailwind 语义映射**（`index.css` 的 `@theme inline`，命名**刻意避开** v1 同名变量以防自引用）：
  `canvas / surface / ink / muted-ink / softer / line / line-strong / brand / brand-fg / highlight / danger`。
- **v2 新增令牌**：字阶 `--fs-xs..2xl`（12/13/14/16/18/22/28）+ `--lh-tight/normal`；阴影 `--shadow-e1..e4`（映射 `shadow-panel` / `shadow-pop`）；动效 `--duration-fast/base/slow` + `--ease-standard`；`--radius-pill`；`--color-border-strong`、`--color-overlay`；`.dark` 占位（无切换 UI）。
- **共存策略（ADR-0012）**：Tailwind 输出进 `@layer theme/utilities`，Element Plus CSS 保持无层 → 无层恒胜，互不破坏。**不引 preflight**，但**必须**保留 `@layer base` 里的 `box-sizing: border-box` 最小重置（缺失见 §7 坑 1）。
- **引入顺序不可动**：`main.ts` 中 `@/styles/index.css` → `element-plus/dist/index.css` → hljs 主题 → `theme.css`。

## 5. 适配层契约（`src/ui/` 终态 21 件 + 4 composables）

**组件**：UiIcon（lucide，PascalCase）· UiButton（cva，5 variant × 4 size）· UiBadge（6 variant）· UiCard · UiAlert（4 variant）· UiEmpty · UiInput · UiTextarea · UiSelect · UiCheckbox · UiCheckboxGroup · UiRadioGroup（button 模式）· UiSlider · UiDatePicker · UiInputNumber（可 null）· UiPagination · UiProgress · UiCollapse · UiDialog · UiDrawer · UiDropdown(+Item) · UiSeparator · UiTooltip · UiUpload（页面只拿 `File[]`）

**composables**：`useNotify()`（success/info/warning/error/raw）· `useConfirm()`（→ boolean）· `usePagedList<T>(fetcher, pageSize)`（items/total/page/loading + `load/goto/reset`）· `useSse`（**原有，未动**）

**三条契约**：
1. 只在此层引第三方 UI 原语；② 组件零业务逻辑（不发请求、不碰 store）；③ 每个组件配最小 vitest 用例（`tests/ui.spec.ts`，现 20 用例）。
2. 表单控件**基类自带 `w-full`** —— 定宽必须**外层容器**包裹（`<div class="w-[140px]">`），直接传宽度类会被 `w-full` 按 CSS 生成顺序覆盖。
3. 通知 / 确认一律走 `useNotify` / `useConfirm`；加载遮罩统一 `v-loading`（共存期豁免，见基线 §9）；空态一律 `UiEmpty`。

## 6. 不可动清单（历史口径的载体，改动即破坏）

| 位置 | 原因 |
|---|---|
| `composables/useSse.ts` | 自实现 SSE（非 EventSource）：需带 Authorization 与自生成 request_id 才能调 `/stop` |
| `components/MarkdownView.vue` | 全项目**唯一** `v-html` 豁免点，只接受 `renderMarkdown()` 产物（双重消毒） |
| `components/CodeEditor.vue` | Monaco 动态 import + `?worker`（`MonacoEnvironment.getWorker`，不是 getWorkerUrl），动了进首屏 |
| `api/` · `types/` | 后端契约镜像（54 端点），冻结只增不改 |
| `main.ts` 引入顺序 | Tailwind 层与 Element Plus 无层样式的共存前提（ADR-0012） |
| `router` 守卫 / `stores/auth` | 13 路由 + 角色过滤 + 401 跳转的行为基线 |
| README「12 功能点」演示口径 | 每次改造逐条勾验，功能零删减 |

## 7. 实证坑（后续开发最该看的五条）

1. **box-sizing 必须全局补**：不引 preflight 后全局是 content-box，`w-full` + 内边距 + 边框的元素会**溢出容器约 26px**（登录页输入框伸出卡片最先暴露）。已在 `index.css` 的 `@layer base` 补 `*, ::before, ::after { box-sizing: border-box }`。**新增自绘组件若带宽度+内边距，别依赖这条被删掉。**
2. **组件未导入 = 静默退化**：`<UiCard>` 没进 import 时 Vue 把它渲染成原生 `<uicard>`，**命名插槽整段消失且编译期不报错**（ChatView 曾因此"右栏只剩空态"）。定位手段：Playwright dump DOM + grep 小写标签。
3. **宽度类覆盖看 CSS 生成顺序，不看 DOM 顺序**：组件基类 `w-full` 与调用方 `w-[140px]` 同层，谁赢不确定。定宽一律外层容器包裹。
4. **冷启动截图抖动**：dev server 刚起时首屏页面（Monaco、自动选中态）500ms 内渲染不完，截图会捕到中间态。**先跑一遍热身再采基线**，否则会把时序差异误判为回归。
5. **`@theme inline` 不能自引用**：Tailwind 映射名与既有 `--color-*` 同名会非法（`--color-primary: var(--color-primary)`），故语义映射名是**新起的一套**（canvas/ink/brand…），新增令牌时延续这个规则。

## 8. 验证体系

| 命令 | 作用 | 当前状态 |
|---|---|---|
| `npm run build` | `vue-tsc --noEmit` + `vite build` | ✓ 零类型错误 |
| `npm test` | vitest（markdown 8 + ui 12） | ✓ 20/20 |
| `npm run test:e2e` | Playwright：登录 + 14 路由截图 + 13 导航项断言 | ✓ 2/2 |
| `npm run test:e2e:update` | 重采 `tests/screenshots/baseline/` | 供基线更新 |
| `NO_TW=1 npm run dev` | 无 Tailwind 模式（回归对照专用） | — |

基线目录：`tests/screenshots/v1-old/`（改造前冻结参照，**已入库**）；`v2/`、`p3/`、`p4/`、`p5/`、`p5b/`、`final/` 为各期产物（gitignore）。比对方法：md5 逐字节 + 人工看图（先用连续两次运行区分"抖动"与"回归"）。

## 9. 常见任务速查

| 我想… | 做法 |
|---|---|
| 新增页面 | `views/{student,admin}/Xxx.vue`（组合式 + `@/ui`）→ `router/index.ts` 懒加载路由 → `nav.ts` 加 NavItem → `tests/e2e/smoke.spec.ts` ROUTES 加一行并更新 13 项断言 |
| 新增/改 ui 组件 | 只改 `src/ui/*`，补 vitest 用例；不得反向引页面 |
| 定宽工具栏控件 | 外层 `<div class="w-[…px]">` 包裹（§5 契约 2） |
| 发通知 / 二次确认 | `useNotify()` / `useConfirm()`，禁止直接 import ElMessage/ElMessageBox |
| 列表页取数 | `usePagedList`（筛选留页面，变更后 `reset()`） |
| 改配色/间距 | 改 `theme.css` 令牌 + 必要时 `index.css` 的 `@theme inline` 映射；**禁止**在页面里写死色值 |
| 换第三方 UI 底层（如 shadcn-vue） | 只改 `src/ui/*` 内部实现，页面零改动 |

## 10. 遗留与后续路线（均已登记，非本任务范围）

1. **P1：shadcn-vue 正式接入**——`components.json`、`cn()`、`@/ui` 契约已就绪；届时只替换 `src/ui/` 内部实现（UiDropdown/Tooltip/Drawer/Dialog/Select/DatePicker 等 el-* 包装件），页面零改动。
2. **Element Plus 完整退场** + 移除 `@layer` 隔离与全量注册（依赖上一条；`v-loading` 届时一并决策）。
3. **可选**：四张管理页抽 `<AdminTable>` 组件（现用 usePagedList + 同构模板已达标，是否再抽象待评估）。
4. **可选**：暗色模式启用（`.dark` 变量已占位）。

## 11. 数据账

- 页面：15 个（学生 6 + 管理 7 + 登录 + 外壳），模板级 `el-*` **280+ → 0**。
- 净删约 **2000 行**（ChatView 590→260、ExerciseView 787→330、CodeEditorView 495→220、CodeReviewView 308→200、MistakeBookView 470→220、UsersAdminView 330→260 等）。
- 测试：vitest 8 → **20**；Playwright 冒烟 **2/2**（14 路由）。
- chunk：AppShell 926 kB → **7.95 kB**（gzip 169 → 2.94 kB）；element-plus 独立 chunk 938 kB（gzip 302 kB）。
- 文档：ADR-0011 / 0012、spec 与 plan 各 1、`ui-baseline.md` v2、CONTEXT.md 两条修订、本报告。
