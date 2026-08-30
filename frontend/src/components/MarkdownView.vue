<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{ content: string }>()

// v-html 的唯一豁免点：renderMarkdown 已做 html:false + DOMPurify 双层消毒，
// 严禁把未经过 renderMarkdown 的内容传进来。
const html = computed(() => renderMarkdown(props.content))
</script>

<template>
  <div class="md" v-html="html"></div>
</template>

<style scoped>
/* 配色 / 间距 / 圆角全部走 theme.css 变量（frontend/docs/ui-baseline.md §2 §4） */
.md {
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}

.md :deep(p) {
  margin: 0 0 var(--space-2);
}

.md :deep(p:last-child) {
  margin-bottom: 0;
}

.md :deep(ul),
.md :deep(ol) {
  margin: 0 0 var(--space-2);
  padding-left: 1.4em;
}

.md :deep(h1),
.md :deep(h2),
.md :deep(h3),
.md :deep(h4) {
  margin: var(--space-3) 0 var(--space-2);
  font-size: 15px;
  line-height: 1.3;
}

.md :deep(h1:first-child),
.md :deep(h2:first-child),
.md :deep(h3:first-child) {
  margin-top: 0;
}

.md :deep(code) {
  padding: 1px 5px;
  border-radius: var(--radius-control);
  background: var(--color-muted);
  font-size: 13px;
}

.md :deep(pre) {
  margin: 0 0 var(--space-2);
  padding: var(--space-3);
  border-radius: var(--radius-control);
  background: var(--color-muted);
  overflow: auto;
}

.md :deep(pre:last-child) {
  margin-bottom: 0;
}

.md :deep(pre code) {
  padding: 0;
  background: transparent;
  font-size: 13px;
}

.md :deep(blockquote) {
  margin: 0 0 var(--space-2);
  padding-left: var(--space-3);
  border-left: 3px solid var(--color-border);
  color: var(--color-muted-foreground);
}

.md :deep(a) {
  color: var(--color-primary);
}

.md :deep(table) {
  border-collapse: collapse;
  margin-bottom: var(--space-2);
}

.md :deep(th),
.md :deep(td) {
  border: 1px solid var(--color-border);
  padding: 4px 8px;
}
</style>
