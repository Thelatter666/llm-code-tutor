# 前端设计基线（UI Baseline）

- 生成方式：`uipro init --ai codebuddy` + `search.py "<产品描述>" --design-system -p "LLM Code Tutor"`
- 生成日期：2026-08-30
- 适用范围：**所有前端页面**（学生端与管理后台）
- 依据：`uiuxpromax` 输出的 design system 与 vue stack 规范

> **本文件是强制约束，不是参考建议。** 后续所有页面（P1–P6）的配色、字体、间距、圆角、
> 组件密度一律以本文件为准。变更本文件须重新走设计确认。
>
> 本基线由 uiuxpromax 生成（非人工拟定）。

---

## 1. 风格定位

**AI-Native UI** —— 关键词：对话式、流式文本、助手感、极简 chrome、上下文卡片。

- 明暗双模式均支持（P0 先落亮色，暗色留待需要时启用）
- **避免**：厚重装饰条、迟缓的响应反馈
- **核心效果**：三点脉冲打字指示器、流式文本动画、上下文卡片、平滑揭示

### 对本项目的适配说明

`uiuxpromax` 给出的 PATTERN 为「Product Demo + Features」——这是**营销落地页**结构，
不适用于本系统（教学应用含对话、代码编辑器、管理后台）。因此：

- ❌ 不采用：Hero / 产品视频 / 功能拆解 / 对比 / CTA 的落地页分节
- ✅ 采用：AI-Native 的**视觉语言**（配色、字体、效果）与**交付前检查清单**
- ✅ 布局改为应用级：顶部导航 + 左侧功能导航 + 主内容区（管理后台）；对话流 + 上下文面板（学生端）

---

## 2. 色彩

以 CSS 变量形式定义，供 Element Plus 主题覆盖使用。

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

语义映射（项目内统一）：

- `#7C3AED` Primary —— 主操作、选中态、AI 相关元素
- `#0891B2` Accent —— 次要强调（如「引用来源」「知识点标签」）
- `#DC2626` Destructive —— 错误与危险操作（判题失败、删除）
- 成功态沿用 Element Plus 默认绿，不额外定义

---

## 3. 字体

- **字体族**：Inter（回退 `-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif`）
- **字重**：400 / 600 / 700 / 800
- **中文字号**：正文 14px，次级 13px，标题 18 / 22 / 28px
- **行高**：正文 1.6，标题 1.3

> 演示环境可能无外网，字体加载失败须能优雅回退到系统字体，不得出现空白。

---

## 4. 间距与圆角

| 项 | 值 |
|---|---|
| 基础间距单位 | 4px，按 4 / 8 / 12 / 16 / 24 / 32 递进 |
| 页面外边距 | 24px（≥1024px）、16px（<768px） |
| 卡片内边距 | 16px |
| 组件圆角 | 8px（按钮/输入框）、12px（卡片）、16px（弹窗） |
| 组件密度 | 默认（Element Plus `default` size），不做紧凑化 |

---

## 5. 交互

- 所有可点击元素必须有 `cursor: pointer`
- Hover 过渡 150–300ms 平滑
- 键盘导航必须有可见 focus 态（使用 `--color-ring`）
- 尊重 `prefers-reduced-motion`：流式打字动画在减少动效下改为直接显示

---

## 6. Vue 实现规范

来自 `uiuxpromax` 的 vue stack 规范（verified 2026-08-13，vue 3.5.x）：

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

---

## 7. 交付前检查清单

每个页面完成时必须逐条自查：

- [ ] 不使用 emoji 充当图标（一律用 SVG 图标：Heroicons / Lucide / Element Plus Icons）
- [ ] 所有可点击元素有 `cursor: pointer`
- [ ] Hover 态过渡在 150–300ms
- [ ] 亮色模式文字对比度 ≥ 4.5:1
- [ ] 键盘导航 focus 态可见
- [ ] `prefers-reduced-motion` 已尊重
- [ ] 响应式断点 375 / 768 / 1024 / 1440px 均无溢出
- [ ] 路由组件已懒加载
- [ ] `vue-tsc --noEmit` 无类型错误
