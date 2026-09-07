<script setup lang="ts">
import * as adminApi from '@/api/admin'
import { useConfirm } from '@/composables/useConfirm'
import { useNotify } from '@/composables/useNotify'
import { usePagedList } from '@/composables/usePagedList'
import type { AdminExerciseOut } from '@/types/admin'
import { TYPE_LABELS } from '@/types/exercise'
import type { ExerciseType } from '@/types/exercise'
import { computed, reactive, ref } from 'vue'
import {
  UiBadge,
  UiButton,
  UiCard,
  UiDialog,
  UiIcon,
  UiInput,
  UiPagination,
  UiRadioGroup,
  UiSelect,
  UiTextarea,
} from '@/ui'

/** 参考答案按题型的 JSON 形态提示（契约定稿 7）。 */
const ANSWER_PLACEHOLDERS: Record<string, string> = {
  choice: '"B"',
  multi: '["A", "C"]',
  blank: '"要填的答案"',
  short: '"参考答案文本"',
  coding: '{"language": "python", "solution": "参考实现"}',
}
const answerPlaceholder = computed(() => ANSWER_PLACEHOLDERS[form.type] ?? '"…"')

/**
 * 习题管理页（spec §6.2 admin·exercise 行，P6 Task 12，对接 P5 五端点）。
 *
 * 三条口径（P5 契约定稿）：
 * - `source` 与 `created_by` 不由表单决定：创建时服务端写死 `source=admin`、
 *   `created_by=当前管理员`；
 * - PATCH schema 外字段一律 422 —— 表单只提交已知字段；
 * - 发布/下架即改 `status`；删除手工级联删该题提交与错题条目（计数进审计）。
 *
 * 复杂结构字段（options / answer / test_cases / knowledge_tags）用 JSON 文本域编辑，
 * 提交时解析失败会在输入框下方即时提示；后端 422 消息由拦截器弹出。
 */

const notify = useNotify()
const confirm = useConfirm()

const filters = reactive({
  type: '' as ExerciseType | '',
  difficulty: '' as number | '',
  knowledgeTag: '',
  status: '' as 'draft' | 'published' | '',
  pageSize: 10,
})

const list = usePagedList<AdminExerciseOut>(async (page, pageSize) => {
  const { data } = await adminApi.listAdminExercises({
    type: filters.type,
    difficulty: filters.difficulty,
    knowledgeTag: filters.knowledgeTag || undefined,
    status: filters.status,
    page,
    pageSize,
  })
  return { items: data.data?.items ?? [], total: data.data?.total ?? 0 }
}, filters.pageSize)

function search() {
  list.reset()
}

function onPageSize(size: number) {
  filters.pageSize = size
  search()
}

const typeOptions = Object.entries(TYPE_LABELS).map(([value, label]) => ({ label, value }))
const difficultyOptions = [1, 2, 3, 4, 5].map((n) => ({ label: `难度 ${n}`, value: n }))
const statusOptions = [
  { label: '草稿', value: 'draft' },
  { label: '已发布', value: 'published' },
]
const difficultyButtons = [1, 2, 3, 4, 5].map((n) => ({ label: String(n), value: n }))

// ---------------------------------------------------------------- 新建 / 编辑

const dialog = ref(false)
const saving = ref(false)
const editId = ref<string | null>(null)

const form = reactive({
  type: 'choice' as ExerciseType,
  stem: '',
  optionsText: '',
  answerText: '',
  testCasesText: '',
  explanation: '',
  knowledgeTagsText: '',
  difficulty: 1,
  status: 'draft' as 'draft' | 'published',
})

const fieldError = reactive<Record<string, string>>({})

function jsonify(text: string): unknown {
  const value = text.trim()
  if (!value) return null
  try {
    return JSON.parse(value)
  } catch {
    throw new Error(`JSON 解析失败：${value.slice(0, 40)}…`)
  }
}

function resetForm() {
  Object.assign(form, {
    type: 'choice',
    stem: '',
    optionsText: '',
    answerText: '',
    testCasesText: '',
    explanation: '',
    knowledgeTagsText: '',
    difficulty: 1,
    status: 'draft',
  })
  Object.keys(fieldError).forEach((k) => delete fieldError[k])
  editId.value = null
}

function openCreate() {
  resetForm()
  dialog.value = true
}

