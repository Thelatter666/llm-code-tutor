<script setup lang="ts">
import * as adminApi from '@/api/admin'
import { useConfirm } from '@/composables/useConfirm'
import { useNotify } from '@/composables/useNotify'
import { usePagedList } from '@/composables/usePagedList'
import type { AdminUserOut } from '@/types/admin'
import { reactive, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { UiBadge, UiButton, UiCard, UiDialog, UiIcon, UiInput, UiSelect } from '@/ui'

/**
 * 用户管理页（spec §6.2 admin 行 / §8.9，P6 Task 9）。
 *
 * 两条口径：
 * 1. **软删除是日常路径**：停用保留全部数据（列表里仍可见，登录/旧 token 立即 4030）；
 * 2. **硬删除不可恢复**：级联清除会话/消息/提交/错题条目/代码会话/代码分析/代码运行，
 *    但审计日志一律保留 —— 确认文案必须如实说明。
 * 自我操作（改自己 role/status、删自己）由后端 4220 拦截，错误消息直接展示。
 */

const auth = useAuthStore()
const notify = useNotify()
const confirm = useConfirm()

const filters = reactive({
  q: '',
  role: '' as 'student' | 'admin' | '',
  status: '' as 'active' | 'disabled' | '',
  pageSize: 10,
})

const list = usePagedList<AdminUserOut>(async (page, pageSize) => {
  const { data } = await adminApi.listAdminUsers({
    q: filters.q || undefined,
    role: filters.role || undefined,
    status: filters.status || undefined,
    page,
    pageSize,
  })
  return { items: data.data?.items ?? [], total: data.data?.total ?? 0 }
}, filters.pageSize)

function search() {
  list.reset()
}

function onPageSize(size: number) {
  filters.pageSize = size
  search()
}

/** UTC 直读，不做本地化换算 —— 演示机上标了时区反而容易误读。 */
function formatTime(iso: string | null): string {
  if (!iso) return '—'
  return `${iso.slice(0, 16).replace('T', ' ')} UTC`
}

const ROLE_OPTIONS = [
  { label: '学生', value: 'student' },
  { label: '管理员', value: 'admin' },
]
const STATUS_OPTIONS = [
  { label: '正常', value: 'active' },
  { label: '已停用', value: 'disabled' },
]

// ---------------------------------------------------------------- 新建

const createDialog = ref(false)
const creating = ref(false)
const createForm = reactive({
  username: '',
  email: '',
  password: '',
  role: 'student' as 'student' | 'admin',
})

function openCreate() {
  Object.assign(createForm, { username: '', email: '', password: '', role: 'student' })
  createDialog.value = true
}

async function submitCreate() {
  if (!createForm.username.trim() || !createForm.email.trim() || !createForm.password) {
    notify.warning('请完整填写用户名、邮箱与密码')
    return
  }
  creating.value = true
  try {
    await adminApi.createAdminUser({ ...createForm })
    notify.success('用户已创建')
    createDialog.value = false
    await list.load()
  } catch {
    // 错误消息已由拦截器弹出
  } finally {
    creating.value = false
  }
}

// ---------------------------------------------------------------- 编辑 / 停用 / 启用

const editDialog = ref(false)
const editing = ref(false)
const editForm = reactive({ id: '', username: '', email: '', role: 'student', status: 'active', password: '' })

function openEdit(row: AdminUserOut) {
  Object.assign(editForm, {
    id: row.id,
    username: row.username,
    email: row.email,
    role: row.role,
    status: row.status,
    password: '',
  })
  editDialog.value = true
}

async function submitEdit() {
  const body: Record<string, string> = {}
  // email 恒回传：后端对「未变更」会跳过查重，不会误伤
  if (editForm.email) body.email = editForm.email
  if (editForm.role) body.role = editForm.role
  if (editForm.status) body.status = editForm.status
  if (editForm.password) body.password = editForm.password
  if (!Object.keys(body).length) {
    notify.warning('没有要保存的变更')
    return
  }
  editing.value = true
  try {
    await adminApi.updateAdminUser(editForm.id, body)
    notify.success('已保存')
    editDialog.value = false
    await list.load()
  } catch {
    // 自停用/自降权等 4220 消息由拦截器弹出
  } finally {
    editing.value = false
  }
}

/** 停用（软删除，日常路径）：保留全部数据；状态切换统一走编辑弹窗的保存。 */
async function toggleStatus(row: AdminUserOut) {
  const target = row.status === 'active' ? 'disabled' : 'active'
  const actionText = target === 'disabled' ? '停用' : '启用'
  const confirmed = await confirm(
    target === 'disabled'
      ? `停用后「${row.username}」将无法登录，已有登录态立即失效；数据全部保留，可随时重新启用。`
      : `重新启用「${row.username}」，恢复登录能力。`,
    `${actionText}用户`,
  )
  if (!confirmed) return
  try {
    await adminApi.updateAdminUser(row.id, { status: target })
    notify.success(`已${actionText}`)
    await list.load()
  } catch {
    // 后端 4220（自停用等）消息由拦截器弹出
  }
}

// ---------------------------------------------------------------- 硬删除

async function removeUser(row: AdminUserOut) {
  if (row.id === auth.user?.id) {
    notify.warning('不能删除当前登录的管理员')
    return
  }
  const confirmed = await confirm(
    `硬删除「${row.username}」将级联清除其全部会话、消息、提交、错题条目、代码会话、代码分析、代码运行记录，且不可恢复；审计日志一律保留。`,
    '硬删除用户',
  )
  if (!confirmed) return
  try {
    await adminApi.deleteAdminUser(row.id)
    notify.success('用户已硬删除')
    await list.load()
  } catch {
    // 后端 4220（末位管理员等）消息由拦截器弹出
  }
}

list.load()
</script>

<template>
  <div class="flex flex-col gap-4">
    <UiCard :padded="false">
      <div class="flex flex-wrap items-center gap-2 border-b border-line p-3">
        <UiInput v-model="filters.q" placeholder="搜索用户名 / 邮箱" class="w-[240px]" @keyup.enter="search" />
        <UiSelect v-model="filters.role" :options="ROLE_OPTIONS" placeholder="全部角色" clearable class="w-[140px]" @update:model-value="search" />
        <UiSelect v-model="filters.status" :options="STATUS_OPTIONS" placeholder="全部状态" clearable class="w-[140px]" @update:model-value="search" />
        <UiButton variant="secondary" @click="search">
          <UiIcon name="RotateCcw" :size="14" />刷新
        </UiButton>
        <UiButton @click="openCreate">
          <UiIcon name="Plus" :size="14" />新建用户
        </UiButton>
      </div>

      <div v-loading="list.loading.value" class="overflow-auto">
        <table class="w-full text-sm">
          <thead class="text-xs text-muted-ink">
            <tr>
              <th class="px-3 py-2 text-left font-medium">用户名</th>
              <th class="px-3 py-2 text-left font-medium">邮箱</th>
              <th class="px-3 py-2 text-left font-medium">角色</th>
              <th class="px-3 py-2 text-left font-medium">状态</th>
              <th class="px-3 py-2 text-left font-medium">创建时间</th>
              <th class="px-3 py-2 text-left font-medium">最近登录</th>
              <th class="px-3 py-2 text-left font-medium">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-line">
            <tr v-for="row in list.items.value" :key="row.id" class="hover:bg-softer">
              <td class="px-3 py-2 font-medium text-ink">{{ row.username }}</td>
              <td class="px-3 py-2 text-muted-ink">{{ row.email }}</td>
              <td class="px-3 py-2">
                <UiBadge :variant="row.role === 'admin' ? 'warning' : 'primary'">
                  {{ row.role === 'admin' ? '管理员' : '学生' }}
                </UiBadge>
              </td>
              <td class="px-3 py-2">
                <UiBadge :variant="row.status === 'active' ? 'success' : 'danger'">
                  {{ row.status === 'active' ? '正常' : '已停用' }}
                </UiBadge>
              </td>
              <td class="px-3 py-2 whitespace-nowrap text-muted-ink">{{ formatTime(row.created_at) }}</td>
              <td class="px-3 py-2 whitespace-nowrap text-muted-ink">{{ formatTime(row.last_login_at) }}</td>
              <td class="px-3 py-2">
                <div class="flex flex-wrap gap-1">
                  <UiButton variant="link" size="sm" @click="openEdit(row)">编辑</UiButton>
                  <UiButton
                    variant="link"
                    size="sm"
                    :disabled="row.id === auth.user?.id"
                    @click="toggleStatus(row)"
                  >
                    {{ row.status === 'active' ? '停用' : '启用' }}
                  </UiButton>
                  <UiButton variant="link" size="sm" :disabled="row.id === auth.user?.id" @click="removeUser(row)">
                    硬删除
                  </UiButton>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="p-3">
        <UiPagination
          :page="list.page.value"
          :total="list.total.value"
          :page-size="filters.pageSize"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          @update:page="list.goto"
          @update:page-size="onPageSize"
        />
      </div>
    </UiCard>

    <UiDialog v-model="createDialog" title="新建用户" width="420px">
      <form class="flex flex-col gap-3" @submit.prevent>
        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">用户名</label>
          <UiInput v-model="createForm.username" />
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">邮箱</label>
          <UiInput v-model="createForm.email" type="email" />
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">密码</label>
          <UiInput v-model="createForm.password" type="password" placeholder="至少 8 位" />
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">角色</label>
          <UiSelect v-model="createForm.role" :options="ROLE_OPTIONS" />
        </div>
      </form>
      <template #footer>
        <UiButton variant="secondary" @click="createDialog = false">取消</UiButton>
        <UiButton :loading="creating" @click="submitCreate">创建</UiButton>
      </template>
    </UiDialog>

    <UiDialog v-model="editDialog" title="编辑用户" width="420px">
      <form class="flex flex-col gap-3" @submit.prevent>
        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">用户名</label>
          <UiInput :model-value="editForm.username" disabled />
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">邮箱</label>
          <UiInput v-model="editForm.email" type="email" />
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">角色</label>
          <UiSelect v-model="editForm.role" :options="ROLE_OPTIONS" :disabled="editForm.id === auth.user?.id" />
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">状态</label>
          <UiSelect v-model="editForm.status" :options="STATUS_OPTIONS" :disabled="editForm.id === auth.user?.id" />
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">重置密码</label>
          <UiInput v-model="editForm.password" type="password" placeholder="留空则不修改" />
        </div>
      </form>
      <template #footer>
        <UiButton variant="secondary" @click="editDialog = false">取消</UiButton>
        <UiButton :loading="editing" @click="submitEdit">保存</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
