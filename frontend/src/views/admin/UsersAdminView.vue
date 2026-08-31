<script setup lang="ts">
import * as adminApi from '@/api/admin'
import type { AdminUserOut } from '@/types/admin'
import { Delete, Plus, RefreshLeft } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'

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
const items = ref<AdminUserOut[]>([])
const total = ref(0)
const loading = ref(false)

const filters = reactive({
  q: '',
  role: '' as 'student' | 'admin' | '',
  status: '' as 'active' | 'disabled' | '',
  page: 1,
  pageSize: 10,
})

async function load() {
  loading.value = true
  try {
    const { data } = await adminApi.listAdminUsers({
      q: filters.q || undefined,
      role: filters.role || undefined,
      status: filters.status || undefined,
      page: filters.page,
      pageSize: filters.pageSize,
    })
    items.value = data.data?.items ?? []
    total.value = data.data?.total ?? 0
  } finally {
    loading.value = false
  }
}

function search() {
  filters.page = 1
  load()
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  return `${iso.slice(0, 16).replace('T', ' ')} UTC`
}

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
    ElMessage.warning('请完整填写用户名、邮箱与密码')
    return
  }
  creating.value = true
  try {
    await adminApi.createAdminUser({ ...createForm })
    ElMessage.success('用户已创建')
    createDialog.value = false
    await load()
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
    ElMessage.warning('没有要保存的变更')
    return
  }
  editing.value = true
  try {
    await adminApi.updateAdminUser(editForm.id, body)
    ElMessage.success('已保存')
    editDialog.value = false
    await load()
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
  const confirmed = await ElMessageBox.confirm(
    target === 'disabled'
      ? `停用后「${row.username}」将无法登录，已有登录态立即失效；数据全部保留，可随时重新启用。`
      : `重新启用「${row.username}」，恢复登录能力。`,
    `${actionText}用户`,
    { type: 'warning', confirmButtonText: actionText, cancelButtonText: '取消' },
  ).catch(() => null)
  if (!confirmed) return
  try {
    await adminApi.updateAdminUser(row.id, { status: target })
    ElMessage.success(`已${actionText}`)
    await load()
  } catch {
    // 后端 4220（自停用等）消息由拦截器弹出
  }
}

// ---------------------------------------------------------------- 硬删除

async function removeUser(row: AdminUserOut) {
  if (row.id === auth.user?.id) {
    ElMessage.warning('不能删除当前登录的管理员')
    return
  }
  const confirmed = await ElMessageBox.confirm(
    `硬删除「${row.username}」将级联清除其全部会话、消息、提交、错题条目、代码会话、` +
      '代码分析、代码运行记录，且**不可恢复**；审计日志一律保留。',
    '硬删除用户',
    { type: 'error', confirmButtonText: '硬删除', cancelButtonText: '取消' },
  ).catch(() => null)
  if (!confirmed) return
  try {
    await adminApi.deleteAdminUser(row.id)
    ElMessage.success('用户已硬删除')
    await load()
  } catch {
    // 后端 4220（末位管理员等）消息由拦截器弹出
  }
}

onMounted(load)
</script>

<template>
  <div class="users-page">
    <div class="users-page__toolbar">
      <el-input
        v-model="filters.q"
        placeholder="搜索用户名 / 邮箱"
        clearable
        class="users-page__search"
        @keyup.enter="search"
        @clear="search"
      />
      <el-select v-model="filters.role" placeholder="全部角色" clearable class="users-page__select" @change="search">
        <el-option label="学生" value="student" />
        <el-option label="管理员" value="admin" />
      </el-select>
      <el-select v-model="filters.status" placeholder="全部状态" clearable class="users-page__select" @change="search">
        <el-option label="正常" value="active" />
        <el-option label="已停用" value="disabled" />
      </el-select>
      <el-button type="primary" :icon="RefreshLeft" @click="search">刷新</el-button>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建用户</el-button>
    </div>

    <el-table v-loading="loading" :data="items" class="users-page__table">
      <el-table-column prop="username" label="用户名" min-width="120" />
      <el-table-column prop="email" label="邮箱" min-width="200" />
      <el-table-column label="角色" width="100">
        <template #default="{ row }">
          <el-tag :type="row.role === 'admin' ? 'warning' : 'primary'" effect="plain">
            {{ row.role === 'admin' ? '管理员' : '学生' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'danger'" effect="plain">
            {{ row.status === 'active' ? '正常' : '已停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="150">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="最近登录" width="150">
        <template #default="{ row }">{{ formatTime(row.last_login_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button
            link
            :type="row.status === 'active' ? 'danger' : 'success'"
            :disabled="row.id === auth.user?.id"
            @click="toggleStatus(row)"
          >
            {{ row.status === 'active' ? '停用' : '启用' }}
          </el-button>
          <el-button
            link
            type="danger"
            :disabled="row.id === auth.user?.id"
            @click="removeUser(row)"
          >
            硬删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="filters.page"
      v-model:page-size="filters.pageSize"
      :total="total"
      :page-sizes="[10, 20, 50]"
      layout="total, sizes, prev, pager, next"
      class="users-page__pager"
      @current-change="load"
      @size-change="search"
    />

    <el-dialog v-model="createDialog" title="新建用户" width="420px">
      <el-form label-width="80px" @submit.prevent>
        <el-form-item label="用户名"><el-input v-model="createForm.username" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="createForm.email" /></el-form-item>
        <el-form-item label="密码">
          <el-input v-model="createForm.password" type="password" show-password placeholder="至少 8 位" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="createForm.role">
            <el-option label="学生" value="student" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editDialog" title="编辑用户" width="420px">
      <el-form label-width="80px" @submit.prevent>
        <el-form-item label="用户名"><el-input :model-value="editForm.username" disabled /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="editForm.email" /></el-form-item>
        <el-form-item label="角色">
          <el-select v-model="editForm.role" :disabled="editForm.id === auth.user?.id">
            <el-option label="学生" value="student" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="editForm.status" :disabled="editForm.id === auth.user?.id">
            <el-option label="正常" value="active" />
            <el-option label="已停用" value="disabled" />
          </el-select>
        </el-form-item>
        <el-form-item label="重置密码">
          <el-input v-model="editForm.password" type="password" show-password placeholder="留空则不修改" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" :loading="editing" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.users-page__toolbar {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
  flex-wrap: wrap;
}

.users-page__search {
  width: 240px;
}

.users-page__select {
  width: 140px;
}

.users-page__pager {
  margin-top: var(--space-4);
}
</style>