function openEdit(row: AdminExerciseOut) {
  resetForm()
  editId.value = row.id
  form.type = row.type
  form.stem = row.stem
  form.optionsText = row.options ? JSON.stringify(row.options, null, 2) : ''
  form.answerText = row.answer !== undefined && row.answer !== null ? JSON.stringify(row.answer, null, 2) : ''
  form.testCasesText = row.test_cases ? JSON.stringify(row.test_cases, null, 2) : ''
  form.explanation = row.explanation ?? ''
  form.knowledgeTagsText = (row.knowledge_tags ?? []).join(', ')
  form.difficulty = row.difficulty
  form.status = row.status
  dialog.value = true
}

function buildBody() {
  const body: Record<string, unknown> = {
    type: form.type,
    stem: form.stem,
    difficulty: form.difficulty,
    status: form.status,
  }
  const parse = (key: string, fn: () => unknown) => {
    try {
      return fn()
    } catch (e) {
      fieldError[key] = (e as Error).message
      return undefined
    }
  }
  const options = parse('options', () => jsonify(form.optionsText))
  const answer = parse('answer', () => jsonify(form.answerText))
  const testCases = parse('test_cases', () => jsonify(form.testCasesText))
  const tags = form.knowledgeTagsText
    .split(/[,，]/)
    .map((t) => t.trim())
    .filter(Boolean)
  if (options !== undefined) body.options = options
  if (answer !== undefined) body.answer = answer
  if (testCases !== undefined) body.test_cases = testCases
  if (tags.length) body.knowledge_tags = tags
  return body
}

async function submit() {
  Object.keys(fieldError).forEach((k) => delete fieldError[k])
  const body = buildBody()
  if (Object.values(fieldError).some(Boolean)) return
  if (!form.stem.trim()) {
    notify.warning('请填写题干')
    return
  }
  saving.value = true
  try {
    if (editId.value) {
      await adminApi.updateAdminExercise(editId.value, body)
      notify.success('已保存')
    } else {
      await adminApi.createAdminExercise(body as never)
      notify.success('已创建')
    }
    dialog.value = false
    await list.load()
  } catch {
    // 后端 422（跨题型形状校验等）消息由拦截器弹出
  } finally {
    saving.value = false
  }
}

// ---------------------------------------------------------------- 发布 / 下架 / 删除

async function togglePublish(row: AdminExerciseOut) {
  const target = row.status === 'published' ? 'draft' : 'published'
  const actionText = target === 'published' ? '发布' : '下架'
  try {
    await adminApi.updateAdminExercise(row.id, { status: target })
    notify.success(`已${actionText}`)
    await list.load()
  } catch {
    // 后端 4220 消息由拦截器弹出
  }
}

async function removeExercise(row: AdminExerciseOut) {
  const stem = row.stem.split('\n')[0].slice(0, 30)
  const confirmed = await confirm(
    '删除这道习题将级联删除其全部提交记录与错题条目，且不可恢复。',
    `删除习题：${stem}…`,
  )
  if (!confirmed) return
  try {
    await adminApi.deleteAdminExercise(row.id)
    notify.success('已删除')
    await list.load()
  } catch {
    // 后端消息由拦截器弹出
  }
}

list.load()
</script>

