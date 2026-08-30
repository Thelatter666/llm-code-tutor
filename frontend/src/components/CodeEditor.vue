<script setup lang="ts">
import type { CodeLanguage } from '@/api/code'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

/**
 * Monaco 编辑器包装（P4）。
 *
 * **懒加载**：`monaco-editor` 全量 ESM 约 30MB 源码 / 构建后数 MB，故不在组件
 * 顶层静态 import，而是在 `onMounted` 里动态 import —— 配合路由级懒加载，
 * 未访问编辑器页的用户完全不会下载它。
 *
 * **Worker 配置**照 `monaco-editor/docs/integrate-esm.md` 的 Vite 段：实现
 * `self.MonacoEnvironment.getWorker`（**不是 `getWorkerUrl`**），Vite 用内建的
 * `?worker` 后缀产出 worker chunk。javascript / typescript 标签给 ts.worker，
 * 其余（基础编辑能力）给 editor.worker。
 */
const props = defineProps<{
  modelValue: string
  language: CodeLanguage
  readOnly?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const host = ref<HTMLDivElement | null>(null)
const ready = ref(false)

// 动态 import 的类型；这里只需要 editor 实例与语言 id 两个能力，故只声明用到的部分
type MonacoApi = typeof import('monaco-editor')

let monaco: MonacoApi | null = null
let editor: ReturnType<MonacoApi['editor']['create']> | null = null
let changeBinding: { dispose(): void } | null = null

async function loadMonaco() {
  // worker 与编辑器同批加载；`?worker` 由 Vite 解析成独立的 worker chunk
  const [editorWorker, tsWorker] = await Promise.all([
    import('monaco-editor/editor/editor.worker?worker'),
    import('monaco-editor/language/typescript/ts.worker?worker'),
  ])
  ;(self as unknown as { MonacoEnvironment: { getWorker(_: unknown, label: string): Worker } }).MonacoEnvironment =
    {
      getWorker(_: unknown, label: string) {
        if (label === 'typescript' || label === 'javascript') return new tsWorker.default()
        return new editorWorker.default()
      },
    }
  return import('monaco-editor')
}

onMounted(async () => {
  if (!host.value) return
  monaco = await loadMonaco()
  editor = monaco.editor.create(host.value, {
    value: props.modelValue,
    language: props.language,
    theme: 'vs',
    fontSize: 13,
    minimap: { enabled: false },
    automaticLayout: true,
    scrollBeyondLastLine: false,
    tabSize: props.language === 'python' ? 4 : 2,
    // 教学场景：不自动插入建议，避免打断输入
    quickSuggestions: false,
    fixedOverflowWidgets: true,
  })
  changeBinding = editor.onDidChangeModelContent(() => {
    emit('update:modelValue', editor?.getValue() ?? '')
  })
  ready.value = true
})

watch(
  () => props.language,
  (language) => {
    if (!monaco || !editor) return
    const model = editor.getModel()
    if (model) monaco.editor.setModelLanguage(model, language)
  },
)

// 外部改了源码（例如加载草稿）时同步进编辑器，且不能触发回声式 update
watch(
  () => props.modelValue,
  (value) => {
    if (!editor) return
    if (editor.getValue() === value) return
    editor.setValue(value)
  },
)

onBeforeUnmount(() => {
  changeBinding?.dispose()
  editor?.getModel()?.dispose()
  editor?.dispose()
  editor = null
  monaco = null
})

defineExpose({
  /** 供父组件把光标内容取回（保存草稿前用一次）。 */
  getValue: () => editor?.getValue() ?? props.modelValue,
})
</script>

<template>
  <div class="editor">
    <div v-show="!ready" class="editor__placeholder">编辑器加载中…</div>
    <div ref="host" class="editor__host" />
  </div>
</template>

<style scoped>
.editor {
  position: relative;
  height: 100%;
  min-height: 320px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  overflow: hidden;
  background: var(--color-card);
}

.editor__host {
  height: 100%;
  width: 100%;
}

.editor__placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: var(--color-muted-foreground);
}
</style>
