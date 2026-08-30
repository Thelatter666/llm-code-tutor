<script setup lang="ts">
import CitationList from '@/components/CitationList.vue'
import DegradedBanner from '@/components/DegradedBanner.vue'
import * as kbApi from '@/api/knowledge'
import type { KnowledgeBaseOut, SearchOut } from '@/types/knowledge'
import { Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { onMounted, ref } from 'vue'

/** 知识库检索演示页：把 P1 的七步装配链路直接暴露出来，便于答辩现场演示。 */
const bases = ref<KnowledgeBaseOut[]>([])
const selected = ref<string[]>([])
const query = ref('')
const topK = ref(5)
const result = ref<SearchOut | null>(null)
const loading = ref(false)

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
    ElMessage.warning('请输入检索关键词')
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
    ElMessage.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

onMounted(loadBases)
</script>

<template>
  <div class="kb-search">
    <el-card shadow="never" class="kb-search__card">
      <template #header>
        <h2 class="kb-search__title">知识库检索演示</h2>
      </template>

      <el-form @submit.prevent="runSearch">
        <el-form-item label="检索词">
          <el-input
            v-model="query"
            placeholder="例如：讲讲排序算法 / 闭包是什么 / 递归的基线条件怎么写"
            @keydown.enter.prevent="runSearch"
          />
        </el-form-item>
        <el-form-item label="知识库">
          <el-select
            v-model="selected"
            multiple
            clearable
            collapse-tags
            collapse-tags-tooltip
            placeholder="不限知识库"
            class="kb-search__kb"
          >
            <el-option v-for="b in bases" :key="b.id" :label="b.name" :value="b.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="返回条数">
          <el-slider v-model="topK" :min="1" :max="10" show-input />
        </el-form-item>
        <el-button type="primary" :icon="Search" :loading="loading" @click="runSearch">
          检索
        </el-button>
      </el-form>
    </el-card>

    <el-card v-if="result" shadow="never" class="kb-search__card">
      <DegradedBanner :degraded="result.degraded" :fallback-reason="result.fallback_reason" />

      <div class="kb-search__summary">
        <el-tag :type="result.rag_hit ? 'success' : 'info'" effect="plain">
          {{ result.rag_hit ? '知识库命中' : '未命中知识库' }}
        </el-tag>
        <span>相关度阈值 {{ result.threshold }}</span>
        <span>向量化器 {{ result.embedder ?? '—' }}</span>
        <span>命中 {{ result.citations.length }} 条</span>
      </div>

      <el-table v-if="result.citations.length" :data="result.citations" style="width: 100%">
        <el-table-column prop="number" label="#" width="60" />
        <el-table-column prop="doc_title" label="来源文档" min-width="180" />
        <el-table-column label="相关度" width="120">
          <template #default="{ row }">
            {{ Number(row.score).toFixed(4) }}
          </template>
        </el-table-column>
        <el-table-column prop="snippet" label="切片内容" min-width="320" show-overflow-tooltip />
      </el-table>
      <CitationList v-if="result.citations.length" :citations="result.citations" />

      <p v-else class="kb-search__miss">
        没有相关度高于阈值的切片。按 spec §7.2 步骤 7，这属于可见降级，不应由模型
        用幻觉冒充知识库答案。
      </p>
    </el-card>
  </div>
</template>

<style scoped>
.kb-search {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.kb-search__card {
  border-radius: var(--radius-card);
}

.kb-search__title {
  font-size: 18px;
}

.kb-search__kb {
  width: 100%;
}

.kb-search__summary {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
  margin-bottom: var(--space-3);
  font-size: 13px;
  color: var(--color-muted-foreground);
}

.kb-search__miss {
  font-size: 13px;
  color: var(--color-muted-foreground);
  line-height: 1.6;
}
</style>
