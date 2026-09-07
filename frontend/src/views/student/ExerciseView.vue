<script setup lang="ts">
import * as exerciseApi from '@/api/exercise'
import CodeEditor from '@/components/CodeEditor.vue'
import CitationList from '@/components/CitationList.vue'
import DegradedBanner from '@/components/DegradedBanner.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import { useNotify } from '@/composables/useNotify'
import { newRequestId } from '@/composables/useSse'
import type { Citation } from '@/types/chat'
import type { RunStatus } from '@/types/code'
import type {
  AnswerValue,
  ExerciseDetail,
  ExerciseListItem,
  ExerciseType,
  HintDoneEvent,
  HintIntent,
  JudgeCase,
  SubmitOut,
} from '@/types/exercise'
import { TYPE_LABELS } from '@/types/exercise'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  UiAlert,
  UiBadge,
  UiButton,
  UiCard,
  UiCheckboxGroup,
  UiCollapse,
  UiEmpty,
  UiIcon,
  UiInput,
  UiPagination,
  UiRadioGroup,
  UiSelect,
  UiTextarea,
} from '@/ui'

/**
 * 习题练习页（spec §5.1 判题四路 / §6.2 exercise 行 / §7.1 双意图辅导）。
 *
 * 三条不可让的口径：
 * 1. **提交前不泄题**：正确答案与解析只在判分结果里出现（后端学生详情本就不含）；
 * 2. **hint 双入口显式区分意图**（ADR-0005）：「获取思路」= seek_answer 受防抄袭档位
 *    约束，「批改我的作答」= review_my_code 豁免档位 —— 后者必须有作答才可点；
 * 3. **降级必须可见**：简答题按 judge_mode 区分「AI 参考评分」与
 *    「AI 参考评分（Mock 启发式）」（裁定 5 修订），hint 侧复用 DegradedBanner。
 */

const PAGE_SIZE = 20

/** 支持错题本深链：`/exercises?focus=<exercise_id>` 直接打开指定习题。 */
const route = useRoute()
const notify = useNotify()

const items = ref<ExerciseListItem[]>([])
const total = ref(0)
const facets = ref<string[]>([])
const filterType = ref('')
const filterDifficulty = ref<number | ''>('')
const filterTag = ref('')
const page = ref(1)

const detail = ref<ExerciseDetail | null>(null)
const draft = ref({ choice: '', multi: [] as string[], blank: '', short: '', coding: '' })
const result = ref<SubmitOut | null>(null)
const submitting = ref(false)

interface HintState {
  intent: HintIntent | null
  text: string
  citations: Citation[]
  done: HintDoneEvent | null
  streaming: boolean
}
const hint = ref<HintState>({ intent: null, text: '', citations: [], done: null, streaming: false })
let hintAbort: AbortController | null = null
/** 身份计数：切题与卸载都会中止旧流，那些路径不该弹「已停止生成」。 */
let hintSeq = 0

// ---------------------------------------------------------------- 列表

async function loadList(autoSelect = true) {
  const { data } = await exerciseApi.listExercises({
    type: filterType.value as ExerciseType | '',
    difficulty: filterDifficulty.value,
    knowledgeTag: filterTag.value,
    page: page.value,
    pageSize: PAGE_SIZE,
  })
  const out = data.data
  if (!out) return
  items.value = out.items
  total.value = out.total
  facets.value = out.facets.knowledge_tags
  if (autoSelect && !detail.value && out.items.length) await selectExercise(out.items[0].id)
}

async function selectExercise(id: string) {
  const { data } = await exerciseApi.getExercise(id)
  detail.value = data.data
  draft.value = { choice: '', multi: [], blank: '', short: '', coding: '' }
  result.value = null
  resetHint()
}

watch([filterType, filterDifficulty, filterTag], () => {
  page.value = 1
  void loadList()
})

onMounted(async () => {
  const focus = typeof route.query.focus === 'string' ? route.query.focus : ''
  await loadList(!focus)
  if (focus) await selectExercise(focus)
})

