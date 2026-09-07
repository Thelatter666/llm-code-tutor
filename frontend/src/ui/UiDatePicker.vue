<script setup lang="ts">
/** 日期选择：封装 el-date-picker，v-model 为 YYYY-MM-DD 字符串（与后端查询参数对齐） */
import { ElDatePicker } from 'element-plus'

const props = withDefaults(
  defineProps<{ modelValue?: string | null; placeholder?: string; disabled?: boolean }>(),
  { modelValue: null, disabled: false },
)
const emit = defineEmits<{ 'update:modelValue': [value: string | null] }>()
</script>

<template>
  <ElDatePicker
    :model-value="props.modelValue"
    type="date"
    value-format="YYYY-MM-DD"
    :placeholder="props.placeholder"
    :disabled="props.disabled"
    @update:model-value="emit('update:modelValue', ($event as string | null) ?? null)"
  />
</template>
