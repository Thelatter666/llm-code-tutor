"""答疑对话的防抄袭策略规则（零 IO）。

**请求意图（CONTEXT.md「请求意图」）决定防抄袭档位是否生效，且意图是显式契约、
不是推断** —— 见 ADR-0005：学生问「这道题怎么做」时常顺手贴题目里的示例代码，
若按「消息含代码块即判为评改」推断，就会误判为豁免并直接给出完整答案，
代价（泄露完整答案）与收益不对称。因此本模块只接收调用方显式传入的 intent，
绝不查看消息内容来猜测意图。

**防抄袭底线（spec §7.1）** 三档共有、不可覆盖、硬编码 —— 这里给出的是「是否
触发底线」的判定（用于 §7.4 的拦截率度量），而底线条文本身硬编码在
`app/prompts/_floor.j2` 里，由所有模板无条件 include。
"""

# --- 请求意图 ---
SEEK_ANSWER = "seek_answer"
REVIEW_MY_CODE = "review_my_code"
JUDGING = "judging"
REQUEST_INTENTS = (SEEK_ANSWER, REVIEW_MY_CODE, JUDGING)

# spec §7.1 豁免表：评改已写代码（学生已写出代码）与判分（不向学生输出实现）
EXEMPT_INTENTS = (REVIEW_MY_CODE, JUDGING)

# --- 防抄袭档位（CONTEXT.md「防抄袭档位」，由管理员在后台配置） ---
MODE_STRICT = "strict"
MODE_GUIDED = "guided"
MODE_LOOSE = "loose"
ANTI_PLAGIARISM_MODES = (MODE_STRICT, MODE_GUIDED, MODE_LOOSE)
DEFAULT_MODE = MODE_GUIDED

# --- 消息角色（spec §5 Message.role） ---
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"
MESSAGE_ROLES = (ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM)

# --- 会话标题 ---
DEFAULT_CONVERSATION_TITLE = "新的对话"
TITLE_MAX_CHARS = 20

# --- 审计动作（spec §8.1：无论正常结束还是异常中断都要写入） ---
ACTION_CHAT = "chat"

# --- 底线规则名（落 Message.blocked_by_policy 的判定依据） ---
FLOOR_HOMEWORK = "homework_ghostwriting"
FLOOR_EXAM = "exam_in_progress"

# 索取实现的措辞：单独出现不足以判定，需与「作业/代做」同现
_HOMEWORK_NOUNS = ("作业", "代做", "帮我写", "帮我做", "直接给")
_HOMEWORK_ASKS = ("帮我", "给我", "直接", "写出", "写完", "答案", "完整")

# 考试 / 竞赛场景：需与「进行中」的措辞同现，否则「考试怎么复习」会被误判
_EXAM_NOUNS = ("考试", "竞赛", "机考", "在线作答")
_EXAM_PROGRESS = ("正在", "现在", "当场", "考试中", "比赛中", "在线")


def is_exempt(intent: str) -> bool:
    """该意图是否豁免防抄袭档位约束（ADR-0005）。

    只看传入的 intent，不看消息内容 —— 推断错了泄露的是完整答案。
    """
    return intent in EXEMPT_INTENTS


def resolve_mode(intent: str, configured: str | None) -> str | None:
    """本次请求生效的防抄袭档位；豁免意图返回 `None`（不施加档位约束）。

    返回 `None` **只免档位，不免底线** —— 底线条文由模板无条件注入，
    装配器侧不存在任何「跳过底线」的开关（spec §3.2 权衡 10）。

    未配置时落 `guided`（spec §7.1 标注为默认档位）。
    """
    if is_exempt(intent):
        return None
    return configured or DEFAULT_MODE


def detect_floor_violation(content: str) -> str | None:
    """返回命中的底线规则名；未命中返回 `None`。

    **CONTEXT.md：拦截率是度量口径，不是检测能力。** 这里刻意用确定性关键词
    规则而非 LLM 分类 —— 若「是否触发底线」本身由模型决定，该指标就不可复现，
    也无法写单测，度量也就失去了意义。
    """
    if not content:
        return None

    text = content.lower()
    if _all_in(text, _EXAM_NOUNS, _EXAM_PROGRESS):
        return FLOOR_EXAM
    if _all_in(text, _HOMEWORK_NOUNS, _HOMEWORK_ASKS):
        return FLOOR_HOMEWORK
    return None


def _all_in(text: str, first: tuple[str, ...], second: tuple[str, ...]) -> bool:
    """两组词各至少命中一个才成立 —— 单个词命中太容易误伤正常提问。"""
    return any(w in text for w in first) and any(w in text for w in second)
