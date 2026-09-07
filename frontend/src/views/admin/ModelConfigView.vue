<script setup lang="ts">
import * as adminApi from '@/api/admin'
import { useNotify } from '@/composables/useNotify'
import type { AntiPlagiarismMode, LlmProvider, ModelConfigPutPayload } from '@/types/admin'
import { computed, onMounted, reactive, ref } from 'vue'
import { UiAlert, UiBadge, UiButton, UiCard, UiIcon, UiInput, UiInputNumber, UiRadioGroup, UiSelect } from '@/ui'

/**
 * 模型配置页（spec §6.2 / §4.2 硬约束 4 / §8.8，P6 Task 10）。
 *
 * 裁定 2 的页面口径：
 * - **api_key 留空 = 不变更**（掩码回显，绝不把已有密钥清掉）；清除密钥请切回 mock；
 * - 保存即 revision += 1，下一次调用即用新值 —— 无需重启；
 * - embedding 配置不在此处修改（409 重建流程在知识库管理页）；本区只读回显。
 */

const MODE_LABELS: Record<AntiPlagiarismMode, string> = {
  strict: '严格（只给思路与伪代码）',
  guided: '引导（默认，允许 ≤10 行片段）',
  loose: '宽松（允许完整实现，需讲解）',
}

const PROVIDER_OPTIONS = [
  { label: 'Mock（无需 API Key）', value: 'mock' },
  { label: 'OpenAI 兼容', value: 'openai_compat' },
]
const modeOptions = (Object.keys(MODE_LABELS) as AntiPlagiarismMode[]).map((mode) => ({
  label: MODE_LABELS[mode],
  value: mode,
}))

const notify = useNotify()

const form = reactive({
  provider: 'mock' as LlmProvider,
  model: 'mock-1',
  base_url: '',
  api_key: '', // 留空 = 不变更
  temperature: 0.7,
  top_p: 1,
  max_tokens: 2048,
  anti_plagiarism_mode: 'guided' as AntiPlagiarismMode,
  score_threshold: null as number | null,
  top_k: 5,
})

const revision = ref(0)
const updatedBy = ref<string | null>(null)
const updatedAt = ref<string | null>(null)
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await adminApi.getModelConfig()
    const cfg = data.data
    if (!cfg) return
    form.provider = cfg.provider
    form.model = cfg.model
    form.base_url = cfg.base_url ?? ''
    // 掩码回显，但绝不回填输入框：提交时 api_key 留空即「不变更」
    form.api_key = ''
    form.temperature = cfg.temperature
    form.top_p = cfg.top_p
    form.max_tokens = cfg.max_tokens
    form.anti_plagiarism_mode = cfg.anti_plagiarism_mode
    form.score_threshold = cfg.score_threshold
    form.top_k = cfg.top_k
    revision.value = cfg.revision
    updatedBy.value = cfg.updated_by
    updatedAt.value = cfg.updated_at ? `${cfg.updated_at.slice(0, 16).replace('T', ' ')} UTC` : null
  } finally {
    loading.value = false
  }
}

function buildPayload(): ModelConfigPutPayload {
  const payload: ModelConfigPutPayload = {
    provider: form.provider,
    model: form.model.trim(),
    base_url: form.base_url.trim() || null,
    temperature: form.temperature,
    top_p: form.top_p,
    max_tokens: form.max_tokens,
    anti_plagiarism_mode: form.anti_plagiarism_mode,
    score_threshold: form.score_threshold,
    top_k: form.top_k,
  }
  // 只在新填了密钥时才带上；留空 = 后端不变更（裁定 2）
  if (form.api_key.trim()) payload.api_key = form.api_key.trim()
  return payload
}

async function save() {
  if (!form.model.trim()) {
    notify.warning('请填写模型名称')
    return
  }
  saving.value = true
  try {
    const { data } = await adminApi.putModelConfig(buildPayload())
    notify.success('配置已保存并生效')
    // 刷新 revision 与更新人回显（保存即 revision += 1）
    const cfg = data.data
    if (cfg) {
      revision.value = cfg.revision
      updatedBy.value = cfg.updated_by
    }
    await load()
  } catch {
    // 后端 4220（openai 无 key 等）消息由拦截器弹出
  } finally {
    saving.value = false
  }
}

