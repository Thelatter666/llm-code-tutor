"""习题种子（spec §11 P5 行：约 40 题，覆盖 Python 基础知识点，五种题型齐备）。

**幂等口径（契约定稿 6）**：Exercise 没有自然键（题干会被改、题型不是标识），
所以用 **uuid5 确定性主键** —— `uuid5(NAMESPACE_URL, "llm-code-tutor:exercise:<slug>")`，
slug 在数据里显式给定。写入前按主键查存在即跳过，不覆盖：管理员在后台改过的习题
不会被 `make seed` 打回原形，这与 admin / ModelConfig 的「已存在则跳过」同一语义。
不为此在 spec §5 之外新增列 —— 幂等判定落在主键的确定性上。

**形状与可解性**：每条数据在写入前过 `domain/exercise.shapes` 的跨题型规则（脏数据
直接抛错、不静默入库）；coding 题的参考答案必须对其全部 `test_cases` 通过，由
`tests/test_seed_exercises.py` 用**真** `SubprocessCodeExecutor` 参数化实测 ——
那是种子可解性的唯一证据（总指挥交接 §9 审阅重点）。
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exercise.judging import SOURCE_SEED, STATUS_PUBLISHED
from app.domain.exercise.shapes import check_exercise_shape
from app.infrastructure.persistence.models import Exercise

# 知识点标签封闭词表（spec §11：覆盖 Python 基础知识点；画像与推荐以此为口径）
KNOWLEDGE_TAGS = (
    "变量与赋值", "数据类型", "运算符", "控制流", "循环", "函数",
    "列表", "字典", "字符串", "切片", "推导式", "异常处理",
)

# 题型与难度配比（spec §11 的题量要求；测试按这两张表核对，改数据前先确认还达不达标）
TYPE_QUOTAS = {"choice": 10, "multi": 6, "blank": 8, "short": 8, "coding": 8}
DIFFICULTY_QUOTAS = {1: 8, 2: 10, 3: 12, 4: 7, 5: 3}

# slug 命名空间：urn 前缀 + slug 唯一决定主键，换前缀等于换整批 id（勿改）
SLUG_URN_PREFIX = "llm-code-tutor:exercise:"

# 种子数据：40 道 Python 基础习题。配比 choice 10 / multi 6 / blank 8 / short 8 / coding 8；
# 难度分布 1×8 / 2×10 / 3×12 / 4×7 / 5×3；knowledge_tags 只取 KNOWLEDGE_TAGS 封闭词表，
# 每个标签至少被 2 道习题引用 —— 薄弱知识点画像与定向推荐要能闭环。
# 形态由 seedable() 在入库前逐条校验；coding 题的可解性由 tests/test_seed_exercises.py
# 用**真** SubprocessCodeExecutor 逐用例实测。
EXERCISES: list[dict] = [
    {
        "slug": "py-choice-01",
        "type": "choice",
        "difficulty": 1,
        "knowledge_tags": ["数据类型"],
        "stem": "在 Python 3 中，表达式 type(3.0) 的返回结果是什么？",
        "options": {
            "A": "<class 'int'>",
            "B": "<class 'float'>",
            "C": "<class 'str'>",
            "D": "<class 'bool'>",
        },
        "answer": "B",
        "explanation": "3.0 带小数点，是浮点数，type() 返回 <class 'float'>。易错点：只看到数字 3 就误选 int；整数 3 才是 int，写成 3.0 就变成 float。",
    },
    {
        "slug": "py-choice-02",
        "type": "choice",
        "difficulty": 1,
        "knowledge_tags": ["变量与赋值"],
        "stem": "下列哪个是 Python 中合法的变量名？",
        "options": {
            "A": "2total",
            "B": "my-name",
            "C": "_score",
            "D": "class",
        },
        "answer": "C",
        "explanation": "变量名由字母（含中文等 Unicode 字母）、数字、下划线组成，且不能以数字开头，也不能是关键字。_score 以下划线开头是合法的；class 是保留关键字，my-name 含减号会被解析成减法表达式。",
    },
    {
        "slug": "py-choice-03",
        "type": "choice",
        "difficulty": 1,
        "knowledge_tags": ["运算符"],
        "stem": "Python 中表达式 7 // 2 的结果是什么？",
        "options": {
            "A": "3.5",
            "B": "3",
            "C": "4",
            "D": "1",
        },
        "answer": "B",
        "explanation": "// 是整除运算符，7 // 2 结果为 3。易错点：把 // 当成普通除法 / 得到 3.5，或把它当成取余 % 得到 1。",
    },
    {
        "slug": "py-choice-04",
        "type": "choice",
        "difficulty": 1,
        "knowledge_tags": ["异常处理"],
        "stem": "执行表达式 1 / 0 时，Python 会抛出哪种异常？",
        "options": {
            "A": "ValueError",
            "B": "TypeError",
            "C": "ZeroDivisionError",
            "D": "MemoryError",
        },
        "answer": "C",
        "explanation": "除数为 0 时 Python 抛出 ZeroDivisionError。易错点：ValueError 通常用于值不合规范（如 int('abc')），TypeError 用于类型不匹配（如 'a' + 1），都不是除零的异常。",
    },
    {
        "slug": "py-choice-05",
        "type": "choice",
        "difficulty": 2,
        "knowledge_tags": ["字符串", "切片"],
        "stem": (
            "执行下列代码，输出是什么？\n"
            "s = \"Hello\"\n"
            "print(s[1:3])"
        ),
        "options": {
            "A": "Hel",
            "B": "el",
            "C": "ell",
            "D": "lo",
        },
        "answer": "B",
        "explanation": "切片 s[1:3] 取下标 1 到 2（左闭右开），即 'e' 和 'l'，结果是 'el'。易错点：把右端点 3 也包含进去得到 'Hel'，或整体下标偏移一格。",
    },
    {
        "slug": "py-choice-06",
        "type": "choice",
        "difficulty": 2,
        "knowledge_tags": ["列表"],
        "stem": (
            "执行下列代码后，列表 a 的长度是多少？\n"
            "a = [1, 2, 3]\n"
            "a.append([4, 5])"
        ),
        "options": {
            "A": "4",
            "B": "5",
            "C": "6",
            "D": "3",
        },
        "answer": "A",
        "explanation": "append 把整个参数当作一个元素追加到列表末尾，所以 [4, 5] 作为 1 个元素加入，长度从 3 变成 4。易错点：把 append 和 extend 混淆，extend 才会逐个添加使长度变为 5。",
    },
    {
        "slug": "py-choice-07",
        "type": "choice",
        "difficulty": 2,
        "knowledge_tags": ["控制流"],
        "stem": (
            "执行下列代码后，变量 y 的值是什么？\n"
            "x = 10\n"
            "if x > 5:\n"
            "    y = 1\n"
            "elif x > 8:\n"
            "    y = 2\n"
            "else:\n"
            "    y = 3"
        ),
        "options": {
            "A": "1",
            "B": "2",
            "C": "3",
            "D": "程序报错",
        },
        "answer": "A",
        "explanation": "if-elif-else 结构中，只要某个分支条件成立就执行该分支并跳过后面所有分支。x = 10 首先满足 x > 5，所以 y = 1；虽然 x > 8 也成立，但 elif 不会再被检查。",
    },
    {
        "slug": "py-choice-08",
        "type": "choice",
        "difficulty": 3,
        "knowledge_tags": ["循环"],
        "stem": (
            "执行下列代码，输出是什么？\n"
            "s = 0\n"
            "for i in range(1, 10):\n"
            "    s = s + i\n"
            "print(s)"
        ),
        "options": {
            "A": "45",
            "B": "55",
            "C": "36",
            "D": "10",
        },
        "answer": "A",
        "explanation": "range(1, 10) 生成 1 到 9（右端点 10 不包含），累加和为 45。最常见的错误是误以为包含 10 而算成 55；也可能因下界看错算成 36（1 到 8 之和）。",
    },
    {
        "slug": "py-choice-09",
        "type": "choice",
        "difficulty": 3,
        "knowledge_tags": ["函数"],
        "stem": (
            "执行下列代码，输出是什么？\n"
            "def add_one(n):\n"
            "    result = n + 1\n"
            "\n"
            "print(add_one(5))"
        ),
        "options": {
            "A": "5",
            "B": "6",
            "C": "None",
            "D": "程序报错",
        },
        "answer": "C",
        "explanation": "函数内没有 return 语句时，即使计算了 result，也不会把值返回，函数默认返回 None，所以打印 None。易错点：误以为函数里算出的变量会自动返回或自动打印；result 是局部变量，函数结束即销毁。",
    },
    {
        "slug": "py-choice-10",
        "type": "choice",
        "difficulty": 4,
        "knowledge_tags": ["字典", "推导式"],
        "stem": (
            "执行下列代码后，len(d) 的结果是什么？\n"
            "names = [\"Ann\", \"Bob\", \"Ann\"]\n"
            "d = {name: len(name) for name in names}"
        ),
        "options": {
            "A": "3",
            "B": "2",
            "C": "6",
            "D": "程序因键重复而报错",
        },
        "answer": "B",
        "explanation": "字典的键必须唯一，推导式中 'Ann' 出现两次，第二次会以相同的值覆盖而不是新增条目，所以最终只有 'Ann' 和 'Bob' 两个键，长度为 2。易错点：以为三个字符串就会产生三个键值对，或以为重复键会报错。",
    },
    {
        "slug": "py-multi-01",
        "type": "multi",
        "difficulty": 1,
        "knowledge_tags": ["数据类型"],
        "stem": "下列关于 Python 数据类型的说法中，正确的有哪些？",
        "options": {
            "A": "type(3.0) 得到的类型是 float，即带小数点的字面量默认是浮点类型",
            "B": "bool 是 int 的子类，表达式 True + 1 的结果等于 2",
            "C": "字符串支持原地修改，对 s = \"abc\" 执行 s[0] = \"x\" 可以把首字符换成 x",
            "D": "None 表示\"没有值\"，它是 NoneType 类型的唯一取值",
        },
        "answer": ["A", "B", "D"],
        "explanation": "3.0 不带引号，是 float 字面量；bool 继承自 int，True 参与运算时按 1 计，故 True + 1 等于 2；None 是 NoneType 的唯一值。C 是典型误区：字符串是不可变序列，s[0] = \"x\" 会抛出 TypeError 而不是修改内容。",
    },
    {
        "slug": "py-multi-02",
        "type": "multi",
        "difficulty": 3,
        "knowledge_tags": ["运算符"],
        "stem": "下列哪些表达式的计算结果是正确的？",
        "options": {
            "A": "7 // 2 * 0.5 的结果是 1.5",
            "B": "2 ** 3 ** 2 的结果是 512",
            "C": "-7 // 2 的结果是 -3",
            "D": "5 / 5 的结果是 int 类型的 1",
            "E": "7 // 2 的结果是 3",
        },
        "answer": ["A", "B", "E"],
        "explanation": "A 中先算 7 // 2 得 3，再乘 0.5 得 1.5；B 中 ** 是右结合，等价于 2 ** (3 ** 2) = 2 ** 9 = 512，误按左结合会算成 64；E 中整除向下取整得 3。C 错在整除是向负无穷方向取整，-7 // 2 应为 -4 而不是截断取 -3；D 错在 / 永远返回 float，结果是 1.0。",
    },
    {
        "slug": "py-multi-03",
        "type": "multi",
        "difficulty": 2,
        "knowledge_tags": ["字符串"],
        "stem": "下列哪些字符串表达式的结果为 True（或描述正确）？",
        "options": {
            "A": "'abc'.upper().isupper() 的结果为 True",
            "B": "'a,b,c'.split(',') 返回包含 3 个元素的列表 ['a', 'b', 'c']",
            "C": "'hello' + 5 会得到字符串 'hello5'",
            "D": "'3.14'.isdigit() 的结果为 False",
        },
        "answer": ["A", "B", "D"],
        "explanation": "upper 转大写后 isupper 为 True；split 按逗号切分得到 3 个元素的列表；isdigit 要求全部字符都是数字，'3.14' 含小数点所以为 False。C 是常见错误：字符串不能直接与 int 用 + 拼接，会抛出 TypeError，需先 str(5)。",
    },
    {
        "slug": "py-multi-04",
        "type": "multi",
        "difficulty": 3,
        "knowledge_tags": ["列表"],
        "stem": (
            "执行下列代码后，哪些说法是正确的？\n"
            "a = [1, 2, 3]\n"
            "b = a\n"
            "b.append(4)\n"
            "c = a[:]\n"
            "c.append(5)"
        ),
        "options": {
            "A": "len(a) 的结果是 4",
            "B": "a == c 的结果是 False",
            "C": "b is a 的结果是 True",
            "D": "c is a 的结果是 True",
        },
        "answer": ["A", "B", "C"],
        "explanation": "b = a 只是多一个名字指向同一个列表对象，b.append(4) 会让 a 也变成 4 个元素，故 A、C 正确；c = a[:] 创建了新列表 [1, 2, 3, 4]，再追加 5 得到 [1, 2, 3, 4, 5]，与 a（[1, 2, 3, 4]）内容不同且不是同一对象，故 B 正确、D 错误。关键易错点是区分\"赋值共享引用\"和\"切片产生新列表\"。",
    },
    {
        "slug": "py-multi-05",
        "type": "multi",
        "difficulty": 3,
        "knowledge_tags": ["异常处理", "函数"],
        "stem": (
            "关于下面这个函数，哪些说法是正确的？\n"
            "def safe_div(a, b):\n"
            "    try:\n"
            "        return a / b\n"
            "    except ZeroDivisionError:\n"
            "        return 0\n"
            "    finally:\n"
            "        print('done')"
        ),
        "options": {
            "A": "调用 safe_div(6, 2) 返回 3.0，并且会打印 done",
            "B": "调用 safe_div(1, 0) 返回 0，并且会打印 done",
            "C": "当不抛出异常时，finally 中的代码不会执行",
            "D": "若把 except Exception 写在 except ZeroDivisionError 之前，除以零时会先进入 except Exception 分支",
        },
        "answer": ["A", "B", "D"],
        "explanation": "finally 块无论是否发生异常都会执行，所以 A、B 都会打印 done，C 错误；except 按书写顺序匹配第一个合适的分支，ZeroDivisionError 是 Exception 的子类，把它写在后面就轮不到它，D 正确。另一个易错点：6 / 2 用 / 除得到的是浮点数 3.0 而非 3。",
    },
    {
        "slug": "py-multi-06",
        "type": "multi",
        "difficulty": 4,
        "knowledge_tags": ["推导式", "切片"],
        "stem": "已知 nums = [1, 2, 3, 4, 5, 6]，下列哪些表达式的结果恰好是 [2, 4, 6]？",
        "options": {
            "A": "[x for x in nums if x % 2 == 0]",
            "B": "[nums[i] for i in range(1, 6, 2)]",
            "C": "nums[1::2]",
            "D": "[x for x in nums if x // 2]",
            "E": "[x for x in nums if x % 2 == 1][:3]",
        },
        "answer": ["A", "B", "C"],
        "explanation": "A 用 x % 2 == 0 筛出偶数；B 的 range(1, 6, 2) 给出下标 1、3、5，取出偶数值 2、4、6；C 的切片从下标 1 开始、步长 2，结果相同。D 是典型陷阱：条件写成 x // 2 用的是\"非零即真\"，3 // 2 = 1 也被保留，得到 [2, 3, 4, 5, 6]；E 先筛出奇数 [1, 3, 5] 再取前 3 个，结果仍是奇数。此题需要把求余判断、range 步长和切片三者对照验证。",
    },
    {
        "slug": "py-blank-01",
        "type": "blank",
        "difficulty": 1,
        "knowledge_tags": ["数据类型"],
        "stem": "在 Python 中，用于查看一个值所属数据类型的内置函数名是 ____，例如对 3.5 调用它会返回 <class 'float'>。",
        "answer": "type",
        "explanation": "type() 是 Python 内置的类型查看函数，传入任意对象返回其类型。易错点是写成其他语言的 typeof，Python 中不存在该函数。",
    },
    {
        "slug": "py-blank-02",
        "type": "blank",
        "difficulty": 1,
        "knowledge_tags": ["函数"],
        "stem": "在 Python 中，定义函数使用的关键字是 ____，它必须出现在函数名之前，且定义行末尾要带冒号。",
        "answer": "def",
        "explanation": "def 是定义函数的保留关键字，后接函数名和括号，行末带冒号。易错点是漏写冒号或与 return 混淆：def 负责定义函数，return 负责返回结果。",
    },
    {
        "slug": "py-blank-03",
        "type": "blank",
        "difficulty": 2,
        "knowledge_tags": ["切片"],
        "stem": "在 Python 3 中，执行 print(\"abcdefgh\"[2:5]) 输出的结果是 ____。",
        "answer": "cde",
        "explanation": "切片遵循左闭右开规则，取下标 2、3、4 三个字符，即 'c'、'd'、'e'，下标 5 的 'f' 不包含。易错点是误当成包含右端点而写成 cdef。",
    },
    {
        "slug": "py-blank-04",
        "type": "blank",
        "difficulty": 2,
        "knowledge_tags": ["运算符"],
        "stem": "在 Python 3 中，执行 print(7 // 2) 输出的结果是 ____。",
        "answer": "3",
        "explanation": "// 是整除（地板除）运算符，结果为两数相除后向下取整的整数，7/2=3.5 向下取整得 3。易错点是写成 3.5，那是普通除法 / 的结果。",
    },
    {
        "slug": "py-blank-05",
        "type": "blank",
        "difficulty": 3,
        "knowledge_tags": ["异常处理"],
        "stem": "在 Python 3 中，执行 int(\"3.5\") 会抛出一种异常，该异常类的名称是 ____。",
        "answer": "ValueError",
        "explanation": "int() 只能把表示整数的字符串（如 \"35\"）或数值直接转换，\"3.5\" 形式合法但值不能转为整数，因此抛出 ValueError（值错误）。易错点是误选 TypeError：类型错误只发生在传入完全不支持的类型时，而字符串是 int() 支持的参数类型，问题出在值本身。",
    },
    {
        "slug": "py-blank-06",
        "type": "blank",
        "difficulty": 2,
        "knowledge_tags": ["推导式"],
        "stem": "在 Python 3 中，执行 print(len([x for x in range(10) if x % 2 == 0])) 输出的结果是 ____。",
        "answer": "5",
        "explanation": "range(10) 生成 0 到 9，其中能被 2 整除的是 0、2、4、6、8 共 5 个。两个易错点：一是遗漏 0（0 也是偶数），二是把 range(10) 当成包含 10（实际右端不含）。",
    },
    {
        "slug": "py-blank-07",
        "type": "blank",
        "difficulty": 4,
        "knowledge_tags": ["字典", "推导式"],
        "stem": "在 Python 3 中，执行 print(sum([v for v in {'a': 1, 'b': 2, 'c': 3}.values() if v > 1])) 输出的结果是 ____。",
        "answer": "5",
        "explanation": "字典的 values() 取出所有值 1、2、3，推导式中 if v > 1 过滤出 2 和 3，sum 求和得 5。易错点有二：直接 for v in 字典 迭代得到的是键而不是值，必须用 .values()；以及条件 v > 1 不包含 1。",
    },
    {
        "slug": "py-blank-08",
        "type": "blank",
        "difficulty": 5,
        "knowledge_tags": ["推导式", "列表"],
        "stem": "在 Python 3 中，执行 print(sum(x for x in [y * 2 for y in range(5)] if x > 4)) 输出的结果是 ____。",
        "answer": "14",
        "explanation": "内层列表推导式先把 range(5) 的 0～4 各乘 2，得到 [0, 2, 4, 6, 8]；外层生成器表达式保留大于 4 的 6 和 8，sum 求和得 14。易错点有三：一是把 range(5) 当成包含 5；二是把条件 x > 4 误读成 x >= 4 而多算一个 4；三是忘记内层已乘 2、直接用原始值判断（那样只剩大于 4 的数不同）。",
    },
    {
        "slug": "py-short-01",
        "type": "short",
        "difficulty": 1,
        "knowledge_tags": ["列表", "字典"],
        "stem": "用自己的话简要说明 Python 中列表（list）和字典（dict）在用途与存取方式上的主要区别，并各举一个适合使用它的生活化例子。",
        "answer": "列表按位置（从 0 开始的数字下标）顺序存放一组元素，元素可以重复，适合存放一组需要按顺序遍历的同类数据，例如记录全班同学的成绩。字典以“键: 值”成对存放数据，直接用有意义的键来查值，键必须唯一且不可变，适合描述一个对象的属性或建立映射关系，例如用学号查某位同学的姓名。核心区别是：列表靠数字位置定位，字典靠键定位。",
        "explanation": "该题考察对两种容器本质差异的记忆与表述：列表是有序序列、按下标访问；字典是键值映射、按键访问且键唯一不可变。常见易错点是把字典也说成“按下标访问”，或忽略“键必须唯一”这一约束。",
    },
    {
        "slug": "py-short-02",
        "type": "short",
        "difficulty": 2,
        "knowledge_tags": ["循环", "控制流"],
        "stem": "range(2, 10, 3) 会依次产生哪些整数？请说明三个参数各自的含义，并解释为什么最后一个产生的数不是 10。",
        "answer": "range(2, 10, 3) 依次产生 2、5、8 三个整数。三个参数分别是起点（包含，从 2 开始）、终点（不包含，到 10 之前截止）和步长（每次加 3）。2、5、8 都小于 10 所以被保留，下一个数 11 已经超过终点 10，因此停止；终点 10 本身是开区间，永远不会出现。",
        "explanation": "该题考察 range 的左闭右开语义与步长概念。最典型的易错点是认为列表里会包含终点值 10，或把第三个参数误当成“元素个数”。可对照 list(range(2, 10, 3)) 得到 [2, 5, 8] 验证。",
    },
    {
        "slug": "py-short-03",
        "type": "short",
        "difficulty": 2,
        "knowledge_tags": ["循环", "控制流"],
        "stem": "在循环中 break 和 continue 有什么区别？请各举一个适合使用它们的场景。",
        "answer": "break 会立即终止整个当前循环，程序跳到循环体之后的语句继续执行；continue 只结束本轮迭代，跳过循环体中它后面的语句，直接进入下一轮循环。适合 break 的场景：在列表中逐个查找某个目标，一旦找到就提前退出循环；适合 continue 的场景：统计一批分数时，遇到负数（无效数据）就跳过本轮、不做统计，继续检查下一个数。",
        "explanation": "该题考察两个循环控制关键字的作用范围差异：break 作用于“整个循环”，continue 只作用于“本轮迭代”。常见易错点是误以为 continue 会退出循环，或以为 break 只是跳过当前元素。",
    },
    {
        "slug": "py-short-04",
        "type": "short",
        "difficulty": 3,
        "knowledge_tags": ["数据类型"],
        "stem": "什么是 Python 中的可变类型与不可变类型？请各举两个例子，并解释为什么字符串可以作为字典的键而列表不行。",
        "answer": "可变对象创建后可以在原地修改其内容（如 append、改元素），不可变对象一旦创建内容就不能变，任何“修改”实际上都是生成了一个新对象。可变类型的例子有列表、字典，不可变类型的例子有整数、字符串、元组。字典的键必须是可哈希的，字符串这类不可变类型的哈希值稳定所以能当键；列表可变、内容变了哈希值就无法保证，Python 规定它不可哈希，因此不能当键。另外像 s = s + '!' 看似“改了”字符串，其实是创建了新字符串再重新绑定。",
        "explanation": "该题考察可变/不可变的本质区别及其与字典键的关系。易错点有二：一是把“变量重新赋值”当成“对象被修改”；二是只背结论“字符串能当键”，说不出背后的可哈希/内容不变原因。",
    },
    {
        "slug": "py-short-05",
        "type": "short",
        "difficulty": 3,
        "knowledge_tags": ["切片", "字符串"],
        "stem": "已知 s = \"Python\"，切片 s[1:4] 和 s[:3] 的结果分别是什么？Python 的切片为什么要设计成“左闭右开”？",
        "answer": "s[1:4] 的结果是 \"yth\"，s[:3] 的结果是 \"Pyt\"。左闭右开表示切片包含起始下标、不包含结束下标，所以 s[1:4] 实际取下标 1、2、3 的字符。这样设计的好处是切片长度恰好等于 j - i（如 s[1:4] 长度为 3），并且 s[:i] 与 s[i:] 能在下标 i 处无缝拼接、不重不漏，遍历和分段处理序列时更方便。",
        "explanation": "该题考察切片下标的取用规则和左闭右开的设计动机。常见易错点是把结束下标对应的字符也算进去（答成 \"ytho\"），或忘记 s[:3] 中省略的起点默认为 0。",
    },
    {
        "slug": "py-short-06",
        "type": "short",
        "difficulty": 3,
        "knowledge_tags": ["函数", "变量与赋值"],
        "stem": (
            "阅读下面的代码，运行时会发生什么？请说明原因，并给出一种正确的改法。\n"
            "\n"
            "x = 10\n"
            "def add_one():\n"
            "    x = x + 1\n"
            "    return x\n"
            "print(add_one())"
        ),
        "answer": "运行不会输出 11，而是在函数内 x = x + 1 这一行抛出 UnboundLocalError（局部变量 x 在赋值前被引用）。原因是 Python 在编译函数时就确定作用域：函数体内对 x 有赋值，x 就被整体视为局部变量，于是等号右边读取的是尚未赋值的局部 x，而不是外面的全局 x。正确改法是在函数开头写 global x 声明使用全局变量，或者更推荐用参数传入、用返回值传出：def add_one(v): return v + 1，避免函数内部直接改写全局状态。",
        "explanation": "该题考察局部与全局作用域的判定规则这一高频易错点：函数里只要出现过对某名字的赋值，该名字在整个函数内都算局部变量，哪怕读取发生在赋值之前。注意“只读全局变量”是完全合法的，报错的关键在于“先读后赋”——对局部 x 的读取发生在对它赋值之前。",
    },
    {
        "slug": "py-short-07",
        "type": "short",
        "difficulty": 4,
        "knowledge_tags": ["推导式", "循环"],
        "stem": "推导式（如列表推导式）写起来比普通 for 循环更简洁，但并不是所有场合都该用它。请说出至少两种应当改用普通 for 循环的情形，并说明推导式在语法上有哪些“做不到”的限制。",
        "answer": "至少两种应改用普通循环的情形：一是循环体需要执行多个动作或产生副作用（例如逐个打印、边遍历边累加多个不同的结果、记录日志），推导式只能承载单个表达式；二是逻辑里包含多层嵌套条件或需要提前中止（如找到目标就退出），推导式不支持 break/continue，硬写成链式条件也会难以阅读。语法上的限制是：推导式的主体必须是一个表达式而不是语句，不能写赋值或多行逻辑，也不含循环中止控制。因此推导式最适合“对序列做一步转换或过滤、生成一个新列表”这类场景，超出这个范围就应回归普通循环以保证可读。",
        "explanation": "该题考察推导式与循环的取舍判断，核心标准是“是否只是单表达式的映射/过滤”。易错点是把推导式当成越短越好的炫技工具，在需要多步骤逻辑或提前退出时也强行套用，反而牺牲可读性甚至无法实现。",
    },
    {
        "slug": "py-short-08",
        "type": "short",
        "difficulty": 4,
        "knowledge_tags": ["异常处理"],
        "stem": "有些程序为了“防止崩溃”，把所有代码都塞进 try 并用不带类型的 except: 后只写一句 pass。请从异常处理意义的角度说明这种做法错在哪里，并给出你认为正确的写法要点。",
        "answer": "这种做法的错误在于：不带类型的 except 会捕获一切异常（包括本不该由这段代码处理的拼写错误、除零等程序缺陷），pass 又把信息彻底吞掉，程序表面不崩溃、实际带着错误状态继续运行或静默失败，出问题时既无提示也难以定位。正确的要点是：try 只包住真正可能出错的一小段代码；except 按类型分别捕获可预期的异常（如 ValueError、KeyError），针对每种异常给出明确处理，比如提示用户重新输入或退回默认值；确实必须执行的收尾清理放在 finally 里；无法处理的异常应当放行或记录日志而不是吞掉。异常处理的真正意义是让程序在可预料的意外面前有恢复的机会，而不是掩盖所有错误。",
        "explanation": "该题考察异常处理的设计意图这一综合运用点：精确捕获、分级处理、及时暴露不可处理的错误。易错点是把 try/except 理解成“防崩保险丝”而滥用宽泛捕获，混淆“处理已知错误”与“隐藏未知 bug”的界限。",
    },
    {
        "slug": "py-coding-01",
        "type": "coding",
        "difficulty": 2,
        "knowledge_tags": ["循环", "运算符"],
        "stem": "读入一行，包含一个正整数 n，输出从 1 到 n（含 n）之间所有偶数的和。如果范围内没有偶数（例如 n=1），输出 0。",
        "answer": {
            "language": "python",
            "solution": (
                "n = int(input())\n"
                "total = 0\n"
                "for i in range(1, n + 1):\n"
                "    if i % 2 == 0:\n"
                "        total += i\n"
                "print(total)"
            ),
        },
        "test_cases": {
            "cases": [
                {
                    "expected_stdout": "30",
                    "stdin": "10\n",
                },
                {
                    "expected_stdout": "12",
                    "stdin": "7\n",
                },
                {
                    "expected_stdout": "0",
                    "stdin": "1\n",
                },
            ],
            "language": "python",
        },
        "explanation": "用 for 遍历 1 到 n（注意 range(1, n + 1) 右端要加 1 才能取到 n），再用 i % 2 == 0 筛出偶数累加。两个易错点：一是 range 的上界写成 n 会漏掉 n 本身；二是忘记 n=1 时区间内没有偶数，累加器初值 0 直接输出 0。",
    },
    {
        "slug": "py-coding-02",
        "type": "coding",
        "difficulty": 3,
        "knowledge_tags": ["字符串", "循环"],
        "stem": "读入一行字符串（可能包含空格与大小写混合的字母），统计其中元音字母的个数并输出。规则：a、e、i、o、u 五个字母无论大小写都算元音，字母 y 不算元音，其他字符一律不计。",
        "answer": {
            "language": "python",
            "solution": (
                "s = input()\n"
                "count = 0\n"
                "for ch in s.lower():\n"
                "    if ch in \"aeiou\":\n"
                "        count += 1\n"
                "print(count)"
            ),
        },
        "test_cases": {
            "cases": [
                {
                    "expected_stdout": "3",
                    "stdin": "Hello World\n",
                },
                {
                    "expected_stdout": "0",
                    "stdin": "xyz\n",
                },
                {
                    "expected_stdout": "6",
                    "stdin": "AEIOU a\n",
                },
            ],
            "language": "python",
        },
        "explanation": "先对整个字符串调用 lower() 把大写统一成小写，再逐字符判断是否属于 aeiou，避免写成 ch in \"aeiouAEIOU\" 漏掉某个大小写分支。易错点有二：一是忘记 lower() 导致大写元音不计数；二是把 y 也当成元音——按规则 y 不算。",
    },
    {
        "slug": "py-coding-03",
        "type": "coding",
        "difficulty": 3,
        "knowledge_tags": ["列表"],
        "stem": "一行中若干个整数，用半角空格分隔（至少 2 个，其中至少包含 2 个不同的值）。把这行整数去掉重复后，输出剩余数字中第二大的数。",
        "answer": {
            "language": "python",
            "solution": (
                "nums = input().split()\n"
                "unique = []\n"
                "for x in nums:\n"
                "    v = int(x)\n"
                "    if v not in unique:\n"
                "        unique.append(v)\n"
                "unique.sort()\n"
                "print(unique[-2])"
            ),
        },
        "test_cases": {
            "cases": [
                {
                    "expected_stdout": "4",
                    "stdin": "1 2 3 4 5\n",
                },
                {
                    "expected_stdout": "3",
                    "stdin": "5 5 3 3 1\n",
                },
                {
                    "expected_stdout": "0",
                    "stdin": "-1 0 -1 0 2\n",
                },
            ],
            "language": "python",
        },
        "explanation": "先用 split() 按空格拆成字符串列表，逐个转成 int 并手动去重（判断 not in 后再 append），排序后取倒数第二个元素。易错点：不去重直接排序会让 5 5 3 3 1 输出 5；另外列表不能混着字符串比较，必须全部转成 int 再排序，否则 \"10\" 会排在 \"9\" 前面。",
    },
    {
        "slug": "py-coding-04",
        "type": "coding",
        "difficulty": 3,
        "knowledge_tags": ["控制流", "运算符"],
        "stem": "读入一行，包含用空格分隔的两个整数：年份 year 和月份 month（month 保证在 1 到 12 之间）。输出该年该月的天数。闰年规则：能被 4 整除且不能被 100 整除的年份是闰年，或者能被 400 整除的年份也是闰年；闰年的 2 月为 29 天，否则 2 月为 28 天；1、3、5、7、8、10、12 月为 31 天，其余月份为 30 天。",
        "answer": {
            "language": "python",
            "solution": (
                "y, m = map(int, input().split())\n"
                "if m in (1, 3, 5, 7, 8, 10, 12):\n"
                "    days = 31\n"
                "elif m in (4, 6, 9, 11):\n"
                "    days = 30\n"
                "elif (y % 4 == 0 and y % 100 != 0) or y % 400 == 0:\n"
                "    days = 29\n"
                "else:\n"
                "    days = 28\n"
                "print(days)"
            ),
        },
        "test_cases": {
            "cases": [
                {
                    "expected_stdout": "29",
                    "stdin": "2024 2\n",
                },
                {
                    "expected_stdout": "28",
                    "stdin": "1900 2\n",
                },
                {
                    "expected_stdout": "29",
                    "stdin": "2000 2\n",
                },
                {
                    "expected_stdout": "30",
                    "stdin": "2023 4\n",
                },
            ],
            "language": "python",
        },
        "explanation": "先用 m in (1,3,5,7,8,10,12) 判大月 31 天，小月 30 天，最后才对二月套闰年规则。闰年条件是 (能被 4 整除且不能被 100 整除) 或 能被 400 整除，括号不能省。最典型易错点：1900 能被 4 和 100 整除但不能被 400 整除，是平年（二月 28 天）；2000 能被 400 整除，是闰年。",
    },
    {
        "slug": "py-coding-05",
        "type": "coding",
        "difficulty": 4,
        "knowledge_tags": ["字典", "字符串"],
        "stem": "第一行是一个正整数 n；接下来 n 行，每行一个由小写字母组成的单词。统计每个单词出现的次数，输出出现次数最多的单词；如果有多个单词并列最高次数，输出其中字典序最小的那个。",
        "answer": {
            "language": "python",
            "solution": (
                "n = int(input())\n"
                "counts = {}\n"
                "for i in range(n):\n"
                "    w = input()\n"
                "    counts[w] = counts.get(w, 0) + 1\n"
                "best = max(counts.values())\n"
                "answer = \"\"\n"
                "for w in counts:\n"
                "    if counts[w] == best:\n"
                "        if answer == \"\" or w < answer:\n"
                "            answer = w\n"
                "print(answer)"
            ),
        },
        "test_cases": {
            "cases": [
                {
                    "expected_stdout": "apple",
                    "stdin": (
                        "5\n"
                        "apple\n"
                        "banana\n"
                        "apple\n"
                        "cherry\n"
                        "banana\n"
                        ""
                    ),
                },
                {
                    "expected_stdout": "cat",
                    "stdin": (
                        "4\n"
                        "cat\n"
                        "dog\n"
                        "cat\n"
                        "dog\n"
                        ""
                    ),
                },
                {
                    "expected_stdout": "hi",
                    "stdin": (
                        "1\n"
                        "hi\n"
                        ""
                    ),
                },
            ],
            "language": "python",
        },
        "explanation": "用字典配合 get(w, 0) + 1 累计词频，再取 max(counts.values()) 得到最高次数，最后在所有并列最高的词中用字符串的 < 比较选出字典序最小者。易错点：一是直接用 max(counts) 会比较出字典序最大的词而不是出现最多的词；二是并列时必须额外做字典序筛选，否则 cat/dog 各出现两次时输出不确定。",
    },
    {
        "slug": "py-coding-06",
        "type": "coding",
        "difficulty": 4,
        "knowledge_tags": ["切片", "字符串"],
        "stem": "第一行是一个字符串 s（长度至少为 1，由小写字母和数字组成）；第二行是一个非负整数 k。对 s 做右旋转：把 s 的最后 k 个字符整体移到其余字符之前，输出旋转后的字符串。若 k 大于 s 的长度，先把 k 对 s 的长度取余再旋转；若 k 为 0，输出原字符串。",
        "answer": {
            "language": "python",
            "solution": (
                "s = input()\n"
                "k = int(input())\n"
                "k = k % len(s)\n"
                "print(s[-k:] + s[:-k])"
            ),
        },
        "test_cases": {
            "cases": [
                {
                    "expected_stdout": "efabcd",
                    "stdin": (
                        "abcdef\n"
                        "2\n"
                        ""
                    ),
                },
                {
                    "expected_stdout": "abc",
                    "stdin": (
                        "abc\n"
                        "6\n"
                        ""
                    ),
                },
                {
                    "expected_stdout": "a",
                    "stdin": (
                        "a\n"
                        "0\n"
                        ""
                    ),
                },
            ],
            "language": "python",
        },
        "explanation": "核心是 s[-k:] + s[:-k] 两段切片拼接：后 k 个字符挪到前面。k 先对长度取模解决 k 超过字符串长度的情况；k=0 时 s[-0:] 等于 s[0:] 即整串、s[:-0] 是空串，拼接结果恰好是原串，天然覆盖边界。易错点：一是忘记取模——k 超过长度时切片不会报错，而是静默返回整串或空串，例如 abcdef 旋转 8 位正确答案是 efabcd，不取模会输出 abcdef；二是误用字符串下标逐个移动，既低效又容易写错。",
    },
    {
        "slug": "py-coding-07",
        "type": "coding",
        "difficulty": 5,
        "knowledge_tags": ["异常处理", "控制流"],
        "stem": "第一行是一个正整数 n；接下来 n 行，每行本应包含用半角空格分隔的两个整数 a 和 b，表示计算 a 除以 b 的商，以浮点数形式保留 2 位小数输出。错误处理规则：如果某一行不能解析为恰好两个整数（字段个数不是 2，或字段含非整数内容），该行输出 input error；如果解析出了两个整数但 b 为 0，该行输出 div error。每行输出恰好一行结果，程序保证能读到 n 行。",
        "answer": {
            "language": "python",
            "solution": (
                "n = int(input())\n"
                "for i in range(n):\n"
                "    line = input()\n"
                "    parts = line.split()\n"
                "    if len(parts) != 2:\n"
                "        print(\"input error\")\n"
                "        continue\n"
                "    try:\n"
                "        a = int(parts[0])\n"
                "        b = int(parts[1])\n"
                "    except ValueError:\n"
                "        print(\"input error\")\n"
                "        continue\n"
                "    try:\n"
                "        print(f\"{a / b:.2f}\")\n"
                "    except ZeroDivisionError:\n"
                "        print(\"div error\")"
            ),
        },
        "test_cases": {
            "cases": [
                {
                    "expected_stdout": (
                        "3.33\n"
                        "div error\n"
                        "input error"
                    ),
                    "stdin": (
                        "3\n"
                        "10 3\n"
                        "8 0\n"
                        "hello 2\n"
                        ""
                    ),
                },
                {
                    "expected_stdout": (
                        "-3.50\n"
                        "2.00"
                    ),
                    "stdin": (
                        "2\n"
                        "-7 2\n"
                        "6 3\n"
                        ""
                    ),
                },
                {
                    "expected_stdout": "0.50",
                    "stdin": (
                        "1\n"
                        "1 2\n"
                        ""
                    ),
                },
                {
                    "expected_stdout": (
                        "input error\n"
                        "input error"
                    ),
                    "stdin": (
                        "2\n"
                        "5\n"
                        "1 2 3\n"
                        ""
                    ),
                },
            ],
            "language": "python",
        },
        "explanation": "需要分层设计错误处理：字段个数不对或整数转换抛 ValueError 都归为 input error，成功解析出两整数后 a/b 抛 ZeroDivisionError 才归为 div error，except 之后用 continue 保证后续行继续处理。输出用 f\"{a / b:.2f}\" 保留两位小数，注意 2.0 也会输出成 2.00。最典型易错点：把除零检查放在 int 转换之前，或漏掉字段多于两个的情况（本题规定必须恰好两个数才算合法）。",
    },
    {
        "slug": "py-coding-08",
        "type": "coding",
        "difficulty": 5,
        "knowledge_tags": ["函数", "推导式"],
        "stem": "第一行是一个正整数 n。要求定义一个函数 is_prime(x) 判断 x 是否为素数（素数是大于 1 且只能被 1 和自身整除的整数，函数体内用循环实现判断），再利用列表推导式计算 2 到 n（含 n）之间所有素数的平方和并输出；若该范围内没有素数，输出 0。",
        "answer": {
            "language": "python",
            "solution": (
                "def is_prime(x):\n"
                "    if x < 2:\n"
                "        return False\n"
                "    for i in range(2, x):\n"
                "        if x % i == 0:\n"
                "            return False\n"
                "    return True\n"
                "\n"
                "n = int(input())\n"
                "total = sum([i * i for i in range(2, n + 1) if is_prime(i)])\n"
                "print(total)"
            ),
        },
        "test_cases": {
            "cases": [
                {
                    "expected_stdout": "87",
                    "stdin": "10\n",
                },
                {
                    "expected_stdout": "4",
                    "stdin": "2\n",
                },
                {
                    "expected_stdout": "0",
                    "stdin": "1\n",
                },
                {
                    "expected_stdout": "1027",
                    "stdin": "20\n",
                },
            ],
            "language": "python",
        },
        "explanation": "需要自己设计 is_prime 函数：x 小于 2 直接返回 False，否则用循环试除 2 到 x-1，任何一个整除就说明不是素数。主流程用带 if 过滤条件的列表推导式 [i*i for i in range(2, n+1) if is_prime(i)] 一次完成筛选与平方。易错点：一是把 1 当素数（range 从 2 开始且函数里 x<2 拦截）；二是 n=1 时 range(2,2) 为空，sum 的空列表结果是 0，正好符合输出 0 的要求。",
    },
]


def exercise_id_for(slug: str) -> str:
    """slug → 确定性主键。同一 slug 在任何机器、任何一次运行都得到同一 id。"""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{SLUG_URN_PREFIX}{slug}"))


def seedable(rows: list[dict]) -> list[dict]:
    """校验每条数据的形状，返回原列表（脏数据抛 `ValueError` 并点名 slug）。"""
    for item in rows:
        problems = check_exercise_shape(
            type=item["type"],
            options=item.get("options"),
            answer=item.get("answer"),
            test_cases=item.get("test_cases"),
        )
        if problems:
            raise ValueError(f"习题种子 {item.get('slug')} 不合法：{'；'.join(problems)}")
    return rows


async def seed_exercises(session: AsyncSession) -> int:
    """写入尚不存在的习题种子；返回本次新建条数。"""
    created = 0
    for item in seedable(EXERCISES):
        row_id = exercise_id_for(item["slug"])
        if await session.get(Exercise, row_id) is not None:
            continue
        session.add(
            Exercise(
                id=row_id,
                type=item["type"],
                stem=item["stem"],
                options=item.get("options"),
                answer=item["answer"],
                test_cases=item.get("test_cases"),
                explanation=item.get("explanation", ""),
                knowledge_tags=item.get("knowledge_tags", []),
                difficulty=item["difficulty"],
                source=SOURCE_SEED,
                # 种子即发布：spec §11 要求 P5 交付可演示题库，无需后台再点一次发布
                status=STATUS_PUBLISHED,
            )
        )
        created += 1
    return created
