<script setup lang="ts">
import * as adminApi from '@/api/admin'
import { usePagedList } from '@/composables/usePagedList'
import type { LogOut } from '@/types/admin'
import { reactive } from 'vue'
import { UiAlert, UiButton, UiCard, UiDatePicker, UiIcon, UiInput, UiPagination } from '@/ui'

/**
 * 系统日志页（spec §6.2 admin 行 / 裁定 8，P6 Task 11）。
 *
 * 页面说明文案（裁定 8）：审计日志记录管理操作与关键行为留痕，仅可查询、
 * 不可修改或删除。
 */

const filters = reactive({
  action: '',
  userId: '',
  start: '',
  end: '',
  pageSize: 20,
})

const list = usePagedList<LogOut>(async (page, pageSize) => {
  const { data } = await adminApi.listAdminLogs({
    action: filters.action.trim() || undefined,
    userId: filters.userId.trim() || undefined,
    start: filters.start || undefined,
    end: filters.end || undefined,
    page,
    pageSize,
  })
  return { items: data.data?.items ?? [], total: data.data?.total ?? 0 }
})

function search() {
  list.reset()
}

function onPageSize(size: number) {
  filters.pageSize = size
  list.reset()
}

/** UTC 直读，不做本地化换算 —— 演示机上标了时区反而容易误读。 */
function formatTime(iso: string): string {
  return `${iso.slice(0, 16).replace('T', ' ')} UTC`
}

/** detail 是 JSON：管理页直接展示序列化文本即可。 */
function formatDetail(detail: Record<string, unknown> | null): string {
  if (!detail) return '—'
  return JSON.stringify(detail)
}

list.load()
</script>

<template>
  <div class="flex flex-col gap-4">
    <UiAlert
      variant="info"
      title="审计日志"
      description="记录管理操作与关键行为留痕，仅可查询、不可修改或删除。"
    />

    <UiCard :padded="false">
      <div class="flex flex-wrap items-center gap-2 border-b border-line p-3">
        <UiInput
          v-model="filters.action"
          placeholder="操作类型（精确匹配，如 admin_user_delete）"
          class="w-[240px]"
          @keyup.enter="search"
        />
        <UiInput v-model="filters.userId" placeholder="用户 ID（精确匹配）" class="w-[200px]" @keyup.enter="search" />
        <UiDatePicker v-model="filters.start" placeholder="开始日期" />
        <UiDatePicker v-model="filters.end" placeholder="结束日期" />
        <UiButton @click="search">
          <UiIcon name="Search" :size="14" />查询
        </UiButton>
      </div>

      <div v-loading="list.loading.value" class="overflow-auto">
        <table class="w-full text-sm">
          <thead class="text-xs text-muted-ink">
            <tr>
              <th class="px-3 py-2 text-left font-medium">时间</th>
              <th class="px-3 py-2 text-left font-medium">操作</th>
              <th class="px-3 py-2 text-left font-medium">用户 ID</th>
              <th class="px-3 py-2 text-left font-medium">对象类型</th>
              <th class="px-3 py-2 text-left font-medium">对象 ID</th>
              <th class="px-3 py-2 text-left font-medium">详情</th>
              <th class="px-3 py-2 text-left font-medium">请求 ID</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-line">
            <tr v-for="row in list.items.value" :key="row.id" class="hover:bg-softer">
              <td class="px-3 py-2 whitespace-nowrap text-muted-ink">{{ formatTime(row.created_at) }}</td>
              <td class="px-3 py-2 font-mono text-xs">{{ row.action }}</td>
              <td class="px-3 py-2 text-xs text-muted-ink">{{ row.user_id ?? '—' }}</td>
              <td class="px-3 py-2 text-xs text-muted-ink">{{ row.target_type ?? '—' }}</td>
              <td class="px-3 py-2 text-xs text-muted-ink">{{ row.target_id ?? '—' }}</td>
              <td class="max-w-[320px] px-3 py-2 text-xs break-all text-muted-ink">{{ formatDetail(row.detail) }}</td>
              <td class="px-3 py-2 font-mono text-xs text-muted-ink">{{ row.request_id ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="p-3">
        <UiPagination
          :page="list.page.value"
          :total="list.total.value"
          :page-size="filters.pageSize"
          layout="total, sizes, prev, pager, next"
          @update:page="list.goto"
          @update:page-size="onPageSize"
        />
      </div>
    </UiCard>
  </div>
</template>
