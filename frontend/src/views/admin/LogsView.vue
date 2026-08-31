<script setup lang="ts">
import * as adminApi from '@/api/admin'
import type { LogOut } from '@/types/admin'
import { RefreshLeft } from '@element-plus/icons-vue'
import { onMounted, reactive, ref } from 'vue'

/**
 * 系统日志页（spec §6.2 admin 行 / 裁定 8，P6 Task 11）。
 *
 * 页面说明文案（裁定 8）：审计日志记录管理操作与关键行为留痕，仅可查询、
 * 不可修改或删除。
 */

const items = ref<LogOut[]>([])
const total = ref(0)
const loading = ref(false)

const filters = reactive({
  action: '',
  userId: '',
  start: '',
  end: '',
  page: 1,
  pageSize: 20,
})

async function load() {
  loading.value = true
  try {
    const { data } = await adminApi.listAdminLogs({
      action: filters.action.trim() || undefined,
      userId: filters.userId.trim() || undefined,
      start: filters.start || undefined,
      end: filters.end || undefined,
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

function formatTime(iso: string): string {
  return `${iso.slice(0, 16).replace('T', ' ')} UTC`
}

/** detail 是 JSON：管理页直接展示序列化文本即可。 */
function formatDetail(detail: Record<string, unknown> | null): string {
  if (!detail) return '—'
  return JSON.stringify(detail)
}

onMounted(load)
</script>

<template>
  <div class="logs-page">
    <el-alert
      type="info"
      show-icon
      :closable="false"
      class="logs-page__notice"
      title="审计日志"
      description="记录管理操作与关键行为留痕，仅可查询、不可修改或删除。"
    />

    <div class="logs-page__toolbar">
      <el-input
        v-model="filters.action"
        placeholder="操作类型（精确匹配，如 admin_user_delete）"
        clearable
        class="logs-page__input"
        @keyup.enter="search"
        @clear="search"
      />
      <el-input
        v-model="filters.userId"
        placeholder="用户 ID（精确匹配）"
        clearable
        class="logs-page__input"
        @keyup.enter="search"
        @clear="search"
      />
      <el-date-picker
        v-model="filters.start"
        type="date"
        value-format="YYYY-MM-DD"
        placeholder="开始日期"
        class="logs-page__date"
      />
      <el-date-picker
        v-model="filters.end"
        type="date"
        value-format="YYYY-MM-DD"
        placeholder="结束日期"
        class="logs-page__date"
      />
      <el-button type="primary" :icon="RefreshLeft" @click="search">查询</el-button>
    </div>

    <el-table v-loading="loading" :data="items" class="logs-page__table">
      <el-table-column label="时间" width="160">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column prop="action" label="操作" width="200" />
      <el-table-column prop="user_id" label="用户 ID" width="180">
        <template #default="{ row }">{{ row.user_id ?? '—' }}</template>
      </el-table-column>
      <el-table-column prop="target_type" label="对象类型" width="130">
        <template #default="{ row }">{{ row.target_type ?? '—' }}</template>
      </el-table-column>
      <el-table-column prop="target_id" label="对象 ID" width="180">
        <template #default="{ row }">{{ row.target_id ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="详情">
        <template #default="{ row }">{{ formatDetail(row.detail) }}</template>
      </el-table-column>
      <el-table-column prop="request_id" label="请求 ID" width="220">
        <template #default="{ row }">{{ row.request_id ?? '—' }}</template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="filters.page"
      v-model:page-size="filters.pageSize"
      :total="total"
      :page-sizes="[10, 20, 50, 100]"
      layout="total, sizes, prev, pager, next"
      class="logs-page__pager"
      @current-change="load"
      @size-change="search"
    />
  </div>
</template>

<style scoped>
.logs-page__notice {
  margin-bottom: var(--space-4);
}

.logs-page__toolbar {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
  flex-wrap: wrap;
}

.logs-page__input {
  width: 240px;
}

.logs-page__date {
  width: 150px;
}

.logs-page__pager {
  margin-top: var(--space-4);
}
</style>
