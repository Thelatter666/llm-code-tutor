# 基于大语言模型的智能编程教学辅助系统

面向编程教学场景的智能辅助系统：学生端提供 AI 答疑对话（RAG 课程知识库增强）、代码智能解析与辅导、
在线代码编辑器与受限运行、习题练习与 AI 习题辅导；管理端提供用户与知识库管理、模型参数配置与系统日志。

## 快速开始

```bash
# 1) 安装（精简版，跳过约 1GB 的 torch；需要真实语义检索再执行 make setup-local-embed）
make install-lite

# 2) 起双端口开发服务：前端 http://localhost:5173 · 后端 http://localhost:8000
make dev

# 3) 单端口演示（先构建前端，再由后端同源伺服 dist）
make serve

# 4) 全量测试（后端 pytest + 前端 vitest）
make test
```

无 API Key 时系统运行在 Mock 提供方模式（`MockProvider`），全链路可跑通，适合演示与开发。

## 受限代码执行器 —— 安全边界声明（必读）

在线编辑器的「运行」会把学生代码在本机以**受限子进程**方式执行（`POST /code/run`）。
该项能力**不是沙箱**，其安全边界如下（设计依据见 `docs/adr/0003-code-sandbox-resource-limits.md`）：

1. **黑名单只防误触，不防攻击。** 内置黑名单（`os.system`、`subprocess`、`socket` 等）用于拦截
   学生无意的危险调用；它**可以被轻易绕过**，例如 `__import__('o'+'s')`、`getattr` 链、
   编码变形等。请勿把它当作安全边界，也不要运行来源不明的代码。
2. **被执行代码以当前操作系统用户身份运行。** 系统不做用户切换、不做容器隔离，
   子进程拥有当前用户在本机上的全部权限。
3. **被执行代码对本机文件系统有读权限。** 写入有 1MB 上限（`RLIMIT_FSIZE`），读取不受限 ——
   当前用户能读的文件，被执行代码都能读。
4. **网络访问未隔离。** 当前执行器不限制子进程的网络访问（规划边界外，见 spec §3.3）。

已有的保护是**资源层**而非安全层，用于防失控而非防恶意：墙钟 5s、CPU 3s、内存 256MB
（psutil 采样进程树 RSS，macOS 下不可用 `RLIMIT_AS/DATA/RSS`，见 ADR-0003）、单流输出截断 8KB、
并发上限 2。执行结束后在 `CodeRun.limit_detail` 留存各层实测数据。

## 文档

| 文档 | 说明 |
|---|---|
| `AGENT.md` | AI 编码助手工作约束（强制） |
| `CONTEXT.md` | 术语表（Ubiquitous Language，唯一术语来源） |
| `docs/adr/` | 架构决策记录（含 0003 受限执行器资源限制） |
| `docs/superpowers/specs/` | 设计 spec |
| `docs/superpowers/plans/` | 各批次实施计划 |
| `docs/review/` | 各批次完成报告与评审 |
| `frontend/docs/ui-baseline.md` | 前端 UI 基线（配色 / 间距 / 圆角，强制） |

## 技术栈

Python 3.12 · FastAPI · SQLAlchemy 2 (async) · SQLite (aiosqlite) · Chroma · pytest ·
Vue 3 · TypeScript · Vite · Element Plus · Monaco Editor · vitest
