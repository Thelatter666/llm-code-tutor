<script setup lang="ts">
/**
 * 告警条：info / warning / error / success。
 * 纯 Tailwind（不依赖 el-alert），配色走基调语义色 + Tailwind 默认柔和色阶。
 */
import { computed } from 'vue'
import { UiIcon } from '@/ui'

const props = withDefaults(
  defineProps<{
    variant?: 'info' | 'warning' | 'error' | 'success'
    title?: string
    description?: string
    closable?: boolean
  }>(),
  { variant: 'info', closable: false },
)

const TONE = {
  info: { cls: 'border-line bg-softer text-ink', icon: 'Info' },
  warning: { cls: 'border-amber-200 bg-amber-50 text-amber-800', icon: 'AlertTriangle' },
  error: { cls: 'border-red-200 bg-red-50 text-red-700', icon: 'CircleAlert' },
  success: { cls: 'border-emerald-200 bg-emerald-50 text-emerald-700', icon: 'CircleCheck' },
} as const

const tone = computed(() => TONE[props.variant])
</script>

<template>
  <div class="flex gap-3 rounded-panel border px-4 py-3 text-sm" :class="tone.cls" role="alert">
    <UiIcon :name="tone.icon" :size="16" class="mt-0.5 shrink-0" />
    <div class="min-w-0 flex-1">
      <p v-if="title" class="font-semibold">{{ title }}</p>
      <p v-if="description" class="mt-0.5 opacity-90">{{ description }}</p>
      <slot />
    </div>
  </div>
</template>
