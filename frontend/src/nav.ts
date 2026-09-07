import type { Component } from 'vue'

/** 导航分组：学习端 + 管理端 */
export type NavGroup = 'learn' | 'admin'

export interface NavItem {
  /** 路由 hash 路径，如 '/chat' */
  path: string
  /** 显示文案 */
  label: string
  /** lucide-vue-next 的图标组件名（PascalCase），由 UiIcon 解析 */
  icon: string
  group: NavGroup
  /** 仅管理员可见 */
  adminOnly?: boolean
}

export const NAV: NavItem[] = [
  { path: '/chat', label: 'AI 答疑对话', icon: 'MessageSquare', group: 'learn' },
  { path: '/code', label: '代码解析辅导', icon: 'Wand2', group: 'learn' },
  { path: '/editor', label: '在线代码编辑器', icon: 'Code', group: 'learn' },
  { path: '/knowledge', label: '知识库检索', icon: 'Search', group: 'learn' },
  { path: '/exercises', label: '习题练习', icon: 'BookOpen', group: 'learn' },
  { path: '/mistakes', label: '错题本', icon: 'NotebookPen', group: 'learn' },

  { path: '/admin/knowledge', label: '知识库管理', icon: 'FileText', group: 'admin', adminOnly: true },
  { path: '/admin/exercises', label: '习题管理', icon: 'ListChecks', group: 'admin', adminOnly: true },
  { path: '/admin/users', label: '用户管理', icon: 'User', group: 'admin', adminOnly: true },
  { path: '/admin/model-config', label: '模型配置', icon: 'Settings', group: 'admin', adminOnly: true },
  { path: '/admin/logs', label: '系统日志', icon: 'List', group: 'admin', adminOnly: true },
  { path: '/admin/overview', label: '仪表盘', icon: 'LayoutDashboard', group: 'admin', adminOnly: true },
  { path: '/admin/anti-plagiarism', label: '防抄袭统计', icon: 'BarChart3', group: 'admin', adminOnly: true },
]

export const GROUP_LABELS: Record<NavGroup, string> = {
  learn: '学习',
  admin: '管理',
}
