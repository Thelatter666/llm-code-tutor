<script setup lang="ts">
import DegradedBanner from '@/components/DegradedBanner.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import * as codeApi from '@/api/code'
import type { CodeAnalysisOut, StaticReport } from '@/types/code'
import { computed, ref } from 'vue'
import { UiAlert, UiBadge, UiButton, UiCard, UiEmpty, UiIcon, UiRadioGroup, UiTextarea } from '@/ui'

/**
 * 代码解析辅导页（spec §8.4）。
 *
 * 边界（P3 裁定）：代码输入用组件本地状态，**不做会话持久化** ——
 * CodeSession / CodeRun 归 P4（在线编辑器批次）。
 * 意图固定为「评改已写代码」，豁免防抄袭档位约束（ADR-0005）。
 */

const LANGUAGE_OPTIONS = [
  { label: 'Python', value: 'python' },
  { label: 'JavaScript', value: 'javascript' },
]

const language = ref<codeApi.CodeLanguage>('python')
const source = ref('')
const analyzing = ref(false)
const result = ref<CodeAnalysisOut | null>(null)

const canAnalyze = computed(() => source.value.trim().length > 0 && !analyzing.value)

const report = computed<StaticReport | null>(() => result.value?.static_report ?? null)

async function analyze() {
  if (!canAnalyze.value) return
  analyzing.value = true
  result.value = null
  try {
    const { data } = await codeApi.analyzeCode({
      language: language.value,
      source: source.value,
    })
    result.value = data.data ?? null
  } finally {
    analyzing.value = false
  }
}

function loadSample() {
  language.value = 'python'
  source.value = [
    'def grade(scores):',
    '    total = 0',
    '    for s in scores:',
    '        if s < 0:',
    '            continue',
    '        total += s',
    '    return total / len(scores)',
    '',
    'def main():',
    '    try:',
    '        print(grade([90, 85, -1]))',
    '    except:',
    '        print("出错了")',
    '',
    'main()',
  ].join('\n')
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col gap-4 lg:flex-row">
    <UiCard class="flex min-h-0 flex-1 flex-col">
      <template #header>
        <UiRadioGroup v-model="language" :options="LANGUAGE_OPTIONS" button :disabled="analyzing" />
        <UiButton variant="link" size="sm" @click="loadSample">
          <UiIcon name="Sparkles" :size="14" />
          填入示例
        </UiButton>
      </template>

      <UiTextarea
        v-model="source"
        :rows="18"
        monospace
        :maxlength="20000"
        :placeholder="`粘贴或输入你的 ${language} 代码，点击「开始解析」`"
        spellcheck="false"
      />

      <template #footer>
        <div class="flex items-center justify-between gap-3">
          <span class="text-sm text-muted-ink">
            本页固定为「评改已写代码」意图，豁免防抄袭档位约束，可直接获得改进建议
          </span>
          <span class="shrink-0 text-xs text-muted-ink">{{ source.length }} / 20000</span>
        </div>
        <UiButton class="mt-3 w-full" :disabled="!canAnalyze" @click="analyze">
          <UiIcon name="Sparkles" :size="14" />
          开始解析
        </UiButton>
      </template>
    </UiCard>

    <UiCard class="flex min-h-0 flex-1 flex-col overflow-auto">
      <UiEmpty v-if="!result" description="解析结果会显示在这里" icon="FileSearch" />

      <template v-else>
        <div class="mb-3 flex flex-wrap gap-2">
          <UiBadge v-if="result.reused" variant="info">与上次分析相同，已复用历史结果</UiBadge>
          <UiBadge v-if="result.ai_report?.usage_estimated" variant="warning">估算用量</UiBadge>
          <UiBadge v-if="result.ai_report" variant="info">{{ result.ai_report.provider }}</UiBadge>
        </div>

        <UiAlert
          v-if="report?.syntax_error"
          variant="error"
          class="mb-3"
          :title="`第 ${report.syntax_error.line} 行存在语法错误`"
          :description="`${report.syntax_error.message}；请先修复语法错误，AI 讲解仅供参考。`"
        />

        <section v-if="report" class="mb-4">
          <h3 class="mb-3 text-md font-semibold text-ink">静态报告</h3>
          <div class="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div v-for="m in [
              { num: report.lines.total, label: `总行数（代码 ${report.lines.code}）` },
              { num: report.functions.length, label: '函数' },
              { num: report.classes.length, label: '类' },
              { num: report.complexity.max, label: report.complexity.worst ? `最高圈复杂度（${report.complexity.worst}）` : '最高圈复杂度' },
            ]" :key="m.label" class="flex flex-col gap-1">
              <span class="text-2xl font-bold leading-tight text-brand">{{ m.num }}</span>
              <span class="text-sm text-muted-ink">{{ m.label }}</span>
            </div>
          </div>

          <template v-if="report.issues.unused_variables.length">
            <h4 class="mb-1 mt-4 text-base font-medium text-ink">未使用变量</h4>
            <ul class="m-0 list-disc pl-6 text-sm text-muted-ink">
              <li v-for="v in report.issues.unused_variables" :key="`${v.name}:${v.line}`">
                <code class="rounded-ctl bg-softer px-1 py-0.5 text-xs">{{ v.name }}</code>
                （第 {{ v.line }} 行）：赋值后从未读取
              </li>
            </ul>
          </template>

          <template v-if="report.issues.bare_excepts.length">
            <h4 class="mb-1 mt-4 text-base font-medium text-ink">
              {{ report.language === 'python' ? '裸 except' : '空 catch 块' }}
            </h4>
            <ul class="m-0 list-disc pl-6 text-sm text-muted-ink">
              <li v-for="b in report.issues.bare_excepts" :key="b.line">第 {{ b.line }} 行</li>
            </ul>
          </template>

          <p
            v-if="!report.issues.unused_variables.length && !report.issues.bare_excepts.length"
            class="m-0 mt-3 text-sm text-muted-ink"
          >
            未发现未使用变量、裸 except 等明显问题。
          </p>
        </section>

        <section v-if="result.ai_report">
          <h3 class="mb-2 text-md font-semibold text-ink">AI 讲解</h3>
          <DegradedBanner
            v-if="result.ai_report.degraded"
            :degraded="true"
            :fallback-reason="result.ai_report.fallback_reason"
          />
          <MarkdownView :content="result.ai_report.content" />
        </section>
      </template>
    </UiCard>
  </div>
</template>
