import { api } from './client'
import type { ApiResponse } from '@/types/api'
import type {
  AdminExerciseIn,
  AdminExerciseOut,
  AdminExercisePatch,
  AdminUserIn,
  AdminUserOut,
  AdminUserPatch,
  AntiPlagiarismStatsOut,
  LogOut,
  ModelConfigOut,
  ModelConfigPutPayload,
  ModelConfigTestOut,
  OverviewOut,
  PageResult,
} from '@/types/admin'
import type { ExerciseType } from '@/types/exercise'

/** 管理后台客户端（spec §6.2 admin 行，P6）。全部端点挂 require_admin。 */

// ---------------------------------------------------------------- 用户

export interface AdminUserFilters {
  q?: string
  role?: 'student' | 'admin' | ''
  status?: 'active' | 'disabled' | ''
  page?: number
  pageSize?: number
}

export const listAdminUsers = (filters: AdminUserFilters = {}) =>
  api.get<ApiResponse<PageResult<AdminUserOut>>>('/admin/users', {
    params: {
      q: filters.q || undefined,
      role: filters.role || undefined,
      status: filters.status || undefined,
      page: filters.page,
      page_size: filters.pageSize,
    },
  })

export const createAdminUser = (body: AdminUserIn) =>
  api.post<ApiResponse<AdminUserOut>>('/admin/users', body)

export const updateAdminUser = (id: string, body: AdminUserPatch) =>
  api.patch<ApiResponse<AdminUserOut>>(`/admin/users/${id}`, body)

export const deleteAdminUser = (id: string) =>
  api.delete<ApiResponse<{ deleted: boolean }>>(`/admin/users/${id}`)

// ---------------------------------------------------------------- 模型配置

export const getModelConfig = () =>
  api.get<ApiResponse<ModelConfigOut>>('/admin/model-config')

export const putModelConfig = (body: ModelConfigPutPayload) =>
  api.put<ApiResponse<ModelConfigOut>>('/admin/model-config', body)

/** 只测已保存配置（裁定 2）；失败返回 ok=false 而非 HTTP 错误。 */
export const testModelConfig = () =>
  api.post<ApiResponse<ModelConfigTestOut>>('/admin/model-config/test')

// ---------------------------------------------------------------- 日志 / 仪表盘 / 统计

export interface LogFilters {
  action?: string
  userId?: string
  start?: string
  end?: string
  page?: number
  pageSize?: number
}

export const listAdminLogs = (filters: LogFilters = {}) =>
  api.get<ApiResponse<PageResult<LogOut>>>('/admin/logs', {
    params: {
      action: filters.action || undefined,
      user_id: filters.userId || undefined,
      start: filters.start || undefined,
      end: filters.end || undefined,
      page: filters.page,
      page_size: filters.pageSize,
    },
  })

export const getOverview = () => api.get<ApiResponse<OverviewOut>>('/admin/overview')

export const getAntiPlagiarismStats = () =>
  api.get<ApiResponse<AntiPlagiarismStatsOut>>('/admin/anti-plagiarism/stats')

// ---------------------------------------------------------------- 习题（管理端）

export interface AdminExerciseFilters {
  type?: ExerciseType | ''
  difficulty?: number | ''
  knowledgeTag?: string
  status?: 'draft' | 'published' | ''
  page?: number
  pageSize?: number
}

export const listAdminExercises = (filters: AdminExerciseFilters = {}) =>
  api.get<ApiResponse<PageResult<AdminExerciseOut>>>('/admin/exercises', {
    params: {
      type: filters.type || undefined,
      difficulty: filters.difficulty || undefined,
      knowledge_tag: filters.knowledgeTag || undefined,
      status: filters.status || undefined,
      page: filters.page,
      page_size: filters.pageSize,
    },
  })

export const getAdminExercise = (id: string) =>
  api.get<ApiResponse<AdminExerciseOut>>(`/admin/exercises/${id}`)

export const createAdminExercise = (body: AdminExerciseIn) =>
  api.post<ApiResponse<AdminExerciseOut>>('/admin/exercises', body)

export const updateAdminExercise = (id: string, body: AdminExercisePatch) =>
  api.patch<ApiResponse<AdminExerciseOut>>(`/admin/exercises/${id}`, body)

export const deleteAdminExercise = (id: string) =>
  api.delete<ApiResponse<{ deleted: boolean }>>(`/admin/exercises/${id}`)
