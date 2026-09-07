<script setup lang="ts">
/** 轻量分隔线；纯 Tailwind，无 shadcn 依赖 */
withDefaults(defineProps<{ orientation?: 'horizontal' | 'vertical' }>(), {
  orientation: 'horizontal',
})
</script>
<template>
  <div
    role="separator"
    :class="orientation === 'horizontal' ? 'h-px w-full bg-line' : 'w-px h-full bg-line'"
  />
</template>
