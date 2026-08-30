<script setup lang="ts">
import * as codeApi from '@/api/code'
import CodeEditor from '@/components/CodeEditor.vue'
import type {
  CodeRunHistoryItem,
  CodeRunOut,
  CodeSessionOut,
  LimitDetail,
  RunStatus,
} from '@/types/code'
import { Delete, Files, VideoPlay } from '@element-plus/icons-vue'
import { computed, onMounted, ref } from 'vue'

/**
 * 在线代码编辑器页（spec §6.2 code 行 / §8.3）。
 *
 * 术语：代码会话 CodeSession（草稿）、代码运行 CodeRun（一次执行记录）。
 *
 * **安全边界必须显式声明**（ADR-0003）：黑名单只防误触不防攻击，被执行代码
 * 以当前 OS 用户身份运行、对本机文件系统有读权限。这行提示不是免责套话 ——
 * 它是本功能唯一诚实的边界说明，删掉它等于向学生隐瞒风险。
 */

const language = ref<codeApi.CodeLanguage>('python')
const source = ref('')
const stdin = ref('')
const running = ref(false)
const result = ref<CodeRunOut | null>(null)

const drafts = ref<CodeSessionOut[]>([])
const activeDraftId = ref<string | null>(null)
const history = ref<CodeRunHistoryItem[]>([])

const canRun = computed(() => source.value.trim().length > 0 && !running.value)

const STATUS_META: Record<RunStatus, { label: string; type: 'success' | 'info' | 'warning' | 'danger' }> = {
  accepted: { label: '运行成功', type: 'success' },
  runtime_error: { label: '运行出错', type: 'danger' },
  timeout: { label: '超时被终止', type: 'warning' },
  memory_exceeded: { label: '内存超限被终止', type: 'warning' },
  blocked: { label: '命中黑名单，未执行', type: 'info' },
}

const statusMeta = computed(() => (result.value ? STATUS_META[result.value.status] : null))

/** 把 limit_detail 翻成四行人话 —— 学生需要知道「为什么被杀」。 */
const limitRows = computed(() => {
  const d = result.value?.limit_detail as LimitDetail | null
  if (!d) return []
  const mb = (n: number) => `${(n / 1024 / 1024).toFixed(1)} MB`
  return [
    {
      layer: '墙钟超时',
      limit: `${d.wall_clock.limit_s}s`,
      measured: `${(d.wall_clock.elapsed_s * 1000).toFixed(0)} ms`,
      applied: true,
      triggered: d.wall_clock.triggered,
    },
    {
      layer: 'CPU 秒',
      limit: `${d.cpu.limit_s}s`,
      measured: d.cpu.applied ? '已设置' : '未生效',
      applied: d.cpu.applied,
      triggered: d.cpu.triggered,
    },
    {
      layer: '内存',
      limit: mb(d.memory.limit_bytes),
      measured: d.memory.sampled ? `峰值 ${mb(d.memory.peak_bytes)}` : '未采样',
      applied: d.memory.sampled,
      triggered: d.memory.triggered,
    },
    {
      layer: '文件写入',
      limit: mb(d.file_size.limit_bytes),
      measured: d.file_size.applied ? '已设置' : '未生效',
      applied: d.file_size.applied,
      triggered: false,
    },
  ]
})

const degradedLayers = computed(() => {
  const d = result.value?.limit_detail as LimitDetail | null
  return d?.degraded_layers ?? []
})

async function run() {
  if (!canRun.value) return
  running.value = true
  result.value = null
  try {
    const { data } = await codeApi.runCode({
      language: language.value,
      source: source.value,
      stdin: stdin.value,
    })
    result.value = data.data
    await loadHistory()
  } finally {
    running.value = false
  }
}

async function loadDrafts() {
  const { data } = await codeApi.listSessions()
  drafts.value = data.data?.items ?? []
}

async function loadHistory() {
  const { data } = await codeApi.listRuns(1, 10)
  history.value = data.data?.items ?? []
}

