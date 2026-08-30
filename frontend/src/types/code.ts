/** 代码解析的出入参类型（spec §6.2 code 行 + §8.4，与后端 StaticReport 结构对齐）。 */

/**
 * 可运行语言（spec §3.1 假设 3：演示环境具备 Python 与 Node 运行时）。
 * 定义在 types 而非 api —— api 层反过来依赖 types，反过来引会造成循环。
 */
export type CodeLanguage = 'python' | 'javascript'

export interface LineStats {
  total: number
  code: number
  blank: number
  comment: number
}

export interface FunctionInfo {
  name: string
  line: number
  args: number
  complexity: number
}

export interface ClassInfo {
  name: string
  line: number
  methods: number
}

export interface ComplexitySummary {
  max: number
  average: number
  worst: string | null
}

export interface UnusedVariable {
  name: string
  line: number
}

export interface BareExcept {
  line: number
}

export interface SyntaxIssue {
  line: number
  message: string
}

export interface StaticReport {
  language: 'python' | 'javascript'
  lines: LineStats
  functions: FunctionInfo[]
  classes: ClassInfo[]
  complexity: ComplexitySummary
  issues: { unused_variables: UnusedVariable[]; bare_excepts: BareExcept[] }
  syntax_error: SyntaxIssue | null
}

export interface AIReport {
  content: string
  provider: string
  model: string
  token_usage: {
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
  } | null
  usage_estimated: boolean
  degraded: boolean
  fallback_reason: string | null
}

export interface CodeAnalysisOut {
  analysis_id: string
  language: string
  static_report: StaticReport
  ai_report: AIReport | null
  reused: boolean
}

// ---------------------------------------------------------------- 代码运行（P4 / spec §8.3）

/** spec §5 的封闭取值。 */
export type RunStatus =
  | 'accepted'
  | 'runtime_error'
  | 'timeout'
  | 'memory_exceeded'
  | 'blocked'

/**
 * 四层资源限制的实测留痕（不是配置回显）。
 * `applied` 为 false 表示该层在当前平台没设上 —— 此时 degraded_layers 会带上它。
 */
export interface LimitDetail {
  executed: boolean
  error: string | null
  blacklist: { rule: string | null; executed: boolean } | null
  wall_clock: { limit_s: number; elapsed_s: number; triggered: boolean }
  cpu: { limit_s: number; applied: boolean; error: string | null; triggered: boolean }
  memory: {
    limit_bytes: number
    sampled: boolean
    interval_ms: number
    peak_bytes: number
    samples: number
    triggered: boolean
  }
  file_size: { limit_bytes: number; applied: boolean; error: string | null }
  output: {
    limit_bytes: number
    stdout_bytes: number
    stderr_bytes: number
    stdout_truncated: boolean
    stderr_truncated: boolean
  }
  process_group: { killed: boolean }
  degraded_layers: string[]
  platform: string
}

export interface CodeRunOut {
  run_id: string
  status: RunStatus
  stdout: string
  stderr: string
  exit_code: number | null
  duration_ms: number
  limit_detail: LimitDetail | null
}

export interface CodeSessionOut {
  id: string
  language: CodeLanguage
  title: string
  source_code: string
  updated_at: string
}

export interface CodeRunHistoryItem {
  id: string
  language: CodeLanguage
  source_code: string
  status: RunStatus
  stdout: string
  stderr: string
  exit_code: number | null
  duration_ms: number
  limit_detail: LimitDetail | null
  created_at: string
}

export interface Paged<T> {
  items: T[]
  total: number
}
