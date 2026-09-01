<script setup lang="ts">
import DegradedBanner from '@/components/DegradedBanner.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import * as codeApi from '@/api/code'
import type { CodeAnalysisOut, StaticReport } from '@/types/code'
import { MagicStick } from '@element-plus/icons-vue'
import { computed, ref } from 'vue'

/**
 * 代码解析辅导页（spec §8.4）。
 *
 * 边界（P3 裁定）：代码输入用组件本地状态，**不做会话持久化** ——
 * CodeSession / CodeRun 归 P4（在线编辑器批次）。
 * 意图固定为「评改已写代码」，豁免防抄袭档位约束（ADR-0005）。
 */

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
  <div class="review">
    <section class="review__editor">
      <div class="review__bar">
        <el-radio-group v-model="language" :disabled="analyzing">
          <el-radio-button value="python">Python</el-radio-button>
          <el-radio-button value="javascript">JavaScript</el-radio-button>
        </el-radio-group>
        <el-button link :icon="MagicStick" class="review__sample" @click="loadSample">
          填入示例
        </el-button>
      </div>
      <el-input
        v-model="source"
        type="textarea"
        :rows="18"
        resize="none"
        maxlength="20000"
        show-word-limit
        :placeholder="`粘贴或输入你的 ${language} 代码，点击「开始解析」`"
        spellcheck="false"
        class="review__source"
      />
      <div class="review__actions">
        <span class="review__hint">
          本页固定为「评改已写代码」意图，豁免防抄袭档位约束，可直接获得改进建议
        </span>
        <el-button type="primary" :icon="MagicStick" :disabled="!canAnalyze" @click="analyze">
          开始解析
        </el-button>
      </div>
    </section>

    <section class="review__result">
      <el-empty v-if="!result" description="解析结果会显示在这里" />
      <template v-else>
        <div class="review__meta">
          <el-tag v-if="result.reused" size="small" type="info" effect="plain">
            与上次分析相同，已复用历史结果
          </el-tag>
          <el-tag v-if="result.ai_report?.usage_estimated" size="small" type="warning" effect="plain">
            估算用量
          </el-tag>
          <el-tag v-if="result.ai_report" size="small" effect="plain" type="info">
            {{ result.ai_report.provider }}
          </el-tag>
        </div>

        <el-alert
          v-if="report?.syntax_error"
          type="error"
          :closable="false"
          show-icon
          class="review__syntax"
          :title="`第 ${report.syntax_error.line} 行存在语法错误`"
          :description="`${report.syntax_error.message}；请先修复语法错误，AI 讲解仅供参考。`"
        />

        <div v-if="report" class="card">
          <h3 class="card__title">静态报告</h3>
          <div class="metrics">
            <div class="metric">
              <span class="metric__num">{{ report.lines.total }}</span>
              <span class="metric__label">总行数（代码 {{ report.lines.code }}）</span>
            </div>
            <div class="metric">
              <span class="metric__num">{{ report.functions.length }}</span>
              <span class="metric__label">函数</span>
            </div>
            <div class="metric">
              <span class="metric__num">{{ report.classes.length }}</span>
              <span class="metric__label">类</span>
            </div>
            <div class="metric">
              <span class="metric__num">{{ report.complexity.max }}</span>
              <span class="metric__label">最高圈复杂度<template v-if="report.complexity.worst">（{{ report.complexity.worst }}）</template></span>
            </div>
          </div>

          <template v-if="report.issues.unused_variables.length">
            <h4 class="card__subtitle">未使用变量</h4>
            <ul class="issues">
              <li v-for="v in report.issues.unused_variables" :key="`${v.name}:${v.line}`">
                <code>{{ v.name }}</code>（第 {{ v.line }} 行）：赋值后从未读取
              </li>
            </ul>
          </template>

          <template v-if="report.issues.bare_excepts.length">
            <h4 class="card__subtitle">
              {{ report.language === 'python' ? '裸 except' : '空 catch 块' }}
            </h4>
            <ul class="issues">
              <li v-for="b in report.issues.bare_excepts" :key="b.line">第 {{ b.line }} 行</li>
            </ul>
          </template>

          <p v-if="!report.issues.unused_variables.length && !report.issues.bare_excepts.length" class="card__clean">
            未发现未使用变量、裸 except 等明显问题。
          </p>
        </div>

        <div v-if="result.ai_report" class="card">
          <h3 class="card__title">AI 讲解</h3>
          <DegradedBanner
            v-if="result.ai_report.degraded"
            :degraded="true"
            :fallback-reason="result.ai_report.fallback_reason"
          />
          <MarkdownView :content="result.ai_report.content" />
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.review {
  display: flex;
  gap: var(--space-4);
  height: 100%;
  min-height: 0;
}

.review__editor {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
}

.review__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.review__sample {
  cursor: pointer;
}

.review__source :deep(textarea) {
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 13px;
  line-height: 1.6;
}

.review__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.review__hint {
  font-size: 13px;
  color: var(--color-muted-foreground);
}

.review__result {
  flex: 1;
  min-width: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
}

.review__meta {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.review__syntax {
  border-radius: var(--radius-control);
}

.card {
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-background);
}

.card__title {
  margin: 0 0 var(--space-2);
  font-size: 15px;
}

.card__subtitle {
  margin: var(--space-3) 0 var(--space-1);
  font-size: 14px;
}

.card__clean {
  margin: 0;
  font-size: 13px;
  color: var(--color-muted-foreground);
}

.metrics {
  display: flex;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.metric__num {
  font-size: 22px;
  font-weight: 700;
  color: var(--color-primary);
}

.metric__label {
  font-size: 13px;
  color: var(--color-muted-foreground);
}

.issues {
  margin: 0;
  padding-left: 1.4em;
  font-size: 13px;
  color: var(--color-muted-foreground);
}

@media (max-width: 1023px) {
  .review {
    flex-direction: column;
  }
}
</style>
