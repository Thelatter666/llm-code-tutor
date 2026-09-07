<script setup lang="ts">
import * as adminApi from '@/api/admin'
import type { OverviewOut } from '@/types/admin'
import { computed, onMounted, ref } from 'vue'
import { UiButton, UiCard, UiIcon } from '@/ui'

/**
 * 仪表盘页（spec §6.2 / 裁定 3 最小集，P6 Task 11）。
 *
 * 展示各实体计数 + 当前模型配置摘要 + 向量化器就绪状态（与 /health 同源）。
 */

const data = ref<OverviewOut | null>(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const { data: resp } = await adminApi.getOverview()
    data.value = resp.data
  } finally {
    loading.value = false
  }
}

onMounted(load)

const cards = computed<Array<{ label: string; value: number | string }>>(() => {
  const d = data.value
  if (!d) return []
  return [
    { label: '用户', value: d.users.total },
    { label: '会话', value: d.conversations },
    { label: '消息', value: d.messages },
    { label: '知识库', value: d.knowledge_bases },
    { label: '文档', value: d.documents },
    { label: '代码会话', value: d.code_sessions },
    { label: '代码分析', value: d.code_analyses },
    { label: '代码运行', value: d.code_runs },
    { label: '已发布习题', value: d.exercises.published },
    { label: '提交', value: d.submissions },
    { label: '未掌握错题', value: d.mistake_entries.unmastered },
    { label: '审计日志', value: d.audit_logs },
  ]
})
</script>

<template>
  <div v-loading="loading" class="flex flex-col gap-4">
    <div class="grid grid-cols-[repeat(auto-fill,minmax(140px,1fr))] gap-3">
      <div
        v-for="card in cards"
        :key="card.label"
        class="rounded-panel border border-line bg-surface p-4 text-center shadow-panel"
      >
        <div class="text-2xl font-bold leading-tight text-brand">{{ card.value }}</div>
        <div class="mt-1 text-sm text-muted-ink">{{ card.label }}</div>
      </div>
    </div>

    <div class="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-4">
      <UiCard title="当前配置">
        <dl class="m-0">
          <div v-for="row in [
            ['LLM 提供方', data?.model_config.provider ?? '—'],
            ['模型', data?.model_config.model ?? '—'],
            ['防抄袭档位', data?.model_config.anti_plagiarism_mode ?? '—'],
            ['配置版本 revision', data?.model_config.revision ?? '—'],
          ]" :key="row[0]" class="flex justify-between border-b border-line py-1 text-sm">
            <dt class="text-muted-ink">{{ row[0] }}</dt>
            <dd class="m-0 font-semibold text-ink">{{ row[1] }}</dd>
          </div>
        </dl>
      </UiCard>

      <UiCard title="向量化器">
        <dl class="m-0">
          <div class="flex justify-between border-b border-line py-1 text-sm">
            <dt class="text-muted-ink">就绪</dt>
            <dd class="m-0 font-semibold" :class="data?.embedder.ready ? 'text-highlight' : 'text-danger'">
              {{ data?.embedder.ready ? '是' : '否（加载中/降级）' }}
            </dd>
          </div>
          <div class="flex justify-between border-b border-line py-1 text-sm">
            <dt class="text-muted-ink">实现</dt>
            <dd class="m-0 font-semibold text-ink">{{ data?.embedder.name ?? '—' }}</dd>
          </div>
          <div class="flex justify-between border-b border-line py-1 text-sm">
            <dt class="text-muted-ink">模型</dt>
            <dd class="m-0 font-semibold text-ink">{{ data?.embedder.model ?? '—' }}</dd>
          </div>
          <div v-if="data?.embedder.error" class="flex justify-between py-1 text-sm">
            <dt class="text-muted-ink">错误</dt>
            <dd class="m-0 font-semibold text-danger">{{ data.embedder.error }}</dd>
          </div>
        </dl>
      </UiCard>

      <UiCard title="用户结构">
        <dl class="m-0">
          <div v-for="row in [
            ['管理员', data?.users.admin ?? 0],
            ['正常状态', data?.users.active ?? 0],
            ['习题草稿', data?.exercises.draft ?? 0],
            ['错题条目', data?.mistake_entries.total ?? 0],
          ]" :key="row[0]" class="flex justify-between border-b border-line py-1 text-sm">
            <dt class="text-muted-ink">{{ row[0] }}</dt>
            <dd class="m-0 font-semibold text-ink">{{ row[1] }}</dd>
          </div>
        </dl>
      </UiCard>
    </div>

    <div>
      <UiButton variant="secondary" @click="load">
        <UiIcon name="RotateCcw" :size="14" />刷新
      </UiButton>
    </div>
  </div>
</template>
