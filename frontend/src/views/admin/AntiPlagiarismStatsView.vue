<script setup lang="ts">
import * as adminApi from '@/api/admin'
import type { AntiPlagiarismStatsOut } from '@/types/admin'
import { RefreshLeft } from '@element-plus/icons-vue'
import { onMounted, ref } from 'vue'

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
  <div v-loading="loading" class="stats-page">
    <el-alert
      type="info"
      show-icon
      :closable="false"
      class="stats-page__notice"
      title="统计口径说明（重要）"
      description="仅统计学生（role=user）发起的答疑请求；拦截率 = 触发防抄袭底线次数 / 总请求数，是度量口径，不是抄袭检出能力。"
    />

    <el-table :data="data?.items ?? []" class="stats-page__table">
      <el-table-column label="档位" width="180">
        <template #default="{ row }">{{ MODE_LABELS[row.mode] ?? row.mode }}</template>
      </el-table-column>
      <el-table-column label="总请求数" prop="total" width="140" />
      <el-table-column label="触发底线次数" prop="blocked" width="160" />
      <el-table-column label="拦截率">
        <template #default="{ row }">{{ blockRateText(row.total, row.blocked, row.block_rate) }}</template>
      </el-table-column>
    </el-table>

    <div v-if="data" class="stats-page__overall">
      <h3 class="stats-page__title">合计（{{ MODE_LABELS[data.overall.mode] }}）</h3>
      <p>{{ blockRateText(data.overall.total, data.overall.blocked, data.overall.block_rate) }}</p>
    </div>

    <el-button class="stats-page__refresh" :icon="RefreshLeft" @click="load">刷新</el-button>
  </div>
</template>

<style scoped>
.stats-page__notice {
  margin-bottom: var(--space-4);
}

.stats-page__overall {
  margin-top: var(--space-4);
  padding: var(--space-4);
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
}

.stats-page__title {
  margin: 0 0 var(--space-2);
  font-size: 15px;
}

.stats-page__refresh {
  margin-top: var(--space-4);
}
</style>
