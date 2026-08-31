import { api } from './client'
import type { ApiResponse } from '@/types/api'
import type {
  MistakeEntryOut,
  RecommendationsOut,
  WeakKnowledgePointOut,
} from '@/types/mistake'

/** 学生端错题本只读四件套 + 手动重置掌握度（spec §6.2 mistake 行）。 */

/** `mastered` 三态：不传=全部、false=未掌握、true=已掌握。 */
export const listMistakes = (mastered?: boolean) =>
  api.get<ApiResponse<MistakeEntryOut[]>>('/mistakes', {
    params: typeof mastered === 'boolean' ? { mastered } : {},
  })

/** 薄弱知识点画像：按知识点聚合 wrong_count，排除已掌握，降序（spec §8.5）。 */
export const getProfile = () =>
  api.get<ApiResponse<WeakKnowledgePointOut[]>>('/mistakes/profile')

/** 定向推荐：top-3 薄弱知识点 → 难度升序 → 不足时随机补足并标注 filled_by。 */
export const getRecommendations = (limit = 5) =>
  api.get<ApiResponse<RecommendationsOut>>('/mistakes/recommendations', {
    params: { limit },
  })

/**
 * 手动重置掌握度（裁定 2）：mastered=false、mastered_at=null、consecutive_correct=0，
 * 而 wrong_count 与上次错误记录保留 —— 是「开启新一轮练习」，不是抹掉历史。
 */
export const resetMastery = (entryId: string) =>
  api.delete<ApiResponse<MistakeEntryOut>>(`/mistakes/${entryId}/mastered`)
