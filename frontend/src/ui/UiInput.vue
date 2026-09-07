<script setup lang="ts">
/** 单行输入：原生 input + Tailwind，不依赖 el-input */
const props = withDefaults(
  defineProps<{
    modelValue: string | number
    type?: 'text' | 'password' | 'number' | 'search' | 'email' | 'tel' | 'url'
    placeholder?: string
    disabled?: boolean
    maxlength?: number
  }>(),
  { type: 'text', disabled: false },
)
const emit = defineEmits<{ 'update:modelValue': [value: string | number] }>()
</script>

<template>
  <input
    :value="props.modelValue"
    :type="props.type"
    :placeholder="props.placeholder"
    :disabled="props.disabled"
    :maxlength="props.maxlength"
    class="box-border w-full rounded-ctl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none transition-colors placeholder:text-muted-ink hover:border-line-strong focus:border-brand focus:ring-2 focus:ring-brand/30 disabled:opacity-60"
    @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
  />
</template>
