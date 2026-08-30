import { api } from './client'
import type { ApiResponse, TokenPair, UserOut } from '@/types/api'

export const register = (body: { username: string; email: string; password: string }) =>
  api.post<ApiResponse<UserOut>>('/auth/register', body)

export const login = (body: { username: string; password: string }) =>
  api.post<ApiResponse<TokenPair>>('/auth/login', body)

export const refresh = (refreshToken: string) =>
  api.post<ApiResponse<TokenPair>>('/auth/refresh', { refresh_token: refreshToken })

export const me = () => api.get<ApiResponse<UserOut>>('/auth/me')

export const logout = () => api.post<ApiResponse<{ logged_out: boolean }>>('/auth/logout')
