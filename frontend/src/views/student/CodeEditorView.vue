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
import { computed, onMounted, ref } from 'vue'
import { UiAlert, UiBadge, UiButton, UiCard, UiEmpty, UiIcon, UiRadioGroup, UiTextarea } from '@/ui'

/**
 * 在线代码编辑器页（spec §6.2 code 行 / §8.3）。
 *
 * 术语：代码会话 CodeSession、代码运行 CodeRun（一次执行记录）。
 *
 * **安全边界必须显式声明**（ADR-0003）：黑名单只防误触不防攻击，被执行代码
 * 以当前 OS 用户身份运行、对本机文件系统有读权限。这行提示不是免责套话 ——
 * 它是本功能唯一诚实的边界说明，删掉它等于向学生隐瞒风险。
 */

const LANGUAGE_OPTIONS = [
  { label: 'Python', value: 'python' },
  { label: 'JavaScript', value: 'javascript' },
]

const language = ref<codeApi.CodeLanguage>('python')
const source = ref('')
const stdin = ref('')
const running = ref(false)
const result = ref<CodeRunOut | null>(null)

const drafts = ref<CodeSessionOut[]>([])
const activeDraftId = ref<string | null>(null)
const history = ref<CodeRunHistoryItem[]>([])

const canRun = computed(() => source.value.trim().length > 0 && !running.value)

const STATUS_META: Record<
  RunStatus,
  { label: string; variant: 'success' | 'info' | 'warning' | 'danger' }
> = {
  accepted: { label: '运行成功', variant: 'success' },
  runtime_error: { label: '运行出错', variant: 'danger' },
  timeout: { label: '超时被终止', variant: 'warning' },
  memory_exceeded: { label: '内存超限被终止', variant: 'warning' },
  blocked: { label: '命中黑名单，未执行', variant: 'info' },
}

const statusMeta = computed(() => (result.value ? STATUS_META[result.value.status] : null))

