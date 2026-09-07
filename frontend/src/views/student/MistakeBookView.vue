<script setup lang="ts">
import * as mistakeApi from '@/api/mistake'
import { useConfirm } from '@/composables/useConfirm'
import { useNotify } from '@/composables/useNotify'
import { TYPE_LABELS } from '@/types/exercise'
import type {
  MistakeEntryOut,
  RecommendationItemOut,
  WeakKnowledgePointOut,
} from '@/types/mistake'
import { computed, onMounted, ref } from 'vue'
import { UiBadge, UiButton, UiCard, UiEmpty, UiIcon, UiRadioGroup } from '@/ui'

/**
 * 错题本页（spec §8.5 / §6.2 mistake 行）。
 *
 * 三块内容各自守一条口径：
 * 1. **条目列表**：mastered 三态筛选；已掌握条目默认仍在「全部」里可见 ——
 *    错题驱动学习要求「掌握了又做错」能重新浮现，所以状态标签必须显眼；
 * 2. **薄弱知识点画像**：排除已掌握的实时聚合，是推荐的依据；
 * 3. **定向推荐**：`filled_by=random` 的条目必须标注「随机补足」，
 *    否则学生会把随机题误当个性化推荐（CONTEXT.md「随机补足」消歧说明）。
 *
 * 「重置掌握度」按裁定 2 清零连对计数（开启新一轮），但 wrong_count 与
 * 上次错误记录是历史，保留 —— 页面文案如实说明这一点，避免学生以为是删除。
 */

type MasteredFilter = 'all' | 'unmastered' | 'mastered'

const FILTER_OPTIONS = [
  { label: '全部', value: 'all' },
  { label: '未掌握', value: 'unmastered' },
  { label: '已掌握', value: 'mastered' },
]

const notify = useNotify()
const confirm = useConfirm()

const entries = ref<MistakeEntryOut[]>([])
const profile = ref<WeakKnowledgePointOut[]>([])
const recommendations = ref<RecommendationItemOut[]>([])
const weakTags = ref<string[]>([])
const filter = ref<MasteredFilter>('all')
const loading = ref(false)
const resetting = ref('')

const masteredParam = computed(() =>
  filter.value === 'all' ? undefined : filter.value === 'mastered',
)

/** 画像里最高的 wrong_count，供条形宽度归一化（无数据时避免除零）。 */
const peakWrong = computed(() => profile.value.reduce((max, p) => Math.max(max, p.wrong_count), 0))

/** 三块面板各自独立的错误态：一个接口失败不该把已取到的条目与画像一起清空。 */
const errors = ref({ entries: '', profile: '', recommendations: '' })

async function loadOne<T>(
  key: keyof typeof errors.value,
  request: () => Promise<{ data: { data: T | null } }>,
  assign: (value: T) => void,
) {
  errors.value[key] = ''
  try {
    const { data } = await request()
    assign(data.data ?? ([] as never))
  } catch {
    errors.value[key] = '加载失败，请稍后重试'
  }
}

