# 薄弱知识点实时聚合，不建冗余表

学生的薄弱知识点不做独立表，而是在查询时按 `Exercise.knowledge_tags` 聚合
`MistakeBookEntry` 实时算出（spec §3.2 权衡 3）。

## Considered Options

- **建 `WeakKnowledgePoint` 冗余表**：查询时直接读，无需聚合；还能保留历史快照，
  便于做「掌握度随时间变化」的图表。代价是引入一条必须与 `MistakeBookEntry` 保持同步的
  派生数据 —— 而后者在 P1 已确定「掌握度可回滚」（答错即重置 `mastered=false`），
  任何一处漏更新都会让学生看到自己「已经掌握」的知识点又出现在薄弱列表里。
- **实时聚合**：单一事实来源，改判或回滚立刻反映到画像上。代价是每次查画像都要跑一次
  `GROUP BY`。

## Consequences

- 聚合成本在声明规模下（注册用户 < 1000、题库约 40 题）可以忽略，SQLite 上单次聚合
  在毫秒级。
- `GET /mistakes/profile` 与 `GET /mistakes/recommendations` 直接对 `MistakeBookEntry`
  做聚合，排除 `mastered=true` 的条目。
- 若将来需要「薄弱知识点变化曲线」这类历史视图，再引入冗余表，并以
  `MistakeBookEntry` 为事实来源做重建任务 —— 而不是反过来。
- 该决策在 P1 只落文档，实现在 P5。
