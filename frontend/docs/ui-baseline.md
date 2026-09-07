# 前端设计基线（UI Baseline）

- v1 生成方式：`uipro init --ai codebuddy` + `search.py "<产品描述>" --design-system -p "LLM Code Tutor"`（2026-08-30，由 uiuxpromax 输出，非人工拟定）
- v2 生效日期：2026-09-08（经设计确认，替代 v1）
- 适用范围：**所有前端页面**（学生端与管理后台）
- 依据：uiuxpromax design system（v1）+ 前端重设计 P0+P2 批次裁定（v2，ADR-0011 / ADR-0012）

> **本文件是强制约束，不是参考建议。** 后续所有页面的配色、字体、间距、圆角、
> 组件密度、动效与外壳结构一律以本文件为准。变更本文件须重新走设计确认。
>
> **v2 变更摘要**（v1 的色彩 / 字体 / 间距 / 圆角全部保留，以下为新增）：
> ① 引入 Tailwind CSS v4 作为新组件层的工具类来源；② 设计令牌 v2（字阶 / 阴影 /
> 动效 / `--radius-pill` / `--color-border-strong` / `--color-overlay` / `.dark` 占位）；
> ③ 明确 Tailwind 与 Element Plus 的共存策略；④ 新增 UI 适配层 `src/ui/` 规范；
> ⑤ 新增应用外壳结构与导航模型。

---

## 1. 风格定位（沿用 v1）

**AI-Native UI** —— 关键词：对话式、流式文本、助手感、极简 chrome、上下文卡片。

- 明暗双模式均支持（P0 先落亮色，暗色变量已占位、待启用）
- **避免**：厚重装饰条、迟缓的响应反馈
- **核心效果**：三点脉冲打字指示器、流式文本动画、上下文卡片、平滑揭示

### 对本项目的适配说明（沿用 v1）

`uiuxpromax` 给出的 PATTERN 为「Product Demo + Features」——这是**营销落地页**结构，
不适用于本系统（教学应用含对话、代码编辑器、管理后台）。因此：

- ❌ 不采用：Hero / 产品视频 / 功能拆解 / 对比 / CTA 的落地页分节
- ✅ 采用：AI-Native 的**视觉语言**（配色、字体、效果）与**交付前检查清单**
- ✅ 布局改为应用级：顶部导航 + 左侧功能导航 + 主内容区（管理后台）；对话流 + 上下文面板（学生端）

---

## 2. 色彩

以 CSS 变量形式定义，供 Element Plus 主题覆盖与新组件层共同使用。

| 角色 | 色值 | CSS 变量 |
|---|---|---|
| Primary | `#7C3AED` | `--color-primary` |
| On Primary | `#FFFFFF` | `--color-on-primary` |
| Secondary | `#A78BFA` | `--color-secondary` |
| On Secondary | `#0F172A` | `--color-on-secondary` |
| Accent / CTA | `#0891B2` | `--color-accent` |
| On Accent | `#000000` | `--color-on-accent` |
| Background | `#FAF5FF` | `--color-background` |
| Foreground | `#1E1B4B` | `--color-foreground` |
| Card | `#FFFFFF` | `--color-card` |
| Card Foreground | `#1E1B4B` | `--color-card-foreground` |
| Muted | `#ECEEF9` | `--color-muted` |
| Muted Foreground | `#475569` | `--color-muted-foreground` |
| Border | `#DDD6FE` | `--color-border` |
| Destructive | `#DC2626` | `--color-destructive` |
| On Destructive | `#FFFFFF` | `--color-on-destructive` |
| Ring | `#7C3AED` | `--color-ring` |
| **Border Strong**（v2） | `#C4B5FD` | `--color-border-strong` |
| **Overlay**（v2） | `rgb(30 27 75 / 0.45)` | `--color-overlay` |

语义映射（项目内统一）：

