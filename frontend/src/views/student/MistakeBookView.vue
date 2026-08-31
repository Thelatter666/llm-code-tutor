<script setup lang="ts">
import * as mistakeApi from '@/api/mistake'
import { TYPE_LABELS } from '@/types/exercise'
import type {
  MistakeEntryOut,
  RecommendationItemOut,
  WeakKnowledgePointOut,
} from '@/types/mistake'
import { RefreshLeft } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, ref } from 'vue'

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

/**
 * 单块面板的取数：失败只标记自己那一块。
 * `load()` 里三块并行发起，互不牵连。
 */
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
  // Element Plus 的确认框在「取消」时 reject：不接住就是未处理的 rejection
  const confirmed = await ElMessageBox.confirm(
    '重置后这道习题重新进入「未掌握」，连对计数归零；错误次数与上次错误记录会保留。',
    `重置掌握度：${stem}…`,
    { type: 'warning', confirmButtonText: '重置掌握度', cancelButtonText: '取消' },
  ).catch(() => null)
  if (!confirmed) return
  resetting.value = entry.id
  try {
    await mistakeApi.resetMastery(entry.id)
    ElMessage.success('已重置掌握度，该习题回到未掌握状态')
    await load()
  } finally {
    resetting.value = ''
  }
}

const unmasteredCount = computed(() => entries.value.filter((e) => !e.mastered).length)
</script>

<template>
  <div class="mistakes">
    <section class="pane pane--entries">
      <header class="pane__head">
        <h2 class="pane__title">错题本</h2>
        <p class="pane__sub">
          自动归集答错的习题：连续答对 2 次视为已掌握，再答错会回到未掌握。
          <span v-if="filter === 'all'">当前未掌握 {{ unmasteredCount }} 条。</span>
        </p>
      </header>

      <el-radio-group v-model="filter" size="small" @change="reloadFilter">
        <el-radio-button value="all">全部</el-radio-button>
        <el-radio-button value="unmastered">未掌握</el-radio-button>
        <el-radio-button value="mastered">已掌握</el-radio-button>
      </el-radio-group>

      <p v-if="errors.entries" class="error">{{ errors.entries }}</p>
      <ul v-loading="loading" class="list">
        <li v-for="entry in entries" :key="entry.id" class="item">
          <div class="item__head">
            <el-tag size="small" effect="plain">{{ TYPE_LABELS[entry.exercise.type] }}</el-tag>
            <el-tag size="small" type="info" effect="plain">
              难度 {{ entry.exercise.difficulty }}
            </el-tag>
            <el-tag
              v-for="tag in entry.exercise.knowledge_tags"
              :key="tag"
              size="small"
              type="warning"
              effect="plain"
            >
              {{ tag }}
            </el-tag>
            <el-tag v-if="entry.mastered" size="small" type="success" effect="dark">已掌握</el-tag>
            <el-tag v-else size="small" type="danger" effect="plain">未掌握</el-tag>
          </div>

          <p class="item__stem">{{ entry.exercise.stem }}</p>

          <dl class="item__meta">
            <div>
              <dt>错误次数</dt>
              <dd>{{ entry.wrong_count }}</dd>
            </div>
            <div>
              <dt>连续答对</dt>
              <dd>{{ entry.consecutive_correct }} / 2</dd>
            </div>
            <div>
              <dt>最近答错</dt>
              <dd>{{ formatTime(entry.last_wrong_at) }}</dd>
            </div>
            <div v-if="entry.mastered">
              <dt>掌握时间</dt>
              <dd>{{ formatTime(entry.mastered_at) }}</dd>
            </div>
          </dl>

          <p class="item__answer">
            <span class="item__answer-label">上次错误作答</span>
            <code>{{ displayAnswer(entry.last_wrong_answer) }}</code>
          </p>

          <div class="item__actions">
            <router-link :to="{ path: '/exercises', query: { focus: entry.exercise_id } }">
              <el-button size="small" :icon="RefreshLeft" plain>重新练习该习题</el-button>
            </router-link>
            <el-button
              v-if="entry.mastered"
              size="small"
              type="warning"
              plain
              :loading="resetting === entry.id"
              @click="resetMastery(entry)"
            >
              重置掌握度
            </el-button>
          </div>
        </li>
        <li v-if="!entries.length && !loading" class="empty">
          {{
            filter === 'mastered'
              ? '还没有已掌握的习题。连续答对 2 次即视为已掌握。'
              : filter === 'unmastered'
                ? '没有未掌握的习题 —— 继续保持。'
                : '错题本是空的：答错的习题会自动归集到这里。'
          }}
        </li>
      </ul>
    </section>

    <aside class="pane pane--side">
      <section class="block">
        <h3 class="block__title">薄弱知识点</h3>
        <p class="block__sub">按错误次数聚合，已掌握的习题不计入。</p>
        <ul v-if="profile.length" class="bars">
          <li v-for="point in profile" :key="point.knowledge_tag" class="bar">
            <div class="bar__head">
              <span>{{ point.knowledge_tag }}</span>
              <span class="bar__count">{{ point.wrong_count }} 次</span>
            </div>
            <div class="bar__track">
              <div class="bar__fill" :style="{ width: barWidth(point.wrong_count) }"></div>
            </div>
          </li>
        </ul>
        <p v-else-if="errors.profile" class="error">{{ errors.profile }}</p>
        <p v-else class="empty">暂无薄弱知识点数据。</p>
      </section>

      <section class="block">
        <h3 class="block__title">推荐练习</h3>
        <p class="block__sub">
          <template v-if="weakTags.length">
            针对薄弱知识点：{{ weakTags.join('、') }}
          </template>
          <template v-else-if="!entries.length">还没有条目，以下按难度递增随机补足。</template>
          <template v-else>暂无薄弱知识点画像（已掌握的条目不计入），以下随机补足。</template>
        </p>
        <ul class="recs">
          <li v-for="rec in recommendations" :key="rec.exercise.id" class="rec">
            <div class="rec__head">
              <el-tag size="small" effect="plain">{{ TYPE_LABELS[rec.exercise.type] }}</el-tag>
              <el-tag size="small" type="info" effect="plain">
                难度 {{ rec.exercise.difficulty }}
              </el-tag>
              <!-- 随机补足必须可见：否则学生把随机题当个性化推荐（CONTEXT.md RandomFill） -->
              <el-tag v-if="rec.filled_by === 'random'" size="small" type="warning" effect="dark">
                随机补足
              </el-tag>
              <el-tag v-else size="small" type="success" effect="plain">薄弱知识点</el-tag>
            </div>
            <p class="rec__stem">{{ rec.exercise.stem }}</p>
            <router-link :to="{ path: '/exercises', query: { focus: rec.exercise.id } }">
              <el-button size="small" type="primary" plain>去做这道习题</el-button>
            </router-link>
          </li>
          <li v-if="errors.recommendations" class="error">{{ errors.recommendations }}</li>
          <li v-else-if="!recommendations.length" class="empty">题库暂无可推荐的习题。</li>
        </ul>
      </section>
    </aside>
  </div>
