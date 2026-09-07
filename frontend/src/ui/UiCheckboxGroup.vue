<script setup lang="ts">
/** 复选组：封装 el-checkbox-group，选项以 props 传入（页面不接触 el-checkbox*） */
import { ElCheckbox, ElCheckboxGroup } from 'element-plus'

export interface CheckOption {
  label: string
  value: string | number
}
const props = withDefaults(
  defineProps<{ modelValue: Array<string | number>; options: CheckOption[]; disabled?: boolean }>(),
  { disabled: false },
)
const emit = defineEmits<{ 'update:modelValue': [value: Array<string | number>] }>()
</script>

<template>
  <ElCheckboxGroup
    :model-value="props.modelValue"
    :disabled="props.disabled"
    @update:model-value="emit('update:modelValue', $event as Array<string | number>)"
  >
    <ElCheckbox v-for="o in props.options" :key="o.value" :value="o.value">{{ o.label }}</ElCheckbox>
  </ElCheckboxGroup>
</template>
