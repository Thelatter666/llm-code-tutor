<script setup lang="ts">
/** 多行输入：原生 textarea + Tailwind，不依赖 el-input */
const props = withDefaults(
  defineProps<{
    modelValue: string
    rows?: number
    placeholder?: string
    readonly?: boolean
    monospace?: boolean
    maxlength?: number
  }>(),
  { rows: 6, readonly: false, monospace: false },
)
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
</script>

<template>
  <textarea
    :value="props.modelValue"
    :rows="props.rows"
    :placeholder="props.placeholder"
    :readonly="props.readonly"
    :maxlength="props.maxlength"
    class="w-full resize-y rounded-ctl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none transition-colors placeholder:text-muted-ink hover:border-line-strong focus:border-brand focus:ring-2 focus:ring-brand/30 disabled:opacity-60"
    :class="props.monospace ? 'font-mono' : ''"
    @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
  />
</template>
