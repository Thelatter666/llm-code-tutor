/** 代码解析的出入参类型（spec §6.2 code 行 + §8.4，与后端 StaticReport 结构对齐）。 */

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
