import axios, { type AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import type { ApiResponse } from '@/types/api'

export const api = axios.create({ baseURL: '/api/v1', timeout: 30000 })

export const ACCESS_KEY = 'lct.access_token'
export const REFRESH_KEY = 'lct.refresh_token'

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(ACCESS_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (resp) => {
    const body = resp.data as ApiResponse
    if (body && typeof body.code === 'number' && body.code !== 0) {
      ElMessage.error(body.message)
      return Promise.reject(new Error(body.message))
    }
    return resp
  },
  (error: AxiosError<ApiResponse>) => {
    if (error.response?.status === 401) {
      localStorage.removeItem(ACCESS_KEY)
      localStorage.removeItem(REFRESH_KEY)
      if (!location.hash.startsWith('#/login')) location.hash = '#/login'
    }
    ElMessage.error(error.response?.data?.message ?? '网络异常')
    return Promise.reject(error)
  },
)
