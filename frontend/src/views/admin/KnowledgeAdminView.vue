<script setup lang="ts">
import * as kbApi from '@/api/knowledge'
import type { DocumentOut, KnowledgeBaseOut } from '@/types/knowledge'
import { Delete, Plus, RefreshRight, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'
import { computed, onMounted, onUnmounted, ref } from 'vue'

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
    ElMessage.warning('请填写知识库名称')
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
    ElMessage.error((e as Error).message)
  } finally {
    creating.value = false
  }
}

async function removeBase(kb: KnowledgeBaseOut) {
  await ElMessageBox.confirm(
    `删除知识库「${kb.name}」会连同其全部文档与切片一并删除，且不可恢复。`,
    '删除知识库',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
  )
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
    ElMessage.error((e as Error).message)
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

async function onUpload(options: UploadRequestOptions) {
  if (!activeKbId.value) return
  try {
    await kbApi.uploadDocument(activeKbId.value, options.file)
    ElMessage.success('已收下文件，正在后台索引')
    await loadDocuments()
    startPolling()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function reindex(doc: DocumentOut) {
  await kbApi.reindexDocument(doc.id)
  ElMessage.success('已重新提交索引')
  await loadDocuments()
  startPolling()
}

async function removeDocument(doc: DocumentOut) {
  await ElMessageBox.confirm(`删除文档「${doc.title}」？`, '删除文档', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  await kbApi.deleteDocument(doc.id)
  await loadDocuments()
}

async function rebuild() {
  if (!activeKbId.value) return
  await kbApi.rebuildVectors(activeKbId.value)
  ElMessage.success('已触发全量重建')
  await loadBases()
  await loadDocuments()
  startPolling()
}

async function gcOrphans() {
  if (!activeKbId.value) return
  const { data } = await kbApi.gcOrphanVectors(activeKbId.value)
  const r = data.data
  ElMessage.success(
    r ? `扫描 ${r.scanned} 条，清理孤儿向量 ${r.deleted} 条` : '孤儿向量清理完成',
  )
}

onMounted(async () => {
  await loadBases()
  if (indexing.value) startPolling()
})

onUnmounted(stopPolling)
</script>

<template>
  <div class="kba">
    <el-card shadow="never" class="kba__card">
      <template #header>
        <div class="kba__head">
          <h2 class="kba__title">知识库管理</h2>
          <el-button type="primary" :icon="Plus" @click="createDialog = true">新建知识库</el-button>
        </div>
      </template>

      <el-table
        :data="bases"
        highlight-current-row
        style="width: 100%"
        @row-click="(row: KnowledgeBaseOut) => selectKb(row.id)"
      >
        <el-table-column prop="name" label="名称" min-width="200" />
        <el-table-column prop="course_code" label="课程代码" width="120">
          <template #default="{ row }">{{ row.course_code || '不限' }}</template>
        </el-table-column>
        <el-table-column prop="embed_model" label="索引模型" min-width="220">
          <template #default="{ row }">{{ row.embed_model || '—' }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'ready' ? 'success' : 'warning'" effect="plain">
              {{ row.status === 'ready' ? '就绪' : '重建中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button link type="danger" :icon="Delete" @click.stop="removeBase(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-if="activeKb" shadow="never" class="kba__card">
      <template #header>
        <div class="kba__head">
          <h3 class="kba__subtitle">文档 · {{ activeKb.name }}</h3>
          <div class="kba__ops">
            <el-button :icon="RefreshRight" @click="rebuild">重建向量</el-button>
            <el-button @click="gcOrphans">清理孤儿向量</el-button>
          </div>
        </div>
      </template>

      <el-upload class="kba__upload" drag :http-request="onUpload" :show-file-list="false" multiple>
        <el-icon class="kba__upload-icon"><UploadFilled /></el-icon>
        <div class="kba__upload-text">把文件拖到这里，或点击上传</div>
        <div class="kba__upload-tip">
          支持 .pdf / .md / .txt / .docx，单文件不超过 10MB；扫描版 PDF 无文字层，需先做 OCR
        </div>
      </el-upload>

      <el-table :data="documents" v-loading="loadingDocs" style="width: 100%">
        <el-table-column prop="title" label="文档" min-width="200" show-overflow-tooltip />
        <el-table-column prop="source_type" label="类型" width="90" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag
              size="small"
              effect="plain"
              :type="
                row.status === 'ready'
                  ? 'success'
                  : row.status === 'failed'
                    ? 'danger'
                    : 'warning'
              "
            >
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="索引进度" min-width="220">
          <template #default="{ row }">
            <el-progress
              v-if="row.chunk_total > 0"
              :percentage="Math.round((row.chunk_indexed / row.chunk_total) * 100)"
              :status="row.status === 'ready' ? 'success' : undefined"
            />
            <span v-else class="kba__muted">等待索引</span>
            <div class="kba__muted kba__progress-text">
              {{ row.chunk_indexed }} / {{ row.chunk_total }} 切片
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="error_msg" label="错误信息" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">{{ row.error_msg || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button link @click="reindex(row)">重建</el-button>
            <el-button link type="danger" @click="removeDocument(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="createDialog" title="新建知识库" width="460px">
      <el-form label-width="88px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" maxlength="128" />
        </el-form-item>
        <el-form-item label="课程代码">
          <el-input v-model="form.course_code" placeholder="留空表示不限课程" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.kba {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.kba__card {
  border-radius: var(--radius-card);
}

.kba__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.kba__title {
  font-size: 18px;
}

.kba__subtitle {
  font-size: 16px;
}

.kba__ops {
  display: flex;
  gap: var(--space-2);
}

.kba__upload {
  margin-bottom: var(--space-4);
}

.kba__upload-icon {
  font-size: 32px;
  color: var(--color-primary);
}

.kba__upload-text {
  font-size: 14px;
  color: var(--color-foreground);
}

.kba__upload-tip {
  font-size: 13px;
  color: var(--color-muted-foreground);
}

.kba__progress-text {
  font-size: 13px;
}

.kba__muted {
  color: var(--color-muted-foreground);
  font-size: 13px;
}
</style>
