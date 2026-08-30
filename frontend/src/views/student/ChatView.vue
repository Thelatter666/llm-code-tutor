<script setup lang="ts">
import CitationList from '@/components/CitationList.vue'
import DegradedBanner from '@/components/DegradedBanner.vue'
import * as chatApi from '@/api/chat'
import * as kbApi from '@/api/knowledge'
import { newRequestId, prefersReducedMotion } from '@/composables/useSse'
import { useAuthStore } from '@/stores/auth'
import type {
  ChatDoneEvent,
  ChatErrorEvent,
  Citation,
  ConversationOut,
} from '@/types/chat'
import type { KnowledgeBaseOut } from '@/types/knowledge'
import { ChatDotRound, Delete, Plus, Promotion, VideoPause } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'

/** 消息气泡的视图模型：服务端行 + 流式过程中的临时状态。 */
interface Bubble {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations: Citation[]
  done: ChatDoneEvent | null
  typing: boolean
  /** 流被中断或异常结束时为 true（spec §8.1） */
  truncated: boolean
}

const auth = useAuthStore()

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

/**
 * 「仍在处理中」= 网络流未结束 **或** 打字机队列未排空。
 *
 * 只判 `streaming` 是不够的：网络传输常在 0.1s 内结束，而打字机还要渲染数秒。
 * 若此时放开「发送」，新提问会插进正在渲染的气泡里，随后又被
 * `loadMessages()` 的重载整段覆盖 —— 学生看到的是自己的问题凭空消失。
 */
const busy = computed(() => streaming.value || pendingText.value.length > 0)

const canSend = computed(() => input.value.trim().length > 0 && !busy.value)

// ---------------------------------------------------------------- 打字机

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

// ---------------------------------------------------------------- 会话

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
  await ElMessageBox.confirm(`删除会话「${conv.title}」？该操作不可恢复。`, '删除会话', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
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

// ---------------------------------------------------------------- 发送与中断

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
        if (err.code === 4990) ElMessage.info('已中断生成')
        else ElMessage.error(err.message || '生成失败')
      },
    })
  } catch (e) {
    assistant.typing = false
    ElMessage.error((e as Error).message)
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
    if (data.data && !data.data.cancelled) ElMessage.info('该请求已结束，无需中断')
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

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
  <div class="chat">
    <aside class="chat__side">
      <el-button class="chat__new" type="primary" :icon="Plus" @click="newConversation">
        新建会话
      </el-button>
      <ul class="chat__list">
        <li v-for="conv in conversations" :key="conv.id">
          <div
            class="chat__item"
            :class="{ 'chat__item--active': conv.id === activeId }"
            role="button"
            tabindex="0"
            @click="selectConversation(conv.id)"
            @keydown.enter="selectConversation(conv.id)"
          >
            <el-icon class="chat__item-icon"><ChatDotRound /></el-icon>
            <span class="chat__item-title">{{ conv.title }}</span>
            <el-button
              link
              class="chat__item-del"
              :icon="Delete"
              @click.stop="removeConversation(conv)"
            />
          </div>
        </li>
      </ul>
      <p v-if="!conversations.length" class="chat__empty">还没有会话，点上方按钮开始</p>
    </aside>

    <section class="chat__panel">
      <div class="chat__settings">
        <el-checkbox v-model="useRag" :disabled="streaming">启用知识库增强（RAG）</el-checkbox>
        <el-select
          v-if="useRag"
          v-model="selectedKb"
          multiple
          collapse-tags
          collapse-tags-tooltip
          clearable
          placeholder="不限知识库"
          :disabled="streaming"
          class="chat__kb"
        >
          <el-option v-for="b in bases" :key="b.id" :label="b.name" :value="b.id" />
        </el-select>
        <span class="chat__hint">答疑入口固定为「求答案」意图，受防抄袭档位约束</span>
      </div>

      <div ref="listRef" class="chat__messages">
        <el-empty v-if="!bubbles.length" description="输入你的编程问题，开始答疑" />
        <div v-for="b in bubbles" :key="b.id" class="bubble" :class="`bubble--${b.role}`">
          <div class="bubble__role">{{ b.role === 'user' ? '我' : 'AI 助教' }}</div>
          <div class="bubble__body">
            <div v-if="b.typing && !b.content" class="typing" aria-label="正在生成">
              <span></span><span></span><span></span>
            </div>
            <pre v-else-if="b.content" class="bubble__text">{{ b.content }}</pre>
            <!-- 中断发生在一个增量都没吐出时：不给一个空气泡，明确说明发生了什么 -->
            <p v-else-if="b.truncated" class="bubble__interrupted">（已中断，未生成内容）</p>

            <DegradedBanner
              v-if="b.done?.degraded"
              :degraded="true"
              :fallback-reason="b.done.fallback_reason"
            />
            <CitationList v-if="b.citations.length" :citations="b.citations" />
            <div v-if="b.done" class="bubble__meta">
              <el-tag size="small" effect="plain" type="info">{{ b.done.provider }}</el-tag>
              <el-tag v-if="b.done.usage_estimated" size="small" effect="plain" type="warning">
                估算用量
              </el-tag>
              <span>{{ b.done.token_usage.total_tokens }} tokens</span>
              <span>{{ b.done.rag_hit ? '知识库命中' : '未命中知识库' }}</span>
            </div>
            <div v-if="b.typing && b.content" class="bubble__meta">生成中…</div>
          </div>
        </div>
      </div>

      <div class="chat__composer">
        <el-input
          v-model="input"
          type="textarea"
          :rows="3"
          resize="none"
          maxlength="8000"
          placeholder="例如：讲讲排序算法；或者「闭包是什么」"
          @keydown.enter.exact.prevent="send"
        />
        <div class="chat__actions">
          <el-button v-if="streaming" :icon="VideoPause" @click="stop">停止生成</el-button>
          <el-button type="primary" :icon="Promotion" :disabled="!canSend" @click="send">
            发送
          </el-button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.chat {
  display: flex;
  gap: var(--space-4);
  height: 100%;
  min-height: 0;
}

.chat__side {
  width: 240px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-4);
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  overflow: auto;
}

