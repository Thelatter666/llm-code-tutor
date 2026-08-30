import * as authApi from '@/api/auth'
import { ACCESS_KEY, REFRESH_KEY } from '@/api/client'
import type { UserOut } from '@/types/api'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserOut | null>(null)

  const isAdmin = computed(() => user.value?.role === 'admin')
  const isAuthed = computed(() => user.value !== null)

  async function doLogin(username: string, password: string) {
    const { data } = await authApi.login({ username, password })
    if (!data.data) throw new Error('登录失败')
    localStorage.setItem(ACCESS_KEY, data.data.access_token)
    localStorage.setItem(REFRESH_KEY, data.data.refresh_token)
    await fetchMe()
  }

  async function fetchMe() {
    const { data } = await authApi.me()
    user.value = data.data
  }

  async function doLogout() {
    try {
      await authApi.logout()
    } finally {
      localStorage.removeItem(ACCESS_KEY)
      localStorage.removeItem(REFRESH_KEY)
      user.value = null
    }
  }

  return { user, isAdmin, isAuthed, doLogin, fetchMe, doLogout }
})
