# 强制单 worker 运行

一键脚本固定 `uvicorn --workers 1`，SQLite 开 WAL + `busy_timeout=5000`，Chroma 使用单 `PersistentClient` 实例。原因是 SQLite 与 Chroma 的本地持久化目录**都不支持多进程并发写** —— 前者在多 worker 下会 `database is locked`，后者会损坏索引；而 `BackgroundTasks` 索引任务在多 worker 下还会各写各的，产生重复向量。

## Considered Options

- **多 worker + 换 PostgreSQL 与独立向量服务**：可水平扩展。但引入外部服务，直接违背「零外部服务、一键启动」的定位，且把工作量转移到非功能性需求上。
- **多 worker + 分布式锁**：能解决写冲突。但分布式锁已在边界外声明，为一个演示原型引入锁服务不成比例。

## Consequences

- 所有同步阻塞调用（代码执行、判题、知识库索引、embedding 推理）必须经 `run_in_threadpool` 卸载到线程池，否则单次代码运行的 5 秒超时会冻结整个后端。
- SSE 中断注册表（`asyncio.Event` 内存表）与 per-`kb_id` 的 `asyncio.Lock` **均依赖单进程前提**。若将来改为多 worker，这三者需一并替换为跨进程实现。
- 无法利用多核。并发 <50 下可接受：时间主要消耗在等待 LLM 响应，而非本地 CPU。
