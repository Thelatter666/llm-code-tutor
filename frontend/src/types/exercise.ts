import type { Citation, TokenUsage } from './chat'
import type { RunStatus } from './code'

/**
 * 习题与错题本的出入参（对齐后端 `app/schemas/exercise.py`）。
 *
 * 术语：实体是「习题」（Exercise），文案一律用「习题」，不用「题目」「试题」。
 */

export type ExerciseType = 'choice' | 'multi' | 'blank' | 'short' | 'coding'

/** hint 的两种学生可见意图；`judging` 是内部判分意图，不对 HTTP 开放（契约定稿 3）。 */
export type HintIntent = 'seek_answer' | 'review_my_code'

export const TYPE_LABELS: Record<ExerciseType, string> = {
  choice: '单选题',
  multi: '多选题',
  blank: '填空题',
  short: '简答题',
  coding: '编程题',
}

/**
 * 作答与答案值，各题型同形（契约定稿 7）：
 * choice `"B"` · multi `["A","C"]` · blank/short 字符串 ·
 * 编程题学生作答 `{"source": 源码}`、题库参考答案 `{"language","solution"}`。
 */
export type AnswerValue = string | string[] | Record<string, string> | null

/** 编程题的学生作答载荷：只交源码，执行语言由题库的 test_cases 决定。 */
export type CodingAnswer = { source: string }

export interface ExerciseListItem {
  id: string
  type: ExerciseType
  stem: string
  options: Record<string, string> | null
  difficulty: number
  knowledge_tags: string[]
}

/** 学生详情：后端刻意不含 answer / explanation / test_cases（提交前不泄题）。 */
export interface ExerciseDetail extends ExerciseListItem {
  language: string | null
}

export interface ExerciseListOut {
  items: ExerciseListItem[]
  total: number
  /** 筛选下拉的数据源；不受 knowledge_tag 过滤影响（契约定稿 11）。 */
  facets: { knowledge_tags: string[] }
}

/** judge_detail 的并集形态：各题型只填自己那部分键（契约定稿 8）。 */
export interface JudgeCase {
  index: number
  stdin: string
  expected_stdout: string
  actual_stdout: string | null
  passed: boolean
  duration_ms: number
  /** 执行器回报的领域状态（与 /code/run 同一取值集，见 types/code.ts::RunStatus） */
  status: RunStatus
  skipped?: boolean
  skip_reason?: string
}

export interface JudgeDetail {
  method?: 'direct' | 'executed'
  passed?: boolean
  missing?: string[]
  wrong?: string[]
  language?: string
  budget_exceeded?: boolean
  budget_limit_s?: number
  cases?: JudgeCase[]
  error?: string
  ai_scored?: boolean
  judge_mode?: 'model' | 'mock_heuristic'
  model?: string | null
  provider?: string | null
  token_usage?: TokenUsage | null
  feedback?: string
}

export interface SubmitOut {
  submission_id: string
  exercise_id: string
  answer: AnswerValue
  is_correct: boolean | null
  score: number
  judge_detail: JudgeDetail | null
  feedback: string | null
  attempt_no: number
  created_at: string
  /** 提交后才揭示的字段（spec §5.1 前端展示需求） */
  correct_answer: AnswerValue
  explanation: string
  ai_scored: boolean
}

/** hint 的 `done` 载荷：chat §6.1 的同源变体，以 exercise_id + intent 替代 message_id。 */
export interface HintDoneEvent {
  exercise_id: string
  intent: HintIntent
  token_usage: TokenUsage
  usage_estimated: boolean
  model: string | null
  provider: string | null
  rag_hit: boolean
  degraded: boolean
  fallback_reason: string | null
}

export interface HintErrorEvent {
  code: number
  message: string
}
