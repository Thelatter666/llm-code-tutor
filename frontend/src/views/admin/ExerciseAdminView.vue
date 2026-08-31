<script setup lang="ts">
import * as adminApi from '@/api/admin'
import type { AdminExerciseOut } from '@/types/admin'
import { TYPE_LABELS } from '@/types/exercise'
import type { ExerciseType } from '@/types/exercise'
import { Delete, Plus, RefreshLeft } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

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

const items = ref<AdminExerciseOut[]>([])
const total = ref(0)
const loading = ref(false)

const filters = reactive({
  type: '' as ExerciseType | '',
  difficulty: '' as number | '',
  knowledgeTag: '',
  status: '' as 'draft' | 'published' | '',
  page: 1,
  pageSize: 10,
})

async function load() {
  loading.value = true
  try {
    const { data } = await adminApi.listAdminExercises({
      type: filters.type,
      difficulty: filters.difficulty,
      knowledgeTag: filters.knowledgeTag || undefined,
      status: filters.status,
      page: filters.page,
      pageSize: filters.pageSize,
    })
    items.value = data.data?.items ?? []
    total.value = data.data?.total ?? 0
  } finally {
    loading.value = false
  }
}

function search() {
  filters.page = 1
  load()
}

function formatTime(iso: string): string {
  return `${iso.slice(0, 16).replace('T', ' ')} UTC`
}

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
    ElMessage.warning('请填写题干')
    return
  }
  saving.value = true
  try {
    if (editId.value) {
      await adminApi.updateAdminExercise(editId.value, body)
      ElMessage.success('已保存')
    } else {
      await adminApi.createAdminExercise(body as never)
      ElMessage.success('已创建')
    }
    dialog.value = false
    await load()
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
    ElMessage.success(`已${actionText}`)
    await load()
  } catch {
    // 后端 4220 消息由拦截器弹出
  }
}

async function removeExercise(row: AdminExerciseOut) {
  const stem = row.stem.split('\n')[0].slice(0, 30)
  const confirmed = await ElMessageBox.confirm(
    `删除这道习题将级联删除其全部提交记录与错题条目，且不可恢复。`,
    `删除习题：${stem}…`,
    { type: 'error', confirmButtonText: '删除', cancelButtonText: '取消' },
  ).catch(() => null)
  if (!confirmed) return
  try {
    await adminApi.deleteAdminExercise(row.id)
    ElMessage.success('已删除')
    await load()
  } catch {
    // 后端消息由拦截器弹出
  }
}

onMounted(load)
</script>

<template>
  <div class="ex-admin-page">
    <div class="ex-admin-page__toolbar">
      <el-select v-model="filters.type" placeholder="全部题型" clearable class="ex-admin-page__select" @change="search">
        <el-option v-for="(label, key) in TYPE_LABELS" :key="key" :label="label" :value="key" />
      </el-select>
      <el-select v-model="filters.difficulty" placeholder="全部难度" clearable class="ex-admin-page__select" @change="search">
        <el-option v-for="d in 5" :key="d" :label="`难度 ${d}`" :value="d" />
      </el-select>
      <el-input
        v-model="filters.knowledgeTag"
        placeholder="知识点标签"
        clearable
        class="ex-admin-page__tag"
        @keyup.enter="search"
        @clear="search"
      />
      <el-select v-model="filters.status" placeholder="全部状态" clearable class="ex-admin-page__select" @change="search">
        <el-option label="草稿" value="draft" />
        <el-option label="已发布" value="published" />
      </el-select>
      <el-button type="primary" :icon="RefreshLeft" @click="search">刷新</el-button>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建习题</el-button>
    </div>

    <el-table v-loading="loading" :data="items" class="ex-admin-page__table">
      <el-table-column label="题干" min-width="260">
        <template #default="{ row }">{{ row.stem.split('\n')[0].slice(0, 40) }}</template>
      </el-table-column>
      <el-table-column label="题型" width="110">
        <template #default="{ row }">{{ TYPE_LABELS[row.type as ExerciseType] }}</template>
      </el-table-column>
      <el-table-column label="难度" width="80">
        <template #default="{ row }">{{ row.difficulty }}</template>
      </el-table-column>
      <el-table-column label="知识点" min-width="160">
        <template #default="{ row }">{{ (row.knowledge_tags ?? []).join('、') || '—' }}</template>
      </el-table-column>
      <el-table-column label="来源" width="80">
        <template #default="{ row }">{{ row.source }}</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'published' ? 'success' : 'info'" effect="plain">
            {{ row.status === 'published' ? '已发布' : '草稿' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link :type="row.status === 'published' ? 'warning' : 'success'" @click="togglePublish(row)">
            {{ row.status === 'published' ? '下架' : '发布' }}
          </el-button>
          <el-button link type="danger" @click="removeExercise(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="filters.page"
      v-model:page-size="filters.pageSize"
      :total="total"
      :page-sizes="[10, 20, 50]"
      layout="total, sizes, prev, pager, next"
      class="ex-admin-page__pager"
      @current-change="load"
      @size-change="search"
    />

    <el-dialog v-model="dialog" :title="editId ? '编辑习题' : '新建习题'" width="640px">
      <el-form label-width="110px" @submit.prevent>
        <el-form-item label="题型">
          <el-select v-model="form.type" class="ex-admin-page__mode">
            <el-option v-for="(label, key) in TYPE_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="题干">
          <el-input v-model="form.stem" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="难度">
          <el-radio-group v-model="form.difficulty">
            <el-radio-button v-for="d in 5" :key="d" :value="d">{{ d }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="form.status">
            <el-radio value="draft">草稿</el-radio>
            <el-radio value="published">发布</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="['choice', 'multi'].includes(form.type)" label="选项 options">
          <el-input v-model="form.optionsText" type="textarea" :rows="3" placeholder='{"A": "选项文本", "B": "…"}' />
          <div v-if="fieldError.options" class="ex-admin-page__error">{{ fieldError.options }}</div>
        </el-form-item>
        <el-form-item label="参考答案 answer">
          <el-input v-model="form.answerText" type="textarea" :rows="2" :placeholder="answerPlaceholder" />
          <div v-if="fieldError.answer" class="ex-admin-page__error">{{ fieldError.answer }}</div>
        </el-form-item>
        <el-form-item v-if="form.type === 'coding'" label="测试用例 test_cases">
          <el-input v-model="form.testCasesText" type="textarea" :rows="4" placeholder='{"language": "python", "cases": [{"stdin": "", "expected_stdout": "6"}]}' />
          <div v-if="fieldError.test_cases" class="ex-admin-page__error">{{ fieldError.test_cases }}</div>
        </el-form-item>
        <el-form-item label="解析 explanation">
          <el-input v-model="form.explanation" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="知识点标签">
          <el-input v-model="form.knowledgeTagsText" placeholder="逗号分隔，如：变量与赋值, 循环" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">{{ editId ? '保存' : '创建' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.ex-admin-page__toolbar {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
  flex-wrap: wrap;
}

.ex-admin-page__select {
  width: 140px;
}

.ex-admin-page__tag {
  width: 180px;
}

.ex-admin-page__mode {
  width: 200px;
}

.ex-admin-page__pager {
  margin-top: var(--space-4);
}

.ex-admin-page__error {
  color: var(--color-danger);
  font-size: 12px;
  line-height: 1.4;
}
</style>
