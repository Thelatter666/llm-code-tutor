<script setup lang="ts">
/** 数值输入：封装 el-input-number */
import { ElInputNumber } from 'element-plus'

const props = withDefaults(
  defineProps<{
    modelValue: number
    min?: number
    max?: number
    step?: number
    controls?: boolean
    disabled?: boolean
  }>(),
  { min: 0, max: Number.MAX_SAFE_INTEGER, step: 1, controls: true, disabled: false },
)
const emit = defineEmits<{ 'update:modelValue': [value: number] }>()
</script>

<template>
  <ElInputNumber
    :model-value="props.modelValue"
    :min="props.min"
    :max="props.max"
    :step="props.step"
    :controls="props.controls"
    :disabled="props.disabled"
    class="!w-full"
    @update:model-value="emit('update:modelValue', $event as number)"
  />
</template>