function mb(n: number) {
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

const limitRows = computed(() => {
  const d = result.value?.limit_detail as LimitDetail | null
  if (!d) return []
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
  const firstLine = source.value.split('\n').find((l) => l.trim()) ?? '未命名会话'
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
  <div class="flex h-full min-h-0 flex-col gap-4 lg:flex-row">
    <!-- 左侧：编辑区 -->
    <UiCard class="flex min-h-0 flex-[3] flex-col">
      <template #header>
        <UiRadioGroup v-model="language" :options="LANGUAGE_OPTIONS" button :disabled="running" />
        <div class="flex items-center gap-2">
          <UiButton variant="link" size="sm" @click="loadSample">
            <UiIcon name="Sparkles" :size="14" />填入示例
          </UiButton>
          <UiButton variant="link" size="sm" @click="saveDraft">
            <UiIcon name="Save" :size="14" />保存会话
          </UiButton>
          <UiButton :disabled="!canRun" :loading="running" @click="run">
            <UiIcon name="Play" :size="14" />运行
          </UiButton>
        </div>
      </template>

      <div class="min-h-[320px] flex-1">
        <CodeEditor v-model="source" :language="language" />
      </div>

      <template #footer>
        <div class="flex flex-col gap-1">
          <label for="stdin" class="text-sm text-muted-ink">输入（stdin）</label>
          <UiTextarea
            id="stdin"
            v-model="stdin"
            :rows="2"
            monospace
            placeholder="程序用 input() 读取的内容；留空则不提供输入"
            spellcheck="false"
          />
        </div>
      </template>
    </UiCard>

    <!-- 右侧：结果与会话 -->
    <div class="flex min-h-0 flex-[2] flex-col gap-4 overflow-auto">
      <UiAlert variant="warning" title="安全边界声明">
        被执行代码以当前操作系统用户身份运行，对本机文件系统有读权限。内置的危险调用黑名单
        <strong>只防误触、不防攻击</strong>，可被轻易绕过。请勿运行来源不明的代码。
      </UiAlert>

      <div v-if="result && statusMeta" class="flex flex-wrap gap-2">
        <UiBadge :variant="statusMeta.variant">{{ statusMeta.label }}</UiBadge>
        <UiBadge v-if="result.exit_code !== null">exit {{ result.exit_code }}</UiBadge>
        <UiBadge>{{ result.duration_ms }} ms</UiBadge>
      </div>

      <UiCard v-if="result" title="标准输出" :padded="false">
        <pre class="m-0 max-h-[220px] overflow-auto rounded-ctl bg-softer p-2 font-mono text-[13px] leading-relaxed text-ink whitespace-pre-wrap break-all">{{ result.stdout || '（无输出）' }}</pre>
      </UiCard>

      <UiCard v-if="result?.stderr" title="标准错误" :padded="false">
        <pre class="m-0 max-h-[220px] overflow-auto rounded-ctl bg-softer p-2 font-mono text-[13px] leading-relaxed text-danger whitespace-pre-wrap break-all">{{ result.stderr }}</pre>
      </UiCard>

      <UiCard v-if="limitRows.length" title="限制层实测" :padded="false">
        <table class="w-full text-sm">
          <thead class="text-xs text-muted-ink">
            <tr>
              <th class="px-3 py-2 text-left font-medium">层</th>
              <th class="px-3 py-2 text-left font-medium">阈值</th>
              <th class="px-3 py-2 text-left font-medium">实测</th>
              <th class="px-3 py-2 text-left font-medium">生效</th>
              <th class="px-3 py-2 text-left font-medium">触发</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-line">
            <tr v-for="row in limitRows" :key="row.layer">
              <td class="px-3 py-2">{{ row.layer }}</td>
              <td class="px-3 py-2 text-muted-ink">{{ row.limit }}</td>
              <td class="px-3 py-2 text-muted-ink">{{ row.measured }}</td>
              <td class="px-3 py-2" :class="row.applied ? 'text-highlight' : 'text-danger'">{{ row.applied ? '是' : '否' }}</td>
              <td class="px-3 py-2" :class="row.triggered ? 'text-danger' : 'text-highlight'">{{ row.triggered ? '是' : '否' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="degradedLayers.length" class="px-3 py-2 text-sm text-muted-ink">
          以下限制层在当前平台未生效：{{ degradedLayers.join('、') }}（spec §9 要求降级可见）
        </p>
      </UiCard>

      <UiEmpty v-if="!result" description="点击「运行」查看输出" icon="Terminal" />

      <UiCard>
        <template #header>
          <h3 class="text-md font-semibold text-ink">会话</h3>
          <UiButton variant="link" size="sm" @click="newDraft">
            <UiIcon name="Plus" :size="14" />新建
          </UiButton>
        </template>
        <ul v-if="drafts.length" class="m-0 flex list-none flex-col gap-1 p-0">
          <li v-for="d in drafts" :key="d.id" class="flex items-center gap-2 rounded-ctl px-1 py-1 transition-colors hover:bg-softer">
            <button
              type="button"
              class="flex min-w-0 flex-1 items-center justify-between gap-2 rounded-ctl px-2 py-1 text-left text-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
              @click="openDraft(d)"
            >
              <span class="min-w-0 flex-1 truncate">{{ d.title }}</span>
              <span class="shrink-0 text-sm text-muted-ink">{{ d.language }}</span>
            </button>
            <UiButton variant="ghost" size="icon-sm" aria-label="删除会话" @click="removeDraft(d)">
              <UiIcon name="Trash2" :size="14" />
            </UiButton>
          </li>
        </ul>
        <p v-else class="text-sm text-muted-ink">还没有会话，写点代码后点「保存会话」。</p>
      </UiCard>

      <UiCard title="运行历史" :padded="false">
        <ul v-if="history.length" class="m-0 flex list-none flex-col gap-1 p-3">
          <li v-for="h in history" :key="h.id">
            <button
              type="button"
              class="flex w-full items-center justify-between gap-2 rounded-ctl px-2 py-1 text-left text-sm text-ink transition-colors hover:bg-softer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
              @click="pickHistory(h)"
            >
              <span class="flex items-center gap-2">
                <UiBadge :variant="STATUS_META[h.status].variant">{{ STATUS_META[h.status].label }}</UiBadge>
              </span>
              <span class="shrink-0 text-sm text-muted-ink">{{ h.duration_ms }} ms</span>
            </button>
          </li>
        </ul>
        <p v-else class="p-3 text-sm text-muted-ink">暂无运行记录。</p>
      </UiCard>
    </div>
  </div>
</template>
