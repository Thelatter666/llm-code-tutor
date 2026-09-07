<script setup lang="ts">
import * as adminApi from '@/api/admin'
import type { AntiPlagiarismStatsOut } from '@/types/admin'
import { onMounted, ref } from 'vue'
import { UiAlert, UiButton, UiCard, UiIcon } from '@/ui'

/**
 * 防抄袭统计页（spec §7.4，P6 Task 11）。
 *
 * 裁定 8 / P2 偏离 4 的页面口径（必须写明，不得改后端）：
 * **统计口径：仅统计学生（role=user）发起的答疑请求**；
 * 拦截率 = 触发底线次数 / 总请求数，**是度量口径，不是抄袭检出能力**。
 */

const MODE_LABELS: Record<string, string> = {
  strict: '严格',
  guided: '引导（默认）',
  loose: '宽松',
  all: '全部档位',
}

const data = ref<AntiPlagiarismStatsOut | null>(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const { data: resp } = await adminApi.getAntiPlagiarismStats()
    data.value = resp.data
  } finally {
    loading.value = false
  }
}

function blockRateText(total: number, blocked: number, rate: number): string {
  if (!total) return '暂无数据'
  return `${blocked} / ${total}（${(rate * 100).toFixed(2)}%）`
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="flex flex-col gap-4">
    <UiAlert
      variant="info"
      title="统计口径说明（重要）"
      description="仅统计学生（role=user）发起的答疑请求；拦截率 = 触发防抄袭底线次数 / 总请求数，是度量口径，不是抄袭检出能力。"
    />

    <UiCard title="各档位统计" :padded="false">
      <table class="w-full text-sm">
        <thead class="text-xs text-muted-ink">
          <tr>
            <th class="px-3 py-2 text-left font-medium">档位</th>
            <th class="px-3 py-2 text-left font-medium">总请求数</th>
            <th class="px-3 py-2 text-left font-medium">触发底线次数</th>
            <th class="px-3 py-2 text-left font-medium">拦截率</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-line">
          <tr v-for="row in data?.items ?? []" :key="row.mode">
            <td class="px-3 py-2">{{ MODE_LABELS[row.mode] ?? row.mode }}</td>
            <td class="px-3 py-2 text-muted-ink">{{ row.total }}</td>
            <td class="px-3 py-2 text-muted-ink">{{ row.blocked }}</td>
            <td class="px-3 py-2">{{ blockRateText(row.total, row.blocked, row.block_rate) }}</td>
          </tr>
        </tbody>
      </table>
    </UiCard>

    <UiCard v-if="data" :title="`合计（${MODE_LABELS[data.overall.mode]}）`">
      <p class="m-0 text-2xl font-bold text-brand">{{ blockRateText(data.overall.total, data.overall.blocked, data.overall.block_rate) }}</p>
    </UiCard>

    <div>
      <UiButton variant="secondary" @click="load">
        <UiIcon name="RotateCcw" :size="14" />刷新
      </UiButton>
    </div>
  </div>
</template>
