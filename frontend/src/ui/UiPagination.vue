<script setup lang="ts">
/** 分页：封装 el-pagination，支持 sizes 布局与页大小双向绑定 */
import { ElPagination } from 'element-plus'

withDefaults(
  defineProps<{
    page: number
    total: number
    pageSize?: number
    layout?: string
    pageSizes?: number[]
  }>(),
  { pageSize: 20, layout: 'prev, pager, next, total', pageSizes: () => [10, 20, 50, 100] },
)
const emit = defineEmits<{
  'update:page': [value: number]
  'update:pageSize': [value: number]
}>()
</script>

<template>
  <ElPagination
    :current-page="page"
    :total="total"
    :page-size="pageSize"
    :page-sizes="pageSizes"
    :layout="layout"
    @current-change="emit('update:page', $event)"
    @size-change="emit('update:pageSize', $event)"
  />
</template>