const optionKeys = computed(() => Object.keys(detail.value?.options ?? {}).sort())
const choiceOptions = computed(() => optionKeys.value.map((k) => ({ label: k, value: k })))

const typeOptions = Object.entries(TYPE_LABELS).map(([value, label]) => ({ label, value }))
const difficultyOptions = [1, 2, 3, 4, 5].map((n) => ({ label: `难度 ${n}`, value: n }))
const tagOptions = computed(() => facets.value.map((t) => ({ label: t, value: t })))

function onPage(next: number) {
  page.value = next
  void loadList()
}

const codingLanguage = computed<'python' | 'javascript'>(() =>
  detail.value?.language === 'javascript' ? 'javascript' : 'python',
)

/** 与 submit 同形的作答值（契约定稿 7：编程题只交 source，语言由题库决定）。 */
const answerPayload = computed<AnswerValue>(() => {
  const type = detail.value?.type
  if (!type) return null
  if (type === 'choice') return draft.value.choice
  if (type === 'multi') return draft.value.multi
  if (type === 'blank') return draft.value.blank
  if (type === 'short') return draft.value.short
  return { source: draft.value.coding }
})

const hasAnswer = computed(() => {
  const value = answerPayload.value
  if (typeof value === 'string') return value.trim().length > 0
  if (Array.isArray(value)) return value.length > 0
  if (value && typeof value === 'object') {
    return Object.values(value).some((v) => v.trim().length > 0)
  }
  return false
})

// ---------------------------------------------------------------- 提交判分

async function submit() {
  if (!detail.value || !hasAnswer.value || submitting.value) return
  submitting.value = true
  try {
    const { data } = await exerciseApi.submitExercise(detail.value.id, answerPayload.value)
    result.value = data.data
    if (!result.value) return
    notify.success(
      result.value.is_correct ? `回答正确，得分 ${result.value.score}` : `得分 ${result.value.score}`,
    )
  } finally {
    submitting.value = false
  }
}

const judgeCases = computed<JudgeCase[]>(() => result.value?.judge_detail?.cases ?? [])

/**
 * 执行状态与「是否通过」是两个维度：`status=accepted` 只说明程序正常退出，
 * 输出对不上仍然不通过。文案与 P4 编辑器页同源。
 */
const CASE_STATUS_LABEL: Record<RunStatus, string> = {
  accepted: '输出与期望不符',
  runtime_error: '运行出错',
  timeout: '超时被终止',
  memory_exceeded: '内存超限被终止',
  blocked: '命中黑名单，未执行',
}

function caseTone(row: JudgeCase): 'success' | 'danger' | 'info' {
  if (row.passed) return 'success'
  return row.skipped ? 'info' : 'danger'
}

function caseLabel(row: JudgeCase): string {
  if (row.skipped) return '超时未执行'
  if (row.passed) return '通过'
  return CASE_STATUS_LABEL[row.status] ?? row.status
}

/** 预算上限取后端回传的 budget_limit_s，不在前端写死 15。 */
const budgetLimit = computed(() => result.value?.judge_detail?.budget_limit_s ?? 15)

/** 「AI 参考评分」标识必须区分 judge_mode（裁定 5 修订：Mock 可接受，降级必须可见）。 */
const aiScoreLabel = computed(() => {
  if (!result.value?.ai_scored) return ''
  return result.value.judge_detail?.judge_mode === 'mock_heuristic'
    ? 'AI 参考评分（Mock 启发式）'
    : 'AI 参考评分'
})

function displayAnswer(value: AnswerValue): string {
  if (value === null || value === undefined) return '（无）'
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.join('、')
  const source = value.solution ?? value.source
  if (typeof source === 'string') return source
  return JSON.stringify(value)
}

// ---------------------------------------------------------------- hint（SSE）

function resetHint() {
  hintSeq += 1
  hintAbort?.abort()
  hintAbort = null
  hint.value = { intent: null, text: '', citations: [], done: null, streaming: false }
}

