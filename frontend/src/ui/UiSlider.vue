<script setup lang="ts">
/** 滑块：封装 el-slider */
import { ElSlider } from 'element-plus'

const props = withDefaults(
  defineProps<{
    modelValue: number
    min?: number
    max?: number
    showInput?: boolean
    disabled?: boolean
  }>(),
  { min: 0, max: 100, showInput: false, disabled: false },
)
const emit = defineEmits<{ 'update:modelValue': [value: number] }>()
</script>

<template>
  <ElSlider
    :model-value="props.modelValue"
    :min="props.min"
    :max="props.max"
    :show-input="props.showInput"
    :disabled="props.disabled"
    @update:model-value="emit('update:modelValue', $event as number)"
  />
</template>
