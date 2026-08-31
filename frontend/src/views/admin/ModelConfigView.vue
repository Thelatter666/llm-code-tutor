<script setup lang="ts">
import * as adminApi from '@/api/admin'
import type { AntiPlagiarismMode, LlmProvider, ModelConfigPutPayload } from '@/types/admin'
import { MagicStick } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

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
    ElMessage.warning('请填写模型名称')
    return
  }
  saving.value = true
  try {
    const { data } = await adminApi.putModelConfig(buildPayload())
    ElMessage.success('配置已保存并生效')
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
    const headline = result.ok
      ? `连接正常（${result.latency_ms ?? 0}ms）`
      : '连接失败'
    ElMessage({
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

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="model-config-page">
    <el-alert
      type="info"
      show-icon
      :closable="false"
      class="model-config-page__notice"
      title="配置保存即生效，无需重启服务"
      description="修改模型或防抄袭档位后，下一次对话/辅导请求立即使用新配置（revision 版本号自动递增）。"
    />

    <el-form label-width="140px" class="model-config-page__form" @submit.prevent>
      <el-form-item label="提供方">
        <el-radio-group v-model="form.provider">
          <el-radio value="mock">Mock（无需 API Key）</el-radio>
          <el-radio value="openai_compat">OpenAI 兼容</el-radio>
        </el-radio-group>
      </el-form-item>

      <el-form-item label="模型名称">
        <el-input v-model="form.model" placeholder="如 gpt-4o-mini / mock-1" />
      </el-form-item>

      <el-form-item label="Base URL">
        <el-input v-model="form.base_url" placeholder="OpenAI 兼容服务地址（可空）" />
      </el-form-item>

      <el-form-item label="API Key">
        <el-input
          v-model="form.api_key"
          type="password"
          show-password
          placeholder="留空则保持不变；读取接口仅显示掩码"
        />
        <div class="model-config-page__hint">
          密钥以加密形式存储，仅在实际调用时于内存中解密（掩码形态 sk-****abcd）。
          {{ form.provider === 'openai_compat' ? '切换 OpenAI 兼容必须提供密钥。' : '清除密钥：切回 Mock 即可。' }}
        </div>
      </el-form-item>

      <el-form-item label="温度 temperature">
        <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" />
      </el-form-item>

      <el-form-item label="top_p">
        <el-input-number v-model="form.top_p" :min="0.01" :max="1" :step="0.05" />
      </el-form-item>

      <el-form-item label="max_tokens">
        <el-input-number v-model="form.max_tokens" :min="1" :step="128" />
      </el-form-item>

      <el-form-item label="防抄袭档位">
        <el-select v-model="form.anti_plagiarism_mode" class="model-config-page__mode">
          <el-option v-for="(label, mode) in MODE_LABELS" :key="mode" :label="label" :value="mode" />
        </el-select>
      </el-form-item>

      <el-form-item label="相关度阈值">
        <el-input-number
          v-model="form.score_threshold"
          :min="0"
          :max="1"
          :step="0.05"
          :value-on-clear="null"
        />
        <div class="model-config-page__hint">留空 = 按 embedding 模型的默认阈值（0.35）。</div>
      </el-form-item>

      <el-form-item label="top_k">
        <el-input-number v-model="form.top_k" :min="1" :max="20" />
      </el-form-item>

      <el-form-item label="embedding 配置">
        <div class="model-config-page__embedding">
          <el-tag size="small" effect="plain" :icon="MagicStick">
            只读回显 —— 切换 embedding 请在知识库管理页走「重建」流程（需二次确认，避免维度混用）
          </el-tag>
        </div>
      </el-form-item>

      <el-form-item label=" ">
        <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
        <el-button :loading="testing" @click="testConnection">测试连接</el-button>
      </el-form-item>
    </el-form>

    <div class="model-config-page__meta">
      <span>revision：{{ revision }}</span>
      <span>最近更新：{{ updatedAt ?? '—' }} · {{ updatedBy ?? '—' }}</span>
    </div>
  </div>
</template>

<style scoped>
.model-config-page__notice {
  margin-bottom: var(--space-4);
}

.model-config-page__form {
  max-width: 560px;
}

.model-config-page__mode {
  width: 320px;
}

.model-config-page__hint {
  font-size: 12px;
  color: var(--color-muted-foreground);
  line-height: 1.5;
}

.model-config-page__embedding {
  display: flex;
  align-items: center;
  min-height: 32px;
}

.model-config-page__meta {
  display: flex;
  gap: var(--space-4);
  margin-top: var(--space-4);
  font-size: 13px;
  color: var(--color-muted-foreground);
}
</style>
