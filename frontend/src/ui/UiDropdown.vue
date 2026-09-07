<script setup lang="ts">
/**
 * 下拉菜单：薄封装 Element Plus el-dropdown，对外保持稳定的 #default / #menu 插槽。
 * 后续迁 shadcn-vue DropdownMenu 时只改本文件。
 */
import { ElDropdown, ElDropdownMenu } from 'element-plus'
</script>

<template>
  <ElDropdown v-bind="$attrs" trigger="click">
    <slot />
    <template #dropdown>
      <ElDropdownMenu>
        <slot name="menu" />
      </ElDropdownMenu>
    </template>
  </ElDropdown>
</template>
