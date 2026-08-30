import { ACCESS_KEY } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { createRouter, createWebHashHistory } from 'vue-router'

/**
 * 路由组件一律懒加载（frontend/docs/ui-baseline.md §6，Medium 严重度）。
 * 管理端路由另加 `requiresAdmin`，由守卫在渲染前拦下。
 */
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', component: () => import('@/views/LoginView.vue') },
    {
      path: '/',
      component: () => import('@/components/AppShell.vue'),
      meta: { requiresAuth: true },
      children: [
        { path: '', redirect: '/chat' },
        { path: 'chat', component: () => import('@/views/student/ChatView.vue') },
        {
          path: 'code',
          component: () => import('@/views/student/CodeReviewView.vue'),
        },
        {
          path: 'knowledge',
          component: () => import('@/views/student/KnowledgeSearchView.vue'),
        },
        {
          path: 'admin/knowledge',
          component: () => import('@/views/admin/KnowledgeAdminView.vue'),
          meta: { requiresAdmin: true },
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/chat' },
  ],
})

router.beforeEach(async (to) => {
  if (!to.meta.requiresAuth) return true
  if (!localStorage.getItem(ACCESS_KEY)) return { path: '/login' }

  const store = useAuthStore()
  if (!store.user) {
    try {
      await store.fetchMe()
    } catch {
      return { path: '/login' }
    }
  }
  if (to.meta.requiresAdmin && !store.isAdmin) return { path: '/chat' }
  return true
})

export default router