.chat__new {
  width: 100%;
  border-radius: var(--radius-control);
}

.chat__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.chat__item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2);
  border-radius: var(--radius-control);
  cursor: pointer;
  transition: background 200ms ease;
}

.chat__item:hover {
  background: var(--color-muted);
}

.chat__item:focus-visible {
  outline: 2px solid var(--color-ring);
  outline-offset: 2px;
}

.chat__item--active {
  background: var(--color-muted);
  color: var(--color-primary);
  font-weight: 600;
}

.chat__item-icon {
  flex-shrink: 0;
  color: var(--color-primary);
}

.chat__item-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.chat__item-del {
  opacity: 0;
  transition: opacity 200ms ease;
}

.chat__item:hover .chat__item-del {
  opacity: 1;
}

.chat__empty {
  color: var(--color-muted-foreground);
  font-size: 13px;
}

.chat__panel {
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

.chat__settings {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.chat__kb {
  min-width: 220px;
}

.chat__hint {
  font-size: 13px;
  color: var(--color-muted-foreground);
}

.chat__messages {
  flex: 1;
  min-height: 240px;
  overflow: auto;
  padding: var(--space-2);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.bubble {
  display: flex;
  gap: var(--space-3);
}

.bubble--user {
  flex-direction: row-reverse;
}

.bubble__role {
  flex-shrink: 0;
  width: 56px;
  font-size: 13px;
  color: var(--color-muted-foreground);
  text-align: right;
}

.bubble--user .bubble__role {
  text-align: left;
}

.bubble__body {
  max-width: min(760px, 80%);
  padding: var(--space-4);
  border-radius: var(--radius-card);
  background: var(--color-muted);
}

.bubble--user .bubble__body {
  background: var(--color-primary);
  color: var(--color-on-primary);
}

.bubble__text {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.bubble__interrupted {
  margin: 0;
  font-size: 13px;
  color: var(--color-muted-foreground);
}

.bubble__meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-2);
  font-size: 13px;
  color: var(--color-muted-foreground);
}

/* 基线 §1：三点脉冲打字指示器 */
.typing {
  display: inline-flex;
  gap: var(--space-1);
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
  0%,
  60%,
  100% {
    opacity: 0.25;
    transform: translateY(0);
  }
  30% {
    opacity: 1;
    transform: translateY(-3px);
  }
}

.chat__composer {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.chat__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}

@media (max-width: 1023px) {
  .chat__side {
    display: none;
  }
}
</style>
