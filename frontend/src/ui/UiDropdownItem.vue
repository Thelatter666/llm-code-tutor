<script setup lang="ts">
import { ElDropdownItem } from 'element-plus'
</script>
<template>
  <ElDropdownItem v-bind="$attrs">
    <slot />
  </ElDropdownItem>
</template>
