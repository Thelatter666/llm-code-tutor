# 采用模块化单体而非微服务

系统覆盖答疑、知识库、代码执行、习题、管理后台五大能力面，但整体运行在单个 FastAPI 进程内，靠领域分包（`auth / chat / knowledge / code / exercise / admin / audit`）与分层（routers → services → domain → infrastructure）维持边界。选它而非按能力拆服务，是因为交付定位是「毕设级演示原型」——一键启动与低联调成本的价值远高于进程级故障隔离，而后者在已声明的规模与无伸缩需求下无人买单。

## Considered Options

- **拆三个服务（gateway / ai-service / sandbox-service）**：故障域隔离、可独立扩容。与「一键启动」硬约束直接冲突 —— 演示要起三个进程加服务发现，联调与日志排查成本陡增，而多花的力气全部落在非功能性需求上。
- **单体 + 独立沙箱服务**：执行器崩溃不拖垮主服务。但执行器本就以 `subprocess` 运行，天然已是独立进程，已获得该方案的核心收益，无需再付编排成本。

## Consequences

- 领域边界靠目录约定与代码评审维持，无编译期或进程级强制。跨领域调用必须走 `services/` 层，不得跨层直连。
- 外部能力（LLM / Embedding / VectorStore / CodeExecutor / CodeParser）定义为 `Protocol` 端口，真实实现与 Mock 实现同签名注入 —— 这是后续替换组件的唯一接缝。
