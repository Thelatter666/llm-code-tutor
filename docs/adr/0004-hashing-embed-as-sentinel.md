# HashingEmbed 作为哨兵，其检索结果不注入 prompt

Embedding 三级回退的最后一级 `HashingEmbed` 产生的是无语义向量，检索结果近似随机。即便它「能跑通链路」，其产出也一律不参与业务逻辑：命中结果不注入 prompt，强制 `rag_hit=false` 并提示「已停用知识库增强」。

宁可少一个功能，不要一个错的功能 —— 若注入，模型会基于完全无关的片段理直气壮地作答，用户看到的是「引用了几段不相干内容还答得很自信」。这比知识库不可用更伤，且会直接毁掉答辩现场。

## Considered Options

- **保留注入 + 标记 `degraded=true`**：功能表面完整。但降级提示救不了观感，用户无法分辨「答案偏弱」与「答案基于噪声」。
- **去掉 HashingEmbed**：无 embedding 时知识库直接不可用，链路断掉，无法演示完整的调用路径与错误处理。

## Consequences

- 无 API Key 且未装本地 embedding 时，知识库检索实际不可用。为降低影响，本地级 `sentence-transformers` 设为 optional extras 且 **`make install` 默认安装**（见 spec §3.2 权衡 17）；`make install-lite` 可跳过。
- 该哨兵仍会执行索引写入，以保证「上传 → 切分 → 向量化 → 存储」整条链路可被演示。
