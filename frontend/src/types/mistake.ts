import type { AnswerValue, ExerciseListItem } from './exercise'

/** 错题本出入参（对齐后端 `app/schemas/exercise.py` 的错题本视图）。 */

/** 错题条目（MistakeBookEntry）+ 学生视图的习题摘要（不含答案，不泄题）。 */
export interface MistakeEntryOut {
  id: string
  exercise_id: string
  wrong_count: number
  /** 连续答对计数：达 2 次即已掌握；手动重置会清零（裁定 2） */
  consecutive_correct: number
  last_wrong_answer: AnswerValue
  last_wrong_at: string | null
  mastered: boolean
  mastered_at: string | null
  exercise: ExerciseListItem
}

/** 薄弱知识点（WeakKnowledgePoint）：实时聚合，无独立表。 */
export interface WeakKnowledgePointOut {
  knowledge_tag: string
  wrong_count: number
}

export interface RecommendationItemOut {
  exercise: ExerciseListItem
  /**
   * profile = 来自薄弱知识点画像；random = 随机补足。
   * 二者必须区分展示，否则学生会把随机题误当个性化推荐（CONTEXT.md RandomFill）。
   */
  filled_by: 'profile' | 'random'
}

export interface RecommendationsOut {
  items: RecommendationItemOut[]
  weak_tags: string[]
}
