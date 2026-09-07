<script setup lang="ts">
/** 分页：封装 el-pagination */
import { ElPagination } from 'element-plus'

withDefaults(
  defineProps<{
    page: number
    total: number
    pageSize?: number
    layout?: string
  }>(),
  { pageSize: 20, layout: 'prev, pager, next, total' },
)
const emit = defineEmits<{ 'update:page': [value: number] }>()
</script>

<template>
  <ElPagination
    :current-page="page"
    :total="total"
    :page-size="pageSize"
    :layout="layout"
    @current-change="emit('update:page', $event)"
  />
</template>
