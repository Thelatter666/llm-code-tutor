<script setup lang="ts">
import type { Citation } from '@/types/chat'
import { ref } from 'vue'

/** 引用列表：模型回答所依据的切片来源，点击可展开溯源（spec §7.2 步骤 6）。 */
defineProps<{ citations: Citation[] }>()

const expanded = ref<Record<string, boolean>>({})

function toggle(id: string) {
  expanded.value[id] = !expanded.value[id]
}
</script>

<template>
  <div v-if="citations.length" class="citations">
    <div class="citations__label">引用来源（{{ citations.length }}）</div>
    <div v-for="c in citations" :key="c.chunk_id" class="citation">
      <button class="citation__head" type="button" @click="toggle(c.chunk_id)">
        <span class="citation__num">[{{ c.number }}]</span>
        <span class="citation__title">{{ c.doc_title || '未命名文档' }}</span>
        <span class="citation__score">相关度 {{ c.score.toFixed(4) }}</span>
        <span class="citation__caret">{{ expanded[c.chunk_id] ? '收起' : '展开' }}</span>
      </button>
      <pre v-if="expanded[c.chunk_id]" class="citation__snippet">{{ c.snippet }}</pre>
    </div>
  </div>
</template>

<style scoped>
.citations {
  margin-top: var(--space-3);
  border-top: 1px dashed var(--color-border);
  padding-top: var(--space-3);
}

.citations__label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-accent);
  margin-bottom: var(--space-2);
}

.citation {
  margin-bottom: var(--space-2);
}

.citation__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-card);
  color: var(--color-foreground);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition: background 200ms ease, border-color 200ms ease;
}

.citation__head:hover {
  background: var(--color-muted);
  border-color: var(--color-secondary);
}

.citation__head:focus-visible {
  outline: 2px solid var(--color-ring);
  outline-offset: 2px;
}

.citation__num {
  color: var(--color-primary);
  font-weight: 700;
}

.citation__title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.citation__score {
  color: var(--color-muted-foreground);
}

.citation__caret {
  color: var(--color-accent);
}

.citation__snippet {
  margin: var(--space-2) 0 0;
  padding: var(--space-3);
  background: var(--color-muted);
  border-radius: var(--radius-card);
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow: auto;
}
</style>
