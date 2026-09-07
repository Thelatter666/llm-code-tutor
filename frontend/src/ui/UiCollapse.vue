<script setup lang="ts">
/** 折叠面板：封装 el-collapse，条目以 props 传入（页面不接触 el-collapse-item） */
import { ElCollapse, ElCollapseItem } from 'element-plus'

export interface CollapseItem {
  name: string
  title: string
}
const props = withDefaults(defineProps<{ items?: CollapseItem[] }>(), { items: () => [] })
</script>

<template>
  <ElCollapse v-bind="$attrs">
    <ElCollapseItem v-for="item in props.items" :key="item.name" :name="item.name" :title="item.title">
      <slot :name="item.name" />
    </ElCollapseItem>
    <slot />
  </ElCollapse>
</template>