async function askHint(intent: HintIntent) {
  if (!detail.value || hint.value.streaming) return
  if (intent === 'review_my_code' && !hasAnswer.value) {
    notify.warning('「批改我的作答」需要先在作答区写出内容')
    return
  }
  const exerciseId = detail.value.id
  const seq = ++hintSeq
  hintAbort?.abort()
  hint.value = { intent, text: '', citations: [], done: null, streaming: true }
  hintAbort = new AbortController()
  try {
    await exerciseApi.streamExerciseHint({
      exerciseId,
      intent,
      answer: intent === 'review_my_code' ? answerPayload.value : undefined,
      requestId: newRequestId(),
      signal: hintAbort.signal,
      onCitation: (c) => hint.value.citations.push(c),
      onToken: (delta) => {
        hint.value.text += delta
      },
      onDone: (done) => {
        hint.value.done = done
      },
      onError: (err) => {
        if (seq !== hintSeq) return
        if (err.code === 4990) notify.info('已中断生成')
        else notify.error(err.message || '辅导生成失败')
      },
    })
  } catch (e) {
    const err = e as Error
    if (seq !== hintSeq) return
    if (err.name === 'AbortError') notify.info('已停止生成')
    else notify.error(err.message)
  } finally {
    if (seq === hintSeq) {
      hint.value.streaming = false
      hintAbort = null
    }
  }
}

function stopHint() {
  hintAbort?.abort()
}

onBeforeUnmount(() => {
  hintSeq += 1
  hintAbort?.abort()
})

const hintMockProvider = computed(() => hint.value.done?.provider === 'mock')
</script>

