<script setup lang="ts">
/**
 * 图标：统一收敛到 lucide-vue-next，禁 emoji。
 * 名称传 PascalCase（如 'MessageSquare'），由 nav.ts 给出。
 */
import * as LucideIcons from 'lucide-vue-next'
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    name: string
    size?: number | string
    strokeWidth?: number
  }>(),
  { size: 16, strokeWidth: 2 },
)

const Cmp = computed(
  () => (LucideIcons as unknown as Record<string, unknown>)[props.name] as never,
)
</script>

<template>
  <component :is="Cmp" :size="size" :stroke-width="strokeWidth" />
</template>
