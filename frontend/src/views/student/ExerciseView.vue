<script setup lang="ts">
import * as exerciseApi from '@/api/exercise'
import CodeEditor from '@/components/CodeEditor.vue'
import CitationList from '@/components/CitationList.vue'
import DegradedBanner from '@/components/DegradedBanner.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import { newRequestId } from '@/composables/useSse'
import type { Citation } from '@/types/chat'
import type {
  AnswerValue,
  ExerciseDetail,
  ExerciseListItem,
  HintDoneEvent,
  HintIntent,
  JudgeCase,
  SubmitOut,
} from '@/types/exercise'
import { TYPE_LABELS } from '@/types/exercise'
import { MagicStick, Promotion, VideoPause } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

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

/**
 * 支持错题本深链：`/exercises?focus=<exercise_id>` 直接打开指定习题
 * （推荐清单与错题条目里的「去做这道习题」走的就是它）。
 */
const route = useRoute()

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

// ---------------------------------------------------------------- 列表

async function loadList(autoSelect = true) {
  const { data } = await exerciseApi.listExercises({
    type: filterType.value as never,
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
    ElMessage.success(
      result.value.is_correct ? `回答正确，得分 ${result.value.score}` : `得分 ${result.value.score}`,
    )
  } finally {
    submitting.value = false
  }
}

const judgeCases = computed<JudgeCase[]>(() => result.value?.judge_detail?.cases ?? [])

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
  hintAbort?.abort()
  hintAbort = null
  hint.value = { intent: null, text: '', citations: [], done: null, streaming: false }
}

async function askHint(intent: HintIntent) {
  if (!detail.value || hint.value.streaming) return
  if (intent === 'review_my_code' && !hasAnswer.value) {
    ElMessage.warning('「批改我的作答」需要先在作答区写出内容')
    return
  }
  const exerciseId = detail.value.id
  resetHint()
  hint.value.intent = intent
  hint.value.streaming = true
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
        // 4990 是学生主动中断，不是服务端故障（spec §6.1）：只收尾，不弹红色错误
        if (err.code === 4990) ElMessage.info('已中断生成')
        else ElMessage.error(err.message || '辅导生成失败')
      },
    })
  } catch (e) {
    const err = e as Error
    if (err.name === 'AbortError') ElMessage.info('已停止生成')
    else ElMessage.error(err.message)
  } finally {
    if (hint.value.intent === intent) hint.value.streaming = false
    hintAbort = null
  }
}

function stopHint() {
  hintAbort?.abort()
}

onBeforeUnmount(() => hintAbort?.abort())

const hintMockProvider = computed(() => hint.value.done?.provider === 'mock')
</script>

