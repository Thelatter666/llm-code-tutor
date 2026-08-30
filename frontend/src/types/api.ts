export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T | null
  request_id: string
}

export interface UserOut {
  id: string
  username: string
  email: string
  role: 'student' | 'admin'
  status: 'active' | 'disabled'
}

export interface TokenPair {
  access_token: string
  refresh_token: string
}
