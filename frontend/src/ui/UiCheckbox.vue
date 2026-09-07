<script setup lang="ts">
/** 复选框：封装 el-checkbox */
import { ElCheckbox } from 'element-plus'

const props = defineProps<{ modelValue: boolean; label?: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
</script>

<template>
  <ElCheckbox
    :model-value="props.modelValue"
    :disabled="props.disabled"
    @update:model-value="emit('update:modelValue', $event as boolean)"
  >
    <slot>{{ props.label }}</slot>
  </ElCheckbox>
</template>
