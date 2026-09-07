<script setup lang="ts">
/**
 * 单选/多选下拉：封装 el-select，选项以 props 传入（页面不接触 el-option）。
 * 后续迁 shadcn-vue Select 只改本文件。
 */
import { ElOption, ElSelect } from 'element-plus'

export interface SelectOption {
  label: string
  value: string | number
}
const props = withDefaults(
  defineProps<{
    modelValue: string | number | Array<string | number> | null
    options: SelectOption[]
    multiple?: boolean
    placeholder?: string
    clearable?: boolean
    collapseTags?: boolean
  }>(),
  { multiple: false, clearable: false, collapseTags: true },
)
const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()
</script>

<template>
  <ElSelect
    :model-value="props.modelValue"
    :multiple="props.multiple"
    :placeholder="props.placeholder"
    :clearable="props.clearable"
    :collapse-tags="props.collapseTags"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <ElOption v-for="o in props.options" :key="o.value" :label="o.label" :value="o.value" />
  </ElSelect>
</template>
