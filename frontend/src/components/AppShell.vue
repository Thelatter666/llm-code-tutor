<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
import { Document, ChatDotRound, MagicStick, Search } from '@element-plus/icons-vue'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

interface NavItem {
  path: string
  label: string
  icon: typeof Document
  adminOnly?: boolean
}

const NAV: NavItem[] = [
  { path: '/chat', label: 'AI 答疑对话', icon: ChatDotRound },
  { path: '/code', label: '代码解析辅导', icon: MagicStick },
  { path: '/knowledge', label: '知识库检索', icon: Search },
  { path: '/admin/knowledge', label: '知识库管理', icon: Document, adminOnly: true },
]

const items = computed(() => NAV.filter((i) => !i.adminOnly || auth.isAdmin))

async function onLogout() {
  await auth.doLogout()
  router.push('/login')
}
</script>

<template>
  <div class="shell">
    <header class="shell__bar">
      <div class="shell__brand">
        <span class="shell__mark" aria-hidden="true"></span>
        智能编程教学辅助系统
      </div>
      <div class="shell__user">
        <span class="shell__name">{{ auth.user?.username }}</span>
        <el-tag size="small" :type="auth.isAdmin ? 'warning' : 'primary'" effect="plain">
          {{ auth.isAdmin ? '管理员' : '学生' }}
        </el-tag>
        <el-button link @click="onLogout">退出登录</el-button>
      </div>
    </header>

    <div class="shell__body">
      <nav class="shell__nav" aria-label="功能导航">
        <button
          v-for="item in items"
          :key="item.path"
          type="button"
          class="shell__link"
          :class="{ 'shell__link--active': route.path.startsWith(item.path) }"
          @click="router.push(item.path)"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </button>
      </nav>

      <main class="shell__main">
        <router-view />
      </main>
    </div>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--color-background);
}

.shell__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--page-gutter);
  background: var(--color-card);
  border-bottom: 1px solid var(--color-border);
}

.shell__brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 18px;
  font-weight: 700;
  color: var(--color-foreground);
}

.shell__mark {
  width: 10px;
  height: 22px;
  border-radius: 999px;
  background: linear-gradient(180deg, var(--color-primary), var(--color-accent));
}

.shell__user {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.shell__name {
  color: var(--color-muted-foreground);
}

.shell__body {
  display: flex;
  flex: 1;
  min-height: 0;
}

.shell__nav {
  width: 200px;
  flex-shrink: 0;
  padding: var(--space-4) var(--space-3);
  background: var(--color-card);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.shell__link {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: none;
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--color-foreground);
  font-size: 14px;
  text-align: left;
  cursor: pointer;
  transition: background 200ms ease, color 200ms ease;
}

.shell__link:hover {
  background: var(--color-muted);
}

.shell__link:focus-visible {
  outline: 2px solid var(--color-ring);
  outline-offset: 2px;
}

.shell__link--active {
  background: var(--color-muted);
  color: var(--color-primary);
  font-weight: 600;
}

.shell__main {
  flex: 1;
  min-width: 0;
  padding: var(--page-gutter);
  overflow: auto;
}

@media (max-width: 1023px) {
  .shell__nav {
    width: 72px;
  }

  .shell__link span {
    display: none;
  }
}
</style>
