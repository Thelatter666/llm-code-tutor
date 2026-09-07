<script setup lang="ts">
import CitationList from '@/components/CitationList.vue'
import DegradedBanner from '@/components/DegradedBanner.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import * as chatApi from '@/api/chat'
import * as kbApi from '@/api/knowledge'
import { useConfirm } from '@/composables/useConfirm'
import { useNotify } from '@/composables/useNotify'
import { newRequestId, prefersReducedMotion } from '@/composables/useSse'
import { useAuthStore } from '@/stores/auth'
import type {
  ChatDoneEvent,
  ChatErrorEvent,
  Citation,
  ConversationOut,
} from '@/types/chat'
import type { KnowledgeBaseOut } from '@/types/knowledge'
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { UiBadge, UiButton, UiCard, UiCheckbox, UiEmpty, UiIcon, UiSelect, UiTextarea } from '@/ui'

interface Bubble {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations: Citation[]
  done: ChatDoneEvent | null
  typing: boolean
  truncated: boolean
}

const auth = useAuthStore()
const notify = useNotify()
const confirm = useConfirm()

const conversations = ref<ConversationOut[]>([])
const activeId = ref<string | null>(null)
const bubbles = ref<Bubble[]>([])
const input = ref('')
const streaming = ref(false)
const requestId = ref('')
const pendingText = ref('')
const bases = ref<KnowledgeBaseOut[]>([])
const selectedKb = ref<string[]>([])
const useRag = ref(true)

const listRef = ref<HTMLElement | null>(null)
const reduceMotion = prefersReducedMotion()
let typeTimer: number | undefined

const busy = computed(() => streaming.value || pendingText.value.length > 0)
const canSend = computed(() => input.value.trim().length > 0 && !busy.value)

function stopTypewriter() {
  if (typeTimer !== undefined) {
    window.clearInterval(typeTimer)
    typeTimer = undefined
  }
}
function startTypewriter() {
  stopTypewriter()
  if (reduceMotion) return
  typeTimer = window.setInterval(() => {
    const last = bubbles.value[bubbles.value.length - 1]
    if (!pendingText.value) {
      if (!streaming.value) stopTypewriter()
      return
    }
    if (last && last.role === 'assistant') {
      last.content += pendingText.value.slice(0, 1)
      pendingText.value = pendingText.value.slice(1)
    }
  }, 18)
}
function appendDelta(delta: string) {
  const last = bubbles.value[bubbles.value.length - 1]
  if (!last || last.role !== 'assistant') return
  if (reduceMotion) {
    last.content += delta
    return
  }
  pendingText.value += delta
}
async function waitForDrain() {
  while (pendingText.value) {
    await new Promise((resolve) => window.setTimeout(resolve, 30))
  }
}