- `#7C3AED` Primary —— 主操作、选中态、AI 相关元素
- `#0891B2` Accent —— 次要强调（如「引用来源」「知识点标签」）
- `#DC2626` Destructive —— 错误与危险操作（判题失败、删除）
- 成功态沿用 Element Plus 默认绿，不额外定义

### Tailwind 语义映射（v2）

`src/styles/index.css` 的 `@theme inline` 将上述变量映射为工具类：

`--color-canvas / -surface / -ink / -muted-ink / -softer / -line / -line-strong / -brand / -brand-fg / -highlight / -danger`

即页面写 `bg-canvas / text-ink / bg-brand / border-line` 等。

> **命名刻意与 v1 的 `--color-*` 错开**：`@theme` 内同名变量会自引用（如
> `--color-primary: var(--color-primary)` 非法），故 Tailwind 侧另起语义名。

---

## 3. 字体

- **字体族**：Inter（回退 `-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif`）
- **字重**：400 / 600 / 700 / 800
- **中文字号**：正文 14px，次级 13px，标题 18 / 22 / 28px
- **行高**：正文 1.6，标题 1.3

> 演示环境可能无外网，字体加载失败须能优雅回退到系统字体，不得出现空白。
>
> v2：`--font-app` 为字族唯一来源，`--font-sans: var(--font-app)` 兼容旧引用。

---

## 4. 间距与圆角

| 项 | 值 |
|---|---|
| 基础间距单位 | 4px，按 4 / 8 / 12 / 16 / 24 / 32 递进 |
| 页面外边距 | 24px（≥1024px）、16px（<768px） |
| 卡片内边距 | 16px |
| 组件圆角 | 8px（按钮/输入框）、12px（卡片）、16px（弹窗） |
| **Pill 圆角**（v2） | 999px（徽标 / 头像） |
| 组件密度 | 默认（Element Plus `default` size），不做紧凑化 |

---

## 5. 阴影（v2 新增）

替代「只有边框没有层级」的旧观感：

| 级别 | 值 | 用途 |
|---|---|---|
| `--shadow-e1` | `0 1px 2px rgb(30 27 75 / 0.06)` | 极轻 |
| `--shadow-e2` | `0 2px 8px rgb(30 27 75 / 0.08)` | 卡片（`--shadow-panel`） |
| `--shadow-e3` | `0 8px 24px rgb(30 27 75 / 0.12)` | 弹层（`--shadow-pop`） |
| `--shadow-e4` | `0 16px 48px rgb(30 27 75 / 0.16)` | 全屏浮层 |

---

## 6. 动效（v2 新增）

| 令牌 | 值 |
|---|---|
| `--duration-fast` | 150ms |
| `--duration-base` | 200ms |
| `--duration-slow` | 300ms |
| `--ease-standard` | `cubic-bezier(.2, 0, 0, 1)`（Tailwind `--ease-smooth`） |

沿用 v1 要求：所有可点击元素必须有 `cursor: pointer`；Hover 过渡 150–300ms 平滑；
键盘导航必须有可见 focus 态（使用 `--color-ring`）；尊重 `prefers-reduced-motion`
（流式打字动画在减少动效下改为直接显示）。

---

## 7. 字阶（v2 新增，与 Tailwind `--text-*` 对齐）

| token | size | line-height | Tailwind |
|---|---|---|---|
| `--fs-xs` | 12px | 1.6 | `text-xs` |
| `--fs-sm` | 13px | 1.6 | `text-sm` |
| `--fs-base` | 14px | 1.6 | `text-base` |
| `--fs-md` | 16px | 1.6 | `text-md` |
| `--fs-lg` | 18px | 1.3 | `text-lg` |
| `--fs-xl` | 22px | 1.3 | `text-xl` |
| `--fs-2xl` | 28px | 1.3 | `text-2xl` |

---

## 8. 暗色预留（v2，占位）

