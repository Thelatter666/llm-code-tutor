<script setup lang="ts">
import * as adminApi from '@/api/admin'
import type { OverviewOut } from '@/types/admin'
import { RefreshLeft } from '@element-plus/icons-vue'
import { onMounted, ref } from 'vue'

/**
 * 仪表盘页（spec §6.2 / 裁定 3 最小集，P6 Task 11）。
 *
 * 展示各实体计数 + 当前模型配置摘要 + 向量化器就绪状态（与 /health 同源）。
 */

const data = ref<OverviewOut | null>(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const { data: resp } = await adminApi.getOverview()
    data.value = resp.data
  } finally {
    loading.value = false
  }
}

onMounted(load)

function buildCards() {
  const d = data.value
  if (!d) return []
  return [
    { label: '用户', value: d.users.total },
    { label: '会话', value: d.conversations },
    { label: '消息', value: d.messages },
    { label: '知识库', value: d.knowledge_bases },
    { label: '文档', value: d.documents },
    { label: '代码会话', value: d.code_sessions },
    { label: '代码分析', value: d.code_analyses },
    { label: '代码运行', value: d.code_runs },
    { label: '已发布习题', value: d.exercises.published },
    { label: '提交', value: d.submissions },
    { label: '未掌握错题', value: d.mistake_entries.unmastered },
    { label: '审计日志', value: d.audit_logs },
  ]
}
</script>

<template>
  <div v-loading="loading" class="overview-page">
    <div class="overview-page__cards">
      <div v-for="card in buildCards()" :key="card.label" class="overview-page__card">
        <div class="overview-page__value">{{ card.value }}</div>
        <div class="overview-page__label">{{ card.label }}</div>
      </div>
    </div>

    <div class="overview-page__panels">
      <div class="overview-page__panel">
        <h3 class="overview-page__title">当前配置</h3>
        <dl class="overview-page__kv">
          <div><dt>LLM 提供方</dt><dd>{{ data?.model_config.provider ?? '—' }}</dd></div>
          <div><dt>模型</dt><dd>{{ data?.model_config.model ?? '—' }}</dd></div>
          <div><dt>防抄袭档位</dt><dd>{{ data?.model_config.anti_plagiarism_mode ?? '—' }}</dd></div>
          <div><dt>配置版本 revision</dt><dd>{{ data?.model_config.revision ?? '—' }}</dd></div>
        </dl>
      </div>

      <div class="overview-page__panel">
        <h3 class="overview-page__title">向量化器</h3>
        <dl class="overview-page__kv">
          <div><dt>就绪</dt><dd>{{ data?.embedder.ready ? '是' : '否（加载中/降级）' }}</dd></div>
          <div><dt>实现</dt><dd>{{ data?.embedder.name ?? '—' }}</dd></div>
          <div><dt>模型</dt><dd>{{ data?.embedder.model ?? '—' }}</dd></div>
          <div v-if="data?.embedder.error"><dt>错误</dt><dd>{{ data.embedder.error }}</dd></div>
        </dl>
      </div>

      <div class="overview-page__panel">
        <h3 class="overview-page__title">用户结构</h3>
        <dl class="overview-page__kv">
          <div><dt>管理员</dt><dd>{{ data?.users.admin ?? 0 }}</dd></div>
          <div><dt>正常状态</dt><dd>{{ data?.users.active ?? 0 }}</dd></div>
          <div><dt>习题草稿</dt><dd>{{ data?.exercises.draft ?? 0 }}</dd></div>
          <div><dt>错题条目</dt><dd>{{ data?.mistake_entries.total ?? 0 }}</dd></div>
        </dl>
      </div>
    </div>

    <el-button class="overview-page__refresh" :icon="RefreshLeft" @click="load">刷新</el-button>
  </div>
</template>

<style scoped>
.overview-page__cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}

.overview-page__card {
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  padding: var(--space-4);
  text-align: center;
}

.overview-page__value {
  font-size: 28px;
  font-weight: 700;
  color: var(--color-primary);
}

.overview-page__label {
  margin-top: var(--space-1);
  font-size: 13px;
  color: var(--color-muted-foreground);
}

.overview-page__panels {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--space-4);
}

.overview-page__panel {
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  padding: var(--space-4);
}

.overview-page__title {
  margin: 0 0 var(--space-3);
  font-size: 15px;
}

.overview-page__kv {
  margin: 0;
}

.overview-page__kv > div {
  display: flex;
  justify-content: space-between;
  padding: var(--space-1) 0;
  border-bottom: 1px solid var(--color-border);
}

.overview-page__kv dt {
  color: var(--color-muted-foreground);
}

.overview-page__kv dd {
  margin: 0;
  font-weight: 600;
}

.overview-page__refresh {
  margin-top: var(--space-4);
}
</style>