<template>
  <div class="flex flex-col gap-4">
    <UiCard :padded="false">
      <div class="flex flex-wrap items-center gap-2 border-b border-line p-3">
        <UiSelect v-model="filters.type" :options="typeOptions" placeholder="全部题型" clearable class="w-[140px]" @update:model-value="search" />
        <UiSelect v-model="filters.difficulty" :options="difficultyOptions" placeholder="全部难度" clearable class="w-[140px]" @update:model-value="search" />
        <UiInput v-model="filters.knowledgeTag" placeholder="知识点标签" class="w-[180px]" @keyup.enter="search" />
        <UiSelect v-model="filters.status" :options="statusOptions" placeholder="全部状态" clearable class="w-[140px]" @update:model-value="search" />
        <UiButton variant="secondary" @click="search">
          <UiIcon name="RotateCcw" :size="14" />刷新
        </UiButton>
        <UiButton @click="openCreate">
          <UiIcon name="Plus" :size="14" />新建习题
        </UiButton>
      </div>

      <div v-loading="list.loading.value" class="overflow-auto">
        <table class="w-full text-sm">
          <thead class="text-xs text-muted-ink">
            <tr>
              <th class="px-3 py-2 text-left font-medium">题干</th>
              <th class="px-3 py-2 text-left font-medium">题型</th>
              <th class="px-3 py-2 text-left font-medium">难度</th>
              <th class="px-3 py-2 text-left font-medium">知识点</th>
              <th class="px-3 py-2 text-left font-medium">来源</th>
              <th class="px-3 py-2 text-left font-medium">状态</th>
              <th class="px-3 py-2 text-left font-medium">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-line">
            <tr v-for="row in list.items.value" :key="row.id" class="hover:bg-softer">
              <td class="max-w-[280px] px-3 py-2">{{ row.stem.split('\n')[0].slice(0, 40) }}</td>
              <td class="px-3 py-2 text-muted-ink">{{ TYPE_LABELS[row.type as ExerciseType] }}</td>
              <td class="px-3 py-2 text-muted-ink">{{ row.difficulty }}</td>
              <td class="px-3 py-2 text-muted-ink">{{ (row.knowledge_tags ?? []).join('、') || '—' }}</td>
              <td class="px-3 py-2 text-xs text-muted-ink">{{ row.source }}</td>
              <td class="px-3 py-2">
                <UiBadge :variant="row.status === 'published' ? 'success' : 'muted'">
                  {{ row.status === 'published' ? '已发布' : '草稿' }}
                </UiBadge>
              </td>
              <td class="px-3 py-2">
                <div class="flex flex-wrap gap-1">
                  <UiButton variant="link" size="sm" @click="openEdit(row)">编辑</UiButton>
                  <UiButton variant="link" size="sm" @click="togglePublish(row)">
                    {{ row.status === 'published' ? '下架' : '发布' }}
                  </UiButton>
                  <UiButton variant="link" size="sm" @click="removeExercise(row)">删除</UiButton>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="p-3">
        <UiPagination
          :page="list.page.value"
          :total="list.total.value"
          :page-size="filters.pageSize"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          @update:page="list.goto"
          @update:page-size="onPageSize"
        />
      </div>
    </UiCard>

    <UiDialog v-model="dialog" :title="editId ? '编辑习题' : '新建习题'" width="640px">
      <form class="flex flex-col gap-3" @submit.prevent>
        <div class="grid gap-3 sm:grid-cols-2">
          <div class="flex flex-col gap-1">
            <label class="text-sm text-muted-ink">题型</label>
            <UiSelect v-model="form.type" :options="typeOptions" />
          </div>
          <div class="flex flex-col gap-1">
            <label class="text-sm text-muted-ink">难度</label>
            <UiRadioGroup v-model="form.difficulty" :options="difficultyButtons" button size="small" />
          </div>
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">题干</label>
          <UiTextarea v-model="form.stem" :rows="3" />
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">状态</label>
          <UiRadioGroup v-model="form.status" :options="statusOptions" />
        </div>
        <div v-if="['choice', 'multi'].includes(form.type)" class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">选项 options</label>
          <UiTextarea v-model="form.optionsText" :rows="3" monospace placeholder='{"A": "选项文本", "B": "…"}' />
          <p v-if="fieldError.options" class="text-xs text-danger">{{ fieldError.options }}</p>
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">参考答案 answer</label>
          <UiTextarea v-model="form.answerText" :rows="2" monospace :placeholder="answerPlaceholder" />
          <p v-if="fieldError.answer" class="text-xs text-danger">{{ fieldError.answer }}</p>
        </div>
        <div v-if="form.type === 'coding'" class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">测试用例 test_cases</label>
          <UiTextarea v-model="form.testCasesText" :rows="4" monospace placeholder='{"language": "python", "cases": [{"stdin": "", "expected_stdout": "6"}]}' />
          <p v-if="fieldError.test_cases" class="text-xs text-danger">{{ fieldError.test_cases }}</p>
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">解析 explanation</label>
          <UiTextarea v-model="form.explanation" :rows="2" />
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">知识点标签</label>
          <UiInput v-model="form.knowledgeTagsText" placeholder="逗号分隔，如：变量与赋值, 循环" />
        </div>
      </form>
      <template #footer>
        <UiButton variant="secondary" @click="dialog = false">取消</UiButton>
        <UiButton :loading="saving" @click="submit">{{ editId ? '保存' : '创建' }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
