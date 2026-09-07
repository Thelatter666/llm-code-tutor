<script setup lang="ts">
import * as kbApi from '@/api/knowledge'
import { useConfirm } from '@/composables/useConfirm'
import { useNotify } from '@/composables/useNotify'
import type { DocumentOut, KnowledgeBaseOut } from '@/types/knowledge'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { UiBadge, UiButton, UiCard, UiDialog, UiIcon, UiInput, UiProgress, UiTextarea, UiUpload } from '@/ui'

const notify = useNotify()
const confirm = useConfirm()

const bases = ref<KnowledgeBaseOut[]>([])
const documents = ref<DocumentOut[]>([])
const activeKbId = ref<string | null>(null)
const loadingDocs = ref(false)

const createDialog = ref(false)
const creating = ref(false)
const form = ref({ name: '', description: '', course_code: '' })

const POLL_INTERVAL_MS = 1000
let pollTimer: number | undefined

const indexing = computed(() =>
  documents.value.some((d) => ['pending', 'indexing', 'reindexing'].includes(d.status)),
)

const activeKb = computed(() => bases.value.find((b) => b.id === activeKbId.value) ?? null)

// ---------------------------------------------------------------- 知识库

async function loadBases() {
  const { data } = await kbApi.listBases()
  bases.value = data.data ?? []
  if (!activeKbId.value && bases.value.length) await selectKb(bases.value[0].id)
}

async function submitCreate() {
  if (!form.value.name.trim()) {
    notify.warning('请填写知识库名称')
    return
  }
  creating.value = true
  try {
    const { data } = await kbApi.createBase({
      name: form.value.name.trim(),
      description: form.value.description || undefined,
      course_code: form.value.course_code || undefined,
    })
    const kb = data.data
    createDialog.value = false
    form.value = { name: '', description: '', course_code: '' }
    await loadBases()
    if (kb) await selectKb(kb.id)
  } catch (e) {
    notify.error((e as Error).message)
  } finally {
    creating.value = false
  }
}

async function removeBase(kb: KnowledgeBaseOut) {
  if (!(await confirm(`删除知识库「${kb.name}」会连同其全部文档与切片一并删除，且不可恢复。`, '删除知识库'))) {
    return
  }
  await kbApi.deleteBase(kb.id)
  if (activeKbId.value === kb.id) {
    activeKbId.value = null
    documents.value = []
  }
  await loadBases()
}

// ---------------------------------------------------------------- 文档

async function selectKb(kbId: string) {
  activeKbId.value = kbId
  await loadDocuments()
}

async function loadDocuments() {
  if (!activeKbId.value) return
  loadingDocs.value = true
  try {
    const { data } = await kbApi.listDocuments(activeKbId.value)
    documents.value = data.data ?? []
  } catch (e) {
    notify.error((e as Error).message)
  } finally {
    loadingDocs.value = false
  }
}

/** spec §8.2 进度可见：索引进行中轮询 chunk_indexed / chunk_total。 */
function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(async () => {
    if (!indexing.value) {
      stopPolling()
      return
    }
    await loadDocuments()
  }, POLL_INTERVAL_MS)
}