async function testConnection() {
  testing.value = true
  try {
    const { data } = await adminApi.testModelConfig()
    const result = data.data
    if (!result) return
    const headline = result.ok ? `连接正常（${result.latency_ms ?? 0}ms）` : '连接失败'
    notify.raw({
      type: result.ok ? 'success' : 'warning',
      message: `${headline}：${result.sample}`,
      duration: 8000,
      showClose: true,
    })
  } catch {
    // 网络级失败消息由拦截器弹出
  } finally {
    testing.value = false
  }
}

const keyHint = computed(() =>
  form.provider === 'openai_compat'
    ? '切换 OpenAI 兼容必须提供密钥。'
    : '清除密钥：切回 Mock 即可。',
)

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="flex flex-col gap-4">
    <UiAlert
      variant="info"
      title="配置保存即生效，无需重启服务"
      description="修改模型或防抄袭档位后，下一次对话/辅导请求立即使用新配置（revision 版本号自动递增）。"
    />

    <UiCard>
      <form class="flex max-w-[560px] flex-col gap-4" @submit.prevent>
        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">提供方</label>
          <UiRadioGroup v-model="form.provider" :options="PROVIDER_OPTIONS" />
        </div>

        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">模型名称</label>
          <UiInput v-model="form.model" placeholder="如 gpt-4o-mini / mock-1" />
        </div>

        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">Base URL</label>
          <UiInput v-model="form.base_url" placeholder="OpenAI 兼容服务地址（可空）" />
        </div>

        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">API Key</label>
          <UiInput
            v-model="form.api_key"
            type="password"
            placeholder="留空则保持不变；读取接口仅显示掩码"
          />
          <p class="text-xs leading-relaxed text-muted-ink">
            密钥以加密形式存储，仅在实际调用时于内存中解密（掩码形态 sk-****abcd）。{{ keyHint }}
          </p>
        </div>

        <div class="grid gap-4 sm:grid-cols-2">
          <div class="flex flex-col gap-1">
            <label class="text-sm text-muted-ink">温度 temperature</label>
            <UiInputNumber v-model="form.temperature" :min="0" :max="2" :step="0.1" />
          </div>
          <div class="flex flex-col gap-1">
            <label class="text-sm text-muted-ink">top_p</label>
            <UiInputNumber v-model="form.top_p" :min="0.01" :max="1" :step="0.05" />
          </div>
          <div class="flex flex-col gap-1">
            <label class="text-sm text-muted-ink">max_tokens</label>
            <UiInputNumber v-model="form.max_tokens" :min="1" :step="128" />
          </div>
          <div class="flex flex-col gap-1">
            <label class="text-sm text-muted-ink">top_k</label>
            <UiInputNumber v-model="form.top_k" :min="1" :max="20" />
          </div>
        </div>

        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">防抄袭档位</label>
          <UiSelect v-model="form.anti_plagiarism_mode" :options="modeOptions" />
        </div>

        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">相关度阈值</label>
          <UiInputNumber v-model="form.score_threshold" :min="0" :max="1" :step="0.05" clearable :value-on-clear="null" />
          <p class="text-xs text-muted-ink">留空 = 按 embedding 模型的默认阈值（0.35）。</p>
        </div>

        <div class="flex flex-col gap-1">
          <label class="text-sm text-muted-ink">embedding 配置</label>
          <div class="flex items-center gap-2">
            <UiBadge variant="muted">
              只读回显 —— 切换 embedding 请在知识库管理页走「重建」流程（需二次确认，避免维度混用）
            </UiBadge>
            <UiIcon name="Info" :size="14" class="text-muted-ink" />
          </div>
        </div>

        <div class="flex gap-2">
          <UiButton :loading="saving" @click="save">保存配置</UiButton>
          <UiButton variant="secondary" :loading="testing" @click="testConnection">测试连接</UiButton>
        </div>
      </form>
    </UiCard>

    <p class="flex gap-4 text-sm text-muted-ink">
      <span>revision：{{ revision }}</span>
      <span>最近更新：{{ updatedAt ?? '—' }} · {{ updatedBy ?? '—' }}</span>
    </p>
  </div>
</template>
