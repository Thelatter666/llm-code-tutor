"""习题判题的纯规则（spec §5.1 四路 + CONTEXT.md「判分 Judging」）。

本模块零 IO：判题规则可以脱离数据库单测（spec §10 领域层）。
常量供 `infrastructure/persistence/models.py` 反向引用（与
`domain/knowledge/status.py` 同模式），判题函数在下方。
"""

# --- 题型（spec §5 Exercise.type，五种齐备） ---
TYPE_CHOICE = "choice"
TYPE_MULTI = "multi"
TYPE_BLANK = "blank"
TYPE_SHORT = "short"
TYPE_CODING = "coding"
EXERCISE_TYPES = (TYPE_CHOICE, TYPE_MULTI, TYPE_BLANK, TYPE_SHORT, TYPE_CODING)

# --- 来源（spec §5 Exercise.source） ---
SOURCE_SEED = "seed"
SOURCE_ADMIN = "admin"
SOURCE_AI = "ai"
EXERCISE_SOURCES = (SOURCE_SEED, SOURCE_ADMIN, SOURCE_AI)

# --- 状态（spec §5 Exercise.status）：学生端只暴露 published ---
STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"
EXERCISE_STATUSES = (STATUS_DRAFT, STATUS_PUBLISHED)