`src/styles/index.css` 已写 `.dark { color-scheme: dark; }`。具体色板留到后续批次确定，
**本期不提供切换入口**。

---

## 9. 共存策略（v2，ADR-0012）

双设计系统共存期（Element Plus 逐步退场）：

- Tailwind 输出进 `@layer theme` / `@layer utilities`；**不引入 preflight**（既有页面依赖
  浏览器默认 margin，引入重置会引起全站布局偏移；基础重置留到页面改造批次按需自写）
- Element Plus CSS 保持无层（unlayered）→ 按 CSS 级联规则恒胜层内样式，既有组件不被破坏
- `main.ts` 引入顺序：`@/styles/index.css` 先，`element-plus/dist/index.css` 后
- 工具类需强制覆盖 el-* 时使用 Tailwind v4 的 `!` 后缀（例：`bg-brand!`）

---

## 10. Vue 实现规范（沿用 v1 + v2 补充）

| 规范 | 要求 | 严重度 |
|---|---|---|
| 单文件组件 | 模板 / 脚本 / 样式同置于 `.vue`，不得拆成 `.js` + `.html` | Low |
| 路由懒加载 | 路由组件一律 `() => import('@/views/Xxx.vue')`，禁止静态导入 | Medium |
| 组件命名 | 导入与模板一律 PascalCase | Low |

补充（本项目约定）：

- 组件放 `components/`，页面放 `views/{student,admin}/`
- 组合式 API + `<script setup lang="ts">`
- 类型定义集中放 `types/`，API 调用集中放 `api/`
- 跨组件状态用 Pinia，组件内状态用 `ref` / `computed`

**v2 补充 —— UI 适配层 `src/ui/`**：

- 只在此层引入第三方 UI 原语；页面 / 外壳**不得**直接 import `el-*` 或 `components/ui/*`
- 适配层组件不内置业务逻辑（不发请求、不碰 store）
- 每个适配层组件须有最小 vitest 用例（现落 `tests/ui.spec.ts`）
- 当前成员：`UiIcon` / `UiButton` / `UiBadge` / `UiSeparator` / `UiDropdown` /
  `UiDropdownItem` / `UiTooltip` / `UiDrawer`

---

## 11. 应用外壳与导航模型（v2）

```
header  h-14   brand + 折叠/菜单触发 + 用户菜单（UiDropdown）
  └─ body
      aside  w-60 / 折叠 w-[72px]，lg+ 显示，<1024 隐藏
      └─ main  flex-1 overflow-auto p-6
  mobile (<1024) → UiDrawer 抽屉导航
```

- 导航数据源 `src/nav.ts`：`NavItem{path, label, icon, group: 'learn' | 'admin', adminOnly}`
- 分组标题「学习」「管理」，仅在有可见项时渲染；管理员项按 `auth.isAdmin` 过滤
- 折叠状态持久化 `localStorage['lct.sidebar.collapsed']`
- 图标统一 lucide-vue-next，**禁止 emoji 充当图标**

---

## 12. 交付前检查清单

每个页面完成时必须逐条自查：

- [ ] 不使用 emoji 充当图标（一律用 SVG 图标：lucide）
- [ ] 所有可点击元素有 `cursor: pointer`
- [ ] Hover 态过渡在 150–300ms
- [ ] 亮色模式文字对比度 ≥ 4.5:1
- [ ] 键盘导航 focus 态可见
- [ ] `prefers-reduced-motion` 已尊重
- [ ] 响应式断点 375 / 768 / 1024 / 1440px 均无溢出
- [ ] 路由组件已懒加载
- [ ] `vue-tsc --noEmit` 无类型错误
- [ ] **（v2）** 旧版页面视觉零变化（截图基线比对，14 路由）
- [ ] **（v2）** `npm test` 全绿、`npm run test:e2e` 冒烟通过
- [ ] **（v2）** 无新增 `v-html`（`MarkdownView` 是唯一豁免点）