async function load() {
  loading.value = true
  try {
    await Promise.all([
      loadOne('entries', () => mistakeApi.listMistakes(masteredParam.value), (v) => {
        entries.value = v
      }),
      loadOne('profile', mistakeApi.getProfile, (v) => {
        profile.value = v
      }),
      loadOne('recommendations', () => mistakeApi.getRecommendations(5), (v) => {
        recommendations.value = v.items
        weakTags.value = v.weak_tags
      }),
    ])
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function reloadFilter() {
  await loadOne('entries', () => mistakeApi.listMistakes(masteredParam.value), (v) => {
    entries.value = v
  })
}

/** UTC 直读，不做本地化换算 —— 演示机上标了时区反而容易误读。 */
function formatTime(iso: string | null): string {
  if (!iso) return '—'
  return `${iso.slice(0, 16).replace('T', ' ')} UTC`
}

function displayAnswer(value: MistakeEntryOut['last_wrong_answer']): string {
  if (value === null || value === undefined) return '（无记录）'
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.join('、')
  const source = value.solution ?? value.source
  if (typeof source === 'string') return source
  return JSON.stringify(value)
}

function barWidth(count: number): string {
  if (!peakWrong.value) return '0%'
  return `${Math.max(6, Math.round((count / peakWrong.value) * 100))}%`
}

async function resetMastery(entry: MistakeEntryOut) {
  const stem = entry.exercise.stem.split('\n')[0].slice(0, 30)
  if (
    !(await confirm(
      '重置后这道习题重新进入「未掌握」，连对计数归零；错误次数与上次错误记录会保留。',
      `重置掌握度：${stem}…`,
    ))
  ) {
    return
  }
  resetting.value = entry.id
  try {
    await mistakeApi.resetMastery(entry.id)
    notify.success('已重置掌握度，该习题回到未掌握状态')
    await load()
  } finally {
    resetting.value = ''
  }
}

const unmasteredCount = computed(() => entries.value.filter((e) => !e.mastered).length)
</script>

<template>
  <div class="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(260px,340px)]">
    <!-- 条目列表 -->
    <UiCard>
      <template #header>
        <div class="flex flex-col gap-1">
          <h2 class="text-md font-bold text-ink">错题本</h2>
          <p class="text-sm text-muted-ink">
            自动归集答错的习题：连续答对 2 次视为已掌握，再答错会回到未掌握。
            <span v-if="filter === 'all'">当前未掌握 {{ unmasteredCount }} 条。</span>
          </p>
        </div>
      </template>

      <UiRadioGroup v-model="filter" :options="FILTER_OPTIONS" button size="small" @change="reloadFilter" />

      <p v-if="errors.entries" class="text-sm text-danger">{{ errors.entries }}</p>
      <ul v-loading="loading" class="m-0 flex list-none flex-col gap-3 p-0">
        <li
          v-for="entry in entries"
          :key="entry.id"
          class="flex flex-col gap-2 rounded-ctl border border-line bg-surface p-3"
        >
          <div class="flex flex-wrap gap-1">
            <UiBadge>{{ TYPE_LABELS[entry.exercise.type] }}</UiBadge>
            <UiBadge variant="info">难度 {{ entry.exercise.difficulty }}</UiBadge>
            <UiBadge v-for="tag in entry.exercise.knowledge_tags" :key="tag" variant="warning">{{ tag }}</UiBadge>
            <UiBadge v-if="entry.mastered" variant="success">已掌握</UiBadge>
            <UiBadge v-else variant="danger">未掌握</UiBadge>
          </div>

          <p class="m-0 whitespace-pre-wrap break-words text-sm leading-relaxed text-ink">{{ entry.exercise.stem }}</p>

          <dl class="m-0 flex flex-wrap gap-3">
            <div class="flex gap-1">
              <dt class="text-xs text-muted-ink">错误次数</dt>
              <dd class="m-0 text-xs font-semibold text-ink">{{ entry.wrong_count }}</dd>
            </div>
            <div class="flex gap-1">
              <dt class="text-xs text-muted-ink">连续答对</dt>
              <dd class="m-0 text-xs font-semibold text-ink">{{ entry.consecutive_correct }} / 2</dd>
            </div>
            <div class="flex gap-1">
              <dt class="text-xs text-muted-ink">最近答错</dt>
              <dd class="m-0 text-xs font-semibold text-ink">{{ formatTime(entry.last_wrong_at) }}</dd>
            </div>
            <div v-if="entry.mastered" class="flex gap-1">
              <dt class="text-xs text-muted-ink">掌握时间</dt>
              <dd class="m-0 text-xs font-semibold text-ink">{{ formatTime(entry.mastered_at) }}</dd>
            </div>
          </dl>

          <p class="m-0 flex flex-wrap items-baseline gap-2 text-xs">
            <span class="text-muted-ink">上次错误作答</span>
            <code class="rounded-ctl bg-softer px-1.5 py-0.5 whitespace-pre-wrap break-words">{{ displayAnswer(entry.last_wrong_answer) }}</code>
          </p>

          <div class="flex flex-wrap gap-2">
            <router-link :to="{ path: '/exercises', query: { focus: entry.exercise_id } }">
              <UiButton variant="secondary" size="sm">
                <UiIcon name="RotateCcw" :size="14" />重新练习该习题
              </UiButton>
            </router-link>
            <UiButton
              v-if="entry.mastered"
              variant="secondary"
              size="sm"
              :loading="resetting === entry.id"
              @click="resetMastery(entry)"
            >
              重置掌握度
            </UiButton>
          </div>
        </li>
        <li v-if="!entries.length && !loading">
          <UiEmpty
            :description="
              filter === 'mastered'
                ? '还没有已掌握的习题。连续答对 2 次即视为已掌握。'
                : filter === 'unmastered'
                  ? '没有未掌握的习题 —— 继续保持。'
                  : '错题本是空的：答错的习题会自动归集到这里。'
            "
            icon="NotebookPen"
          />
        </li>
      </ul>
    </UiCard>

    <!-- 侧栏：薄弱知识点画像 + 定向推荐 -->
    <div class="flex flex-col gap-4">
      <UiCard title="薄弱知识点" :padded="false">
        <div class="flex flex-col gap-2 p-4">
          <p class="m-0 text-xs text-muted-ink">按错误次数聚合，已掌握的习题不计入。</p>
          <ul v-if="profile.length" class="m-0 flex list-none flex-col gap-2 p-0">
            <li v-for="point in profile" :key="point.knowledge_tag">
              <div class="flex justify-between text-xs text-ink">
                <span>{{ point.knowledge_tag }}</span>
                <span class="text-muted-ink">{{ point.wrong_count }} 次</span>
              </div>
              <div class="mt-1 h-1.5 overflow-hidden rounded-pill bg-softer">
                <div
                  class="h-full rounded-pill bg-gradient-to-r from-brand to-highlight transition-[width] duration-base ease-smooth"
                  :style="{ width: barWidth(point.wrong_count) }"
                />
              </div>
            </li>
          </ul>
          <p v-else-if="errors.profile" class="text-sm text-danger">{{ errors.profile }}</p>
          <p v-else class="text-sm text-muted-ink">暂无薄弱知识点数据。</p>
        </div>
      </UiCard>

      <UiCard title="推荐练习" :padded="false">
        <div class="flex flex-col gap-2 p-4">
          <p class="m-0 text-xs leading-relaxed text-muted-ink">
            <template v-if="weakTags.length">针对薄弱知识点：{{ weakTags.join('、') }}</template>
            <template v-else-if="!entries.length">还没有条目，以下按难度递增随机补足。</template>
            <template v-else>暂无薄弱知识点画像（已掌握的条目不计入），以下随机补足。</template>
          </p>
          <ul class="m-0 flex list-none flex-col gap-3 p-0">
            <li
              v-for="rec in recommendations"
              :key="rec.exercise.id"
              class="flex flex-col gap-2 rounded-ctl border border-line bg-surface p-3"
            >
              <div class="flex flex-wrap gap-1">
                <UiBadge>{{ TYPE_LABELS[rec.exercise.type] }}</UiBadge>
                <UiBadge variant="info">难度 {{ rec.exercise.difficulty }}</UiBadge>
                <!-- 随机补足必须可见：否则学生把随机题当个性化推荐（CONTEXT.md RandomFill） -->
                <UiBadge v-if="rec.filled_by === 'random'" variant="warning">随机补足</UiBadge>
                <UiBadge v-else variant="success">薄弱知识点</UiBadge>
              </div>
              <p class="m-0 whitespace-pre-wrap break-words text-sm leading-relaxed text-ink">{{ rec.exercise.stem }}</p>
              <router-link :to="{ path: '/exercises', query: { focus: rec.exercise.id } }">
                <UiButton size="sm">
                  <UiIcon name="ArrowRight" :size="14" />去做这道习题
                </UiButton>
              </router-link>
            </li>
            <li v-if="errors.recommendations" class="text-sm text-danger">{{ errors.recommendations }}</li>
            <li v-else-if="!recommendations.length" class="text-sm text-muted-ink">题库暂无可推荐的习题。</li>
          </ul>
        </div>
      </UiCard>
    </div>
  </div>
</template>
