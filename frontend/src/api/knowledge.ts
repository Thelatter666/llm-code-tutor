import type { ApiResponse } from '@/types/api'
import type { ChunkOut, DocumentOut, GcOut, KnowledgeBaseOut, SearchOut } from '@/types/knowledge'
import { api } from './client'
import { repeatArrayParams } from './params'

// ---- 学生端只读（spec §6.2 knowledge 行） ----

export const listBases = (courseCode?: string) =>
  api.get<ApiResponse<KnowledgeBaseOut[]>>('/knowledge/bases', {
    params: courseCode ? { course_code: courseCode } : {},
  })

export interface SearchParams {
  query: string
  kbIds?: string[]
  courseCode?: string
  topK?: number
}

export const search = (params: SearchParams) =>
  api.get<ApiResponse<SearchOut>>('/knowledge/search', {
    params: {
      query: params.query,
      kb_ids: params.kbIds?.length ? params.kbIds : undefined,
      course_code: params.courseCode || undefined,
      top_k: params.topK,
    },
    paramsSerializer: repeatArrayParams,
  })

// ---- 管理端（spec §6.2 admin·kb 行） ----

export const createBase = (body: { name: string; description?: string; course_code?: string }) =>
  api.post<ApiResponse<KnowledgeBaseOut>>('/admin/knowledge/bases', body)

export const updateBase = (
  id: string,
  body: { name?: string; description?: string; course_code?: string },
) => api.patch<ApiResponse<KnowledgeBaseOut>>(`/admin/knowledge/bases/${id}`, body)

export const deleteBase = (id: string) =>
  api.delete<ApiResponse<{ deleted: boolean }>>(`/admin/knowledge/bases/${id}`)

export const listDocuments = (kbId: string, status?: string) =>
  api.get<ApiResponse<DocumentOut[]>>(`/admin/knowledge/bases/${kbId}/documents`, {
    params: status ? { status } : {},
  })

export const uploadDocument = (kbId: string, file: File) => {
  const form = new FormData()
  form.append('file', file)
  return api.post<ApiResponse<DocumentOut>>(`/admin/knowledge/bases/${kbId}/documents`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export const reindexDocument = (documentId: string) =>
  api.post<ApiResponse<DocumentOut>>(`/admin/knowledge/documents/${documentId}/reindex`)

export const deleteDocument = (documentId: string) =>
  api.delete<ApiResponse<{ deleted: boolean }>>(`/admin/knowledge/documents/${documentId}`)

export const listChunks = (documentId: string) =>
  api.get<ApiResponse<ChunkOut[]>>(`/admin/knowledge/documents/${documentId}/chunks`)

export const rebuildVectors = (kbId: string) =>
  api.post<ApiResponse<{ kb_id: string; status: string }>>(
    `/admin/knowledge/bases/${kbId}/rebuild-vector`,
  )

export const gcOrphanVectors = (kbId: string) =>
  api.post<ApiResponse<GcOut>>(`/admin/knowledge/bases/${kbId}/gc-orphan-vectors`)
