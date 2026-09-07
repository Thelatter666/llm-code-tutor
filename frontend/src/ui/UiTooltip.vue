<script setup lang="ts">
/** Tooltip：封装 el-tooltip，后续迁 shadcn-vue Tooltip 只改本文件 */
import { ElTooltip } from 'element-plus'
</script>
<template>
  <ElTooltip v-bind="$attrs">
    <template v-if="$slots.content" #content>
      <slot name="content" />
    </template>
    <slot />
  </ElTooltip>
</template>
