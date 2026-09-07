<script setup lang="ts">
import { computed } from 'vue'
import { UiAlert } from '@/ui'

/**
 * 降级提示条（spec §9「降级必须可见」）。
 *
 * 三种降级靠 `fallback_reason` 区分，文案各不相同：
 * - `hashing_embed_no_semantics`：检索结果无语义、不可信（ADR-0004）
 * - `no_relevant_chunk`：知识库里没有相关内容，属正常未命中
 * - `llm_fallback_to_mock`：模型服务不可用，已降级到 Mock 提供方（M10）
 */
const props = defineProps<{
  degraded: boolean
  fallbackReason: string | null
}>()

const COPY: Record<string, { title: string; detail: string }> = {
  hashing_embed_no_semantics: {
    title: '当前为无语义向量模式，已停用知识库增强',
    detail: '检索结果不具备语义可信度，本次回答未使用知识库内容。',
  },
  no_relevant_chunk: {
    title: '知识库无相关内容，以下为通用回答',
    detail: '本次未命中任何切片，请注意区分通用回答与课程内容。',
  },
  llm_fallback_to_mock: {
    title: '模型服务不可用，已降级到 Mock 提供方',
    detail: '回答由 Mock 提供方生成，用量按字符数估算，仅供参考。',
  },
}

const copy = computed(() => {
  if (!props.degraded) return null
  return (
    (props.fallbackReason && COPY[props.fallbackReason]) || {
      title: '本次回答存在降级',
      detail: props.fallbackReason ? `降级原因：${props.fallbackReason}` : '',
    }
  )
})
</script>

<template>
  <UiAlert
    v-if="copy"
    variant="warning"
    class="mb-3"
    :title="copy.title"
    :description="copy.detail"
  />
</template>