async function saveDraft() {
  if (activeDraftId.value) {
    await codeApi.updateSession(activeDraftId.value, {
      language: language.value,
      source_code: source.value,
    })
  } else {
    const { data } = await codeApi.createSession({
      language: language.value,
      title: defaultTitle(),
      source_code: source.value,
    })
    activeDraftId.value = data.data?.id ?? null
  }
  await loadDrafts()
}

function defaultTitle() {
  const firstLine = source.value.split('\n').find((l) => l.trim()) ?? '未命名草稿'
  return firstLine.slice(0, 40)
}

function openDraft(draft: CodeSessionOut) {
  activeDraftId.value = draft.id
  language.value = draft.language
  source.value = draft.source_code
}

function newDraft() {
  activeDraftId.value = null
  source.value = ''
  stdin.value = ''
  result.value = null
}

async function removeDraft(draft: CodeSessionOut) {
  await codeApi.deleteSession(draft.id)
  if (activeDraftId.value === draft.id) activeDraftId.value = null
  await loadDrafts()
}

function loadSample() {
  language.value = 'python'
  source.value = [
    'def bubble_sort(xs):',
    '    n = len(xs)',
    '    for i in range(n):',
    '        for j in range(0, n - i - 1):',
    '            if xs[j] > xs[j + 1]:',
    '                xs[j], xs[j + 1] = xs[j + 1], xs[j]',
    '    return xs',
    '',
    'print(bubble_sort([5, 2, 9, 1, 3]))',
  ].join('\n')
}

function pickHistory(item: CodeRunHistoryItem) {
  language.value = item.language
  source.value = item.source_code
}

onMounted(async () => {
  await Promise.all([loadDrafts(), loadHistory()])
})
</script>

