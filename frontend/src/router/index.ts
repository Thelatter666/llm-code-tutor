import { ACCESS_KEY } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { createRouter, createWebHashHistory } from 'vue-router'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', component: () => import('@/views/LoginView.vue') },
    { path: '/', component: () => import('@/views/HomeView.vue'), meta: { requiresAuth: true } },
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
  return true
})

export default router
