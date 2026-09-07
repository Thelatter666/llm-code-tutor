<script setup lang="ts">
/** 进度条：封装 el-progress（知识库索引进度等） */
import { ElProgress } from 'element-plus'

withDefaults(defineProps<{ percentage: number; textInside?: boolean; strokeWidth?: number }>(), {
  textInside: true,
  strokeWidth: 14,
})
</script>

<template>
  <ElProgress v-bind="$attrs" :percentage="percentage" :text-inside="textInside" :stroke-width="strokeWidth" />
</template>