<template>
  <div class="grid items-start gap-4 lg:grid-cols-[minmax(280px,360px)_minmax(0,1fr)]">
    <!-- 列表 -->
    <UiCard>
      <template #header>
        <div class="flex flex-col gap-1">
          <h2 class="text-md font-bold text-ink">习题练习</h2>
          <p class="text-sm text-muted-ink">按题型、难度与知识点筛选，作答后提交判分。</p>
        </div>
      </template>

      <div class="flex flex-wrap gap-2">
        <div class="w-[130px]">
          <UiSelect v-model="filterType" :options="typeOptions" placeholder="全部题型" clearable />
        </div>
        <div class="w-[130px]">
          <UiSelect v-model="filterDifficulty" :options="difficultyOptions" placeholder="全部难度" clearable />
        </div>
        <div class="w-[130px]">
          <UiSelect v-model="filterTag" :options="tagOptions" placeholder="全部知识点" clearable />
        </div>
      </div>

      <ul class="mt-3 flex max-h-[60vh] list-none flex-col gap-2 overflow-auto p-0">
        <li v-for="item in items" :key="item.id">
          <button
            type="button"
            class="flex w-full flex-col gap-2 rounded-ctl border px-3 py-2 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
            :class="detail?.id === item.id ? 'border-brand bg-softer' : 'border-line bg-surface hover:bg-softer'"
            @click="selectExercise(item.id)"
          >
            <span class="flex flex-wrap gap-1">
              <UiBadge>{{ TYPE_LABELS[item.type] }}</UiBadge>
              <UiBadge variant="info">难度 {{ item.difficulty }}</UiBadge>
              <UiBadge v-for="tag in item.knowledge_tags" :key="tag" variant="warning">{{ tag }}</UiBadge>
            </span>
            <span class="line-clamp-3 whitespace-pre-wrap text-muted-ink">{{ item.stem }}</span>
          </button>
        </li>
        <li v-if="!items.length" class="text-sm text-muted-ink">当前筛选条件下没有可练习的习题。</li>
      </ul>

      <UiPagination
        v-if="total > PAGE_SIZE"
        class="mt-3"
        :page="page"
        :total="total"
        :page-size="PAGE_SIZE"
        @update:page="onPage"
      />
    </UiCard>

    <!-- 作答区 -->
    <UiCard v-if="!detail">
      <UiEmpty description="请从左侧选择一道习题。" icon="BookOpen" />
    </UiCard>

    <UiCard v-else>
      <template #header>
        <div class="flex flex-col gap-1">
          <h2 class="text-md font-bold text-ink">作答区</h2>
          <p class="m-0 whitespace-pre-wrap break-words text-sm leading-relaxed text-ink">{{ detail.stem }}</p>
        </div>
      </template>

      <div v-if="optionKeys.length" class="rounded-ctl bg-softer p-3 text-sm">
        <div v-for="key in optionKeys" :key="key" class="flex gap-2">
          <span class="font-bold text-brand">{{ key }}</span>
          <span class="text-ink">{{ detail.options?.[key] }}</span>
        </div>
      </div>

      <div class="mt-3 flex flex-col gap-3">
        <UiRadioGroup v-if="detail.type === 'choice'" v-model="draft.choice" :options="choiceOptions" />
        <UiCheckboxGroup v-else-if="detail.type === 'multi'" v-model="draft.multi" :options="choiceOptions" />
        <UiInput v-else-if="detail.type === 'blank'" v-model="draft.blank" placeholder="填写答案" />
        <UiTextarea v-else-if="detail.type === 'short'" v-model="draft.short" :rows="6" placeholder="写下你的解答" />
        <div v-else-if="detail.type === 'coding'" class="min-h-[320px]">
          <CodeEditor :key="detail.id" v-model="draft.coding" :language="codingLanguage" />
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <UiButton :disabled="!hasAnswer || submitting || hint.streaming" :loading="submitting" @click="submit">
            <UiIcon name="Send" :size="14" />提交判分
          </UiButton>
          <UiButton variant="secondary" :disabled="hint.streaming" @click="askHint('seek_answer')">
            <UiIcon name="Lightbulb" :size="14" />获取思路
          </UiButton>
          <UiButton variant="secondary" :disabled="!hasAnswer || hint.streaming" @click="askHint('review_my_code')">
            <UiIcon name="ClipboardCheck" :size="14" />批改我的作答
          </UiButton>
          <UiButton v-if="hint.streaming" variant="ghost" @click="stopHint">
            <UiIcon name="Pause" :size="14" />停止生成
          </UiButton>
          <router-link
            v-if="result && result.is_correct === false"
            to="/mistakes"
            class="text-sm text-brand hover:underline"
          >
            已计入错题本，去看看薄弱知识点
          </router-link>
        </div>
      </div>

      <!-- 判分结果：提交后才揭示正确答案与解析 -->
      <section v-if="result" class="mt-4 flex flex-col gap-2 border-t border-dashed border-line pt-3">
        <h3 class="m-0 flex flex-wrap items-center gap-2 text-base font-bold text-ink">
          判分结果
          <UiBadge :variant="result.is_correct ? 'success' : 'danger'">{{ result.is_correct ? '回答正确' : '回答错误' }}</UiBadge>
          <UiBadge variant="info">得分 {{ result.score }}</UiBadge>
          <UiBadge v-if="aiScoreLabel" variant="warning">{{ aiScoreLabel }}</UiBadge>
          <UiBadge>第 {{ result.attempt_no }} 次作答</UiBadge>
        </h3>

        <UiAlert
          v-if="result.judge_detail?.budget_exceeded"
          variant="warning"
          :title="`用例执行累计超过 ${budgetLimit} 秒，剩余用例已中止`"
          description="按已通过用例的比例计分；未通过的用例请检查是否写入了无限循环或过重计算。"
        />
        <UiAlert v-if="result.judge_detail?.error" variant="error" :title="result.judge_detail.error" />

        <p v-if="result.judge_detail?.missing?.length" class="m-0 text-sm text-ink">
          漏选：{{ result.judge_detail.missing.join('、') }}
        </p>
        <p v-if="result.judge_detail?.wrong?.length" class="m-0 text-sm text-ink">
          错选：{{ result.judge_detail.wrong.join('、') }}
        </p>

        <table v-if="judgeCases.length" class="w-full text-sm">
          <thead class="text-xs text-muted-ink">
            <tr>
              <th class="px-3 py-2 text-left font-medium">用例</th>
              <th class="px-3 py-2 text-left font-medium">输入</th>
              <th class="px-3 py-2 text-left font-medium">期望输出</th>
              <th class="px-3 py-2 text-left font-medium">实际输出</th>
              <th class="px-3 py-2 text-left font-medium">耗时(ms)</th>
              <th class="px-3 py-2 text-left font-medium">结果</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-line">
            <tr v-for="row in judgeCases" :key="row.index">
              <td class="px-3 py-2">{{ row.index }}</td>
              <td class="px-3 py-2 text-xs text-muted-ink">{{ row.stdin || '（无输入）' }}</td>
              <td class="px-3 py-2 text-xs text-muted-ink">{{ row.expected_stdout }}</td>
              <td class="px-3 py-2 text-xs text-muted-ink">{{ row.skipped ? '（未执行）' : row.actual_stdout || '（无输出）' }}</td>
              <td class="px-3 py-2 text-muted-ink">{{ row.duration_ms }}</td>
              <td class="px-3 py-2"><UiBadge :variant="caseTone(row)">{{ caseLabel(row) }}</UiBadge></td>
            </tr>
          </tbody>
        </table>

        <p v-if="result.feedback" class="m-0 rounded-ctl bg-softer px-3 py-2 text-sm leading-relaxed text-ink">
          {{ result.feedback }}
        </p>

        <UiCollapse :items="[{ name: 'reveal', title: '正确答案与解析' }]">
          <template #reveal>
            <pre class="m-0 mb-2 overflow-auto whitespace-pre-wrap break-words rounded-ctl bg-softer p-3 text-sm">{{ displayAnswer(result.correct_answer) }}</pre>
            <p class="m-0 text-sm leading-relaxed text-muted-ink">{{ result.explanation || '（该习题暂无解析）' }}</p>
          </template>
        </UiCollapse>
      </section>

      <!-- AI 辅导：citation 先行 → 流式正文 → done 携带降级与用量 -->
      <section v-if="hint.intent" class="mt-4 flex flex-col gap-2 border-t border-dashed border-line pt-3">
        <h3 class="m-0 flex flex-wrap items-center gap-2 text-base font-bold text-ink">
          {{ hint.intent === 'seek_answer' ? '思路提示' : '我的作答批改' }}
          <UiBadge v-if="hint.done?.provider" variant="info">提供方 {{ hint.done.provider }}</UiBadge>
          <UiBadge v-if="hintMockProvider" variant="warning">Mock 模式</UiBadge>
          <UiBadge v-if="hint.done?.usage_estimated" variant="info">用量按字符估算</UiBadge>
        </h3>

        <DegradedBanner :degraded="Boolean(hint.done?.degraded)" :fallback-reason="hint.done?.fallback_reason ?? null" />

        <p v-if="hint.intent === 'seek_answer'" class="m-0 text-sm text-muted-ink">
          提示只给思路与关键概念，不含完整实现；请自己写出答案后提交判分。
        </p>

        <MarkdownView v-if="hint.text" :content="hint.text" />
        <p v-else-if="!hint.streaming" class="m-0 text-sm text-muted-ink">本次没有返回内容，请稍后重试。</p>
        <p v-if="hint.streaming" class="hint-typing m-0 text-sm text-muted-ink">生成中…</p>

        <CitationList v-if="hint.citations.length" :citations="hint.citations" />
      </section>
    </UiCard>
  </div>
</template>

<style scoped>
/* 基线 §5：生成中提示的呼吸动画；尊重 prefers-reduced-motion */
.hint-typing {
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% {
    opacity: 0.4;
  }
  50% {
    opacity: 1;
  }
}
@media (prefers-reduced-motion: reduce) {
  .hint-typing {
    animation: none;
  }
}
</style>