function stopPolling() {
  if (pollTimer !== undefined) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

async function onFiles(files: File[]) {
  if (!activeKbId.value) return
  for (const file of files) {
    try {
      await kbApi.uploadDocument(activeKbId.value, file)
      notify.success(`已收下「${file.name}」，正在后台索引`)
      await loadDocuments()
      startPolling()
    } catch (e) {
      notify.error((e as Error).message)
    }
  }
}

async function reindex(doc: DocumentOut) {
  await kbApi.reindexDocument(doc.id)
  notify.success('已重新提交索引')
  await loadDocuments()
  startPolling()
}

async function removeDocument(doc: DocumentOut) {
  if (!(await confirm(`删除文档「${doc.title}」？`, '删除文档'))) return
  await kbApi.deleteDocument(doc.id)
  await loadDocuments()
}

async function rebuild() {
  if (!activeKbId.value) return
  await kbApi.rebuildVectors(activeKbId.value)
  notify.success('已触发全量重建')
  await loadBases()
  await loadDocuments()
  startPolling()
}

async function gcOrphans() {
  if (!activeKbId.value) return
  const { data } = await kbApi.gcOrphanVectors(activeKbId.value)
  const r = data.data
  notify.success(r ? `扫描 ${r.scanned} 条，清理孤儿向量 ${r.deleted} 条` : '孤儿向量清理完成')
}

function progressOf(row: DocumentOut): number {
  if (row.chunk_total <= 0) return 0
  return Math.round((row.chunk_indexed / row.chunk_total) * 100)
}

onMounted(async () => {
  await loadBases()
  if (indexing.value) startPolling()
})

onUnmounted(stopPolling)
</script>

<template>
  <div class="flex flex-col gap-4">
    <!-- 知识库列表 -->
    <UiCard :padded="false">
      <div class="flex items-center justify-between gap-3 border-b border-line p-3">
        <h2 class="text-md font-bold text-ink">知识库管理</h2>
        <UiButton @click="createDialog = true">
          <UiIcon name="Plus" :size="14" />新建知识库
        </UiButton>
      </div>
      <table class="w-full text-sm">
        <thead class="text-xs text-muted-ink">
          <tr>
            <th class="px-3 py-2 text-left font-medium">名称</th>
            <th class="px-3 py-2 text-left font-medium">课程代码</th>
            <th class="px-3 py-2 text-left font-medium">索引模型</th>
            <th class="px-3 py-2 text-left font-medium">状态</th>
            <th class="px-3 py-2 text-left font-medium">操作</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-line">
          <tr
            v-for="kb in bases"
            :key="kb.id"
            class="cursor-pointer hover:bg-softer"
            :class="kb.id === activeKbId ? 'bg-softer' : ''"
            @click="selectKb(kb.id)"
          >
            <td class="px-3 py-2" :class="kb.id === activeKbId ? 'font-semibold text-brand' : ''">{{ kb.name }}</td>
            <td class="px-3 py-2 text-muted-ink">{{ kb.course_code || '不限' }}</td>
            <td class="px-3 py-2 font-mono text-xs text-muted-ink">{{ kb.embed_model || '—' }}</td>
            <td class="px-3 py-2">
              <UiBadge :variant="kb.status === 'ready' ? 'success' : 'warning'">
                {{ kb.status === 'ready' ? '就绪' : '重建中' }}
              </UiBadge>
            </td>
            <td class="px-3 py-2">
              <UiButton variant="link" size="sm" @click.stop="removeBase(kb)">删除</UiButton>
            </td>
          </tr>
        </tbody>
      </table>
    </UiCard>

    <!-- 文档管理 -->
    <UiCard v-if="activeKb" :title="`文档 · ${activeKb.name}`" :padded="false">
      <template #header>
        <h3 class="text-md font-semibold text-ink">文档 · {{ activeKb.name }}</h3>
        <div class="flex gap-2">
          <UiButton variant="secondary" size="sm" @click="rebuild">
            <UiIcon name="RefreshCw" :size="14" />重建向量
          </UiButton>
          <UiButton variant="secondary" size="sm" @click="gcOrphans">
            <UiIcon name="Brush" :size="14" />清理孤儿向量
          </UiButton>
        </div>
      </template>

      <div class="flex flex-col gap-4 p-4">
        <UiUpload multiple @files="onFiles">
          <div class="flex flex-col items-center gap-1 py-6">
            <UiIcon name="Upload" :size="28" class="text-brand" />
            <p class="text-sm text-ink">把文件拖到这里，或点击上传</p>
            <p class="text-sm text-muted-ink">
              支持 .pdf / .md / .txt / .docx，单文件不超过 10MB；扫描版 PDF 无文字层，需先做 OCR
            </p>
          </div>
        </UiUpload>

        <div v-loading="loadingDocs" class="overflow-auto">
          <table class="w-full text-sm">
            <thead class="text-xs text-muted-ink">
              <tr>
                <th class="px-3 py-2 text-left font-medium">文档</th>
                <th class="px-3 py-2 text-left font-medium">类型</th>
                <th class="px-3 py-2 text-left font-medium">状态</th>
                <th class="px-3 py-2 text-left font-medium">索引进度</th>
                <th class="px-3 py-2 text-left font-medium">错误信息</th>
                <th class="px-3 py-2 text-left font-medium">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line">
              <tr v-for="row in documents" :key="row.id" class="hover:bg-softer">
                <td class="max-w-[220px] px-3 py-2" :title="row.title">{{ row.title }}</td>
                <td class="px-3 py-2 text-xs text-muted-ink">{{ row.source_type }}</td>
                <td class="px-3 py-2">
                  <UiBadge :variant="row.status === 'ready' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'">
                    {{ row.status }}
                  </UiBadge>
                </td>
                <td class="min-w-[200px] px-3 py-2">
                  <template v-if="row.chunk_total > 0">
                    <UiProgress :percentage="progressOf(row)" />
                    <div class="mt-1 text-xs text-muted-ink">{{ row.chunk_indexed }} / {{ row.chunk_total }} 切片</div>
                  </template>
                  <span v-else class="text-sm text-muted-ink">等待索引</span>
                </td>
                <td class="max-w-[200px] px-3 py-2 text-xs break-all text-muted-ink" :title="row.error_msg || ''">
                  {{ row.error_msg || '—' }}
                </td>
                <td class="px-3 py-2">
                  <div class="flex gap-1">
                    <UiButton variant="link" size="sm" @click="reindex(row)">重建</UiButton>
                    <UiButton variant="link" size="sm" @click="removeDocument(row)">删除</UiButton>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </UiCard>

    <UiDialog v-model="createDialog" title="新建知识库" width="460px">
      <form class="flex flex-col gap-3" @submit.prevent>
        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">名称 *</label>
          <UiInput v-model="form.name" :maxlength="128" />
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">课程代码</label>
          <UiInput v-model="form.course_code" placeholder="留空表示不限课程" />
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">描述</label>
          <UiTextarea v-model="form.description" :rows="3" />
        </div>
      </form>
      <template #footer>
        <UiButton variant="secondary" @click="createDialog = false">取消</UiButton>
        <UiButton :loading="creating" @click="submitCreate">创建</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
