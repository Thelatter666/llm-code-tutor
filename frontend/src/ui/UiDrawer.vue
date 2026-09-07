<script setup lang="ts">
/** 抽屉：封装 el-drawer；移动端导航抽屉使用 */
import { ElDrawer } from 'element-plus'
</script>
<template>
  <ElDrawer v-bind="$attrs">
    <slot />
  </ElDrawer>
</template>
