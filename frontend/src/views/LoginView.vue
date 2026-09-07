<script setup lang="ts">
import { useNotify } from '@/composables/useNotify'
import { useAuthStore } from '@/stores/auth'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { UiButton, UiCard, UiInput } from '@/ui'

const router = useRouter()
const auth = useAuthStore()
const notify = useNotify()
const form = ref({ username: '', password: '' })
const loading = ref(false)

async function submit() {
  loading.value = true
  try {
    await auth.doLogin(form.value.username, form.value.password)
    router.push('/')
  } catch (e) {
    notify.error((e as Error).message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="flex h-screen items-center justify-center bg-canvas p-4">
    <UiCard class="w-[380px] shadow-pop">
      <template #header>
        <div class="flex items-center justify-center gap-2">
          <span class="h-5 w-1.5 rounded-pill bg-gradient-to-b from-brand to-highlight" aria-hidden="true" />
          <h2 class="text-lg font-bold text-ink">智能编程教学辅助系统</h2>
        </div>
      </template>

      <form class="flex flex-col gap-3" @submit.prevent="submit">
        <div class="flex flex-col gap-1">
          <label for="username" class="text-sm text-muted-ink">用户名</label>
          <UiInput id="username" v-model="form.username" autocomplete="username" />
        </div>
        <div class="flex flex-col gap-1">
          <label for="password" class="text-sm text-muted-ink">密码</label>
          <UiInput id="password" v-model="form.password" type="password" autocomplete="current-password" />
        </div>
        <UiButton class="mt-1 w-full" type="submit" :loading="loading">登录</UiButton>
      </form>
    </UiCard>
  </div>
</template>
