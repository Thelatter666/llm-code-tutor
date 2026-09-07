<script setup lang="ts">
/**
 * 应用外壳（P2 重设计）。
 * 仅依赖 @/ui（内部封装 el-*），后续 shadcn-vue 接入只改 @/ui，AppShell 不动。
 */
import { useAuthStore } from '@/stores/auth'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { GROUP_LABELS, NAV, type NavItem, type NavGroup } from '@/nav'
import { UiBadge, UiButton, UiDrawer, UiDropdown, UiDropdownItem, UiIcon, UiTooltip } from '@/ui'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const COLLAPSE_KEY = 'lct.sidebar.collapsed'
const collapsed = ref(localStorage.getItem(COLLAPSE_KEY) === '1')
function toggleCollapse() {
  collapsed.value = !collapsed.value
  localStorage.setItem(COLLAPSE_KEY, collapsed.value ? '1' : '0')
}

const isMobile = ref(false)
const drawerOpen = ref(false)
const onResize = () => {
  isMobile.value = window.innerWidth < 1024
  if (!isMobile.value) drawerOpen.value = false
}
onMounted(() => { onResize(); window.addEventListener('resize', onResize) })
onBeforeUnmount(() => window.removeEventListener('resize', onResize))

const items = computed<NavItem[]>(() => NAV.filter((i) => !i.adminOnly || auth.isAdmin))
const groups = computed<Record<NavGroup, NavItem[]>>(() => {
  const m: Record<NavGroup, NavItem[]> = { learn: [], admin: [] }
  for (const i of items.value) m[i.group].push(i)
  return m
})
const showLearn = computed(() => groups.value.learn.length > 0)
const showAdmin = computed(() => groups.value.admin.length > 0)

function go(path: string) {
  if (isMobile.value) drawerOpen.value = false
  router.push(path)
}
async function onLogout() {
  await auth.doLogout()
  router.push('/login')
}
function isActive(path: string) {
  return route.path === path || route.path.startsWith(path + '/')
}

const navBtnBase =
  'flex w-full items-center gap-3 rounded-ctl px-3 py-2 text-sm text-ink transition-colors hover:bg-softer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand'
</script>

<template>
  <a href="#main" class="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-ctl focus:bg-brand focus:px-3 focus:py-2 focus:text-brand-fg">跳到主内容</a>

  <div class="flex h-screen flex-col bg-canvas text-ink">
    <header class="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-line bg-surface px-6">
      <div class="flex items-center gap-3">
        <UiButton v-if="isMobile" variant="ghost" size="icon" aria-label="打开菜单" @click="drawerOpen = true">
          <UiIcon name="Menu" :size="20" />
        </UiButton>
        <UiButton v-else variant="ghost" size="icon" :aria-label="collapsed ? '展开侧栏' : '收起侧栏'" @click="toggleCollapse">
          <UiIcon :name="collapsed ? 'PanelLeftOpen' : 'PanelLeftClose'" :size="20" />
        </UiButton>
        <div class="flex items-center gap-2 text-lg font-bold">
          <span class="h-5 w-1.5 rounded-pill bg-gradient-to-b from-brand to-highlight" aria-hidden="true" />
          智能编程教学辅助系统
        </div>
      </div>
      <UiDropdown>
        <UiButton variant="ghost">
          <span class="text-muted-ink">{{ auth.user?.username }}</span>
          <UiBadge :variant="auth.isAdmin ? 'warning' : 'primary'">{{ auth.isAdmin ? '管理员' : '学生' }}</UiBadge>
          <UiIcon name="ChevronDown" />
        </UiButton>
        <template #menu>
          <UiDropdownItem @click="onLogout">
            <span class="inline-flex items-center gap-2"><UiIcon name="LogOut" :size="14" />退出登录</span>
          </UiDropdownItem>
        </template>
      </UiDropdown>
    </header>

    <div class="flex min-h-0 flex-1">
      <aside
        v-if="!isMobile"
        class="flex shrink-0 flex-col gap-4 border-r border-line bg-surface p-3 transition-[width] duration-base ease-smooth"
        :class="collapsed ? 'w-[72px]' : 'w-60'"
        aria-label="功能导航"
      >
        <template v-if="showLearn">
          <div v-if="!collapsed" class="px-3 py-1 text-xs uppercase tracking-wide text-muted-ink">{{ GROUP_LABELS.learn }}</div>
          <button
            v-for="i in groups.learn"
            :key="i.path"
            type="button"
            :class="[navBtnBase, isActive(i.path) ? 'bg-softer font-semibold text-brand' : '', collapsed ? 'justify-center' : '']"
            :aria-current="isActive(i.path) ? 'page' : undefined"
            @click="go(i.path)"
          >
            <UiTooltip v-if="collapsed" placement="right">
              <UiIcon :name="i.icon" :size="18" />
              <template #content>{{ i.label }}</template>
            </UiTooltip>
            <template v-else>
              <UiIcon :name="i.icon" :size="18" />
              <span>{{ i.label }}</span>
            </template>
          </button>
        </template>

        <template v-if="showAdmin">
          <hr v-if="!collapsed" class="border-line" />
          <div v-if="!collapsed" class="px-3 py-1 text-xs uppercase tracking-wide text-muted-ink">{{ GROUP_LABELS.admin }}</div>
          <button
            v-for="i in groups.admin"
            :key="i.path"
            type="button"
            :class="[navBtnBase, isActive(i.path) ? 'bg-softer font-semibold text-brand' : '', collapsed ? 'justify-center' : '']"
            :aria-current="isActive(i.path) ? 'page' : undefined"
            @click="go(i.path)"
          >
            <UiTooltip v-if="collapsed" placement="right">
              <UiIcon :name="i.icon" :size="18" />
              <template #content>{{ i.label }}</template>
            </UiTooltip>
            <template v-else>
              <UiIcon :name="i.icon" :size="18" />
              <span>{{ i.label }}</span>
            </template>
          </button>
        </template>
      </aside>

      <main id="main" tabindex="-1" class="min-w-0 flex-1 overflow-auto p-6">
        <router-view />
      </main>
    </div>

    <UiDrawer v-if="isMobile" v-model="drawerOpen" direction="ltr" size="240px" :with-header="false">
      <div class="flex flex-col gap-4 p-3">
        <template v-if="showLearn">
          <div class="px-3 py-1 text-xs uppercase tracking-wide text-muted-ink">{{ GROUP_LABELS.learn }}</div>
          <button
            v-for="i in groups.learn"
            :key="i.path"
            type="button"
            :class="[navBtnBase, isActive(i.path) ? 'bg-softer font-semibold text-brand' : '']"
            @click="go(i.path)"
          >
            <UiIcon :name="i.icon" :size="18" />
            <span>{{ i.label }}</span>
          </button>
        </template>
        <template v-if="showAdmin">
          <hr class="border-line" />
          <div class="px-3 py-1 text-xs uppercase tracking-wide text-muted-ink">{{ GROUP_LABELS.admin }}</div>
          <button
            v-for="i in groups.admin"
            :key="i.path"
            type="button"
            :class="[navBtnBase, isActive(i.path) ? 'bg-softer font-semibold text-brand' : '']"
            @click="go(i.path)"
          >
            <UiIcon :name="i.icon" :size="18" />
            <span>{{ i.label }}</span>
          </button>
        </template>
      </div>
    </UiDrawer>
  </div>
</template>