<template>
  <div class="exercises">
    <section class="pane pane--list">
      <header class="pane__head">
        <h2 class="pane__title">习题练习</h2>
        <p class="pane__hint">按题型、难度与知识点筛选，作答后提交判分。</p>
      </header>

      <div class="filters">
        <el-select v-model="filterType" size="small" placeholder="全部题型" clearable>
          <el-option
            v-for="(label, value) in TYPE_LABELS"
            :key="value"
            :label="label"
            :value="value"
          />
        </el-select>
        <el-select v-model="filterDifficulty" size="small" placeholder="全部难度" clearable>
          <el-option v-for="level in [1, 2, 3, 4, 5]" :key="level" :label="`难度 ${level}`" :value="level" />
        </el-select>
        <el-select v-model="filterTag" size="small" placeholder="全部知识点" clearable filterable>
          <el-option v-for="tag in facets" :key="tag" :label="tag" :value="tag" />
        </el-select>
      </div>

      <ul class="list">
        <li v-for="item in items" :key="item.id">
          <button
            type="button"
            class="card"
            :class="{ 'card--active': detail?.id === item.id }"
            @click="selectExercise(item.id)"
          >
            <span class="card__tags">
              <el-tag size="small" effect="plain">{{ TYPE_LABELS[item.type] }}</el-tag>
              <el-tag size="small" type="info" effect="plain">难度 {{ item.difficulty }}</el-tag>
              <el-tag
                v-for="tag in item.knowledge_tags"
                :key="tag"
                size="small"
                type="warning"
                effect="plain"
              >
                {{ tag }}
              </el-tag>
            </span>
            <span class="card__stem">{{ item.stem }}</span>
          </button>
        </li>
        <li v-if="!items.length" class="list__empty">当前筛选条件下没有可练习的习题。</li>
      </ul>

      <el-pagination
        v-if="total > PAGE_SIZE"
        layout="prev, pager, next, total"
        :page-size="PAGE_SIZE"
        :current-page="page"
        :total="total"
        @current-change="
          (next: number) => {
            page = next
            void loadList()
          }
        "
      />
    </section>

    <section class="pane pane--answer">
      <div v-if="!detail" class="list__empty">请从左侧选择一道习题。</div>

      <template v-else>
        <header class="pane__head">
          <h2 class="pane__title">作答区</h2>
          <p class="stem">{{ detail.stem }}</p>
        </header>

        <div v-if="optionKeys.length" class="options">
          <div v-for="key in optionKeys" :key="key" class="options__row">
            <span class="options__key">{{ key }}</span>
            <span>{{ detail.options?.[key] }}</span>
          </div>
        </div>

        <div class="answer">
          <el-radio-group v-if="detail.type === 'choice'" v-model="draft.choice">
            <el-radio v-for="key in optionKeys" :key="key" :value="key">{{ key }}</el-radio>
          </el-radio-group>

          <el-checkbox-group v-else-if="detail.type === 'multi'" v-model="draft.multi">
            <el-checkbox v-for="key in optionKeys" :key="key" :value="key">{{ key }}</el-checkbox>
          </el-checkbox-group>

          <el-input
            v-else-if="detail.type === 'blank'"
            v-model="draft.blank"
            placeholder="填写答案"
            clearable
          />

          <el-input
            v-else-if="detail.type === 'short'"
            v-model="draft.short"
            type="textarea"
            :rows="6"
            placeholder="写下你的解答"
          />

          <div v-else-if="detail.type === 'coding'" class="answer__coding">
            <CodeEditor
              :key="detail.id"
              v-model="draft.coding"
              :language="codingLanguage"
            />
          </div>

          <div class="answer__actions">
            <el-button
              type="primary"
              :icon="Promotion"
              :disabled="!hasAnswer || submitting || hint.streaming"
              :loading="submitting"
              @click="submit"
            >
              提交判分
            </el-button>
            <el-button
              :icon="MagicStick"
              :disabled="hint.streaming"
              @click="askHint('seek_answer')"
            >
              获取思路
            </el-button>
            <el-button
              :disabled="!hasAnswer || hint.streaming"
              :title="hasAnswer ? '' : '需要先在作答区写出内容'"
              @click="askHint('review_my_code')"
            >
              批改我的作答
            </el-button>
            <el-button v-if="hint.streaming" :icon="VideoPause" @click="stopHint">
              停止生成
            </el-button>
            <router-link v-if="result && result.is_correct === false" to="/mistakes" class="inline-link">
              已计入错题本，去看看薄弱知识点
            </router-link>
          </div>
        </div>

        <!-- 判分结果：提交后才揭示正确答案与解析 -->
        <section v-if="result" class="result">
          <h3 class="result__head">
            判分结果
            <el-tag :type="result.is_correct ? 'success' : 'danger'" effect="dark" size="small">
              {{ result.is_correct ? '回答正确' : '回答错误' }}
            </el-tag>
            <el-tag type="info" effect="plain" size="small">得分 {{ result.score }}</el-tag>
            <el-tag v-if="aiScoreLabel" type="warning" effect="plain" size="small">
              {{ aiScoreLabel }}
            </el-tag>
            <el-tag effect="plain" size="small">第 {{ result.attempt_no }} 次作答</el-tag>
          </h3>

          <el-alert
            v-if="result.judge_detail?.budget_exceeded"
            type="warning"
            show-icon
            :closable="false"
            title="用例执行累计超过 15 秒，剩余用例已中止"
            description="按已通过用例的比例计分；未通过的用例请检查是否写入了无限循环或过重计算。"
          />
          <el-alert
            v-if="result.judge_detail?.error"
            type="error"
            show-icon
            :closable="false"
            :title="result.judge_detail.error"
          />

          <p v-if="result.judge_detail?.missing?.length" class="result__line">
            漏选：{{ result.judge_detail.missing.join('、') }}
          </p>
          <p v-if="result.judge_detail?.wrong?.length" class="result__line">
            错选：{{ result.judge_detail.wrong.join('、') }}
          </p>

          <el-table v-if="judgeCases.length" :data="judgeCases" size="small" class="result__table">
            <el-table-column prop="index" label="用例" width="56" />
            <el-table-column label="输入" min-width="90">
              <template #default="{ row }">
                <code class="cell">{{ row.stdin || '（无输入）' }}</code>
              </template>
            </el-table-column>
            <el-table-column label="期望输出" min-width="90">
              <template #default="{ row }">
                <code class="cell">{{ row.expected_stdout }}</code>
              </template>
            </el-table-column>
            <el-table-column label="实际输出" min-width="90">
              <template #default="{ row }">
                <code class="cell">{{ row.skipped ? '（未执行）' : row.actual_stdout || '（无输出）' }}</code>
              </template>
            </el-table-column>
            <el-table-column prop="duration_ms" label="耗时(ms)" width="86" />
            <el-table-column label="结果" width="110">
              <template #default="{ row }">
                <el-tag v-if="row.skipped" size="small" type="info">超时中止</el-tag>
                <el-tag v-else-if="row.passed" size="small" type="success">通过</el-tag>
                <el-tag v-else size="small" type="danger">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
          </el-table>

          <p v-if="result.feedback" class="result__feedback">{{ result.feedback }}</p>

          <el-collapse class="result__reveal">
            <el-collapse-item title="正确答案与解析" name="reveal">
              <pre class="reveal__answer">{{ displayAnswer(result.correct_answer) }}</pre>
              <p class="reveal__text">{{ result.explanation || '（该习题暂无解析）' }}</p>
            </el-collapse-item>
          </el-collapse>
        </section>

        <!-- AI 辅导：citation 先行 → 流式正文 → done 携带降级与用量 -->
        <section v-if="hint.intent" class="hint">
          <h3 class="result__head">
            {{ hint.intent === 'seek_answer' ? '思路提示' : '我的作答批改' }}
            <el-tag v-if="hint.done?.provider" size="small" effect="plain">
              提供方 {{ hint.done.provider }}
            </el-tag>
            <el-tag v-if="hintMockProvider" size="small" type="warning" effect="plain">
              Mock 模式
            </el-tag>
            <el-tag v-if="hint.done?.usage_estimated" size="small" type="info" effect="plain">
              用量按字符估算
            </el-tag>
          </h3>

          <DegradedBanner
            :degraded="Boolean(hint.done?.degraded)"
            :fallback-reason="hint.done?.fallback_reason ?? null"
          />

          <p v-if="hint.intent === 'seek_answer'" class="hint__note">
            提示只给思路与关键概念，不含完整实现；请自己写出答案后提交判分。
          </p>

          <MarkdownView v-if="hint.text" :content="hint.text" />
          <p v-else-if="!hint.streaming" class="hint__note">本次没有返回内容，请稍后重试。</p>
          <p v-if="hint.streaming" class="hint__typing">生成中…</p>

          <CitationList v-if="hint.citations.length" :citations="hint.citations" />
        </section>
      </template>
    </section>
  </div>
