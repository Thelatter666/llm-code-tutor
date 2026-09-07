<script setup lang="ts">
import CitationList from '@/components/CitationList.vue'
import DegradedBanner from '@/components/DegradedBanner.vue'
import * as kbApi from '@/api/knowledge'
import { useNotify } from '@/composables/useNotify'
import type { KnowledgeBaseOut, SearchOut } from '@/types/knowledge'
import { computed, onMounted, ref } from 'vue'
import { UiBadge, UiButton, UiCard, UiIcon, UiInput, UiSelect, UiSlider } from '@/ui'

/** 知识库检索演示页：把 P1 的七步装配链路直接暴露出来，便于答辩现场演示。 */
const bases = ref<KnowledgeBaseOut[]>([])
const selected = ref<string[]>([])
const query = ref('')
const topK = ref(5)
const result = ref<SearchOut | null>(null)
const loading = ref(false)
const notify = useNotify()

const kbOptions = computed(() => bases.value.map((b) => ({ label: b.name, value: b.id })))

async function loadBases() {
  try {
    const { data } = await kbApi.listBases()
    bases.value = (data.data ?? []).filter((b) => b.status === 'ready')
  } catch {
    bases.value = []
  }
}

async function runSearch() {
  const q = query.value.trim()
  if (!q) {
    notify.warning('请输入检索关键词')
    return
  }
  loading.value = true
  try {
    const { data } = await kbApi.search({
      query: q,
      kbIds: selected.value,
      topK: topK.value,
    })
    result.value = data.data
  } catch (e) {
    notify.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

onMounted(loadBases)
</script>

<template>
  <div class="flex flex-col gap-4">
    <UiCard title="知识库检索演示">
      <form @submit.prevent="runSearch">
        <div class="grid gap-4 sm:grid-cols-2">
          <div class="flex flex-col gap-1">
            <label for="q" class="text-sm text-muted-ink">检索词</label>
            <UiInput
              id="q"
              v-model="query"
              placeholder="例如：讲讲排序算法 / 闭包是什么 / 递归的基线条件怎么写"
              @keydown.enter.prevent="runSearch"
            />
          </div>
          <div class="flex flex-col gap-1">
            <label class="text-sm text-muted-ink">知识库</label>
            <UiSelect
              v-model="selected"
              :options="kbOptions"
              multiple
              clearable
              placeholder="不限知识库"
            />
          </div>
        </div>
        <div class="mt-4 flex flex-col gap-1">
          <label class="text-sm text-muted-ink">返回条数（{{ topK }}）</label>
          <UiSlider v-model="topK" :min="1" :max="10" show-input />
        </div>
        <UiButton class="mt-4" :loading="loading" @click="runSearch">
          <UiIcon name="Search" :size="14" />
          检索
        </UiButton>
      </form>
    </UiCard>

    <UiCard v-if="result">
      <DegradedBanner :degraded="result.degraded" :fallback-reason="result.fallback_reason" />

      <div class="mb-3 flex flex-wrap items-center gap-3 text-sm text-muted-ink">
        <UiBadge :variant="result.rag_hit ? 'success' : 'info'">
          {{ result.rag_hit ? '知识库命中' : '未命中知识库' }}
        </UiBadge>
        <span>相关度阈值 {{ result.threshold }}</span>
        <span>向量化器 {{ result.embedder ?? '—' }}</span>
        <span>命中 {{ result.citations.length }} 条</span>
      </div>

      <table v-if="result.citations.length" class="w-full text-sm">
        <thead class="text-xs text-muted-ink">
          <tr>
            <th class="px-3 py-2 text-left font-medium">#</th>
            <th class="px-3 py-2 text-left font-medium">来源文档</th>
            <th class="px-3 py-2 text-left font-medium">相关度</th>
            <th class="px-3 py-2 text-left font-medium">切片内容</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-line">
          <tr v-for="c in result.citations" :key="c.chunk_id">
            <td class="px-3 py-2 text-brand">{{ c.number }}</td>
            <td class="px-3 py-2">{{ c.doc_title }}</td>
            <td class="px-3 py-2 text-muted-ink">{{ Number(c.score).toFixed(4) }}</td>
            <td class="px-3 py-2 text-muted-ink">
              <span class="line-clamp-2">{{ c.snippet }}</span>
            </td>
          </tr>
        </tbody>
      </table>
      <CitationList v-if="result.citations.length" :citations="result.citations" />

      <p v-else class="text-sm leading-relaxed text-muted-ink">
        没有相关度高于阈值的切片。按 spec §7.2 步骤 7，这属于可见降级，不应由模型
        用幻觉冒充知识库答案。
      </p>
    </UiCard>
  </div>
</template>
