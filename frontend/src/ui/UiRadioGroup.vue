<script setup lang="ts">
/**
 * 单选组：封装 el-radio-group，选项以 props 传入（页面不接触 el-radio*）。
 * `button` 为真时渲染按钮式分段控件。
 */
import { ElRadio, ElRadioButton, ElRadioGroup } from 'element-plus'

export interface RadioOption {
  label: string
  value: string | number
  disabled?: boolean
}
const props = withDefaults(
  defineProps<{
    modelValue: string | number
    options: RadioOption[]
    button?: boolean
    size?: 'large' | 'default' | 'small'
  }>(),
  { button: false, size: 'default' },
)
const emit = defineEmits<{ 'update:modelValue': [value: string | number] }>()
</script>

<template>
  <ElRadioGroup
    :model-value="props.modelValue"
    :size="props.size"
    @update:model-value="emit('update:modelValue', $event as string | number)"
  >
    <template v-if="props.button">
      <ElRadioButton v-for="o in props.options" :key="o.value" :value="o.value" :disabled="o.disabled">
        {{ o.label }}
      </ElRadioButton>
    </template>
    <template v-else>
      <ElRadio v-for="o in props.options" :key="o.value" :value="o.value" :disabled="o.disabled">
        {{ o.label }}
      </ElRadio>
    </template>
  </ElRadioGroup>
</template>
