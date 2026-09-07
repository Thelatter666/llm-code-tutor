<script setup lang="ts">
/** 空态：统一文案与留白，替代 el-empty 与手写 .empty 混用 */
withDefaults(defineProps<{ description?: string; icon?: string }>(), {
  description: '暂无数据',
  icon: 'Inbox',
})
</script>

<template>
  <div class="flex flex-col items-center justify-center gap-2 rounded-panel border border-dashed border-line bg-surface px-4 py-10 text-center">
    <UiIcon :name="icon" :size="24" class="text-muted-ink" />
    <p class="text-sm text-muted-ink">{{ description }}</p>
    <div v-if="$slots.action" class="mt-1">
      <slot name="action" />
    </div>
  </div>
</template>