async function loadConversations() {
  const { data } = await chatApi.listConversations()
  conversations.value = data.data ?? []
}
async function selectConversation(id: string) {
  if (busy.value) return
  activeId.value = id
  await loadMessages(id)
}
async function loadMessages(id: string) {
  const { data } = await chatApi.listMessages(id)
  bubbles.value = (data.data ?? []).map((m) => ({
    id: m.id,
    role: m.role === 'assistant' ? 'assistant' : 'user',
    content: m.content,
    citations: m.citations ?? [],
    done: null,
    typing: false,
    truncated: m.truncated,
  }))
  scrollToBottom()
}
async function newConversation() {
  if (busy.value) return
  const { data } = await chatApi.createConversation()
  const conv = data.data
  if (!conv) return
  await loadConversations()
  await selectConversation(conv.id)
}
async function removeConversation(conv: ConversationOut) {
  if (busy.value) return
  if (!(await confirm(`删除会话「${conv.title}」？该操作不可恢复。`, '删除会话'))) return
  await chatApi.deleteConversation(conv.id)
  if (activeId.value === conv.id) {
    activeId.value = null
    bubbles.value = []
  }
  await loadConversations()
}
function scrollToBottom() {
  nextTick(() => {
    const el = listRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function send() {
  const text = input.value.trim()
  if (!text || !canSend.value) return
  if (!activeId.value) await newConversation()
  const conversationId = activeId.value
  if (!conversationId) return

  bubbles.value.push({
    id: `u-${Date.now()}`,
    role: 'user',
    content: text,
    citations: [],
    done: null,
    typing: false,
    truncated: false,
  })
  bubbles.value.push({
    id: `a-${Date.now()}`,
    role: 'assistant',
    content: '',
    citations: [],
    done: null,
    typing: true,
    truncated: false,
  })
  input.value = ''
  streaming.value = true
  requestId.value = newRequestId()
  startTypewriter()
  scrollToBottom()

  const assistant = bubbles.value[bubbles.value.length - 1]
  try {
    await chatApi.streamMessage({
      conversationId,
      content: text,
      useRag: useRag.value,
      kbIds: selectedKb.value,
      requestId: requestId.value,
      onCitation: (c) => assistant.citations.push(c),
      onToken: (delta) => {
        appendDelta(delta)
        scrollToBottom()
      },
      onDone: (done: ChatDoneEvent) => {
        assistant.done = done
        assistant.typing = false
      },
      onError: (err: ChatErrorEvent) => {
        assistant.typing = false
        assistant.truncated = true
        if (err.code === 4990) notify.info('已中断生成')
        else notify.error(err.message || '生成失败')
      },
    })
  } catch (e) {
    assistant.typing = false
    notify.error((e as Error).message)
  } finally {
    streaming.value = false
    await waitForDrain()
    stopTypewriter()
    if (activeId.value === conversationId) await loadMessages(conversationId)
    await loadConversations()
  }
}

async function stop() {
  if (!activeId.value || !requestId.value) return
  try {
    const { data } = await chatApi.stopGeneration(activeId.value, requestId.value)
    if (data.data && !data.data.cancelled) notify.info('该请求已结束，无需中断')
  } catch (e) {
    notify.error((e as Error).message)
  }
}

const kbOptions = computed(() => bases.value.map((b) => ({ label: b.name, value: b.id })))

onMounted(async () => {
  await loadConversations()
  try {
    const { data } = await kbApi.listBases()
    bases.value = (data.data ?? []).filter((b) => b.status === 'ready')
  } catch {
    bases.value = []
  }
})
onUnmounted(stopTypewriter)
</script>

<template>
  <div class="flex h-full min-h-0 flex-col gap-4 lg:flex-row">
    <!-- 左侧会话列表面板 -->
    <aside class="flex w-full shrink-0 flex-col gap-3 rounded-panel border border-line bg-surface p-3 lg:w-60">
      <UiButton class="w-full" @click="newConversation">
        <UiIcon name="Plus" :size="14" />
        新建会话
      </UiButton>
      <ul class="m-0 flex list-none flex-col gap-1 p-0">
        <li v-for="conv in conversations" :key="conv.id">
          <div
            class="group flex cursor-pointer items-center gap-2 rounded-ctl px-2 py-2 text-sm text-ink transition-colors hover:bg-softer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
            :class="conv.id === activeId ? 'bg-softer font-semibold text-brand' : ''"
            role="button"
            tabindex="0"
            @click="selectConversation(conv.id)"
            @keydown.enter="selectConversation(conv.id)"
          >
            <UiIcon name="MessagesSquare" :size="16" class="shrink-0 text-brand" />
            <span class="min-w-0 flex-1 truncate">{{ conv.title }}</span>
            <UiButton
              variant="ghost"
              size="icon-sm"
              class="opacity-0 transition-opacity group-hover:opacity-100"
              @click.stop="removeConversation(conv)"
              aria-label="删除会话"
            >
              <UiIcon name="Trash2" :size="14" />
            </UiButton>
          </div>
        </li>
      </ul>
      <p v-if="!conversations.length" class="text-sm text-muted-ink">还没有会话，点上方按钮开始</p>
    </aside>

    <!-- 右侧对话面板 -->
    <UiCard class="flex min-h-0 flex-1 flex-col">
      <template #header>
        <div class="flex flex-wrap items-center gap-3">
          <UiCheckbox v-model="useRag" :disabled="streaming">启用知识库增强（RAG）</UiCheckbox>
          <UiSelect
            v-if="useRag"
            v-model="selectedKb"
            :options="kbOptions"
            multiple
            collapse-tags
            clearable
            placeholder="不限知识库"
            :disabled="streaming"
            class="min-w-[220px]"
          />
          <span class="text-sm text-muted-ink">答疑入口固定为「求答案」意图，受防抄袭档位约束</span>
        </div>
      </template>

      <div ref="listRef" class="flex min-h-0 flex-1 flex-col gap-4 overflow-auto p-2">
        <UiEmpty v-if="!bubbles.length" description="输入你的编程问题，开始答疑" icon="MessageSquare" />

        <div
          v-for="b in bubbles"
          :key="b.id"
          class="flex gap-3"
          :class="b.role === 'user' ? 'flex-row-reverse' : ''"
        >
          <div
            class="w-14 shrink-0 text-sm text-muted-ink"
            :class="b.role === 'user' ? 'text-left' : 'text-right'"
          >
            {{ b.role === 'user' ? '我' : 'AI 助教' }}
          </div>
          <div
            class="max-w-[min(760px,80%)] rounded-panel px-4 py-3 text-sm leading-relaxed"
            :class="b.role === 'user' ? 'bg-brand text-brand-fg' : 'bg-softer text-ink'"
          >
            <div v-if="b.typing && !b.content" class="typing" aria-label="正在生成">
              <span></span><span></span><span></span>
            </div>
            <template v-else-if="b.content">
              <MarkdownView v-if="b.role === 'assistant'" :content="b.content" />
              <pre v-else class="m-0 whitespace-pre-wrap break-words font-sans">{{ b.content }}</pre>
            </template>
            <p v-else-if="b.truncated" class="m-0 text-sm text-muted-ink">（已中断，未生成内容）</p>

            <DegradedBanner
              v-if="b.done?.degraded"
              :degraded="true"
              :fallback-reason="b.done.fallback_reason"
            />
            <CitationList v-if="b.citations.length" :citations="b.citations" />
            <div v-if="b.done" class="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted-ink">
              <UiBadge variant="info">{{ b.done.provider }}</UiBadge>
              <UiBadge v-if="b.done.usage_estimated" variant="warning">估算用量</UiBadge>
              <span>{{ b.done.token_usage.total_tokens }} tokens</span>
              <span>{{ b.done.rag_hit ? '知识库命中' : '未命中知识库' }}</span>
            </div>
            <div v-if="b.typing && b.content" class="mt-2 text-sm text-muted-ink">生成中…</div>
          </div>
        </div>
      </div>

      <template #footer>
        <UiTextarea
          v-model="input"
          :rows="3"
          :maxlength="8000"
          placeholder="例如：讲讲排序算法；或者「闭包是什么」"
          @keydown.enter.exact.prevent="send"
        />
        <div class="mt-2 flex justify-end gap-2">
          <UiButton v-if="streaming" variant="secondary" @click="stop">
            <UiIcon name="Pause" :size="14" />
            停止生成
          </UiButton>
          <UiButton :disabled="!canSend" @click="send">
            <UiIcon name="Send" :size="14" />
            发送
          </UiButton>
        </div>
      </template>
    </UiCard>
  </div>
</template>

<style scoped>
/* 基线 §1：三点脉冲打字指示器（仅这一处用 animation） */
.typing {
  display: inline-flex;
  gap: 4px;
}
.typing span {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: var(--color-primary);
  animation: pulse 1.2s ease-in-out infinite;
}
.typing span:nth-child(2) {
  animation-delay: 0.15s;
}
.typing span:nth-child(3) {
  animation-delay: 0.3s;
}
@keyframes pulse {
  0%, 60%, 100% {
    opacity: 0.25;
    transform: translateY(0);
  }
  30% {
    opacity: 1;
    transform: translateY(-3px);
  }
}
@media (prefers-reduced-motion: reduce) {
  .typing span {
    animation: none;
  }
}
</style>
