<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'

const auth = useAuthStore()
const router = useRouter()

async function onLogout() {
  await auth.doLogout()
  router.push('/login')
}
</script>

<template>
  <div class="home">
    <header class="home__bar">
      <span class="home__user">
        当前用户：{{ auth.user?.username }}（{{ auth.user?.role }}）
      </span>
      <el-button link @click="onLogout">退出登录</el-button>
    </header>
    <el-empty description="P0 基座已就绪，功能模块将在后续批次接入" />
  </div>
</template>

<style scoped>
.home__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  background: var(--color-card);
  border-bottom: 1px solid var(--color-border);
}

.home__user {
  color: var(--color-muted-foreground);
}
</style>