</template>

<style scoped>
.mistakes {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 340px);
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

.pane__head {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.pane__title,
.block__title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--color-foreground);
}

.block__title {
  font-size: 14px;
}

.pane__sub,
.block__sub {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--color-muted-foreground);
}

.list,
.recs {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.item,
.rec {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-card);
}

.item__head,
.rec__head {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.item__stem,
.rec__stem {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--color-foreground);
  white-space: pre-wrap;
  word-break: break-word;
}

.item__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin: 0;
}

.item__meta div {
  display: flex;
  gap: var(--space-1);
}

.item__meta dt {
  font-size: 12px;
  color: var(--color-muted-foreground);
}

.item__meta dd {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-foreground);
}

.item__answer {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--space-2);
  margin: 0;
  font-size: 12px;
}

.item__answer-label {
  color: var(--color-muted-foreground);
}

.item__answer code {
  padding: 1px 6px;
  border-radius: var(--radius-control);
  background: var(--color-muted);
  white-space: pre-wrap;
  word-break: break-word;
}

.item__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.block {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.bars {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.bar__head {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--color-foreground);
}

.bar__count {
  color: var(--color-muted-foreground);
}

.bar__track {
  height: 6px;
  border-radius: 999px;
  background: var(--color-muted);
  overflow: hidden;
}

.bar__fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--color-primary), var(--color-accent));
}

.empty {
  font-size: 12px;
  color: var(--color-muted-foreground);
}

.error {
  margin: 0;
  font-size: 12px;
  color: var(--color-destructive);
}

@media (max-width: 1023px) {
  .mistakes {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