</template>

<style scoped>
.exercises {
  display: grid;
  grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
  gap: var(--space-4);
  align-items: start;
}

.pane {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-card);
  min-width: 0;
}

.pane__title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--color-foreground);
}

.pane__head {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.pane__hint {
  margin: 0;
  font-size: 13px;
  color: var(--color-muted-foreground);
}

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.filters :deep(.el-select) {
  width: 130px;
}

.list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-height: 60vh;
  overflow: auto;
}

.list__empty {
  font-size: 13px;
  color: var(--color-muted-foreground);
}

.card {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-card);
  color: var(--color-foreground);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition: background 200ms ease, border-color 200ms ease;
}

.card:hover {
  background: var(--color-muted);
}

.card:focus-visible {
  outline: 2px solid var(--color-ring);
  outline-offset: 2px;
}

.card--active {
  border-color: var(--color-primary);
  background: var(--color-muted);
}

.card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.card__stem {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  color: var(--color-muted-foreground);
  white-space: pre-wrap;
}

.stem {
  margin: 0;
  font-size: 14px;
  line-height: 1.7;
  color: var(--color-foreground);
  white-space: pre-wrap;
  word-break: break-word;
}

.options {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-3);
  border-radius: var(--radius-control);
  background: var(--color-muted);
  font-size: 13px;
}

.options__row {
  display: flex;
  gap: var(--space-2);
}

.options__key {
  font-weight: 700;
  color: var(--color-primary);
}

.answer {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.answer__coding {
  min-height: 320px;
}

.answer__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.inline-link {
  font-size: 13px;
  color: var(--color-primary);
}

.result,
.hint {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-top: var(--space-3);
  border-top: 1px dashed var(--color-border);
}

.result__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-foreground);
}

.result__line,
.result__feedback {
  margin: 0;
  font-size: 13px;
  color: var(--color-foreground);
}

.result__feedback {
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-control);
  background: var(--color-muted);
  line-height: 1.6;
}

.result__table {
  width: 100%;
}

.cell {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
}

.result__reveal {
  border-top: none;
}

.reveal__answer {
  margin: 0 0 var(--space-2);
  padding: var(--space-3);
  border-radius: var(--radius-control);
  background: var(--color-muted);
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-word;
  overflow: auto;
}

.reveal__text {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--color-muted-foreground);
  white-space: pre-wrap;
}

.hint__note,
.hint__typing {
  margin: 0;
  font-size: 12px;
  color: var(--color-muted-foreground);
}

.hint__typing {
  animation: pulse 1.2s ease-in-out infinite;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 0.4;
  }
  50% {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .hint__typing {
    animation: none;
  }
}

@media (max-width: 1023px) {
  .exercises {
    grid-template-columns: minmax(0, 1fr);
  }

  .list {
    max-height: none;
  }
}
</style>