<template>
  <div class="lab">
    <section class="lab__left">
      <div class="lab__bar">
        <el-radio-group v-model="language" :disabled="running">
          <el-radio-button value="python">Python</el-radio-button>
          <el-radio-button value="javascript">JavaScript</el-radio-button>
        </el-radio-group>
        <div class="lab__bar-actions">
          <el-button link :icon="Files" @click="loadSample">填入示例</el-button>
          <el-button link :icon="Files" @click="saveDraft">保存草稿</el-button>
          <el-button
            type="primary"
            :icon="VideoPlay"
            :disabled="!canRun"
            :loading="running"
            @click="run"
          >
            运行
          </el-button>
        </div>
      </div>

      <div class="lab__editor">
        <CodeEditor v-model="source" :language="language" />
      </div>

      <div class="lab__stdin">
        <label class="lab__label" for="stdin">输入（stdin）</label>
        <el-input
          id="stdin"
          v-model="stdin"
          type="textarea"
          :rows="2"
          resize="none"
          placeholder="程序用 input() 读取的内容；留空则不提供输入"
          spellcheck="false"
        />
      </div>
    </section>

    <section class="lab__right">
      <el-alert class="lab__notice" type="warning" show-icon :closable="false" title="安全边界声明">
        被执行代码以当前操作系统用户身份运行，对本机文件系统有读权限。内置的危险调用黑名单
        <strong>只防误触、不防攻击</strong>，可被轻易绕过。请勿运行来源不明的代码。
      </el-alert>

      <div v-if="result && statusMeta" class="lab__status">
        <el-tag :type="statusMeta.type" effect="dark" size="small">{{ statusMeta.label }}</el-tag>
        <el-tag v-if="result.exit_code !== null" size="small" effect="plain">
          exit {{ result.exit_code }}
        </el-tag>
        <el-tag size="small" effect="plain">{{ result.duration_ms }} ms</el-tag>
      </div>

      <div v-if="result" class="card">
        <h3 class="card__title">标准输出</h3>
        <pre class="out">{{ result.stdout || '（无输出）' }}</pre>
      </div>

      <div v-if="result?.stderr" class="card">
        <h3 class="card__title">标准错误</h3>
        <pre class="out out--err">{{ result.stderr }}</pre>
      </div>

      <div v-if="limitRows.length" class="card">
        <h3 class="card__title">限制层实测</h3>
        <el-table :data="limitRows" size="small">
          <el-table-column prop="layer" label="层" width="96" />
          <el-table-column prop="limit" label="阈值" width="80" />
          <el-table-column prop="measured" label="实测" />
          <el-table-column label="生效" width="72">
            <template #default="{ row }">
              <span :class="row.applied ? 'ok' : 'no'">{{ row.applied ? '是' : '否' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="触发" width="72">
            <template #default="{ row }">
              <span :class="row.triggered ? 'no' : 'ok'">{{ row.triggered ? '是' : '否' }}</span>
            </template>
          </el-table-column>
        </el-table>
        <p v-if="degradedLayers.length" class="card__note">
          以下限制层在当前平台未生效：{{ degradedLayers.join('、') }}（spec §9 要求降级可见）
        </p>
      </div>

      <el-empty v-if="!result" description="点击「运行」查看输出" />

      <div class="card">
        <h3 class="card__title">
          草稿
          <el-button link class="card__action" @click="newDraft">新建</el-button>
        </h3>
        <ul v-if="drafts.length" class="list">
          <li v-for="d in drafts" :key="d.id" class="list__row">
            <button type="button" class="list__main" @click="openDraft(d)">
              <span class="list__title">{{ d.title }}</span>
              <span class="list__meta">{{ d.language }}</span>
            </button>
            <el-button link :icon="Delete" class="list__del" @click="removeDraft(d)" />
          </li>
        </ul>
        <p v-else class="card__note">还没有草稿，写点代码后点「保存草稿」。</p>
      </div>

      <div class="card">
        <h3 class="card__title">运行历史</h3>
        <ul v-if="history.length" class="list">
          <li v-for="h in history" :key="h.id" class="list__row">
            <button type="button" class="list__main" @click="pickHistory(h)">
              <span class="list__title">
                <el-tag :type="STATUS_META[h.status].type" size="small" effect="plain">
                  {{ STATUS_META[h.status].label }}
                </el-tag>
              </span>
              <span class="list__meta">{{ h.duration_ms }} ms</span>
            </button>
          </li>
        </ul>
        <p v-else class="card__note">暂无运行记录。</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.lab {
  display: flex;
  gap: var(--space-4);
  height: 100%;
  min-height: 0;
}

.lab__left {
  flex: 3;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
}

.lab__right {
  flex: 2;
  min-width: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
}

.lab__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.lab__bar-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.lab__editor {
  flex: 1;
  min-height: 320px;
}

.lab__stdin {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.lab__label {
  font-size: 13px;
  color: var(--color-muted-foreground);
}

.lab__notice {
  border-radius: var(--radius-card);
}

.lab__status {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.card {
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-background);
}

.card__title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 0 0 var(--space-2);
  font-size: 15px;
}

.card__action {
  cursor: pointer;
  font-size: 13px;
}

.card__note {
  margin: var(--space-2) 0 0;
  font-size: 13px;
  color: var(--color-muted-foreground);
}

.out {
  margin: 0;
  padding: var(--space-2);
  max-height: 220px;
  overflow: auto;
  border-radius: var(--radius-control);
  background: var(--color-muted);
  color: var(--color-foreground);
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

.out--err {
  color: var(--color-destructive);
}

.list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.list__row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  border-radius: var(--radius-control);
  transition: background 200ms ease;
}

.list__row:hover {
  background: var(--color-muted);
}

.list__main {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-2);
  border: none;
  background: transparent;
  color: var(--color-foreground);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.list__main:focus-visible {
  outline: 2px solid var(--color-ring);
  outline-offset: 2px;
}

.list__title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.list__meta {
  flex-shrink: 0;
  font-size: 13px;
  color: var(--color-muted-foreground);
}

.list__del {
  cursor: pointer;
}

.ok {
  color: var(--color-accent);
}

.no {
  color: var(--color-destructive);
}

@media (max-width: 1023px) {
  .lab {
    flex-direction: column;
  }
}
</style>
