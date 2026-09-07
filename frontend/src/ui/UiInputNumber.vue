<script setup lang="ts">
/** 数值输入：封装 el-input-number；允许 null（如 score_threshold 留空走默认值） */
import { ElInputNumber } from 'element-plus'

const props = withDefaults(
  defineProps<{
    modelValue: number | null
    min?: number
    max?: number
    step?: number
    controls?: boolean
    disabled?: boolean
    clearable?: boolean
    valueOnClear?: number | null
  }>(),
  {
    min: 0,
    max: Number.MAX_SAFE_INTEGER,
    step: 1,
    controls: true,
    disabled: false,
    clearable: false,
    valueOnClear: null,
  },
)
const emit = defineEmits<{ 'update:modelValue': [value: number | null] }>()
</script>

<template>
  <ElInputNumber
    :model-value="props.modelValue"
    :min="props.min"
    :max="props.max"
    :step="props.step"
    :controls="props.controls"
    :disabled="props.disabled"
    :clearable="props.clearable"
    :value-on-clear="props.valueOnClear"
    class="!w-full"
    @update:model-value="emit('update:modelValue', $event as number | null)"
  />
</template>
